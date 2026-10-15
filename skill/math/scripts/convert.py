#!/usr/bin/env python3
"""数学的另 4 个子命令 —— 换算与出图.

money   占比 · 折扣 · 涨跌 · 单利复利 · 月供      units   长度/质量/面积/…/温度 换算
plot    函数图 · 折线 · 散点 · 柱状(出 SVG)        date    日期差 · 推算 · 周几 · 第几周

★ 钱一律走 Decimal 高精度(不用 float): 0.1 元就是 0.1 元, 不带二进制尾巴.
★ 单位换算表里全是精确有理数(1 英里 = 1609.344 米 这种定值), 换出来是精确分数.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, timedelta
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path
from typing import Callable, Sequence, cast

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import engine as en  # noqa: E402
from cli import as_number, digits_of, emit, flag, need, run  # noqa: E402

LOG_DIR = HERE.parent / "logs"
CONVERT_HANDLERS: dict[str, Callable[[list[str]], int]] = {}

WEEKDAY = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def dec(text: str) -> Decimal:
    """文本 -> Decimal(钱的写法都在这儿进来)."""
    try:
        return Decimal(text.strip().replace(",", "").replace("，", ""))
    except Exception as error:
        raise ValueError(f"看不懂这个数: {text}") from error


def money_text(value: Decimal, digits: int) -> str:
    """金额打印: 去掉尾零, 不出现科学计数法."""
    with localcontext() as ctx:
        ctx.prec = max(digits + 4, 34)
        text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


# ============================================================
# 9. money —— 占比 · 折扣 · 涨跌 · 利息 · 月供
# ============================================================

def cmd_money(args: list[str]) -> int:
    need(args, 2, "money <占比|折扣|涨|跌|单利|复利|月供> ...")
    action, rest = args[0], args[1:]
    digits = digits_of(args)
    with localcontext() as ctx:
        ctx.prec = max(digits + 8, 34)
        if action == "占比":
            need(rest, 2, "money 占比 <部分> <整体>")
            part, whole = dec(rest[0]), dec(rest[1])
            if whole == 0:
                raise ValueError("整体不能是 0")
            emit("money 占比", [("部分 / 整体", f"{money_text(part, digits)} / {money_text(whole, digits)}"),
                                ("百分比", f"{money_text(part / whole * 100, digits)}%"),
                                ("倍数", money_text(part / whole, digits))])
            return 0
        if action == "折扣":
            need(rest, 2, "money 折扣 <原价> <折数>")
            price, rate = dec(rest[0]), dec(rest[1])
            if not 0 < rate <= 10:
                raise ValueError("折数按中文习惯写: 8 表示八折, 8.5 表示八五折")
            final = price * rate / 10
            emit("money 折扣", [("原价", money_text(price, digits)),
                                ("折扣", f"{money_text(rate, digits)} 折"),
                                ("现价", money_text(final, digits)),
                                ("省下", money_text(price - final, digits))])
            return 0
        if action in ("涨", "跌"):
            need(rest, 2, f"money {action} <原值> <百分比>")
            value, ratio = dec(rest[0]), dec(rest[1])
            delta = value * ratio / 100
            result = value + (delta if action == "涨" else -delta)
            emit(f"money {action}", [("原值", money_text(value, digits)),
                                     ("幅度", f"{action} {money_text(ratio, digits)}%"),
                                     ("变化量", money_text(delta, digits)),
                                     ("新值", money_text(result, digits))])
            return 0
        if action == "单利":
            need(rest, 3, "money 单利 <本金> <年利率%> <年数>")
            principal, rate, years = dec(rest[0]), dec(rest[1]), dec(rest[2])
            interest = principal * rate / 100 * years
            emit("money 单利", [("本金", money_text(principal, digits)),
                                ("年利率", f"{money_text(rate, digits)}%"),
                                ("年数", money_text(years, digits)),
                                ("利息", money_text(interest, digits)),
                                ("本息合计", money_text(principal + interest, digits))])
            return 0
        if action == "复利":
            need(rest, 3, "money 复利 <本金> <年利率%> <年数> [--每年追加 x] [--复利次数 m]")
            principal, rate, years_text = dec(rest[0]), dec(rest[1]), dec(rest[2])
            extra_text = flag(rest, "--每年追加", "0")
            times_text = flag(rest, "--复利次数", "1")
            extra, times = dec(extra_text or "0"), int(dec(times_text or "1"))
            years = int(years_text)
            if years < 0 or years > 500 or times < 1 or times > 365:
                raise ValueError("年数 0~500, 每年复利次数 1~365")
            grown, invested = principal, principal
            for _ in range(years):
                for _ in range(times):
                    grown = grown * (1 + rate / 100 / times)
                grown += extra
                invested += extra
            interest = grown - invested
            emit("money 复利", [("本金", money_text(principal, digits)),
                                ("年利率", f"{money_text(rate, digits)}%(每年复利 {times} 次)"),
                                ("年数 / 每年追加", f"{years} / {money_text(extra, digits)}"),
                                ("总投入", money_text(invested, digits)),
                                ("到期终值", money_text(grown, digits)),
                                ("其中利息", money_text(interest, digits)),
                                ("终值 / 投入", f"{money_text(grown / invested, digits)} 倍" if invested else "-")])
            return 0
        if action == "月供":
            need(rest, 3, "money 月供 <本金> <年利率%> <月数>")
            principal, rate, months_text = dec(rest[0]), dec(rest[1]), dec(rest[2])
            months = int(months_text)
            if months <= 0 or months > 1200:
                raise ValueError("月数要在 1~1200 之间")
            monthly_rate = rate / 100 / 12
            if monthly_rate == 0:
                payment = principal / months
            else:
                growth = (1 + monthly_rate) ** months
                payment = principal * monthly_rate * growth / (growth - 1)
            total = payment * months
            emit("money 月供", [("本金", money_text(principal, digits)),
                                ("年利率 / 期数", f"{money_text(rate, digits)}% / {months} 期"),
                                ("每月还款", money_text(payment, digits)),
                                ("总还款", money_text(total, digits)),
                                ("总利息", money_text(total - principal, digits)),
                                ("利息占比", f"{money_text((total - principal) / principal * 100, digits)}%")])
            return 0
    raise ValueError(f"money 不认这个子动作: {action}")


# ============================================================
# 10. units —— 单位换算
# ============================================================

UNITS: dict[str, dict[str, Fraction]] = {
    "长度": {"m": Fraction(1), "米": Fraction(1), "km": Fraction(1000), "千米": Fraction(1000),
             "公里": Fraction(1000), "dm": Fraction(1, 10), "cm": Fraction(1, 100),
             "厘米": Fraction(1, 100), "mm": Fraction(1, 1000), "毫米": Fraction(1, 1000),
             "um": Fraction(1, 1000000), "μm": Fraction(1, 1000000), "nm": Fraction(1, 10**9),
             "mi": Fraction("1609.344"), "英里": Fraction("1609.344"),
             "yd": Fraction("0.9144"), "码": Fraction("0.9144"),
             "ft": Fraction("0.3048"), "英尺": Fraction("0.3048"),
             "in": Fraction("0.0254"), "英寸": Fraction("0.0254"),
             "里": Fraction(500), "尺": Fraction(1, 3), "寸": Fraction(1, 30),
             "海里": Fraction(1852), "nmi": Fraction(1852)},
    "质量": {"kg": Fraction(1), "千克": Fraction(1), "公斤": Fraction(1), "g": Fraction(1, 1000),
             "克": Fraction(1, 1000), "mg": Fraction(1, 10**6), "t": Fraction(1000),
             "吨": Fraction(1000), "斤": Fraction(1, 2), "市斤": Fraction(1, 2),
             "两": Fraction(1, 20), "lb": Fraction("0.45359237"), "磅": Fraction("0.45359237"),
             "oz": Fraction("0.028349523125"), "盎司": Fraction("0.028349523125"),
             "ct": Fraction(1, 5000), "克拉": Fraction(1, 5000)},
    "面积": {"m2": Fraction(1), "平方米": Fraction(1), "km2": Fraction(10**6),
             "平方千米": Fraction(10**6), "cm2": Fraction(1, 10000),
             "ha": Fraction(10000), "公顷": Fraction(10000),
             "亩": Fraction(2000, 3), "ft2": Fraction("0.09290304"), "in2": Fraction("0.00064516"),
             "平方英里": Fraction("2589988.110336"), "平方英尺": Fraction("0.09290304")},
    "体积": {"L": Fraction(1), "升": Fraction(1), "mL": Fraction(1, 1000),
             "毫升": Fraction(1, 1000), "m3": Fraction(1000), "立方米": Fraction(1000),
             "cm3": Fraction(1, 1000), "立方厘米": Fraction(1, 1000),
             "gal": Fraction("3.785411784"), "加仑": Fraction("3.785411784"),
             "gal_uk": Fraction("4.54609"), "英制加仑": Fraction("4.54609"),
             "ft3": Fraction("28.316846592"), "立方英尺": Fraction("28.316846592")},
    "速度": {"m/s": Fraction(1), "米每秒": Fraction(1), "km/h": Fraction(5, 18),
             "千米每小时": Fraction(5, 18), "迈": Fraction(5, 18), "码每小时": Fraction(5, 18),
             "mph": Fraction("0.44704"), "英里每小时": Fraction("0.44704"),
             "节": Fraction("0.514444"), "knot": Fraction("0.514444"),
             "ft/s": Fraction("0.3048"), "马赫": Fraction("340.29")},
    "数据": {"B": Fraction(1), "字节": Fraction(1), "bit": Fraction(1, 8), "位": Fraction(1, 8),
             "KB": Fraction(1000), "MB": Fraction(10**6), "GB": Fraction(10**9),
             "TB": Fraction(10**12), "PB": Fraction(10**15),
             "KiB": Fraction(1024), "MiB": Fraction(1024**2), "GiB": Fraction(1024**3),
             "TiB": Fraction(1024**4), "PiB": Fraction(1024**5)},
    "时间": {"s": Fraction(1), "秒": Fraction(1), "min": Fraction(60), "分钟": Fraction(60),
             "h": Fraction(3600), "小时": Fraction(3600), "天": Fraction(86400),
             "day": Fraction(86400), "周": Fraction(604800), "week": Fraction(604800),
             "年": Fraction(31557600), "月": Fraction(2629800), "毫秒": Fraction(1, 1000),
             "ms": Fraction(1, 1000), "微秒": Fraction(1, 10**6), "us": Fraction(1, 10**6)},
    "压力": {"Pa": Fraction(1), "帕": Fraction(1), "kPa": Fraction(1000), "MPa": Fraction(10**6),
             "bar": Fraction(100000), "巴": Fraction(100000), "atm": Fraction(101325),
             "标准大气压": Fraction(101325), "mmHg": Fraction("133.322387415"),
             "毫米汞柱": Fraction("133.322387415"), "psi": Fraction("6894.757293168")},
    "能量": {"J": Fraction(1), "焦": Fraction(1), "kJ": Fraction(1000), "cal": Fraction("4.184"),
             "卡": Fraction("4.184"), "kcal": Fraction(4184), "大卡": Fraction(4184),
             "千卡": Fraction(4184), "kWh": Fraction(3600000), "度": Fraction(3600000),
             "eV": Fraction("1.602176634e-19"), "Wh": Fraction(3600)},
    "功率": {"W": Fraction(1), "瓦": Fraction(1), "kW": Fraction(1000), "千瓦": Fraction(1000),
             "MW": Fraction(10**6), "兆瓦": Fraction(10**6),
             "米制马力": Fraction("735.49875"), "英制马力": Fraction("745.6998715822702")},
    "角度": {"deg": Fraction(1), "度": Fraction(1), "rad": Fraction("57.29577951308232"),
             "弧度": Fraction("57.29577951308232"), "grad": Fraction("0.9"), "gradian": Fraction("0.9"),
             "圈": Fraction(360), "转": Fraction(360)},
}
TEMPERATURES = ("C", "℃", "摄氏", "F", "℉", "华氏", "K", "开尔文")


def _find_unit(name: str) -> tuple[str, Fraction] | None:
    """按名字找单位(同一名字只属于一类)."""
    for category, table in UNITS.items():
        if name in table:
            return category, table[name]
    return None


def _to_celsius(value: Fraction, name: str) -> Fraction:
    """温度归一到摄氏度(只有这三种是加减关系, 不进比率表)."""
    if name in ("C", "℃", "摄氏"):
        return value
    if name in ("F", "℉", "华氏"):
        return (value - 32) * Fraction(5, 9)
    return value - Fraction("273.15")


def _from_celsius(value: Fraction, name: str) -> Fraction:
    if name in ("C", "℃", "摄氏"):
        return value
    if name in ("F", "℉", "华氏"):
        return value * Fraction(9, 5) + 32
    return value + Fraction("273.15")


def cmd_units(args: list[str]) -> int:
    need(args, 1, "units <换算|温度|表> ...")
    action, rest = args[0], args[1:]
    digits = digits_of(args)
    if action == "表":
        wanted = rest[0] if rest else None
        for category, table in UNITS.items():
            if wanted and wanted != category:
                continue
            names = " · ".join(list(dict.fromkeys(table))[:14])
            print(f"[units 表] {category}: {names}")
        print("[units 表] 温度: C(摄氏) · F(华氏) · K(开尔文)")
        return 0
    if action == "换" or action == "换算":
        need(rest, 3, "units 换算 <数值> <源单位> <目标单位>")
        value = as_number(rest[0])
        source, target = rest[1].strip(), rest[2].strip()
        found_from, found_to = _find_unit(source), _find_unit(target)
        if found_from is None or found_to is None:
            raise ValueError(f"不认识这个单位(先看 units 表): {source if found_from is None else target}")
        if source in TEMPERATURES or target in TEMPERATURES:
            raise ValueError("温度换算用 units 温度 <数值> <源> <目标>")
        if found_from[0] != found_to[0]:
            raise ValueError(f"跨类换不了: {source} 属于 {found_from[0]}, {target} 属于 {found_to[0]}")
        result = value * found_from[1] / found_to[1]
        rows = [("输入", f"{en.fmt(value)} {source}"),
                ("换算", f"1 {source} = {en.fmt(found_from[1] / found_to[1])} {target}"),
                ("结果", f"{en.approximate(result, digits)} {target}")]
        if result.denominator != 1:
            rows.append(("精确值", en.fmt(result)))
        rows.append(("成色", en.kind_of(result)))
        emit("units 换算", rows)
        return 0
    if action == "温度":
        need(rest, 3, "units 温度 <数值> <源> <目标>")
        value = as_number(rest[0])
        source, target = rest[1].strip(), rest[2].strip()
        if source not in TEMPERATURES or target not in TEMPERATURES:
            raise ValueError("温度单位只认 C(摄氏) / F(华氏) / K(开尔文)")
        result = _from_celsius(_to_celsius(value, source), target)
        rows = [("输入", f"{en.fmt(value)} {source}"),
                ("结果", f"{en.approximate(result, digits)} {target}")]
        if result.denominator != 1:
            rows.append(("精确值", en.fmt(result)))
        rows.append(("成色", "精确"))
        emit("units 温度", rows)
        return 0
    raise ValueError(f"units 不认这个子动作: {action}")


# ============================================================
# 11. plot —— 出图(纯 SVG, 零依赖)
# ============================================================

WIDTH, HEIGHT = 1000, 640
LEFT, RIGHT, TOP, BOTTOM = 90, 40, 60, 70
BG, CARD, GRID, AXIS, LINE, TEXT, MUTED = "#0f0f0f", "#161616", "#1c1c1c", "#4a4a4a", "#4ade80", "#e8e8e8", "#8a8a8a"


def _tick_text(value: float) -> str:
    if value == 0:
        return "0"
    if abs(value) >= 1e5 or abs(value) < 1e-3:
        return f"{value:.3g}"
    return f"{value:.6g}"


def svg_chart(xs: Sequence[float], ys: Sequence[float], title: str, path: Path,
              kind: str = "line", labels: Sequence[str] | None = None) -> str:
    """画一张图: 折线 / 散点 / 柱状, 出 SVG(自带深色皮肤)."""
    if not xs:
        raise ValueError("没有可画的数据")
    xs = [float(value) for value in xs]
    ys = [float(value) for value in ys]
    low_x, high_x = min(xs), max(xs)
    low_y, high_y = min(ys + [0.0]), max(ys + [0.0])
    if high_x == low_x:
        low_x, high_x = low_x - 1, high_x + 1
    pad_x = (high_x - low_x) * 0.05
    low_x, high_x = low_x - pad_x, high_x + pad_x
    span_y = (high_y - low_y) or 1.0
    low_y, high_y = low_y - span_y * 0.08, high_y + span_y * 0.08
    width, height = WIDTH - LEFT - RIGHT, HEIGHT - TOP - BOTTOM

    def px(x_value: float) -> float:
        return LEFT + (x_value - low_x) / (high_x - low_x) * width

    def py(y_value: float) -> float:
        return TOP + (high_y - y_value) / (high_y - low_y) * height

    body: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" font-family="monospace">',
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="{BG}"/>',
        f'<rect x="{LEFT}" y="{TOP}" width="{width}" height="{height}" fill="{CARD}" stroke="{GRID}"/>',
        f'<text x="{WIDTH / 2:.0f}" y="34" fill="{TEXT}" font-size="20" text-anchor="middle">{title}</text>',
    ]
    for step in range(6):
        ratio = step / 5
        y_value = low_y + (high_y - low_y) * ratio
        y_pixel = py(y_value)
        body.append(f'<line x1="{LEFT}" y1="{y_pixel:.1f}" x2="{LEFT + width}" y2="{y_pixel:.1f}" stroke="{GRID}"/>')
        body.append(f'<text x="{LEFT - 12}" y="{y_pixel + 5:.1f}" fill="{MUTED}" font-size="13" '
                    f'text-anchor="end">{_tick_text(y_value)}</text>')
        x_value = low_x + (high_x - low_x) * ratio
        x_pixel = px(x_value)
        body.append(f'<line x1="{x_pixel:.1f}" y1="{TOP}" x2="{x_pixel:.1f}" y2="{TOP + height}" stroke="{GRID}"/>')
        body.append(f'<text x="{x_pixel:.1f}" y="{TOP + height + 24}" fill="{MUTED}" font-size="13" '
                    f'text-anchor="middle">{_tick_text(x_value)}</text>')
    if low_y < 0 < high_y:
        body.append(f'<line x1="{LEFT}" y1="{py(0):.1f}" x2="{LEFT + width}" y2="{py(0):.1f}" stroke="{AXIS}" stroke-width="1.5"/>')
    if low_x < 0 < high_x:
        body.append(f'<line x1="{px(0):.1f}" y1="{TOP}" x2="{px(0):.1f}" y2="{TOP + height}" stroke="{AXIS}" stroke-width="1.5"/>')
    if kind == "bar":
        names = list(labels or [])
        slot = width / max(len(xs), 1)
        for index, y_value in enumerate(ys):
            bar_x = px(xs[index]) - slot * 0.35
            top = py(max(y_value, 0.0))
            bottom = py(min(y_value, 0.0))
            body.append(f'<rect x="{bar_x:.1f}" y="{top:.1f}" width="{slot * 0.7:.1f}" '
                        f'height="{abs(bottom - top):.1f}" fill="{LINE}" opacity="0.75" rx="3"/>')
            if index < len(names):
                body.append(f'<text x="{bar_x + slot * 0.35:.1f}" y="{TOP + height + 46}" fill="{MUTED}" '
                            f'font-size="13" text-anchor="middle">{names[index]}</text>')
    else:
        points = " ".join(f"{px(x_value):.1f},{py(y_value):.1f}" for x_value, y_value in zip(xs, ys))
        if kind == "line" and len(xs) > 1:
            body.append(f'<polyline points="{points}" fill="none" stroke="{LINE}" stroke-width="2.2"/>')
        if kind in ("scatter", "line"):
            for x_value, y_value in zip(xs, ys):
                body.append(f'<circle cx="{px(x_value):.1f}" cy="{py(y_value):.1f}" r="3.4" fill="{LINE}"/>')
    body.append(f'<text x="{WIDTH - RIGHT}" y="{HEIGHT - 18}" fill="{MUTED}" font-size="13" '
                f'text-anchor="end">{len(xs)} 个点 · x[{low_x:.4g}, {high_x:.4g}] · y[{low_y:.4g}, {high_y:.4g}]</text>')
    body.append("</svg>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    return str(path)


def _out_path(rest: list[str], stem: str) -> Path:
    wanted = flag(rest, "-o", flag(rest, "--输出"))
    if wanted:
        return Path(wanted).expanduser()
    stamp = __import__("datetime").datetime.now().strftime("%Y%m%d-%H%M%S")
    return LOG_DIR / f"{stem}-{stamp}.svg"


def point_list(text: str) -> tuple[list[float], list[float]]:
    """点集: JSON [[x,y],…] 或 "x,y x,y" / "x,y;x,y"."""
    raw = text.strip()
    xs: list[float] = []
    ys: list[float] = []
    if raw.startswith("["):
        loaded = cast(object, json.loads(raw))
        for item in cast(list[object], loaded):
            cells = cast(list[object], item) if isinstance(item, list) else None
            if cells is None or len(cells) < 2:
                raise ValueError("点集要写成 [[x,y],[x,y],…]")
            xs.append(float(as_number(str(cells[0]))))
            ys.append(float(as_number(str(cells[1]))))
        return xs, ys
    for piece in [p for p in re.split(r"[;\s]+", raw) if p]:
        left, _, right = piece.partition(",")
        if not right:
            raise ValueError('点集要写成 "1,2 3,4" 或 [[1,2],[3,4]]')
        xs.append(float(as_number(left)))
        ys.append(float(as_number(right)))
    return xs, ys


def cmd_plot(args: list[str]) -> int:
    need(args, 2, 'plot <函数|折线|散点|柱状> ...')
    action, rest = args[0], args[1:]
    digits_of(args)          # 只为剥掉 --位数(画图用不上位数, 但别把它当成文件名)
    if action == "函数":
        need(rest, 3, 'plot 函数 "<f(x)>" <起> <止> [--点 N] [-o 文件.svg]')
        expression, low_text, high_text = rest[0], rest[1], rest[2]
        count_text = flag(rest, "--点", "400") or "400"
        low, high = float(as_number(low_text)), float(as_number(high_text))
        if high <= low:
            raise ValueError("起止要递增")
        count = max(2, min(int(count_text), 5000))
        function = en.as_function(expression)
        xs: list[float] = []
        ys: list[float] = []
        for index in range(count):
            x_value = low + (high - low) * index / (count - 1)
            try:
                y_value = function(x_value)
            except Exception:
                continue
            if abs(y_value) < 1e12 and y_value == y_value:
                xs.append(x_value)
                ys.append(y_value)
        path = _out_path(rest, "函数图")
        saved = svg_chart(xs, ys, f"f(x) = {expression}   x ∈ [{low:g}, {high:g}]", path)
        emit("plot 函数", [("表达式", expression), ("区间", f"[{low:g}, {high:g}]"),
                           ("采点", f"{len(xs)} 个(跳过无定义的点)"),
                           ("y 范围", f"[{min(ys):.6g}, {max(ys):.6g}]"),
                           ("文件", saved)])
        return 0
    if action in ("折线", "散点"):
        need(rest, 1, f'plot {action} "<点集>" [-o 文件.svg]')
        xs, ys = point_list(rest[0])
        path = _out_path(rest, action)
        saved = svg_chart(xs, ys, f"{action} · {len(xs)} 个点", path,
                          kind="line" if action == "折线" else "scatter")
        emit(f"plot {action}", [("点数", str(len(xs))),
                                ("x 范围", f"[{min(xs):.6g}, {max(xs):.6g}]"),
                                ("y 范围", f"[{min(ys):.6g}, {max(ys):.6g}]"),
                                ("文件", saved)])
        return 0
    if action == "柱状":
        need(rest, 1, 'plot 柱状 "标签=值,标签=值" [-o 文件.svg]')
        names: list[str] = []
        ys = []
        xs = []
        for piece in [p for p in re.split(r"[,;、]+", rest[0]) if p.strip()]:
            label, _, value = piece.partition("=")
            if not value:
                raise ValueError('柱状要写成 "标签=值,标签=值"')
            names.append(label.strip())
            ys.append(float(as_number(value)))
            xs.append(float(len(xs)))
        path = _out_path(rest, "柱状图")
        saved = svg_chart(xs, ys, f"柱状 · {len(names)} 项", path, kind="bar", labels=names)
        emit("plot 柱状", [("项数", str(len(names))),
                           ("最大 / 最小", f"{max(ys):.6g} / {min(ys):.6g}"),
                           ("文件", saved)])
        return 0
    raise ValueError(f"plot 不认这个子动作: {action} (试 函数 / 折线 / 散点 / 柱状)")


# ============================================================
# 12. date —— 日期与天数
# ============================================================

def parse_date(text: str) -> date:
    """认 2026-10-07 / 2026/10/7 / 20261007, 也认 今天 / 明天 / 昨天."""
    raw = text.strip()
    if raw in ("今天", "今日"):
        return date.today()
    if raw == "明天":
        return date.today() + timedelta(days=1)
    if raw in ("昨天", "昨日"):
        return date.today() - timedelta(days=1)
    cleaned = raw.replace("/", "-").replace(".", "-").replace("年", "-").replace("月", "-").replace("日", "")
    pieces = [piece for piece in cleaned.split("-") if piece]
    try:
        if len(pieces) == 3:
            return date(int(pieces[0]), int(pieces[1]), int(pieces[2]))
        if len(pieces) == 1 and len(pieces[0]) == 8:
            return date(int(pieces[0][:4]), int(pieces[0][4:6]), int(pieces[0][6:]))
    except ValueError as error:
        raise ValueError(f"日期看不懂: {text}") from error
    raise ValueError(f"日期要写成 2026-10-07 这样: {text}")


def workdays(low: date, high: date) -> int:
    """两个日子之间的工作日数(不含周末; 不含 high 当天)."""
    if high < low:
        low, high = high, low
    total = (high - low).days
    full_weeks, rest = divmod(total, 7)
    count = full_weeks * 5
    for step in range(rest):
        if (low.weekday() + step) % 7 < 5:
            count += 1
    return count


def cmd_date(args: list[str]) -> int:
    need(args, 1, "date <差|加|周几|今天> ...")
    action, rest = args[0], args[1:]
    if action == "今天":
        today = date.today()
        emit("date 今天", [("今天", today.isoformat()), ("星期", WEEKDAY[today.weekday()]),
                           ("今年第几天", str(today.timetuple().tm_yday)),
                           ("ISO 第几周", str(today.isocalendar().week))])
        return 0
    if action == "差":
        need(rest, 2, "date 差 <日期1> <日期2>")
        first, second = parse_date(rest[0]), parse_date(rest[1])
        delta = (second - first).days
        emit("date 差", [("从", first.isoformat()), ("到", second.isoformat()),
                         ("相差", f"{delta} 天(={abs(delta) / 7:.2f} 周)"),
                         ("工作日(不含周末)", f"{workdays(first, second)} 天"),
                         ("注意", "只是日子相减, 不含两端当天的时长")])
        return 0
    if action == "加":
        need(rest, 2, "date 加 <日期> <如 30天 / 2周 / 3月 / 1年>")
        start = parse_date(rest[0])
        text = rest[1].strip()
        match = re.match(r"^([+-]?\d+)\s*(天|日|周|星期|月|年|day|week|month|year)$", text)
        if not match:
            raise ValueError("单位只认 天 / 周 / 月 / 年, 比如 30天、2周、3月、1年")
        amount, unit = int(match.group(1)), match.group(2)
        if unit in ("天", "日", "day"):
            result = start + timedelta(days=amount)
        elif unit in ("周", "星期", "week"):
            result = start + timedelta(weeks=amount)
        elif unit in ("月", "month"):
            result = _shift_months(start, amount)
        else:
            result = _shift_months(start, amount * 12)
        emit("date 加", [("起始", f"{start.isoformat()} ({WEEKDAY[start.weekday()]})"),
                         ("加减", f"{amount:+d} {unit}"),
                         ("结果", f"{result.isoformat()} ({WEEKDAY[result.weekday()]})"),
                         ("相差", f"{(result - start).days} 天")])
        return 0
    if action == "周几":
        need(rest, 1, "date 周几 <日期>")
        day = parse_date(rest[0])
        emit("date 周几", [("日期", day.isoformat()), ("星期", WEEKDAY[day.weekday()]),
                           ("今年第几天", str(day.timetuple().tm_yday)),
                           ("ISO 第几周", str(day.isocalendar().week)),
                           ("是否闰年", "是" if _is_leap(day.year) else "不是")])
        return 0
    raise ValueError(f"date 不认这个子动作: {action} (试 差 / 加 / 周几 / 今天)")


def _is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _shift_months(start: date, months: int) -> date:
    """按月推算(日子超出就压到当月最后一天)."""
    total = start.year * 12 + (start.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    last = [31, 29 if _is_leap(year) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    return date(year, month, min(start.day, last))


CONVERT_HANDLERS.update({
    "money": cmd_money, "units": cmd_units, "plot": cmd_plot, "date": cmd_date,
})


if __name__ == "__main__":
    sys.exit(run(CONVERT_HANDLERS, sys.argv[1:]))
