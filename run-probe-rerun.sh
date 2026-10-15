#!/usr/bin/env bash
# 补跑两条没跑完的探针（2026-10-13 立项、10-14 22:2x 被 kill，退出码 143）
#
#   ① tests/judge_readback_probe.py     —— judge 出口形态：json vs 读回 × mimo/本地8B × 28 题
#   ② skill/linux/tests/left_chain_probe.py —— 左链路由（json 模式，现状）
#   ③ 同上（读回 模式）—— 必须真改 config，跑完改回
#
# ★ config/sub_agent.json 的 skill_retrieval.judge_输出 中途会切成「读回」，
#   无论成功失败都在退出时改回「json」（trap EXIT）—— 生产行为不留尾巴。
# ★ 两条探针都不写库、不需要 PG，所以不用 sudo 口令。
#
# 跑法（脱离会话）:  setsid nohup bash run-probe-rerun.sh >/dev/null 2>&1 < /dev/null &
# 看进度:            tail -f logs/探针补跑-*.log
# 停:                pkill -f run-probe-rerun.sh   （★ 但别用模式匹配杀自己那条命令行）

set -u
cd /home/lou/桌面/collaplex_agent || exit 1

STAMP=$(date +%Y%m%d-%H%M%S)
LOG="logs/探针补跑-$STAMP.log"
CFG="config/sub_agent.json"
BAK="logs/sub_agent.json.补跑前.$STAMP"

log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

改模式() {
  python3 - "$1" <<'PY'
import json, pathlib, sys
p = pathlib.Path('config/sub_agent.json')
d = json.loads(p.read_text(encoding='utf-8'))
d['skill_retrieval']['judge_输出'] = sys.argv[1]
p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(f"    judge_输出 -> {sys.argv[1]}")
PY
}

restore() {
  if [ -f "$BAK" ]; then
    cp -a "$BAK" "$CFG"
    log "★ 退出兜底：config/sub_agent.json 已从备份还原（judge_输出 = json）"
  fi
}
trap restore EXIT

cp -a "$CFG" "$BAK"
log "=== 探针补跑开始 ==="
log "配置备份: $BAK · 日志: $LOG"
log "现值: $(python3 -c "import json;print(json.load(open('config/sub_agent.json'))['skill_retrieval']['judge_输出'])")"

log "〔①〕judge 出口形态（json 与 读回 两模式 × mimo/本地8B × 28 题，走真件 judge_skill）—— 开始"
timeout 14400 .venv/bin/python tests/judge_readback_probe.py >> "$LOG" 2>&1
log "〔①〕结束，退出码 $?"

log "〔②〕左链路由 · json 模式 —— 开始"
timeout 7200 .venv/bin/python skill/linux/tests/left_chain_probe.py >> "$LOG" 2>&1
log "〔②〕结束，退出码 $?"

log "〔③〕左链路由 · 读回 模式（真改 config）—— 开始"
改模式 读回 >> "$LOG" 2>&1
timeout 7200 .venv/bin/python skill/linux/tests/left_chain_probe.py >> "$LOG" 2>&1
log "〔③〕结束，退出码 $?"
改模式 json >> "$LOG" 2>&1

log "=== 全部结束 ==="
echo "--- 关键结论行 ---" >> "$LOG"
grep -nE '^（|汇总|路由对的|判对|broken|=== ' "$LOG" | tail -30 >> "$LOG" 2>/dev/null
tail -40 "$LOG"
