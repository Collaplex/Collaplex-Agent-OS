#!/usr/bin/env python3
"""追问不许断档回归 —— 子 agent 的分析/判断两步必须看见"上一轮说了什么".

背景(老板 2026-10-09 实测原话): "子agent给主agent拼记忆得加上上一次对话的输出让子agent去识别,
不然容易断档, 刚刚就出现了"。

查下来的形状: recent_turn_hits 那条"最近几轮原文"的注入**只给了主 agent**(和 exec)当材料,
子 agent **自己**的分析 / 判断两步却只拿到**这一句** —— 于是

  - 分析步: "那两个也处理了"在它眼里没头没尾 -> 只能拿"那两个"去检索, 规划不出像样的问句
  - 判断步: 同一句也判不准(是让本机真的动一下, 还是接着上文问概念?)

规矩: 最近一轮的问 + 答, 以【上文 · 刚刚发生过的对话】块的形式进**分析/判断两步的 user 消息**,
并明说"那是已经发生过的, 不是这一轮要办的事"(不说清, 模型会把上一轮的事当成这一轮的)。

测试方法: 模型用假的(不打网络、不花钱) —— 假模型把每次 create 的 kwargs 记下来,
直接查 user 消息里有没有那块。检索也换成假的(不起子进程)。

跑法: .venv/bin/python tests/test_followup_context.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path.insert(0, str(PROJECT))

import sub_agent  # noqa: E402

上一轮问 = "看看当前目录下有多少个 py 文件"
上一轮答 = "当前目录下有 14 个 .py 文件，最大的那个是 sub_agent.py。"
这一轮问 = "那两个也处理了"
历史一轮: list[dict[str, str]] = [{"问": 上一轮问, "答": 上一轮答}]

分析输出 = '{"queries": ["py 文件 批量处理", "当前目录 py 文件"], "think": false, "reason": "接着上文"}'
判定输出 = '{"need": false, "wanted": ""}'
被截的判定 = '{"need": true, "wanted": "把那两个'


class 假模型:
    """假模型: 按顺序把预设文本当模型输出发回来, 并把每次收到的参数记下来。

    `base_url` 指向本机一个必然没人听的端口(9/discard) —— prepare_skill 会用它去问
    总上下文窗口, 连不上就回落配置值, 这样测试不碰真网络。
    """

    def __init__(self, 输出表: list[str]) -> None:
        self.输出表: list[str] = list(输出表)
        self.调用次数: int = 0
        self.收到的参数: list[dict[str, Any]] = []
        self.base_url: str = "http://127.0.0.1:9/v1"
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> Any:
        self.调用次数 += 1
        self.收到的参数.append(dict(kwargs))
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


def 判据(名: str, 通过: bool, 说明: str = "") -> bool:
    print(f"  {'通过' if 通过 else '不过'}  {名}{('  ' + 说明) if 说明 else ''}")
    return 通过


def 取user消息(参数: dict[str, Any]) -> str:
    """从假模型记下的调用参数里把 user 那一句抠出来。"""
    消息们 = cast(list[dict[str, Any]], 参数["messages"])
    return str(消息们[-1]["content"])


def 测_上文块本身() -> list[bool]:
    print("\n一、history_briefing: 块长什么样")
    结果: list[bool] = []

    空 = sub_agent.history_briefing(None)
    结果.append(判据("没历史 -> 空串(不塞空块)", 空 == "", 说明=f"(得到 {空!r})"))

    零轮 = sub_agent.history_briefing(历史一轮, 轮数=0)
    结果.append(判据("轮数=0 -> 空串(可关)", 零轮 == ""))

    一块 = sub_agent.history_briefing(历史一轮)
    结果.append(判据(
        "一轮 -> 带上文问+答原文, 且标明'已经发生过'",
        (上一轮问 in 一块) and (上一轮答 in 一块) and (sub_agent.上文头 in 一块)
        and 一块.rstrip().endswith(sub_agent.上文尾),
        说明=f"({len(一块)} 字符)",
    ))

    两轮 = sub_agent.history_briefing(
        [{"问": "更早的问", "答": "更早的答"}, *历史一轮], 轮数=2
    )
    结果.append(判据(
        "轮数=2 -> 最近两轮都在",
        ("更早的问" in 两轮) and (上一轮问 in 两轮),
    ))

    短 = sub_agent.history_briefing(历史一轮, 答上限=10)
    结果.append(判据(
        "答超上限 -> 截断并标注",
        ("…(截断)" in 短) and (上一轮答 not in 短),
        说明=f"({短[短.index('答: '):短.index('答: ') + 30]!r}…)",
    ))
    return 结果


def 测_分析步带上文() -> list[bool]:
    print("\n二、分析步(plan_queries): user 消息里得有上一轮")
    结果: list[bool] = []
    块 = sub_agent.history_briefing(历史一轮)

    带 = 假模型([分析输出])
    sub_agent.plan_queries(cast(Any, 带), "假模型", 这一轮问, 3, 上文=块)
    消息 = 取user消息(带.收到的参数[0])
    结果.append(判据(
        "带上文 -> 消息里有上一轮的答, 且这一轮那句在最后",
        (上一轮答 in 消息) and 消息.rstrip().endswith(这一轮问)
        and (sub_agent.上文头 in 消息),
       说明=f"(消息 {len(消息)} 字符)",
    ))

    不带 = 假模型([分析输出])
    sub_agent.plan_queries(cast(Any, 不带), "假模型", 这一轮问, 3)
    消息2 = 取user消息(不带.收到的参数[0])
    结果.append(判据(
        "没上文(首轮) -> 消息就是这一句, 不塞空块",
        消息2 == 这一轮问,
       说明=f"(得到 {消息2!r})",
    ))
    return 结果


def 测_判断步带上文() -> list[bool]:
    print("\n三、判断步(judge_skill): 首答和重试那次都得带上文")
    结果: list[bool] = []
    块 = sub_agent.history_briefing(历史一轮)
    配置 = {"enabled": True}

    一次 = 假模型([判定输出])
    sub_agent.judge_skill(cast(Any, 一次), "假模型", 这一轮问, 配置, max_tokens=1200, 上文=块)
    结果.append(判据(
        "带上文 -> 判定步也看得见上一轮",
        上一轮答 in 取user消息(一次.收到的参数[0]),
       说明=f"({一次.调用次数} 次调用)",
    ))

    两次 = 假模型([被截的判定, 判定输出])
    sub_agent.judge_skill(cast(Any, 两次), "假模型", 这一轮问, 配置, max_tokens=1200, 上文=块)
    结果.append(判据(
        "被截重试 -> 重试那次的 user 消息也带上文(不许只在首次带)",
        两次.调用次数 == 2
        and all(上一轮答 in 取user消息(参数) for 参数 in 两次.收到的参数),
       说明=f"({两次.调用次数} 次调用)",
    ))
    return 结果


def 测_全链接上了() -> list[bool]:
    print("\n四、prepare_skill 全链: 两块都接上了, 开关也认")
    结果: list[bool] = []
    真配置 = sub_agent.load_config()
    原_建客户端 = sub_agent.build_client
    原_检索 = sub_agent.recall_memory

    def 假_建客户端() -> tuple[Any, str]:
        return (假_当前[0], "假模型")

    假_当前: list[假模型] = [假模型([分析输出, 判定输出])]
    try:
        sub_agent.build_client = 假_建客户端  # type: ignore[assignment]
        sub_agent.recall_memory = lambda queries, rag: []  # type: ignore[assignment]

        配置 = copy.deepcopy(真配置)
        配置["history_context"] = {"enabled": True, "turns": 1, "answer_chars": 400}
        出 = sub_agent.prepare_skill(这一轮问, config=配置, 历史=历史一轮)
        消息们 = [取user消息(参数) for 参数 in 假_当前[0].收到的参数]
        结果.append(判据(
            "分析 + 判断两步都带上了上一轮",
            len(消息们) == 2 and all(上一轮答 in 消息 for 消息 in 消息们),
           说明=f"(调了 {假_当前[0].调用次数} 次: {'分析/判断'} 各一条)",
        ))
        结果.append(判据(
            "主 agent 那份材料(最近几轮原文)照旧在",
            上一轮答 in str(出["skill"]),
        ))

        假_当前[0] = 假模型([分析输出, 判定输出])
        配置2 = copy.deepcopy(真配置)
        配置2["history_context"] = {"enabled": False}
        sub_agent.prepare_skill(这一轮问, config=配置2, 历史=历史一轮)
        消息们2 = [取user消息(参数) for 参数 in 假_当前[0].收到的参数]
        结果.append(判据(
            "history_context.enabled=false -> 两步都不带上文(可回滚)",
            len(消息们2) == 2
            and all((sub_agent.上文头 not in 消息) for 消息 in 消息们2),
        ))

        假_当前[0] = 假模型([分析输出, 判定输出])
        配置3 = copy.deepcopy(真配置)
        配置3["history_context"] = {"enabled": True, "turns": 1, "answer_chars": 12}
        sub_agent.prepare_skill(这一轮问, config=配置3, 历史=历史一轮)
        消息3 = 取user消息(假_当前[0].收到的参数[0])
        结果.append(判据(
            "answer_chars 生效 -> 块里那条答被截断",
            ("…(截断)" in 消息3) and (上一轮答 not in 消息3),
        ))
    finally:
        sub_agent.build_client = 原_建客户端  # type: ignore[assignment]
        sub_agent.recall_memory = 原_检索  # type: ignore[assignment]
    return 结果


def main() -> int:
    print("追问不许断档回归 —— 子 agent 的分析/判断两步看得见上一轮吗")
    结果: list[bool] = []
    结果 += 测_上文块本身()
    结果 += 测_分析步带上文()
    结果 += 测_判断步带上文()
    结果 += 测_全链接上了()

    好 = sum(1 for row in 结果 if row)
    print(f"\n合计 {好}/{len(结果)} 通过")
    return 0 if 好 == len(结果) else 1


if __name__ == "__main__":
    raise SystemExit(main())
