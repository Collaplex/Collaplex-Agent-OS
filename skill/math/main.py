#!/usr/bin/env python3
"""数学命令库统一入口: 算数 · 解方程 · 矩阵 · 统计 · 概率 · 换算 · 出图 · 日期.

用法:
    .venv/bin/python skill/math/main.py <动作> [参数...]

例:
    .venv/bin/python skill/math/main.py calc "6/2*(1+2)"
    .venv/bin/python skill/math/main.py calc "1/3+1/6" --位数 20
    .venv/bin/python skill/math/main.py solve 线性 "2x+3y=7" "x-y=1"
    .venv/bin/python skill/math/main.py find "算一下复利" -n 3
    .venv/bin/python skill/math/main.py index

实现分三处: compute.py(算) / convert.py(换算与出图) / retrieve.py(查命令库);
这里只负责把动作名接上、参数原样递过去 —— 输出不截断、不加工, 退出码原样带回。
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import cast

HERE = Path(__file__).resolve().parent      # skill/math
SCRIPTS = HERE / "scripts"                   # 实现都在这
ROOT = HERE.parent.parent                    # 项目根 (放 .venv)

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))   # 根上的公共件
import path_locator as 件定位   # noqa: E402

# 动作名 -> (脚本文件名, 递进去的第一个参数, 一句话说明)
ACTIONS: dict[str, tuple[str, str, str]] = {
    "calc": ("compute.py", "calc", "算表达式(精确分数 / 高精度小数; 支持 sqrt/ln/sin/阶乘/百分号/^)"),
    "num": ("compute.py", "num", "数论与计数: 分解/质数/阶乘/组合/排列/斐波那契/进制/位运算"),
    "solve": ("compute.py", "solve", "解方程: 一元数值求根 / 线性方程组精确解"),
    "linalg": ("compute.py", "linalg", "矩阵: 行列式/逆/转置/乘/秩/解/特征值"),
    "poly": ("compute.py", "poly", "多项式: 求值/加减乘除/导数/积分/求根"),
    "calculus": ("compute.py", "calculus", "导数/二阶导/定积分/极限/求和/连乘"),
    "stats": ("compute.py", "stats", "描述统计(均值·方差·四分位)/相关/线性回归"),
    "prob": ("compute.py", "prob", "概率: 二项/正态/泊松/几何"),
    "money": ("convert.py", "money", "占比/折扣/涨跌/单利/复利/房贷月供(Decimal 高精度)"),
    "units": ("convert.py", "units", "单位换算(长度·质量·面积·体积·速度·数据·压力·能量·功率·角度·温度)"),
    "plot": ("convert.py", "plot", "函数图/折线/散点/柱状, 出 SVG 文件"),
    "date": ("convert.py", "date", "日期差(含工作日)/加减日期/周几/第几周"),
    "find": ("retrieve.py", "find", "查数学命令库: 给一句话, 拿回该用哪条命令(用法/选项/示例)"),
    "index": ("retrieve.py", "index", "建/更新命令库索引(按 hash 复用向量, 不重打模型)"),
}


# ★ 编译版（Nuitka）：实现件已经用 --include-module 编进这个 exe 里，直接在同一个进程里
#   调它们的 run()。.py 版照旧走子进程转发 —— 那边实现件是磁盘上的真实文件，要用项目
#   自己的解释器（选解释器那套在编译版里会指到 exe 自己身上，必崩）。
编译版 = "__compiled__" in globals()

# ★ 这三行必须硬编码在模块顶层，Nuitka 才看得见、才会编进去。
#   retrieve 牵连 rag 那套（embed/search/store → psycopg、dotenv）—— 编不进来时不要把整个
#   exe 拖死：分开 try，缺了哪个就只让那几个动作报一句清楚的话。
_模块表: dict[str, object] = {}
_编译缺件: dict[str, str] = {}   # 缺了哪个实现件、为什么 —— 只在真要用到它时才说出来
if 编译版:
    try:
        import compute as _compute

        _模块表["compute.py"] = _compute
    except Exception as _错:  # noqa: BLE001
        _编译缺件["compute.py"] = str(_错)
    try:
        import convert as _convert

        _模块表["convert.py"] = _convert
    except Exception as _错:  # noqa: BLE001
        _编译缺件["convert.py"] = str(_错)
    try:
        import retrieve as _retrieve

        _模块表["retrieve.py"] = _retrieve
    except Exception as _错:  # noqa: BLE001
        _编译缺件["retrieve.py"] = str(_错)

if os.environ.get("MATH_DEBUG"):   # 临时探针：确认编译版判定，验完就删
    print(f"[debug] 编译版={编译版} | 带 compil 的 globals 键={[k for k in globals() if 'compil' in k.lower()]}"
          f" | frozen={getattr(sys, 'frozen', None)} | __file__={globals().get('__file__')!r}"
          f" | argv0={sys.argv[0]!r}", file=sys.stderr)


def _处理表(模: object) -> dict[str, object] | None:
    """实现件里那个 HANDLERS 字典（compute 叫 CALC_HANDLERS、别的不一定同名）—— 按后缀找。

    ★ 返回前 `cast` 一下：`vars()` 拿出来的是 `Any`、`isinstance(值, dict)` 只能收窄成
      `dict[Unknown, Unknown]`，直接返回会被判"返回类型部分未知"（2026-10-13 清红点时改的）。
    """
    for 名, 值 in vars(模).items():
        if 名.endswith("HANDLERS") and isinstance(值, dict):
            return cast(dict[str, object], 值)
    return None


def python_bin() -> str:
    """优先用项目 venv 的解释器, 没有就用当前解释器."""
    candidate = ROOT / ".venv" / "bin" / "python"
    return str(candidate) if candidate.exists() else sys.executable


def show_actions() -> None:
    """列出所有可用动作."""
    print("数学命令库可用动作:")
    width = max(len(name) for name in ACTIONS)
    for name, (filename, _sub, note) in ACTIONS.items():
        ready = "" if 件定位.有件(SCRIPTS, filename) else "   [缺文件]"
        print(f"  {name.ljust(width)}  {note}   ({filename}){ready}")
    print("\n跑法: .venv/bin/python skill/math/main.py <动作> [参数...]")


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
    # ★ 编译版里实现件是编进 exe 的模块，磁盘上本来就没有这个文件 —— 不要把它当缺件挡掉。
    if not 编译版 and script is None:
        print(f"[错误] 实现件不在: {script}", file=sys.stderr)
        return 2

    if 编译版:
        模 = _模块表.get(filename)
        if 模 is None or not hasattr(模, "run"):
            print(f"[错误] 这个动作的实现件没编进 exe（{filename}）"
                  f"{'：' + _编译缺件[filename] if filename in _编译缺件 else ''}；"
                  f"改用源码版的 .py 入口跑它", file=sys.stderr)
            return 2
        表 = _处理表(模)
        if 表 is None:
            print(f"[错误] {filename} 里找不到处理表", file=sys.stderr)
            return 2
        try:
            return int(模.run(表, [sub, *rest]) or 0)  # type: ignore[attr-defined]
        except KeyboardInterrupt:
            return 130

    try:
        return 件定位.跑件(script, [sub, *rest], ROOT, python_bin())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
