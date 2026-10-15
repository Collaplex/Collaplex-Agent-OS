#!/usr/bin/env python3
"""框架侧的定时任务接缝 —— 主 agent 这一侧怎么用 skill/timer。

三件事:
- 重挂(): 进程起来时读回表、过期条目补一次、有活就把定时器线程起起来(线程在**本进程**里)
- 取待办(): 每轮开场拉一次 —— 到点的搬出来, 拼成给主 agent 的开场话(非阻塞那条路)
- 等阻塞(条): 这一轮登记了阻塞式(「就在这等着」) -> 框架就在这一轮里等, 每秒回调读秒

★ 线程为什么在框架进程: skill 子进程登记完就退, 起不了线程。
★ 提醒为什么是「拉」式: 到点先标「到点待注入」, 由 取待办() 在下一轮开场交付 ——
  线程没起着、进程刚重启过, 都不会漏(表里状态说了算)。
★ 阻塞式到点: 等() 收尾时自己会把它标成「到点待注入」, 于是下一轮开场就把它交回主 agent ——
  无需另设一条「叫醒」通道。
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from typing import Any, Callable

根 = Path(__file__).resolve().parent
sys.path.insert(0, str(根 / "skill" / "timer" / "scripts"))

import 引擎 as _引擎  # noqa: E402 - 得先把 skill 目录挂上

import 作业  # noqa: E402 - 同目录的根件: 长活的账

表名 = "定时"


def 进程(名字: str) -> None:
    """这个进程占库里哪一行: web / cli. 在框架启动时点一次（同一张表，一行一个进程）。"""
    os.environ["COLLAPLEX_TIMER_PROCESS"] = 名字


def 开一轮() -> str:
    """给这一轮打个记号, 记进环境 —— 这一轮里登记的定时条目都会带上它.

    ★ 为什么不用「登记时刻 > 本轮起点」识别本轮: 登记发生在 **skill 子进程**里, 它的钟
      跟框架各锚各的(加速/假时钟下完全不可比); 记号跟着环境走, 两边对得上.
    """
    记号 = uuid.uuid4().hex[:8]
    os.environ["COLLAPLEX_TIMER_TURN"] = 记号
    return 记号


def 现在() -> float:
    """框架侧的「现在」(墙钟). 交付/判过期都用它这一个口径."""
    return _引擎.墙钟()


def 重挂() -> dict[str, Any]:
    """进程起来时调一次：读回库里的账、过期条目补一次、有活就起线程。"""
    return _兜("重挂", {"表": "?", "刚响": 0, "挂着": 0, "线程": False}, _引擎.重挂)


def 取待办() -> str | None:
    """这一轮开场要交给主 agent 的话: 到点的提醒 + 跑完了的作业结果。没有就 None。

    ★ 作业为什么走这里(2026-10-09 老板定): 起一个长活、「延时让它跑完、然后看结果」——
      跑完那一刻没人叫醒主 agent, 所以跟提醒一样由下一轮开场「拉」: 取出结果(退出码 +
      日志尾)、当场标成交付过。进程重启、这一轮没跑都不丢, 账说了算。
    """
    段 = [_引擎.提醒话(条) for 条 in _兜("取到点的", [], _引擎.捡待注入)]
    for 条 in 作业.待交付():
        段.append(作业.结果话(条))
        作业.交掉(str(条.get("号") or ""))
    if not 段:
        return None
    return "\n".join(段)


def _兜(动作: str, 默认: Any, 做: Callable[[], Any]) -> Any:
    """冷库不通时不让框架崩掉 —— 打一行中文，返回安全默认值。

    为什么框架侧要兜而 skill 侧要炸：skill 那边静默当空表会把别人的条目覆盖掉（要炸出来），
    框架这边只是读一次、读不到也不应拦住启动。
    """
    try:
        return 做()
    except Exception as 错:                     # noqa: BLE001 - 冷库怎么坏都可能
        print(f"[定时] 冷库不通（{动作}）：{错}")
        return 默认


def 本轮的阻塞条目(轮记号: str) -> list[dict[str, Any]]:
    """这一轮(带这个记号)登记的、还挂着、阻塞式的条目."""
    return [条 for 条 in _引擎.列出()
            if 条.get("阻塞") and str(条.get("轮记号") or "") == 轮记号]


def 等阻塞(条: dict[str, Any], 每秒: Callable[[float], None] | None = None) -> str | None:
    """阻塞式等到点(每秒回调读秒). 到点返回提醒话; 被撤了返回 None."""
    if _引擎.等(条, 每秒):
        return _引擎.提醒话(条)
    return None


def 重新计时(条: dict[str, Any]) -> bool:
    """阻塞式倒计时: 从「框架开始等」这一刻重新起算(见引擎里的说明)."""
    return _引擎.重新计时(条)


def 剩余说法(秒: float) -> str:
    return _引擎.剩余说法(秒)


def 到点说法(条: dict[str, Any]) -> str:
    return _引擎.到点说法(条)


def 列出() -> list[dict[str, Any]]:
    return _引擎.列出()


def 撤销(编号: str | None, 最近: bool = False) -> tuple[dict[str, Any] | None, str]:
    return _引擎.撤销(编号, 最近)


def 表() -> str:
    """账落在冷库哪张表（web 与 CLI 同一张表、各占一行）。"""
    return _引擎.表名()


def 行键() -> str:
    """这一进程占哪一行（进程键）。"""
    return _引擎.进程键()


def 线程活着() -> bool:
    return _引擎.线程活着()


def 停线程() -> bool:
    return _引擎.停线程()
