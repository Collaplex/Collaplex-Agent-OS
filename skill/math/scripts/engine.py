#!/usr/bin/env python3
"""数学计算的引擎 —— 值类型 / 表达式求值 / 数值算法 / 格式化.

三件事, 各管一段:
    值      有理数用 Fraction(精确, 不落浮点) · 无理数用 Decimal(按 --位数 给高精度)
    表达式  ast 白名单求值 —— 只认数字/运算符/白名单函数, 绝不 eval 任意字符串
    算法    求根 / 积分 / 极限 / 多项式 / 线性方程组 / 统计 的数值实现

★ 为什么不用 float 打底: 模型最常算错的一类就是"钱 / 比例 / 大数", 用 float 会算出
  0.30000000000000004 这种; 这里默认全走 Fraction, 1/3 + 1/6 就是 1/2.
★ 三角函数只有双精度(标准库 math), 输出的成色标记会写明, 不要把它当 20 位精确值用.
"""

from __future__ import annotations

import ast
import math
import re
from decimal import Decimal, localcontext
from fractions import Fraction
from typing import Callable, Sequence

Value = Fraction | Decimal

prec = 34                    # Decimal 有效位下限(够 30 位输出, 不虚耗)
_vars: dict[str, Value] = {}  # 表达式里的自由变量(如 x / k), 由调用方注入
FUNCS: dict[str, Callable[..., Value]] = {}
CONSTS: dict[str, Value] = {}


# ============================================================
# 值: Fraction(精确) 或 Decimal(高精度)
# ============================================================

def set_precision(digits: int) -> None:
    """按要显示的位数抬高 Decimal 精度(留 8 位余量, 以免末位是舍入噪声)."""
    global prec
    prec = max(34, digits + 8)


def to_dec(value: Value) -> Decimal:
    """转 Decimal(精度由调用方所在的 localcontext 决定)."""
    if isinstance(value, Decimal):
        return value
    return Decimal(value.numerator) / Decimal(value.denominator)


def dec_of(number: float) -> Decimal:
    """双精度结果转 Decimal —— 按 repr 转, 保留它真实的有效位(不假装更精确)."""
    return Decimal(repr(number))


def frac_of_text(text: str) -> Fraction:
    """十进制字面量 -> 精确分数: 0.1 就是 1/10, 不是二进制近似."""
    return Fraction(Decimal(text))


def dop(a: Value, b: Value, fn: Callable[[Decimal, Decimal], Decimal]) -> Decimal:
    """Decimal 路: 在 prec 位上下文里算."""
    with localcontext() as ctx:
        ctx.prec = prec
        return fn(to_dec(a), to_dec(b))


def unary(value: Value, fn: Callable[[Decimal], Decimal]) -> Decimal:
    """Decimal 路的一元函数."""
    with localcontext() as ctx:
        ctx.prec = prec
        return fn(to_dec(value))


def is_zero(value: Value) -> bool:
    return value == 0


def as_int(value: Value, what: str = "这个数") -> int:
    """要一个整数: 不是整数就如实报错(不悄悄取整)."""
    if isinstance(value, Fraction):
        if value.denominator == 1:
            return int(value.numerator)
        raise ValueError(f"{what}得是整数, 给的是 {value.numerator}/{value.denominator}")
    if value == value.to_integral_value():
        return int(value)
    raise ValueError(f"{what}得是整数, 给的是 {value}")


# --- Decimal 的运算(写成具名函数, 以免 lambda 的类型推不出来) ---

def _d_add(a: Decimal, b: Decimal) -> Decimal:
    return a + b


def _d_sub(a: Decimal, b: Decimal) -> Decimal:
    return a - b


def _d_mul(a: Decimal, b: Decimal) -> Decimal:
    return a * b


def _d_div(a: Decimal, b: Decimal) -> Decimal:
    return a / b


def _d_mod(a: Decimal, b: Decimal) -> Decimal:
    return a % b


def _d_pow(a: Decimal, b: Decimal) -> Decimal:
    """幂: 整数次直接乘; 分数次走 exp(b·ln a) —— 比 float 那把多十几位."""
    if b == b.to_integral_value() and abs(b) < 100000:
        return a ** int(b)
    if a <= 0:
        raise ValueError("底数不是正数时, 分数次幂不在实数范围里")
    return (b * a.ln()).exp()


