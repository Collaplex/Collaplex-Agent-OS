#!/usr/bin/env python3
"""试点验收：judge 那一步的**出口形态**两种模式走真件比一比。

- `json` 模式（现状）：提示词直接要求 `{"need","wanted"}`，程序 parse。
- `读回` 模式（老板方案）：提示词换成 `judge_freeform`（**不要求 JSON**，让它把判断说出来），
  再由 `config/skills/readback.md` 把结论读回来。

走的都是**生产函数** `sub_agent.judge_skill()`（不是探针里另抄一套），
所以验的就是"真接上去会怎样"。

判据：need 是否与期望一致（28 题 × 2 组模型）+ broken 率 + 耗时 + 每题的模型调用次数。

跑法: .venv/bin/python tests/judge_readback_probe.py
"""

from __future__ import annotations

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
from skill_style_probe import 组表  # noqa: E402

本地端口 = "http://127.0.0.1:8790/v1"


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
    with op.open(本地端口 + "/models", timeout=30) as resp:
        载荷 = cast(dict[str, Any], json.loads(resp.read().decode("utf-8")))
    行 = cast(list[Any], 载荷.get("data") or 载荷.get("models") or [])
    if 行 and isinstance(行[0], dict):
        r = cast(dict[str, Any], 行[0])
        return str(r.get("id") or r.get("name") or "qwen3-vl-8b")
    return "qwen3-vl-8b"


def main() -> int:
    日期 = dt.date.today().strftime("%Y%m%d")
    产物 = PROJECT / "logs" / f"试点-judge出口形态-{日期}.txt"
    产物.write_text("", encoding="utf-8")
    行: list[str] = []

    def 记(文: str = "") -> None:
        print(文, flush=True)
        行.append(文)
        with 产物.open("a", encoding="utf-8") as fh:
            fh.write(文 + "\n")

    resolved = sub_agent.load_config()
    基础配置 = dict(cast(dict[str, Any], resolved["skill_retrieval"]))
    上限 = int(cast(dict[str, Any], resolved.get("limits") or {}).get("judge_max_tokens") or 1200)
    mimo客户端, mimo模型 = sub_agent.build_client()
    本地名 = 本地模型名()
    本地 = 本地客户端()
    题表 = [(问, 期望, 组) for 组, 题 in 组表 for 问, 期望 in 题]

    记("=" * 100)
    记(f"试点验收 · judge 出口形态（json vs 读回）    {dt.datetime.now():%Y-%m-%d %H:%M:%S}")
    记("=" * 100)
    记(f"走真件 sub_agent.judge_skill · max_tokens={上限} · {len(题表)} 题 × 2 组模型 × 2 模式")
    记("")

    # ★ 可选过滤(不改默认行为): PROBE_MODES=读回 / PROBE_MODELS=mimo 只跑指定的臂。
    #   云端只跑一遍时用它把本地 8B 那两臂(80~214 秒/发)跳过, 免得为已知结论等几小时。
    想跑的模式 = [x.strip() for x in os.environ.get("PROBE_MODES", "").split(",") if x.strip()]
    想跑的模型 = [x.strip() for x in os.environ.get("PROBE_MODELS", "").split(",") if x.strip()]

    汇总: dict[tuple[str, str], dict[str, float]] = {}
    for 模式 in ("json", "读回"):
        if 想跑的模式 and 模式 not in 想跑的模式:
            continue
        配置 = dict(基础配置)
        配置["judge_输出"] = 模式
        记("-" * 100)
        记(f"【{模式} 模式】判据提示词 = "
           f"{'judge_freeform（不要求 JSON）' if 模式 == '读回' else 'judge（要求 JSON）'}")
        for 模型名, 客户端, 模型 in (("mimo", mimo客户端, mimo模型), ("本地8B", 本地, 本地名)):
            if 想跑的模型 and 模型名 not in 想跑的模型:
                continue
            对 = 0
            坏 = 0
            秒合计 = 0.0
            for 问, 期望, _组 in 题表:
                起 = time.perf_counter()
                果 = sub_agent.judge_skill(客户端, 模型, 问, 配置, max_tokens=上限)
                秒合计 += time.perf_counter() - 起
                need = bool(果["need"]) and not bool(果["broken"])
                坏 += 1 if 果["broken"] else 0
                对 += 1 if need == 期望 and not 果["broken"] else 0
                if os.environ.get("PROBE_VERBOSE"):
                    print(f"     · {问[:22]:<24} need={need} 期望={期望} broken={果['broken']}"
                          f" {round(time.perf_counter() - 起, 1)}s", flush=True)
            n = len(题表)
            print(f"   {模型名:<7} {对}/{n} · broken {坏} · 均 {round(秒合计/n,1)}s", flush=True)
            汇总[(模式, 模型名)] = {"对": 对, "n": n, "broken": 坏, "秒": round(秒合计 / n, 1)}
        记("")

    记("=" * 100)
    记("汇总（判据 = need 与期望一致；broken = 那一步没给出结论）")
    记("=" * 100)
    记(f"{'模式':<8}{'模型':<9}{'判对':<10}{'broken':<9}均耗时")
    for (模式, 模型名), v in 汇总.items():
        记(f"{模式:<8}{模型名:<9}{int(v['对'])}/{int(v['n'])} = {int(v['对']) * 100 // int(v['n'])}%"
           f"{'':<4}{int(v['broken']):<9}{v['秒']}s")
    记("")
    记("调用次数：读回模式每题多花 1 次模型调用（上游说 + 读回件读）；实测读回件本地 0.5 秒/条。")
    print(f"\n产物: {产物}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
