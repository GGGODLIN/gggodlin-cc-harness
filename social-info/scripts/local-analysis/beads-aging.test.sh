#!/bin/bash
set -uo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$DIR/beads-aging.py"
TMP=$(mktemp -d)
trap 'rc=$?; rm -rf "$TMP"; exit $rc' EXIT
ROOT="$TMP/root"
DATA="$TMP/data"
FAKE="$TMP/bd"
SLOW="$TMP/bd-slow"
ARGS_LOG="$TMP/args.log"
TARGET="$TMP/linked-target"
LINK_ROOT="$TMP/link-root"
mkdir -p "$ROOT/project-a/.beads" "$ROOT/project-b/.beads" "$ROOT/quiet/.beads" "$ROOT/malformed/.beads" "$ROOT/slow/.beads" "$TARGET/.beads" "$LINK_ROOT" "$DATA"
ln -s "$TARGET" "$LINK_ROOT/linked-project"

cat > "$DATA/project-a.json" <<'EOF'
[
  {"id":"a-overdue","title":"same title","status":"open","priority":2,"updated_at":"2026-07-20T00:00:00Z","due_at":"2026-07-29T00:00:00Z"},
  {"id":"a-soon","title":"due soon","status":"open","priority":1,"updated_at":"2026-07-30T00:00:00Z","due_at":"2026-08-05T00:00:00Z"},
  {"id":"a-future","title":"future deferred","status":"deferred","priority":0,"updated_at":"2026-05-01T00:00:00Z","defer_until":"2026-08-15T00:00:00Z"},
  {"id":"a-future-due","title":"future deferred with overdue due","status":"deferred","priority":0,"updated_at":"2026-05-01T00:00:00Z","due_at":"2026-07-01T00:00:00Z","defer_until":"2026-08-15T00:00:00Z"},
  {"id":"a-expired-one","title":"expired one week","status":"open","priority":3,"updated_at":"2026-07-29T00:00:00Z","defer_until":"2026-07-20T00:00:00Z"},
  {"id":"a-expired-two","title":"expired two weeks","status":"open","priority":3,"updated_at":"2026-07-29T00:00:00Z","defer_until":"2026-07-10T00:00:00Z"},
  {"id":"a-stale","title":"stale task","status":"open","priority":2,"updated_at":"2026-06-01T00:00:00Z"},
  {"id":"a-timezone-fresh","title":"Taipei date is only 29 days old","status":"open","priority":2,"updated_at":"2026-07-01T16:30:00Z"},
  {"id":"a-fresh-p0","title":"fresh high priority","status":"open","priority":0,"updated_at":"2026-07-30T00:00:00Z"}
]
EOF

cat > "$DATA/project-b.json" <<'EOF'
[
  {"id":"b-overdue","title":"same title","status":"open","priority":1,"updated_at":"2026-07-25T00:00:00Z","due_at":"2026-07-28T00:00:00Z"}
]
EOF

cat > "$DATA/quiet.json" <<'EOF'
[
  {"id":"q-fresh","title":"fresh","status":"open","priority":0,"updated_at":"2026-07-30T00:00:00Z"},
  {"id":"q-future","title":"future","status":"deferred","priority":1,"updated_at":"2026-05-01T00:00:00Z","defer_until":"2026-08-15T00:00:00Z"}
]
EOF

cat > "$DATA/malformed.json" <<'EOF'
[{}]
EOF

cat > "$DATA/linked-target.json" <<'EOF'
[
  {"id":"linked-overdue","title":"linked overdue","status":"open","priority":2,"updated_at":"2026-07-30T00:00:00Z","due_at":"2026-07-01T00:00:00Z"}
]
EOF

cat > "$DATA/slow.json" <<'EOF'
[]
EOF

cat > "$FAKE" <<'EOF'
#!/bin/bash
printf '%s\n' "$*" >> "$ARGS_LOG"
repo=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "-C" ]; then
    repo="$2"
    shift 2
    continue
  fi
  shift
done
name=$(basename "$repo")
python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1]))))' "$FAKE_DATA_DIR/$name.json"
EOF
chmod +x "$FAKE"

cat > "$SLOW" <<'EOF'
#!/bin/bash
sleep 1
printf '[]\n'
EOF
chmod +x "$SLOW"

PASS=0
FAIL=0
check() {
  local name="$1"
  shift
  if "$@"; then
    PASS=$((PASS + 1))
    printf '  ok   %s\n' "$name"
  else
    FAIL=$((FAIL + 1))
    printf '  FAIL %s\n' "$name"
  fi
}

not_has() {
  test -f "$1" && ! grep -qF -- "$2" "$1"
}

