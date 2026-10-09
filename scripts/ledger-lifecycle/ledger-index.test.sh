#!/bin/bash
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$DIR/ledger-index.py"
TMP="$(mktemp -d /tmp/ledger-index-test.XXXXXX)"
trap 'rc=$?; rm -rf "$TMP"; exit $rc' EXIT
PASS=0
FAIL=0

check() {
  local name="$1" expect="$2" actual="$3"
  if [ "$expect" = "$actual" ]; then
    PASS=$((PASS + 1))
    printf '  ok   %-64s %s\n' "$name" "$actual"
  else
    FAIL=$((FAIL + 1))
    printf '  FAIL %-64s expect=%s actual=%s\n' "$name" "$expect" "$actual"
  fi
}

ARCHIVE="$TMP/archived.md"
ARCHIVE_INDEX="$TMP/archived.index.md"
cat > "$ARCHIVE" <<'EOF'
# Archived Trials
### legacy arrow (2026-01-02 → 2026-01-03 review KILL)
**Verdict：KILL** — legacy reason.
### legacy simple (2026-01-04)
**Verdict：KEEP** — simple reason.
### ✅ [結案 2026-02-03 · KEEP — explicit reason] modern keep (原 review 2026-02-01)
**Verdict**：KEEP — explicit reason.
### ✅ [結案 2026-03-03 · DEFER — defer reason] modern defer｜variant (原 review 2026-03-01)
**Verdict**：DEFER — defer reason.
### ✅ [結案 2026-04-03 · 已處理] headroom（當日安裝當日移除，無 review 期）
**結案動作**：fixture close.
### child heading（2026-04-01）
This is not an entry.
### no date heading
This is not an entry.
EOF

if [ ! -f "$SCRIPT" ]; then
  printf '%s\n' 'RED: ledger-index.py is missing'
  exit 1
fi

python3 "$SCRIPT" build --kind archived --source "$ARCHIVE" --output "$ARCHIVE_INDEX" >/dev/null
check "archived valid entry count" 5 "$(grep -vE '^(#|$)' "$ARCHIVE_INDEX" | wc -l | tr -d ' ')"
check "legacy verdict is UNKNOWN" 1 "$(grep -c '^legacy-arrow｜UNKNOWN｜2026-01-03｜' "$ARCHIVE_INDEX")"
check "new free-text verdict is UNKNOWN" 1 "$(grep -c '^headroom｜UNKNOWN｜2026-04-03｜已處理｜' "$ARCHIVE_INDEX")"
check "modern verdict is extracted" 1 "$(grep -c '^modern-keep｜KEEP｜2026-02-03｜explicit reason｜### ✅ \[結案 2026-02-03 · KEEP — explicit reason\] modern keep (原 review 2026-02-01)$' "$ARCHIVE_INDEX")"
check "child heading is excluded" 0 "$(grep -c 'child-heading' "$ARCHIVE_INDEX")"
check "anchor preserves title delimiter" 1 "$(grep -F -c '### ✅ [結案 2026-03-03 · DEFER — defer reason] modern defer｜variant (原 review 2026-03-01)' "$ARCHIVE_INDEX")"
if python3 "$SCRIPT" build --kind archived --source "$ARCHIVE" --output "$ARCHIVE" >/dev/null 2>&1; then
  SAME_PATH_FAILURE=0
else
  SAME_PATH_FAILURE=1
fi
check "build rejects source overwrite" 1 "$SAME_PATH_FAILURE"
check "source remains intact after rejected overwrite" 1 "$(grep -c '^# Archived Trials$' "$ARCHIVE")"

