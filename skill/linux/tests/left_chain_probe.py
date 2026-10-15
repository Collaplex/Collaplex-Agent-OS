#!/usr/bin/env python3
"""左链路由探针 —— 只跑 判断(need/wanted) + 检索skill + 挑选(声明), 不带 exec.

查看"什么该走左链、什么不该", 以及真走左链时挑中的是不是期望的那个（`linux` 或本系统手册 `ops`）。
不跑命令、不写库, 只读.

跑法:
    .venv/bin/python skill/linux/tests/left_chain_probe.py
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent            # skill/linux/tests
PROJECT = HERE.parent.parent.parent               # 项目根
sys.path.insert(0, str(PROJECT))

import main as project_main  # noqa: E402  (要先插 sys.path)
import sub_agent  # noqa: E402

# (问题, 期望: 该不该走左链, 期望挑中的 skill; 不走左链时最后一项留空)
CASES: list[tuple[str, bool, str]] = [
    ("磁盘还剩多少空间", True, "linux"),
    ("谁占着 8789 端口", True, "linux"),
    ("现在跑着哪些进程", True, "linux"),
    ("我的定时任务都有啥", True, "linux"),
    ("根分区快满了吗", True, "linux"),
    ("U 盘挂上了没有", True, "linux"),
    ("日志里最近报了啥错", True, "linux"),
    # ★ 问「这套系统自己」的用法/维护: 主语是本系统 -> 要走左链, 且挑中 ops 手册
    ("这套系统的清洗怎么跑", True, "ops"),
    ("这套系统的日志在哪", True, "ops"),
    ("加一个新 skill 要改哪几处", True, "ops"),
    ("磁盘满了会有什么后果", False, ""),
    ("linux 的 inode 是什么意思", False, ""),
    ("清洗是什么", False, ""),
    ("systemd 怎么建个服务", False, ""),
    ("帮我把这句话翻成英文", False, ""),
    ("你好，介绍一下你自己", False, ""),
]


def main() -> int:
    print(f"探针: {len(CASES)} 问 (判断 -> 检索skill -> 挑选/声明)\n")
    right = 0
    for number, (question, want_chain, want_skill) in enumerate(CASES, 1):
        # 判断步: 缺缺能力 -> wanted
        prepared = sub_agent.prepare_skill(question)
        wanted = str(prepared["wanted"] or "").strip()
        went_chain = bool(wanted)

        picked_name = ""
        declaration = ""
        if went_chain:
            picked = project_main.find_skill_for(question, wanted)
            if picked is not None:
                picked_name = str(picked["name"])
                declaration = str(picked["声明"])

        ok = went_chain == want_chain and (not went_chain or picked_name == want_skill)
        right += 1 if ok else 0
        print(f"[{'对' if ok else '错'}] {number}. {question}")
        print(f"      判断 wanted={wanted!r}" if went_chain else "      判断 wanted=(空) -> 不走左链")
        if picked_name:
            print(f"      挑中 {picked_name} · 声明 {declaration!r}")
        elif went_chain:
            print("      挑了: 没挑出来(回落自己答)")

    print(f"\n路由对的 {right}/{len(CASES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
