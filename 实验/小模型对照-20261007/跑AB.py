# -*- coding: utf-8 -*-
"""A/B：产品的「该动没动」到底能不能靠流程改掉？

背景（59 条人眼标注，见 标注-59条.md / 标注统计.py）：
  产品**动手就赢**：真的去查/真的会做的那 28 条，89.3% 判「对」；
  但**该动没动的 14 条（23.7%）**里 71% 判「错」—— 其中大量是**直接编答案**
  （把 load average 说成"污垢累积速率"、编出"行业同规模基准"、
   二层热库/三层冷库答成"-18℃冷冻库"）。

老板判过"靠提示词没用"——那是对的（改措辞不会让模型变勤快）。
所以本脚本**不靠感觉**，只干一件事：同一批题，跑两个条件，比一个数。

  条件 A（基线）: 直接问
  条件 B（结构）: 把 think 循环的机制搬进来 —— 先要求它说"我需要知道什么"，
                 agent 执行取数、把结果喂回去，再让它正式回答

★ 判据：不是"哪个答得好看"，而是**「该动没动」的条数**（该查却没查就直接给答案）。
  回答内容的人眼判分复用 标注统计.py 的口径（关键事实是否出现，不比格式）。

用法：
    .venv/bin/python 跑AB.py --条件 A --条数 14      # 只跑标注里"该动没动"的那批
    .venv/bin/python 跑AB.py --条件 B --条数 14
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

产出 = Path(__file__).parent
项目 = 产出.parent.parent

# ★ 只跑"该动没动"这批（标注里的题号）—— 这才是要证明的地方
该动没动题号 = [2, 3, 4, 8, 9, 14, 17, 18, 20, 23, 26, 37, 38, 56]

# ★ 用**产品自己的模型**（.env 的 OPENAI_*）——因为要测的是"产品能不能变好"，
#   不是"本地 8B 行不行"。产品当前是云 mimo（本地 8B 是兜底）。
def _读env() -> tuple[str, str, str]:
    env = 项目 / ".env"
    值: dict[str, str] = {}
    if env.exists():
        for 行 in env.read_text().splitlines():
            行 = 行.strip()
            if not 行 or 行.startswith("#") or "=" not in 行:
                continue
            k, _, v = 行.partition("=")
            值[k.strip()] = v.strip()
    return (值.get("OPENAI_BASE_URL", "http://127.0.0.1:8790/v1"),
            值.get("OPENAI_API_KEY", "local"),
            值.get("OPENAI_MODEL", "qwen3-vl-8b"))


_云端点, _云密钥, _云模型 = _读env()
# ★ 默认用**本地 8B**：59 条基线就是它跑的 ⇒ 同模型对照 = 控制变量，且不花钱。
#   要测"产品那条链"再加 --云（走 .env 的 mimo）。
端点, 密钥, 模型名 = "http://127.0.0.1:8790/v1", "local", "qwen3-vl-8b"

# 取数手段（这只是实验里给 agent 用的最小集；产品里 exec_agent 才是正主）
手段: list[tuple[tuple[str, ...], str]] = [
    (("根分区", "磁盘", "硬盘", "剩余空间"), "df -h /"),
    (("内存", "RAM"), "free -h"),
    (("几核", "CPU", "处理器", "算力", "配置"), "lscpu | head -22"),
    (("内存条", "几条", "型号"), "sudo -n dmidecode -t memory 2>/dev/null | head -30 || echo '（需 root，取不到）'"),
    (("几点", "现在时间", "当前时间", "当前日期", "今天的日期", "今天", "日期", "月份", "几月"), "date +'%Y-%m-%d %A %H:%M %Z'"),
    (("端口", "监听", "在听"), "ss -ltnp"),
    (("进程",), "ps aux --sort=-%mem | head -6"),
    (("温度", "显存", "GPU", "显卡"), "nvidia-smi --query-gpu=name,temperature.gpu,memory.used,memory.total --format=csv"),
    (("报错", "日志"), "tail -30 logs/refine.log 2>/dev/null || echo '（无该日志）'"),
    (("健康", "状态", "负载"), "uptime && free -h"),
    (("文件", "写了什么", "内容", "源码", "代码", "多少行"), ""),   # 留空 = 从问题里抠路径再读
    (("型号", "配置", "什么机器", "硬件"), "lscpu | head -18 && echo '──' && free -h"),
    (("软路由", "路由"), "echo '（软路由在 192.168.10.1，本机不是它）'"),
    (("vllm",), "find /home/lou -maxdepth 4 -type d -name 'vllm*' 2>/dev/null | head -5"),
    (("文件数量", ".py", ".cu", "有多少个"), ""),
    (("算力", "浮点", "FLOPS", "指令"), "lscpu | grep -E 'Model name|Core|MHz|Flags' | head -5"),
    (("记一下", "记下", "记住", "提醒"), "@记"),        # 特殊：走产品的记忆入口，这里只报"已写入"
    (("日志", "报错", "错误"), "tail -30 日志/refine.log 2>/dev/null || ls -la 日志/ 2>/dev/null || echo '（无日志目录）'"),
]


def 问(提示: str, 温: float = 0.2, 上限: int = 300) -> str:
    体 = json.dumps({
        "model": 模型名,
        "messages": [{"role": "user", "content": 提示}],
        "max_tokens": 上限, "temperature": 温, "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
        "thinking": {"type": "disabled"},        # ★ mimo 默认开思考，必须显式关
    }).encode()
    请 = urllib.request.Request(f"{端点}/chat/completions", data=体,
                              headers={"Content-Type": "application/json",
                                       "Authorization": f"Bearer {密钥}"})
    with urllib.request.urlopen(请, timeout=240) as r:
        出: dict[str, Any] = json.loads(r.read().decode())
    return str(出["choices"][0]["message"]["content"]).strip()


def 抽需求(文本: str) -> str:
    m = re.search(r"需要(?:知道|获取|查看|确认|了解|读)?[：:]\s*([^\n。；;]+)", 文本)
    return m.group(1).strip() if m else ""


def 挑手段(需求: str) -> str:
    最好, 长 = "", 0
    for 组, 命令 in 手段:
        for k in 组:
            if k in 需求 and len(k) > 长:
                最好, 长 = 命令, len(k)
    return 最好


def 取数(命令: str, 问题: str = "") -> str:
    if not 命令 and 问题:
        # "文件里写了什么" —— 从问题里抠路径
        m = re.search(r"(/[\w./\-.]+)", 问题)
        if m:
            命令 = f"head -20 {m.group(1)}"
    if not 命令:
        return ""
    try:
        出 = subprocess.run(命令, shell=True, capture_output=True, text=True, timeout=25)
        return (出.stdout or 出.stderr).strip()[:600]
    except (subprocess.SubprocessError, OSError) as e:
        return f"(取数出错: {e})"


def 跑A(问题: str) -> tuple[str, str]:
    return 问(问题), ""


def 跑B(问题: str) -> tuple[str, str]:
    """结构版：先逼它说需求 → agent 取数 → 喂回去再答。"""
    第1轮 = 问(
        f"{问题}\n\n"
        "★ 先别答。要答准这条，你需要知道哪些外部情况？"
        "如果必须查了才知道，就只说这一句：`需要知道：<要查什么>`。"
        "只有确实是纯知识题（不用查任何本机状态）才可以直接答。", 0.2, 120)
    需求 = 抽需求(第1轮)
    证据 = ""
    if 需求:
        命令 = 挑手段(需求)
        证据 = 取数(命令, 问题)
    if not 证据:
        return 第1轮, 需求
    正式 = 问(
        f"问题：{问题}\n\n"
        f"你刚才说需要知道：{需求}\n"
        f"实际查到的结果：\n{证据}\n\n"
        "现在只给正式回答，直接回答，不要重复思考、不要提\"查询过程\"。", 0.2, 300)
    return 正式, f"{需求} ⇒ {证据[:80]}"


if __name__ == "__main__":
    解 = argparse.ArgumentParser()
    解.add_argument("--条件", default="A", choices=["A", "B"])
    解.add_argument("--条数", type=int, default=len(该动没动题号))
    解.add_argument("--云", action="store_true", help="改用 .env 的产品模型（mimo 云）")
    解.add_argument("--全", action="store_true", help="跑全部 59 条（默认只跑『该动没动』那 14 条）")
    参 = 解.parse_args()
    if 参.云:
        端点, 密钥, 模型名 = _云端点, _云密钥, _云模型
        print(f"（用云端 {模型名}）")

    题库 = []
    for 行 in (产出 / "题库.jsonl").read_text().splitlines():
        if 行.strip():
            题库.append(json.loads(行))
    if 参.全:
        要跑 = [(i, t.get("题", "")) for i, t in enumerate(题库, 1)]
    else:
        要跑 = [(i, 题库[i - 1].get("题", "")) for i in 该动没动题号[:参.条数] if i - 1 < len(题库)]

    结果: list[dict[str, Any]] = []
    起点 = time.time()
    print(f"═══ 条件 {参.条件}｜{len(要跑)} 条（都是标注里『该动没动』的）═══\n")
    for 号, 题 in 要跑:
        try:
            答, 过程 = (跑A(题) if 参.条件 == "A" else 跑B(题))
        except (urllib.error.URLError, TimeoutError, KeyError) as e:
            print(f"[{号}] 出错跳过: {e}")
            continue
        结果.append({"号": 号, "题": 题, "答": 答, "过程": 过程})
        print(f"[{号}] {题[:40]}")
        if 过程:
            print(f"    agent: {过程[:90]}")
        print(f"    答: {答[:110]}\n")

    文件 = 产出 / f"AB-条件{参.条件}.jsonl"
    with 文件.open("w") as f:
        for x in 结果:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    print(f"完成 {len(结果)} 条，用时 {(time.time() - 起点) / 60:.1f} 分钟")
    print(f"结果 → {文件}")
    print("\n★ 判分口径见 标注统计.py：只看『关键事实是否出现』，不比格式。")
    print("  跑完请人眼过一遍，重点看『该查的有没有去查』——这才是条件 B 要证明的。")
