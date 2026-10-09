#!/bin/bash
# recurring-errors-envclass.sh — 錯誤簽名的確定性環境／行為分流（2026-08-01 建，HKUDS/OpenSpace 抽件 1）
#
# 為什麼要這層：recurring-errors 的六類種子標籤全是 agent 行為類（context_degradation /
# tool_confusion / instruction_drift / goal_abandonment / circular_reasoning /
# premature_conclusion），沒有一類容得下「機器或網路當下壞掉」。環境類錯誤被硬塞進行為
# 分類，就會長出「建個防線防止再犯」這種對它們沒意義的建議——流程沒錯，是環境沒醒。
# 所以在 LLM 語意聚類**之前**用寫死的詞表先分流，環境類走自己的節、不進聚類、不出防線建議。
#
# 詞表紀律（兩個都是實資料撞出來的，改詞表前先看）：
#   1. 錯誤碼用顯式邊界 (^|[^a-z])xxx([^a-z]|$)——裸寫 enotfound 會誤命中
#      fil-enotfound-error / modul-enotfound-error 這兩個真實簽名（它們是 agent 找錯路徑／
#      漏裝套件，不是環境）。
#   2. timeout 一律詞組化（timed out / timeout of / configured timeout…），不收裸 token——
#      裸 timeout 會誤命中 python traceback 的程式碼行 `return opener.open(url, data, timeout)`。
# 寧可漏（環境類掉回行為流程、頂多多一條無用建議）不可誤（把 agent 自己的錯判成「不是我的問題」）。
#
# 用法：
#   bash recurring-errors-envclass.sh env       # 環境類候選（全量，不與雜訊競爭 top-N）
#   bash recurring-errors-envclass.sh behavior  # 行為類候選（供 LLM 聚類）
#   bash recurring-errors-envclass.sh stats     # 兩類計數
#   ENVCLASS_LEDGER=<path> 可覆寫 ledger（測試用）
#
# 測試：bash recurring-errors-envclass.test.sh（改詞表後必跑）

set -uo pipefail

LEDGER="${ENVCLASS_LEDGER:-$HOME/code/social-info/reports/local-analysis/recurring-errors-ledger.jsonl}"
MIN_N=${ENVCLASS_MIN_N:-3}
MIN_SESSIONS=${ENVCLASS_MIN_SESSIONS:-2}

B='(^|[^a-z])'
A='([^a-z]|$)'

ENV_RE="timed out|timeout of|timeout exceeded|exceeded.*timeout|configured timeout|protocoltimeout|not found: timeout"
ENV_RE="$ENV_RE|cdp sendcommand|renderer may be frozen|renderer may be unresponsive"
ENV_RE="$ENV_RE|${B}econnrefused${A}|${B}econnreset${A}|${B}enotfound${A}|${B}eaddrinuse${A}|${B}etimedout${A}|${B}epipe${A}|${B}ehostunreach${A}"
ENV_RE="$ENV_RE|broken pipe|socket hang up|socket connection was closed|connection refused|connection reset by peer|network is unreachable"
ENV_RE="$ENV_RE|permission denied \(publickey\)|host key verification failed"
ENV_RE="$ENV_RE|could not resolve host|temporary failure in name resolution|name or service not known"
ENV_RE="$ENV_RE|certificate verify failed|ssl certificate problem|unable to get local issuer"
ENV_RE="$ENV_RE|rate limit|too many requests|status code 429|429 too many"
ENV_RE="$ENV_RE|502 bad gateway|503 service unavailable|504 gateway|bad gateway|service unavailable"
ENV_RE="$ENV_RE|no space left on device|disk full|diskusage|quota exceeded on device"
ENV_RE="$ENV_RE|out of memory|oom-kill|cannot allocate memory"

candidates() {
  jq -rs --argjson n "$MIN_N" --argjson s "$MIN_SESSIONS" \
    'group_by(.sig)
     | map({sig: .[0].sig, n: length, sessions: (map(.session)|unique|length), last: (map(.date)|max)})
     | sort_by(-.n)
     | .[]
     | select(.n >= $n and .sessions >= $s)
     | "\(.n)x | \(.sessions) sessions | \(.last) | \(.sig)"' \
    "$LEDGER" 2>/dev/null
}

case "${1:-stats}" in
  env)      candidates | grep -iE "$ENV_RE" ;;
  behavior) candidates | grep -ivE "$ENV_RE" ;;
  stats)
    all=$(candidates | grep -c . || true)
    env=$(candidates | grep -icE "$ENV_RE" || true)
    printf 'candidates=%s environment=%s behavior=%s\n' "$all" "$env" "$((all - env))"
    ;;
  *) echo "usage: $0 {env|behavior|stats}" >&2; exit 2 ;;
esac
