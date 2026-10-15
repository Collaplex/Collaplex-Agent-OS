"""催促兜底回归: 模型"只说不做"(吐预告语)时, 程序不能当结论收下。

实测 bug(2026-10-06): 问"看看这台机器是什么配置", exec agent 只回了一句
"我来查这台机器的 CPU、内存和磁盘分区情况。" —— 一个 <调用> 都没给,
主循环 `if not commands: break` 直接当它答完了, 结果一条命令没跑、结论是空话
(main.py 的守卫认出来了: "[入二层库] 它没真跑过命令, 产出不算话")。

这里不联网、不调模型: 用一个假 agent 按脚本吐回答, 验证程序会催它给命令。

跑法: .venv/bin/python tests/test_exec_nudge.py
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam

import exec_agent

DEAD_URL = "http://127.0.0.1:9/v1"  # 只为过一遍构造, 本测试从不真发请求


class FakeAgent(exec_agent.ChatAgent):
    """按脚本吐回答的 exec agent —— 第 N 轮吐 script[N], 用完就吐最后一条。"""

    script: list[str]
    rounds: int

    def __init__(self, script: list[str]) -> None:
        super().__init__(
            client=OpenAI(api_key="sk-test-not-used", base_url=DEAD_URL),
            model="fake-model",
            system_prompt="(测试用提示词)",
        )
        self.script = list(script)
        self.rounds = 0

    def ask(
        self,
        messages: list[ChatCompletionMessageParam],
        on_event: exec_agent.ProgressFn | None = None,
    ) -> tuple[str, str, dict[str, int | float | None]]:
        """不联网: 按脚本吐, 顺带把 usage 也给成 0。"""
        self.rounds += 1
        index = min(self.rounds - 1, len(self.script) - 1)
        return "", self.script[index], {"prompt_tokens": 0, "completion_tokens": 0}


def test_preamble_gets_nudged() -> bool:
    """先吐预告语 -> 程序催 -> 它才给命令 -> 真跑。"""
    agent = FakeAgent([
        "我来查这台机器的 CPU、内存和磁盘分区情况。",   # 第 1 轮: 预告语(原 bug 就死在这)
        "<调用>echo 催过了</调用>",                     # 第 2 轮: 被催之后给了命令
        "结论: 跑完了。",
    ])
    events: list[tuple[str, str]] = []
    _, answer, _, calls = agent.run("看看这台机器是什么配置", on_event=lambda k, t: events.append((k, t)))

    print("  轮数:", agent.rounds, "真跑命令:", [c["command"] for c in calls])
    print("  事件里的催:", [t for k, t in events if k == "note"])
    print("  回答:", answer.strip()[:40])

    ok = True
    if not calls:
        print("  ✗ 一条命令都没跑 —— 预告语又被当成结论了")
        ok = False
    if not any("催" in text for _, text in events):
        print("  ✗ 没有催的动作")
        ok = False
    if agent.rounds < 3:
        print(f"  ✗ 轮数不对({agent.rounds}), 说明没催就往下走了")
        ok = False
    return ok


def test_preamble_detector() -> bool:
    """预告语判据本身。"""
    markers = ["我来", "正在", "接下来", "这就"]
    cases: list[tuple[str, bool]] = [
        ("我来查这台机器的 CPU、内存和磁盘分区情况。", True),
        ("正在检索…", True),
        ("我来查一下", True),
        # 长文本 = 它已经给出结论了, 不算预告
        ("这台机器是 AMD Ryzen 9。\n" + "判据: lscpu 显示 Model name 为 AMD Ryzen 9 8940HX。" * 6, False),
        ("结论: 8899 端口没有服务在监听。", False),
    ]
    ok = True
    for text, expect in cases:
        got = exec_agent.looks_like_preamble(text, markers, 120)
        flag = "✓" if got == expect else "✗"
        if got != expect:
            ok = False
        print(f"  {flag} 期望{expect} 实得{got}: {text[:28]!r}")
    return ok


def test_conclusion_not_nudged_after_work() -> bool:
    """已经跑过命令、然后给出结论 —— 不该再催。"""
    agent = FakeAgent([
        "<调用>echo 先跑一条</调用>",
        "结论: 跑完了, 就这样。",   # 短, 但没有预告词 -> 是结论, 不该催
    ])
    events: list[tuple[str, str]] = []
    run_result = agent.run("随便看看", on_event=lambda k, t: events.append((k, t)))
    calls = run_result[3]
    print("  轮数:", agent.rounds, "命令数:", len(calls), "催的次数:", sum(1 for kind, _ in events if kind == "note"))
    if sum(1 for kind, _ in events if kind == "note") != 0:
        print("  ✗ 跑过命令之后给结论, 却被催了")
        return False
    if not calls:
        print("  ✗ 第一条命令没跑")
        return False
    return True


class WrapupAwareAgent(FakeAgent):
    """永远只给命令块的模型 —— 但收到"收尾"提示词时会给结论(模拟真实模型被点醒)。"""

    def ask(
        self,
        messages: list[ChatCompletionMessageParam],
        on_event: exec_agent.ProgressFn | None = None,
    ) -> tuple[str, str, dict[str, int | float | None]]:
        seen = " ".join(str(item.get("content", "")) for item in messages[1:])
        if "回合用尽" in seen:
            self.rounds += 1
            return "", "结论: 16G 单条、槽位 1/2; 型号要 root 查不到。", {
                "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15,
            }
        return super().ask(messages, on_event)


def test_wrapup_rescues_answer() -> bool:
    """回合用尽 -> 程序补一次收尾 -> 答案来自收尾(不是白卷, 不是那句占位符)。"""
    agent = WrapupAwareAgent([
        "<调用>echo 第一条</调用>",
        "<调用>echo 第二条</调用>",
    ])
    events: list[tuple[str, str]] = []
    _, answer, usage, calls = agent.run(
        "内存条什么型号", max_rounds=2, on_event=lambda k, t: events.append((k, t)),
    )
    print("  轮数:", agent.rounds, "命令数:", len(calls), "回答:", answer.strip()[:44])

    if not calls:
        print("  ✗ 命令没跑")
        return False
    if "来回次数用尽" in answer:
        print("  ✗ 还是交了白卷(占位符) —— 收尾没生效")
        return False
    if "16G" not in answer:
        print("  ✗ 答案不是收尾那趟给的")
        return False
    if not any("收尾" in text for _, text in events):
        print("  ✗ 没打收尾的提示")
        return False
    if usage["total_tokens"] != 15:
        print(f"  ✗ 收尾那趟的用量没算进去: {usage}")
        return False
    return True


def test_wrapup_no_fabrication() -> bool:
    """收尾那趟要是还不给结论(仍在要命令) -> 如实标"用尽", 不许编; ★ 但也不许交白卷。"""
    agent = FakeAgent(["<调用>echo 一直在跑</调用>"])
    _, answer, _, calls = agent.run("随便查个查不到的", max_rounds=2)
    print("  命令数:", len(calls), "回答:", answer.strip()[:60].replace("\n", " / "))
    ok = True
    if "来回次数用尽" not in answer:
        print("  ✗ 该标『用尽』的地方没标 —— 像在假装干完了")
        ok = False
    # ★ 2026-10-09 报告的问题: 屏幕上**只有那一行标签** —— 兜底必须把真跑过的东西列出来
    if "echo 一直在跑" not in answer:
        print("  ✗ 只标了个『用尽』, 连它还想跑什么、跑过什么都没摊出来(白卷)")
        ok = False
    if "一直在跑" not in answer or "全文" not in answer:
        print("  ✗ 命令输出 / 输出全文路径没摊出来")
        ok = False
    if len(answer.strip().splitlines()) < 3:
        print("  ✗ 回答还是只有一行标签")
        ok = False
    return ok


def test_salvage_when_nothing_ran() -> bool:
    """一条命令都没跑成时, 兜底照样得说人话 —— 不是只剩标签。"""
    text = exec_agent.salvage_from_calls("<调用>ls /nope</调用>", "", [])
    print("  兜底文:", text.replace("\n", " / "))
    ok = True
    if "还想跑: ls /nope" not in text:
        print("  ✗ 没把『它还想跑什么』摊出来")
        ok = False
    if "一条命令都没跑成" not in text:
        print("  ✗ 一条没跑成时没交代清楚")
        ok = False
    if len(text.splitlines()) < 2:
        print("  ✗ 只有一行")
        ok = False
    return ok


def main() -> None:
    results: list[tuple[str, bool]] = []
    cases = [
        test_preamble_gets_nudged,
        test_preamble_detector,
        test_conclusion_not_nudged_after_work,
        test_wrapup_rescues_answer,
        test_wrapup_no_fabrication,
        test_salvage_when_nothing_ran,
    ]
    for case in cases:
        print(f"── {case.__name__}")
        results.append((case.__name__, bool(case())))
    passed = sum(1 for _, ok in results if ok)
    print(f"\n{'✓' if passed == len(results) else '✗'} 催促兜底 {passed}/{len(results)}")
    for name, ok in results:
        if not ok:
            print(f"   失败: {name}")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
