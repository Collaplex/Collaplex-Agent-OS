#!/usr/bin/env bash
# 本地兜底 —— 云 API 卡住/断网时，用本地模型跑 agent os
#
# 背景（实测）：
#   主链是云 API（.env 里 OPENAI_BASE_URL=https://api.xiaomimimo.com/v1）。
#   云端会**间歇卡住**（学校网高峰 19-23 点尤甚）—— 但它的元数据端点又是好的
#   （实测 HTTP 200、首字节 0.13s），所以"卡"不是断了、而是长连接被掐：
#   命令行测不出来，用起来体感明显。
#   而实测证明：只换三个环境变量就能把整条链切到本地，**一行代码都不改**。
#
# 用法：
#   ./本地兜底.sh            起本地模型（没起的话）并进交互
#   ./本地兜底.sh --检查     只查本地模型 + agent 能不能跑，不进交互
set -euo pipefail
cd "$(dirname "$0")"

EP=http://127.0.0.1:8790/v1
MDL=qwen3-vl-8b

if curl -s -m 3 -o /dev/null "$EP/models"; then
    echo "本地模型在 ($EP)"
else
    echo "本地模型没起，拉起中…"
    ./start_models.sh start
fi

if [ "${1:-}" = "--检查" ]; then
    export OPENAI_BASE_URL="$EP" OPENAI_API_KEY=local OPENAI_MODEL="$MDL"
    .venv/bin/python - <<'PY'
import os
from openai import OpenAI
c = OpenAI(api_key="local", base_url=os.environ["OPENAI_BASE_URL"])
r = c.chat.completions.create(model=os.environ["OPENAI_MODEL"],
    messages=[{"role": "user", "content": "回一个字：好"}], max_tokens=8)
print("  本地模型答:", r.choices[0].message.content)
PY
    echo "✓ 本地兜底可用（云卡了就 ./本地兜底.sh）"
    exit 0
fi

echo "切本地跑 agent os（云 API 不参与）"
export OPENAI_BASE_URL="$EP" OPENAI_API_KEY=local OPENAI_MODEL="$MDL"
exec .venv/bin/python main.py "$@"
