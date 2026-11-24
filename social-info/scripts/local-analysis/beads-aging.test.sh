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

MALFORMED_OUT="$TMP/malformed.md"
ARGS_LOG="$TMP/malformed.log" FAKE_DATA_DIR="$DATA" python3 "$SCRIPT" --date 2026-07-31 --out "$MALFORMED_OUT" --root "$ROOT/malformed" --bd-bin "$FAKE" >/dev/null 2>"$TMP/malformed.err"
MALFORMED_STATUS=$?
check "畸形 issue 寫入失敗段不中斷整體掃描" test "$MALFORMED_STATUS" = 0
check "畸形 issue 報告含 repo 與 index" bash -c "grep -qF '掃描失敗 repo' '$MALFORMED_OUT' && grep -qF '$ROOT/malformed' '$MALFORMED_OUT' && grep -qF 'issue 0' '$MALFORMED_OUT'"

LINK_OUT="$TMP/linked.md"
ARGS_LOG="$TMP/linked.log" FAKE_DATA_DIR="$DATA" python3 "$SCRIPT" --date 2026-07-31 --out "$LINK_OUT" --root "$LINK_ROOT" --bd-bin "$FAKE" >/dev/null 2>&1
check "symlink 專案會被掃到" grep -qF 'linked-overdue' "$LINK_OUT"

SLOW_OUT="$TMP/slow.md"
ARGS_LOG="$TMP/slow.log" FAKE_DATA_DIR="$DATA" python3 "$SCRIPT" --date 2026-07-31 --out "$SLOW_OUT" --root "$ROOT/slow" --bd-bin "$SLOW" --bd-timeout 0.1 >/dev/null 2>"$TMP/slow.err"
SLOW_STATUS=$?
check "bd timeout 寫入失敗段並 0 退出" test "$SLOW_STATUS" = 0
check "bd timeout 報告含 repo 與 timed out" bash -c "grep -qF '掃描失敗 repo' '$SLOW_OUT' && grep -qF '$ROOT/slow' '$SLOW_OUT' && grep -qi 'timed out' '$SLOW_OUT'"

BADJSON_ROOT="$TMP/badjson-root"
mkdir -p "$BADJSON_ROOT/bad-json/.beads" "$BADJSON_ROOT/bad-date/.beads" "$BADJSON_ROOT/empty-due-at/.beads"
FAKE_EDGE="$TMP/bd-edge"
cat > "$FAKE_EDGE" <<'EOF'
#!/bin/bash
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
case "$name" in
  bad-json) printf '{not valid json\n' ;;
  bad-date) printf '[{"id":"bd1","title":"bad date","status":"open","priority":1,"updated_at":"not-a-date"}]\n' ;;
  empty-due-at) printf '[{"id":"ed1","title":"fallback due","status":"open","priority":2,"updated_at":"2026-07-30T00:00:00Z","due_at":"","due":"2026-07-20T00:00:00Z"}]\n' ;;
  *) python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1]))))' "$FAKE_DATA_DIR/$name.json" ;;
esac
EOF
chmod +x "$FAKE_EDGE"

EDGE_JSON_OUT="$TMP/edge-json.md"
FAKE_DATA_DIR="$DATA" python3 "$SCRIPT" --date 2026-07-31 --out "$EDGE_JSON_OUT" --root "$ROOT/project-b" --root "$BADJSON_ROOT/bad-json" --bd-bin "$FAKE_EDGE" >/dev/null 2>"$TMP/edge-json.err"
EDGE_JSON_RC=$?
check "bd 畸形 JSON 隔離失敗不中斷健康 repo" test "$EDGE_JSON_RC" = 0
check "bd 畸形 JSON 報告含健康候選與失敗段" bash -c "grep -qF 'b-overdue' '$EDGE_JSON_OUT' && grep -qF 'bad-json' '$EDGE_JSON_OUT'"

