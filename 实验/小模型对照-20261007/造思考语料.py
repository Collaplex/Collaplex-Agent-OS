# -*- coding: utf-8 -*-
"""造思考语料 —— 用 8B 跑 think 循环，判据筛出"答到题"的轨迹，当专家的训练语料

为什么这么做（老板的路子）：
    "输出模型不用很强" + "专家模型需要从输出模型中来，因为是草稿模型"
    ⇒ 专家的语料不该是项目文档（那样它只会吐文档碎片），
      该是**输出模型自己产出的、经判据验证过的思考轨迹** ⇒ 这就是蒸馏。

产物：`思考语料.jsonl`，每条 = {题, think(多轮专家对话全文), 正式回答, 判据命中}
      ★ 只留**判据命中**的——让专家学"好的思考长什么样"。

逻辑与 `think循环-带感受器.py` 一致（那边是实验台，这里是批量造料）。
"""
from __future__ import annotations

import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, TypedDict, cast

项目 = Path("/home/lou/桌面/collaplex_agent")
产出 = 项目 / "实验/小模型对照-20261007"
题库 = 产出 / "题库.jsonl"
料文件 = 产出 / "思考语料.jsonl"

端口 = 8790
模型名 = "qwen3-vl-8b"
专家: list[tuple[str, float]] = [("稳", 0.2), ("发散", 0.9), ("挑刺", 0.5)]
最多轮数 = 4

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


class 一条(TypedDict):
    题: str
    think: str
    正式回答: str
    命中: bool


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
        出: dict[str, Any] = json.loads(r.read().decode())
    return str(出["choices"][0]["message"]["content"]).strip()


def 抽需求(文本: str) -> str:
    m = re.search(r"需要(?:知道|获取|查看|确认|了解)?[：:]\s*([^\n。；;]+)", 文本)
    return m.group(1).strip() if m else ""


def 挑手段(需求: str) -> str:
    # ★ 最长关键词优先：否则「8790 端口是哪个进程在听」会被"进程"先抢走（实测踩过）
    最好命令, 最好长 = "", 0
    for 关键词组, 命令 in 手段表:
        for k in 关键词组:
            if k in 需求 and len(k) > 最好长:
                最好命令, 最好长 = 命令, len(k)
    return 最好命令


def 取数(命令: str) -> str:
    if not 命令 or 命令 not in {c for _, c in 手段表}:
        return ""
    try:
        出 = subprocess.run(命令, shell=True, capture_output=True, text=True, timeout=20)
        return (出.stdout or 出.stderr).strip()[:400]
    except (subprocess.SubprocessError, OSError) as e:
        return f"(取数出错: {e})"


def 跑一题(问题: str, 判据: str) -> 一条:
    思路: list[str] = []
    感受: list[tuple[str, str, str]] = []
    for 轮 in range(1, 最多轮数 + 1):
        要要说: list[str] = []
        for 名字, 温 in 专家:
            上文 = "、".join(f"{n}说「{t}」" for n, t in zip([e for e, _ in 专家], 要要说)) if 要要说 else ""
            感受文 = "".join(f"[已知] {d} → {r[:120]}\n" for d, _, r in 感受)
            提示 = (
                f"多专家小组一起想这个问题：{问题}\n你是「{名字}」视角。\n"
                + (f"刚刚别人说：{上文}\n" if 上文 else "")
                + 感受文
                + "规则：\n1. 一句话，25 字以内，说你的思路。\n"
                  "2. ★ 如果光靠想不够、必须知道外部情况才能继续，就直接说你缺什么，"
                  "格式：`需要知道：<你要的东西>`。\n3. 别自己编数据，别假装知道，别客套。\n")
            要要说.append(问(提示, 温, 70))
            思路.append(f"第{轮}轮 {名字}：{要要说[-1]}")

        需求 = 抽需求(要要说[-1]) or next((抽需求(t) for t in 要要说 if 抽需求(t)), "")
        已问 = {d for d, _, _ in 感受}
        if 需求 and 需求 not in 已问:
            手段 = 挑手段(需求)
            结果 = 取数(手段)
            if 结果:
                感受.append((需求, 手段, 结果))
                print(f"    [agent] {需求} → {手段}")

        if any(("想清楚" in t or "可以答" in t or "够了" in t) for t in 要要说):
            break

    感受文 = "\n".join(f"[已知] {d} → {r}" for d, _, r in 感受)
    正式 = 问(
        f"问题：{问题}\n\n你们的思路：\n" + "\n".join(思路[-6:]) + "\n\n"
        + (f"实际查到的情况：\n{感受文}\n\n" if 感受文 else "")
        + "现在只给正式答案，直接回答，别重复思考。", 0.2, 150)
    return {"题": 问题, "think": "\n".join(思路), "正式回答": 正式,
            "命中": bool(re.search(判据, 正式)) if 判据 else False}


if __name__ == "__main__":
    题单: list[tuple[str, str]] = []
    for 行 in 题库.read_text().splitlines():
        if 行.strip():
            条: dict[str, Any] = json.loads(行)
            题 = str(条.get("题", "")).strip()
            if 题:
                题单.append((题, str(条.get("判据", ""))))
    题单 = 题单[:59]
    print(f"题 {len(题单)} 道，开始造思考语料（判据只留答到题的）…\n")

    已有: list[一条] = []
    if 料文件.exists():
        已有 = [cast(一条, json.loads(l)) for l in 料文件.read_text().splitlines() if l.strip()]
        已做 = {x["题"] for x in 已有}
        题单 = [(t, j) for t, j in 题单 if t not in 已做]
        print(f"（续跑：已做 {len(已做)} 道）")

    t0 = time.time()
    for i, (题, 判) in enumerate(题单, 1):
        print(f"[{i}/{len(题单)}] {题}")
        try:
            结果条: 一条 = 跑一题(题, 判)
        except (urllib.error.URLError, TimeoutError, KeyError) as e:
            print(f"    出错跳过: {e}")
            continue
        已有.append(结果条)
        print(f"    ⇒ {'✓ 答到' if 结果条['命中'] else '✗ 没答到'}｜{结果条['正式回答'][:50]}")
        with 料文件.open("a") as f:
            f.write(json.dumps(结果条, ensure_ascii=False) + "\n")

    命中 = sum(1 for x in 已有 if x["命中"])
    print(f"\n完成：{len(已有)} 条，答到 {命中} 条（{命中 / max(len(已有), 1):.1%}），"
          f"用时 {(time.time() - t0) / 60:.1f} 分钟")
    print(f"语料 → {料文件}")
