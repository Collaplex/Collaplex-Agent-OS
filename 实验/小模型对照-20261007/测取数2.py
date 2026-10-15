# -*- coding: utf-8 -*-
"""看 short_call 的原始返回 —— 上面三条全 None，得看它到底吐了什么。"""
from __future__ import annotations
import sys
from pathlib import Path
项目 = Path(__file__).parent.parent.parent
sys.path.insert(0, str(项目))
import sub_agent  # noqa: E402

需求 = "查看本机硬件与系统配置(CPU/内存/磁盘/系统版本)"
prompt = (
    "把下面这个『要查的东西』变成**一条**能在本机直接跑的 shell 命令。\n"
    "只输出命令本身：不要解释、不要代码块、不要引号包裹、不要多行。\n"
    "只许读本机事实（df / free / lscpu / ss / ps / date / uptime / tail / head / ls / cat / find / wc）。\n"
    "★ 不许出现任何写操作（rm / mv / dd / mkfs / systemctl / kill / apt / pip / sed -i / 重定向）。\n\n"
    f"要查的东西：{需求}\n问题背景：看看这台机器是什么配置"
)
if __name__ == "__main__":
    客户端, 模型 = sub_agent.build_client()
    print(f"模型 {模型}")
    try:
        出 = sub_agent.short_call(客户端, 模型, prompt, "看看这台机器是什么配置", 60)
        print(f"返回类型 {type(出).__name__}｜长度 {len(出)}")
        print(f"原始 = {出!r}")
    except Exception as e:
        print(f"抛异常 {type(e).__name__}: {e}")
