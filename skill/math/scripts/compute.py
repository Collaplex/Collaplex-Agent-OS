#!/usr/bin/env python3
"""数学的 12 个子命令 —— 一条命令一组函数, 全部交给 Python 真算.

calc    表达式求值(精确分数 / 高精度小数)      num     数论 · 组合 · 进制 · 位运算
solve   方程(一元求根) / 线性方程组            linalg  矩阵与线性代数
poly    多项式(四则 · 导/积 · 求根)            calculus 导数 · 积分 · 极限 · 求和 · 连乘
stats   描述统计 · 相关 · 回归                 prob    二项 · 正态 · 泊松 · 几何
money   占比 · 折扣 · 涨跌 · 单利复利 · 月供    units   长度/质量/面积/体积/速度/数据/温度…
plot    函数图 · 折线 · 散点 · 柱状(出 SVG)     date    日期差 · 推算 · 周几 · 第几周

★ 这里的每个数都是 Python 算出来的, 输出带 [精确] / [近似] 标记 —— 汇报时照抄, 不要改写.
"""

from __future__ import annotations

import json
import math
import re
import sys
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path
from typing import Callable, Sequence, cast

import numpy as np
from numpy.typing import NDArray

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import engine as en  # noqa: E402  (同目录的引擎, 进来前要先把它加进 sys.path)
from cli import (as_fraction, as_number, digits_of, emit, need,  # noqa: E402
                 number_list, pair_flag, run)

FloatMatrix = NDArray[np.float64]
CALC_HANDLERS: dict[str, Callable[[list[str]], int]] = {}


# ============================================================
# 小工具: 参数 · 解析 · 打印
# ============================================================

def float_matrix(text: str) -> FloatMatrix:
    """矩阵: JSON 二维数组, 比如 [[1,2],[3,4]]."""
    loaded = cast(object, json.loads(text))
    if not isinstance(loaded, list):
        raise ValueError("矩阵要写成 JSON 二维数组, 比如 [[1,2],[3,4]]")
    rows: list[list[float]] = []
    for row in cast(list[object], loaded):
        if not isinstance(row, list):
            raise ValueError("矩阵的每一行都要是数组")
        rows.append([float(as_number(str(cell))) for cell in cast(list[object], row)])
    if not rows or not rows[0]:
        raise ValueError("矩阵是空的")
    return np.array(rows, dtype=np.float64)


def frac_list(text: str) -> list[Fraction]:
    """多项式系数: 降幂, 比如 [1,0,-4] 表示 x^2 - 4."""
    return number_list(text)


def matrix_text(matrix: FloatMatrix) -> str:
    """矩阵打印: 每个数保留 6 位有效, 整数就印整数."""
    lines: list[str] = []
    for row in matrix.tolist():
        cells = [f"{cell:g}" if abs(cell - round(cell)) > 1e-9 or abs(cell) > 1e15
                 else str(round(cell)) for cell in cast(list[float], row)]
        lines.append("  " + "  ".join(f"{cell:>14s}" for cell in cells))
    return "\n" + "\n".join(lines)


def to_python_source(expression: str) -> str:
    """把用户写的表达式掰成 Python 写法(交给引擎, 这里只是便于打印)."""
    return en.normalize(expression)


# ============================================================
# 1. calc —— 表达式求值
# ============================================================

def cmd_calc(args: list[str]) -> int:
    digits = digits_of(args)
    need(args, 1, 'calc "<表达式>" [--位数 N]')
    expression = args[0]
    value = en.evaluate(expression)
    emit("calc", [
        ("表达式", expression if expression == en.normalize(expression)
         else f"{expression}   (按 {en.normalize(expression)} 算)"),
        ("结果", en.fmt_full(value, digits)),
        ("成色", en.kind_of(value)),
    ])
    return 0


# ============================================================
# 2. num —— 数论 · 组合 · 进制 · 位运算
# ============================================================

def _miller_rabin(number: int) -> bool:
    """确定性 Miller-Rabin: 对 3.3e24 以内的整数判断是准确的."""
    if number < 2:
        return False
    small = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37]
    for prime in small:
        if number % prime == 0:
            return number == prime
    odd, power = number - 1, 0
    while odd % 2 == 0:
        odd //= 2
        power += 1
    for base in small:
        witness = pow(base, odd, number)
        if witness in (1, number - 1):
            continue
        for _ in range(power - 1):
            witness = witness * witness % number
            if witness == number - 1:
                break
        else:
            return False
    return True


