#!/usr/bin/env python3
"""math skill 的公共件 —— 参数取法 · 数据解析 · 输出格式.

compute.py(算) 和 convert.py(换算/出图) 都从这里拿:
    flag / digits_of / need   参数表里取选项、取位数、缺参数就报用法
    as_number / number_list   文本 -> 精确分数 / 一串数据
    emit                      统一的 "[标题] + 名字: 值" 输出

★ 输出格式统一在这里定: 别的脚本别自己 print 一套 —— 模型和人都按同一眼一眼读.
"""

from __future__ import annotations

import json
import re
import sys
from fractions import Fraction
from pathlib import Path
from typing import Callable, Sequence, cast

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import engine as en  # noqa: E402  (同目录的引擎)


def flag(args: list[str], name: str, default: str | None = None) -> str | None:
    """从参数表里取走 "--名字 值"; 没有就给默认值."""
    if name not in args:
        return default
    index = args.index(name)
    if index + 1 >= len(args):
        del args[index]
        raise ValueError(f"{name} 后面要给个值")
    value = args[index + 1]
    del args[index:index + 2]
    return value


def digits_of(args: list[str], default: int = 10) -> int:
    """--位数 / --小数 取一个 1~200 的位数, 顺便抬高 Decimal 精度."""
    text = flag(args, "--位数", flag(args, "--小数"))
    if text is None:
        return default
    got = int(text)
    if not 1 <= got <= 200:
        raise ValueError("位数要在 1~200 之间")
    en.set_precision(got)
    return got


def need(args: list[str], count: int, usage: str) -> list[str]:
    """参数不够就报用法(顺便兜底写错的命令)."""
    if len(args) < count:
        raise ValueError(f"用法: {usage}")
    return args


def pair_flag(args: list[str], name: str, default: tuple[str, str] | None = None
              ) -> tuple[str, str] | None:
    """取走 "--名字 值1 值2" 这种要两个值的选项(比如 --区间 -10 10)."""
    if name not in args:
        return default
    index = args.index(name)
    if index + 2 >= len(args):
        del args[index:]
        raise ValueError(f"{name} 后面要给两个值, 比如 {name} -10 10")
    values = (args[index + 1], args[index + 2])
    del args[index:index + 3]
    return values


def emit(title: str, rows: Sequence[tuple[str, str]]) -> None:
    """统一输出: 一行标题 + 若干 '名字: 值'."""
    print(f"[{title}]")
    for name, value in rows:
        print(f"  {name}: {value}")


def as_number(text: str) -> Fraction:
    """文本 -> 精确分数(十进制写法就是精确的十进制值, 不落二进制近似)."""
    try:
        return en.frac_of_text(text.strip())
    except Exception as error:
        raise ValueError(f"看不懂这个数: {text}") from error


def as_fraction(value: en.Value, what: str = "结果") -> Fraction:
    """要一个有理数: 这里不接受无理数结果(该走有理数的地方就得是有理数)."""
    if isinstance(value, Fraction):
        return value
    raise ValueError(f"{what}不是有理数({value}) —— 这一步只收有理数")


def number_list(text: str) -> list[Fraction]:
    """数据表: 支持 JSON 数组 / 逗号 / 空格 / 分号 / 顿号."""
    raw = text.strip()
    if raw.startswith("["):
        loaded = cast(object, json.loads(raw))
        if not isinstance(loaded, list):
            raise ValueError("数据要写成数组, 比如 [1, 2, 3]")
        return [as_number(str(item)) for item in cast(list[object], loaded)]
    parts = [piece for piece in re.split(r"[,;\s、]+", raw) if piece]
    if not parts:
        raise ValueError("没给数据")
    return [as_number(piece) for piece in parts]


def run(handlers: dict[str, Callable[[list[str]], int]], argv: Sequence[str]) -> int:
    """脚本入口: argv[0] 是动作名, 后面原样递给那一条.

    退出码: 0 算出来了 · 1 算不了(理由打印出来) · 2 动作名/用法不对.
    ★ 只把 ValueError/算数错误翻成中文原因; 别的异常照常抛 —— 那是真 bug, 别藏.
    """
    if not argv:
        print("[错误] 要给一个动作名", file=sys.stderr)
        return 2
    handler = handlers.get(argv[0])
    if handler is None:
        print(f"[错误] 不认识这个动作: {argv[0]}", file=sys.stderr)
        print("可选动作: " + " / ".join(handlers), file=sys.stderr)
        return 2
    try:
        return handler(list(argv[1:]))
    except ValueError as error:
        print(f"[算不了] {error}", file=sys.stderr)
        return 1
    except ArithmeticError as error:
        print(f"[算不了] 数学上出问题了: {error}", file=sys.stderr)
        return 1
