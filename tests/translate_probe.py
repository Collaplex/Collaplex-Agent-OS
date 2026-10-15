#!/usr/bin/env python3
"""翻译件探针：叙事版输出 → 结构化结论，三级还原（老板 2026-10-13 提的方案）。

背景：叙事版 skill（"老周的值班室"）能把模型带进戏里（零元话、行为模式被偏移），
但它的产出是散文 —— 判别件要的可解析结论被吃了。老板的方案：**训练一个翻译件**，
专门挑出这段话的主语意思，直接翻过来。本探针先验"不训练能不能干"的三级：

    ① 规则层：在散文里抠 JSON（`子agent.parse_json_object`）
    ② 关键词层：戏内说法 → 结论（"转到院里/得有人去/派人" ⇒ 需要；"窗口就能办/我来说清" ⇒ 不需要）
    ③ 模型层：仍翻不出，就把这段散文交给翻译件（`tests/skill_styles/翻译件.md`）翻成一行 JSON

产物同时是**训练数据的原料**（每题 × 每模型 × 原文 × 期望 × 三级结果）。

跑法: .venv/bin/python tests/translate_probe.py
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
from skill_style_probe import 组表  # noqa: E402  (题组同源, 不另抄一份)

本地端口 = "http://127.0.0.1:8790/v1"
材料目录 = HERE / "skill_styles"

# 戏内说法 → 结论。只做"明显在演戏"的那种，含糊的一律留给模型层。
要派的话 = ["转到院", "得转到", "让人去", "派人", "得有人去", "得去院里", "要动机器", "缺的能力",
           "让搜索的人", "得去翻", "得去问", "上外头", "交账房", "一律交账房", "得有人看表"]
不用派的话 = ["窗口就能办", "我来说清", "我就能说清", "窗口说清就行", "不用转", "窗口就能",
             "在窗口说清楚就行", "窗口的事", "说话就到", "说清楚就行"]


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


def L1_抠json(原文: str) -> bool | None:
    载荷 = sub_agent.parse_json_object(原文)
    return bool(载荷["need"]) if "need" in 载荷 else None


def L2_关键词(原文: str) -> bool | None:
    派 = any(w in 原文 for w in 要派的话)
    不派 = any(w in 原文 for w in 不用派的话)
    if 派 and not 不派:
        return True
    if 不派 and not 派:
        return False
    return None


def main() -> int:
    解析 = argparse.ArgumentParser()
    解析.add_argument("--版本", default="judge-叙事.md", help="被翻译的那一版 skill 文件名")
    参数 = 解析.parse_args()

    日期 = dt.date.today().strftime("%Y%m%d")
    简称 = 参数.版本.replace("judge-", "").replace(".md", "")
    txt = PROJECT / "logs" / f"对照-翻译件-{简称}-{日期}.txt"
    jsonl = PROJECT / "logs" / f"对照-翻译件-{简称}-{日期}.jsonl"
    if not txt.exists():
        txt.write_text("", encoding="utf-8")
    if not jsonl.exists():
        jsonl.write_text("", encoding="utf-8")
    行: list[str] = []

    def 记(文: str = "") -> None:
        print(文, flush=True)
        行.append(文)
        with txt.open("a", encoding="utf-8") as fh:
            fh.write(文 + "\n")

    被翻 = (材料目录 / 参数.版本).read_text(encoding="utf-8")
    翻译件 = (材料目录 / "翻译件.md").read_text(encoding="utf-8")
    mimo客户端, mimo模型 = sub_agent.build_client()
    本地名 = 本地模型名()
    本地 = 本地客户端()
    题表 = [(问, 期望, 组) for 组, 题 in 组表 for 问, 期望 in 题]

    记("=" * 100)
    记(f"翻译件探针 · 叙事版输出 → 结构化结论（三级还原）    {dt.datetime.now():%Y-%m-%d %H:%M:%S}")
    记("=" * 100)
    记(f"原始臂: {参数.版本}（{len(被翻.splitlines())} 行）· 翻译件 {len(翻译件.splitlines())} 行")
    记(f"题量: {len(题表)} 题 × 2 模型 = {len(题表)*2} 发；每发走 ① 抠 JSON ② 关键词 ③ 模型翻译")
    记("")
    记(f"{'题':<26}{'期望':<6}{'模型':<8}{'① 抠JSON':<10}{'② 关键词':<10}{'③ 模型':<9}{'最终':<6}{'原文长度'}")
    记("-" * 100)

    条数 = {"A": 0, "AB": 0, "ABC": 0, "总": 0}
    记错: list[dict[str, Any]] = []

    for 问, 期望, 组 in 题表:
        for 模型名, 客户端, 模型 in (("mimo", mimo客户端, mimo模型), ("本地8B", 本地, 本地名)):
            起 = time.perf_counter()
            try:
                原文 = sub_agent.short_call(客户端, 模型, 被翻, 问, 400)
            except Exception as 异:  # noqa: BLE001
                原文 = ""
                记(f"[打失败] {模型名} {问!r}: {异}")
            秒 = round(time.perf_counter() - 起, 1)

            一 = L1_抠json(原文)
            二 = 一 if 一 is not None else L2_关键词(原文)
            三 = 二
            走了 = "—"
            if 三 is None and 原文.strip():
                走了 = "翻译件"
                try:
                    out = sub_agent.short_call(客户端, 模型, 翻译件, 原文, 120)
                    三 = L1_抠json(out)
                except Exception as 异:  # noqa: BLE001
                    走了 = f"失败 {type(异).__name__}"

            条 = {"版本": 简称, "组": 组, "题": 问, "期望": 期望, "模型": 模型名, "①": 一, "②": 二, "③": 三,
                  "走了": 走了, "对一二": 二 == 期望, "对全": 三 == 期望, "秒": 秒,
                  "原文": 原文, "原文长": len(原文)}
            with jsonl.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(条, ensure_ascii=False) + "\n")
            if 三 != 期望:
                记错.append(条)

            条数["总"] += 1
            条数["A"] += 1 if 一 == 期望 else 0
            条数["AB"] += 1 if 二 == 期望 else 0
            条数["ABC"] += 1 if 三 == 期望 else 0
            记(f"{问:<26}{str(期望):<6}{模型名:<8}{str(一):<10}{str(二):<10}{str(三):<9}"
              f"{'✅' if 三 == 期望 else '❌':<6}{len(原文)}")

    记("")
    记("=" * 100)
    记("还原率（分母 = 全部发数；① 是「先抠 JSON」能救回多少，②③ 是在它之后再加层的收益）")
    记("=" * 100)
    记(f"① 只抠 JSON        : {条数['A']}/{条数['总']}  = {条数['A']*100//条数['总']}%")
    记(f"①+② 再加关键词层   : {条数['AB']}/{条数['总']}  = {条数['AB']*100//条数['总']}%")
    记(f"①+②+③ 再加模型翻译 : {条数['ABC']}/{条数['总']}  = {条数['ABC']*100//条数['总']}%")
    记(f"（对照：同一批题上，清单式原样 = 56/56）")
    记("")
    记(f"仍翻错的 {len(记错)} 发：")
    for t in 记错:
        记(f"  [{t['模型']}] {t['题']!r} 期望={t['期望']} ①{t['①']} ②{t['②']} ③{t['③']} · {t['走了']}")
    记("")
    记("训练数据原料（每题原文都在 jsonl 里，含 期望/三级结果）: " + str(jsonl))
    print(f"\n产物: {txt}\n      {jsonl}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
