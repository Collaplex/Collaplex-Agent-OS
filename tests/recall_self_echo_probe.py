#!/usr/bin/env python3
"""对照实验：同一份检索材料，mimo（云）与本地 8B 各答一遍 —— 病在供给，还是病在模型。

四臂 = 材料(现状 / 只留真资料) × 模型(mimo / 本地 qwen3-vl-8b)，同一批题各答一遍：

    材料·现状      = `prepare_skill` 真跑出来的 skill 文本（含 `# 任务` 自回声块，与线上一致）
    材料·只留真资料 = 同一批命中里剔掉 `# 任务` 开头的块，再按**同一个**拼接标准重拼

输出: logs/对照-自回声-<日期>.txt —— 逐臂原文 + 一张机器判据表（关键事实 / 打太极）。
判据是关键词命中，只当辅助；结论以原文为准（老板看原文）。

跑法: .venv/bin/python tests/recall_self_echo_probe.py
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import urllib.request
import time
from pathlib import Path
from typing import Any, cast

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path.insert(0, str(PROJECT))

from openai import OpenAI  # noqa: E402

import sub_agent  # noqa: E402

本地端口 = "http://127.0.0.1:8790/v1"
题表: list[dict[str, Any]] = [
    {
        "问": "今天让你做的ppt应该还记得吧",
        "关键事实": ["44", "pandoc", "pptx", "MI", "VI", "BI", "太阳神", "中银", "中国银行"],
    },
    {
        "问": "品牌识别系统鉴赏分析.pptx这个你不记得了吗？",
        "关键事实": ["44", "pandoc", "pptx", "MI", "VI", "BI", "太阳神", "中国银行", "焕一"],
    },
    {
        "问": "你还记得之前那个做盒子的那个作业吗？",
        "关键事实": ["7cm", "7×5×8", "8cm", "展开图", "照片", "卡扣", "刀版", "粘口"],
    },
]
太极词 = [
    "查不到", "没查到", "没有查", "没有记录", "没有找到", "没找到", "不记得", "记不得",
    "没有保留", "不掌握", "无法确认", "没有相关", "没出现", "没有出现", "不清楚",
]


def 本地客户端() -> OpenAI:
    """本机模型必须**强制直连**: 本机 http_proxy 会把 127.0.0.1 也拦掉, 而 venv 里没有 httpx
    (别引新依赖) —— 所以建客户端那一瞬把代理环境变量摘掉, httpx 在 __init__ 时读它们."""
    摘 = {k: os.environ.pop(k) for k in list(os.environ)
          if k.lower() in ("http_proxy", "https_proxy", "all_proxy")}
    try:
        return OpenAI(api_key="local", base_url=本地端口)
    finally:
        os.environ.update(摘)


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


def 问一发(
    客户端: OpenAI,
    模型: str,
    系统提示: str,
    问题: str,
    extra_body: dict[str, Any] | None = None,
    上限秒: float = 300.0,
) -> tuple[str, float]:
    """打一发，回来 (答案原文, 秒). 不开思考(两支都不开, 免得变量多一个)。"""
    起 = time.perf_counter()
    流 = 客户端.chat.completions.create(
        model=模型,
        messages=[
            {"role": "system", "content": 系统提示},
            {"role": "user", "content": 问题},
        ],
        stream=True,
        timeout=上限秒,
        extra_body=extra_body or None,
    )
    块: list[str] = []
    for 片 in 流:
        if not 片.choices:
            continue
        增量 = 片.choices[0].delta
        if 增量.content:
            块.append(str(增量.content))
    return "".join(块), round(time.perf_counter() - 起, 1)


def 是自回声(命中: dict[str, Any]) -> bool:
    return str(命中.get("text") or "").lstrip().startswith("# 任务")


def 判(答案: str, 关键事实: list[str]) -> tuple[str, str]:
    事实 = "、".join([k for k in 关键事实 if k in 答案][:4]) or "—"
    太极 = "、".join([k for k in 太极词 if k in 答案][:3]) or "—"
    return 事实, 太极


def 主() -> int:
    日期 = dt.date.today().strftime("%Y%m%d")
    产物 = PROJECT / "logs" / f"对照-自回声-{日期}.txt"
    行: list[str] = []
    产物.write_text("", encoding="utf-8")  # 开机清一次, 免得跟上一次的产物串起来

    def 记(文: str = "") -> None:
        # 边跑边落盘: 中途被掐也留得住已有几臂（本地臂慢, 长跑别等收尾才写）
        print(文, flush=True)
        行.append(文)
        with 产物.open("a", encoding="utf-8") as fh:
            fh.write(文 + "\n")

    resolved = sub_agent.load_config()
    主skill = sub_agent.load_main_skill(resolved)
    预算 = dict(cast(dict[str, Any], resolved["budget"]))
    mimo客户端, mimo模型 = sub_agent.build_client()
    mimo方言 = str(getattr(mimo客户端, "base_url", ""))
    routing = sub_agent.load_routing()
    mimo思考, mimo思考说明 = sub_agent.thinking_params(mimo方言, mimo模型, False, routing)
    本地名 = 本地模型名()
    本地模型客户端 = 本地客户端()

    记("=" * 100)
    记(f"对照实验 · 同一份检索材料, 两支模型各答一遍    {dt.datetime.now():%Y-%m-%d %H:%M:%S}")
    记("=" * 100)
    记(f"mimo 臂  : {mimo模型}  @ {mimo方言}   （{mimo思考说明}）")
    记(f"本地臂   : {本地名}  @ {本地端口}")
    记("材料两版: 现状 = prepare_skill 原样（含 # 任务 自回声块） / 只留真资料 = 剔掉 # 任务 后按同一标准重拼")
    记("")

    表: list[tuple[str, str, str, str, str]] = []
    for 序, 题 in enumerate(题表, 1):
        问题 = str(题["问"])
        关键 = cast(list[str], 题["关键事实"])
        记("=" * 100)
        记(f"【题 {序}】{问题}")
        记("=" * 100)
        prepared = sub_agent.prepare_skill(问题)
        命中 = cast(list[dict[str, Any]], prepared.get("记忆") or [])
        真料 = [h for h in 命中 if not 是自回声(h)]
        回声数 = len(命中) - len(真料)
        现状材料, _, 预算A = sub_agent.build_skill_text(问题, 命中, 主skill, dict(预算))
        真料材料, _, 预算B = sub_agent.build_skill_text(问题, 真料, 主skill, dict(预算))
        记(f"[供给] 检索词 {len(cast(list[object], prepared.get('queries') or []))} 条 · 命中 {len(命中)} 条 "
            f"（其中 # 任务 自回声 {回声数} 条）")
        for i, h in enumerate(命中, 1):
            标 = "自回声" if 是自回声(h) else "  资料"
            首行 = " ".join(str(h.get("text") or "").split())[:60]
            记(f"      [{i}][{标}] {h.get('score')} {Path(str(h.get('source'))).name} | {首行}")
        记(f"[材料] 现状 {len(现状材料)} 字符（记忆上限 {预算A.available}）· "
            f"只留真资料 {len(真料材料)} 字符（记忆上限 {预算B.available}，剔掉 {回声数} 块）")
        记("")

        for 材料名, 材料 in (("现状", 现状材料), ("只留真资料", 真料材料)):
            for 模型名, 客户端, 模型, 方言 in (
                ("mimo", mimo客户端, mimo模型, mimo思考),
                ("本地8B", 本地模型客户端, 本地名, None),
            ):
                标 = f"{材料名} × {模型名}"
                记(f"----- {标} -----")
                try:
                    答案, 秒 = 问一发(客户端, 模型, 材料, 问题, extra_body=方言)
                except Exception as 错:  # noqa: BLE001
                    记(f"[打失败] {type(错).__name__}: {错}")
                    表.append((标, "打失败", "—", "—", "—"))
                    记("")
                    continue
                事实, 太极 = 判(答案, 关键)
                表.append((标, 事实, 太极, f"{秒}s", f"{len(答案)} 字"))
                记(答案.strip())
                记(f"[判] 关键事实: {事实} · 打太极词: {太极} · {秒}s · {len(答案)} 字")
                记("")

    记("=" * 100)
    记("机器判据表（只当辅助；结论以原文为准）")
    记("=" * 100)
    记(f"{'臂':<18}{'关键事实':<26}{'太极词':<14}{'耗时':<10}{'答案'}")
    for r in 表:
        记(f"{r[0]:<18}{r[1]:<26}{r[2]:<14}{r[3]:<10}{r[4]}")
    记("")
    产物.write_text("\n".join(行), encoding="utf-8")
    print(f"\n产物: {产物}")
    return 0


if __name__ == "__main__":
    raise SystemExit(主())
