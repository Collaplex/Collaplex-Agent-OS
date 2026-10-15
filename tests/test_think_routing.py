#!/usr/bin/env python3
"""思考路由回归 —— 判定"主 agent 这轮要不要开长链路思考"的三层规则。

背景(2026-10-06 基准实测): 开思考**不是普遍更准** —— deepseek-flash 同题对比
GSM8K 90.0→85.0、HumanEval 91.7→83.3, 输出 token 涨 5.2 倍; 而 Qwen3-VL-8B-Instruct
根本没有思考模式(template 里 think 出现 0 次)。所以思考要按任务路由, 不能恒定开/关。

规矩:
- 关键词硬规则先判(命中即定, 不花模型调用) -> 子 agent 分析步给的 think -> 默认档(保守=关)
- 模型那步坏掉(被截/没给字段)**不许静默当结论**, 走默认档并把来源标成"默认"
- 不发无效参数: 认不出的 provider、没有思考模式的模型, 都要在日志里说清, 不要把"发了无效"记成"已开"

跑法: .venv/bin/python tests/test_think_routing.py
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import sub_agent  # noqa: E402

passed = 0
failed = 0


def check(name: str, got: object, want: object) -> None:
    global passed, failed
    if got == want:
        passed += 1
        print(f"  ok   {name}")
    else:
        failed += 1
        print(f"  FAIL {name}\n       要 {want!r}\n       得 {got!r}")


def main() -> int:
    routing = sub_agent.load_routing()

    print("[配置] think_routing.json 能读、默认档是保守关")
    check("配置非空", bool(routing), True)
    check("默认开关 = false(保守)", bool(routing.get("默认开关")), False)
    check("有方言表", isinstance(routing.get("方言"), list), True)
    check("有关键词规则", isinstance(routing.get("关键词规则"), list), True)

    print("[硬规则] 命中即定, 不花模型调用")
    hit, why = sub_agent.decide_by_keywords("帮我算一下这个月的账", routing)
    check("算账 -> 开", hit, True)
    check("理由里带命中词", "算一下" in why or "账" in why, True)
    hit, _ = sub_agent.decide_by_keywords("把这段翻译成英文", routing)
    check("翻译 -> 关", hit, False)
    hit, _ = sub_agent.decide_by_keywords("数一下 vllm 目录下有多少 .py 文件", routing)
    check("数文件(机器操作) -> 关", hit, False)
    hit, why = sub_agent.decide_by_keywords(
        "统计一下 /home/lou/桌面/collaplex_agent 下面有多少个 .py 文件", routing
    )
    check("统计文件(实测误判过) -> 关", hit, False)
    hit, _ = sub_agent.decide_by_keywords("讲个笑话", routing)
    check("讲笑话(没命中任何规则) -> None", hit, None)
    hit, _ = sub_agent.decide_by_keywords("看下日志里的报错", routing)
    check("看日志(机器操作, 曾被'报错'误伤) -> 关", hit, False)
    hit, _ = sub_agent.decide_by_keywords("这个函数为什么会报错", routing)
    check("改代码报错(真调试) -> 开", hit, True)
    hit, _ = sub_agent.decide_by_keywords("至少保留 3 份备份", routing)
    check("'至少'(曾被当多约束) -> None", hit, None)
    hit, _ = sub_agent.decide_by_keywords("记账: 收入 8000 支出 4800", routing)
    check("记账 -> 开", hit, True)
    hit, _ = sub_agent.decide_by_keywords("三个人三天喝三桶水, 九个人九天喝几桶", routing)
    check("要推理但没关键词 -> None(交给模型)", hit, None)
    hit, _ = sub_agent.decide_by_keywords("你好", routing)
    check("闲聊 -> 关", hit, False)
    hit, _ = sub_agent.decide_by_keywords("讲个笑话", routing)
    check("没命中任何规则 -> None", hit, None)

    print("[三层判定] 规则 > 模型 > 默认")
    got = sub_agent.decide_think("帮我算一下 1.5 倍是多少", False, "模型说不用", routing)
    check("规则说要开, 模型说不开 -> 听规则的", got["开关"], True)
    check("来源标规则", got["来源"], "规则")
    check("分歧要留痕(规则误判才看得出来)", "相反意见" in str(got["理由"]), True)

    got = sub_agent.decide_think("讲个笑话", True, "需要构思笑点", routing)
    check("规则没命中, 模型说要开 -> 听模型的", got["开关"], True)
    check("来源标模型", got["来源"], "模型")

    got = sub_agent.decide_think("讲个笑话", None, "", routing)
    check("规则没命中 + 模型没给结论 -> 默认档关", got["开关"], False)
    check("来源标默认(不许静默当结论)", got["来源"], "默认")
    check("理由写清是模型没给结论", "模型这步没给结论" in str(got["理由"]), True)

    print("[方言] 按 provider 拼参数, 不支持的要显式说")
    body, note = sub_agent.thinking_params(
        "https://api.deepseek.com/v1", "deepseek-flash", True, routing
    )
    check("deepseek 开 -> thinking.type=enabled", body, {"thinking": {"type": "enabled"}})
    body, _ = sub_agent.thinking_params(
        "https://api.deepseek.com/v1", "deepseek-flash", False, routing
    )
    check("deepseek 关 -> thinking.type=disabled", body, {"thinking": {"type": "disabled"}})

    body, _ = sub_agent.thinking_params(
        "http://127.0.0.1:8790/v1", "glm-4.6v-flash", True, routing
    )
    check(
        "本机 GLM 开 -> chat_template_kwargs",
        body,
        {"chat_template_kwargs": {"enable_thinking": True}},
    )

    body, note = sub_agent.thinking_params(
        "http://127.0.0.1:8791/v1", "Qwen3-VL-8B-Instruct", True, routing
    )
    check("Qwen3-VL-Instruct 没有思考模式 -> 不发参数", body, {})
    check("说明里写清是没有思考模式", "没有思考模式" in note, True)

    body, note = sub_agent.thinking_params(
        "https://api.anthropic.com/v1", "claude", True, routing
    )
    check("认不出的 provider -> 不发参数", body, {})
    check("说明里写清认不出", "认不出" in note, True)

    print("[提示词] plan.md(分析步) 必须要求模型给 think/reason")
    prompt = (ROOT / "config" / "skills" / "plan.md").read_text(encoding="utf-8")
    check("提示词里有 think 字段", '"think"' in prompt, True)
    check("提示词里有 reason 字段", '"reason"' in prompt, True)
    check("提示词里说明拿不准给 false", "拿不准就给 false" in prompt, True)

    print(f"\n{'-' * 50}\n通过 {passed} / 失败 {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
