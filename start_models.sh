#!/usr/bin/env bash
# collaplex_agent 要的两个本地模型服务 —— 都是 llama.cpp
#
#   主模型  qwen3-vl-8b            http://127.0.0.1:8790/v1
#   向量    qwen3-embedding-0.6b    http://127.0.0.1:8199/v1
#
# 用法: ./start_models.sh start | stop | status | log
#
# 备注:
#   · Qwen3-VL-8B-Q4_K_M 4.68G(比 GLM 5.74G 小 1G) —— 满层上卡 -ngl 99 实测 50.2 tok/s
#     (GLM 只能 -ngl 24, 层压 CPU, 10.3 tok/s; 换模型后 4.9 倍)
#   · ★ KV 必须量化成 q8_0: 16k 上下文的 f16 KV 要 2.4G, 加上权重就超 8G(实测 -ngl 99 不带
#     --cache-type 会 "failed to create context") —— 量化后显存 7501/8151 MiB, 刚好站住
#   · --alias qwen3-vl-8b 让 llama.cpp 报这个名字, 跟 .env 的 OPENAI_MODEL 对得上
#   · 换回 GLM: CHAT_MODEL / -ngl / --cache-type / --alias 四处改回去(glm 用 -ngl 24, 不要 KV 量化)
#   · 服务只在这个脚本里管; 想手动起也行, .env 指向 8790 就够
set -u

HERE=$(cd "$(dirname "$0")" && pwd)
# ★ llama.cpp 已经搬进项目里了(vendor/), 不再依赖桌面那份 —— 换机器/删了老目录也照跑。
#   (搬的时候把 RUNPATH 用 patchelf 改成了 $ORIGIN, 所以 .so 跟着自己走)
LLAMA="$HERE/vendor/llama.cpp/build/bin/llama-server"
# ★ 2026-10-09: LM Studio 卸载, 模型搬到 ~/models(原来是 ~/.lmstudio/models 软链到 /mnt/data/lmstudio)。
#   目录结构照旧是 <发布者>/<模型>/, 所以下面三条路径不用改。
# 模型目录: 默认跟老板这台机一致; 换机器 / 做镜像用 COLLAPLEX_MODELS 指到别处。
# ★ 这里为什么自己去配置里捞一下: 应用只在"用到模型"的核心模块里 load_dotenv,
#   而「模型 start」这条路径(cli → web/start.py 管模型 → 转发给本脚本)不经过那些模块,
#   子进程里就没有这个变量 —— 于是镜像里会去 /home/lou/models 找模型, 找不到起不来。
#   只取这一个键(不 source 整个文件), 免得把库口令之类的带进 shell。
if [ -z "${COLLAPLEX_MODELS:-}" ]; then
    for cfg in /etc/collaplex-agent-os/env "$HERE/.env"; do
        [ -f "$cfg" ] || continue
        val=$(sed -n 's/^COLLAPLEX_MODELS=//p' "$cfg" | head -1)
        [ -n "$val" ] && { COLLAPLEX_MODELS="$val"; export COLLAPLEX_MODELS; break; }
    done
fi
MODELS="${COLLAPLEX_MODELS:-/home/lou/models}"
LOGS="$HERE/logs"

CHAT_MODEL="$MODELS/lmstudio-community/Qwen3-VL-8B-Instruct-GGUF/Qwen3-VL-8B-Instruct-Q4_K_M.gguf"
# ★ 看图必须带视觉塔(mmproj): 不带它主模型只认文字, 视觉请求一律回
#   "image input is not supported" —— 那样"本地兜底"就是条假兜底。
CHAT_MMPROJ="$MODELS/lmstudio-community/Qwen3-VL-8B-Instruct-GGUF/mmproj-Qwen3-VL-8B-Instruct-F16.gguf"
EMBED_MODEL="$MODELS/Qwen/Qwen3-Embedding-0.6B-GGUF/Qwen3-Embedding-0.6B-Q8_0.gguf"

CHAT_PORT=8790
EMBED_PORT=8199

# 按"模型文件路径"精确点名, 绝不用 llama-server 这种宽匹配 —— 那会把另一个服务一起杀掉
pids_of() {
  local want=$1 pid line
  for pid in $(ls /proc | grep -E '^[0-9]+$'); do
    line=$(cat "/proc/$pid/cmdline" 2>/dev/null | tr '\0' ' ')
    case "$line" in *llama-server*"$want"*) echo "$pid" ;; esac
  done
}

alive() { curl -s -o /dev/null --noproxy '*' --max-time 2 "http://127.0.0.1:$1/health"; }

