"""解析外壳 —— 模型无关的那一层。

它只管一件事：**不许丢内容、不许静默**。

里面**没有任何模型知识** —— 一家的习惯放 `parser/adapters/<家族>.py`，各写各的。
没有适配件也照样能活（直接走这层），这就是保险：新模型接进来没适配过，
最坏也只是"剥得不漂亮"，不会"整轮凭空消失"。

2026-10-11 立：模型偶尔把**整段回答**塞进 ```json 围栏里，原来的做法是从围栏那儿切、
切完得空串，下游 `if 正文.strip()` 一不成立就什么都不做 —— 不显示、不记账、连"没答"都不说。
所以"整段被围栏吃掉"是一种**要交代的情况**，不是"无事发生"。
"""

from __future__ import annotations

import json
from typing import Any, cast


def 找尾部JSON起点(text: str) -> int | None:
    """找末尾那段 json 的起点（字符下标）; 没有返回 None.

    skill 的约定是"先输出 md 回答, 最后再输出 json" —— 模型会给那段套个 ```json
    围栏, 直接认这个围栏就行。取最后一个: 正文里就算夹着同款, 末尾那个也只会更靠后。
    模型偶尔会在 ```json 前面多吐一个空围栏, 一起藏掉。
    """
    index = text.rfind("```json")
    if index == -1:
        return None
    head = text[:index]
    if head.rstrip("\n").endswith("```"):
        # 前面多吐的那个空围栏, 连它那一行的行首一起收
        index = head.rfind("\n", 0, head.rfind("```")) + 1
    return index


def 围栏内容(text: str) -> str:
    """把第一段 ``` 围栏里的东西抠出来（末尾那段 json 标记就长这样）。"""
    起 = text.find("```")
    if 起 == -1:
        return ""
    换行 = text.find("\n", 起)
    if 换行 == -1:
        return ""
    尾 = text.find("```", 换行)
    return text[换行 + 1 :] if 尾 == -1 else text[换行 + 1 : 尾]


def 从JSON里捞正文(块: str) -> str:
    """整段被围栏吃掉时，试着从那个 json 里把答案捞出来（认几个常见键）。"""
    try:
        数据: Any = json.loads(块.strip())
    except (json.JSONDecodeError, ValueError):
        return ""
    if not isinstance(数据, dict):
        return ""
    表 = cast(dict[str, Any], 数据)
    for 键 in ("回答", "答案", "正文", "内容", "说明", "answer", "text", "content"):
        值 = 表.get(键)
        if isinstance(值, str) and 值.strip():
            return 值.strip()
    return ""


def 把关(净: str, 原文: str) -> tuple[str, str]:
    """特化之后过一遍 —— 净空了就回原文兜底，**绝不返回空**（除非模型真一个字没吐）。

    返回 (正文, 说明)：说明非空 = 走了兜底，调用方该把这句话报给界面/终端。
    ★ 这一层的意义就是"不管上一步（适配件）把文本弄成什么样，这里都不许让一轮问答消失"。
    """
    if 净.strip():
        return 净.rstrip(), ""
    if not 原文.strip():
        # 模型真一个字都没吐 —— 也要有交代, 别让调用方自己去猜"是空还是坏了"
        return "", "模型这轮一个字都没吐出来"
    捞出来 = 从JSON里捞正文(围栏内容(原文))
    if 捞出来:
        return 捞出来, "模型这轮把回答整段写进了 json 块 —— 已把它里面的内容捞出来显示"
    return 原文.strip(), "模型这轮没写正文、整段只吐了 json 块 —— 已原样端出来，别当它没答"


def 捞正文(text: str) -> tuple[str, str]:
    """正文 + 末尾 json 标记 → 给人看的正文。返回 (正文, 说明)。

    单独调它 = 只走外壳（没经过适配件），给老调用点用。
    """
    起点 = 找尾部JSON起点(text)
    净 = text if 起点 is None else text[:起点]
    return 把关(净, text)