OUT="$TMP/report.md"
ARGS_LOG="$ARGS_LOG" FAKE_DATA_DIR="$DATA" python3 "$SCRIPT" --date 2026-07-31 --out "$OUT" --root "$ROOT/project-a" --root "$ROOT/project-b" --bd-bin "$FAKE" >/dev/null 2>&1
RUN_STATUS=$?
FULL="$TMP/full.md"
ARGS_LOG="$TMP/full.log" FAKE_DATA_DIR="$DATA" python3 "$SCRIPT" --date 2026-07-31 --out "$FULL" --root "$ROOT/project-a" --bd-bin "$FAKE" --limit 20 >/dev/null 2>&1
check "scanner 執行成功" test "$RUN_STATUS" = 0
check "候選總數包含 overdue soon expired stale" grep -qF 'candidates: 6' "$OUT"
check "只展開兩筆" test "$(grep -c '^## B[12]$' "$OUT")" = 2
check "剩餘四筆" grep -qF 'remaining: 4' "$OUT"
check "B1 是最早逾期" bash -c "grep -A8 '^## B1$' '$OUT' | grep -qF 'b-overdue'"
check "B2 是次早逾期" bash -c "grep -A8 '^## B2$' '$OUT' | grep -qF 'a-overdue'"
check "跨 repo 同名保留絕對路徑" grep -qF "$ROOT/project-b" "$OUT"
check "每筆含入選原因" test "$(grep -c '^- reason:' "$OUT")" = 2
check "每筆含 due" test "$(grep -c '^- due:' "$OUT")" = 2
check "每筆含 defer" test "$(grep -c '^- defer:' "$OUT")" = 2
check "每筆含 age" test "$(grep -c '^- age_days:' "$OUT")" = 2
check "fresh P0 不單獨入選" not_has "$FULL" 'a-fresh-p0'
check "future deferred 不入選" not_has "$FULL" '- id: `a-future`'
check "future defer 優先於 overdue due" not_has "$FULL" 'a-future-due'
check "updated_at 先換台北日期再算老化" not_has "$FULL" 'a-timezone-fresh'
check "錯過一輪 defer 仍入選" grep -qF 'expired one week' "$FULL"
check "錯過兩輪 defer 仍入選" grep -qF 'expired two weeks' "$FULL"
check "bd 查詢強制 readonly" grep -q -- '--readonly' "$ARGS_LOG"
check "bd 查詢強制 limit 0" grep -q -- '--limit 0' "$ARGS_LOG"
check "bd 查詢多 status 用逗號" grep -q -- '--status open,in_progress,blocked,deferred' "$ARGS_LOG"

QUIET="$TMP/quiet.md"
ARGS_LOG="$TMP/quiet.log" FAKE_DATA_DIR="$DATA" python3 "$SCRIPT" --date 2026-07-31 --out "$QUIET" --root "$ROOT/quiet" --bd-bin "$FAKE" >/dev/null 2>&1
check "無候選輸出 SILENT" test "$(cat "$QUIET")" = '__SILENT__'

MALFORMED_ERR="$TMP/malformed.err"
ARGS_LOG="$TMP/malformed.log" FAKE_DATA_DIR="$DATA" python3 "$SCRIPT" --date 2026-07-31 --out "$TMP/malformed.md" --root "$ROOT/malformed" --bd-bin "$FAKE" >/dev/null 2>"$MALFORMED_ERR"
MALFORMED_STATUS=$?
check "畸形 issue 明確失敗" test "$MALFORMED_STATUS" = 1
check "畸形 issue 錯誤含 repo 與 index" bash -c "grep -qF '$ROOT/malformed' '$MALFORMED_ERR' && grep -qF 'issue 0' '$MALFORMED_ERR'"

LINK_OUT="$TMP/linked.md"
ARGS_LOG="$TMP/linked.log" FAKE_DATA_DIR="$DATA" python3 "$SCRIPT" --date 2026-07-31 --out "$LINK_OUT" --root "$LINK_ROOT" --bd-bin "$FAKE" >/dev/null 2>&1
check "symlink 專案會被掃到" grep -qF 'linked-overdue' "$LINK_OUT"

SLOW_ERR="$TMP/slow.err"
ARGS_LOG="$TMP/slow.log" FAKE_DATA_DIR="$DATA" python3 "$SCRIPT" --date 2026-07-31 --out "$TMP/slow.md" --root "$ROOT/slow" --bd-bin "$SLOW" --bd-timeout 0.1 >/dev/null 2>"$SLOW_ERR"
SLOW_STATUS=$?
check "bd timeout 非 0 退出" test "$SLOW_STATUS" = 1
check "bd timeout 錯誤含 repo" bash -c "grep -qF '$ROOT/slow' '$SLOW_ERR' && grep -qi 'timed out' '$SLOW_ERR'"

printf '\n%s PASS / %s FAIL\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
