#!/bin/bash
# failure-mode-daily：local-analysis 每日 shell channel。
# 讀探針表「案例登記」區，輸出近 30 天登記筆數、暫定門檻命中、無法解析的行；
# 無新登記時輸出 __SILENT__，並維護探針表檔首的 top-2 提醒行（並發安全）。
# 邏輯在 scripts/failure-mode-daily.py；本檔只負責路徑約定。
set -euo pipefail
DATE="${LOCAL_ANALYSIS_DATE:-$(date +%F)}"
OUT="$HOME/code/social-info/reports/local-analysis/${DATE}-failure-mode.md"
python3 ~/.claude/scripts/failure-mode-daily.py --date "$DATE" --out "$OUT"
