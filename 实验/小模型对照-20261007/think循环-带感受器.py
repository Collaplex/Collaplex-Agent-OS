# -*- coding: utf-8 -*-
"""think 循环 + 感受器 —— 模型只思考，agent 管取数（照老板的分层）

★ 老板的更正（2026-10-07）：
   "专家团不用调工具，调工具是 agent 的事，专家团只要思考思路就可以了，不要搞混了。"

⇒ 分层（本版就按这个写，代码里也分得清清楚楚）：
   ┌ 模型层（专家团 + 输出模型）—— 只想思路；想不通时**说出我还需要知道什么**（自然语言，不是命令）
   └ agent 层（取数器）—— 拿到需求 → **决定用什么手段**（路由）→ 真去拿 → 从**感受器**喂回
     ★ 模型不碰工具、不编数据；agent 不替模型思考。

对比（上一版的毛病）：提示词只让它"说想法" ⇒ 遇到该查机器的题，四个专家全程空谈
（"应持续监控"）⇒ 所以这一版的关键改动是：**让模型开口要数据**，agent 负责满足。
"""
from __future__ import annotations

import json
import re
import subprocess
import time
import urllib.request
from typing import TypedDict

端口 = 8790
模型名 = "qwen3-vl-8b"
专家: list[tuple[str, float]] = [("稳", 0.2), ("发散", 0.9), ("挑刺", 0.5)]
最多轮数 = 4

# ── agent 层：需求（自然语言）→ 手段（命令）。★ 这一步以后归"路由头"，现在先用规则兜底
# ★ 关键词要**严**（"时间"/"系统"/"地址"这种宽词会满世界误配）：
#   实测踩过：「请假时间、医院科室」被配上 `date`；「8790 端口」被配上 `ps aux` ⇒ 答"没有进程绑定"。
# ★ 命令要**能直接看全表**（端口这类必须带参数的查询，用 `ss -ltnp` 列全让模型自己找，
#   不要为它造参数化模板 —— 那层将来归路由头）。
手段表: list[tuple[tuple[str, ...], str]] = [
    (("根分区", "磁盘", "硬盘", "剩余空间", "还剩多少空间"), "df -h /"),
    (("内存", "RAM", "swap"), "free -h"),
    (("几核", "CPU 核心", "处理器核心", "核数", "cpu 型号"), "lscpu | head -20"),
    (("几点", "现在时间", "当前时间", "现在几号", "今天星期"), "date"),
    (("端口", "监听", "在听", "被占用"), "ss -ltnp"),
    (("进程", "占内存", "吃内存"), "ps aux --sort=-%mem | head -8"),
    (("温度", "显存", "显卡", "GPU"), "nvidia-smi --query-gpu=name,temperature.gpu,memory.used,memory.total --format=csv"),
    (("网卡", "本机 IP", "IP 地址"), "ip -brief addr"),
    (("跑了多久", "开机多久", "负载", "负载多少"), "uptime"),
]


class 总结果(TypedDict):
    思路: list[str]
    感受: list[感受器输入]
    正式回答: str
    草稿耗时: float
    正式耗时: float


class 感受器输入(TypedDict):
    轮: int
    需求: str
    手段: str
    结果: str