# ============================================================
# 表达式: ast 白名单
# ============================================================

_THOUSANDS = re.compile(r"\d{1,3}(?:,\d{3})+(?![\d,])")
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)%(?![\d=])")      # 百分号要紧贴数字: "50%" 是百分数, "10 % 3" 是取模
_FACTORIAL = re.compile(r"(\d+(?:\.\d+)?)!(?!\s*=)")     # 数学写法的阶乘: 170! -> factorial(170)


def _part_of_name(text: str, index: int, char: str) -> bool:
    """index 前面那串数字是不是某个名字的一部分 —— log2 的 2 / 0xFF 的 x / 1e3 的 e 都算.

    ★ 这条是给隐式乘法把关的: 少了它, log2(8) 会被掰成 log2*(8) （已踩坑）.
    """
    cursor = index - 1
    while cursor >= 0 and text[cursor].isdigit():
        cursor -= 1
    start = cursor + 1
    if char in "xXbBoO" and text[start:index] == "0":
        return True                                        # 进制前缀 0x / 0b / 0o
    if char in "eE" and text[start:index].isdigit() and text[index + 1:index + 2].isdigit():
        return True                                        # 科学计数 1e3
    return cursor >= 0 and (text[cursor].isalpha() or text[cursor] in "._")


def insert_implicit_mul(text: str) -> str:
    """给 2x / 2(x+1) / (x+1)(x-1) / (x+1)2 补上乘号(只在紧挨着的时候补)."""
    out: list[str] = []
    for index, char in enumerate(text):
        previous = text[index - 1] if index else ""
        if previous and not char.isspace() and not previous.isspace():
            need = False
            if char in "([":
                need = (previous.isdigit() or previous == ")") and not _part_of_name(text, index, char)
            elif char.isalpha():
                need = previous == ")" or (previous.isdigit() and not _part_of_name(text, index, char))
            elif char.isdigit():
                need = previous == ")"
            if need:
                out.append("*")
        out.append(char)
    return "".join(out)


def normalize(expr: str) -> str:
    """把数学写法掰成 Python 写法: × ÷ ^ 全角 · 千分位 · 百分号 · 阶乘 · 隐式乘法."""
    text = expr.strip()
    for old, new in (("×", "*"), ("÷", "/"), ("−", "-"), ("–", "-"), ("（", "("), ("）", ")"),
                     ("，", ","), ("^", "**"), ("**", "^")):
        text = text.replace(old, new)
    text = text.replace("^", "**")
    text = _PERCENT.sub(r"(\1/100)", text)
    text = _FACTORIAL.sub(r"factorial(\1)", text)
    text = _THOUSANDS.sub(lambda match: match.group(0).replace(",", ""), text)
    return insert_implicit_mul(text)


def _eval(node: ast.AST) -> Value:
    """递归求值: 认什么、不认什么都在这里定死."""
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant):
        raw = node.value
        if isinstance(raw, bool):
            raise ValueError("布尔值不在计算范围里")
        if isinstance(raw, int):
            return Fraction(raw)
        if isinstance(raw, float):
            return frac_of_text(repr(raw))
        raise ValueError(f"不认这个常量: {raw!r}")
    if isinstance(node, ast.Name):
        if node.id in _vars:
            return _vars[node.id]
        if node.id in CONSTS:
            return CONSTS[node.id]
        if node.id in FUNCS:
            raise ValueError(f"{node.id} 是函数, 后面要跟括号, 比如 {node.id}(2)")
        raise ValueError(f"不认识的符号: {node.id}")
    if isinstance(node, ast.UnaryOp):
        operand = _eval(node.operand)
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return operand
        if isinstance(node.op, ast.Invert):
            return Fraction(~as_int(operand, "取反的数"))
        raise ValueError("只支持 正 / 负 / 按位取反")
    if isinstance(node, ast.BinOp):
        return _binop(node.op, _eval(node.left), _eval(node.right))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCS:
            raise ValueError("只能调用白名单里的函数")
        if node.keywords:
            raise ValueError("函数不支持关键字参数")
        return FUNCS[node.func.id](*[_eval(arg) for arg in node.args])
    raise ValueError(f"不支持的写法: {type(node).__name__}")


