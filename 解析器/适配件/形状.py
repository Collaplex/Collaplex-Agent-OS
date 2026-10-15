"""适配件长什么样 —— 一个 dataclass，够用就好，别加花样。

一家模型 = 一个 `适配件(...)` 实例（写在自己的 <家族>.py 里），登记进 `适配件/__init__.py`。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class 适配件:
    家族: str
    # (怪癖, 一次真踩过的证据) —— 写给人看，也给自测打印
    已知产出侧习惯: tuple[tuple[str, str], ...]
    # 剥掉这家的包装：正文 → (正文, 说明)。★ 不许在这里做通用兜底 —— 那是外壳的活
    特化: Callable[[str], tuple[str, str]]
