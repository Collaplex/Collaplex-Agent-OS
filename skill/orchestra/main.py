#!/usr/bin/env python3
"""任务编排统一入口：立单 / 看单 / 推进 / 重试 / 收工（活儿单落冷库 PG 表 orchestra）。

用法:
    .venv/bin/python skill/orchestra/main.py <动作> [参数...]

例:
    echo '[{"说明":"勘察落点","做法":"grep main.py","判据":"指出行号"},
           {"说明":"写 skill","做法":"CRUD","判据":"CLI 通"}]' | \
        .venv/bin/python skill/orchestra/main.py plan --json -
    .venv/bin/python skill/orchestra/main.py list
    .venv/bin/python skill/orchestra/main.py next --json
    .venv/bin/python skill/orchestra/main.py doing 2
    .venv/bin/python skill/orchestra/main.py done 2 --产出 "skill 写完, CLI 通了"
    .venv/bin/python skill/orchestra/main.py retry 3
    .venv/bin/python skill/orchestra/main.py status
    .venv/bin/python skill/orchestra/main.py finish          # 收工：撤单，web 面板自己消失

对话id: --对话 X 或环境变量 COLLAPLEX_CHAT_ID（框架在进程内设；默认 "cli"）。
输出不加工、退出码原样带回(0 成了 / 1 条件不足 / 2 用法错 / 3 没找着)。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, cast

HERE = Path(__file__).resolve().parent          # skill/orchestra
ROOT = HERE.parent.parent                       # 项目根
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import manifest as 清单  # noqa: E402  - 清单逻辑在仓根(框架侧), 这里只是它的命令行

动作说明: list[tuple[str, str]] = [
    ("plan", "立单：从 --json 或 stdin 收条目(数组), 整份盖掉这一对话原来的单"),
    ("list", "看这一对话的单(逐条: 序号 状态 说明 / 产出)"),
    ("next", "下一件该干的(先『在做』后『待做』); --json 出结构化"),
    ("doing", "标成在做(递出去时调)"),
    ("done", "标成好了, --产出 记一笔"),
    ("blocked", "标成卡住(重试到顶或判定做不了), --产出 说明为什么"),
    ("retry", "给一件记一次重试, 返回累计次数(到上限就别再试)"),
    ("finish", "收工: 撤掉这一对话的单"),
    ("status", "表 / 对话 / 进度 / 档位"),
    ("selfcheck", "自检: 冷库通不通 / 表在不在 / 条目字段齐不齐"),
]


def 对话() -> str:
    """这一对话的键：--对话 优先, 其次环境变量, 最后 cli。"""
    参 = sys.argv
    if "--对话" in 参:
        位 = 参.index("--对话")
        if 位 + 1 < len(参):
            return 参[位 + 1]
    return os.environ.get("COLLAPLEX_CHAT_ID", "").strip() or "cli"


def 取值(名: str) -> str:
    参 = sys.argv
    if 名 in 参:
        位 = 参.index(名)
        if 位 + 1 < len(参):
            return 参[位 + 1]
    return ""


def 要JSON() -> bool:
    return "--json" in sys.argv


def 出(东西: Any) -> None:
    if 要JSON():
        print(json.dumps(东西, ensure_ascii=False, indent=1))
    elif isinstance(东西, str):
        print(东西)
    else:
        print(json.dumps(东西, ensure_ascii=False, indent=1))


def 铺列表() -> int:
    单 = 清单.读(对话())
    if not 单:
        print(f"（{对话()} 这一对话没有清单）")
        return 0
    好了, 总 = 清单.进度(对话())
    print(f"任务 {好了}/{总}（对话 {对话()}）")
    for 条 in 单:
        尾 = f"  ← {条['产出']}" if str(条.get("产出") or "") else ""
        print(f"  {条['序号']}. [{条['状态']}] {条['说明']}"
              + (f"（重试 {条['重试次数']}）" if int(条.get("重试次数") or 0) else "") + 尾)
    return 0


def 读条目() -> list[dict[str, Any]]:
    原 = ""
    源 = 取值("--json")
    if 源 == "-" or not 源:
        原 = sys.stdin.read()
    else:
        原 = 源
    读: Any = json.loads(原 or "[]")
    if isinstance(读, dict):
        包 = cast(dict[str, Any], 读)
        读 = 包.get("条目") or 包.get("清单") or []
    if not isinstance(读, list):
        raise ValueError("条目要是一个数组")
    return [dict(cast(dict[str, Any], 条)) for 条 in cast(list[Any], 读) if isinstance(条, dict)]


def main() -> int:
    参 = sys.argv[1:]
    if not 参 or 参[0] in ("-h", "--help", "help", "actions"):
        print("任务编排可用动作:")
        for 名, 说 in 动作说明:
            print(f"  {名.ljust(10)} {说}")
        print("\n跑法: .venv/bin/python skill/orchestra/main.py <动作> [参数...]")
        return 0
    动 = 参[0]
    try:
        if 动 == "plan":
            单 = 清单.建(对话(), 读条目())
            出({"对话": 对话(), "件数": len(单), "单": 单})
            return 0
        if 动 == "list":
            return 铺列表()
        if 动 == "next":
            条 = 清单.下一件(对话())
            if 条 is None:
                print("没有下一件了（单是空的或都做完了）")
                return 3
            出(条)
            return 0
        if 动 in ("doing", "done", "blocked"):
            号 = int(参[1]) if len(参) > 1 and 参[1].isdigit() else 0
            状态 = {"doing": "在做", "done": "好了", "blocked": "卡住"}[动]
            条 = 清单.推进(对话(), 号, 状态, 取值("--产出"))
            if 条 is None:
                print(f"没有第 {号} 件", file=sys.stderr)
                return 3
            出(条)
            return 0
        if 动 == "retry":
            号 = int(参[1]) if len(参) > 1 and 参[1].isdigit() else 0
            次 = 清单.重试一次(对话(), 号)
            上限 = int(清单.配置().get("单条重试上限") or 3)
            if not 次:
                print(f"没有第 {号} 件", file=sys.stderr)
                return 3
            print(f"第 {号} 件重试 {次}/{上限}" + ("（到顶了，该标卡住）" if 次 >= 上限 else ""))
            return 0
        if 动 == "finish":
            删 = 清单.收工(对话())
            print(f"撤了 {删} 行（对话 {对话()}）—— web 面板会自己消失")
            return 0
        if 动 == "status":
            好了, 总 = 清单.进度(对话())
            出({"表": 清单.库.表名(清单.表), "对话": 对话(), "好了": 好了, "总共": 总,
                "档位": 清单.配置()})
            return 0
        if 动 == "selfcheck":
            回 = 清单.库.在不在()
            单 = 清单.读(对话())
            齐 = all({"序号", "说明", "状态"} <= set(条) for 条 in 单)
            print(f"冷库: {'通' if 回 else '不通'} · 表 {清单.库.表名(清单.表)} · "
                  f"这一对话 {len(单)} 件 · 字段{'齐' if 齐 else '缺'}")
            return 0 if 回 and 齐 else 1
        print(f"没这个动作: {动}", file=sys.stderr)
        return 2
    except ValueError as 错:
        print(f"条件不足: {错}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
