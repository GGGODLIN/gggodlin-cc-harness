#!/bin/bash
# skill-trigger-health channel wrapper（weekly-tue、shell channel、零 LLM）。
# 職責：只跑偵測腳本 skill-trigger-health.py 落報告；語意判讀（slash 是習慣還是 miss、
# 死庫存留/殺）歸 main session 排檔——三分架構分工，見 repo CLAUDE.md。
# 設計討論與拍板：2026-07-31 session（M3 衍生案）；trial entry 見 trials/active.md skill-trigger-health。
cd /
set -euo pipefail

PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:~/.local/bin:/opt/homebrew/bin"
export PATH

REPO_DIR="$HOME/code/social-info"
OUT_DIR="$REPO_DIR/reports/local-analysis"
LOG_DIR="$REPO_DIR/logs"

mkdir -p "$OUT_DIR" "$LOG_DIR"
DATE="${LOCAL_ANALYSIS_DATE:-$(date +%Y-%m-%d)}"
OUT="${SKILL_TRIGGER_OUT:-$OUT_DIR/$DATE-skill-trigger-health.md}"
LOG="${SKILL_TRIGGER_LOG:-$LOG_DIR/local-analysis-skill-trigger-$DATE.log}"

{
  echo "=== skill-trigger-health started: $(date) ==="
  python3 "$REPO_DIR/scripts/local-analysis/skill-trigger-health.py" --date "$DATE" --out "$OUT"
} >> "$LOG" 2>&1
