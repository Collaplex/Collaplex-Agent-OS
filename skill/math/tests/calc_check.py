#!/usr/bin/env python3
"""计算对拍 —— 12 条命令**真跑**一遍, 拿已知答案核对.

不是单测(不 mock、不 import 函数直接调): 每条都当真命令行跑, 比对 stdout ——
模型将来也是这么用的, 所以这里必须走同一条路。

用法:
    .venv/bin/python skill/math/tests/calc_check.py
    .venv/bin/python skill/math/tests/calc_check.py --verbose      # 把每条的输出也贴出来

判据两类:
    该算对的    stdout 里必须出现"答案片段"(精确硬编码, 不用大约数)
    该算不了的  退出码必须是 1, 且 stderr/stdout 里说明了原因
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_FILE = HERE.parent
ROOT = SKILL_FILE.parent.parent
ENTRY = SKILL_FILE / "main.py"
PYTHON = ROOT / ".venv" / "bin" / "python"
PLOT_OUT = SKILL_FILE / "logs" / "自检-正弦.svg"

# (命令参数, 输出里必须出现的片段)
CHECKS: list[tuple[list[str], str]] = [
    # —— calc: 精确优先 ——
    (["calc", "6/2*(1+2)"], "结果: 9"),
    (["calc", "0.1+0.2"], "3/10"),                       # 不是 0.30000000000000004
    (["calc", "1/3+1/6"], "1/2"),
    (["calc", "2**100"], "1267650600228229401496703205376"),
    (["calc", "170!"], "7257415615307998967396728211129263114716991681296451376543577798900"),
    (["calc", "170!"], "共 307 位"),
    (["calc", "sqrt(2)", "--位数", "20"], "1.4142135623730950488"),
    (["calc", "sqrt(144)"], "结果: 12"),
    (["calc", "50%*80"], "结果: 40"),
    (["calc", "log2(8)"], "结果: 3"),
    (["calc", "1,234,567+1"], "1234568"),
    (["calc", "2^10"], "1024"),
    # —— num ——
    (["num", "分解", "360"], "2^3 · 3^2 · 5"),
    (["num", "质数", "1000000007"], "是质数"),
    (["num", "斐波那契", "100"], "354224848179261915075"),
    (["num", "组合", "49", "6"], "13983816"),
    (["num", "进制", "255"], "11111111"),
    (["num", "位", "1 << 40"], "1099511627776"),
    # —— solve ——
    (["solve", "一元", "x^2-2=0", "--区间", "-5", "5"], "x ≈ 1.414213562"),
    (["solve", "一元", "x^2-2=0", "--区间", "-5", "5"], "x ≈ -1.414213562"),
    (["solve", "线性", "2x+3y=7", "x-y=1"], "x: 2"),
    (["solve", "线性", "2x+3y=7", "x-y=1"], "y: 1"),
    # —— linalg ——
    (["linalg", "行列式", "[[1,2],[3,4]]"], "det: -2"),
    (["linalg", "逆", "[[4,7],[2,6]]"], "0.6"),
    (["linalg", "解", "[[2,1],[1,3]]", "[[5],[10]]"], "x1: 1"),
    (["linalg", "秩", "[[1,2],[2,4]]"], "秩: 1"),
    # —— poly ——
    (["poly", "乘", "[1,1]", "[1,-1]"], "x^2 - 1"),
    (["poly", "除", "[1,0,-4]", "[1,-2]"], "商: x + 2"),
    (["poly", "求值", "[1,0,-4]", "3"], "f(x): 5"),
    (["poly", "导数", "[1,0,-4]"], "2*x"),
    # —— calculus ——
    (["calculus", "导数", "x^2", "3"], "结果: 6"),
    (["calculus", "二阶导", "x^3", "2"], "结果: 12"),
    (["calculus", "积分", "x^2", "0", "3"], "结果: 9"),
    (["calculus", "极限", "sin(x)/x", "0"], "1 → 1"),
    (["calculus", "求和", "k^2", "1", "100"], "338350"),
    (["calculus", "连乘", "k", "1", "5"], "120"),
    # —— stats ——
    (["stats", "描述", "2,4,4,4,5,5,7,9"], "总体方差: 4"),
    (["stats", "描述", "2,4,4,4,5,5,7,9"], "众数: 4(出现 3 次)"),
    (["stats", "回归", "1,2,3,4", "2,4,6,9"], "y = 2.3·x - 0.5"),
    (["stats", "相关", "1,2,3,4", "2,4,6,8"], "r: 1"),
    # —— prob ——
    (["prob", "二项", "10", "0.5", "5"], "63/256"),
    (["prob", "正态", "0", "1", "1.96"], "0.9750021049"),
    (["prob", "泊松", "3", "2"], "0.2240418076"),
    (["prob", "几何", "0.2", "5"], "0.08192"),
    # —— money ——
    (["money", "占比", "30", "200"], "15%"),
    (["money", "折扣", "200", "8.5"], "现价: 170"),
    (["money", "单利", "10000", "3", "5"], "利息: 1500"),
    (["money", "复利", "10000", "3.5", "10"], "14105.9"),      # 10000 × 1.035^10
    (["money", "月供", "1000000", "4.2", "360"], "4890.17"),   # 百万 30 年 4.2%
    # —— units ——
    (["units", "换算", "10", "km", "mi"], "6.2137119223"),
    (["units", "换算", "1", "GiB", "MB"], "1073.741824"),
    (["units", "换算", "1", "斤", "g"], "500 g"),
    (["units", "温度", "100", "C", "F"], "212 F"),
    (["units", "温度", "0", "C", "K"], "273.15 K"),
    # —— date ——
    (["date", "差", "2026-01-01", "2026-10-07"], "279 天"),
    (["date", "加", "2026-10-07", "30天"], "2026-11-06"),
    (["date", "加", "2026-01-31", "1月"], "2026-02-28"),
    (["date", "周几", "2026-10-07"], "周三"),
]

# (命令参数, 报错里必须出现的原因片段) —— 算不了就得明说, 不许默默给个数
REFUSALS: list[tuple[list[str], str]] = [
    (["calc", "1/0"], "除数是 0"),
    (["calc", "sqrt(-1)"], "负数开平方"),
    (["calc", "2 +"], "表达式看不懂"),
    (["calc", "abc"], "不认识的符号"),
    (["num", "阶乘", "-1"], "阶乘只支持"),
    (["solve", "线性", "x^2+y=1", "x+y=2"], "这个方程不是线性的"),
    (["units", "换算", "1", "m", "kg"], "跨类换不了"),
    (["units", "换算", "1", "furlong", "m"], "不认识这个单位"),
    (["linalg", "行列式", "[[1,2,3],[4,5,6]]"], "行列式要方阵"),
    (["date", "差", "2026-13-01", "2026-10-07"], "日期看不懂"),
    (["plot", "函数", "sin(x)", "3", "1"], "起止要递增"),
    (["stats", "回归", "1,2,3", "1,2"], "两组数据要一样长"),
    (["calc", "1+"], "表达式看不懂"),
]


def run(args: list[str]) -> tuple[int, str, str]:
    """真跑一条命令: 返回 (退出码, stdout, stderr)."""
    done = subprocess.run([str(PYTHON), str(ENTRY), *args], cwd=str(ROOT),
                          capture_output=True, text=True)
    return done.returncode, done.stdout, done.stderr


def main() -> int:
    verbose = "--verbose" in sys.argv
    passed = 0
    failed: list[str] = []

    for args, want in CHECKS:
        code, out, err = run(args)
        text = out + err
        if code == 0 and want in text:
            passed += 1
            if verbose:
                print(f"[✓] math {' '.join(args)}\n{out.rstrip()}\n")
        else:
            failed.append(f"[✗] math {' '.join(args)}\n    期望出现: {want}\n    退出码 {code}\n"
                          f"    实际: {text.strip()[:400]}")
            print(f"[✗] math {' '.join(args)}  期望 {want!r}, 实际退出码 {code}")

    plot_args = ["plot", "函数", "sin(x)", "-3.14159", "3.14159", "-o", str(PLOT_OUT)]
    code, out, err = run(plot_args)
    if code == 0 and PLOT_OUT.is_file() and PLOT_OUT.stat().st_size > 2000:
        passed += 1
        print(f"[✓] plot 真落盘: {PLOT_OUT} ({PLOT_OUT.stat().st_size} 字节)")
    else:
        failed.append(f"[✗] plot 没落盘或文件太小: 退出码 {code} {out.strip()[:200]} {err.strip()[:200]}")
        print(f"[✗] plot 没落盘")

    for args, want in REFUSALS:
        code, out, err = run(args)
        text = out + err
        if code == 1 and want in text:
            passed += 1
        else:
            failed.append(f"[✗] math {' '.join(args)} 该拒答\n    期望: {want}\n"
                          f"    退出码 {code}\n    实际: {text.strip()[:300]}")
            print(f"[✗] math {' '.join(args)}  该拒答, 实际退出码 {code}")

    total = len(CHECKS) + 1 + len(REFUSALS)
    print(f"\n通过 {passed} / 失败 {len(failed)}    (共 {total} 条: 算对 {len(CHECKS)} + 落盘 1 + 拒答 {len(REFUSALS)})")
    for line in failed:
        print(line)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
