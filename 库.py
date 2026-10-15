#!/usr/bin/env python3
"""库.py —— 冷库的公用一层：连接 / 文档表 / 执行查询。

两个后端，同一套 API（调用方无需知道底层是哪种）
    pg      PostgreSQL —— 这台开发机在生产用的那份（pgvector 记忆库的邻居）
    sqlite  单文件 SQLite —— Windows / 单机自带一份：零安装、零服务，首次用就把表建好

选哪个
    - 环境变量 `COLLAPLEX_DB_BACKEND` = pg | sqlite，明说优先；
    - 没明说时：配了 `RAG_PG_DSN` 走 pg，否则落 sqlite（文件见 `库文件()`）。

为什么要有 sqlite（2026-10-11）
    打 Windows 包时"全自动安装 + 自带空白数据表"这条硬要求，靠 PG 落不了地：
    它要装服务、要 initdb、pgvector 还得自己编。SQLite 是标准库自带、单文件，
    第一次运行 `create table if not exists` 就是那张空表 —— 装机脚本什么都不必做。

形状对齐
    文档表两边都是 (键 text 主键, 值 json/jsonb, 更新时刻)；sqlite 那份值是 JSON 文本，读写自己转。

沙盒
    环境变量 `COLLAPLEX_DB_PREFIX`，默认空。测试设成 `测试_` 之类，所有表名自动带前缀，
    跑完自己删 —— **测试不许碰生产表**。

文档表（一个键一行、值是一坨 JSON）
    适合"整份表就是一个文档"的用法：读出来是 Python 对象、写回去是整份替换，
    一条 upsert 就是原子的 —— 不需要本地文件那种"先写临时件再换名"。
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any, LiteralString

if TYPE_CHECKING:  # 只为类型检查：真导入放在 pg 分支里，只用 sqlite 的机器不必装 psycopg
    from psycopg import sql

根 = Path(__file__).resolve().parent

_连接缓存: dict[str, Any] = {}
_ENV已载 = False


def _载环境() -> None:
    """把仓根 .env 读进环境（只读一次）；没装 dotenv 也能跑（环境变量直接给）。"""
    global _ENV已载
    if _ENV已载:
        return
    _ENV已载 = True
    try:
        from dotenv import load_dotenv  # noqa: PLC0415  - 没装也能跑

        load_dotenv(根 / ".env")
    except ImportError:
        return


def 后端() -> str:
    """走哪个后端：'pg' 还是 'sqlite'（判定口径见模块头）。"""
    _载环境()
    明说 = os.getenv("COLLAPLEX_DB_BACKEND", "").strip().lower()
    if 明说 in ("pg", "postgres", "postgresql"):
        return "pg"
    if 明说 in ("sqlite", "sqlite3"):
        return "sqlite"
    return "pg" if os.getenv("RAG_PG_DSN", "").strip() else "sqlite"


def 库文件() -> Path:
    """sqlite 那份库落在哪（`COLLAPLEX_DB_FILE` 可覆盖；相对路径按仓根算）。"""
    _载环境()
    明说 = os.getenv("COLLAPLEX_DB_FILE", "").strip()
    if not 明说:
        return 根 / "state" / "collaplex.sqlite"
    路径 = Path(明说).expanduser()
    return 路径 if 路径.is_absolute() else 根 / 路径


def _连PG() -> Any:
    import psycopg  # noqa: PLC0415  - 只有真用 pg 的机器才需要它

    _载环境()
    dsn = os.getenv("RAG_PG_DSN", "").strip()
    if not dsn:
        raise RuntimeError(
            "没配 RAG_PG_DSN —— 定时/编排的账要落冷库，先在 .env 里配（或导出这个环境变量）"
        )
    return psycopg.connect(dsn, autocommit=True)


def _连SQLITE() -> sqlite3.Connection:
    路径 = 库文件()
    路径.parent.mkdir(parents=True, exist_ok=True)
    连 = sqlite3.connect(str(路径), isolation_level=None)  # None = autocommit
    连.execute("pragma journal_mode = wal")
    连.execute("pragma busy_timeout = 5000")
    return 连


def 连接() -> Any:
    """拿一条 autocommit 连接（连过就复用）。pg 认 RAG_PG_DSN，sqlite 认库文件。"""
    哪个 = 后端()
    if 哪个 not in _连接缓存:
        _连接缓存[哪个] = _连PG() if 哪个 == "pg" else _连SQLITE()
    return _连接缓存[哪个]


def 关连接() -> None:
    """把缓存的连接放掉（测试换后端 / 收尾用）。"""
    for 连 in _连接缓存.values():
        关 = getattr(连, "close", None)
        if callable(关):
            try:
                关()
            except Exception:  # noqa: BLE001  - 收尾失败不影响结果
                pass
    _连接缓存.clear()


def 表名(名: str) -> str:
    """给表名挂沙盒前缀（`COLLAPLEX_DB_PREFIX`），平时原样返回。"""
    return os.getenv("COLLAPLEX_DB_PREFIX", "") + 名


def _引号(名: str) -> str:
    """sqlite 里引一个标识符（双引号，内部的双引号翻倍）。"""
    return '"' + 名.replace('"', '""') + '"'


def 文档表(名: str) -> str:
    """建（没有才建）一张文档表，返回真实表名。两边形状都是 (键 / 值 / 更新时刻)。"""
    真名 = 表名(名)
    if 后端() == "pg":
        from psycopg import sql

        with 连接().cursor() as cur:
            cur.execute(
                sql.SQL(
                    "create table if not exists {} ("
                    "键 text primary key, 值 jsonb not null, "
                    "更新时刻 timestamptz not null default now())"
                ).format(sql.Identifier(真名))
            )
    else:
        连接().execute(
            f"create table if not exists {_引号(真名)} ("
            "键 text primary key, 值 text not null, "
            "更新时刻 text not null default (datetime('now')))"
        )
    return 真名


def 读文档(名: str, 键: str) -> Any | None:
    """读一份文档。表不存在 / 键不在 / 值不是对象 —— 一律返回 None，不当异常。"""
    真名 = 表名(名)
    if 后端() == "pg":
        import psycopg
        from psycopg import sql

        try:
            with 连接().cursor() as cur:
                cur.execute(
                    sql.SQL("select 值 from {} where 键 = %s").format(sql.Identifier(真名)),
                    (键,),
                )
                行 = cur.fetchone()
        except psycopg.errors.UndefinedTable:
            return None
    else:
        try:
            行 = 连接().execute(
                f"select 值 from {_引号(真名)} where 键 = ?", (键,)
            ).fetchone()
        except sqlite3.OperationalError:  # 表还没建起来
            return None
    if 行 is None:
        return None
    值 = 行[0]
    if isinstance(值, str):  # sqlite 那份存的是 JSON 文本
        try:
            return json.loads(值)
        except json.JSONDecodeError:
            return None
    return 值


def 写文档(名: str, 键: str, 值: Any) -> None:
    """整份替换那份文档（一条 upsert，原子）。表不在就先建。"""
    真名 = 文档表(名)
    if 后端() == "pg":
        from psycopg import sql
        from psycopg.types.json import Jsonb

        with 连接().cursor() as cur:
            cur.execute(
                sql.SQL(
                    "insert into {} (键, 值, 更新时刻) values (%s, %s, now()) "
                    "on conflict (键) do update set 值 = excluded.值, 更新时刻 = now()"
                ).format(sql.Identifier(真名)),
                (键, Jsonb(值)),
            )
        return
    连接().execute(
        f"insert into {_引号(真名)} (键, 值, 更新时刻) values (?, ?, datetime('now')) "
        "on conflict (键) do update set 值 = excluded.值, 更新时刻 = datetime('now')",
        (键, json.dumps(值, ensure_ascii=False)),
    )


def 删文档(名: str, 键: str) -> int:
    """删一份文档，返回删掉几行（表不在就当 0）。"""
    真名 = 表名(名)
    if 后端() == "pg":
        import psycopg
        from psycopg import sql

        try:
            with 连接().cursor() as cur:
                cur.execute(
                    sql.SQL("delete from {} where 键 = %s").format(sql.Identifier(真名)), (键,)
                )
                return int(cur.rowcount or 0)
        except psycopg.errors.UndefinedTable:
            return 0
    try:
        游标 = 连接().execute(f"delete from {_引号(真名)} where 键 = ?", (键,))
    except sqlite3.OperationalError:
        return 0
    return int(游标.rowcount or 0)


def 全部(名: str) -> list[tuple[Any, Any]]:
    """读一张文档表的全部行 [(键, 值), ...]（表不在就是空表，不抛）。

    ★ 清单「列出本对话所有条目」这类用法走它 —— 不让调用方自行拼 SQL：
      拼 SQL 的地方一多，换后端就得满仓改。
    """
    真名 = 表名(名)
    if 后端() == "pg":
        import psycopg
        from psycopg import sql

        try:
            with 连接().cursor() as cur:
                cur.execute(sql.SQL("select 键, 值 from {}").format(sql.Identifier(真名)))
                return [(行[0], 行[1]) for 行 in cur.fetchall()]
        except psycopg.errors.UndefinedTable:
            return []
    try:
        行们 = 连接().execute(f"select 键, 值 from {_引号(真名)}").fetchall()
    except sqlite3.OperationalError:
        return []
    出: list[tuple[Any, Any]] = []
    for 键, 值 in 行们:
        try:
            值 = json.loads(值) if isinstance(值, str) else 值
        except json.JSONDecodeError:
            值 = None
        出.append((键, 值))
    return 出


def 建表(名: str, 列: LiteralString) -> str:
    """建一张普通行表。列定义必须是代码里硬编码的字面量。"""
    真名 = 表名(名)
    if 后端() == "pg":
        from psycopg import sql

        with 连接().cursor() as cur:
            cur.execute(
                sql.SQL("create table if not exists {} ({})").format(
                    sql.Identifier(真名), sql.SQL(列)
                )
            )
    else:
        连接().execute(f"create table if not exists {_引号(真名)} ({列})")
    return 真名


def 执行(语句: sql.Composed | str, 参数: tuple[Any, ...] = ()) -> None:
    """跑一条写语句（pg 收 psycopg 的 Composed；sqlite 收字符串语句，占位符用 ?）。"""
    if 后端() == "pg":
        with 连接().cursor() as cur:
            cur.execute(语句, 参数)  # type: ignore[arg-type]  - pg 分支里一定是 Composed
        return
    if not isinstance(语句, str):
        raise TypeError("sqlite 后端只收字符串语句（动态表名请走 库.全部 / 库.写文档 这类封装）")
    连接().execute(语句, 参数)


def 查(语句: sql.Composed | str, 参数: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    """跑一条读语句，返回所有行。"""
    if 后端() == "pg":
        with 连接().cursor() as cur:
            cur.execute(语句, 参数)  # type: ignore[arg-type]  - pg 分支里一定是 Composed
            return list(cur.fetchall())
    if not isinstance(语句, str):
        raise TypeError("sqlite 后端只收字符串语句（动态表名请走 库.全部 / 库.读文档 这类封装）")
    return list(连接().execute(语句, 参数).fetchall())


def 删表(名: str) -> None:
    """把表删掉（测试收尾用）。"""
    真名 = 表名(名)
    if 后端() == "pg":
        from psycopg import sql

        with 连接().cursor() as cur:
            cur.execute(sql.SQL("drop table if exists {}").format(sql.Identifier(真名)))
        return
    连接().execute(f"drop table if exists {_引号(真名)}")


def 在不在() -> bool:
    """冷库通不通 —— 连不上返回 False，不抛（自检用）。"""
    try:
        if 后端() == "pg":
            连接().cursor().close()
        else:
            连接().execute("select 1")
        return True
    except Exception:  # noqa: BLE001  - 自检要的是"通不通"，不是异常原文
        return False
