#!/usr/bin/env bash
# 探针补跑 · 只跑云端（老板 2026-10-15 定：本地 8B 那两臂 80~214 秒/发，跳掉）
#
#   ① judge 出口形态 —— 只跑「读回 × mimo」（json×mimo 已验 28/28；json 与 读回 的本地臂跳过）
#   ② 左链路由 · json 模式（云端，从没跑过）
#   ③ 左链路由 · 读回 模式（云端，须真改 config）
#
# ★ config/sub_agent.json 的 skill_retrieval.judge_输出 在 ③ 步临时切「读回」，
#   trap EXIT/SIGTERM/SIGINT 三重兜底改回 json —— 生产行为不留尾巴。
# ★ 两条探针都不写库、不需要 PG。
#
# 看进度: tail -f logs/探针补跑-云端-*.log

set -u
cd /home/lou/桌面/collaplex_agent || exit 1

STAMP=$(date +%Y%m%d-%H%M%S)
LOG="logs/探针补跑-云端-$STAMP.log"
CFG="config/sub_agent.json"
BAK="logs/sub_agent.json.云端补跑前.$STAMP"

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
    log "★ 退出兜底：config/sub_agent.json 还原为 json"
  fi
}
trap restore EXIT SIGTERM SIGINT SIGHUP

cp -a "$CFG" "$BAK"
log "=== 探针补跑·云端 开始 ==="
log "备份: $BAK · 日志: $LOG"

log "〔①〕judge 出口形态 · 读回 × mimo（28 题，走真件 judge_skill）—— 开始"
PROBE_MODES=读回 PROBE_MODELS=mimo PROBE_VERBOSE=1 \
  timeout 3600 .venv/bin/python tests/judge_readback_probe.py >> "$LOG" 2>&1
log "〔①〕结束，退出码 $?"

log "〔②〕左链路由 · json 模式（云端）—— 开始"
timeout 3600 .venv/bin/python skill/linux/tests/left_chain_probe.py >> "$LOG" 2>&1
log "〔②〕结束，退出码 $?"

log "〔③〕左链路由 · 读回 模式（云端，真改 config）—— 开始"
改模式 读回 >> "$LOG" 2>&1
timeout 3600 .venv/bin/python skill/linux/tests/left_chain_probe.py >> "$LOG" 2>&1
log "〔③〕结束，退出码 $?"
改模式 json >> "$LOG" 2>&1

log "=== 全部结束 ==="
grep -nE '汇总|路由对的|判对|broken|=====' "$LOG" | tail -20 >> "$LOG" 2>/dev/null
