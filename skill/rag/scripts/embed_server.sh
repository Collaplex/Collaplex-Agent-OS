#!/usr/bin/env bash
# 向量服务 (Qwen3-Embedding-0.6B) 起停. 用法: ./embed_server.sh start|stop|status|log
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$HERE/../../../.env"
LOG="$HERE/embed-server.log"

BIN="$HOME/桌面/llama.cpp/build/bin/llama-server"
MODEL="$HOME/models/Qwen/Qwen3-Embedding-0.6B-GGUF/Qwen3-Embedding-0.6B-Q8_0.gguf"   # 2026-10-09 LM Studio 卸载, 模型搬到 ~/models

# 端口只在 .env 里定义一处, 这里从 EMBEDDING_BASE_URL 解析
EMBED_URL=$(grep -E '^EMBEDDING_BASE_URL=' "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2-)
PORT=$(printf '%s' "$EMBED_URL" | sed -E 's#.*:([0-9]+).*#\1#')
case "$PORT" in ''|*[!0-9]*) echo "从 .env 解析端口失败: '$EMBED_URL'" >&2; exit 1 ;; esac

# ★ 从端口反查 pid, 不用 pgrep -f: 后者会匹配到调用者自己的命令行
# (实测 2026-10-08: 手工执行 start 时它说"已在跑: PID xxx", 而服务早停了 = 匹到自己)
pid_of() { ss -ltnp 2>/dev/null | grep ":$PORT " | grep -oP 'pid=\K[0-9]+' | head -1; }

start() {
  if [ -n "$(pid_of)" ]; then echo "已在跑: PID $(pid_of)"; return 0; fi
  mkdir -p "$(dirname "$LOG")"
  # -ngl 99 = 全量上 GPU (约 2.9G 显存, 比 CPU 快数倍); 想省显存改回 -ngl 0
  nohup "$BIN" -m "$MODEL" --embedding --pooling last \
    --port "$PORT" --host 127.0.0.1 \
    -c 8192 -b 2048 -ub 2048 -ngl 99 \
    > "$LOG" 2>&1 &
  echo "启动中, PID $!"
  for i in $(seq 1 60); do
    curl -s --noproxy '*' --max-time 2 "http://127.0.0.1:$PORT/health" 2>/dev/null | grep -q '"ok"' \
      && { echo "就绪, 用时 ${i}s"; return 0; }
    sleep 1
  done
  echo "60s 没起来, 看日志: $LOG"; return 1
}

stop() {
  local pids; pids=$(pid_of)
  if [ -z "$pids" ]; then echo "没在跑"; return 0; fi
  for p in $pids; do kill "$p" 2>/dev/null; done
  sleep 2
  for p in $(pid_of); do kill -9 "$p" 2>/dev/null; done
  echo "已停"
}

status() {
  local pids; pids=$(pid_of)
  if [ -z "$pids" ]; then echo "没在跑"; return 1; fi
  echo "PID: $pids"
  curl -s --noproxy '*' --max-time 3 "http://127.0.0.1:$PORT/v1/models" | head -c 300; echo
}

case "${1:-status}" in
  start)  start ;;
  stop)   stop ;;
  status) status ;;
  log)    tail -f "$LOG" ;;
  *)      echo "用法: $0 start|stop|status|log" ;;
esac
