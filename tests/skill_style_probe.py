#!/usr/bin/env python3
"""对照实验：skill 的写法 —— 现行「清单式」 vs 新「钢印＋潜暗示式」。

只换**写法**，不换内容：两版 skill 的产出契约（`{"need","wanted"}`）与判据点一一对应。
载体用 `judge.md`（判断步，84 行、五节追加式），因为它**有现成回归**（`left_chain_probe.py` 的 17 条）。

组的意义（老板口径：单组排除耦合与突发）= 同一组里的题同属一类, 组间不混；
同一题的**两版 × 两模型紧挨着跑**, 让当时的环境（模型负载/网络）对两版是一样的。

    .venv/bin/python tests/skill_style_probe.py            # 全部组 × 全部版本 × 两支模型
    .venv/bin/python tests/skill_style_probe.py --只 3      # 只跑第 3 题(单题重跑, 项目惯例)
    .venv/bin/python tests/skill_style_probe.py --版本 judge-钢印.md

产物（边跑边落盘）: logs/对照-skill写法-<日期>.jsonl（每发一行）＋ .txt（汇总 + 明细）
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, cast

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "skill" / "linux" / "tests"))

from openai import OpenAI  # noqa: E402

import left_chain_probe  # noqa: E402  (复用那 17 条判据用例, 单一真相)
import sub_agent  # noqa: E402

本地端口 = "http://127.0.0.1:8790/v1"


def 本地客户端() -> OpenAI:
    """本机模型必须**强制直连**: 本机 http_proxy 会把 127.0.0.1 也拦掉, 而 venv 里没有 httpx
    (别引新依赖) —— 所以建客户端那一瞬把代理环境变量摘掉, httpx 在 __init__ 时读它们."""
    摘 = {k: os.environ.pop(k) for k in list(os.environ)
          if k.lower() in ("http_proxy", "https_proxy", "all_proxy")}
    try:
        return OpenAI(api_key="local", base_url=本地端口)
    finally:
        os.environ.update(摘)
版本目录 = HERE / "skill_styles"

# 组 → [(问句, 期望 need)]。组 1~3 直接取现成回归用例（同源, 不另抄一份）；
# 组 4~5 取现行 skill 里「实测每次都漏」的那两张表。
CASES: list[tuple[str, bool, str]] = left_chain_probe.CASES
组表: list[tuple[str, list[tuple[str, bool]]]] = [
    ("1 本机实况", [(q, w) for q, w, _ in CASES[:7]]),
    ("2 本系统手册", [(q, w) for q, w, _ in CASES[7:10]]),
    ("3 常识概念", [(q, w) for q, w, _ in CASES[10:]]),
    (
        "4 短句(实测每次都漏)",
        [
            ("现在几点了", True),
            ("时间怎么换算、时区怎么算", False),
            ("两车相向而行", True),
            ("加盐提浓度", True),
            ("帮我看看还有多少空间", True),
            ("空间不足会怎样", False),
        ],
    ),
    (
        "5 算数(不许脑算)",
        [
            ("0.1+0.2 的精确值", True),
            ("123456789 乘 987654321 等于多少", True),
            ("15% 折扣后多少钱", True),
            ("求 2x+3=7 的解", True),
            ("解释一下什么是导数", False),
            ("帮我写个求两数之和的函数", False),
        ],
    ),
]


def 载入版本(只要: str = "") -> list[tuple[str, str]]:
    """载入 skill 版本 → [(版本名, 全文)]."""
    出: list[tuple[str, str]] = []
    for p in sorted(版本目录.glob("judge-*.md")):  # README 不是版本
        if "说话" in p.stem:  # ★ 说话版不吐 JSON, 拿它测"判得准不准"没意义(它归形态探针)
            continue
        if 只要 and p.name != 只要:
            continue
        出.append((p.stem, p.read_text(encoding="utf-8")))
    if not 出:
        raise SystemExit(f"没找到 skill 版本: {版本目录}/*.md")
    return 出


def 本地模型名() -> str:
    """llama.cpp 的 /v1/models 不是标准 OpenAI 形状(`{"models":[{"name":…}]}`) —— 直接解析, 别指望 SDK."""
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with op.open(本地端口 + "/models", timeout=30) as resp:
            payload = cast(dict[str, Any], json.loads(resp.read().decode("utf-8")))
        rows = cast(list[Any], payload.get("data") or payload.get("models") or [])
        if rows and isinstance(rows[0], dict):
            row = cast(dict[str, Any], rows[0])
            return str(row.get("id") or row.get("name") or row.get("model") or "qwen3-vl-8b")
    except Exception:  # noqa: BLE001
        pass
    return "qwen3-vl-8b"


def 判一发(raw: str, 期望: bool) -> tuple[bool, bool, str]:
    """回来 (解析出 need 没有, 判对没有, wanted)."""
    payload = sub_agent.parse_json_object(raw)
    if "need" not in payload:
        return False, False, ""
    need = bool(payload.get("need"))
    return True, need == 期望, str(payload.get("wanted") or "").strip()


def main() -> int:
    解析 = argparse.ArgumentParser()
    解析.add_argument("--只", type=int, default=0, help="只跑第 N 题(1 起), 单题重跑")
    解析.add_argument("--版本", default="", help="只跑某个版本的 md 文件名")
    参数 = 解析.parse_args()

    日期 = dt.date.today().strftime("%Y%m%d")
    明细 = PROJECT / "logs" / f"对照-skill写法-{日期}.txt"
    jsonl = PROJECT / "logs" / f"对照-skill写法-{日期}.jsonl"
    明细.write_text("", encoding="utf-8")
    jsonl.write_text("", encoding="utf-8")
    行: list[str] = []

    def 记(文: str = "") -> None:
        print(文, flush=True)
        行.append(文)
        with 明细.open("a", encoding="utf-8") as fh:
            fh.write(文 + "\n")

    resolved = sub_agent.load_config()
    limits = cast(dict[str, Any], resolved.get("limits") or {})
    max_tokens = int(limits.get("judge_max_tokens") or 200)
    mimo客户端, mimo模型 = sub_agent.build_client()
    本地名 = 本地模型名()
    版本 = 载入版本(参数.版本)

    记("=" * 104)
    记(f"对照实验 · skill 写法（现行清单式 vs 钢印+潜暗示式）    {dt.datetime.now():%Y-%m-%d %H:%M:%S}")
    记("=" * 104)
    记(f"载体: judge.md（判断步）· 只换写法不换内容 · 契约都是 {{\"need\",\"wanted\"}} · max_tokens={max_tokens}")
    for 名, 文 in 版本:
        记(f"  版本 {名:<16} {len(文.splitlines())} 行 / {len(文)} 字符")
    记(f"模型: mimo = {mimo模型} · 本地 = {本地名}")
    记(f"题量: {len(组表)} 组 / {sum(len(题) for _, 题 in 组表)} 题 × {len(版本)} 版 × 2 模型"
      f" = {sum(len(题) for _, 题 in 组表) * len(版本) * 2} 发")
    记("")

    表: list[dict[str, Any]] = []
    题序 = 0
    for 组名, 题表 in 组表:
        记("-" * 104)
        记(f"【组 {组名}】（{len(题表)} 题）")
        for 问, 期望 in 题表:
            题序 += 1
            if 参数.只 and 题序 != 参数.只:
                continue
            for 版名, 版文 in 版本:
                for 模型名, 客户端, 模型 in (
                    ("mimo", mimo客户端, mimo模型),
                    ("本地8B", 本地客户端(), 本地名),
                ):
                    起 = time.perf_counter()
                    try:
                        raw = sub_agent.short_call(客户端, 模型, 版文, 问, max_tokens)
                        错 = ""
                    except Exception as 异:  # noqa: BLE001
                        raw, 错 = "", f"{type(异).__name__}: {异}"
                    秒 = round(time.perf_counter() - 起, 1)
                    有结论, 判对, wanted = 判一发(raw, 期望) if raw else (False, False, "")
                    条 = {
                        "组": 组名, "题": 问, "期望": 期望, "版本": 版名, "模型": 模型名,
                        "need": 有结论 and bool(sub_agent.parse_json_object(raw).get("need")),
                        "对": 判对, "wanted": wanted, "字符": len(raw), "秒": 秒, "错": 错,
                        "原文": raw[:400],
                    }
                    表.append(条)
                    with jsonl.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps(条, ensure_ascii=False) + "\n")
                    print(f"  [{'对' if 判对 else '错'}] {版名:<16} {模型名:<7} {问!r:<28}"
                          f" need={条['need']!s:<5} 期望={期望!s:<5} {秒}s", flush=True)
        记("")

    记("=" * 104)
    记("汇总（一组一行为准；同一题的两版两模型是紧挨着跑的）")
    记("=" * 104)
    for 版名, _ in 版本:
        for 模型名 in ("mimo", "本地8B"):
            切 = [t for t in 表 if t["版本"] == 版名 and t["模型"] == 模型名]
            if not 切:
                continue
            总对 = sum(1 for t in 切 if t["对"])
            均字 = round(sum(int(t["字符"]) for t in 切) / len(切))
            均秒 = round(sum(float(t["秒"]) for t in 切) / len(切), 1)
            记(f"[{版名} × {模型名}] 总 {总对}/{len(切)} · 平均 {均字} 字符 · 平均 {均秒}s")
            for 组名, 题表 in 组表:
                子 = [t for t in 切 if t["组"] == 组名]
                if 子:
                    记(f"    {组名:<22} {sum(1 for t in 子 if t['对'])}/{len(子)}")
    记("")
    记("逐题明细（期望/两版两模型是否判对）")
    for 组名, 题表 in 组表:
        for 问, 期望 in 题表:
            单元: list[str] = []
            for 版名, _ in 版本:
                for 模型名 in ("mimo", "本地8B"):
                    找 = [t for t in 表 if t["题"] == 问 and t["版本"] == 版名 and t["模型"] == 模型名]
                    if 找:
                        单元.append(f"{版名[:6]}/{模型名}:{'✅' if 找[0]['对'] else '❌'}")
            记(f"{'✅' if 期望 else '⛔'} {问!r:<30} 期望={期望!s:<5} {'  '.join(单元)}")
    print(f"\n产物: {明细}\n      {jsonl}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