def _factorize(number: int) -> tuple[list[tuple[int, int]], int]:
    """试除法分解, 返回 (质因数指数表, 上限切掉后没分解完的剩余).

    除数超过 1e7 就停(不然大数会跑到天荒地老); 正常停下时剩下的那个一定是质数.
    """
    factors: list[tuple[int, int]] = []
    left = number
    divisor = 2
    capped = False
    while divisor * divisor <= left:
        if divisor > 10_000_000:
            capped = True
            break
        count = 0
        while left % divisor == 0:
            left //= divisor
            count += 1
        if count:
            factors.append((divisor, count))
        divisor += 1 if divisor == 2 else 2
    if left > 1 and not capped:
        factors.append((left, 1))       # 除数已经比它大, 它是质数
    return factors, (left if capped else 1)


def _fibonacci(index: int) -> int:
    """快速倍增法算斐波那契(大数不吃力)."""
    def pair(position: int) -> tuple[int, int]:
        if position == 0:
            return 0, 1
        half, after = pair(position >> 1)
        doubled = half * (2 * after - half)
        squared = half * half + after * after
        return (squared, doubled + squared) if position & 1 else (doubled, squared)

    return pair(index)[0]


def _base_out(number: int, base: int) -> str:
    """整数转任意进制(2~36)."""
    if not 2 <= base <= 36:
        raise ValueError("进制要在 2~36 之间")
    if number == 0:
        return "0"
    table = "0123456789abcdefghijklmnopqrstuvwxyz"
    sign = "-" if number < 0 else ""
    left = abs(number)
    out: list[str] = []
    while left:
        out.append(table[left % base])
        left //= base
    return sign + "".join(reversed(out))


def cmd_num(args: list[str]) -> int:
    need(args, 1, "num <分解|质数|阶乘|组合|排列|斐波那契|约|进制|位> ...")
    action, rest = args[0], args[1:]
    if action == "分解":
        need(rest, 1, "num 分解 <整数>")
        number = en.as_int(as_number(rest[0]), "要分解的数")
        if abs(number) > 10**18:
            raise ValueError("分解先支持 1e18 以内的整数")
        factors, left = _factorize(abs(number))
        pieces = [f"{prime}^{count}" if count > 1 else f"{prime}" for prime, count in factors]
        if left > 1:
            pieces.append(f"{left}(没分解完, 可能是质数或两个大质数之积)")
        emit("num 分解", [
            ("数", f"{number}"),
            ("质因数", " · ".join(pieces) or "1"),
            ("是否质数", "是" if _miller_rabin(abs(number)) else "不是"),
        ])
        return 0
    if action == "质数":
        need(rest, 1, "num 质数 <整数>")
        number = en.as_int(as_number(rest[0]), "要判断的数")
        rows = [("数", f"{number}"), ("结论", "是质数" if _miller_rabin(number) else "不是质数")]
        if not _miller_rabin(number) and number > 3:
            factors, _left = _factorize(abs(number))
            if factors:
                rows.append(("最小因子", str(factors[0][0])))
        emit("num 质数", rows)
        return 0
    if action == "阶乘":
        need(rest, 1, "num 阶乘 <整数>")
        number = en.as_int(as_number(rest[0]), "阶乘的参数")
        if not 0 <= number <= 100000:
            raise ValueError("阶乘只支持 0~100000 的整数")
        value = Fraction(math.factorial(number))
        emit("num 阶乘", [("n", str(number)), ("n!", en.fmt(value)), ("位数", str(len(str(int(value)))))])
        return 0
    if action in ("组合", "排列"):
        need(rest, 2, f"num {action} <n> <k>")
        left, right = (en.as_int(as_number(piece), f"{action} 的 n") for piece in rest[:2])
        if action == "组合":
            if not 0 <= right <= max(left, 0):
                raise ValueError("组合数要满足 0 <= k <= n")
            value = Fraction(math.comb(left, right))
        else:
            if not 0 <= right <= max(left, 0):
                raise ValueError("排列数要满足 0 <= k <= n")
            value = Fraction(math.perm(left, right))
        emit(f"num {action}", [
            ("n, k", f"{left}, {right}"),
            ("结果", en.fmt(value)),
            ("公式", f"C({left},{right})" if action == "组合" else f"P({left},{right})"),
        ])
        return 0
    if action == "斐波那契":
        need(rest, 1, "num 斐波那契 <项号>")
        index = en.as_int(as_number(rest[0]), "项号")
        if not 0 <= index <= 100000:
            raise ValueError("项号要在 0~100000 之间")
        value = _fibonacci(index)
        emit("num 斐波那契", [("第 n 项", str(index)), ("F(n)", str(value)),
                              ("位数", str(len(str(value))))])
        return 0
    if action == "约":
        need(rest, 2, "num 约 <整数A> <整数B>")
        left, right = (en.as_int(as_number(piece), "参数") for piece in rest[:2])
        emit("num 约", [("A, B", f"{left}, {right}"),
                        ("最大公约数", str(math.gcd(left, right))),
                        ("最小公倍数", str(math.lcm(left, right)))])
        return 0
    if action == "进制":
        need(rest, 1, "num 进制 <数> [目标进制] 或 num 进制 <数> <源进制> <目标进制>")
        if len(rest) == 1:
            number = en.as_int(as_number(rest[0]), "要转换的数")
        elif len(rest) == 2:
            number = en.as_int(as_number(rest[0]), "要转换的数")
        else:
            base_from = en.as_int(as_number(rest[1]), "源进制")
            number = int(rest[0].strip().lower(), base_from) if base_from != 10 else int(rest[0])
        target = en.as_int(as_number(rest[-1]), "目标进制") if len(rest) >= 2 else 16
        emit("num 进制", [
            ("十进制", str(number)),
            ("二进制", _base_out(number, 2)),
            ("八进制", _base_out(number, 8)),
            ("十六进制", _base_out(number, 16)),
            (f"按 {target} 进制", _base_out(number, target)),
        ])
        return 0
    if action == "位":
        need(rest, 1, 'num 位 "<位运算表达式>"')
        value = en.evaluate(rest[0])
        number = en.as_int(value, "位运算结果")
        emit("num 位", [("表达式", rest[0]), ("结果", str(number)),
                        ("十六进制", _base_out(number, 16)), ("二进制", _base_out(number, 2))])
        return 0
    raise ValueError(f"num 不认这个子动作: {action}")


