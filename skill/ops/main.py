#!/usr/bin/env python3
"""命令库统一入口: 按动作名调用检索件.

用法:
    .venv/bin/python skill/ops/main.py <动作> [参数...]

例:
    .venv/bin/python skill/ops/main.py find "磁盘还剩多少空间" -n 3
    .venv/bin/python skill/ops/main.py find "谁占着 8789 端口" --mode rrf
    .venv/bin/python skill/ops/main.py index

检索件在 scripts/retrieve.py (它自己也能单独跑); 这里只负责把动作名接上、参数原样递过去:
输出不截断、不加工, 退出码原样带回。
"""

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent      # skill/ops
SCRIPTS = HERE / "scripts"                   # 检索件在这
ROOT = HERE.parent.parent                    # 项目根 (放 .venv)

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))   # 根上的公共件
import 件定位   # noqa: E402

# 动作名 -> (脚本文件名, 递进去的第一个参数, 一句话说明)
ACTIONS: dict[str, tuple[str, str, str]] = {
    "find": ("retrieve.py", "find", "查手册条目: 给一句话, 拿回该用哪条命令(用途/用法/示例)"),
    "index": ("retrieve.py", "index", "建/更新命令库索引(按 hash 复用向量, 不重打模型)"),
}


def python_bin() -> str:
    """优先用项目 venv 的解释器, 没有就用当前解释器."""
    candidate = ROOT / ".venv" / "bin" / "python"
    return str(candidate) if candidate.exists() else sys.executable


def show_actions() -> None:
    """列出所有可用动作."""
    print("手册可用动作:")
    width = max(len(name) for name in ACTIONS)
    for name, (filename, _sub, note) in ACTIONS.items():
        ready = "" if 件定位.有件(SCRIPTS, filename) else "   [缺文件]"
        print(f"  {name.ljust(width)}  {note}   ({filename}){ready}")
    print("\n跑法: .venv/bin/python skill/ops/main.py <动作> [参数...]")


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
        print(f"[错误] 检索件不在: {script}", file=sys.stderr)
        return 2

    try:
        return 件定位.跑件(script, [sub, *rest], ROOT, python_bin())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
