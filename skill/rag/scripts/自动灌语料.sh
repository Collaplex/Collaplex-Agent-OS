#!/usr/bin/env bash
# 热库自动进管线: Hermes 会话 -> 语料 md -> 二层(向量)。走完之后 refine(cron 每分钟)自己捡走清洗。
#
# ★ 为什么要有这一步: 没有它, 新对话只堆在 ~/.hermes/state.db 里, 清洗管线永远看不到
#   (2026-10-11 老板: "热库加上我们这些要清洗的")。
# ★ 为什么必须增量: 全量 import 会把**已经洗过、语料原文已被第③步删掉**的会话重新写回语料 ->
#   再嵌向量 -> 再清洗 = 死循环(烧算力, 还把旧内容当新内容反复往下沉)。
#   增量靠 state/import-断点.json: 只收"断点之后有新消息、且已静默 --quiet-min 分钟"的会话。
# ★ 变量名必须 ASCII: bash 的标识符只认 [A-Za-z0-9_] —— 中文变量名会被当成命令去执行
#   (报 "xxx: 没有那个文件或目录")。参数名同理, cron 环境 locale 是 POSIX。
set -u
cd /home/lou/桌面/collaplex_agent

# ★ 停机闸门: web 上「关模型/全部」会落 state/停机 —— 机器停机了就别灌(向量服务也没了)。
if [ -e state/停机 ]; then
  echo "⏸ 停机闸门在(state/停机) —— 机器停机中, 这轮不灌。"
  exit 0
fi

echo ""
echo "=== 自动灌语料 $(date '+%F %T') ==="

./.venv/bin/python skill/rag/scripts/import_hermes_hist.py \
  skill/rag/corpus/hermes-history --incremental --sessions 0 --quiet-min "${QUIET_MIN:-30}"
rc=$?
if [ "$rc" != "0" ]; then
  echo "import 退出码 $rc —— 这轮不嵌了, 下轮再来"
  exit "$rc"
fi

LIST=state/import-最新.txt
if [ ! -s "$LIST" ]; then
  echo "没有待嵌的会话, 不用嵌"
  exit 0
fi

TOTAL=$(wc -l < "$LIST")
echo "待嵌 $TOTAL 个会话文件, 开始嵌向量..."

# embed.py 是"全部算完才一次性落库"的趟制 —— 一批别超 20 个文件, 断了只丢当前这批。
i=0
allok=1
batch=()
flush() {
  [ "${#batch[@]}" -eq 0 ] && return 0
  i=$((i + 1))
  echo "--- 第 $i 批 (${#batch[@]} 个 / 共 $TOTAL) ---"
  ./.venv/bin/python -u skill/rag/scripts/embed.py "${batch[@]}" || allok=0
  batch=()
}
while IFS= read -r one; do
  batch+=("$one")
  if [ "${#batch[@]}" -eq 20 ]; then flush; fi
done < "$LIST"
flush

if [ "$allok" = "1" ]; then
  : > "$LIST"          # ★ 全嵌成了才清清单; 有失败就留着下轮重来(embed 是 accumulate, 重复嵌无害)
  echo "=== 完 $(date '+%T')  (清单已清空) ==="
else
  echo "=== 完 $(date '+%T')  ★ 有批次失败, 清单留着, 下轮重来 ==="
  exit 1
fi
