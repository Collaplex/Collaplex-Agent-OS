#!/usr/bin/env python3
"""manifest.py —— 编排（任务编排 skill）的活儿单，落**冷库** PG 表 `orchestra`。

一份清单 = 一个对话一行（行键 = 对话id），值 = 条目列表。
为什么按对话分行：编排是「主 agent 在一轮对话里给自己排的活儿单」，
换对话就该是另一张单；一行一个对话，同时开两个对话也不会互相盖。

条目形状（字段名即模型可读的中文，不要翻译）：
    {"序号": 1, "说明": "勘察落点", "做法": "grep main.py 找接缝", "判据": "指出行号",
     "状态": "待做", "重试次数": 0, "产出": "", "起于": None, "终于": None}

状态四种：
    待做  —— 还没轮到
    在做  —— 框架刚把它递出去（一轮只递一件）
    好了  —— 做完且验收过了
    卡住  —— 重试到顶或主 agent 判定做不了（★ 不许静默跳过，要在清单里留痕）

★ 断电续干：清单落在库里，进程起来读回来接着推，不靠内存里的轮次。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, cast

import memory_store as 库

表 = "orchestra"
状态们 = ("待做", "在做", "好了", "卡住")
配置路径 = Path(__file__).resolve().parent / "config" / "orchestra.json"
_缺省: dict[str, Any] = {"单条上限": 20, "单条重试上限": 3, "对话_exec上限": 50, "重策划上限": 3}


def 配置() -> dict[str, Any]:
    """编排的档位都在 config/orchestra.json（缺文件就用缺省，不炸）。"""
    try:
        读: Any = json.loads(配置路径.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(_缺省)
    if not isinstance(读, dict):
        return dict(_缺省)
    return {**_缺省, **{str(k): v for k, v in cast(dict[str, Any], 读).items()}}


def 键(对话id: str) -> str:
    return str(对话id).strip() or "默认"


def _条目(序号: int, 说明: str, 做法: str = "", 判据: str = "") -> dict[str, Any]:
    return {
        "序号": int(序号),
        "说明": 说明.strip(),
        "做法": 做法.strip(),
        "判据": 判据.strip(),
        "状态": "待做",
        "重试次数": 0,
        "产出": "",
        "起于": None,
        "终于": None,
    }


def 建(对话id: str, 条目们: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """整份立单（盖掉这一对话原来的那份）。条目按给的顺序编序号。"""
    if not 条目们:
        raise ValueError("清单是空的 —— 攒到活儿再立单")
    上限 = int(配置().get("单条上限") or 20)
    if len(条目们) > 上限:
        raise ValueError(f"一张单最多 {上限} 件（现在 {len(条目们)} 件）—— 拆成两轮做")
    # ★ 换掉手里那张单 = 重策划（第一张不计）。到顶就拦住 —— 不把重排当逃避，推不动就标卡住。
    if 读(对话id):
        重排上限 = int(配置().get("重策划上限") or 3)
        次 = _加账(对话id, "重策划次数")
        if 次 > 重排上限:
            raise ValueError(
                f"重策划已经 {次} 次（上限 {重排上限}）—— 别再排了："
                "要么把手里这张单推完，要么把推不动的标「卡住」说清为什么")
    单: list[dict[str, Any]] = []
    for 位, 条 in enumerate(条目们, 1):
        单.append(_条目(位, str(条.get("说明") or ""),
                        str(条.get("做法") or ""), str(条.get("判据") or "")))
    if any(not 条["说明"] for 条 in 单):
        raise ValueError("有条目没写「说明」—— 清单里不许有无名活儿")
    库.写文档(表, 键(对话id), 单)
    return 单


def 读(对话id: str) -> list[dict[str, Any]]:
    """读这一对话的清单；没有就是空表（不抛）。"""
    原始: Any = 库.读文档(表, 键(对话id))
    if not isinstance(原始, list):
        return []
    return [dict(cast(dict[str, Any], 条)) for 条 in cast(list[Any], 原始) if isinstance(条, dict)]


def 下一件(对话id: str) -> dict[str, Any] | None:
    """下一件该干的：先捡「在做」（上一轮递出去没干完的），再捡「待做」。"""
    for 想要 in ("在做", "待做"):
        for 条 in 读(对话id):
            if str(条.get("状态")) == 想要:
                return 条
    return None


def 推进(对话id: str, 序号: int, 状态: str, 产出: str = "") -> dict[str, Any] | None:
    """标一件的状态（可带产出）。找不到那一件返回 None。"""
    if 状态 not in 状态们:
        raise ValueError(f"状态只能是 {'/'.join(状态们)}")
    单 = 读(对话id)
    改了: dict[str, Any] | None = None
    for 条 in 单:
        if int(条.get("序号") or 0) != int(序号):
            continue
        if 状态 == "在做" and 条.get("起于") is None:
            条["起于"] = time.time()
        if 状态 in ("好了", "卡住"):
            条["终于"] = time.time()
        if 产出:
            条["产出"] = 产出
        条["状态"] = 状态
        改了 = 条
        break
    if 改了 is not None:
        库.写文档(表, 键(对话id), 单)
    # ★ 全好了 = 这一单结束了 —— 整份撤掉（web 上那个框自己消失）。
    #   卡住的不算「好了」：留着让你看得见有事要处理，不许悄悄收走。
    if 改了 is not None and 单 and all(str(条.get("状态")) == "好了" for 条 in 单):
        库.删文档(表, 键(对话id))
        print(f"清单 {len(单)} 件全好了 —— 收工，web 面板自己消失")
        改了["单已收"] = True
    return 改了


def 重试一次(对话id: str, 序号: int) -> int:
    """给一件记一次重试，返回累计次数。★ 到 3 次就不再重试（事不过三），由调用方判定。"""
    单 = 读(对话id)
    次数 = 0
    for 条 in 单:
        if int(条.get("序号") or 0) == int(序号):
            条["重试次数"] = int(条.get("重试次数") or 0) + 1
            次数 = int(条["重试次数"])
            条["状态"] = "在做"
            break
    if 次数:
        库.写文档(表, 键(对话id), 单)
    return 次数


def 收工(对话id: str) -> int:
    """这一对话的清单整份撤掉（做完了 → web 上那个面板自己消失）。"""
    return 库.删文档(表, 键(对话id))


def 进度(对话id: str) -> tuple[int, int]:
    """(好了几件, 总共几件)。"""
    单 = 读(对话id)
    return sum(1 for 条 in 单 if str(条.get("状态")) == "好了"), len(单)


账表 = "对话账"


def _加账(对话键: str, 字段: str) -> int:
    账: Any = 库.读文档(账表, 键(对话键))
    本账: dict[str, Any] = dict(cast(dict[str, Any], 账)) if isinstance(账, dict) else {}
    本账[字段] = int(本账.get(字段) or 0) + 1
    本账["更新"] = time.time()
    库.写文档(账表, 键(对话键), 本账)
    return int(本账[字段])


def 记一次exec(对话键: str) -> int:
    """这一对话起了一次 exec 任务，返回累计次数（对话级闸用）。

    ★ 记「次数」不记「件数」：一件活儿重复重试也算多次 —— 闸的就是实际起了几次。
    """
    return _加账(对话键, "exec次数")


def 重策划次数(对话键: str) -> int:
    """这一对话重排过几次单（0 = 没排过）。"""
    账: Any = 库.读文档(账表, 键(对话键))
    if not isinstance(账, dict):
        return 0
    return int(cast(dict[str, Any], 账).get("重策划次数") or 0)


def exec次数(对话键: str) -> int:
    """这一对话已经起了几次 exec 任务（0 = 没记过）。"""
    账: Any = 库.读文档(账表, 键(对话键))
    if not isinstance(账, dict):
        return 0
    return int(cast(dict[str, Any], 账).get("exec次数") or 0)


def 清账(对话键: str) -> int:
    """把这一对话的账删掉（/new 开新对话时用）。"""
    return 库.删文档(账表, 键(对话键))


def 全单() -> dict[str, list[dict[str, Any]]]:
    """所有还挂着的清单（web 那个面板要按对话列）。表不在就是空。"""
    行 = 库.全部(表)
    出: dict[str, list[dict[str, Any]]] = {}
    for 键们, 值 in 行:
        出[str(键们)] = [dict(cast(dict[str, Any], 条)) for 条 in cast(list[Any], 值)
                        if isinstance(条, dict)]
    return 出
