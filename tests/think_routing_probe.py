#!/usr/bin/env python3
"""思考路由实测 —— 真跑模型, 不是 mock。

验两件事:
  1) 子 agent 的分析步真的会给 think/reason (走 prepare_skill 全链, 真模型 + 真检索)
  2) 主 agent 带上思考参数后**行为真的变了** —— 对比同题在 关/开 两种参数下的
     输出 token、耗时、有没有推理内容

跑法: .venv/bin/python tests/think_routing_probe.py     (本地 GLM 慢, 约 3~6 分钟)
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
from openai import OpenAI  # noqa: E402

import sub_agent  # noqa: E402
from main import StreamingChatAssistant  # noqa: E402

QUESTIONS = [
    "帮我算一下这个月的账：房租 2400，水电 320，吃饭 1850，交通 240，剩下的存起来。收入 8000，能存多少？",
    "把这句话翻译成英文：今天天气不错，我们出去走走吧。",
    "统计一下 /home/lou/桌面/collaplex_agent 下面有多少个 .py 文件，同时看看 8790 端口是哪个进程在跑。",
]


def main() -> int:
    load_dotenv(str(ROOT / ".env"))
    base_url = str(os.getenv("OPENAI_BASE_URL") or "")
    model = str(os.getenv("OPENAI_MODEL") or "")
    routing = sub_agent.load_routing()

    print("=" * 72)
    print(f"被测: {model} @ {base_url}")
    print("=" * 72)

    print("\n【1】子 agent 分析步真的会给 think/reason 吗（走真模型 + 真检索）")
    print("-" * 72)
    for question in QUESTIONS:
        started = time.perf_counter()
        prepared = sub_agent.prepare_skill(question)
        used = time.perf_counter() - started
        print(f"\n问: {question[:42]}...")
        print(
            f"  判定 {prepared.get('think')} | 来源 {prepared.get('think_source')}"
            f" | 理由 {prepared.get('think_reason')}"
        )
        print(
            f"  检索问句 {prepared.get('queries')} | 取回 {prepared.get('hits')} 条"
            f" | 缺能力 {prepared.get('wanted') or '无'} | {used:.1f}s"
        )

    print("\n\n【2】思考参数真的改变主 agent 的行为吗（同题, 关 vs 开）")
    print("-" * 72)
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), base_url=base_url)
    question = "一个水池有两个进水管：甲管 6 小时注满，乙管 4 小时注满，丙管 12 小时放空。三管齐开多久注满？要一步步算。"
    print(f"问: {question}\n")
    rows: list[tuple[str, int | float | None, float, int]] = []
    for label, enabled in (("关思考", False), ("开思考", True)):
        body, note = sub_agent.thinking_params(base_url, model, enabled, routing)
        print(f"  {label}: {note}   extra_body={body}")
        assistant = StreamingChatAssistant(client, model, "你是严谨的助手。", extra_body=body)
        started = time.perf_counter()
        reasoning, answer, stats = assistant.chat(question)
        used = time.perf_counter() - started
        tokens = stats["completion_tokens"]
        rows.append((label, tokens, used, len(reasoning or "")))
        shown = (answer or "").replace("\n", " ")[:60]
        print(f"    输出 {tokens} tok | {used:.1f}s | 推理字段 {len(reasoning or '')} 字")
        print(f"    答: {shown}...\n")

    print("-" * 72)
    print(f"{'':8}{'输出tok':>10}{'耗时s':>10}{'推理字段':>12}")
    for label, tokens, used, reasoning_len in rows:
        print(f"{label:8}{str(tokens):>10}{used:>10.1f}{reasoning_len:>12}")
    off, on = rows[0], rows[1]
    if off[1] and on[1]:
        print(f"\n开/关 输出 token 比 = {on[1] / off[1]:.2f}×")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
