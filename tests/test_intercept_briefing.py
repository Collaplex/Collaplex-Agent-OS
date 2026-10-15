#!/usr/bin/env python3
"""拦截简报回归 —— 界面上那行"查询 N 条 · 记忆 M 条"必须说真话。

背景(2026-10-13 老板报"又是老问题: 它不记得"):
    自答轮(判定说不需要派活那条路)界面上**天天报"记忆 0 条"**, 而同一轮的 skill 文本里明明
    塞着 `[记忆 1]…[记忆 N]` 块(实测: 报 0 条那轮, skill 文本 13662 字符、里面有 5 块记忆)。
    真因: `prepare_skill` 有两条出口 —— 走左链那条带 `"记忆"` 列表, 自答那条只带 `hits` 计数;
    而简报 `describe_intercept` 只读 `prepared["记忆"]`, 读不到就 `or []` → 恒 0。
    顺带还有第二处后果: 判定那步坏掉、回落走左链时, main/bridge 也从这儿取记忆贴给 exec。

规矩(两条, 缺一不可):
    ① `prepare_skill` **两条出口都要带 "记忆" 原文**(与 hits 同源、条数必须一致);
    ② 简报读不到列表时**退回 hits 计数** —— 显示层不许因为少一个键就把"有"说成"没有"。

跑法: .venv/bin/python tests/test_intercept_briefing.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path.insert(0, str(PROJECT))

import main as main_mod  # noqa: E402
import sub_agent  # noqa: E402

通过 = 0
失败 = 0


def 判据(名: str, ok: bool, 说明: str = "") -> None:
    global 通过, 失败
    if ok:
        通过 += 1
        print(f"  ok   {名}{('  ' + 说明) if 说明 else ''}")
    else:
        失败 += 1
        print(f"  FAIL {名}{('  ' + 说明) if 说明 else ''}")


class 假模型:
    """假模型: 按顺序把预设文本当模型输出发回来(不连网络、不花钱)."""

    def __init__(self, 输出表: list[str]) -> None:
        self.输出表: list[str] = list(输出表)
        # ★ 得有个 base_url: build_skill_text 会用它去问上下文窗口(问不到就用配置兜底)。
        #   指向一个没人听的本地端口 —— 立刻拒连, 以免测试真去打云端。
        self.base_url = "http://127.0.0.1:1/v1"
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> Any:
        文本 = self.输出表.pop(0) if self.输出表 else ""
        if kwargs.get("stream"):
            块 = SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        delta=SimpleNamespace(content=文本, reasoning_content=None),
                    )
                ]
            )
            return [块]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=文本))]
        )


def 测_简报条数() -> None:
    print("\n一、简报条数(纯逻辑: 两条出口的两种形状都要报对数)")
    exec形: dict[str, Any] = {
        "queries": ["谁占着 8790"],
        "wanted": "查端口的进程",
        "hits": 3,
        "记忆": [{"text": "a"}, {"text": "b"}, {"text": "c"}],
        "skill": "x" * 100,
    }
    行 = main_mod.describe_intercept(exec形)
    判据("走左链那条(带 wanted + 记忆 列表) -> 3 条 且 缺 skill 也报记忆", "记忆 3 条" in 行 and "缺 skill" in 行, 行)

    自答形: dict[str, Any] = {
        "queries": ["今天让你做的 ppt 应该还记得吧"],
        "hits": 5,
        "skill": "y" * 200,
    }
    行 = main_mod.describe_intercept(自答形)
    判据("★ 自答那条(只有 hits 计数, 没有 记忆 列表) -> 报 5 条, 不许报 0", "记忆 5 条" in 行, 行)

    自答形2: dict[str, Any] = {"queries": ["q"], "hits": 4, "记忆": [{"text": "a"}] * 4}
    判据("自答那条带列表时 -> 以列表为准(4 条)", "记忆 4 条" in main_mod.describe_intercept(自答形2))

    真零: dict[str, Any] = {"queries": ["q"], "hits": 0, "记忆": []}
    判据("真的一条都没召回 -> 照实报 0 条", "记忆 0 条" in main_mod.describe_intercept(真零))

    无查询: dict[str, Any] = {"queries": [], "hits": 0}
    判据("这步没给查询也没兜底 -> 明说是这个原因", "这步没给查询" in main_mod.describe_intercept(无查询))

    兜底: dict[str, Any] = {"queries": ["原话"], "hits": 2, "记忆兜底": True}
    判据("程序拿原话兜底的那轮 -> 说清是兜底来的", "拿你的原话兜底 · 记忆 2 条" in main_mod.describe_intercept(兜底))

    坏了: dict[str, Any] = {"queries": ["q"], "hits": 1, "broken": True}
    判据("判定那步没结论 -> 明说(而不是假装不需要)", "没给出结论" in main_mod.describe_intercept(坏了))

    预算: dict[str, Any] = {"queries": ["q"], "hits": 1, "memory_budget": 26362}
    判据("尾缀带记忆上限", "记忆上限 26362" in main_mod.describe_intercept(预算))


def 测_两条出口都带记忆() -> None:
    print("\n二、prepare_skill 两条出口都带记忆(模型用假的, 检索用假的; 断言的是出口形状)")
    from typing import cast as _cast  # noqa: PLC0415

    原build = sub_agent.build_client
    原recall = sub_agent.recall_memory
    假命中: list[dict[str, Any]] = [
        {"query": "q1", "score": 0.81, "source": "skill/rag/corpus/x.md", "text": "甲"},
        {"query": "q1", "score": 0.72, "source": "skill/rag/corpus/y.md", "text": "乙"},
    ]
    try:
        def 假recall(queries: list[str], rag: dict[str, Any]) -> list[dict[str, Any]]:
            del queries, rag
            return list(假命中)

        sub_agent.recall_memory = _cast(Any, 假recall)

        分析 = json.dumps({"queries": ["品牌识别系统鉴赏分析.pptx 文件"], "think": False, "reason": "回忆类"}, ensure_ascii=False)
        for 名, 判定 in (("自答(need=false)", '{"need": false, "wanted": ""}'),
                        ("走左链(need=true)", '{"need": true, "wanted": "查手册"}')):
            sub_agent.build_client = _cast(Any, (lambda 表: (lambda: (假模型(表), "假模型")))([分析, 判定]))
            果 = sub_agent.prepare_skill("品牌识别系统鉴赏分析.pptx这个你不记得了吗？")
            有键 = "记忆" in 果
            条数对 = len(cast(list[object], 果.get("记忆") or [])) == int(果.get("hits") or 0)
            行 = main_mod.describe_intercept(果)
            真话 = f"记忆 {果.get('hits')} 条" in 行
            判据(f"{名}: 出口带 记忆 原文", 有键, f"键={sorted(果.keys())[:5]}…")
            判据(f"{名}: 记忆条数 == hits", 条数对 and int(果.get("hits") or 0) == len(假命中))
            判据(f"{名}: 简报按真实条数报", 真话, 行)
    finally:
        sub_agent.build_client = 原build
        sub_agent.recall_memory = 原recall


def 主() -> int:
    print("=" * 100)
    print("拦截简报回归 —— \"记忆 0 条\"不许再假报")
    print("=" * 100)
    测_简报条数()
    测_两条出口都带记忆()
    print("\n" + "=" * 100)
    print(f"结果: {通过} 通过 / {失败} 失败")
    print("=" * 100)
    return 0 if 失败 == 0 else 1


if __name__ == "__main__":
    raise SystemExit(主())