# ============================================================
# 3. solve —— 方程与方程组
# ============================================================

def cmd_solve(args: list[str]) -> int:
    need(args, 2, 'solve 一元 "<方程>" [--区间 A B] | solve 线性 "<方程1>" "<方程2>" ...')
    action, rest = args[0], args[1:]
    digits = digits_of(args)
    if action == "一元":
        need(rest, 1, 'solve 一元 "<方程>" [--区间 A B]')
        expression = rest[0]
        low, high = -100.0, 100.0
        bounds = pair_flag(rest, "--区间")
        if bounds:
            low, high = float(as_number(bounds[0])), float(as_number(bounds[1]))
        if high <= low:
            raise ValueError("--区间 要递增, 比如 --区间 -10 10")
        left, right = (expression.split("=") + ["0"])[:2] if "=" in expression else (expression, "0")
        function = en.as_function(f"({left}) - ({right})")
        roots = en.find_roots(function, low, high)
        rows: list[tuple[str, str]] = [("方程", f"{left.strip()} = {right.strip()}")]
        if not roots:
            rows.append(("实根", f"区间 [{low:g}, {high:g}] 里没找到(扫描法只找实数根)"))
        else:
            for index, root in enumerate(roots, start=1):
                rows.append((f"根 {index}", f"x ≈ {root:.{digits}g}"))
        rows.append(("方法", f"[{low:g}, {high:g}] 上扫符号变化 + 二分, 只给近似值"))
        emit("solve 一元", rows)
        return 0
    if action == "线性":
        equations = [piece for piece in rest if "=" in piece]
        if len(equations) < 2:
            raise ValueError('线性方程组至少给两个方程, 每个都要带 "=", 比如 "2x+3y=7"')
        names = _variables_of(equations)
        coefficients, constants = _linear_system(equations, names)
        solution = en.gauss_solve(coefficients, constants)
        rows = [("方程", " / ".join(equations)), ("变量", ", ".join(names))]
        rows += [(name, en.fmt_full(value, digits)) for name, value in zip(names, solution)]
        rows.append(("成色", "精确(有理数高斯消元)"))
        emit("solve 线性", rows)
        return 0
    raise ValueError(f"solve 不认这个子动作: {action}")


