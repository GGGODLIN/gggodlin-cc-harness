#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP="$(mktemp -d)"
trap 'rc=$?; rm -rf "$TMP"; exit $rc' EXIT
BASELINE="$TMP/baseline"
CURRENT="$TMP/current"
OUT="$TMP/out.md"
LOG="$TMP/run.log"

run_case() {
  SKILL_COLLISION_BASELINE="$BASELINE" \
  SKILL_COLLISION_CURRENT_INPUT="$CURRENT" \
  SKILL_COLLISION_OUT="$OUT" \
  SKILL_COLLISION_LOG="$LOG" \
  LOCAL_ANALYSIS_DATE="2026-07-29" \
  bash "$DIR/skill-collision-daily.sh"
}

printf 'alpha|beta|0.60\n' > "$BASELINE"
printf 'alpha|beta|0.61\n' > "$CURRENT"
run_case
grep -Fx '__SILENT__' "$OUT" >/dev/null
grep -Fx 'alpha|beta|0.61' "$BASELINE" >/dev/null

printf 'alpha|beta|0.74\n' > "$BASELINE"
printf 'alpha|beta|0.76\n' > "$CURRENT"
run_case
grep -F '## ⚠️ 相似度跨級' "$OUT" >/dev/null
grep -F 'overlap 74% → collision 76%' "$OUT" >/dev/null

printf 'alpha|beta|0.80\n' > "$BASELINE"
printf 'alpha|beta|0.70\n' > "$CURRENT"
run_case
grep -F 'collision 80% → overlap 70%' "$OUT" >/dev/null

printf 'alpha|beta|0.744900\n' > "$BASELINE"
printf 'alpha|beta|0.745100\n' > "$CURRENT"
run_case
grep -Fx '__SILENT__' "$OUT" >/dev/null

printf 'alpha|beta|0.80\n' > "$BASELINE"
: > "$CURRENT"
run_case
grep -F '## ✅ 已解除的 pair' "$OUT" >/dev/null
grep -F 'alpha ↔ beta' "$OUT" >/dev/null

printf '5/5 passed\n'
