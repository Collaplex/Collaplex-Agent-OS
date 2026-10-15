#!/usr/bin/env python3
"""「过程」里的作业播报回归 —— 旧账不许当新闻念(老板 2026-10-09 抓出).

老板原话: "◉ 跑完 · 抓 B 站列表(12 秒) · 退出码 0 · 12 秒  这个怎么就定着了，是不是硬编码了"

查下来**不是硬编码**: 账(state/作业.json)是跨轮跨进程留着的, 那条是当天 18:15 留的自测活
(命令 `sleep 6; sleep 6` = 真 12 秒, 说明里当时也写了"(12 秒)" —— 两处 12 都是真数, 撞一块了)。
真毛病在**播报**: 每轮开场把账一扫, 上一轮(甚至昨天)就跑完的活被当成「刚刚发生」念一遍 ——
`跑了` 是 止于-起于 的终值, 不会再动, 看着就像硬编码。

规矩(web/bridge.py 看作业流 + 该报吗): 开场那一遍**只吐「在跑」的**; 这一轮里起、
这一轮里完的活照样吐(它在开场那次还没出现在账上)。旧账盖住时要**连不吐的一起记账**,
否则下一遍它又冒出来。

跑法: .venv/bin/python tests/test_job_notes.py
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Any

_根 = Path(__file__).resolve().parent.parent
for _p in (str(_根), str(_根 / "web")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import bridge  # noqa: E402


def 判据(名: str, 通过: bool, 说明: str = "") -> bool:
    print(f"  {'通过' if 通过 else '不过'}  {名}{('  ' + 说明) if 说明 else ''}")
    return 通过


def 活(号: str, 状态: str, 说明: str, 跑了: str = "12 秒", 退出码: int | None = 0) -> dict[str, Any]:
    return {"号": 号, "状态": 状态, "说明": 说明, "跑了": 跑了, "退出码": 退出码}


def 跑一段(每遍账: list[list[dict[str, Any]]], 遍数: int) -> list[str]:
    """按剧本喂 看作业流, 收它吐出来的行。

    剧本: 第 n 次对账返回 每遍账[n]; 攒够 遍数 后收手。每遍秒 调小, 以免测试要等 2 秒。
    """
    吐出的: list[str] = []
    停 = threading.Event()
    调用数 = [0]
    够了 = threading.Event()

    def 账源() -> list[dict[str, Any]]:
        第 = 调用数[0]
        调用数[0] += 1
        if 第 >= 遍数:
            够了.set()
            return 每遍账[-1]
        return 每遍账[第]

    def 吐(kind: str, text: str) -> None:
        if kind == "note":
            吐出的.append(text)

    线 = threading.Thread(target=bridge.看作业流, args=(吐, 停, 账源), kwargs={"每遍秒": 0.05}, daemon=True)
    线.start()
    if not 够了.wait(5.0):
        停.set()
        线.join(timeout=3.0)
        raise AssertionError("看作业流 没在 5 秒内对够账")
    停.set()
    线.join(timeout=3.0)
    return 吐出的


def 测_旧账不当新闻() -> list[bool]:
    """开场那一眼: 昨天就跑完的活 + 一个还在跑的活 —— 只该看见后者。"""
    旧 = 活("1009181533-d272b7", "跑完", "抓 B 站列表(12 秒)")
    在跑 = 活("1009200000-aaaaaa", "在跑", "重洗语料", 跑了="3 秒", 退出码=None)
    吐出 = 跑一段([[旧, 在跑], [旧, 在跑]], 遍数=2)
    return [
        判据("开场不念旧账(跑完的那条一个字都不出现)", not any("抓 B 站列表" in s for s in 吐出), f"吐了 {吐出}"),
        判据("开场照旧报「在跑」的", any(s == "◈ 起活 · 重洗语料" for s in 吐出)),
        判据("旧账不重复冒出来(第二遍也不念)", sum(1 for s in 吐出 if "抓 B 站列表" in s) == 0),
        判据("在跑的也不重复报(同一格只念一次)", sum(1 for s in 吐出 if "重洗语料" in s) == 1),
    ]


def 测_这轮跑完的照报() -> list[bool]:
    """开场之后才出现的「跑完」= 这一轮起的活, 必须报 —— 不要把开场那道闸修成一律不报终态。"""
    旧 = 活("1009181533-d272b7", "跑完", "抓 B 站列表(12 秒)")
    新的 = 活("1009300000-bbbbbb", "跑完", "算一下 123456789×987654321", 跑了="3 秒")
    吐出 = 跑一段([[旧], [旧, 新的], [旧, 新的]], 遍数=3)
    return [
        判据("这一轮跑完的活照报", any(s == "◉ 跑完 · 算一下 123456789×987654321 · 退出码 0 · 3 秒" for s in 吐出), f"吐了 {吐出}"),
        判据("旧账还是没被念", not any("抓 B 站列表" in s for s in 吐出)),
        判据("报过就不重复(第三遍不再吐)", sum(1 for s in 吐出 if "123456789" in s) == 1),
    ]


def 测_失败与停在也走同一道闸() -> list[bool]:
    """失败 / 停了 同样是终态 —— 开场不许念, 这轮里出现就得念。"""
    旧失败 = 活("1009181533-cccccc", "失败", "跑挂了的活", 退出码=1)
    在跑 = 活("1009200000-dddddd", "在跑", "重洗语料", 退出码=None)
    吐出 = 跑一段([[旧失败, 在跑], [旧失败, 在跑]], 遍数=2)
    return [
        判据("开场的旧失败也不念", not any("跑挂了" in s for s in 吐出), f"吐了 {吐出}"),
    ]


def main() -> int:
    print("作业播报回归 —— 过程里那几行是不是老老实实只说这一轮的事")
    结果: list[bool] = []
    结果 += 测_旧账不当新闻()
    结果 += 测_这轮跑完的照报()
    结果 += 测_失败与停在也走同一道闸()

    好 = sum(1 for row in 结果 if row)
    print(f"\n合计 {好}/{len(结果)} 通过")
    return 0 if 好 == len(结果) else 1


if __name__ == "__main__":
    raise SystemExit(main())
