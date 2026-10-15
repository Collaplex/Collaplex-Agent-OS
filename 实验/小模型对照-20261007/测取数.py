# -*- coding: utf-8 -*-
"""单独测 main.gather_evidence —— 刚才产品实测里它报"没拿到可用命令"，要查为什么。

三种可能：
  a) 模型（经 short_call）返回空 / 拿不出命令
  b) 命令超过 200 字被我自己挡了
  c) 命令里带写操作被第二道闸作废
这里把每一步的原始返回都打出来，别猜。
"""
from __future__ import annotations

import sys
from pathlib import Path

项目 = Path(__file__).parent.parent.parent
sys.path.insert(0, str(项目))

import main  # noqa: E402
import sub_agent  # noqa: E402

样本 = [
    "查看本机硬件与系统配置(CPU/内存/磁盘/系统版本)",
    "查根分区剩余空间",
    "读取本机文件 /home/lou/桌面/llama.cpp/app/llama.cpp 的内容",
]

if __name__ == "__main__":
    客户端, 模型 = sub_agent.build_client()
    print(f"模型 {模型}\n")
    for 需求 in 样本:
        print(f"── 需要：{需求}")
        try:
            出 = main.gather_evidence("看看这台机器是什么配置", 需求, 客户端, 模型)
        except Exception as e:  # 云端什么都可能
            print(f"   ✗ 抛异常: {type(e).__name__}: {e}\n")
            continue
        if 出 is None:
            print("   ✗ 返回 None（没拿到可用命令）\n")
        else:
            print(f"   ✓ 命令: {出['命令']}")
            print(f"     输出: {出['输出'][:200]!r}\n")
