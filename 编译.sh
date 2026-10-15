#!/usr/bin/env bash
# 用 Nuitka 编 cli.py（standalone，★ 不含 skill）—— 长活，自己脱离 Hermes 会话
# 跑法：bash 编译.sh   （前台立刻返回，真正的编译在 setsid 里跑）
# ★ 变量名一律 ASCII：本机 bash 5.3.9 在这个 locale 下不认中文变量名（"根=x" 会当成命令）
set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"
LOG="$ROOT/logs/编译.log"
cd "$ROOT" || exit 1

RUNNING="$(pgrep -f 'nuitka.*cli\.py' | head -1)"
if [ -n "$RUNNING" ]; then
  echo "已经有一份在编（pid=$RUNNING），不重复起"
  exit 1
fi

mkdir -p "$ROOT/编译产物"
echo "=== $(date '+%F %T') 开编（standalone，不含 skill） ===" >> "$LOG"
setsid nohup "$ROOT/.venv/bin/python" -m nuitka \
  --standalone --follow-imports \
  --nofollow-import-to=skill \
  --include-package=numpy --include-package=psycopg --include-package=websocket \
  --include-package=openai --include-package=pydantic --include-package=anyio \
  --include-package=jiter --include-package=sniffio --include-package=h11 \
  --include-package=typing_extensions --include-package=dotenv \
  --output-dir="$ROOT/编译产物" --output-filename=collaplex-agent \
  "$ROOT/cli.py" >>"$LOG" 2>&1 &
echo "编译已起（pid=$!）· 日志：$LOG"
