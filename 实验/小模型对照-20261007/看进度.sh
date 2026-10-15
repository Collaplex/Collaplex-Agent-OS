#!/bin/bash
# 看实验跑到哪儿了: 实时进度 + 汇总表。
H={H}
echo "── 汇总 ──"; cat "$H/汇总.md" 2>/dev/null
echo
echo "── 实时进度(最近 25 行, Ctrl-C 退出) ──"
tail -n 25 -f "$H/进度.log"
