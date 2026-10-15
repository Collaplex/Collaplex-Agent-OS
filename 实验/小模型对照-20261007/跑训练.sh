#!/bin/bash
# 训专家：停服务腾显存 → 训 → **无论如何都起回服务**（长任务必须后台跑，别让工具超时把它杀了）
cd /home/lou/桌面/collaplex_agent || exit 1
./start_models.sh stop >/dev/null 2>&1
sleep 3
echo "显存(停后): $(nvidia-smi --query-gpu=memory.used --format=csv,noheader)"
cd 实验/小模型对照-20261007 || exit 1
OMP_NUM_THREADS=4 ~/mineru-env/bin/python 专家-训4.py
echo "训练退出码: $?"
cd /home/lou/桌面/collaplex_agent || exit 1
echo "══ 起回服务"
./start_models.sh start 2>&1 | tail -3
for i in 1 2 3 4 5 6 7 8; do
  u=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits)
  if [ "$u" -gt 6000 ]; then echo "显存已装 ${u} MiB"; break; fi
  sleep 5
done
curl -s --noproxy '*' --max-time 30 http://127.0.0.1:8790/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3-vl-8b","messages":[{"role":"user","content":"回一个字：好"}],"max_tokens":8,"chat_template_kwargs":{"enable_thinking":false}}' \
  | python3 -c "import sys,json;print('主模型回:',json.load(sys.stdin)['choices'][0]['message']['content'])"
