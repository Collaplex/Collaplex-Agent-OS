# -*- coding: utf-8 -*-
"""实测产品的「判断」节点：它到底判"不需要"，还是**输出被截/解析失败**？

为什么必须测这个（决定改哪儿）：
  judge.md 的判据写得极细，A 里那 14 条它**逐条都定义了**（"答案在机器上不在脑子里"）。
  但产品还是回落自己答 -> 开始编。源码里写着两种可能：
    a) 模型真判 need=false      -> 要动判据/加硬规则
    b) 输出被截 / 解析失败      -> 只改 max_tokens 一个数
  所以直接拿产品的 judge prompt + short_call 跑一遍，看原始输出。

用法：.venv/bin/python 测判断节点.py
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

产出 = Path(__file__).parent
项目 = 产出.parent.parent
sys.path.insert(0, str(项目))

# 直接借产品的配置读取
import sub_agent  # noqa: E402

# 挑 A 里判错的几条代表作
样本 = [
    (2, "软路由的型号和配置是什么"),
    (4, "二层热库和三层冷库有什么区别"),
    (14, "看看这台机器是什么配置"),
    (26, "/home/lou/桌面/llama.cpp/app/llama.cpp 这个文件里写了点什么"),
    (5, "根分区还剩多少"),          # 这条是"对的"，拿它做反例（看会不会被误判成不用动）
]


def 原始问(prompt: str, 问题: str, 上限: int) -> tuple[str, str]:
    """不走产品的解析，直接看原始返回 —— 这样才能分清"被截"还是"真判不需要"。"""
    import os
    端点 = os.getenv("SUBAGENT_BASE_URL") or os.getenv("OPENAI_BASE_URL") or ""
    密钥 = os.getenv("SUBAGENT_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
    模型 = os.getenv("SUBAGENT_MODEL") or os.getenv("OPENAI_MODEL") or "qwen3-vl-8b"
    体 = json.dumps({
        "model": 模型,
        "messages": [{"role": "system", "content": prompt},
                     {"role": "user", "content": 问题}],
        "max_tokens": 上限, "temperature": 0,
        "thinking": {"type": "disabled"},
    }).encode()
    请 = urllib.request.Request(f"{端点}/chat/completions", data=体,
                              headers={"Content-Type": "application/json",
                                       "Authorization": f"Bearer {密钥}"})
    with urllib.request.urlopen(请, timeout=180) as r:
        出: dict[str, Any] = json.loads(r.read().decode())
    选 = 出["choices"][0]
    return str(选["message"]["content"]), str(选.get("finish_reason", "?"))


if __name__ == "__main__":
    提示 = sub_agent.load_prompt("judge")
    配置 = sub_agent.load_config()
    上限 = int(配置.get("skill_retrieval", {}).get("max_tokens", 200))
    print(f"judge prompt {len(提示)} 字｜判断步 max_tokens = {上限}")
    import os
    print(f"模型 {os.getenv('OPENAI_MODEL', '?')}\n")

    for 号, 题 in 样本:
        内容, 结束 = 原始问(提示, 题, 上限)
        能解析 = "need" in 内容
        print(f"[{号}] {题[:44]}")
        print(f"    finish_reason = {结束}｜能解析 = {能解析}")
        print(f"    原始输出 = {内容[:160]!r}\n")