EDGE_DATE_OUT="$TMP/edge-date.md"
FAKE_DATA_DIR="$DATA" python3 "$SCRIPT" --date 2026-07-31 --out "$EDGE_DATE_OUT" --root "$ROOT/project-b" --root "$BADJSON_ROOT/bad-date" --bd-bin "$FAKE_EDGE" >/dev/null 2>"$TMP/edge-date.err"
EDGE_DATE_RC=$?
check "無效日期 issue 隔離失敗不中斷健康 repo" test "$EDGE_DATE_RC" = 0
check "無效日期 issue 報告含健康候選與失敗段" bash -c "grep -qF 'b-overdue' '$EDGE_DATE_OUT' && grep -qF 'bad-date' '$EDGE_DATE_OUT'"
check "無效日期的失敗段指出 issue ID 與欄位" grep -qE 'issue bd1 .*has invalid updated_at' "$EDGE_DATE_OUT"

python3 "$SCRIPT" --date 2026-07-31 --out "$TMP/nan.md" --root "$TMP/empty-root" --bd-bin "$FAKE" --bd-timeout nan >/dev/null 2>&1
NAN_RC=$?
check "--bd-timeout nan 拒絕執行" test "$NAN_RC" != 0

python3 "$SCRIPT" --date 2026-07-31 --out "$TMP/inf.md" --root "$TMP/empty-root" --bd-bin "$FAKE" --bd-timeout inf >/dev/null 2>&1
INF_RC=$?
check "--bd-timeout inf 拒絕執行" test "$INF_RC" != 0

EMPTY_DUE_OUT="$TMP/empty-due.md"
FAKE_DATA_DIR="$DATA" python3 "$SCRIPT" --date 2026-07-31 --out "$EMPTY_DUE_OUT" --root "$BADJSON_ROOT/empty-due-at" --bd-bin "$FAKE_EDGE" >/dev/null 2>&1
check "空字串 due_at 應退回使用 due 欄位" grep -qF 'ed1' "$EMPTY_DUE_OUT"

BOUNDARY_ROOT="$TMP/boundary-root"
mkdir -p "$BOUNDARY_ROOT/exact-bounds/.beads"
cat > "$DATA/exact-bounds.json" <<'EOF'
[
  {"id":"due-day-7","title":"exact 7 days due","status":"open","priority":2,"updated_at":"2026-07-30T00:00:00Z","due_at":"2026-08-07"},
  {"id":"stale-day-30","title":"exact 30 days stale","status":"open","priority":2,"updated_at":"2026-07-01T00:00:00+08:00"}
]
EOF
BOUND_OUT="$TMP/exact-bounds.md"
ARGS_LOG="$TMP/bound.log" FAKE_DATA_DIR="$DATA" python3 "$SCRIPT" --date 2026-07-31 --out "$BOUND_OUT" --root "$BOUNDARY_ROOT/exact-bounds" --bd-bin "$FAKE" --limit 10 >/dev/null 2>&1
check "剛好 7 天內到期邊界入選" grep -qF 'due-day-7' "$BOUND_OUT"
check "剛好 30 天未更新邊界入選" grep -qF 'stale-day-30' "$BOUND_OUT"

mkdir -p "$BOUNDARY_ROOT/year-end/.beads"
printf '%s\n' '[{"id":"due-at-max","title":"due at date.max","priority":2,"updated_at":"9999-12-30","due_at":"9999-12-31"}]' > "$DATA/year-end.json"
ARGS_LOG="$TMP/year-end.log" FAKE_DATA_DIR="$DATA" python3 "$SCRIPT" --date 9999-12-30 --out "$TMP/year-end.md" --root "$BOUNDARY_ROOT/year-end" --bd-bin "$FAKE" >/dev/null
check "接近最晚曆日仍能分類隔日到期議題" bash -c 'grep -qF "due-at-max" "$1" && grep -qF "reason: 1 天內到期" "$1"' _ "$TMP/year-end.md"

printf '\n%s PASS / %s FAIL\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
