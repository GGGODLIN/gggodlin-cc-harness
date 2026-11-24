#!/bin/bash
# tool-reliability-weekly.sh — /daily-local workflow 的 tool-reliability channel（2026-08-01 建）。
#
# kind: 'shell'——**刻意零 LLM**。這支只做確定性統計（tool_use_id 配對 + 週聚合 + 週對週差），
# 沒有任何需要判斷的環節。同領域的 skill-collision / skill-trigger-health 也是這個路線。
#
# 每次執行都全量重算（session jsonl 會持續追加，增量會雙重計數）；輸出蓋寫同一個 jsonl。

set -euo pipefail
S="$(cd "$(dirname "$0")" && pwd)"

DATE="${LOCAL_ANALYSIS_DATE:-$(date +%Y-%m-%d)}"
OUT_DIR="${TOOL_RELIABILITY_OUT_DIR:-~/code/social-info/reports/local-analysis}"
OUT="${TOOL_RELIABILITY_OUT:-$OUT_DIR/$DATE-tool-reliability.md}"
mkdir -p "$(dirname "$OUT")"

python3 "$S/tool-reliability-extract.py" >/dev/null

TMP="$(mktemp "$(dirname "$OUT")/.tool-reliability.XXXXXX")"
trap 'rm -f "$TMP"' EXIT
python3 "$S/tool-reliability-extract.py" --report > "$TMP"
mv "$TMP" "$OUT"
trap - EXIT
