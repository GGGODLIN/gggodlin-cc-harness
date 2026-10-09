#!/usr/bin/env bash
# rules-size-weekly.sh 的行為測試：規則檔、報告目錄、state 全導到臨時目錄，不碰真實 ~/.claude 與 reports/。
# 零使用清單由 stub 或真的 session-audit.py zero-use（空 state）提供；清單本身的判斷由 session-audit.test.py 負責。
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WRAPPER="$SCRIPT_DIR/rules-size-weekly.sh"
TMP="$(mktemp -d)"
PASS=0
FAIL=0
DATE="2026-10-05"
PY_BIN="$(command -v /opt/homebrew/bin/python3 || command -v python3)"

cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

pass() { PASS=$((PASS + 1)); printf 'PASS: %s\n' "$1"; }
fail() { FAIL=$((FAIL + 1)); printf 'FAIL: %s\n' "$1"; }

assert_contains() {
  if printf '%s' "$3" | grep -qF -- "$2"; then pass "$1"; else fail "$1 — missing: $2"; fi
}
assert_not_contains() {
  if printf '%s' "$3" | grep -qF -- "$2"; then fail "$1 — unexpected: $2"; else pass "$1"; fi
}

mkdir -p "$TMP/home/rules/common"
printf '# small\n- one rule\n' > "$TMP/home/CLAUDE.md"
printf '# common\n- another rule\n' > "$TMP/home/rules/common/a.md"

cat > "$TMP/stub_zero.py" <<'PY'
import os
import sys

assert sys.argv[1] == "zero-use", sys.argv
mode = os.environ["STUB_MODE"]
if mode == "fail":
    print("rules-roster-unavailable", file=sys.stderr)
    sys.exit(2)
if mode == "empty":
    print("## 🪦 零使用規則候選（0）")
    print("本週沒有候選")
else:
    print("## 🪦 零使用規則候選（2）")
    print("連續 4 個有覆蓋的週沒遇到場合；觀察範圍內未見場合的候選，不是已證明的死碼")
    print("- 「規則甲」｜識別 `aaaaaaaaaaaaaaaa`｜CLAUDE.md｜判斷用 commit `111111111111`｜觀察期間 2026-W38～2026-W41（4 週）｜最近一次遇到場合：開始觀察後未見")
    print("- 「規則乙」｜識別 `bbbbbbbbbbbbbbbb`｜rules/common/a.md｜判斷用 commit `111111111111`｜觀察期間 2026-W38～2026-W41（4 週）｜最近一次遇到場合：開始觀察後未見")
PY

# run_wrapper <stub mode|real> [claude cap]
run_wrapper() {
  local mode="$1" cap="${2:-14000}"
  rm -rf "$TMP/repo" "$TMP/state"
  local script_env=()
  [ "$mode" = "real" ] || script_env=(RULES_SIZE_ZERO_USE_SCRIPT="$TMP/stub_zero.py")
  env STUB_MODE="$mode" \
    LOCAL_ANALYSIS_DATE="$DATE" \
    RULES_SIZE_REPO_DIR="$TMP/repo" \
    RULES_SIZE_CLAUDE_HOME="$TMP/home" \
    RULES_SIZE_CLAUDE_CAP="$cap" \
    SESSION_AUDIT_PYTHON="$PY_BIN" \
    SESSION_AUDIT_STATE="$TMP/state" \
    RULES_SIZE_RULES_REPO="$TMP/no-rules-repo" \
    ${script_env[@]+"${script_env[@]}"} \
    bash "$WRAPPER" >/dev/null 2>&1
}

out_file="$TMP/repo/reports/local-analysis/$DATE-rules-size.md"

# 1. 未超標且零使用 0 條：維持 __SILENT__。
run_wrapper empty; rc=$?
[ "$rc" -eq 0 ] && pass "within caps, no candidates exits 0" || fail "within caps, no candidates exits 0 — rc=$rc"
[ "$(cat "$out_file" 2>/dev/null)" = "__SILENT__" ] && pass "within caps, no candidates stays __SILENT__" || fail "within caps, no candidates stays __SILENT__ — $(cat "$out_file" 2>/dev/null)"