BUILD_PARENT_TARGET="$TMP/build-output-parent-target"
BUILD_PARENT_LINK="$TMP/build-output-parent"
BUILD_SYMLINK_OUTPUT="$BUILD_PARENT_LINK/index.md"
BUILD_SYMLINK_SOURCE="$TMP/build-symlink-source.md"
BUILD_SYMLINK_ANCHOR='### PR-009 output parent symlink'
mkdir -p "$BUILD_PARENT_TARGET"
ln -s "$BUILD_PARENT_TARGET" "$BUILD_PARENT_LINK"
printf '%s\n' 'keep external bytes' > "$BUILD_PARENT_TARGET/keep.txt"
printf '%s\n' '# 校稿紀錄' "$BUILD_SYMLINK_ANCHOR" '- **文章**：fixture' '- **校稿項目**：output parent symlink' > "$BUILD_SYMLINK_SOURCE"
cp "$BUILD_SYMLINK_SOURCE" "$TMP/build-source-before.md"
cp "$BUILD_PARENT_TARGET/keep.txt" "$TMP/build-keep-before.txt"
if python3 "$SCRIPT" build --kind proofread --source "$BUILD_SYMLINK_SOURCE" --output "$BUILD_SYMLINK_OUTPUT" --pending-anchor "$BUILD_SYMLINK_ANCHOR" > "$TMP/build-symlink.log" 2>&1; then
  BUILD_SYMLINK_FAILURE=0
else
  BUILD_SYMLINK_FAILURE=1
fi
if cmp -s "$TMP/build-source-before.md" "$BUILD_SYMLINK_SOURCE"; then
  BUILD_SOURCE_IDENTICAL=1
else
  BUILD_SOURCE_IDENTICAL=0
fi
if cmp -s "$TMP/build-keep-before.txt" "$BUILD_PARENT_TARGET/keep.txt" && [ "$(find "$BUILD_PARENT_TARGET" -type f | wc -l | tr -d ' ')" = '1' ]; then
  BUILD_EXTERNAL_IDENTICAL=1
else
  BUILD_EXTERNAL_IDENTICAL=0
fi
check "build rejects output parent symlink" 1 "$BUILD_SYMLINK_FAILURE"
check "output parent symlink leaves source byte-identical" 1 "$BUILD_SOURCE_IDENTICAL"
check "output parent symlink leaves external contents byte-identical" 1 "$BUILD_EXTERNAL_IDENTICAL"
check "output parent symlink reports a path diagnostic" 1 "$(grep -ci 'symlink' "$TMP/build-symlink.log")"

PROOFREAD="$TMP/proofread-log.md"
PROOFREAD_INDEX="$TMP/proofread-log.index.md"
cat > "$PROOFREAD" <<'EOF'
# 校稿紀錄
## 主題：example-post
### PR-001 結構問題
- **文章**：example-post
- **校稿項目**：開頭缺少問題
- **類別**：結構
- **修正**：補上問題
### PR-002 缺欄位
- **文章**：second-post
- **修正**：改寫段落
EOF
python3 "$SCRIPT" build --kind proofread --source "$PROOFREAD" --output "$PROOFREAD_INDEX" >/dev/null
check "proofread keeps missing type as UNKNOWN" 1 "$(grep -c '^PR-002｜second-post｜UNKNOWN｜改寫段落｜### PR-002 缺欄位$' "$PROOFREAD_INDEX")"

FACTCHECK="$TMP/factcheck-log.md"
cat > "$FACTCHECK" <<'EOF'
# 事實查核紀錄
## 主題：example-post（系列）
### FC-001 一條宣稱
- **宣稱**：工具會工作
- **判定**：成立
### 無編號舊段
- **宣稱**：缺少編號
## 主題：中文主題
### FC-002 中文宣稱
- **宣稱**：中文工具會工作
- **判定**：未驗
EOF
FACT_JSON="$TMP/factcheck.json"
python3 "$SCRIPT" inspect --kind factcheck --source "$FACTCHECK" --json > "$FACT_JSON"
check "factcheck parser preserves missing identifier" 1 "$(python3 - "$FACT_JSON" <<'PY'
import json
import sys
rows=json.load(open(sys.argv[1]))
print(sum(row['id'] == 'UNKNOWN' for row in rows))
PY
)"
check "factcheck parser extracts topic slug" 2 "$(python3 - "$FACT_JSON" <<'PY'
import json
import sys
rows=json.load(open(sys.argv[1]))
print(sum(row['topic'] == 'example-post' for row in rows))
PY
)"
check "factcheck parser strips Chinese topic label" 1 "$(python3 - "$FACT_JSON" <<'PY'
import json
import sys
rows=json.load(open(sys.argv[1]))
print(sum(row['topic'] == '中文主題' for row in rows))
PY
)"

