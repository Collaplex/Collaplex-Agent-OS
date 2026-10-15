#!/usr/bin/env python3
"""读回件探针：**全部不用 JSON 契约**，把结构责任全交给一个专用读回件。

老板的方案（2026-10-13）：*"其实全部可以不用 json，只要在后面放一个专用模型就可以去除装饰
拿到主语就能分析意图然后代替 json，而且不会出现模型不输出我们要求的键。"*

和 `translate_probe.py` 的区别：那个是把三级**规则**（抠 JSON / 关键词）串起来、模型翻译只做兜底；
这个是**只用一个专用读回件**（`tests/skill_styles/readback.md`，指令 + 手写 few-shot），
一次读回，看"专用化"能把准确率抬到哪 —— 这就是"用专用件代替 JSON 契约"的上限估计。

**离线复评**：直接吃三份已有 jsonl 里的原始输出（不再重跑上游模型），只花读回件的调用。

跑法:
    .venv/bin/python tests/readback_probe.py                  # 本地 8B, 全部三版
    .venv/bin/python tests/readback_probe.py --模型 mimo       # 换云模型当读回件
    .venv/bin/python tests/readback_probe.py --只 20           # 抽样前 20 条(冒烟)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, cast

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path.insert(0, str(PROJECT))

from openai import OpenAI  # noqa: E402

import sub_agent  # noqa: E402

本地端口 = "http://127.0.0.1:8790/v1"
材料目录 = HERE / "skill_styles"
数据源 = [
    ("现行-说话", "logs/对照-翻译件-现行-说话-20261013.jsonl"),
    ("钢印-说话", "logs/对照-翻译件-钢印-说话-20261013.jsonl"),
    ("叙事（老周）", "logs/对照-叙事翻译-20261013.jsonl"),
]


def 本地客户端() -> OpenAI:
    摘 = {k: os.environ.pop(k) for k in list(os.environ)
          if k.lower() in ("http_proxy", "https_proxy", "all_proxy")}
    try:
        return OpenAI(api_key="local", base_url=本地端口)
    finally:
        os.environ.update(摘)


def 本地模型名() -> str:
    import urllib.request

    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with op.open(本地端口 + "/models", timeout=30) as resp:
            payload = cast(dict[str, Any], json.loads(resp.read().decode("utf-8")))
        rows = cast(list[Any], payload.get("data") or payload.get("models") or [])
        if rows and isinstance(rows[0], dict):
            row = cast(dict[str, Any], rows[0])
            return str(row.get("id") or row.get("name") or "qwen3-vl-8b")
    except Exception:  # noqa: BLE001
        pass
    return "qwen3-vl-8b"


def main() -> int:
    解析 = argparse.ArgumentParser()
    解析.add_argument("--模型", default="本地8B", choices=["本地8B", "mimo"])
    解析.add_argument("--只", type=int, default=0, help="每个版本只跑前 N 条(冒烟)")
    参数 = 解析.parse_args()

    日期 = dt.date.today().strftime("%Y%m%d")
    产物 = PROJECT / "logs" / f"对照-读回件-{参数.模型}-{日期}.txt"
    产物.write_text("", encoding="utf-8")
    行: list[str] = []

    def 记(文: str = "") -> None:
        print(文, flush=True)
        行.append(文)
        with 产物.open("a", encoding="utf-8") as fh:
            fh.write(文 + "\n")

    读回件 = (材料目录 / "readback.md").read_text(encoding="utf-8")
    if 参数.模型 == "mimo":
        客户端, 模型名 = sub_agent.build_client()
    else:
        客户端, 模型名 = 本地客户端(), 本地模型名()

    记("=" * 100)
    记(f"专用读回件探针（全部不用 JSON 契约）    {dt.datetime.now():%Y-%m-%d %H:%M:%S}")
    记("=" * 100)
    记(f"读回件 {len(读回件.splitlines())} 行 / {len(读回件)} 字符（指令 + 7 个手写 few-shot）· 读回模型 = {模型名}")
    记("数据：三份已有 jsonl 的**原始输出**离线复评（不重跑上游）")
    记(f"{'上游写法':<14}{'条数':<6}{'判对':<8}{'读不出JSON':<10}{'犹豫(含糊判要)':<14}均耗时")
    记("-" * 100)

    for 名, rel in 数据源:
        p = PROJECT / rel
        rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
        if 参数.只:
            rows = rows[: 参数.只]
        对 = 0
        读不出 = 0
        秒合计 = 0.0
        for r in rows:
            原文 = str(r.get("原文") or "")
            起 = time.perf_counter()
            try:
                out = sub_agent.short_call(客户端, 模型名, 读回件, 原文, 120) if 原文.strip() else ""
            except Exception as 异:  # noqa: BLE001
                out = ""
                print("  打失败", 异, flush=True)
            秒合计 += time.perf_counter() - 起
            载荷 = sub_agent.parse_json_object(out)
            if "need" not in 载荷:
                读不出 += 1
                得 = None
            else:
                得 = bool(载荷["need"])
                对 += 1 if 得 == r["期望"] else 0
            记(f"  [{r['模型']}] {r['题']!r:<30} 期望={r['期望']!s:<5} 读回={得!s:<5} "
                f"{'✅' if 得 == r['期望'] else '❌'}")
        记(f"[{名}] 判对 {对}/{len(rows)} = {对*100//max(1,len(rows))}% · 读不出 JSON {读不出} 条 · "
            f"均 {round(秒合计/max(1,len(rows)),1)}s")
        记("")

    记("=" * 100)
    记("与其它读回方式的对比（同一批 28 题 × 2 模型 = 56 发/版）")
    记("=" * 100)
    记("  上游写法        三级规则链（抠JSON+关键词+模型）   专用读回件（本探针）   有 JSON 契约时原样")
    记("  现行-说话       49/56 = 87%                       见上                   56/56 = 100%")
    记("  钢印-说话       41/56 = 73%                       见上                   52/56 = 92.9%")
    记("  叙事（老周）     32/56 = 57%                       见上                   28/56 = 50%")
    print(f"\n产物: {产物}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