def _variables_of(equations: Sequence[str]) -> list[str]:
    """从方程里抠出单字母变量(把函数名和常数剔掉)."""
    reserved = set(en.FUNCS) | set(en.CONSTS) | {"="}
    names: list[str] = []
    for piece in equations:
        for token in re.findall(r"[A-Za-z]+", piece):
            if token in reserved or len(token) > 6:
                continue
            for letter in token:
                if letter not in names and letter not in reserved:
                    names.append(letter)
    if not names:
        raise ValueError("没认出变量 —— 方程里请用单字母(如 x / y), 比如 \"2x + 3y = 7\"")
    return names


def _linear_system(equations: Sequence[str],
                   names: Sequence[str]) -> tuple[list[list[Fraction]], list[Fraction]]:
    """线性方程组抽系数: 用采样法(线性函数下是精确的, 顺便验一下它真是线性的)."""
    matrix: list[list[Fraction]] = []
    constants: list[Fraction] = []
    zero = Fraction(0)
    for piece in equations:
        left, _, right = piece.partition("=")
        text = f"({left}) - ({right or '0'})"
        origin: dict[str, en.Value] = {name: zero for name in names}
        base = as_fraction(en.evaluate(text, origin), f"常数项({piece.strip()})")
        row: list[Fraction] = []
        for name in names:
            probe: dict[str, en.Value] = {other: zero for other in names}
            probe[name] = Fraction(1)
            row.append(as_fraction(en.evaluate(text, probe), f"{name} 的系数") - base)
        probe = {other: zero for other in names}
        probe[names[0]] = Fraction(2)
        if as_fraction(en.evaluate(text, probe), "线性检查") - base != 2 * row[0]:
            raise ValueError(f"这个方程不是线性的: {piece.strip()}(线性方程组只收一次项)")
        matrix.append(row)
        constants.append(-base)
    if len(matrix) != len(names):
        raise ValueError(f"方程 {len(matrix)} 个, 变量 {len(names)} 个 —— 要对上才能解")
    return matrix, constants


# ============================================================
# 4. linalg —— 矩阵与线性代数
# ============================================================

def cmd_linalg(args: list[str]) -> int:
    need(args, 2, "linalg <行列式|逆|转置|乘|秩|解|特征值> <矩阵JSON> [矩阵JSON]")
    action, rest = args[0], args[1:]
    if action == "乘":
        need(rest, 2, "linalg 乘 <矩阵A> <矩阵B>")
        left, right = float_matrix(rest[0]), float_matrix(rest[1])
        if left.shape[1] != right.shape[0]:
            raise ValueError(f"矩阵尺寸对不上: {left.shape[1]} 列 vs {right.shape[0]} 行")
        emit("linalg 乘", [("A 形状", str(left.shape)), ("B 形状", str(right.shape)),
                           ("A×B", matrix_text(left @ right))])
        return 0
    need(rest, 1, "linalg <动作> <矩阵JSON>")
    matrix = float_matrix(rest[0])
    if action == "行列式":
        if matrix.shape[0] != matrix.shape[1]:
            raise ValueError("行列式要方阵")
        value = float(np.linalg.det(matrix))
        emit("linalg 行列式", [("形状", str(matrix.shape)), ("det", f"{value:.10g}")])
        return 0
    if action == "逆":
        if matrix.shape[0] != matrix.shape[1]:
            raise ValueError("求逆要方阵")
        emit("linalg 逆", [("形状", str(matrix.shape)), ("det", f"{float(np.linalg.det(matrix)):.10g}"),
                           ("A⁻¹", matrix_text(np.linalg.inv(matrix)))])
        return 0
    if action == "转置":
        emit("linalg 转置", [("形状", f"{matrix.shape} -> {matrix.T.shape}"),
                             ("Aᵀ", matrix_text(np.asarray(matrix.T, dtype=np.float64)))])
        return 0
    if action == "秩":
        emit("linalg 秩", [("形状", str(matrix.shape)),
                           ("秩", str(int(np.linalg.matrix_rank(matrix)))),
                           ("行列式(方阵才有)", f"{float(np.linalg.det(matrix)):.10g}"
                            if matrix.shape[0] == matrix.shape[1] else "非方阵")])
        return 0
    if action == "特征值":
        if matrix.shape[0] != matrix.shape[1]:
            raise ValueError("特征值要方阵")
        values = np.linalg.eigvals(matrix)
        text = ", ".join(f"{complex(value):.8g}" for value in values.tolist())
        emit("linalg 特征值", [("形状", str(matrix.shape)), ("特征值", text)])
        return 0
    if action == "解":
        need(rest, 2, "linalg 解 <系数矩阵> <右端向量>")
        coefficients, rhs = float_matrix(rest[0]), float_matrix(rest[1])
        solution = np.linalg.solve(coefficients, np.asarray(rhs, dtype=np.float64).reshape(-1))
        rows = [("A", str(coefficients.shape)), ("b", str(rhs.shape))]
        for index, value in enumerate(cast(list[float], solution.tolist()), start=1):
            rows.append((f"x{index}", f"{value:.10g}"))
        rows.append(("验证", f"A·x - b 最大偏差 {float(np.max(np.abs(coefficients @ solution - np.asarray(rhs, dtype=np.float64).reshape(-1)))):.3g}"))
        emit("linalg 解", rows)
        return 0
    raise ValueError(f"linalg 不认这个子动作: {action}")


