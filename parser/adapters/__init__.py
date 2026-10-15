"""适配件登记处 —— **一家一个文件，各写各的，不共享可变状态、不靠调用顺序**。

这是"防玄学 bug"的那一半：A 家模型的处理写不到 B 家身上去。
另一半是 `parser/shell.py`（模型无关的最后一道，任何一家翻车它都兜）。

加一个模型：① 写 `适配件/<家族>.py`  ② 下面 `登记` 里加一行  ③ `config/parsing.json` 里给它几个关键词。
★ 没登记的家族 → 命中不了 → **直接走外壳**（不会因为"新模型没人适配"就丢内容）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from parser.adapters import deepseek, mimo, qwen3
from parser.adapters.shape import 适配件

登记: dict[str, 适配件] = {
    "deepseek": deepseek.件,
    "mimo": mimo.件,
    "qwen3": qwen3.件,
}

_关键词表: dict[str, list[str]] | None = None

# 项目根 = 本文件往上三级(适配件 → parser → 项目根)。★ 少算一级就会去 parser/config/ 找,
# 那份不存在 ⇒ 关键词表读成空 ⇒ **适配件一个都不生效**(登记了也等于没登记)。
_项目根 = Path(__file__).resolve().parent.parent.parent


def _读关键词表() -> dict[str, list[str]]:
    """从 config/parsing.json 读 家族 → 关键词。读不到就返回空表（等于全走外壳，不会炸）。"""
    global _关键词表
    if _关键词表 is not None:
        return _关键词表
    路径 = _项目根 / "config" / "parsing.json"
    try:
        原件: Any = json.loads(路径.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _关键词表 = {}
        return _关键词表
    干净: dict[str, list[str]] = {}
    if isinstance(原件, dict):
        表: Any = cast(dict[str, Any], 原件).get("关键词")
        if isinstance(表, dict):
            for 家族, 词 in cast(dict[str, Any], 表).items():
                if isinstance(词, list):
                    干净[str(家族)] = [str(每) for 每 in cast(list[Any], 词) if isinstance(每, str)]
    _关键词表 = 干净
    return _关键词表


def 找家族(模型: str) -> str:
    """模型名 → 家族名。命中不了返回 ""（= 只走外壳）。

    按**关键词**匹配，不按精确 id —— 别名、量化版、版本号换了照样命中；
    配上 `登记` 里没有的家族（只在 config 里写了、还没写适配件）也返回 ""（走外壳，安全）。
    """
    if not 模型:
        return ""
    名 = 模型.lower()
    for 家族, 词列表 in _读关键词表().items():
        if any(词.lower() in 名 for 词 in 词列表):
            return 家族 if 家族 in 登记 else ""
    return ""
