#!/bin/bash
set -euo pipefail
DATE="${LOCAL_ANALYSIS_DATE:-$(date +%F)}"
OUT="$HOME/code/social-info/reports/local-analysis/${DATE}-skillevaluator.md"
export SKILLEVALUATOR_EMBEDDING_PREFLIGHT_TIMEOUT_SECONDS="${SKILLEVALUATOR_EMBEDDING_PREFLIGHT_TIMEOUT_SECONDS:-90}"
python3 ~/.claude/scripts/skillevaluator-trial.py weekly \
  --collection ~/.claude/skills \
  --date "$DATE" \
  --summary "$OUT" \
  --workers "${SKILLEVALUATOR_WEEKLY_WORKERS:-2}" >/dev/null
