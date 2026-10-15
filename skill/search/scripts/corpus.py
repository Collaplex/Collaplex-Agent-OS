#!/usr/bin/env python3
"""搜索语料的存取层: 热库(只搜这里) + 冷库 + 去重 + TTL + 截图同清 + 体积闸.

为什么分两张表:
  热库 search_hot     刚搜到的结果条目与页面切片放这儿, **检索只查这张**（老板定: 只搜热的）。
                      过了热窗口（默认 24h）就沉到冷库。
  冷库 search_corpus  沉下来的原件（默认留 90 天 / 2GB 封顶）, 只做留存与复用, 不参与检索。
热库不分来源: 谁搜来的只是 site 一列（bing / 百度 / 直连）, 共用一份。

列对着 rag_chunks 来(tier/idx/hash/source/text/kind/embedding/created_at), 搜索这边多几列:
  url / norm(去重键) / title / snippet / site(来源) / query(谁搜的) / kind / shot(截图) /
  status(取页状态码) / hits(被复用几次) / used_at
去重: 规范化地址 + 正文指纹 唯一; 再搜到同一条只刷新 used_at 与次数, 不新增行。
TTL: 热到点沉冷; 冷到点连截图一起清（老板: 截图跟 ttl 一起清）。
体积闸: 单页 5MB / 单次 20MB 由取页那侧拦(fetch.py / serp.py), 落盘 2GB 由 trim_cache() 按 LRU 拦。
闸: 单轮最多 100 次（防模型发疯）, 状态落 cache/budget.json。

★ 复用 rag 的切片与嵌入（chunker / embed）: 所以本件**故意不叫 store.py** ——
  rag 那边有个同名的, 撞名时类型检查与运行时会各认一份。叫 corpus.py 名字唯一,
  `import serp` / `import corpus` 都不会猜错。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, cast

import psycopg
from psycopg import sql

HERE = Path(__file__).resolve().parent                # skill/search/scripts
SKILL_DIR = HERE.parent                               # skill/search
ROOT = HERE.parents[2]                                # 项目根
RAG_DIR = ROOT / "skill" / "rag" / "scripts"          # 复用 rag 的切片与嵌入
if str(RAG_DIR) not in sys.path:
    sys.path.insert(0, str(RAG_DIR))

import chunker  # noqa: E402
import embed  # noqa: E402
import serp  # noqa: E402

CONFIG_PATH = SKILL_DIR / "resources" / "store.json"
COLUMNS = "query, url, norm, title, snippet, site, kind, text, hash, embedding, shot, status, created_at"


# ============================================================
# 配置与连接
# ============================================================

def load_config(path: Path | None = None) -> dict[str, Any]:
    """读落库配置（默认 resources/store.json）."""
    target = path or CONFIG_PATH
    if not target.exists():
        raise RuntimeError(f"缺配置文件: {target}")
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"配置文件不是对象: {target}")
    return cast(dict[str, Any], data)


def store_section(config: dict[str, Any]) -> dict[str, Any]:
    """取 store.pg 段."""
    section = config.get("store")
    if not isinstance(section, dict):
        return {}
    pg = cast(dict[str, Any], section).get("pg")
    return cast(dict[str, Any], pg) if isinstance(pg, dict) else {}


def table(config: dict[str, Any], which: str = "hot") -> sql.Identifier:
    """表名（hot=热库 / corpus=冷库）, 白名单校验防注入."""
    key = "hot_table" if which == "hot" else "corpus_table"
    name = str(store_section(config).get(key, f"search_{which}"))
    if not name.replace("_", "").isalnum():
        raise ValueError(f"表名不合法: {name}")
    return sql.Identifier(name)


def budget_section(config: dict[str, Any]) -> dict[str, Any]:
    section = config.get("budget")
    return cast(dict[str, Any], section) if isinstance(section, dict) else {}


def _ensure_env() -> None:
    """从项目根 .env 补 PG 连接串（密钥不落代码）."""
    if os.getenv("RAG_PG_DSN"):
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(ROOT / ".env")


def connect(config: dict[str, Any]) -> psycopg.Connection[Any]:
    """按 .env 里的 DSN 连库（连不上等几秒再试: PG 重启那两秒别让整个件崩掉）."""
    _ensure_env()
    env_key = str(store_section(config).get("dsn_env", "RAG_PG_DSN"))
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
                time.sleep(2.0 * (attempt + 1))
    if last is not None:
        raise last
    raise RuntimeError("连不上 PG, 且没有拿到具体错误")


# ============================================================
# 建表
# ============================================================

def _table_name(config: dict[str, Any], which: str) -> str:
    key = "hot_table" if which == "hot" else "corpus_table"
    return str(store_section(config).get(key, f"search_{which}"))


def _existing_dim(conn: psycopg.Connection[Any], config: dict[str, Any], which: str) -> int:
    """已有表里 embedding 列的维度（表还没建给 0）. pgvector 把维度存在 typmod 上.

    ★ 查目录别拿表名做 regclass 强转: 表不存在时那一转直接抛 "relation does not exist",
      建表前的一次自检就把整件事卡死了。
    """
    row = conn.execute(
        "SELECT a.atttypmod FROM pg_attribute a"
        " JOIN pg_class c ON c.oid = a.attrelid"
        " JOIN pg_namespace n ON n.oid = c.relnamespace"
        " WHERE n.nspname = current_schema() AND c.relname = %s AND a.attname = 'embedding'",
        (_table_name(config, which),),
    ).fetchone()
    return int(row[0]) if row and int(row[0]) > 0 else 0


def _size_mb(conn: psycopg.Connection[Any], config: dict[str, Any], which: str) -> float:
    """表占多少 MB（表不存在给 0）. 同上, 按名字查目录."""
    row = conn.execute(
        "SELECT COALESCE(pg_total_relation_size(c.oid), 0) FROM pg_class c"
        " JOIN pg_namespace n ON n.oid = c.relnamespace"
        " WHERE n.nspname = current_schema() AND c.relname = %s",
        (_table_name(config, which),),
    ).fetchone()
    return round(float(row[0]) / 1048576, 1) if row else 0.0


def _size_text(conn: psycopg.Connection[Any], config: dict[str, Any], which: str) -> str:
    row = conn.execute(
        "SELECT pg_size_pretty(pg_total_relation_size(c.oid)) FROM pg_class c"
        " JOIN pg_namespace n ON n.oid = c.relnamespace"
        " WHERE n.nspname = current_schema() AND c.relname = %s",
        (_table_name(config, which),),
    ).fetchone()
    return str(row[0]) if row else "0"


def ensure_schema(conn: psycopg.Connection[Any], config: dict[str, Any]) -> int:
    """建两张表 + 索引（幂等）, 返回向量维度. psycopg 一次只让发一条语句, 逐条来."""
    dim = int(config.get("dim", 1024))
    for which in ("hot", "corpus"):
        got = _existing_dim(conn, config, which)
        if got and got != dim:
            raise RuntimeError(
                f"{_table_name(config, which)}.embedding 是 {got} 维, 配置写的是 {dim} 维 —— "
                "换了嵌入模型就得同步改 resources/store.json 的 dim, 并重建这两张表"
            )
    hot = table(config, "hot")
    corpus = table(config, "corpus")
    cols = (
        " query text NOT NULL DEFAULT '',"
        " url text NOT NULL DEFAULT '',"
        " norm text NOT NULL DEFAULT '',"
        " title text NOT NULL DEFAULT '',"
        " snippet text NOT NULL DEFAULT '',"
        " site text NOT NULL DEFAULT '',"
        " kind text NOT NULL DEFAULT 'serp',"
        " text text NOT NULL DEFAULT '',"
        " hash text NOT NULL,"
        " embedding vector({}),"
        " shot text NOT NULL DEFAULT '',"
        " status integer NOT NULL DEFAULT 0,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " UNIQUE (norm, hash)"
    )
    conn.execute(sql.SQL(
        "CREATE TABLE IF NOT EXISTS {} (id bigserial PRIMARY KEY,{}"
        " , hits integer NOT NULL DEFAULT 1, used_at timestamptz NOT NULL DEFAULT now())"
    ).format(hot, sql.SQL(cols).format(sql.Literal(dim))))
    conn.execute(sql.SQL(
        "CREATE TABLE IF NOT EXISTS {} (id bigserial PRIMARY KEY,{}"
        " , sunk_at timestamptz NOT NULL DEFAULT now())"
    ).format(corpus, sql.SQL(cols).format(sql.Literal(dim))))
    for which in ("hot", "corpus"):
        name = _table_name(config, which)
        target = table(config, which)
        # 老表补列(幂等): CREATE TABLE IF NOT EXISTS 不会给已经存在的表加列
        conn.execute(sql.SQL(
            "ALTER TABLE {} ADD COLUMN IF NOT EXISTS status integer NOT NULL DEFAULT 0"
        ).format(target))
        conn.execute(sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} (norm)").format(sql.Identifier(f"{name}_norm_idx"), target))
        conn.execute(sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} (created_at)").format(sql.Identifier(f"{name}_born_idx"), target))
        conn.execute(sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} (site)").format(sql.Identifier(f"{name}_site_idx"), target))
        conn.execute(sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} (kind)").format(sql.Identifier(f"{name}_kind_idx"), target))
        conn.execute(
            sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} USING hnsw (embedding vector_cosine_ops)")
            .format(sql.Identifier(f"{name}_hnsw"), target)
        )
    return dim


# ============================================================
# 写入
# ============================================================

def _vec_literal(vector: list[float]) -> str:
    """pgvector 的文本字面量格式: [0.1,0.2,...]."""
    return "[" + ",".join(f"{float(value):.7g}" for value in vector) + "]"


def _clean(value: Any) -> str:
    """剔 NUL（0x00）: PG 的 text 明令不收, 带一个整批落库就废."""
    text = str(value) if value is not None else ""
    return text.replace("\x00", "") if "\x00" in text else text


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit]


def embed_texts(texts: list[str], config: dict[str, Any]) -> list[list[float]]:
    """调 rag 那套向量接口（带重试）, 按 batch_size 分批, 超长先截."""
    model = embed.resolve_model()
    limit = int(config.get("embed_max_chars", 4000))
    batch = max(1, int(config.get("batch_size", 16)))
    digits = int(config.get("vector_digits", 6))
    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch):
        part = [_clip(_clean(text), limit) or " " for text in texts[start:start + batch]]
        vectors.extend(embed.request_vectors(part, config, model))
    return [[round(float(value), digits) for value in row] for row in vectors]


def _insert(conn: psycopg.Connection[Any], config: dict[str, Any],
            items: list[dict[str, Any]]) -> tuple[int, int]:
    """插一批进热库: 撞唯一键（同地址同指纹）就只刷新 used_at 与次数. 返回 (新增, 复用)."""
    hot = table(config, "hot")
    added = reused = 0
    with conn.transaction():
        with conn.cursor() as cur:
            for item in items:
                raw = item.get("vector")
                if not isinstance(raw, list) or not raw:
                    continue
                vector = [float(value) for value in cast(list[Any], raw)]
                cur.execute(
                    sql.SQL(
                        "INSERT INTO {} (query, url, norm, title, snippet, site, kind, text, hash, embedding, shot, status)"
                        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s, %s)"
                        " ON CONFLICT (norm, hash) DO UPDATE SET used_at = now(), hits = {}.hits + 1"
                        " RETURNING (xmax = 0) AS inserted"
                    ).format(hot, hot),
                    (
                        _clean(item.get("query", "")), _clean(item.get("url", "")), _clean(item.get("norm", "")),
                        _clean(item.get("title", "")), _clean(item.get("snippet", "")), _clean(item.get("site", "")),
                        _clean(item.get("kind", "serp")), _clean(item.get("text", "")), _clean(item.get("hash", "")),
                        _vec_literal(vector), _clean(item.get("shot", "")),
                        int(item.get("status", 0) or 0),
                    ),
                )
                row = cur.fetchone()
                if row and bool(row[0]):
                    added += 1
                else:
                    reused += 1
    return added, reused


def put_serp(conn: psycopg.Connection[Any], config: dict[str, Any], query: str,
             rows: list[dict[str, Any]]) -> tuple[int, int]:
    """搜索结果条目落热库: 每条把 标题 + 摘要 合起来嵌一份向量."""
    items: list[dict[str, Any]] = []
    for row in rows:
        link = str(row.get("url", "")).strip()
        title = str(row.get("title", "")).strip()
        snippet = str(row.get("snippet", "")).strip()
        text = f"{title} {snippet}".strip()
        if not link or not text:
            continue
        items.append({
            "query": query,
            "url": link,
            "norm": serp.norm_url(link),
            "title": title,
            "snippet": snippet,
            "site": str(row.get("来源", "")),
            "kind": "serp",
            "text": text,
            "hash": embed.text_hash(text),
            "shot": str(row.get("shot", "")),
            "status": int(row.get("status", 200) or 200),
        })
    if not items:
        return 0, 0
    for item, vector in zip(items, embed_texts([str(i["text"]) for i in items], config), strict=True):
        item["vector"] = vector
    return _insert(conn, config, items)


def put_page(conn: psycopg.Connection[Any], config: dict[str, Any], query: str,
             page: dict[str, Any]) -> tuple[int, int]:
    """整页正文落热库: 先按 rag 的算法切片（借 chunker）, 再逐块嵌, 一块一行."""
    link = str(page.get("url", "")).strip()
    text = _clean(page.get("text", "")).strip()
    if not link or not text:
        return 0, 0
    size = int(config.get("chunk_size", 800))
    pieces = chunker.split_text(text, size)
    title = str(page.get("title", "")).strip()
    norm = serp.norm_url(link)
    status = int(page.get("status", 0) or 0)
    items: list[dict[str, Any]] = []
    for piece in pieces:
        piece = piece.strip()
        if not piece:
            continue
        items.append({
            "query": query,
            "url": link,
            "norm": norm,
            "title": title,
            "snippet": "",
            "site": str(page.get("来源", "")),
            "kind": "page",
            "text": piece,
            "hash": embed.text_hash(piece),
            "shot": str(page.get("shot", "")),
            "status": status,
        })
    if not items:
        return 0, 0
    for item, vector in zip(items, embed_texts([str(i["text"]) for i in items], config), strict=True):
        item["vector"] = vector
    return _insert(conn, config, items)


# ============================================================
# 检索（只查热库）
# ============================================================

def find(conn: psycopg.Connection[Any], config: dict[str, Any], text: str,
         limit: int = 10, kind: str = "") -> list[dict[str, Any]]:
    """检索**只查热库**, 且只看热窗口内的. 按向量距离排, 顺带把命中行的次数记上."""
    if not text.strip():
        return []
    hot = table(config, "hot")
    vector = _vec_literal(embed_texts([text], config)[0])
    clause = sql.SQL("WHERE created_at > now() - make_interval(hours => %s)")
    params: list[Any] = [int(config.get("hot_hours", 24))]
    if kind:
        clause = clause + sql.SQL(" AND kind = %s")
        params.append(kind)
    rows = conn.execute(
        sql.SQL(
            "SELECT id, query, url, title, snippet, site, kind, text, shot, status, hits,"
            " created_at, used_at, 1 - (embedding <=> %s::vector) AS score"
            " FROM {} {} ORDER BY embedding <=> %s::vector LIMIT %s"
        ).format(hot, clause),
        [vector, *params, vector, max(1, limit)],
    ).fetchall()
    hits: list[dict[str, Any]] = []
    ids: list[int] = []
    for row in rows:
        ids.append(int(row[0]))
        hits.append({
            "id": int(row[0]),
            "query": str(row[1]),
            "url": str(row[2]),
            "title": str(row[3]),
            "snippet": str(row[4]),
            "来源": str(row[5]),
            "kind": str(row[6]),
            "text": str(row[7]),
            "shot": str(row[8]),
            "状态码": int(row[9]),
            "次数": int(row[10]),
            "created_at": str(row[11]),
            "used_at": str(row[12]),
            "相似度": round(float(row[13]), 4),
        })
    if ids:
        with conn.transaction():
            conn.execute(
                sql.SQL("UPDATE {} SET hits = hits + 1, used_at = now() WHERE id = ANY(%s)").format(hot),
                (ids,),
            )
    return hits


# ============================================================
# TTL: 下沉 与 清理
# ============================================================

def sink(conn: psycopg.Connection[Any], config: dict[str, Any]) -> tuple[int, int]:
    """过期的热行沉到冷库（同一事务）: 冷库已有同一条就只把热的那份删掉."""
    hot, corpus = table(config, "hot"), table(config, "corpus")
    hours = int(config.get("hot_hours", 24))
    cols = sql.SQL(COLUMNS)
    moved = dropped = 0
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    "INSERT INTO {} ({}, sunk_at) SELECT {}, now() FROM {}"
                    " WHERE created_at < now() - make_interval(hours => %s)"
                    " ON CONFLICT (norm, hash) DO NOTHING RETURNING 1"
                ).format(corpus, cols, cols, hot),
                (hours,),
            )
            moved = len(cur.fetchall())
            cur.execute(
                sql.SQL("DELETE FROM {} WHERE created_at < now() - make_interval(hours => %s)").format(hot),
                (hours,),
            )
            dropped = max(0, int(cur.rowcount))
    return moved, dropped


def _unlink(paths: list[str], dry: bool) -> int:
    """删截图文件（dry 只数不删）."""
    gone = 0
    for raw in paths:
        path = Path(raw)
        if not path.is_file():
            continue
        gone += 1
        if not dry:
            try:
                path.unlink()
            except OSError:
                gone -= 1
    return gone


def _corpus_mb(conn: psycopg.Connection[Any], config: dict[str, Any]) -> float:
    return _size_mb(conn, config, "corpus")


def clean(conn: psycopg.Connection[Any], config: dict[str, Any], dry: bool = False) -> dict[str, Any]:
    """冷库到点的删掉、截图跟着一起清（老板: 截图跟 ttl 一起清）, 顺带扫没主的截图."""
    corpus = table(config, "corpus")
    days = int(config.get("corpus_days", 90))
    cap = float(config.get("corpus_max_mb", 2048))
    with conn.transaction():
        with conn.cursor() as cur:
            if dry:
                cur.execute(
                    sql.SQL("SELECT shot FROM {} WHERE sunk_at < now() - make_interval(days => %s)").format(corpus),
                    (days,),
                )
                shots = [str(row[0]) for row in cur.fetchall() if row[0]]
                aged = len(shots)
            else:
                cur.execute(
                    sql.SQL("DELETE FROM {} WHERE sunk_at < now() - make_interval(days => %s) RETURNING shot").format(corpus),
                    (days,),
                )
                shots = [str(row[0]) for row in cur.fetchall() if row[0]]
                aged = len(shots)
    trimmed = 0
    size = _corpus_mb(conn, config)
    while size > cap and trimmed < 50000:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("DELETE FROM {} WHERE id IN (SELECT id FROM {} ORDER BY sunk_at LIMIT 500) RETURNING shot")
                    .format(corpus, corpus)
                )
                shots.extend(str(row[0]) for row in cur.fetchall() if row[0])
                got = max(0, int(cur.rowcount))
        if got == 0:
            break
        trimmed += got
        size = _corpus_mb(conn, config)
    orphans = _orphan_shots(conn, config)
    removed = _unlink(shots + orphans, dry)
    return {
        "冷库过期行": aged,
        "超量再删": trimmed,
        "截图删掉": removed,
        "冷库现在MB": size,
        "扫到的孤儿截图": len(orphans),
        "试跑": dry,
    }


def _orphan_shots(conn: psycopg.Connection[Any], config: dict[str, Any]) -> list[str]:
    """扫截图目录: 数据库里没人引的、而且比热窗口还老的, 算孤儿."""
    shot_dir = SKILL_DIR / str(config.get("shot_dir", "cache/shots"))
    if not shot_dir.is_dir():
        return []
    hot, corpus = table(config, "hot"), table(config, "corpus")
    rows = conn.execute(
        sql.SQL("SELECT shot FROM {} WHERE shot <> '' UNION SELECT shot FROM {} WHERE shot <> ''").format(hot, corpus)
    ).fetchall()
    known = {str(row[0]) for row in rows}
    limit = time.time() - float(config.get("hot_hours", 24)) * 3600
    orphans: list[str] = []
    for path in sorted(shot_dir.glob("*")):
        if str(path) in known or not path.is_file():
            continue
        try:
            if path.stat().st_mtime < limit:
                orphans.append(str(path))
        except OSError:
            continue
        if len(orphans) >= 2000:
            break
    return orphans


def _size_of(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _cache_files(config: dict[str, Any]) -> list[Path]:
    """落盘缓存里的文件(html + 截图), 按修改时间从老到新排."""
    folders = [SKILL_DIR / str(config.get("page_dir", "cache/pages")),
               SKILL_DIR / str(config.get("shot_dir", "cache/shots"))]
    items: list[tuple[float, Path]] = []
    for folder in folders:
        if not folder.is_dir():
            continue
        for path in folder.glob("*"):
            if not path.is_file():
                continue
            try:
                items.append((path.stat().st_mtime, path))
            except OSError:
                continue
    items.sort(key=lambda pair: pair[0])
    return [path for _, path in items]


def trim_cache(conn: psycopg.Connection[Any], config: dict[str, Any],
               dry: bool = False) -> dict[str, Any]:
    """落盘 2GB 封顶(LRU): 超了就从最老的开始删.

    ★ 只动 cache/pages(html) 与 cache/shots(截图) —— 都是可重取的加速件, 库里切好的正文不受影响。
      截图被删时顺手把 hot/corpus 里对它的引用抹掉, 免得留一个指不到的死路径。
    """
    cap = float(config.get("disk_max_mb", 2048)) * 1048576
    files = _cache_files(config)
    total = sum(_size_of(path) for path in files)
    if total <= cap:
        return {"落盘现在MB": round(total / 1048576, 1), "缓存删文件": 0, "抹掉引用": 0}
    shot_dir = SKILL_DIR / str(config.get("shot_dir", "cache/shots"))
    victims: list[Path] = []
    for path in files:
        if total <= cap:
            break
        victims.append(path)
        total -= _size_of(path)
    shots = [str(path) for path in victims if path.parent == shot_dir]
    blanked = 0
    if dry:
        removed = len(victims)
    else:
        removed = _unlink([str(path) for path in victims], False)
        if shots:
            with conn.transaction():
                for target in (table(config, "hot"), table(config, "corpus")):
                    cur = conn.execute(
                        sql.SQL("UPDATE {} SET shot = '' WHERE shot = ANY(%s)").format(target),
                        (shots,),
                    )
                    blanked += max(0, int(cur.rowcount))
    return {"落盘现在MB": round(total / 1048576, 1), "缓存删文件": removed, "抹掉引用": blanked}


def tidy(conn: psycopg.Connection[Any], config: dict[str, Any]) -> dict[str, int]:
    """顺手做的日常维护: 过期热行沉冷库 + 冷库到点清（连截图一起清） + 落盘缓存封顶.

    ★ 为什么不做成 cron: 搜索这动作本来就零星, 每次落库顺手做一下够用, 也不违背
      "系统服务不自启/手动控制"的偏好。落到实处的判据还是 TTL 那两行 SQL。
    """
    moved, dropped = sink(conn, config)
    report = clean(conn, config)
    disk = trim_cache(conn, config)
    return {
        "沉冷库": moved,
        "热库清": dropped,
        "冷库清": int(report["冷库过期行"]) + int(report["超量再删"]),
        "截图清": int(report["截图删掉"]),
        "缓存清": int(disk["缓存删文件"]),
    }


# ============================================================
# 单轮次数闸（防模型发疯）
# ============================================================

def budget(config: dict[str, Any], cost: int = 1, peek: bool = False) -> dict[str, Any]:
    """单轮次数闸: 一次搜索算 1 次, 超上限就抛.

    一轮 = 连续动作之间不超过 round_gap_seconds（默认 30 分钟）的那一段;
    停手超过这个间隔就自动开新一轮。状态落 cache/budget.json。
    """
    section = budget_section(config)
    limit = int(section.get("max_per_round", 100))
    gap = float(section.get("round_gap_seconds", 1800))
    path = SKILL_DIR / str(section.get("state", "cache/budget.json"))
    now = time.time()
    state: dict[str, Any] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                state = cast(dict[str, Any], loaded)
        except (OSError, ValueError):
            state = {}
    if now - float(state.get("last", 0.0)) > gap:
        state = {"round": int(state.get("round", 0)) + 1, "count": 0, "last": 0.0}
    count = int(state.get("count", 0))
    if peek:
        return {"轮次": int(state.get("round", 1)), "已用": count, "上限": limit,
                "剩": max(0, limit - count), "窗口秒": int(gap)}
    count += max(1, cost)
    if count > limit:
        raise RuntimeError(
            f"这一轮已经搜了 {count - 1} 次, 到上限 {limit} 就停 —— 这就是防模型钻牛角尖的闸。"
            f" 还想搜: 等 {int(gap // 60)} 分钟自动开新一轮, 或调 resources/store.json 的 budget.max_per_round"
        )
    state["count"] = count
    state["last"] = now
    state["round"] = int(state.get("round", 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"轮次": int(state["round"]), "已用": count, "上限": limit, "剩": limit - count}


# ============================================================
# 概览
# ============================================================

def stats(conn: psycopg.Connection[Any], config: dict[str, Any]) -> dict[str, Any]:
    """一眼看清: 两张表各多少行、多大、热窗口里有多少、什么时候的、落盘缓存多大."""
    hot, corpus = table(config, "hot"), table(config, "corpus")
    hours = int(config.get("hot_hours", 24))
    out: dict[str, Any] = {}
    for which, key, target in (("热库", "hot", hot), ("冷库", "corpus", corpus)):
        row = conn.execute(sql.SQL("SELECT count(*) FROM {}").format(target)).fetchone()
        out[which] = {"行数": int(row[0]) if row else 0, "大小": _size_text(conn, config, key)}
    row = conn.execute(
        sql.SQL("SELECT count(*), count(*) FILTER (WHERE kind = 'page'), count(*) FILTER (WHERE kind = 'serp'),"
                " min(created_at), max(used_at) FROM {} WHERE created_at > now() - make_interval(hours => %s)")
        .format(hot),
        (hours,),
    ).fetchone()
    if row:
        out["热窗口内"] = {"行数": int(row[0]), "页面块": int(row[1]), "结果条目": int(row[2]),
                        "最早": str(row[3]), "最后用过": str(row[4]), "热窗口小时": hours}
    rows = cast(list[tuple[Any, ...]], conn.execute(
        sql.SQL("SELECT site, count(*) FROM {} GROUP BY site ORDER BY 2 DESC").format(hot)
    ).fetchall())
    out["来源分布"] = {str(row[0]) or "(空)": int(row[1]) for row in rows}
    out["落盘缓存"] = {"MB": round(sum(_size_of(path) for path in _cache_files(config)) / 1048576, 1),
                     "文件数": len(_cache_files(config)),
                     "上限MB": float(config.get("disk_max_mb", 2048))}
    out["本轮闸"] = budget(config, peek=True)
    return out


# ============================================================
# 命令行
# ============================================================

def _read_stdin_json() -> Any:
    raw = sys.stdin.read().strip()
    if not raw:
        raise RuntimeError("要从标准输入喂 JSON")
    return json.loads(raw)


def main() -> int:
    ap = argparse.ArgumentParser(description="搜索语料落库: 热库 / 冷库 / 去重 / TTL / 次数闸")
    sub = ap.add_subparsers(dest="action", required=True)
    sub.add_parser("schema", help="建表 + 索引（幂等）")
    p_put = sub.add_parser("put-serp", help="把搜索结果条目落热库（标准输入喂 [{title,url,snippet,来源}]）")
    p_put.add_argument("--query", required=True, help="这次搜的词")
    p_page = sub.add_parser("put-page", help="把整页正文落热库（标准输入喂 {url,title,text,来源}）")
    p_page.add_argument("--query", default="", help="这次搜的词")
    p_find = sub.add_parser("find", help="检索（只查热库）")
    p_find.add_argument("text")
    p_find.add_argument("-n", type=int, default=10, help="要几条")
    p_find.add_argument("--kind", choices=("serp", "page"), default="", help="只要结果条目或只要页面块")
    p_find.add_argument("--json", action="store_true", help="出 JSON")
    sub.add_parser("sink", help="过期的热行沉到冷库")
    p_clean = sub.add_parser("clean", help="冷库过期/超量的删掉 + 落盘缓存封顶, 截图跟着一起清")
    p_clean.add_argument("--dry", action="store_true", help="只数不删")
    p_stats = sub.add_parser("stats", help="两表行数/大小/来源/落盘/闸")
    p_stats.add_argument("--json", action="store_true", help="出 JSON")
    p_budget = sub.add_parser("budget", help="看本轮还剩几次（--take 真扣一次）")
    p_budget.add_argument("--take", action="store_true", help="扣一次（到上限会报错）")
    p_budget.add_argument("--json", action="store_true", help="出 JSON")
    args = ap.parse_args()

    config = load_config()
    try:
        if args.action == "budget":
            info = budget(config, peek=not bool(args.take))
            print(json.dumps(info, ensure_ascii=False) if args.json
                  else f"第 {info['轮次']} 轮: 已用 {info['已用']} / {info['上限']}, 还剩 {info['剩']}")
            return 0

        if args.action == "schema":
            with connect(config) as conn:
                dim = ensure_schema(conn, config)
            print(f"建好了: {_table_name(config, 'hot')} / {_table_name(config, 'corpus')}（向量 {dim} 维）")
            return 0

        with connect(config) as conn:
            if args.action == "put-serp":
                rows = _read_stdin_json()
                if not isinstance(rows, list):
                    raise RuntimeError("put-serp 要一个数组")
                added, reused = put_serp(conn, config, str(args.query),
                                        [cast(dict[str, Any], one) for one in cast(list[Any], rows)])
                print(f"结果条目: 新增 {added} 条, 撞车复用 {reused} 条")
                return 0
            if args.action == "put-page":
                page = _read_stdin_json()
                if not isinstance(page, dict):
                    raise RuntimeError("put-page 要一个对象")
                added, reused = put_page(conn, config, str(args.query), cast(dict[str, Any], page))
                print(f"页面块: 新增 {added} 块, 撞车复用 {reused} 块")
                return 0
            if args.action == "find":
                hits = find(conn, config, str(args.text), int(args.n), str(args.kind))
                if args.json:
                    print(json.dumps(hits, ensure_ascii=False, indent=2))
                    return 0 if hits else 1
                print(f"热库里找到 {len(hits)} 条（只查热的, 只看热窗口内）")
                for hit in hits:
                    print(f"\n{hit['相似度']:.3f}  [{hit['来源']} / {hit['kind']} / HTTP {hit['状态码']}]  {hit['title'][:60]}")
                    print(f"   {hit['url']}")
                    body = hit["text"] if hit["kind"] == "page" else hit["snippet"]
                    print(f"   {str(body)[:200]}")
                return 0 if hits else 1
            if args.action == "sink":
                moved, dropped = sink(conn, config)
                print(f"沉到冷库 {moved} 行, 热库清掉 {dropped} 行")
                return 0
            if args.action == "clean":
                dry = bool(args.dry)
                report = clean(conn, config, dry=dry)
                for key, value in report.items():
                    print(f"  {key}: {value}")
                disk = trim_cache(conn, config, dry=dry)
                for key, value in disk.items():
                    print(f"  {key}: {value}")
                return 0
            if args.action == "stats":
                report = stats(conn, config)
                print(json.dumps(report, ensure_ascii=False, indent=2) if args.json
                      else json.dumps(report, ensure_ascii=False, indent=2))
                return 0
    except (RuntimeError, psycopg.Error, ValueError) as error:
        print(f"[出错] {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
