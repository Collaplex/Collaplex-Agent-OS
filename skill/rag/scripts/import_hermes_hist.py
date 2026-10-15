#!/usr/bin/env python3
"""Hermes state.db 的历史对话 -> collaplex 语料 (每会话一个 md 文件). v2

用法:
    .venv/bin/python import_hermes_hist.py <输出目录> [--sessions N] [--tools] [--min-msgs M] [--all]

约定:
    只导 user/assistant 正文; --tools 才带上 tool 输出(占 76% 但多是过程材料).
    每会话一文件, 会话内按时间排序, 供 chunker 切 800 字符块后嵌向量.

v2 修正两处语料污染:
    ① 只导 active=1 的消息 —— Hermes 压缩时把同一内容重复存(active=0 是旧态), 默认剔掉;
    ② 剔掉 Hermes 的内部标记消息([CONTEXT COMPACTION...] / [STILL IN PROGRESS...]) —— 那是框架的话, 不是对话.

v3 再修一处语料污染 (2026-10-09):
    ③ 清掉消息正文里模型的原生工具调用标记 —— DeepSeek 会把 DSML 标记(全角竖线夹 DSML)留在
       content 里, 导出成语料后检索再喂回上下文, 模型看见自己的标记就跟着模仿(污染自我扩散)。
       清洗规则跟 exec/落语料共用同一份: 项目根的 native_marks.py。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, cast

# 项目根的公共清洗层(只放纯正则, 零依赖) —— 语料污染防线就这一份, 别在这儿再抄一遍。
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
import native_marks  # noqa: E402  (得先补 sys.path 才 import 得到)

DB = Path.home() / ".hermes" / "state.db"
# ★ 增量断点/最新文件清单都落项目 state/ —— cron 用它接下一棒(嵌向量)。
#   参数名故意用 ASCII: cron 环境的 locale 是 POSIX, 中文参数名有解码风险。
断点路径 = _ROOT / "state" / "import-断点.json"
最新清单 = _ROOT / "state" / "import-最新.txt"
ROLE_CN = {"user": "用户", "assistant": "助手", "tool": "工具"}
# Hermes 框架注入的标记行, 开头出现就整条跳过
NOISE_PREFIXES = ("[CONTEXT COMPACTION", "[STILL IN PROGRESS", "[REFERENCE ONLY")


def is_noise(content: str) -> bool:
    """是不是 Hermes 框架注入的标记消息(不是真实对话)."""
    head = content.lstrip()[:40]
    return any(head.startswith(prefix) for prefix in NOISE_PREFIXES)


def session_ids(
    cur: sqlite3.Cursor,
    roles: tuple[str, ...],
    min_msgs: int,
    limit: int,
    active_only: bool,
    since: float = 0.0,
    until: float = 1e12,
) -> list[tuple[str, int, float]]:
    """挑会话: 消息数够多, 按最后活动时间倒序 (limit<=0 表示不限)。

    ★ since/until 按**会话最后活动时刻**卡窗口(时间戳是 epoch 浮点):
      since = 上次断点(只要比它新的) —— 增量导, 不把已洗过的会话重新写回语料;
      until = 现在-静默分钟(正在聊的先不导) —— 否则一个会话会被反复导出+嵌向量+清洗。
    """
    ph = ",".join("?" * len(roles))
    active = " AND active = 1" if active_only else ""
    sql = f"""
        SELECT session_id, COUNT(*) AS n, MAX(timestamp) AS last
        FROM messages
        WHERE role IN ({ph}) AND content IS NOT NULL AND TRIM(content) != '' {active}
        GROUP BY session_id
        HAVING n >= ? AND MAX(timestamp) > ? AND MAX(timestamp) <= ?
        ORDER BY last DESC
    """
    params: list[object] = [*roles, min_msgs, since, until]
    if limit > 0:
        sql += " LIMIT ?"
        params.append(limit)
    cur.execute(sql, params)
    return [(str(r[0]), int(r[1]), float(r[2])) for r in cur.fetchall()]


def 读断点() -> float:
    """上次导到哪(epoch 秒)。没有/读坏 = 0.0(那就从头来, 交给人手动跑全量)。"""
    try:
        data = json.loads(断点路径.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0.0
    if not isinstance(data, dict):
        return 0.0
    return float(cast(dict[str, Any], data).get("断到", 0.0) or 0.0)


def 写断点(时刻: float) -> None:
    断点路径.parent.mkdir(parents=True, exist_ok=True)
    断点路径.write_text(
        json.dumps({"断到": 时刻, "写于": time.strftime("%Y-%m-%d %H:%M:%S")}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Hermes 历史对话 -> 语料 (v2)")
    ap.add_argument("out_dir", help="输出目录")
    ap.add_argument("--sessions", type=int, default=30, help="导多少个会话 (0=全部)")
    ap.add_argument("--tools", action="store_true", help="带上 tool 输出 (默认不带)")
    ap.add_argument("--min-msgs", type=int, default=4, help="会话最少几条消息才要")
    ap.add_argument("--all", action="store_true", help="含 active=0 的历史态 (默认不含)")
    ap.add_argument("--incremental", action="store_true", help="增量: 只导断点之后有新消息、且已静默的会话 (给 cron 用)")
    ap.add_argument("--quiet-min", type=int, default=30, help="增量模式: 静默够这么多分钟的会话才收 (正在聊的先不收)")
    args = ap.parse_args()

    roles: tuple[str, ...] = ("user", "assistant", "tool") if args.tools else ("user", "assistant")
    ph = ",".join("?" * len(roles))
    active_only = not args.all
    active = " AND active = 1" if active_only else ""

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=60)
    cur = con.cursor()
    if args.incremental:
        断点 = 读断点()
        since, until = 断点, time.time() - args.quiet_min * 60
    else:
        since, until = 0.0, 1e12
    picked = session_ids(cur, roles, args.min_msgs, args.sessions, active_only, since, until)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    total_chars = 0
    skipped_noise = 0
    skipped_marker = 0
    新文件: list[str] = []
    for sid, _n, _last in picked:
        cur.execute(
            f"""SELECT role, content FROM messages
                WHERE session_id = ? AND role IN ({ph})
                  AND content IS NOT NULL AND TRIM(content) != '' {active}
                ORDER BY timestamp ASC, id ASC""",
            (sid, *roles),
        )
        rows: list[tuple[str, str]] = []
        for r in cur.fetchall():
            role, content = str(r[0]), str(r[1])
            if is_noise(content):
                skipped_noise += 1
                continue
            # v3: 清掉模型的原生工具调用标记再收 —— 不要把 DSML / MiMo 那套标记写进语料
            cleaned = native_marks.strip_all_calls(content)
            if not cleaned:
                skipped_marker += 1  # 整条就是一段工具调用标记, 清完是空的, 不留
                continue
            rows.append((role, cleaned))
        title = ""
        for role, content in rows:
            if role == "user" and content.strip():
                title = content.strip().splitlines()[0][:60]
                break
        parts = [f"# Hermes 会话 {sid[:12]} - {title or '(无标题)'}", ""]
        for role, content in rows:
            parts.append(f"**{ROLE_CN.get(role, role)}**")
            parts.append("")
            parts.append(content.strip())
            parts.append("")
        text = "\n".join(parts)
        路径 = out / f"{sid}.md"
        路径.write_text(text, encoding="utf-8")
        新文件.append(str(路径))
        total_chars += len(text)

    con.close()
    # ★ 给下一棒(cron 里的 embed)留两样东西: 这轮落了哪些文件 / 断点推到哪。
    #   清单是**追加+去重**: 上一轮没嵌成功(清单里还留着)的不能被这轮冲掉 ——
    #   清单由 自动灌语料.sh 在嵌完之后清空, 这样"嵌失败"也能下轮重来。
    最新清单.parent.mkdir(parents=True, exist_ok=True)
    旧单 = [
        x.strip()
        for x in (最新清单.read_text(encoding="utf-8").splitlines() if 最新清单.is_file() else [])
        if x.strip()
    ]
    最新清单.write_text(
        "".join(f"{p}\n" for p in dict.fromkeys([*旧单, *新文件])), encoding="utf-8"
    )
    if args.incremental and picked:
        写断点(max(最近 for _, _, 最近 in picked))

    增量说明 = ""
    if args.incremental:
        增量说明 = f"  (增量: 断点之后且已静默 {args.quiet_min} 分钟)"
    print(
        f"导出 {len(picked)} 个会话, {total_chars:,} 字符 -> {out}{增量说明}"
        f"  (剔掉噪声消息 {skipped_noise} 条, 清掉纯标记消息 {skipped_marker} 条)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