# ============================================================
# 5. poly —— 多项式
# ============================================================

def cmd_poly(args: list[str]) -> int:
    need(args, 2, "poly <求值|加|减|乘|除|导数|积分|根> <系数> [参数]")
    action, rest = args[0], args[1:]
    if action == "求值":
        need(rest, 2, 'poly 求值 "[系数]" <x>')
        coefficients = en.poly_trim(frac_list(rest[0]))
        at = as_number(rest[1])
        value = Fraction(0)
        for coefficient in coefficients:
            value = value * at + coefficient
        emit("poly 求值", [("多项式", en.poly_text(coefficients)), ("x", en.fmt(at)),
                           ("f(x)", en.fmt_full(value))])
        return 0
    if action == "根":
        need(rest, 1, 'poly 根 "[系数]"')
        coefficients = en.poly_trim(frac_list(rest[0]))
        roots = np.roots([float(piece) for piece in coefficients])
        text = ", ".join(f"{complex(value):.10g}" for value in roots.tolist())
        emit("poly 根", [("多项式", en.poly_text(coefficients)), ("次数", str(len(coefficients) - 1)),
                         ("根(含复根)", text or "无")])
        return 0
    if action in ("加", "减", "乘", "除"):
        need(rest, 2, f'poly {action} "[系数A]" "[系数B]"')
        left, right = en.poly_trim(frac_list(rest[0])), en.poly_trim(frac_list(rest[1]))
        if action == "乘":
            result = en.poly_mul(left, right)
            emit("poly 乘", [("A", en.poly_text(left)), ("B", en.poly_text(right)),
                             ("A×B", en.poly_text(result))])
            return 0
        if action == "除":
            quotient, remainder = en.poly_divmod(left, right)
            emit("poly 除", [("被除式", en.poly_text(left)), ("除式", en.poly_text(right)),
                             ("商", en.poly_text(quotient)), ("余式", en.poly_text(remainder)),
                             ("校验", f"商×除式+余式 = {en.poly_text(en.poly_trim([value + (remainder[index] if index < len(remainder) else Fraction(0)) for index, value in enumerate(en.poly_mul(quotient, right))]))}")])
            return 0
        width = max(len(left), len(right))
        pad_left = [Fraction(0)] * (width - len(left)) + left
        pad_right = [Fraction(0)] * (width - len(right)) + right
        total = [a + b for a, b in zip(pad_left, pad_right)] if action == "加" else \
            [a - b for a, b in zip(pad_left, pad_right)]
        emit(f"poly {action}", [("A", en.poly_text(left)), ("B", en.poly_text(right)),
                                (f"A {'+' if action == '加' else '-'} B", en.poly_text(en.poly_trim(total)))])
        return 0
    if action == "导数":
        need(rest, 1, 'poly 导数 "[系数]" [阶数]')
        coefficients = en.poly_trim(frac_list(rest[0]))
        times = en.as_int(as_number(rest[1]), "阶数") if len(rest) > 1 else 1
        for _ in range(times):
            degree = len(coefficients) - 1
            coefficients = en.poly_trim([coefficient * (degree - index)
                                        for index, coefficient in enumerate(coefficients[:degree])]) \
                if degree >= 1 else [Fraction(0)]
        emit(f"poly {times} 阶导数", [("多项式", en.poly_text(en.poly_trim(frac_list(rest[0])))),
                                     ("导数", en.poly_text(coefficients))])
        return 0
    if action == "积分":
        need(rest, 1, 'poly 积分 "[系数]"')
        coefficients = en.poly_trim(frac_list(rest[0]))
        degree = len(coefficients) - 1
        primitives = [coefficient / (degree - index + 1) for index, coefficient in enumerate(coefficients)]
        emit("poly 积分", [("多项式", en.poly_text(coefficients)),
                           ("原函数(任意常数 C)", f"{en.poly_text(primitives + [Fraction(0)])} + C")])
        return 0
    raise ValueError(f"poly 不认这个子动作: {action}")


