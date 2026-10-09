#!/bin/bash
# 2026-08-18 拍板：harbor-3arm / oldco-shop 兩 db schema v65 > binary v53（bd 1.2.2＝上游最新）——等 bd 新 release 再解；
# oldco-shop 接受不修（離職交接）。掃描失敗已改列報告不炸 channel（beads-aging.py failures 段）。v65 來源未定論。
cd /
set -euo pipefail

PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:~/.local/bin:/opt/homebrew/bin"
export PATH

REPO_DIR="$HOME/code/social-info"
OUT_DIR="$REPO_DIR/reports/local-analysis"
LOG_DIR="$REPO_DIR/logs"

mkdir -p "$OUT_DIR" "$LOG_DIR"
DATE="${LOCAL_ANALYSIS_DATE:-$(date +%Y-%m-%d)}"
OUT="${BEADS_AGING_OUT:-$OUT_DIR/$DATE-beads-aging.md}"
LOG="${BEADS_AGING_LOG:-$LOG_DIR/local-analysis-beads-aging-$DATE.log}"

{
  printf '=== beads-aging started: %s ===\n' "$(date)"
  python3 "$REPO_DIR/scripts/local-analysis/beads-aging.py" --date "$DATE" --out "$OUT"
} >> "$LOG" 2>&1
