#!/usr/bin/env python3
"""对照实验 · 加了「思想钢印」之后**输出会变成什么样**（不是让它答题，是让它说话）。

老板口径：*"不是让 ai 去答题而是去说……在思想钢印类的可能会出现自言自语，你去观察一下"*。
所以这个探针**不判对错**，只收形态：
  - 自言自语：第一人称独白 / 自问自答（"嗯…这算落在机器上吗？算。"）
  - 表演：自我介绍开场、括号写动作、emoji、"作为一个 AI"
  - 守不守契约：吐 JSON / 散文 / 两个都吐
  - 把判据念出来没有（"结果落在哪里""常识""手头"）—— 钢印生效的一种可见痕迹

做法：同一份内容两版写法（`tests/skill_styles/` 下那两版）当 system prompt，
喂**同一句**用户话（4 个"说"的场景），两支模型各跑一发，逐手原文全落盘。

跑法: .venv/bin/python tests/skill_voice_probe.py
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, cast

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path.insert(0, str(PROJECT))

from openai import OpenAI  # noqa: E402

import sub_agent  # noqa: E402

本地端口 = "http://127.0.0.1:8790/v1"
版本目录 = HERE / "skill_styles"

场景表: list[tuple[str, str]] = [
    ("S1 自述", "说说你是干什么的、平时怎么处理一件事。"),
    ("S2 边想边说", "磁盘还剩多少空间？别输出 JSON，把你判断的过程原原本本说给我听。"),
    ("S3 模糊输入", "帮我看看。"),
    ("S4 被问身份", "你好，介绍一下你自己。"),
]
独白词 = ["我在想", "让我想想", "让我想", "我打算", "我先", "我得", "我应该", "我判断", "我看看",
          "嗯，", "嗯．", "其实", "等等", "话说", "我想", "我需不需要", "要不要", "应该算", "算不算"]
自问自答 = re.compile(r"[？?][^？?\n]{0,24}(是的|对|不用|需要|可以|不行|应该|算)")
表演词 = ["你好", "我是", "我是一名", "作为一个", "作为 AI", "AI 助手", "AI助手", "😊", "🙂",
          "*（", "（思考）", "（内心", "【内心"]
判据词 = ["落在", "机器上", "常识", "缺能力", "手头", "结果落在", "门房"]
# ★ 元话 = 把"这是一套提示词/规则装置"暴露出来的词。老板口径：模型嘴里冒出"思想钢印"这种词
#   = 它认出来了 = 潜暗示失效。契约字段(need/wanted)不算元话 —— 那是程序要读的。
元词 = ["钢印", "判据", "规则", "指令", "提示词", "系统提示", "skill", "SKILL", "字段",
        "JSON", "json", "输出格式", "自我", "人设", "角色扮演"]


def 本地客户端() -> OpenAI:
    """本机模型必须**强制直连**: 本机 http_proxy 会把 127.0.0.1 也拦掉, venv 里又没有 httpx。"""
    摘 = {k: os.environ.pop(k) for k in list(os.environ)
          if k.lower() in ("http_proxy", "https_proxy", "all_proxy")}
    try:
        return OpenAI(api_key="local", base_url=本地端口)
    finally:
        os.environ.update(摘)


def 本地模型名() -> str:
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


def 空形态() -> dict[str, Any]:
    return {"字符": 0, "行数": 0, "契约": "打失败", "独白词": [], "独白数": 0,
            "自问自答": [], "表演词": [], "判据词": [], "元话": []}


def 形态(raw: str) -> dict[str, Any]:
    行 = [ln for ln in raw.splitlines() if ln.strip()]
    独 = [w for w in 独白词 if w in raw]
    表 = [w for w in 表演词 if w in raw]
    判 = [w for w in 判据词 if w in raw]
    元 = [w for w in 元词 if w in raw]
    有json = bool(sub_agent.parse_json_object(raw))
    有散文 = len(re.sub(r"\{[^}]*\}", "", raw).strip()) > 40
    契约 = "JSON" if 有json and not 有散文 else ("散文" if 有散文 and not 有json else ("两样都有" if 有json else "没契约"))
    return {
        "字符": len(raw), "行数": len(行), "契约": 契约,
        "独白词": 独, "独白数": len(独) + len(自问自答.findall(raw)), "自问自答": 自问自答.findall(raw)[:3],
        "表演词": 表, "判据词": 判, "元话": 元,
    }


def main() -> int:
    日期 = dt.date.today().strftime("%Y%m%d")
    产物 = PROJECT / "logs" / f"对照-skill输出形态-{日期}.txt"
    产物.write_text("", encoding="utf-8")
    行: list[str] = []

    def 记(文: str = "") -> None:
        print(文, flush=True)
        行.append(文)
        with 产物.open("a", encoding="utf-8") as fh:
            fh.write(文 + "\n")

    # 只认 judge-*.md（README 是说明，不是版本）
    版本 = [(p.stem, p.read_text(encoding="utf-8"))
            for p in sorted(版本目录.glob("judge-*.md"))]
    mimo客户端, mimo模型 = sub_agent.build_client()
    本地名 = 本地模型名()
    本地 = 本地客户端()

    记("=" * 100)
    记(f"对照实验 · 加了钢印之后「输出会变成什么样」（让它说，不让它答题）    {dt.datetime.now():%Y-%m-%d %H:%M:%S}")
    记("=" * 100)
    for 名, 文 in 版本:
        记(f"  版本 {名:<14} {len(文.splitlines())} 行 / {len(文)} 字符")
    记(f"  模型 mimo={mimo模型} · 本地={本地名}")
    记("")

    统计: list[tuple[str, str, str, dict[str, Any]]] = []
    for 场景, 用户话 in 场景表:
        记("#" * 100)
        记(f"【{场景}】用户话: {用户话!r}")
        记("#" * 100)
        for 版名, 版文 in 版本:
            for 模型名, 客户端, 模型 in (("mimo", mimo客户端, mimo模型), ("本地8B", 本地, 本地名)):
                起 = time.perf_counter()
                try:
                    raw = sub_agent.short_call(客户端, 模型, 版文, 用户话, 400)
                    错 = ""
                except Exception as 异:  # noqa: BLE001
                    raw, 错 = "", f"{type(异).__name__}: {异}"
                秒 = round(time.perf_counter() - 起, 1)
                m: dict[str, Any] = 形态(raw) if raw else 空形态()
                统计.append((场景, 版名, 模型名, m))
                记(f"----- {版名} × {模型名} -----  {秒}s · {m['字符']} 字符 · {m['行数']} 行 · "
                    f"契约={m['契约']} · 自言自语标记 {m['独白数']} · 表演标记 {len(m['表演词'])} ----")
                if 错:
                    记(f"[打失败] {错}")
                else:
                    记(raw.strip())
                    记(f"[形态] 独白词={m['独白词']} 自问自答={m['自问自答']} 表演词={m['表演词']} "
                        f"判据词={m['判据词']} ★元话={m['元话']}")
                记("")

    记("=" * 100)
    记("形态汇总（不判对错，只看输出长成什么样）")
    记("=" * 100)
    记(f"{'版本':<18}{'模型':<8}{'场景':<12}{'契约':<9}{'字符':<7}{'行数':<6}{'自言自语':<8}{'表演':<6}{'念判据':<6}元话")
    for 场景, _ in 场景表:
        记(f"— {场景} —")
        for 版名, _ in 版本:
            for 模型名 in ("mimo", "本地8B"):
                找 = [x for x in 统计 if x[0] == 场景 and x[1] == 版名 and x[2] == 模型名]
                if not 找:
                    continue
                mm = 找[0][3]
                记(f"{版名:<18}{模型名:<8}{场景:<12}{mm['契约']:<9}{mm['字符']:<7}{mm['行数']:<6}"
                  f"{mm['独白数']:<8}{len(mm['表演词']):<6}{len(mm['判据词']):<6}"
                  f"{mm['元话'] if mm['元话'] else '—'}")
    print(f"\n产物: {产物}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
