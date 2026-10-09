#!/bin/bash
# distill-errors.sh — distill-weekly C 線的確定性前濾：把近 7 天 CC session jsonl
# 的失敗工具呼叫機械抽成一份 digest，LLM 只讀 digest 不翻 raw jsonl。
# 抽取引擎 = ~/.claude/scripts/extract-errors.py（vendored 自 EveryInc/compound-engineering，2026-07-11 抽件）
set -uo pipefail

REPO_DIR="$HOME/code/social-info"
OUT="$REPO_DIR/reports/local-analysis/distill-errors.txt"
EXTRACTOR="$HOME/.claude/scripts/extract-errors.py"

mkdir -p "$(dirname "$OUT")"
: > "$OUT"

total_sessions=0
total_errors=0

while IFS= read -r f; do
  out=$(python3 "$EXTRACTOR" < "$f" 2>/dev/null) || continue
  meta=$(printf '%s\n' "$out" | tail -1)
  n=$(printf '%s' "$meta" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("errors_found",0))' 2>/dev/null) || n=0
  [ "${n:-0}" -gt 0 ] || continue
  total_sessions=$((total_sessions + 1))
  total_errors=$((total_errors + n))
  {
    echo "=== session: $f (errors: $n)"
    printf '%s\n' "$out" | sed '$d'
    echo
  } >> "$OUT"
done < <(find "$HOME/.claude/projects" -name '*.jsonl' -mtime -7 -size +1k)

echo "digest → $OUT (sessions with errors: $total_sessions, total errors: $total_errors)"
