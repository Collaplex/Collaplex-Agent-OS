#!/usr/bin/env python3
"""pending_injection.py —— 框架「下一轮开场说什么」的通道（落冷库 PG 表 inbox）。

为什么要有它
    定时到点要叫醒主 agent（「闹钟响了」），编排每推完一件也要把主 agent 叫回来推下一件
    （「下一件：xxx」）。两条来源、一个口子 —— 否则各写各的，开场注入只认得一边。

一条 = 一行（按对话键分行，值是一坨列表）；取走即标掉，不会重复注入。
    - 放(对话键, 来源, 文本)      —— 谁都能往里丢
    - 取(对话键) -> str | None    —— 框架开场调一次：先来先走
★ 断电不丢：东西在库里，进程起来照样能取到。
"""
from __future__ import annotations

import time
from typing import Any, cast

import memory_store as 库

表 = "inbox"


def 键(对话键: str) -> str:
    return str(对话键).strip() or "cli"


def _读(对话键: str) -> list[dict[str, Any]]:
    原始: Any = 库.读文档(表, 键(对话键))
    if not isinstance(原始, list):
        return []
    return [dict(cast(dict[str, Any], 条)) for 条 in cast(list[Any], 原始) if isinstance(条, dict)]


def 放(对话键: str, 来源: str, 文本: str) -> None:
    """丢一条进去（来源写清楚是谁放的：定时 / 编排 / 手塞）。"""
    单 = _读(对话键)
    单.append({"来源": str(来源), "文本": str(文本), "放入": time.time(), "拿走": False})
    库.写文档(表, 键(对话键), 单)


def 取(对话键: str) -> str | None:
    """拿最老的一条没拿走的（拿走的标掉，不会重复注入）。没有返回 None。"""
    单 = _读(对话键)
    for 条 in 单:
        if not 条.get("拿走"):
            条["拿走"] = True
            条["拿于"] = time.time()
            库.写文档(表, 键(对话键), 单)
            return str(条.get("文本") or "")
    return None


def 剩几条(对话键: str) -> int:
    return sum(1 for 条 in _读(对话键) if not 条.get("拿走"))


def 清(对话键: str) -> int:
    """把这一对话的注入箱整份删掉（/new 或者收尾时用）。"""
    return 库.删文档(表, 键(对话键))