python3 "$SCRIPT" reconcile --kind proofread --source "$PROOFREAD" --index "$PROOFREAD_INDEX" > "$TMP/reconcile-ok.txt"
check "reconcile equal" 1 "$(grep -c '差異 0' "$TMP/reconcile-ok.txt")"
TRAIL_SOURCE="$TMP/trailing.md"
TRAIL_INDEX="$TMP/trailing.index.md"
printf '### PR-007 trailing  \n' > "$TRAIL_SOURCE"
python3 "$SCRIPT" build --kind proofread --source "$TRAIL_SOURCE" --output "$TRAIL_INDEX" >/dev/null
python3 "$SCRIPT" reconcile --kind proofread --source "$TRAIL_SOURCE" --index "$TRAIL_INDEX" > "$TMP/trailing-reconcile.txt"
check "reconcile preserves anchor trailing spaces" 1 "$(grep -c '差異 0' "$TMP/trailing-reconcile.txt")"
printf '%s\n' '### PR-003 新增條目' >> "$PROOFREAD"
python3 "$SCRIPT" reconcile --kind proofread --source "$PROOFREAD" --index "$PROOFREAD_INDEX" > "$TMP/reconcile-drift.txt"
check "reconcile N versus N-1" 1 "$(grep -c '差異 1' "$TMP/reconcile-drift.txt")"
check "reconcile lists missing anchor" 1 "$(grep -c 'PR-003 新增條目' "$TMP/reconcile-drift.txt")"

NEW_LINE='PR-003｜new-post｜UNKNOWN｜UNKNOWN｜### PR-003 新增條目'
BAD_INDEX="$TMP/missing/index.md"
if python3 "$SCRIPT" append --kind proofread --source "$PROOFREAD" --index "$BAD_INDEX" --anchor '### PR-003 新增條目' --line "$NEW_LINE" >/dev/null 2>&1; then
  APPEND_FAILURE=0
else
  APPEND_FAILURE=1
fi
check "append failure returns nonzero" 1 "$APPEND_FAILURE"
check "append failure marks source" 1 "$(grep -c '\[index-pending\]' "$PROOFREAD")"
mkdir -p "$TMP/missing"
python3 "$SCRIPT" append --kind proofread --source "$PROOFREAD" --index "$BAD_INDEX" --anchor '### PR-003 新增條目' --line "$NEW_LINE" >/dev/null
check "successful retry clears pending" 0 "$(grep -c '\[index-pending\]' "$PROOFREAD")"
check "successful retry appends index line" 1 "$(grep -c '^PR-003｜new-post｜UNKNOWN｜UNKNOWN｜### PR-003 新增條目$' "$BAD_INDEX")"
PENDING_TEXT_SOURCE="$TMP/pending-text.md"
PENDING_TEXT_INDEX="$TMP/pending-text/index.md"
printf '%s\n' '### PR-008 正文 marker' '- 說明 [index-pending] 行為' > "$PENDING_TEXT_SOURCE"
if python3 "$SCRIPT" append --kind proofread --source "$PENDING_TEXT_SOURCE" --index "$PENDING_TEXT_INDEX" --anchor '### PR-008 正文 marker' --line 'PR-008｜fixture｜結構｜reason｜### PR-008 正文 marker' >/dev/null 2>&1; then
  PENDING_TEXT_FAILURE=0
else
  PENDING_TEXT_FAILURE=1
