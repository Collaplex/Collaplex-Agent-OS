# -*- coding: utf-8 -*-
"""验证取数表修好后，「8790 端口是哪个进程在听」能不能答对。"""
import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
spec = importlib.util.spec_from_file_location("造料", Path(__file__).parent / "造思考语料.py")
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

# 直接看它挑的手段对不对（不跑整轮，快）
for 需求 in ["8790 端口是哪个进程在听", "现在几点了", "磁盘还剩多少空间",
              "帮我写个请假条，说明我明天下午要去医院"]:
    print(f"需求: {需求}\n  → 手段: {m.挑手段(需求) or '（不取数）'}")