# ============================================================
# 6. calculus —— 导数 · 积分 · 极限 · 求和 · 连乘
# ============================================================

def cmd_calculus(args: list[str]) -> int:
    need(args, 2, 'calculus <导数|二阶导|积分|极限|求和|连乘> "<表达式>" ...')
    action, rest = args[0], args[1:]
    digits = digits_of(args)
    if action in ("导数", "二阶导"):
        need(rest, 2, f'calculus {action} "<f(x)>" <x0>')
        function = en.as_function(rest[0])
        at = float(as_number(rest[1]))
        value, wobble = en.numeric_derivative(function, at, 2 if action == "二阶导" else 1)
        emit(f"calculus {action}", [("f(x)", rest[0]), ("x0", f"{at:g}"),
                                    ("结果", f"{value:.{digits}g}"),
                                    ("稳定性", f"换步长再算差 {wobble:.3g}(越小越可靠)")])
        return 0
    if action == "积分":
        need(rest, 3, 'calculus 积分 "<f(x)>" <a> <b>')
        function = en.as_function(rest[0])
        low, high = float(as_number(rest[1])), float(as_number(rest[2]))
        value, error = en.adaptive_integral(function, low, high)
        emit("calculus 积分", [("f(x)", rest[0]), ("区间", f"[{low:g}, {high:g}]"),
                               ("结果", f"{value:.{digits}g}"),
                               ("误差估计", f"约 {error:.3g}(自适应 Simpson, 不是严格上界)")])
        return 0
    if action == "极限":
        need(rest, 2, 'calculus 极限 "<f(x)>" <x0>')
        function = en.as_function(rest[0])
        at = float(as_number(rest[1]))
        rows: list[tuple[str, str]] = [("f(x)", rest[0]), ("趋向", f"x -> {at:g}")]
        for side, sign in (("左", -1.0), ("右", 1.0)):
            series = [function(at + sign * step) for step in (1e-2, 1e-4, 1e-6, 1e-8)]
            rows.append((f"{side}逼近", " → ".join(f"{value:.{min(digits, 8)}g}" for value in series)))
        emit("calculus 极限", rows)
        return 0
    if action in ("求和", "连乘"):
        need(rest, 3, f'calculus {action} "<f(k)>" <起> <止>')
        expression, low_text, high_text = rest[0], rest[1], rest[2]
        low, high = en.as_int(as_number(low_text), "起点"), en.as_int(as_number(high_text), "终点")
        if high - low > 2_000_000 or high < low:
            raise ValueError("区间要递增, 且不超过 200 万项")
        total = Fraction(1 if action == "连乘" else 0)
        for index in range(low, high + 1):
            bindings: dict[str, en.Value] = {name: Fraction(index) for name in ("k", "n", "i")}
            piece = as_fraction(en.evaluate(expression, bindings), "通项")
            total = total * piece if action == "连乘" else total + piece
        emit(f"calculus {action}", [("通项", expression), ("范围", f"k = {low} ~ {high}"),
                                    ("结果", en.fmt_full(total, digits)),
                                    ("成色", en.kind_of(total))])
        return 0
    raise ValueError(f"calculus 不认这个子动作: {action}")


# ============================================================
# 7. stats —— 描述统计 · 相关 · 回归
# ============================================================