fi
check "正文含 marker 字串時失敗仍回非零" 1 "$PENDING_TEXT_FAILURE"
check "正文含 marker 字串時插入獨立 marker" 1 "$(grep -c '^<!-- \[index-pending\] -->$' "$PENDING_TEXT_SOURCE")"
check "正文 marker 字串失敗時保留" 1 "$(grep -c '說明 \[index-pending\] 行為' "$PENDING_TEXT_SOURCE")"
mkdir -p "$TMP/pending-text"
python3 "$SCRIPT" append --kind proofread --source "$PENDING_TEXT_SOURCE" --index "$PENDING_TEXT_INDEX" --anchor '### PR-008 正文 marker' --line 'PR-008｜fixture｜結構｜reason｜### PR-008 正文 marker' >/dev/null
check "成功後只清除獨立 marker" 0 "$(grep -c '^<!-- \[index-pending\] -->$' "$PENDING_TEXT_SOURCE")"
check "成功後正文 marker 字串保留" 1 "$(grep -c '說明 \[index-pending\] 行為' "$PENDING_TEXT_SOURCE")"
MALFORMED_SOURCE="$TMP/malformed-source.md"
MALFORMED_INDEX="$TMP/malformed.index.md"
printf '%s\n' '### PR-005 malformed existing row' > "$MALFORMED_SOURCE"
printf '%s\n' '# proofread index' 'broken row' > "$MALFORMED_INDEX"
if python3 "$SCRIPT" append --kind proofread --source "$MALFORMED_SOURCE" --index "$MALFORMED_INDEX" --anchor '### PR-005 malformed existing row' --line 'PR-005｜fixture｜結構｜reason｜### PR-005 malformed existing row' >/dev/null 2>&1; then
  MALFORMED_EXISTING_FAILURE=0
else
  MALFORMED_EXISTING_FAILURE=1
fi
check "malformed existing index returns nonzero" 1 "$MALFORMED_EXISTING_FAILURE"
check "malformed existing index marks source" 1 "$(grep -c '\[index-pending\]' "$MALFORMED_SOURCE")"
MALFORMED_LINE_SOURCE="$TMP/malformed-line-source.md"
printf '%s\n' '### PR-006 malformed new row' > "$MALFORMED_LINE_SOURCE"
if python3 "$SCRIPT" append --kind proofread --source "$MALFORMED_LINE_SOURCE" --index "$TMP/malformed-line.index.md" --anchor '### PR-006 malformed new row' --line 'broken row' >/dev/null 2>&1; then
  MALFORMED_LINE_FAILURE=0
else
  MALFORMED_LINE_FAILURE=1
fi
check "malformed new index line returns nonzero" 1 "$MALFORMED_LINE_FAILURE"
check "malformed new index line marks source" 1 "$(grep -c '\[index-pending\]' "$MALFORMED_LINE_SOURCE")"
printf '%s\n' '### PR-004 首次建置失敗' >> "$PROOFREAD"
BUILD_BAD="$TMP/uncreated/index.md"
if python3 "$SCRIPT" build --kind proofread --source "$PROOFREAD" --output "$BUILD_BAD" --pending-anchor '### PR-004 首次建置失敗' >/dev/null 2>&1; then
  BUILD_FAILURE=0
else
  BUILD_FAILURE=1
fi
check "build failure returns nonzero" 1 "$BUILD_FAILURE"
check "build failure marks source" 1 "$(grep -c '\[index-pending\]' "$PROOFREAD")"
mkdir -p "$TMP/uncreated"
if python3 "$SCRIPT" build --kind proofread --source "$PROOFREAD" --output "$BUILD_BAD" --pending-anchor '### PR-004 首次建置失敗' >/dev/null 2>&1; then
  BUILD_RETRY=0
else
  BUILD_RETRY=1
fi
check "build retry returns zero" 0 "$BUILD_RETRY"
check "build retry clears only pending entry" 0 "$(grep -c '\[index-pending\]' "$PROOFREAD")"
python3 "$SCRIPT" reconcile --kind proofread --source "$PROOFREAD" --index "$BUILD_BAD" > "$TMP/build-reconcile.txt"
check "build retry reconcile is zero" 1 "$(grep -c '差異 0' "$TMP/build-reconcile.txt")"
PARTIAL_SOURCE="$TMP/partial.md"
PARTIAL_INDEX="$TMP/partial.index.md"
printf '%s\n' '### PR-001 partial one' '<!-- [index-pending] -->' '### PR-002 partial two' '<!-- [index-pending] -->' > "$PARTIAL_SOURCE"
python3 "$SCRIPT" build --kind proofread --source "$PARTIAL_SOURCE" --output "$PARTIAL_INDEX" --pending-anchor '### PR-001 partial one' >/dev/null
check "batch build preserves another pending entry" 1 "$(grep -c '\[index-pending\]' "$PARTIAL_SOURCE")"

printf 'ledger-index test: %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