def 问(提示: str, 温度: float, 上限: int = 70) -> str:
    体 = json.dumps({
        "model": 模型名,
        "messages": [{"role": "user", "content": 提示}],
        "max_tokens": 上限, "temperature": 温度, "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    请 = urllib.request.Request(
        f"http://127.0.0.1:{端口}/v1/chat/completions", data=体,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(请, timeout=180) as r:
        出: dict[str, object] = json.loads(r.read().decode())
    选项 = 出["choices"]
    消息 = 选项[0]["message"]          # type: ignore[index]
    return str(消息["content"]).strip()  # type: ignore[index]


def 抽需求(文本: str) -> str:
    """模型说的人话 ⇒ 抽成需求句。模型给的是"我需要知道什么"，不是命令。"""
    m = re.search(r"需要(?:知道|获取|查看|确认|了解)?[：:]\s*([^\n。；;]+)", 文本)
    return m.group(1).strip() if m else ""


def 挑手段(需求: str) -> str:
    """agent 的活：把需求变成手段（★ 以后换成路由头）"""
    # ★ 最长关键词优先：否则「8790 端口是哪个进程在听」会被"进程"先抢走（实测踩过）
    最好命令, 最好长 = "", 0
    for 关键词组, 命令 in 手段表:
        for k in 关键词组:
            if k in 需求 and len(k) > 最好长:
                最好命令, 最好长 = 命令, len(k)
    return 最好命令


def 取数(命令: str) -> str:
    """agent 真去拿。白名单外的命令不执行。"""
    if not 命令 or 命令 not in {c for _, c in 手段表}:
        return ""
    try:
        出 = subprocess.run(命令, shell=True, capture_output=True, text=True, timeout=20)
        return (出.stdout or 出.stderr).strip()[:400]
    except (subprocess.SubprocessError, OSError) as e:
        return f"(取数出错: {e})"


def 跑(问题: str) -> 总结果:
    思路: list[str] = []
    感受: list[感受器输入] = []
    t0 = time.time()

    for 轮 in range(1, 最多轮数 + 1):
        要要说: list[str] = []
        for 名字, 温 in 专家:
            上文 = "、".join(f"{n}说「{t}」" for n, t in zip([e for e, _ in 专家], 要要说)) if 要要说 else ""
            感受文 = ""
            for s in 感受:
                感受文 += f"[已知] {s['需求']} → {s['结果'][:120]}\n"
            提示 = (
                f"多专家小组一起想这个问题：{问题}\n你是「{名字}」视角。\n"
                + (f"刚刚别人说：{上文}\n" if 上文 else "")
                + (感受文 if 感受文 else "")
                + "规则：\n"
                "1. 一句话，25 字以内，说你的思路。\n"
                "2. ★ 如果光靠想不够、必须知道外部情况才能继续，就直接说你缺什么，"
                "格式：`需要知道：<你要的东西>`。\n"
                "3. 别自己编数据，别假装知道，别客套。\n"
            )
            要要说.append(问(提示, 温, 70))
            思路.append(f"第{轮}轮 {名字}：{要要说[-1]}")

        # ── agent 层动手（模型不碰）
        需求 = 抽需求(要要说[-1]) or next((抽需求(t) for t in 要要说 if 抽需求(t)), "")
        已问过 = {s["需求"] for s in 感受}
        if 需求 and 需求 not in 已问过:
            手段 = 挑手段(需求)
            结果 = 取数(手段)
            if 结果:
                感受.append({"轮": 轮, "需求": 需求, "手段": 手段, "结果": 结果})

        说够了 = any(("想清楚" in t or "可以答" in t or "够了" in t) for t in 要要说)
        if 说够了:
            break

    草稿耗时 = time.time() - t0

    t1 = time.time()
    感受文 = "\n".join(f"[已知] {s['需求']} → {s['结果']}" for s in 感受)
    正式 = 问(
        f"问题：{问题}\n\n你们的思路：\n" + "\n".join(思路[-6:]) + "\n\n"
        + (f"实际查到的情况：\n{感受文}\n\n" if 感受文 else "")
        + "现在只给正式答案，直接回答，别重复思考。",
        0.2, 150)
    正式耗时 = time.time() - t1
    return {"思路": 思路, "感受": 感受, "正式回答": 正式,
            "草稿耗时": 草稿耗时, "正式耗时": 正式耗时}


if __name__ == "__main__":
    判据 = {
        "根分区还剩多少": r"\d+(\.\d+)?\s*[GT]",
        "现在几点了": r"CST|GMT\+8|\d{2}:\d{2}",
    }
    for 题 in 判据:
        print(f"\n{'═' * 66}\n【问题】{题}\n")
        print("<think>")
        r = 跑(题)
        for 行 in r["思路"]:
            print("  " + 行)
        for s in r["感受"]:
            print(f"  ── agent 取数：{s['需求']} → `{s['手段']}`")
            print(f"     感受器输入：{s['结果'][:140].replace(chr(10), ' / ')}")
        print("</think>\n")
        print(f"【正式回答】{r['正式回答']}")
        命中 = bool(re.search(判据[题], r["正式回答"]))
        print(f"\n【判据】{判据[题]} ⇒ {'✓ 答到了' if 命中 else '✗ 没答到'}")
        print(f"【账】think {r['草稿耗时']:.1f}s　正式 {r['正式耗时']:.1f}s"
              f"　agent 取数 {len(r['感受'])} 次")
