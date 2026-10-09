#!/bin/bash
set -euo pipefail

WRAPPER="$1"
OUT="$2"
ANALYSIS_DATE="$3"
FORCE="${4:-false}"
# 完成標記只表示這份報告由本 runner 寫完；沒有它的報告（被中斷或手寫）不重用。
MARKER="$OUT.complete"

mkdir -p "$(dirname "$OUT")"

if [ "$FORCE" != "true" ] && [ -s "$OUT" ] && [ -s "$MARKER" ]; then
  exit 0
fi

BACKUP="$OUT.previous"
rm -f "$MARKER"
if [ -e "$OUT" ]; then
  rm -f "$BACKUP"
  mv "$OUT" "$BACKUP"
fi
if ! LOCAL_ANALYSIS_DATE="$ANALYSIS_DATE" bash "$WRAPPER"; then
  rm -f "$OUT"
  exit 1
fi
if [ ! -s "$OUT" ]; then
  rm -f "$OUT"
  exit 1
fi
printf '%s\n' "$ANALYSIS_DATE" > "$MARKER.tmp"
mv "$MARKER.tmp" "$MARKER"
rm -f "$BACKUP"