START_ENV=""    # 可选: 给下面那条 nohup 附环境变量(留空=不加)

start_one() {   # 名字 端口 日志 启动参数...
  local name=$1 port=$2 log=$3
  shift 3
  if alive "$port"; then
    echo "  $name  —— 已经在跑 (:$port)"
    return
  fi
  # ★ setsid: 让模型自己当会话头, 彻底脱开"拉起它的那个 shell / 会话"。
  #   不加的话进程组跟着父 shell 走 —— 那边一被回收(工具跑完清理它的进程组、
  #   或者谁 kill 了同组的别的进程), 模型就被顺手带走。症状极难认:
  #   两个模型在几秒内一起"干净退出", 而 dmesg / oomd / journal 全都没有记录,
  #   因为根本没 OOM, 就是收到了 SIGTERM。
  setsid nohup env $START_ENV "$LLAMA" "$@" > "$log" 2>&1 < /dev/null &
  for _ in $(seq 1 120); do
    if alive "$port"; then
      echo "  $name  —— 起来了 (:$port)"
      return
    fi
    sleep 1
  done
  echo "  $name  —— 起不来, 看 $log"
}

start() {
  mkdir -p "$LOGS"
  echo "起本地模型:"
  # ★ 视觉塔(--mmproj)必须带: 不带它主模型只认文字, 视觉请求一律回
  #   "image input is not supported" —— 那样"本地兜底"就是条假兜底。
  # ★ 而且必须 --no-mmproj-offload: 权重+KV 已占 7271/8151 MiB, 只剩 ~880M,
  #   塞不下 1.16G 的 F16 视觉塔(往显存放会 failed to create context)。放 CPU/RAM
  #   里算 —— 看图是偶发一次, 慢点无妨。
  start_one "主模型 qwen3-vl-8b" "$CHAT_PORT" "$LOGS/chat.log" \
    -m "$CHAT_MODEL" --mmproj "$CHAT_MMPROJ" --no-mmproj-offload \
    -ngl 99 --cache-type-k q8_0 --cache-type-v q8_0 -fa on --jinja \
    -c 32768 --alias qwen3-vl-8b \
    --port "$CHAT_PORT" --host 127.0.0.1
  # ★ 嵌入服务本身 -ngl 0(纯 CPU 算), 但它照样会开 CUDA 上下文占 ~1.6G 显存 ——
  #   显存要留给主模型的上下文窗口(预算按窗口算, 窗口小=记忆名额为 0)。
  #   CUDA_VISIBLE_DEVICES= 让它连显卡都看不见。
  # ★ -b/-ub 必须小：嵌入跑在 CPU 上(-ngl 0)，-ub 2048 会让 CPU 侧的计算缓冲
  #   撑到 ~10G RSS（实测 9.97G，挤得整机只剩 1G 可用、逼到 oomd 边缘）。嵌入请求
  #   本来就很短，512 足够。
  # ★ 注释**不能**插在续行符 \ 后面 —— Bash 只认"\ 紧跟换行"，插了注释这条命令
  #   就被截断，start_one 收不到参数，会起一个 argv 空的 llama-server 空壳（踩过）。
  START_ENV="CUDA_VISIBLE_DEVICES=" start_one "向量 qwen3-embedding" "$EMBED_PORT" "$LOGS/embed.log" \
    -m "$EMBED_MODEL" --embedding --pooling last -c 8192 -b 512 -ub 512 -ngl 0 \
    --port "$EMBED_PORT" --host 127.0.0.1
  echo
  echo "跑吧: .venv/bin/python main.py"
}

stop() {
  local pid found
  found="$(pids_of "$CHAT_MODEL") $(pids_of "$EMBED_MODEL")"
  if [ -z "$(echo "$found" | tr -d ' ')" ]; then
    echo "  没有在跑的服务"
    return
  fi
  for pid in $found; do
    echo "  停 $pid"
    kill "$pid" 2>/dev/null
  done
  sleep 3
  echo "  还剩: $(pids_of "$CHAT_MODEL") $(pids_of "$EMBED_MODEL")"
}

status() {
  printf '  主模型 :%s  ' "$CHAT_PORT"
  if alive "$CHAT_PORT"; then echo "通"; else echo "不通"; fi
  printf '  向量   :%s  ' "$EMBED_PORT"
  if alive "$EMBED_PORT"; then echo "通"; else echo "不通"; fi
}

case "${1:-status}" in
  start)  start ;;
  stop)   stop ;;
  status) status ;;
  log)    tail -f "$LOGS/chat.log" ;;
  *)      echo "用法: $0 start | stop | status | log" ;;
esac