def cmd_stats(args: list[str]) -> int:
    need(args, 2, 'stats <描述|相关|回归> "<数据>" ["<数据2>"]')
    action, rest = args[0], args[1:]
    digits = digits_of(args)
    if action == "描述":
        data = number_list(rest[0])
        count = len(data)
        total = sum(data, Fraction(0))
        mean = total / count
        ordered = sorted(data)
        middle = count // 2
        median = ordered[middle] if count % 2 else (ordered[middle - 1] + ordered[middle]) / 2
        counts: dict[Fraction, int] = {}
        for value in data:
            counts[value] = counts.get(value, 0) + 1
        best = max(counts.values())
        modes = [value for value, times in counts.items() if times == best]
        spread = Fraction(0)
        for value in data:
            spread += (value - mean) ** 2
        sample_var = spread / (count - 1) if count > 1 else Fraction(0)
        population_var = spread / count

        def quartile(ratio: Fraction) -> Fraction:
            position = ratio * (count - 1)
            lower = int(position)
            upper = min(lower + 1, count - 1)
            weight = position - lower
            return ordered[lower] * (1 - weight) + ordered[upper] * weight

        emit("stats 描述", [
            ("个数", str(count)), ("和", en.fmt_full(total, digits)),
            ("均值", en.fmt_full(mean, digits)),
            ("中位数", en.fmt_full(median, digits)),
            ("众数", f"{', '.join(en.fmt(value) for value in modes)}(出现 {best} 次)"),
            ("最小 / 最大", f"{en.fmt(ordered[0])} / {en.fmt(ordered[-1])}"),
            ("极差", en.fmt(ordered[-1] - ordered[0])),
            ("样本方差", en.fmt_full(sample_var, digits)),
            ("样本标准差", en.fmt_full(en.sqrt_of(sample_var), digits)),
            ("总体方差", en.fmt_full(population_var, digits)),
            ("总体标准差", en.fmt_full(en.sqrt_of(population_var), digits)),
            ("Q1 / Q3", f"{en.fmt_full(quartile(Fraction(1, 4)), digits)} / {en.fmt_full(quartile(Fraction(3, 4)), digits)}"),
            ("IQR", en.fmt_full(quartile(Fraction(3, 4)) - quartile(Fraction(1, 4)), digits)),
        ])
        return 0
    if action == "相关":
        need(rest, 2, 'stats 相关 "<x 数据>" "<y 数据>"')
        xs = [float(value) for value in number_list(rest[0])]
        ys = [float(value) for value in number_list(rest[1])]
        if len(xs) != len(ys) or len(xs) < 2:
            raise ValueError("两组数据要一样长, 且至少 2 个点")
        array_x, array_y = np.array(xs), np.array(ys)
        emit("stats 相关", [("点数", str(len(xs))),
                            ("皮尔逊 r", f"{float(np.corrcoef(array_x, array_y)[0][1]):.{digits}g}"),
                            ("说明", "r 只量线性相关; 接近 0 不代表没关系")])
        return 0
    if action == "回归":
        need(rest, 2, 'stats 回归 "<x 数据>" "<y 数据>"')
        xs = [float(value) for value in number_list(rest[0])]
        ys = [float(value) for value in number_list(rest[1])]
        if len(xs) != len(ys) or len(xs) < 2:
            raise ValueError("两组数据要一样长, 且至少 2 个点")
        depth = np.polyfit(np.array(xs), np.array(ys), 1)
        slope, intercept = float(depth[0]), float(depth[1])
        predicted = slope * np.array(xs) + intercept
        residual = float(np.sum((np.array(ys) - predicted) ** 2))
        spread = float(np.sum((np.array(ys) - float(np.mean(ys))) ** 2))
        emit("stats 回归", [("点数", str(len(xs))),
                            ("拟合式", f"y = {slope:.{digits}g}·x "
                                      f"{'+' if intercept >= 0 else '-'} {abs(intercept):.{digits}g}"),
                            ("R²", f"{1 - residual / spread:.{digits}g}" if spread else "数据全等, 无意义"),
                            ("残差平方和", f"{residual:.6g}")])
        return 0
    raise ValueError(f"stats 不认这个子动作: {action}")


# ============================================================
# 8. prob —— 概率分布
# ============================================================

def _comb_int(n: int, k: int) -> Fraction:
    """组合数(C(n, k)), 精确整数."""
    return Fraction(math.comb(n, k))


def _binom_tail(n: int, probability: Fraction, at: int) -> Fraction:
    """P(X >= at) 精确算(分数)."""
    total = Fraction(0)
    for index in range(at, n + 1):
        total += _comb_int(n, index) * probability ** index * (1 - probability) ** (n - index)
    return total


