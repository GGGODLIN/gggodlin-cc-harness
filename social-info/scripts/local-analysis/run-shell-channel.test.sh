#!/bin/bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUNNER="$SCRIPT_DIR/run-shell-channel.sh"
FIX="$(mktemp -d)"
trap 'rc=$?; rm -rf "$FIX"; exit $rc' EXIT
WRAPPER="$FIX/wrapper.sh"
OUT="$FIX/report.md"
COUNT="$FIX/count"
DATE_OUT="$FIX/date"

cat > "$WRAPPER" <<'EOF'
#!/bin/bash
n=0
[ ! -f "$COUNT_FILE" ] || n=$(<"$COUNT_FILE")
n=$((n + 1))
printf '%s\n' "$n" > "$COUNT_FILE"
printf '%s\n' "$LOCAL_ANALYSIS_DATE" > "$DATE_FILE"
if [ "${SKIP_WRITE:-false}" = "true" ]; then
  exit 0
elif [ "${WRITE_EMPTY:-false}" = "true" ]; then
  : > "$REPORT_FILE"
elif [ "${WRITE_PARTIAL_THEN_FAIL:-false}" = "true" ]; then
  printf 'partial\n' > "$REPORT_FILE"
  exit 1
else
  printf '# report %s\n' "$n" > "$REPORT_FILE"
fi
EOF
chmod +x "$WRAPPER"

pass=0
fail=0
check() {
  name="$1"
  shift
  if "$@"; then
    printf 'PASS: %s\n' "$name"
    pass=$((pass + 1))
  else
    printf 'FAIL: %s\n' "$name"
    fail=$((fail + 1))
  fi
}

env COUNT_FILE="$COUNT" DATE_FILE="$DATE_OUT" REPORT_FILE="$OUT" bash "$RUNNER" "$WRAPPER" "$OUT" 2026-07-29 false
check "首次執行 wrapper" test "$(<"$COUNT")" = 1
check "傳入指定分析日期" test "$(<"$DATE_OUT")" = 2026-07-29
check "產生完成標記" test -s "$OUT.complete"

env COUNT_FILE="$COUNT" DATE_FILE="$DATE_OUT" REPORT_FILE="$OUT" bash "$RUNNER" "$WRAPPER" "$OUT" 2026-07-29 false
check "完整報告可重用" test "$(<"$COUNT")" = 1

rm -f "$OUT.complete"
env COUNT_FILE="$COUNT" DATE_FILE="$DATE_OUT" REPORT_FILE="$OUT" bash "$RUNNER" "$WRAPPER" "$OUT" 2026-07-29 false
check "沒有完成標記的報告會重跑" test "$(<"$COUNT")" = 2

rm -f "$OUT.complete"
printf 'legacy marker\n' > "$OUT.complete.sha256"
env COUNT_FILE="$COUNT" DATE_FILE="$DATE_OUT" REPORT_FILE="$OUT" bash "$RUNNER" "$WRAPPER" "$OUT" 2026-07-29 false
check "舊格式完成標記被忽略並重跑" test "$(<"$COUNT")" = 3
rm -f "$OUT.complete.sha256"

env COUNT_FILE="$COUNT" DATE_FILE="$DATE_OUT" REPORT_FILE="$OUT" bash "$RUNNER" "$WRAPPER" "$OUT" 2026-07-29 true
check "force 會重跑" test "$(<"$COUNT")" = 4

previous="$(<"$OUT")"
if env SKIP_WRITE=true COUNT_FILE="$COUNT" DATE_FILE="$DATE_OUT" REPORT_FILE="$OUT" bash "$RUNNER" "$WRAPPER" "$OUT" 2026-07-29 true 2>/dev/null; then
  stale_failed=false
else
  stale_failed=true
fi
check "wrapper 未寫新報告時拒絕舊檔" test "$stale_failed" = true
check "失敗後 canonical 報告不存在" test ! -e "$OUT"
check "失敗後舊報告移到 previous" test "$(<"$OUT.previous")" = "$previous"
check "未寫新報告不留完成標記" test ! -e "$OUT.complete"

if env WRITE_PARTIAL_THEN_FAIL=true COUNT_FILE="$COUNT" DATE_FILE="$DATE_OUT" REPORT_FILE="$OUT" bash "$RUNNER" "$WRAPPER" "$OUT" 2026-07-29 true 2>/dev/null; then
  partial_failed=false
else
  partial_failed=true
fi
check "wrapper 寫部分報告後失敗會回傳失敗" test "$partial_failed" = true
check "部分報告失敗後 canonical 不存在" test ! -e "$OUT"
check "部分報告失敗後保留 previous" test "$(<"$OUT.previous")" = "$previous"

if env WRITE_EMPTY=true COUNT_FILE="$COUNT" DATE_FILE="$DATE_OUT" REPORT_FILE="$OUT" bash "$RUNNER" "$WRAPPER" "$OUT" 2026-07-29 true 2>/dev/null; then
  empty_failed=false
else
  empty_failed=true
fi
check "空報告拒絕成功" test "$empty_failed" = true
check "空報告不留完成標記" test ! -e "$OUT.complete"

printf '%s\n' '----'
printf '%s PASS / %s FAIL\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
