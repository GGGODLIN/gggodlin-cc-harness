#!/bin/bash
# skill-changes-daily：local-analysis 每日 shell channel。
# 對上次執行以來改版過的 skill／command 跑 SkillEvaluator T1／T2 與 skill-up 回歸，
# 產出帶「建議檔位：高／中／低」的報告給 digest。無改版時輸出 __SILENT__。
# 邏輯在 scripts/skill-changes-daily.py；本檔只負責路徑約定。
set -euo pipefail
DATE="${LOCAL_ANALYSIS_DATE:-$(date +%F)}"
OUT="$HOME/code/social-info/reports/local-analysis/${DATE}-skill-changes.md"
python3 ~/.claude/scripts/skill-changes-daily.py --date "$DATE" --out "$OUT"
