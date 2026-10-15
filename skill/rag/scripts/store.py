#!/usr/bin/env python3
"""索引存取层: PostgreSQL(pgvector) 后端。

为什么要它: 老的 JSON 索引是全量读进内存(numpy 暴力检索), 到几十万块就撑不住
(载入几十秒 + 常驻 GB 级内存)。PG 后端把向量留在库里, 检索走 pgvector 的 HNSW 索引,
进程内存与索引大小无关。

后端在 resources/embed.json 的 store 段选; 连接串从环境变量读(密钥不落盘)。
默认走 Unix socket: PG 18 本机这条路的认证最省事, 也最安全。

★ psycopg 3.3 的 execute() 只收 LiteralString, 动态 SQL 一律用 psycopg.sql 包装
  (表名走 sql.Identifier, 类型维度走 sql.Literal) —— 既是防注入, 也是类型检查的要求。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, cast

import psycopg
from psycopg import sql

# ============================================================
# 配置
# ============================================================

def store_config(config: dict[str, Any]) -> dict[str, Any]:
    """取 store 段, 缺省当 json 后端(向后兼容)."""
    section = config.get("store")
    if not isinstance(section, dict):
        return {"backend": "json"}
    return cast(dict[str, Any], section)


def is_pg(config: dict[str, Any]) -> bool:
    """这一套配置是不是走 PG 后端."""
    return str(store_config(config).get("backend", "json")).lower() == "pg"


def _pg_section(config: dict[str, Any]) -> dict[str, Any]:
    section = store_config(config).get("pg")
    return cast(dict[str, Any], section) if isinstance(section, dict) else {}


def table_name(config: dict[str, Any]) -> str:
    """表名(白名单校验, 防注入到 SQL 里)."""
    name = str(_pg_section(config).get("table", "rag_chunks"))
    if not name.replace("_", "").isalnum():
        raise ValueError(f"表名不合法: {name}")
    return name


_env_done = False


def _ensure_env() -> None:
    """从项目根 .env 补 PG 连接串等变量(幂等).

    连接串只走环境变量(密钥不落代码), 但调用方不必各自 load_dotenv —— 那正是
    各入口容易漏、漏了就"库读不到"的坑。
    """
    global _env_done
    if _env_done:
        return
    _env_done = True
    if os.getenv("RAG_PG_DSN"):
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    root = Path(__file__).resolve().parents[3]      # skill/rag/scripts -> 项目根
    load_dotenv(root / ".env")


def connect(config: dict[str, Any]) -> psycopg.Connection[Any]:
    """按 .env 里的 DSN 连库.

    ★ 连不上要等一等再试: PG 会被重启(systemd 拉、断电恢复), 那一两秒里 cron 的清洗
      正好撞上就整个崩掉 —— 日志里留一堆 traceback, 把真正要看的东西盖住(2026-10-08
      就是这么被误看成"清洗一直在报错")。等几秒多数就过去了, 真等不到才抛。
    """
    _ensure_env()
    section = _pg_section(config)
    env_key = str(section.get("dsn_env", "RAG_PG_DSN"))
    dsn = os.getenv(env_key, "")
    if not dsn:
        raise RuntimeError(f"环境缺 {env_key} (PG 连接串); 写进项目根 .env")

    last: psycopg.OperationalError | None = None
    for attempt in range(3):
        try:
            return psycopg.connect(dsn, autocommit=True)
        except psycopg.OperationalError as err:
            last = err
            if attempt < 2:
                time.sleep(2.0 * (attempt + 1))     # 等 2s, 再等 4s
    if last is not None:
        raise last
    raise RuntimeError("连不上 PG, 且没有拿到具体错误")   # 理论上到不了


# ============================================================
# 建表
# ============================================================

def _identifier(config: dict[str, Any]) -> sql.Identifier:
    return sql.Identifier(table_name(config))


def ensure_schema(conn: psycopg.Connection[Any], config: dict[str, Any], dim: int) -> None:
    """建表(幂等) + 三个索引, 向量列维度按实际模型定. psycopg 一次只让发一条语句, 逐条来."""
    table = _identifier(config)
    base = table_name(config)
    conn.execute(
        sql.SQL(
            "CREATE TABLE IF NOT EXISTS {} ("
            " id bigserial PRIMARY KEY,"
            " tier smallint NOT NULL,"
            " idx integer NOT NULL,"
            " hash text NOT NULL,"
            " source text NOT NULL DEFAULT '',"
            " text text NOT NULL,"
            " kind text NOT NULL DEFAULT '',"
            " embedding vector({}),"
            " created_at timestamptz NOT NULL DEFAULT now(),"
            " UNIQUE (tier, hash))"
        ).format(table, sql.Literal(int(dim)))
    )
    conn.execute(sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} (tier)").format(sql.Identifier(f"{base}_tier_idx"), table))
    conn.execute(sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} (source)").format(sql.Identifier(f"{base}_source_idx"), table))
    conn.execute(
        sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} USING hnsw (embedding vector_cosine_ops)")
        .format(sql.Identifier(f"{base}_hnsw"), table)
    )


# ============================================================
# 读写
# ============================================================

def _vec_literal(vector: list[float]) -> str:
    """pgvector 的文本字面量格式: [0.1,0.2,...]."""
    return "[" + ",".join(f"{float(value):.7g}" for value in vector) + "]"


def _ts_or_none(value: Any) -> str | None:
    """时间戳参数: 空串/None 一律给 None -> PG 的 NULL。

    ★ timestamptz 拒收空串(invalid input syntax for type timestamp: ""),
      而调用方很容易用 `or ""` 兜底, 所以在这里再挡一道。
    """
    text = str(value).strip() if value is not None else ""
    return text or None


def _clean_text(value: Any) -> str:
    """正文参数: 剔掉 NUL(0x00) —— PG 的 text 类型明令不收, 带一个就整批落库失败。

    ★ 实测 2026-10-08: Hermes 会话导出里带 NUL(附件/二进制残留), 21560 块算了半个多小时,
      最后 `upsert` 抛 `psycopg.DataError: PostgreSQL text fields cannot contain NUL (0x00) bytes`
      —— 落库在最后一步, 前功尽弃。其它控制字符 PG 都收, 只有 NUL 要剔。
    """
    text = str(value) if value is not None else ""
    return text.replace("\x00", "") if "\x00" in text else text


def load_existing(conn: psycopg.Connection[Any], config: dict[str, Any], tier: str) -> list[dict[str, Any]]:
    """读回这一层的旧条目(hash + 向量 + 源), 供增量复用与累积合并."""
    rows = conn.execute(
        sql.SQL(
            "SELECT idx, hash, source, text, kind, embedding::text,"
            " 对话id, to_char(对话时间, 'YYYY-MM-DD\"T\"HH24:MI:SSOF'), 角色, 来源id"
            " FROM {} WHERE tier = %s ORDER BY idx"
        )
        .format(_identifier(config)),
        (int(tier),),
    ).fetchall()
    items: list[dict[str, Any]] = []
    for idx, chunk_hash, source, text, kind, vector_text, dialog, when, role, refs in rows:
        raw = str(vector_text or "").strip("[]")
        vector = [float(x) for x in raw.split(",")] if raw else []
        items.append({
            "index": int(idx),
            "hash": str(chunk_hash),
            "source": str(source),
            "text": str(text),
            "kind": str(kind or ""),
            "vector": vector,
            "对话id": dialog,
            "对话时间": when,
            "角色": role,
            "来源id": refs,
        })
    return items


def upsert(conn: psycopg.Connection[Any], config: dict[str, Any], tier: str, items: list[dict[str, Any]]) -> int:
    """整层覆盖写: 先删这一层, 再批量插(tier 内自洽, 不会新旧混着).

    ★ 删+插必须在**同一个事务**里. 连接是 autocommit 的, 裸着跑就等于两条独立提交 ——
      中途出错(窗口/磁盘/进程被杀)会把整层删空却没插回去。用显式事务包住,
      要么整层换掉, 要么原样不动。
    """
    table = _identifier(config)
    written = 0
    with conn.transaction():              # autocommit 连接下也是显式 BEGIN/COMMIT
        with conn.cursor() as cur:
            cur.execute(sql.SQL("DELETE FROM {} WHERE tier = %s").format(table), (int(tier),))
            for item in items:
                vector = item.get("vector")
                if not isinstance(vector, list):
                    continue
                cur.execute(
                    sql.SQL(
                        "INSERT INTO {} (tier, idx, hash, source, text, kind, embedding, 对话id, 对话时间, 角色, 来源id)"
                        " VALUES (%s, %s, %s, %s, %s, %s, %s::vector, %s, %s, %s, %s)"
                        " ON CONFLICT (tier, hash) DO UPDATE SET"
                        " idx = EXCLUDED.idx, source = EXCLUDED.source,"
                        " text = EXCLUDED.text, kind = EXCLUDED.kind,"
                        " embedding = EXCLUDED.embedding, 来源id = EXCLUDED.来源id"
                    ).format(table),
                    (int(tier), int(item["index"]), str(item["hash"]), str(item.get("source", "")),
                     _clean_text(item["text"]), str(item.get("kind", "")), _vec_literal(cast(list[float], vector)),
                     item.get("对话id"), item.get("对话时间"), item.get("角色"), item.get("来源id")),
                )
                written += 1
    return written


def append_history(conn: psycopg.Connection[Any], config: dict[str, Any], items: list[dict[str, Any]]) -> int:
    """★ 历史对话层(tier=1)专用: 按 source 先删后插, **不整层清**。

    为什么不能用 upsert: 它是"整层覆盖写"(先 DELETE 整个 tier), 对只增不减的底档等于
    每搬一次就把全部历史清除一遍。这里只动这一批的来源, 别的场次一行不碰。

    删+插同事务 —— 中途出错不会留下"删了没插回去"的半条场次。
    """
    if not items:
        return 0
    table = _identifier(config)
    sources = sorted({str(item.get("source", "")) for item in items})
    written = 0
    with conn.transaction():
        with conn.cursor() as cur:
            if sources:
                cur.execute(
                    sql.SQL("DELETE FROM {} WHERE tier = 1 AND source = ANY(%s)").format(table),
                    (sources,),
                )
            for item in items:
                vector = item.get("vector")
                if not isinstance(vector, list):
                    continue
                cur.execute(
                    sql.SQL(
                        "INSERT INTO {} (tier, idx, hash, source, text, kind, embedding,"
                        " 对话id, 对话时间, 角色) VALUES (%s, %s, %s, %s, %s, %s, %s::vector, %s, %s, %s)"
                        # ★ 同一段内容会换个来源名再来一次(同一次会话既进 hermes-history/ 导出,
                        #   又由 web 存成 q-*.md; 语料重嵌后清洗还会再搬一遍) —— (tier,hash) 是唯一的,
                        #   而"按来源 DELETE"删不掉挂在**别的来源**名下的那一行, 于是 INSERT 撞唯一键,
                        #   整轮清洗直接崩退出(2026-10-10 实测: 历史对话层因此从早停到现在)。
                        #   撞了就按新来源覆盖 —— 跟 upsert 一个口径: 以最新这份语料为准。
                        " ON CONFLICT (tier, hash) DO UPDATE SET"
                        " idx = EXCLUDED.idx, source = EXCLUDED.source,"
                        " text = EXCLUDED.text, kind = EXCLUDED.kind,"
                        " embedding = EXCLUDED.embedding,"
                        " 对话id = EXCLUDED.对话id, 对话时间 = EXCLUDED.对话时间,"
                        " 角色 = EXCLUDED.角色"
                    ).format(table),
                    (1, int(item["index"]), str(item["hash"]), str(item.get("source", "")),
                     _clean_text(item["text"]), str(item.get("kind", "")), _vec_literal(cast(list[float], vector)),
                     item.get("对话id"), _ts_or_none(item.get("对话时间")), item.get("角色")),
                )
                written += 1
    return written


def ids_by_source(conn: psycopg.Connection[Any], config: dict[str, Any]) -> dict[str, str]:
    """tier=1 里按来源聚出 id 列表 —— 经验层挂指针用(逗号分隔)."""
    rows = conn.execute(
        sql.SQL("SELECT source, string_agg(id::text, ',' ORDER BY id) FROM {} WHERE tier = 1 GROUP BY source")
        .format(_identifier(config))
    ).fetchall()
    return {str(source): str(ids) for source, ids in rows if source}


def search(
    conn: psycopg.Connection[Any],
    config: dict[str, Any],
    tier: str,
    query_vector: list[float],
    top_k: int,
) -> list[dict[str, Any]]:
    """余弦近邻检索, 返回与 JSON 后端同形状的结果(不带向量)."""
    literal = _vec_literal(query_vector)
    rows = conn.execute(
        sql.SQL(
            "SELECT idx, hash, source, text, 1 - (embedding <=> %s::vector) AS score"
            " FROM {} WHERE tier = %s AND embedding IS NOT NULL"
            " ORDER BY embedding <=> %s::vector LIMIT %s"
        ).format(_identifier(config)),
        (literal, int(tier), literal, max(int(top_k), 1)),
    ).fetchall()
    results: list[dict[str, Any]] = []
    for rank, (idx, chunk_hash, source, text, score) in enumerate(rows, 1):
        results.append({
            "rank": rank,
            "score": round(float(score), 6),
            "index": int(idx),
            "hash": str(chunk_hash),
            "source": str(source),
            "text": str(text),
        })
    return results


def count(conn: psycopg.Connection[Any], config: dict[str, Any], tier: str) -> int:
    """这一层有多少条."""
    row = conn.execute(
        sql.SQL("SELECT count(*) FROM {} WHERE tier = %s").format(_identifier(config)),
        (int(tier),),
    ).fetchone()
    return int(row[0]) if row else 0


def 概览(conn: psycopg.Connection[Any], config: dict[str, Any]) -> dict[str, Any]:
    """三层各多少条 + 各来源多少条 —— 页面「数据库」节打头那块用。

    ★ 来源按条数倒序: 大会话排前面, 一眼看出"内容压在谁身上"。
    """
    table = _identifier(config)
    层行 = conn.execute(
        sql.SQL("SELECT tier, count(*) FROM {} GROUP BY tier ORDER BY tier").format(table)
    ).fetchall()
    每层 = {int(t): int(n) for t, n in 层行}
    源行 = conn.execute(
        sql.SQL("SELECT source, count(*) FROM {} GROUP BY source ORDER BY count(*) DESC").format(table)
    ).fetchall()
    return {
        "每层": 每层,
        "共": sum(每层.values()),
        "来源": [{"source": str(s), "n": int(n)} for s, n in 源行],
    }


def 翻页(
    conn: psycopg.Connection[Any],
    config: dict[str, Any],
    tier: str,
    偏移: int = 0,
    每页: int = 50,
    关键词: str = "",
    来源: str = "",
) -> dict[str, Any]:
    """表格数据(分页)。不带 embedding —— 1024 维的向量发到浏览器纯属浪费。

    返回 {"行": [...], "共": N, "偏移": x, "每页": y}。过滤条件: tier 必给,
    关键词 = text ILIKE, 来源 = 精确等值(点来源那一栏时用)。
    """
    table = _identifier(config)
    条件 = [sql.SQL("tier = %s")]
    参数: list[Any] = [int(tier)]
    if 关键词.strip():
        条件.append(sql.SQL("text ILIKE %s"))
        参数.append(f"%{关键词.strip()}%")
    if 来源.strip():
        条件.append(sql.SQL("source = %s"))
        参数.append(来源)
    筛选 = sql.SQL(" WHERE ") + sql.SQL(" AND ").join(条件)

    总行 = conn.execute(
        sql.SQL("SELECT count(*) FROM {}").format(table) + 筛选, 参数
    ).fetchone()
    行们 = conn.execute(
        sql.SQL(
            # ★ 时间列与排序(2026-10-10 修): 一律**新的在最上面**。
            #   原来是 `ORDER BY id` 升序 ⇒ 第一页是最老的、新条目全在最后一页,
            #   看着像"历史对话不动了"。
            #   ★ 经验层(tier=3)自己的 `对话时间` 是空的 —— 整层是同一分钟写进去的,
            #   于是 119 页时间全是那个值、看不出正反。它到底是哪次对话长出来的?
            #   顺 `来源id` 指针回历史对话层取那批原文的对话时间(取最晚那条) —— 那才是它的时间。
            "SELECT id, tier, idx, source, kind, text,"
            " to_char(COALESCE(_dt, _st, _ct), 'MM-DD HH24:MI') AS 时间,"
            " CASE WHEN _dt IS NOT NULL THEN '对话'"
            "      WHEN _st IS NOT NULL THEN '源对话'"
            "      ELSE '落库' END AS 时间来源,"
            " 对话id, to_char(对话时间, 'MM-DD HH24:MI'), 角色, 来源id,"
            " to_char(created_at, 'MM-DD HH24:MI')"
            " FROM ("
            "   SELECT r.id, r.tier, r.idx, r.source, r.kind, r.text, r.created_at,"
            "     r.对话时间, r.对话id, r.角色, r.来源id,"
            "     r.对话时间 AS _dt, r.created_at AS _ct,"
            # 经验自己没有对话时间 —— 顺两层兜底找"它是哪次对话里长出来的":
            #   ① 来源id 指针(精确) ② 同源文件在历史对话层里的最晚对话时间(粗一点但覆盖面大)
            #   ★ 只在自己没有对话时间时才算(否则每一页都把 2 万行都算一遍, 白费)
            "     CASE WHEN r.对话时间 IS NOT NULL THEN NULL ELSE COALESCE("
            "       CASE WHEN r.来源id ~ '^[0-9]+(,[0-9]+)*$' THEN ("
            "         SELECT max(h.对话时间) FROM {t} h"
            "         WHERE h.id = ANY(string_to_array(r.来源id, ',')::bigint[])"
            "       ) END,"
            "       CASE WHEN r.source <> '' THEN ("
            "         SELECT max(h2.对话时间) FROM {t} h2"
            "         WHERE h2.tier = 1 AND h2.source = r.source"
            "       ) END"
            "     ) END AS _st"
            "   FROM {t} r"
        ).format(t=table)
        + 筛选
        + sql.SQL(
            # ★ 排序: 先按"有没有真实对话时间"分组 —— 经验层里那些顺出处也找不到时间的,
            #   只剩整层重写时的落库时刻(全层同一个值, 排在最前会把第一页糊成一团),
            #   把它们压到最后; 组内再按时间倒序(新的在上), id 兜底稳定。
            " ) x ORDER BY (CASE WHEN _dt IS NOT NULL OR _st IS NOT NULL THEN 0 ELSE 1 END),"
            " COALESCE(_dt, _st, _ct) DESC, id DESC LIMIT %s OFFSET %s"
        ),
        参数 + [max(int(每页), 1), max(int(偏移), 0)],
    ).fetchall()
    行 = [
        {
            "id": int(i), "tier": int(t), "idx": int(x), "source": str(s), "kind": str(k),
            "text": str(tx), "时间": str(时 or ""), "时间来源": str(源 or ""),
            "落库时间": str(ct or ""), "对话id": str(did or ""),
            "对话时间": str(dt or ""), "角色": str(role or ""), "来源id": str(sid or ""),
        }
        for i, t, x, s, k, tx, 时, 源, did, dt, role, sid, ct in 行们
    ]
    return {"行": 行, "共": int(总行[0]) if 总行 else 0, "偏移": int(偏移), "每页": int(每页)}


def 按词搜(
    conn: psycopg.Connection[Any],
    config: dict[str, Any],
    tier: str,
    词: str,
    数: int = 20,
) -> list[dict[str, Any]]:
    """关键词路(兜底): SQL ILIKE。语义路搜不到时用它取字面命中的。

    ★ 与向量路同形状返回(rank/score/index/hash/source/text), 前端不用分两套渲染。
    score 位置放 0.0 —— 字面命中没有余弦分, 别编一个假的。
    """
    纯 = 词.strip()
    if not 纯:
        return []
    rows = conn.execute(
        sql.SQL(
            "SELECT idx, hash, source, text FROM {}"
            " WHERE tier = %s AND text ILIKE %s ORDER BY id LIMIT %s"
        ).format(_identifier(config)),
        (int(tier), f"%{纯}%", max(int(数), 1)),
    ).fetchall()
    return [
        {"rank": r, "score": 0.0, "index": int(i), "hash": str(h), "source": str(s), "text": str(t)}
        for r, (i, h, s, t) in enumerate(rows, 1)
    ]


# ============================================================
# 一次性搬迁: 老 JSON 索引 -> PG
# ============================================================

def migrate_from_json(config: dict[str, Any], tier: str, json_path: Path) -> int:
    """把老的 JSON 索引灌进 PG. 返回写入条数."""
    if not json_path.is_file():
        raise FileNotFoundError(f"没有可搬迁的 JSON 索引: {json_path}")
    data = json.loads(json_path.read_text(encoding="utf-8"))
    items = [cast(dict[str, Any], x) for x in cast(list[Any], data.get("items", []))]
    dim = len(cast(list[Any], items[0]["vector"])) if items else 0
    with connect(config) as conn:
        ensure_schema(conn, config, dim)
        return upsert(conn, config, tier, items)
