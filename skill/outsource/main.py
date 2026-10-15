#!/usr/bin/env python3
"""outsource 统一入口: 按功能名调用外援的各个件.

用法:
    .venv/bin/python skill/outsource/main.py <功能名> [参数...]

例:
    .venv/bin/python skill/outsource/main.py status
    .venv/bin/python skill/outsource/main.py ask "写个把 GBK 转 UTF-8 的脚本"

每个件都在 scripts/ 里, 都能单独跑; 这里只负责找到它、把参数原样递过去:
输出不截断、不加工, 退出码原样带回.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent      # skill/outsource
SCRIPTS = HERE / "scripts"                  # 件都在这
ROOT = HERE.parent.parent                   # 项目根 (放 .venv)

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))   # 根上的公共件
import 件定位   # noqa: E402

# 功能名 -> (脚本文件名, 一句话说明)
FUNCTIONS: dict[str, tuple[str, str]] = {
    "ask": ("ask.py", "摇人请外援: 一件明确的活交给云端强模型"),
    "status": ("status.py", "看开关 / 今天花了几毛 / 各路凭据在不在"),
}


def python_bin() -> str:
    """优先用项目 venv 的解释器, 没有就用当前解释器."""
    candidate = ROOT / ".venv" / "bin" / "python"
    return str(candidate) if candidate.exists() else sys.executable


def find_function(name: str) -> Path | None:
    """功能名 -> 脚本路径. 表里没登记的, 就按 <功能名>.py 找."""
    entry = FUNCTIONS.get(name)
    filename = entry[0] if entry is not None else f"{name}.py"
    return 件定位.件路径(SCRIPTS, filename)


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        print("功能名:")
        for name in sorted(FUNCTIONS):
            print(f"  {name:<8} {FUNCTIONS[name][1]}")
        return 0 if len(sys.argv) >= 2 else 1

    name = sys.argv[1]
    script = find_function(name)
    if script is None:
        print(f"没有这个功能: {name}")
        print("有的: " + ", ".join(sorted(FUNCTIONS)))
        return 1

    return subprocess.call([python_bin(), str(script), *sys.argv[2:]])


if __name__ == "__main__":
    raise SystemExit(main())
