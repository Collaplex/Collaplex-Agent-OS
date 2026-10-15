#!/usr/bin/env python3
"""对照组: 同一份树, 源码形态 vs 字节码形态, 跑同样几件事, 逐字比。

为什么要有对照: 字节码树里自检会报「热库/冷库读不到」—— 那是**新装机器本来就没有
state/**（源码树里本机有 state/ 所以过得去），不是字节码的毛病。只有把
「同样排除口径的源码树」也跑一遍, 才能证明差异归谁。

    python3 packaging/compare_source_vs_bytecode.py            # 用现成的 dist/字节码树
    python3 packaging/compare_source_vs_bytecode.py --重编      # 先重建字节码树再比

判据:
    自检      比 (共/正确/报错) 三个数 —— 路径与时间戳会变, 数字才说明问题
    检索/算数  比整段 stdout 逐字节
"""
from __future__ import annotations

import argparse
import os
import pathlib
import re
import shutil
import subprocess
import sys

根 = pathlib.Path(__file__).resolve().parent.parent
字节树 = 根 / "dist/字节码树"
源码树 = 根 / "dist/源码对照树"
验证PY = 根 / ".venv/bin/python"

用例: list[tuple[str, list[str], int]] = [
    ("自检", ["{树}/selfcheck.pyc", ], 600),
    ("检索", ["{树}/skill/linux/main.pyc", "find", "磁盘还剩多少空间", "-n", "2"], 600),
    ("算数", ["{树}/skill/math/main.pyc", "calc", "1/3+1/6", "--位数", "20"], 300),
]


def 建源码树() -> None:
    """同口径拷一份, **不编字节码** —— 当对照。"""
    if 源码树.exists():
        shutil.rmtree(源码树)
    sys.path.insert(0, str(根 / "packaging"))
    import importlib

    字节 = importlib.import_module("字节码化")
    字节.建树(源码树)          # 同一套排除口径
    print(f"  对照树（源码形态）{源码树}")


def 跑(树: pathlib.Path, 命令: list[str], 超时: int) -> tuple[int, str]:
    # 源码树里同名件是 .py, 字节码树里是 .pyc —— 命令按实际形态改写
    真命令: list[str] = []
    for 段 in 命令:
        if 段.startswith("{树}/"):
            相对 = 段[len("{树}/"):]
            候选 = 树 / 相对
            if not 候选.is_file():                       # 源码树里同名件带 .py
                备 = 树 / (相对[:-4] + ".py") if 相对.endswith(".pyc") else 树 / (相对 + ".pyc")
                if 备.is_file():
                    候选 = 备
            真命令.append(str(候选))
        else:
            真命令.append(段)
    if 真命令 and 真命令[0].startswith(str(树)) and 真命令[0].endswith((".py", ".pyc")):
        真命令.insert(0, str(验证PY))          # 用解释器跑（跟入口脚本一样的跑法）
    env = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    for 行 in (根 / ".env").read_text(encoding="utf-8", errors="replace").splitlines() if (根 / ".env").is_file() else []:
        行 = 行.strip()
        if 行 and not 行.startswith("#") and "=" in 行:
            键, _, 值 = 行.partition("=")
            env.setdefault(键.strip(), 值.strip().strip('"').strip("'"))
    r = subprocess.run(真命令, cwd=树, capture_output=True, text=True, timeout=超时, env=env)
    return r.returncode, r.stdout + r.stderr


def 摘数字(出: str) -> str:
    """自检输出里只留 (共/正确/报错) 三个数 —— 路径与时间戳每跑都不同。"""
    数 = re.findall(r"^\s*(?:共|正确|报错)\s+(\d+)", 出, re.M)
    return "/".join(数)


def 归一(出: str, 树: pathlib.Path) -> str:
    """把树路径与时间戳抹掉, 剩下的才是能比的。"""
    出 = 出.replace(str(树), "<树>")
    出 = re.sub(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", "<时间>", 出)
    出 = re.sub(r"耗时[\d.]+ms", "耗时<ms>", 出)
    return 出


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--重编", action="store_true")
    a = ap.parse_args()

    if a.重编 or not 字节树.is_dir():
        subprocess.run([str(验证PY), str(根 / "packaging/build_bytecode.py")], cwd=根, check=False)
    if not 源码树.is_dir() or a.重编:
        print("═══ 建对照树（源码形态）═══")
        建源码树()

    print("\n═══ 两形态跑同样几件事 ═══")
    一致 = 0
    for 名, 命令, 超时 in 用例:
        码A, 出A = 跑(字节树, 命令, 超时)
        码B, 出B = 跑(源码树, 命令, 超时)
        if 名 == "自检":
            比A, 比B = 摘数字(出A), 摘数字(出B)
        else:
            比A, 比B = 归一(出A, 字节树), 归一(出B, 源码树)
        同 = (码A == 码B) and (比A == 比B)
        一致 += 同
        print(f"  {'✓ 一致' if 同 else '✗ 有差异'}  {名}")
        print(f"      字节码: 退出码 {码A} · {比A.splitlines()[0][:88] if 比A else '(空)'}")
        print(f"      源码  : 退出码 {码B} · {比B.splitlines()[0][:88] if 比B else '(空)'}")
        if not 同 and 名 != "自检":
            for x, y in zip(比A.splitlines(), 比B.splitlines()):
                if x != y:
                    print(f"      首个不同行:\n        字节码: {x[:100]}\n        源码  : {y[:100]}")
                    break

    print(f"\n  一致 {一致}/{len(用例)}")
    if 一致 == len(用例):
        print("  → 差异归零: 字节码形态跟源码形态行为一样（自检里那两项热库/冷库是 state/ 没进包, 源码树同样报）")
    return 0 if 一致 == len(用例) else 1


if __name__ == "__main__":
    sys.exit(main())
