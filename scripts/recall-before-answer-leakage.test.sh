#!/bin/bash
# Fixture：C077 兩週資料、映射識別、30 天窗、命中與漏抓比例。
set -uo pipefail

SCRIPT="$(cd "$(dirname "$0")" && pwd)/recall-before-answer-leakage.py"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
LEDGER="$TMP/ledger.jsonl"
MAPPING="$TMP/mapping.json"

python3 - "$LEDGER" "$MAPPING" <<'PY'
import json
import sys
from pathlib import Path

ledger = [
    {"date": "2026-08-20", "kind": "rule_violation", "rule": "使用者說「我記得／之前有」時先翻紀錄再回答", "quote": "上次的決定是什麼？"},
    {"date": "2026-08-21", "kind": "rule_violation", "rule": "使用者說「我記得／之前有」時先翻紀錄再回答", "quote": "請確認這件事"},
    {"date": "2026-08-22", "kind": "rule_violation", "rule_id": "C077", "quote": "之前有討論過"},
    {"date": "2026-08-23", "kind": "rule_violation", "rule_ids": ["C077"], "quote": "請重新處理"},
    {"date": "2026-08-20", "kind": "rule_violation", "rule_id": "C077", "quote": "這是你自創的嗎"},
    {"date": "2026-08-21", "kind": "rule_violation", "rule_id": "C077", "quote": "先確認目前機制"},
    {"date": "2026-08-22", "kind": "rule_violation", "rule_id": "C077", "quote": "看一下現在的紀錄"},
    {"date": "2026-08-23", "kind": "rule_violation", "rule_id": "C077", "quote": "我不是有 token 嗎"},
    {"date": "2026-08-10", "kind": "rule_violation", "rule_id": "C077", "quote": "我記得這件事"},
    {"date": "2026-07-01", "kind": "rule_violation", "rule_id": "C077", "quote": "沒有命中"},
    {"date": "2026-08-23", "kind": "new_rule_candidate", "rule_id": "C077", "quote": "上次不算糾正列"},
    {"date": "2026-08-23", "kind": "rule_violation", "rule_id": "C041", "quote": "訪談模式"},
]
mapping = {"mappings": [{"rule": "使用者說「我記得／之前有」時先翻紀錄再回答", "ids": ["C077"], "confidence": "high"}]}
Path(sys.argv[1]).write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in ledger) + "\n", encoding="utf-8")
Path(sys.argv[2]).write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
PY

OUTPUT=$(python3 "$SCRIPT" "$LEDGER" --mapping "$MAPPING" --since 2026-08-01 --until 2026-08-26)
if printf '%s' "$OUTPUT" | jq -e '
  .rule_id == "C077" and
  .total.numerator == 2 and
  .total.denominator == 9 and
  .total.rate == (2 / 9) and
  ([.weeks[] | select(.week_start == "2026-08-17")][0].numerator == 2) and
  ([.weeks[] | select(.week_start == "2026-08-17")][0].denominator == 8)
' >/dev/null; then
  echo 'PASS C077 30 天窗與週漏抓率'
else
  echo "FAIL C077 30 天窗與週漏抓率 output=$OUTPUT"
  exit 1
fi

WEEK_OUTPUT=$(python3 "$SCRIPT" "$LEDGER" --mapping "$MAPPING" --since 2026-08-01 --until 2026-08-26 --week 2026-08-17)
if printf '%s' "$WEEK_OUTPUT" | jq -e '.selected_week.week_start == "2026-08-17" and .selected_week.numerator == 2 and .selected_week.denominator == 8 and .selected_week.rate == 0.25' >/dev/null; then
  echo 'PASS 指定週輸出含分子分母'
else
  echo "FAIL 指定週輸出 output=$WEEK_OUTPUT"
  exit 1
fi

printf '%s\n' 'PASS=2 FAIL=0'
