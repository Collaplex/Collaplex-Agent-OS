#!/usr/bin/env python3
"""定时任务统一入口: 闹钟 · 倒计时 (登记 / 撤 / 查 / 等 / 重挂 / 自检).

用法:
    .venv/bin/python skill/timer/main.py <动作> [参数...]

例:
    .venv/bin/python skill/timer/main.py register "30分钟后提醒我关火, 先去忙别的"
    .venv/bin/python skill/timer/main.py register "下午3点提醒我开会, 等着"
    .venv/bin/python skill/timer/main.py register "25分钟后提醒我关火" --json --阻塞
    .venv/bin/python skill/timer/main.py list
    .venv/bin/python skill/timer/main.py cancel --最近
    .venv/bin/python skill/timer/main.py take --json
    .venv/bin/python skill/timer/main.py status
    .venv/bin/python skill/timer/main.py selfcheck

实现分两处: scripts/引擎.py(表 · 判据 · 时间解析 · 阻塞等待 · 线程) / scripts/动作.py(命令行动作).
动作表只有一份(在 动作.py 的 动作说明 里), 这里现问现列 —— 不另抄一份以免对不上.
输出不截断、不加工, 退出码原样带回(0 成了 / 1 条件不足 / 2 用法错 / 3 没找着).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent      # skill/timer
SCRIPTS = HERE / "scripts"                  # 实现都在这
ROOT = HERE.parent.parent                   # 项目根 (放 .venv)

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))   # 根上的公共件
import 件定位   # noqa: E402
动作件 = 件定位.件路径(SCRIPTS, "动作.py")


def python_bin() -> str:
    """优先用项目 venv 的解释器, 没有就用当前解释器."""
    candidate = ROOT / ".venv" / "bin" / "python"
    return str(candidate) if candidate.exists() else sys.executable


def 递(参数: list[str]) -> int:
    try:
        completed = subprocess.run([python_bin(), str(动作件), *参数], cwd=ROOT)
    except KeyboardInterrupt:
        return 130
    return completed.returncode


def show_actions() -> None:
    """动作表问 动作.py(单一来源), 不在这里另抄."""
    print("定时任务可用动作:")
    completed = subprocess.run([python_bin(), str(动作件), "actions"],
                              cwd=ROOT, capture_output=True, text=True)
    for 行 in (completed.stdout or "").splitlines():
        if "\t" in 行:
            名, 说明 = 行.split("\t", 1)
            print(f"  {名.ljust(10)} {说明}")
    print("\n跑法: .venv/bin/python skill/timer/main.py <动作> [参数...]")


def main() -> int:
    args = sys.argv[1:]
    # ★ 注意: 这里**不能**把 "list" 当 help 拦 —— "list" 是本 skill 的正经动作(看挂着几条),
    #   跟 math 那种「list = 列动作」的惯例撞名, 所以 help 的别名只留 help / actions.
    if not args or args[0] in ("help", "-h", "--help", "actions"):
        show_actions()
        return 0
    if 动作件 is None:
        print(f"[错误] 实现件不在: {动作件}", file=sys.stderr)
        return 2
    return 递(args)


if __name__ == "__main__":
    sys.exit(main())