def cmd_prob(args: list[str]) -> int:
    need(args, 2, "prob <二项|正态|泊松|几何> ...")
    action, rest = args[0], args[1:]
    digits = digits_of(args)
    if action == "二项":
        need(rest, 3, "prob 二项 <n> <p> <k>")
        times = en.as_int(as_number(rest[0]), "试验次数 n")
        probability = as_number(rest[1])
        hits = en.as_int(as_number(rest[2]), "命中次数 k")
        if not 0 <= probability <= 1:
            raise ValueError("概率 p 要在 0~1 之间")
        at_k = _comb_int(times, hits) * probability ** hits * (1 - probability) ** (times - hits)
        emit("prob 二项", [
            ("n / p / k", f"{times} / {en.fmt(probability)} / {hits}"),
            ("恰好 k 次", en.fmt_full(at_k, digits)),
            ("至多 k 次", en.fmt_full(_binom_tail(times, probability, 0) - _binom_tail(times, probability, hits + 1), digits)),
            ("至少 k 次", en.fmt_full(_binom_tail(times, probability, hits), digits)),
            ("期望 / 方差", f"{en.fmt(probability * times)} / {en.fmt(probability * (1 - probability) * times)}"),
        ])
        return 0
    if action == "正态":
        need(rest, 3, "prob 正态 <均值> <标准差> <x> [--区间 a b]")
        mean, deviation = float(as_number(rest[0])), float(as_number(rest[1]))
        if deviation <= 0:
            raise ValueError("标准差要大于 0")
        def cdf(x: float) -> float:
            return 0.5 * (1 + math.erf((x - mean) / (deviation * math.sqrt(2))))
        rows: list[tuple[str, str]] = [("均值 / 标准差", f"{mean:g} / {deviation:g}")]
        span = pair_flag(rest, "--区间")
        if span:
            low, high = float(as_number(span[0])), float(as_number(span[1]))
            rows.append(("P(a < X < b)", f"{cdf(high) - cdf(low):.{digits}g}"))
        else:
            x = float(as_number(rest[2]))
            rows += [("x", f"{x:g}"), ("P(X <= x)", f"{cdf(x):.{digits}g}"),
                     ("P(X >= x)", f"{1 - cdf(x):.{digits}g}"),
                     ("标准化 z", f"{(x - mean) / deviation:.{digits}g}")]
        rows.append(("方法", "标准正态 erf 精确到双精度"))
        emit("prob 正态", rows)
        return 0
    if action == "泊松":
        need(rest, 2, "prob 泊松 <λ> <k>")
        rate = float(as_number(rest[0]))
        hits = en.as_int(as_number(rest[1]), "次数 k")
        with localcontext() as ctx:
            ctx.prec = max(digits + 8, 34)
            exact = Decimal(-rate).exp() * Decimal(rate) ** hits / Decimal(math.factorial(hits))
            cumulative = sum((Decimal(-rate).exp() * Decimal(rate) ** index / Decimal(math.factorial(index))
                              for index in range(hits + 1)), Decimal(0))
        emit("prob 泊松", [("λ / k", f"{rate:g} / {hits}"),
                           ("P(X = k)", en.plain(exact, digits)),
                           ("P(X <= k)", en.plain(cumulative, digits)),
                           ("方法", f"高精度 Decimal 指数({en.prec} 位)")])
        return 0
    if action == "几何":
        need(rest, 2, "prob 几何 <p> <k>")
        probability = as_number(rest[0])
        hits = en.as_int(as_number(rest[1]), "第几次才成功 k")
        if not 0 < probability <= 1:
            raise ValueError("概率 p 要在 0~1 之间")
        value = (1 - probability) ** (hits - 1) * probability
        emit("prob 几何", [("p / k", f"{en.fmt(probability)} / {hits}"),
                           ("P(第 k 次才中)", en.fmt_full(value, digits))])
        return 0
    raise ValueError(f"prob 不认这个子动作: {action}")


CALC_HANDLERS.update({
    "calc": cmd_calc, "num": cmd_num, "solve": cmd_solve, "linalg": cmd_linalg,
    "poly": cmd_poly, "calculus": cmd_calculus, "stats": cmd_stats, "prob": cmd_prob,
})


if __name__ == "__main__":
    sys.exit(run(CALC_HANDLERS, sys.argv[1:]))
