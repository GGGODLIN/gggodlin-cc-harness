#!/bin/bash
# skill-evidence-weekly.sh — /daily-local workflow 的 skill-evidence channel（2026-08-01 建）。
#
# kind: 'shell'——零 LLM，純確定性訊號偵測 + 使用量 join。
# 給 skill 退役判斷提供第二個軸（既有死庫存偵測只看 invoke 數）。
# 量的是「文件有沒有引用證據的痕跡」不是「固化當下有沒有驗證」，限制寫在 py 檔頭與報告開頭。

set -uo pipefail
S="$(cd "$(dirname "$0")" && pwd)"

DATE="${LOCAL_ANALYSIS_DATE:-$(date +%Y-%m-%d)}"
OUT="$HOME/code/social-info/reports/local-analysis/$DATE-skill-evidence.md"

python3 "$S/skill-evidence-audit.py" > "$OUT"
