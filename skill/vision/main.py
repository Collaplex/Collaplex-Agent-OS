#!/usr/bin/env python3
"""看图命令库统一入口: 看图 · 状态 · find · index.

用法:
    .venv/bin/python skill/vision/main.py <动作> [参数...]

例:
    .venv/bin/python skill/vision/main.py 看图 skill/search/cache/shots/xxxx.jpg
    .venv/bin/python skill/vision/main.py 看图 某图.png --问 "这页的标题是什么" --json
    .venv/bin/python skill/vision/main.py 状态 --真读
    .venv/bin/python skill/vision/main.py find "图里写了什么" -n 3
    .venv/bin/python skill/vision/main.py index

实现分三处: see.py(看图) / status.py(状态) / retrieve.py(查命令库);
这里只负责把动作名接上、参数原样递过去 —— 输出不截断、不加工, 退出码原样带回.

★ 别的 skill 的 main.py 都往实现件递一个"子动作名"; 这里的 see/status 没有子动作
  (它们的第一个参数就是图片路径 / 无参), 所以 ACTIONS 里 sub 写 None 表示"不递".
"""

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent      # skill/vision
SCRIPTS = HERE / "scripts"                   # 实现都在这
ROOT = HERE.parent.parent                    # 项目根 (放 .venv)

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))   # 根上的公共件
import path_locator as 件定位   # noqa: E402

# 动作名 -> (脚本文件名, 递给它的子动作名(None=不递), 一句话说明)
ACTIONS: dict[str, tuple[str, str | None, str]] = {
    "看图": ("see.py", None, "看一眼: 一张本地图片 → 文字 (主路云端, 不成自动兜底本地)"),
    "状态": ("status.py", None, "两条路各通不通 + 本轮还剩几次 (--真读 能证明本地能不能读图)"),
    "find": ("retrieve.py", "find", "查看图命令库: 给一句话, 拿回该用哪条命令 (用法/选项/示例)"),
    "index": ("retrieve.py", "index", "建/更新命令库索引 (按 hash 复用向量, 不重打模型)"),
}


def python_bin() -> str:
    """优先用项目 venv 的解释器, 没有就用当前解释器."""
    candidate = ROOT / ".venv" / "bin" / "python"
    return str(candidate) if candidate.exists() else sys.executable


def show_actions() -> None:
    """列出所有可用动作."""
    print("看图命令库可用动作:")
    width = max(len(name) for name in ACTIONS)
    for name, (filename, _sub, note) in ACTIONS.items():
        ready = "" if 件定位.有件(SCRIPTS, filename) else "   [缺文件]"
        print(f"  {name.ljust(width)}  {note}   ({filename}){ready}")
    print("\n跑法: .venv/bin/python skill/vision/main.py <动作> [参数...]")


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] in ("list", "help", "-h", "--help"):
        show_actions()
        return 0

    name = args[0]
    rest = args[1:]
    entry = ACTIONS.get(name)
    if entry is None:
        print(f"[错误] 没有这个动作: {name}\n")
        show_actions()
        return 2

    filename, sub, _note = entry
    script = 件定位.件路径(SCRIPTS, filename)
    if script is None:
        print(f"[错误] 实现件不在: {script}", file=sys.stderr)
        return 2

    return 件定位.跑件(script, ([sub] if sub else []) + rest, ROOT, python_bin())


if __name__ == "__main__":
    sys.exit(main())
