"""解析器自测 —— 逐家 × 逐样本对「期望正文」，不用起 web、不用起模型。

跑法: `./.venv/bin/python 解析器/自测.py`

★ 这份自测是「防玄学」真正靠的东西：改了某一家的适配件，就跑这一家那份样本 ——
  过了才能说"只动了我家、没碰别家"。样本是**真踩过的脏原文**（`解析器/样本/<家族>.jsonl`），
  每条一行 JSON：名字 / 原文 / 期望正文 / 要说明。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from 解析器 import 取干净  # noqa: E402  (先把项目根塞进 sys.path 才能 import)

样本目录 = Path(__file__).resolve().parent / "样本"

# 关键词匹配的判据：真模型 id（别名/量化版换了也得命中）→ 该落哪家；"" = 该只走外壳
关键词用例: tuple[tuple[str, str], ...] = (
    ("qwen3-vl-8b", "qwen3"),
    ("Qwen3-VL-8B-Instruct-Q4_K_M.gguf", "qwen3"),
    ("deepseek-v4-flash", "deepseek"),
    ("mimo-v2.5", "mimo"),
    ("glm-4.6v-flash", ""),   # 没登记适配件 -> 只走外壳(安全, 不许炸)
    ("", ""),                  # 名字都没给 -> 只走外壳
)


def 读样本(路径: Path) -> list[dict[str, Any]]:
    """一行一条 JSON。坏行直接报出来，别静默跳过。"""
    条: list[dict[str, Any]] = []
    for 序号, 行 in enumerate(路径.read_text(encoding="utf-8").splitlines(), 1):
        if not 行.strip():
            continue
        try:
            原件: Any = json.loads(行)
        except json.JSONDecodeError as 错:
            raise SystemExit(f"{路径.name} 第 {序号} 行不是合法 JSON: {错}") from 错
        if not isinstance(原件, dict):
            raise SystemExit(f"{路径.name} 第 {序号} 行不是对象")
        条.append(cast(dict[str, Any], 原件))
    return 条


def 跑一家(家族: str, 路径: Path) -> tuple[int, int, list[str]]:
    """跑一家那份样本，返回 (过, 总, 失败说明)。"""
    过 = 0
    失败: list[str] = []
    条 = 读样本(路径)
    for 每 in 条:
        名 = str(每.get("名字", "?"))
        原文 = str(每.get("原文", ""))
        期望正文 = str(每.get("期望正文", ""))
        要说明 = bool(每.get("要说明", False))
        得 = 取干净(原文, 家族)
        问题: list[str] = []
        if 得.正文 != 期望正文:
            问题.append(f"正文 得={得.正文!r} 期望={期望正文!r}")
        if bool(得.说明) != 要说明:
            问题.append(f"说明 得={得.说明!r} 要说明={要说明}")
        if 得.家族 != 家族:
            问题.append(f"家族 得={得.家族!r} 期望={家族!r}")
        if 问题:
            失败.append(f"{家族} / {名}: " + "; ".join(问题))
            print(f"  ✗ {家族} · {名}")
        else:
            过 += 1
            print(f"  ✓ {家族} · {名}")
    return 过, len(条), 失败


def 跑关键词() -> list[str]:
    """模型名 → 家族：对不上就是"填了模型却没加载对应解析"，会静默退化成只走外壳。"""
    失败: list[str] = []
    for 模型, 期望 in 关键词用例:
        得 = 取干净("正文", 模型).家族
        if 得 != 期望:
            失败.append(f"找家族({模型!r}) 得={得!r} 期望={期望!r}")
    return 失败


def 主() -> int:
    print("解析器自测（不用起 web、不用起模型）")
    文件 = sorted(样本目录.glob("*.jsonl"))
    if not 文件:
        print(f"✗ {样本目录} 里一份样本都没有 —— 这层等于没防玄学")
        return 1

    总数 = 0
    过数 = 0
    失败: list[str] = []
    for 路径 in 文件:
        家族 = 路径.stem
        print(f"\n[{家族}] {路径.name}")
        过, 总, 这家失败 = 跑一家(家族, 路径)
        过数 += 过
        总数 += 总
        失败 += 这家失败

    print("\n[关键词] 模型名 → 家族")
    if not 跑关键词():
        print(f"  ✓ {len(关键词用例)} 条都命中（含没登记的走外壳、空名字走外壳）")
    else:
        失败 += 跑关键词()
        for 一条 in 失败[-len(关键词用例):]:
            print(f"  ✗ {一条}")

    print(f"\n结果: {过数}/{总数} 条样本过 · 失败 {len(失败)} 条")
    for 一条 in 失败:
        print(f"  ✗ {一条}")
    return 1 if 失败 else 0


if __name__ == "__main__":
    raise SystemExit(主())
