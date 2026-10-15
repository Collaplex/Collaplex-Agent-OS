#!/usr/bin/env python3
"""skill_search 统一入口: 按软件名调用本 skill 的各个功能件.

用法:
    .venv/bin/python skill/skill_search/main.py <软件名> [参数...]

例:
    .venv/bin/python skill/skill_search/main.py index
    .venv/bin/python skill/skill_search/main.py find "把 PDF 转成 markdown"

每个功能件都在 scripts/ 里, 都能单独跑; 这里只负责找到它、把参数原样递过去:
输出不截断、不加工, 退出码原样带回.
"""

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent      # skill/skill_search
SCRIPTS = HERE / "scripts"                   # 功能件都在这
ROOT = HERE.parent.parent                    # 项目根 (放 .venv)

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))   # 根上的公共件
import 件定位   # noqa: E402

# 软件名 -> (脚本文件名, 一句话说明)
SOFTWARE: dict[str, tuple[str, str]] = {
    "index": ("index_skills.py", "扫 skill 目录, 建/刷新 skill 索引"),
    "find": ("find_skill.py", "给一句话, 找出该用哪个 skill"),
}


def python_bin() -> str:
    """优先用项目 venv 的解释器, 没有就用当前解释器."""
    candidate = ROOT / ".venv" / "bin" / "python"
    return str(candidate) if candidate.exists() else sys.executable


def find_software(name: str) -> Path | None:
    """软件名 -> 脚本路径. 表里没登记的, 就按 <软件名>.py 找."""
    entry = SOFTWARE.get(name)
    filename = entry[0] if entry is not None else f"{name}.py"
    return 件定位.件路径(SCRIPTS, filename)


def show_software() -> None:
    """列出所有可用软件."""
    print("skill_search 可用软件:")
    width = max(len(name) for name in SOFTWARE)
    for name, (filename, note) in SOFTWARE.items():
        ready = "" if 件定位.有件(SCRIPTS, filename) else "   [缺文件]"
        print(f"  {name.ljust(width)}  {note}   ({filename}){ready}")
    print("\n跑法: .venv/bin/python skill/skill_search/main.py <软件名> [参数...]")


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] in ("list", "help", "-h", "--help"):
        show_software()
        return 0

    name = args[0]
    rest = args[1:]

    script = find_software(name)
    if script is None:
        print(f"[错误] 没有这个软件: {name}\n")
        show_software()
        return 2

    try:
        return 件定位.跑件(script, rest, ROOT, python_bin())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