# 2. 未超標但有候選：寫報告，只有標題＋零使用段，不能出現「🎯 建議處理」（daily-local 靠它判斷超標）。
run_wrapper candidates; rc=$?
report="$(cat "$out_file" 2>/dev/null)"
[ "$rc" -eq 0 ] && pass "within caps with candidates exits 0" || fail "within caps with candidates exits 0 — rc=$rc"
assert_contains "candidates report has the zero-use heading" "## 🪦 零使用規則候選（2）" "$report"
assert_contains "candidates report keeps the items" "- 「規則乙」" "$report"
assert_contains "candidates report has a title" "# Rules 檔長度健康度 Weekly — $DATE" "$report"
assert_not_contains "within caps never writes the over-cap heading" "🎯 建議處理" "$report"
assert_not_contains "within caps has no over-cap table" "超標檔案" "$report"
assert_not_contains "within caps report is not silent" "__SILENT__" "$report"

# 3. 超標且零使用 0 條：照舊的超標報告，零使用段接在末尾。
run_wrapper empty 5; rc=$?
report="$(cat "$out_file" 2>/dev/null)"
[ "$rc" -eq 0 ] && pass "over cap exits 0" || fail "over cap exits 0 — rc=$rc"
assert_contains "over cap report has the over-cap heading" "## 🎯 建議處理" "$report"
assert_contains "over cap report lists the file" "超標檔案（1）" "$report"
assert_contains "over cap report ends with the zero-use section" "## 🪦 零使用規則候選（0）" "$report"
[ "$(printf '%s' "$report" | grep -n '🎯 建議處理' | cut -d: -f1)" -lt "$(printf '%s' "$report" | grep -n '🪦 零使用規則候選' | cut -d: -f1)" ] && pass "zero-use section comes after the over-cap body" || fail "zero-use section comes after the over-cap body"

# 4. zero-use 失敗：週報照常產生並寫失敗原因，不整份失敗、不靜默。
run_wrapper fail; rc=$?
report="$(cat "$out_file" 2>/dev/null)"
[ "$rc" -eq 0 ] && pass "zero-use failure keeps the wrapper exit 0" || fail "zero-use failure keeps the wrapper exit 0 — rc=$rc"
assert_contains "failure line carries the reason" "零使用清單產生失敗：rules-roster-unavailable" "$report"
# daily-local 第 5 條只原文保留含 ⚠️ 的行；失敗行不以 ⚠️ 開頭就會在摘要裡消失。
if printf '%s\n' "$report" | grep -q '^⚠️ 零使用清單產生失敗：'; then pass "failure line starts with the warning mark"; else fail "failure line starts with the warning mark"; fi
assert_not_contains "failure within caps does not fake the over-cap heading" "🎯 建議處理" "$report"
run_wrapper fail 5; rc=$?
report="$(cat "$out_file" 2>/dev/null)"
assert_contains "failure plus over cap still has the over-cap heading" "## 🎯 建議處理" "$report"
assert_contains "failure plus over cap still has the failure line" "零使用清單產生失敗：rules-roster-unavailable" "$report"

# 5. 真的 session-audit.py zero-use（state 不存在）：接線與參數正確，0 條仍 __SILENT__。
run_wrapper real; rc=$?
[ "$rc" -eq 0 ] && pass "real zero-use on a missing state exits 0" || fail "real zero-use on a missing state exits 0 — rc=$rc"
[ "$(cat "$out_file" 2>/dev/null)" = "__SILENT__" ] && pass "real zero-use on a missing state stays __SILENT__" || fail "real zero-use on a missing state stays __SILENT__ — $(cat "$out_file" 2>/dev/null)"
[ ! -e "$TMP/state" ] && pass "wrapper does not create the state" || fail "wrapper does not create the state"

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