def _binop(op: ast.operator, a: Value, b: Value) -> Value:
    """二元运算: 两个都是 Fraction 就精确算, 有一个是 Decimal 就走高精度."""
    if isinstance(op, ast.Add):
        return a + b if isinstance(a, Fraction) and isinstance(b, Fraction) else dop(a, b, _d_add)
    if isinstance(op, ast.Sub):
        return a - b if isinstance(a, Fraction) and isinstance(b, Fraction) else dop(a, b, _d_sub)
    if isinstance(op, ast.Mult):
        return a * b if isinstance(a, Fraction) and isinstance(b, Fraction) else dop(a, b, _d_mul)
    if isinstance(op, ast.Div):
        if is_zero(b):
            raise ValueError("除数是 0")
        return a / b if isinstance(a, Fraction) and isinstance(b, Fraction) else dop(a, b, _d_div)
    if isinstance(op, ast.FloorDiv):
        if is_zero(b):
            raise ValueError("除数是 0")
        return Fraction(as_int(a, "整除左边") // as_int(b, "整除右边"))
    if isinstance(op, ast.Mod):
        if is_zero(b):
            raise ValueError("模 0 没有意义")
        return a % b if isinstance(a, Fraction) and isinstance(b, Fraction) else dop(a, b, _d_mod)
    if isinstance(op, ast.Pow):
        if isinstance(a, Fraction) and isinstance(b, Fraction) and b.denominator == 1:
            power = int(b.numerator)
            if abs(power) > 100000:
                raise ValueError("指数太大(超过 10 万), 换小一点的")
            if power < 0 and is_zero(a):
                raise ValueError("0 的负数次幂没有意义")
            return a ** power
        return dop(a, b, _d_pow)
    if isinstance(op, ast.BitAnd):
        return Fraction(as_int(a, "位运算左边") & as_int(b, "位运算右边"))
    if isinstance(op, ast.BitOr):
        return Fraction(as_int(a, "位运算左边") | as_int(b, "位运算右边"))
    if isinstance(op, ast.BitXor):
        return Fraction(as_int(a, "位运算左边") ^ as_int(b, "位运算右边"))
    if isinstance(op, ast.LShift) or isinstance(op, ast.RShift):
        left, right = as_int(a, "位移的数"), as_int(b, "位移位数")
        if not 0 <= right <= 4096:
            raise ValueError("移位次数要在 0~4096 之间")
        return Fraction(left << right) if isinstance(op, ast.LShift) else Fraction(left >> right)
    raise ValueError("不支持的运算符")


def evaluate(expr: str, variables: dict[str, Value] | None = None) -> Value:
    """算一个表达式. variables 给了就能带符号(如 x), 否则只认常数."""
    global _vars
    saved, _vars = _vars, dict(variables or {})
    try:
        text = normalize(expr)
        try:
            tree = ast.parse(text, mode="eval")
        except SyntaxError as error:
            raise ValueError(f"表达式看不懂: {text} ({error.msg})") from error
        return _eval(tree)
    finally:
        _vars = saved


def as_function(expr: str) -> Callable[[float], float]:
    """把表达式包成 f(x) -> float, 给求根 / 积分 / 画面用(那里双精度够)."""
    def call(x: float) -> float:
        return float(evaluate(expr, {"x": frac_of_text(repr(x))}))
    return call


# ============================================================
# 白名单函数(int 语义的走整数, 无理的走 Decimal, 三角的走双精度)
# ============================================================

def _f_abs(x: Value) -> Value:
    return x if x >= 0 else -x


def _f_sqrt(x: Value) -> Value:
    if x < 0:
        raise ValueError("负数开平方不在实数范围里")
    if isinstance(x, Fraction):
        num, den = math.isqrt(x.numerator), math.isqrt(x.denominator)
        if num * num == x.numerator and den * den == x.denominator:
            return Fraction(num, den)
    return unary(x, lambda d: d.sqrt())


def _f_cbrt(x: Value) -> Value:
    return dec_of(math.copysign(abs(float(x)) ** (1 / 3), float(x)))


def _f_exp(x: Value) -> Value:
    return unary(x, lambda d: d.exp())


def _f_ln(x: Value) -> Value:
    if x <= 0:
        raise ValueError("对数的真数要大于 0")
    return unary(x, lambda d: d.ln())


def _f_log(x: Value, base: Value | None = None) -> Value:
    if base is None:
        return _f_ln(x)
    if base <= 0 or base == 1:
        raise ValueError("对数的底要大于 0 且不等于 1")
    return dop(_f_ln(x), _f_ln(base), _d_div)


def _f_round(x: Value, digits: Value | None = None) -> Value:
    if digits is None:
        return Fraction(round(float(x)))
    with localcontext() as ctx:
        ctx.prec = prec
        step = Decimal(1).scaleb(-as_int(digits, "保留位数"))
        return to_dec(x).quantize(step)


def _f_sign(x: Value) -> Value:
    return Fraction((x > 0) - (x < 0))


def sqrt_of(value: Value) -> Value:
    """对外可直接调的开方: 完全平方给精确分数, 否则给高精度小数."""
    return _f_sqrt(value)


def _f_min(*xs: Value) -> Value:
    return min(xs)


def _f_max(*xs: Value) -> Value:
    return max(xs)


def _f_hypot(*xs: Value) -> Value:
    return dec_of(math.hypot(*[float(value) for value in xs]))


def _f_gcd(*xs: Value) -> Value:
    return Fraction(math.gcd(*[as_int(value, "gcd 的参数") for value in xs]))


def _f_lcm(*xs: Value) -> Value:
    return Fraction(math.lcm(*[as_int(value, "lcm 的参数") for value in xs]))


def _f_factorial(x: Value) -> Value:
    got = as_int(x, "阶乘的参数")
    if got < 0 or got > 100000:
        raise ValueError("阶乘只支持 0~100000 的整数")
    return Fraction(math.factorial(got))


def _f_comb(n: Value, k: Value) -> Value:
    return Fraction(math.comb(as_int(n, "组合数 n"), as_int(k, "组合数 k")))


def _f_perm(n: Value, k: Value) -> Value:
    return Fraction(math.perm(as_int(n, "排列数 n"), as_int(k, "排列数 k")))


def _f_atan2(y: Value, x: Value) -> Value:
    with localcontext() as ctx:
        ctx.prec = prec
        return dec_of(math.atan2(float(y), float(x)))


def _f_sin(x: Value) -> Value:
    return dec_of(math.sin(float(x)))


def _f_cos(x: Value) -> Value:
    return dec_of(math.cos(float(x)))


def _f_tan(x: Value) -> Value:
    return dec_of(math.tan(float(x)))


def _f_asin(x: Value) -> Value:
    if x < -1 or x > 1:
        raise ValueError("反正弦的输入要在 -1~1 之间")
    return dec_of(math.asin(float(x)))


def _f_acos(x: Value) -> Value:
    if x < -1 or x > 1:
        raise ValueError("反余弦的输入要在 -1~1 之间")
    return dec_of(math.acos(float(x)))


def _f_atan(x: Value) -> Value:
    return dec_of(math.atan(float(x)))


def _f_sinh(x: Value) -> Value:
    return dec_of(math.sinh(float(x)))


def _f_cosh(x: Value) -> Value:
    return dec_of(math.cosh(float(x)))


def _f_tanh(x: Value) -> Value:
    return dec_of(math.tanh(float(x)))


def _f_degrees(x: Value) -> Value:
    return dec_of(math.degrees(float(x)))


def _f_radians(x: Value) -> Value:
    return dec_of(math.radians(float(x)))


def _f_floor(x: Value) -> Value:
    return Fraction(math.floor(float(x)))


def _f_ceil(x: Value) -> Value:
    return Fraction(math.ceil(float(x)))


def _f_log10(x: Value) -> Value:
    return _f_log(x, Fraction(10))


def _f_log2(x: Value) -> Value:
    return _f_log(x, Fraction(2))


def build_funcs() -> None:
    """一次性注册白名单函数(名字 -> 实现)."""
    decimal_consts: dict[str, str] = {
        "pi": "3.14159265358979323846264338327950288419716939937510582097494459",
        "e": "2.71828182845904523536028747135266249775724709369995957496696763",
        "tau": "6.28318530717958647692528676655900576839433879875021164194988918",
    }
    for name, text in decimal_consts.items():
        CONSTS[name] = Decimal(text)
    CONSTS["inf"] = Decimal("Infinity")
    FUNCS.update({
        "abs": _f_abs, "sqrt": _f_sqrt, "cbrt": _f_cbrt,
        "exp": _f_exp, "ln": _f_ln, "log": _f_log,
        "log10": _f_log10, "log2": _f_log2,
        "sin": _f_sin, "cos": _f_cos, "tan": _f_tan,
        "asin": _f_asin, "acos": _f_acos, "atan": _f_atan, "atan2": _f_atan2,
        "sinh": _f_sinh, "cosh": _f_cosh, "tanh": _f_tanh,
        "degrees": _f_degrees, "radians": _f_radians,
        "floor": _f_floor, "ceil": _f_ceil,
        "round": _f_round, "sign": _f_sign,
        "min": _f_min, "max": _f_max, "hypot": _f_hypot,
        "gcd": _f_gcd, "lcm": _f_lcm,
        "factorial": _f_factorial, "comb": _f_comb, "perm": _f_perm,
    })


build_funcs()


# ============================================================
# 格式化: 精确 / 近似 说清楚
# ============================================================

def plain(value: Decimal, digits: int) -> str:
    """Decimal -> 定点字符串, 去掉尾零(不出现 1E+21 这种)."""
    if value.is_nan() or value.is_infinite():
        return str(value)
    with localcontext() as ctx:
        ctx.prec = max(digits + 2, 34)
        text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def fmt(value: Value, digits: int = 10) -> str:
    """一个值 -> 给人看的字符串: 整数给整数, 分数给分数, 小数给小数."""
    if isinstance(value, Fraction):
        if value.denominator == 1:
            whole = str(value.numerator)
            return f"{whole} (共 {len(whole.lstrip('-'))} 位)" if len(whole.lstrip("-")) > 21 else whole
        return f"{value.numerator}/{value.denominator}"
    return plain(value, digits)


def approximate(value: Value, digits: int = 10) -> str:
    """小数近似(精确分数也给出小数形式, 便于对照量级)."""
    with localcontext() as ctx:
        ctx.prec = max(digits + 8, 34)
        return plain(to_dec(value), digits)


def fmt_full(value: Value, digits: int = 10) -> str:
    """分数 + 小数一起给: "3/7 (约 0.4285714286)"; 整数只给整数."""
    if isinstance(value, Fraction) and value.denominator == 1:
        return fmt(value, digits)
    if isinstance(value, Decimal):
        return f"{fmt(value, digits)}"
    return f"{fmt(value, digits)} (约 {approximate(value, digits)})"


def kind_of(value: Value) -> str:
    """这个结果是什么成色 —— 输出的 [精确/近似] 标记靠它."""
    return "精确" if isinstance(value, Fraction) else "近似"


# ============================================================
# 数值算法
# ============================================================

def find_roots(f: Callable[[float], float], low: float, high: float,
               steps: int = 2000) -> list[float]:
    """区间内找实根: 扫符号变化 + 二分收敛(不用导数, 对折点也稳)."""
    roots: list[float] = []
    width = (high - low) / steps
    previous_x, previous_y = low, f(low)
    for index in range(1, steps + 1):
        x = low + width * index
        y = f(x)
        if y == 0.0:
            roots.append(x)
        elif previous_y * y < 0:
            left, right, value_left = previous_x, x, previous_y
            for _ in range(200):
                middle = (left + right) / 2
                value_middle = f(middle)
                if value_middle == 0.0 or right - left < 1e-15:
                    break
                if value_left * value_middle < 0:
                    right = middle
                else:
                    left, value_left = middle, value_middle
            roots.append((left + right) / 2)
        previous_x, previous_y = x, y
    merged: list[float] = []
    for root in roots:
        if not merged or abs(root - merged[-1]) > max(1e-9, abs(root) * 1e-9):
            merged.append(root)
    return merged


def adaptive_integral(f: Callable[[float], float], low: float, high: float,
                      depth: int = 24) -> tuple[float, float]:
    """自适应 Simpson: 返回 (值, 误差估计) —— 误差是两次细分之差, 不是严格上界."""
    def simpson(a: float, b: float, fa: float, fm: float, fb: float) -> float:
        return (b - a) * (fa + 4 * fm + fb) / 6

    def refine(a: float, b: float, fa: float, fm: float, fb: float,
               whole: float, eps: float, left: int) -> tuple[float, float]:
        middle = (a + b) / 2
        left_middle, right_middle = (a + middle) / 2, (middle + b) / 2
        flm, frm = f(left_middle), f(right_middle)
        head = simpson(a, middle, fa, flm, fm)
        tail = simpson(middle, b, fm, frm, fb)
        delta = head + tail - whole
        if left <= 0 or abs(delta) <= 15 * eps:
            return head + tail + delta / 15, abs(delta) / 15
        got_head, err_head = refine(a, middle, fa, flm, fm, head, eps / 2, left - 1)
        got_tail, err_tail = refine(middle, b, fm, frm, fb, tail, eps / 2, left - 1)
        return got_head + got_tail, err_head + err_tail

    middle = (low + high) / 2
    fa, fm, fb = f(low), f(middle), f(high)
    return refine(low, high, fa, fm, fb, simpson(low, high, fa, fm, fb), 1e-10, depth)


def numeric_derivative(f: Callable[[float], float], at: float,
                       order: int = 1, width: float = 1e-5) -> tuple[float, float]:
    """中心差分(一阶 / 二阶) + 换个步长再算一次, 两次差多少就是稳定性指标."""
    def once(step: float) -> float:
        if order == 1:
            return (f(at + step) - f(at - step)) / (2 * step)
        return (f(at + step) - 2 * f(at) + f(at - step)) / (step * step)

    first = once(width)
    second = once(width * 10)
    return first, abs(first - second)


def gauss_solve(matrix: list[list[Fraction]], rhs: list[Fraction]) -> list[Fraction]:
    """有理数高斯消元(带选主元) —— 线性方程组给精确解, 不是浮点近似."""
    size = len(rhs)
    rows = [list(row) + [rhs[index]] for index, row in enumerate(matrix)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(rows[row][column]))
        if rows[pivot][column] == 0:
            raise ValueError("系数矩阵奇异 —— 这个方程组没有唯一解")
        rows[column], rows[pivot] = rows[pivot], rows[column]
        head = rows[column][column]
        rows[column] = [value / head for value in rows[column]]
        for other in range(size):
            if other == column:
                continue
            factor = rows[other][column]
            if factor:
                rows[other] = [value - factor * rows[column][index]
                               for index, value in enumerate(rows[other])]
    return [rows[index][size] for index in range(size)]


def poly_trim(coefficients: Sequence[Fraction]) -> list[Fraction]:
    """去掉高次那头的零(全零保留一个 0)."""
    out = list(coefficients)
    while len(out) > 1 and out[0] == 0:
        out.pop(0)
    return out


def poly_text(coefficients: Sequence[Fraction], variable: str = "x") -> str:
    """降幂打印: 3x^2 + 2x - 1."""
    terms: list[str] = []
    degree = len(coefficients) - 1
    for index, coefficient in enumerate(coefficients):
        power = degree - index
        if coefficient == 0:
            continue
        sign = "-" if coefficient < 0 else ("+" if terms else "")
        size = abs(coefficient)
        number = "" if size == 1 and power else fmt(size)
        body = f"{'*' if number else ''}{variable}" if power else ""
        terms.append(f"{sign} {number}{body}{f'^{power}' if power > 1 else ''}".strip())
    return " ".join(terms) or "0"


def poly_mul(a: Sequence[Fraction], b: Sequence[Fraction]) -> list[Fraction]:
    """多项式乘法(降幂系数)."""
    out = [Fraction(0)] * (len(a) + len(b) - 1)
    for i, left in enumerate(a):
        for j, right in enumerate(b):
            out[i + j] += left * right
    return out


def poly_divmod(a: Sequence[Fraction],
                b: Sequence[Fraction]) -> tuple[list[Fraction], list[Fraction]]:
    """多项式带余除法: a = 商 * b + 余(降幂系数)."""
    dividend = list(a)
    divisor = poly_trim(b)
    if divisor == [Fraction(0)]:
        raise ValueError("除式是 0")
    if len(dividend) < len(divisor):
        return [Fraction(0)], poly_trim(dividend)
    quotient = [Fraction(0)] * (len(dividend) - len(divisor) + 1)
    while len(dividend) >= len(divisor) and dividend != [Fraction(0)]:
        shift = len(dividend) - len(divisor)
        factor = dividend[0] / divisor[0]
        quotient[len(quotient) - 1 - shift] = factor
        for index, value in enumerate(divisor):
            dividend[index] -= factor * value
        dividend = poly_trim(dividend)
    return poly_trim(quotient), poly_trim(dividend)
