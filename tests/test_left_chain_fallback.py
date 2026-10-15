#!/usr/bin/env python3
"""左链兜底回归 —— 判定/挑选这步坏了, 主流程必须还能把活派出去.

背景(实测踩到): 问「看看 vllm 下面 .py 和 .cu 文件分别有多少个, 同时查看 8790 端口是哪个进程在跑」
子 agent 的判断那步输出被截(`{"need": true, "wanted": "统计 vllm 目录下 .py 和 .c`), 解析不出来
-> 旧代码当成"不需要 skill" -> 整条左链跳过 -> 回落主 skill(seek) -> seek 手头没有执行体 ->
它答"我这边当前没有可以跑命令的工具", 还把 find/lsof 丢给用户自己跑。**活一件没干**。

这里的规矩: 模型这步的结论只是"建议", 坏掉了不能变成"不需要" —— 兜底必须放程序里。
测试方法: 模型用假的(不打真网络、不花钱), **检索用真的**(真起 skill_search 子进程)。

跑法: .venv/bin/python tests/test_left_chain_fallback.py
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

# 实测那道题的原文 —— 兜底能不能把它派给 linux, 是最直接的判据
真问题 = "看看vllm下面.py和.cu文件分别有多少个，同时查看8790端口是哪个进程在跑"
被截的判定 = '{"need": true, "wanted": "统计 vllm 目录下 .py 和 .c'
说都不合适 = '{"use": false, "pick": "", "声明": ""}'


class 假模型:
    """假模型: 按顺序把预设文本当模型输出发回来(流式/非流式都装得像)."""

    def __init__(self, 输出表: list[str]) -> None:
        self.输出表: list[str] = list(输出表)
        self.调用次数: int = 0
        self.收到的参数: list[dict[str, Any]] = []
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


def 测_检索词兜底() -> list[bool]:
    print("\n一、判定没结论时, 拿什么去检索 skill")
    结果: list[bool] = []
    结果.append(判据(
        "说了缺什么 -> 用它",
        main_mod.retrieval_term({"wanted": "查端口", "need": True, "broken": False}, 真问题) == "查端口",
    ))
    结果.append(判据(
        "被截(broken) -> 拿用户原话兜",
        main_mod.retrieval_term({"wanted": "", "need": False, "broken": True}, 真问题) == 真问题,
    ))
    结果.append(判据(
        "说要却没说是什么(need) -> 拿用户原话兜",
        main_mod.retrieval_term({"wanted": "", "need": True, "broken": True}, 真问题) == 真问题,
    ))
    结果.append(判据(
        "明确说不需要 -> 空(不乱派)",
        main_mod.retrieval_term({"wanted": "", "need": False, "broken": False}, 真问题) == "",
    ))
    return 结果


def 测_判定步重试与标记() -> list[bool]:
    print("\n二、判定这步: 被截要重试, 两次都不行要标 broken")
    结果: list[bool] = []
    配置 = {"enabled": True}

    假 = 假模型([被截的判定, '{"need": true, "wanted": "查 8790 端口的进程"}'])
    判定 = sub_agent.judge_skill(cast(Any, 假), "假模型", 真问题, 配置, max_tokens=1200)
    结果.append(判据(
        "第一次被截 -> 重试一次拿到结论",
        假.调用次数 == 2 and 判定 == {"need": True, "wanted": "查 8790 端口的进程", "broken": False},
        说明=f"(调了 {假.调用次数} 次, 判定={判定})",
    ))

    假2 = 假模型([被截的判定, 被截的判定])
    判定2 = sub_agent.judge_skill(cast(Any, 假2), "假模型", 真问题, 配置, max_tokens=1200)
    结果.append(判据(
        "两次都被截 -> broken, 不许当'不需要'",
        判定2["broken"] is True and 判定2["need"] is False and 假2.调用次数 == 2,
        说明=f"(判定={判定2})",
    ))

    假3 = 假模型(['{"need": true}'])
    判定3 = sub_agent.judge_skill(cast(Any, 假3), "假模型", 真问题, 配置, max_tokens=1200)
    结果.append(判据(
        "说要却没说是什么 -> broken",
        判定3["broken"] is True and 判定3["need"] is True,
        说明=f"(判定={判定3})",
    ))

    假4 = 假模型(['{"need": false, "wanted": ""}'])
    判定4 = sub_agent.judge_skill(cast(Any, 假4), "假模型", "什么是 inode", 配置, max_tokens=1200)
    结果.append(判据(
        "正常说不需要 -> 不重试不标坏",
        判定4 == {"need": False, "wanted": "", "broken": False} and 假4.调用次数 == 1,
        说明=f"(调了 {假4.调用次数} 次)",
    ))
    return 结果


def 测_挑选不许回落() -> list[bool]:
    print("\n三、挑选说'都不合适'时, 程序按最相关的候选派(检索走真的)")
    结果: list[bool] = []

    假 = 假模型([说都不合适])
    选中 = main_mod.find_skill_for(真问题, 真问题, client=cast(Any, 假), model="假模型")
    结果.append(判据(
        "拿用户原话检索 -> 不是 None(没回落自己答)",
        选中 is not None,
    ))
    if 选中 is not None:
        结果.append(判据(
            "派的是检索最相关那个(linux)",
            选中["name"] == "linux",
            说明=f"(派给 {选中['name']})",
        ))
        结果.append(判据(
            "声明带着用户的活(没丢)",
            bool(选中.get("声明")) and "8790" in str(选中["声明"]),
            说明=f"(声明={选中['声明'][:40]}…)",
        ))
        # ★ 别把候选数写死: 它跟 config/sub_agent.json 的 skill_search.top_k 是一回事。
        #   写死 3 会在配置放宽之后仍然假红 —— file 实测排第 5，本来就在"取 3 个"的窗口外。
        候选数 = int(sub_agent.load_config()["skill_search"]["top_k"])
        结果.append(判据(
            f"候选里既有 linux 也有 file(两个技能都注册上了, 候选取 {候选数} 个)",
            {"linux", "file"}.issubset(
                {
                    str(c["name"])
                    for c in sub_agent.search_skills(
                        真问题, {"entry": "skill/skill_search/main.py", "top_k": 候选数}
                    )
                }
            ),
        ))

    假2 = 假模型(['{"use": true, "pick": "file", "声明": "把 add 改成乘法"}'])
    选中2 = main_mod.find_skill_for(真问题, 真问题, client=cast(Any, 假2), model="假模型")
    结果.append(判据(
        "模型正常挑 -> 照它挑的派",
        选中2 is not None and 选中2["name"] == "file",
        说明=f"(派给 {选中2['name'] if 选中2 else None})",
    ))
    return 结果


def 测_不可交办的件不许派() -> list[bool]:
    print("\n四、元技能/花钱的件不许派给执行体(挑选与回落都按剔完的清单走)")
    结果: list[bool] = []

    名单 = set(main_mod.不可交办名单())
    结果.append(判据(
        "配置里读到了不可交办名单",
        名单 >= {"skill_search", "outsource", "mtp"},
        说明=f"(名单={sorted(名单)})",
    ))

    合成 = [
        {"name": "outsource", "description": "摇人请外援"},
        {"name": "skill_search", "description": "给一句话找出该用哪个 skill"},
        {"name": "linux", "description": "本机操作"},
    ]
    留 = [str(c["name"]) for c in main_mod.能交办的(合成)]
    结果.append(判据(
        "合成清单: 剔掉 outsource/skill_search, 只留 linux",
        留 == ["linux"],
        说明=f"(留下 {留})",
    ))

    # 实测那道题的原话检索会把 outsource / skill_search 带出来 —— 回落取第一名时绝不许派它
    原话 = "这个开源软件支持中文吗？"
    候选名 = [str(c["name"]) for c in sub_agent.search_skills(原话, {"entry": "skill/skill_search/main.py", "top_k": 3})]
    假 = 假模型([说都不合适])
    选中 = main_mod.find_skill_for(原话, 原话, client=cast(Any, 假), model="假模型")
    结果.append(判据(
        "模型说'都不合适'时, 派出去的绝不是元技能/花钱的件",
        选中 is None or str(选中["name"]) not in 名单,
        说明=f"(原话候选={候选名} → 派给 {选中['name'] if 选中 else None})",
    ))

    假2 = 假模型(['{"use": true, "pick": "skill_search", "声明": "找出该用哪个 skill"}'])
    选中2 = main_mod.find_skill_for(原话, 原话, client=cast(Any, 假2), model="假模型")
    结果.append(判据(
        "模型指名要挑元技能 -> 也不派它(改派可派的那个)",
        选中2 is None or str(选中2["name"]) not in 名单,
        说明=f"(派给 {选中2['name'] if 选中2 else None})",
    ))

    日志 = main_mod.挑技能日志
    尾巴 = ""
    if 日志.exists():
        尾巴 = 日志.read_text(encoding="utf-8").strip().splitlines()[-1]
    落了 = False
    派出 = ""
    if 尾巴:
        try:
            最后一 = json.loads(尾巴)
            落了 = "派出" in 最后一 and "剔完可派" in 最后一
            派出 = str(最后一.get("派出"))
        except json.JSONDecodeError:
            落了 = False
    结果.append(判据(
        "挑 skill 的结论落了盘(logs/挑技能.jsonl: 检索词/候选/剔完可派/模型挑中/派出)",
        落了,
        说明=f"(最后一行派出={派出})",
    ))
    return 结果


def 主() -> int:
    print("=" * 100)
    print("左链兜底回归 —— 判定/挑选坏了, 活还得派出去")
    print("=" * 100)
    全部: list[bool] = []
    全部 += 测_检索词兜底()
    全部 += 测_判定步重试与标记()
    全部 += 测_挑选不许回落()
    全部 += 测_不可交办的件不许派()
    通过 = sum(1 for x in 全部 if x)
    print("\n" + "=" * 100)
    print(f"结果: {通过} 通过 / {len(全部) - 通过} 失败")
    print("=" * 100)
    return 0 if 通过 == len(全部) else 1


if __name__ == "__main__":
    raise SystemExit(主())
