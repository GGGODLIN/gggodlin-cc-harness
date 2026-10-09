#!/bin/bash
set -u

HELPER="$HOME/Desktop/projects/.claude/hooks/friction-review-state.py"
FIX=$(mktemp -d)
PASS=0
FAIL=0
CLAIMED_AT=$(date -u -v-1H '+%Y-%m-%dT%H:%M:%SZ')
EXPIRES_AT=$(date -u -v+23H '+%Y-%m-%dT%H:%M:%SZ')
VALID_LOCK="<!-- friction-review-lock:v1 session=test-session claimed_at=${CLAIMED_AT} expires_at=${EXPIRES_AT} -->"
trap 'rm -rf "$FIX"' EXIT

pass() {
  printf 'PASS: %s\n' "$1"
  PASS=$((PASS + 1))
}

fail() {
  printf 'FAIL: %s\n' "$1"
  FAIL=$((FAIL + 1))
}

make_fixture() {
  local file="$1"
  local lock="${2:-$VALID_LOCK}"
  mkdir -p "$(dirname "$file")"
  printf '# fixture\n\n## 待折\n%s\n- alpha\n- beta\n\n## 已折 / 已否決\n\n- old\n' "$lock" > "$file"
}

digest_of() {
  python3 "$HELPER" inspect --file "$1" | awk -F= '/^digest=/{print $2}'
}

validate() {
  python3 "$HELPER" validate --file "$1" --session test-session --digest "$2" >/dev/null 2>&1
}

op_json() {
  python3 - "$1" "$2" "$3" <<'PY'
import json
import sys
print(json.dumps([{'action': sys.argv[1], 'original': sys.argv[2], 'receipt': sys.argv[3]}], ensure_ascii=False))
PY
}

run_transform() {
  local file="$1"
  local digest="$2"
  local operations="$3"
  shift 3
  python3 "$HELPER" transform --file "$file" --session test-session --digest "$digest" --operations "$operations" "$@"
}

FILE="$FIX/friction-log.md"
make_fixture "$FILE"
BASE_DIGEST=$(digest_of "$FILE")
if validate "$FILE" "$BASE_DIGEST"; then pass '認領後完整 owner、期限與 digest 有效'; else fail '認領後完整 owner、期限與 digest 有效'; fi

cp "$FILE" "$FIX/owner-changed.md"
python3 - "$FIX/owner-changed.md" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
p.write_text(p.read_text().replace('session=test-session', 'session=other-session'))
PY
if validate "$FIX/owner-changed.md" "$BASE_DIGEST"; then fail 'owner 改變會被拒絕'; else pass 'owner 改變會被拒絕'; fi

EXPIRED_CLAIM=$(date -u -v-25H '+%Y-%m-%dT%H:%M:%SZ')
EXPIRED_AT=$(date -u -v-1H '+%Y-%m-%dT%H:%M:%SZ')
make_fixture "$FIX/expired.md" "<!-- friction-review-lock:v1 session=test-session claimed_at=${EXPIRED_CLAIM} expires_at=${EXPIRED_AT} -->"
if validate "$FIX/expired.md" "$(digest_of "$FIX/expired.md")"; then fail '過期鎖會被拒絕'; else pass '過期鎖會被拒絕'; fi

FUTURE_CLAIM=$(date -u -v+1H '+%Y-%m-%dT%H:%M:%SZ')
FUTURE_EXPIRY=$(date -u -v+25H '+%Y-%m-%dT%H:%M:%SZ')
make_fixture "$FIX/future-claim.md" "<!-- friction-review-lock:v1 session=test-session claimed_at=${FUTURE_CLAIM} expires_at=${FUTURE_EXPIRY} -->"
if validate "$FIX/future-claim.md" "$(digest_of "$FIX/future-claim.md")"; then fail '未來 claimed_at 會被拒絕'; else pass '未來 claimed_at 會被拒絕'; fi

SHORT_EXPIRY=$(date -u -v+22H '+%Y-%m-%dT%H:%M:%SZ')
make_fixture "$FIX/invalid-window.md" "<!-- friction-review-lock:v1 session=test-session claimed_at=${CLAIMED_AT} expires_at=${SHORT_EXPIRY} -->"
if validate "$FIX/invalid-window.md" "$(digest_of "$FIX/invalid-window.md")"; then fail '非 24 小時鎖會被拒絕'; else pass '非 24 小時鎖會被拒絕'; fi

make_fixture "$FIX/malformed.md" "<!-- friction-review-lock:v1 session=test-session claimed_at=${CLAIMED_AT} -->"
if validate "$FIX/malformed.md" "$(digest_of "$FIX/malformed.md")"; then fail '缺欄 marker 會被拒絕'; else pass '缺欄 marker 會被拒絕'; fi

cp "$FILE" "$FIX/indented-marker.md"
python3 - "$FIX/indented-marker.md" "$VALID_LOCK" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
lock = sys.argv[2]
p.write_text(p.read_text().replace('- alpha\n', f'  {lock}\n- alpha\n', 1))
PY
if validate "$FIX/indented-marker.md" "$BASE_DIGEST"; then fail '前置空白 marker 會被拒絕'; else pass '前置空白 marker 會被拒絕'; fi

cp "$FILE" "$FIX/unknown-version.md"
python3 - "$FIX/unknown-version.md" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
p.write_text(p.read_text().replace('- alpha\n', '<!-- friction-review-lock:v2 session=test-session -->\n- alpha\n', 1))
PY
if validate "$FIX/unknown-version.md" "$BASE_DIGEST"; then fail '未知版本 marker 會被拒絕'; else pass '未知版本 marker 會被拒絕'; fi

cp "$FILE" "$FIX/multiple.md"
python3 - "$FIX/multiple.md" "$VALID_LOCK" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
lock = sys.argv[2]
p.write_text(p.read_text().replace('- alpha\n', f'{lock}\n- alpha\n', 1))
PY
if validate "$FIX/multiple.md" "$(digest_of "$FIX/multiple.md")"; then fail '多 marker 會被拒絕'; else pass '多 marker 會被拒絕'; fi

cp "$FILE" "$FIX/outside-marker.md"
python3 - "$FIX/outside-marker.md" "$VALID_LOCK" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
lock = sys.argv[2]
p.write_text(p.read_text() + f'\n{lock}\n')
PY
if validate "$FIX/outside-marker.md" "$BASE_DIGEST"; then fail '待折段外 marker 會被拒絕'; else pass '待折段外 marker 會被拒絕'; fi

cp "$FILE" "$FIX/wrong-position.md"
python3 - "$FIX/wrong-position.md" "$VALID_LOCK" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
lock = sys.argv[2]
s = p.read_text().replace(lock + '\n', '', 1)
p.write_text(s.replace('- alpha\n', f'- alpha\n{lock}\n', 1))
PY
if validate "$FIX/wrong-position.md" "$BASE_DIGEST"; then fail 'marker 非標題下一行會被拒絕'; else pass 'marker 非標題下一行會被拒絕'; fi

cp "$FILE" "$FIX/digest-drift.md"
python3 - "$FIX/digest-drift.md" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
p.write_text(p.read_text().replace('- beta\n', '- beta\n- external append\n', 1))
PY
if validate "$FIX/digest-drift.md" "$BASE_DIGEST"; then fail '待折內容漂移會被拒絕'; else pass '待折內容漂移會被拒絕'; fi

make_fixture "$FIX/duplicate-pending.md"
python3 - "$FIX/duplicate-pending.md" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
p.write_text(p.read_text() + '\n## 待折\n\n- ignored\n')
PY
if [ "$(digest_of "$FIX/duplicate-pending.md")" = "$(digest_of "$FILE")" ]; then pass '只解析第一個精確待折段'; else fail '只解析第一個精確待折段'; fi

for action in approved rejected landed company-pending; do
  make_fixture "$FIX/second-lock-${action}.md"
  python3 - "$FIX/second-lock-${action}.md" "$CLAIMED_AT" "$EXPIRES_AT" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
claimed_at = sys.argv[2]
expires_at = sys.argv[3]
p.write_text(p.read_text() + f'\n## 待折\n<!-- friction-review-lock:v1 session=other-session claimed_at={claimed_at} expires_at={expires_at} -->\n- ignored\n')
PY
  if [ "$action" = company-pending ]; then
    receipt='- [pending_implementation proposal_source=trial-review:file-3@test; user_decision=approved@test; implementation=N-A（等待公司側落地）] alpha'
  elif [ "$action" = rejected ]; then
    receipt='- [proposal_source=trial-review:file-3@test; user_decision=rejected@test; implementation=N-A] alpha → rejected'
  else
    receipt='- [proposal_source=trial-review:file-3@test; user_decision=approved@test; implementation=abc123:path] alpha → landed'
  fi
  operations=$(op_json "$action" '- alpha' "$receipt")
  if ! run_transform "$FIX/second-lock-${action}.md" "$(digest_of "$FIX/second-lock-${action}.md")" "$operations" --release-lock >/dev/null; then
    fail "$action transform 必須成功"
  elif grep -q '^<!-- friction-review-lock:v1 session=other-session ' "$FIX/second-lock-${action}.md"; then
    pass "$action 保留第二個待折段的鎖"
  else
    fail "$action 保留第二個待折段的鎖"
  fi
done

cp "$FILE" "$FIX/multiline-receipt.md"
multiline=$(op_json approved '- alpha' $'- landed\n## injected')
if run_transform "$FIX/multiline-receipt.md" "$BASE_DIGEST" "$multiline" --release-lock >/dev/null 2>&1; then fail '多行 receipt 會被拒絕'; else pass '多行 receipt 會被拒絕'; fi

cp "$FILE" "$FIX/arbitrary-receipt.md"
arbitrary=$(op_json approved '- alpha' '- arbitrary')
if run_transform "$FIX/arbitrary-receipt.md" "$BASE_DIGEST" "$arbitrary" --release-lock >/dev/null 2>&1; then fail '缺歸因 receipt 會被拒絕'; else pass '缺歸因 receipt 會被拒絕'; fi

printf '# fixture\n\n## 待折\n%s\n- alpha\n' "$VALID_LOCK" > "$FIX/missing-closed.md"
if python3 "$HELPER" inspect --file "$FIX/missing-closed.md" >/dev/null 2>&1; then fail '缺已折段在認領前被拒絕'; else pass '缺已折段在認領前被拒絕'; fi

printf '# fixture\n\n## 已折 / 已否決\n\n- earlier\n\n## 待折\n%s\n- alpha\n\n## 已折 / 已否決\n\n- later\n' "$VALID_LOCK" > "$FIX/closed-before-pending.md"
operations=$(op_json approved '- alpha' '- [proposal_source=trial-review:file-3@test; user_decision=approved@test; implementation=abc123:path] alpha → landed')
run_transform "$FIX/closed-before-pending.md" "$(digest_of "$FIX/closed-before-pending.md")" "$operations" --release-lock >/dev/null
if awk '/^- earlier$/{early=NR}/implementation=abc123:path/{receipt=NR}/^- later$/{late=NR}END{exit early < receipt && receipt < late ? 0 : 1}' "$FIX/closed-before-pending.md"; then pass '搬遷寫入待折段之後的第一個已折段'; else fail '搬遷寫入待折段之後的第一個已折段'; fi

make_fixture "$FIX/batch.md"
batch_ops=$(python3 - <<'PY'
import json
print(json.dumps([
  {'action': 'approved', 'original': '- alpha', 'receipt': '- [proposal_source=trial-review:file-3@test; user_decision=approved@test; implementation=abc123:path] alpha → landed'},
  {'action': 'rejected', 'original': '- beta', 'receipt': '- [proposal_source=trial-review:file-3@test; user_decision=rejected@test; implementation=N-A] beta → rejected'},
], ensure_ascii=False))
PY
)
run_transform "$FIX/batch.md" "$(digest_of "$FIX/batch.md")" "$batch_ops" --release-lock >/dev/null
if ! grep -q 'friction-review-lock:v1' "$FIX/batch.md" && grep -q 'user_decision=approved.*alpha' "$FIX/batch.md" && grep -q 'user_decision=rejected.*beta' "$FIX/batch.md"; then pass '同檔多項目一次批次處理並最後釋放鎖'; else fail '同檔多項目一次批次處理並最後釋放鎖'; fi

make_fixture "$FIX/metadata.md"
METADATA_ORIGINAL='- 2026-08-30 [source_ref=session:test-session#turn-1; signal_type=user-correction; target=skill:example; feedback_quote="short"; why="reason"; flags=minor,duplicate-root] alpha'
python3 - "$FIX/metadata.md" "$METADATA_ORIGINAL" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
path.write_text(path.read_text().replace('- alpha\n', f'{sys.argv[2]}\n', 1))
PY
METADATA_RECEIPT='- 2026-08-30 [proposal_source=trial-review:file-3@test; user_decision=approved@test; implementation=abc123:path] [source_ref=session:test-session#turn-1; signal_type=user-correction; target=skill:example; feedback_quote="short"; why="reason"; flags=minor,duplicate-root] alpha'
metadata_ops=$(op_json approved "$METADATA_ORIGINAL" "$METADATA_RECEIPT")
run_transform "$FIX/metadata.md" "$(digest_of "$FIX/metadata.md")" "$metadata_ops" --release-lock >/dev/null
if grep -q 'implementation=abc123:path.*flags=minor,duplicate-root.*alpha' "$FIX/metadata.md" && ! grep -q 'friction-review-lock:v1' "$FIX/metadata.md"; then pass 'optional metadata 搬遷時完整保留且不需改寫既有 parser'; else fail 'optional metadata 搬遷時完整保留且不需改寫既有 parser'; fi

make_fixture "$FIX/company-pending.md"
pending_ops=$(op_json company-pending '- alpha' '- [pending_implementation proposal_source=trial-review:file-3@test; user_decision=approved@test; implementation=N-A（等待公司側落地）] alpha')
run_transform "$FIX/company-pending.md" "$(digest_of "$FIX/company-pending.md")" "$pending_ops" --release-lock >/dev/null
if run_transform "$FIX/company-pending.md" "$(digest_of "$FIX/company-pending.md")" "$(op_json landed '- [pending_implementation proposal_source=trial-review:file-3@test; user_decision=approved@test; implementation=N-A（等待公司側落地）] alpha' '- [proposal_source=trial-review:file-3@test; user_decision=approved@test; implementation=def456:path] alpha → landed')" --release-lock >/dev/null 2>&1; then fail 'pending 無鎖不得結案'; else pass 'pending 無鎖不得結案'; fi

NEW_CLAIMED_AT=$(date -u -v-30M '+%Y-%m-%dT%H:%M:%SZ')
NEW_EXPIRES_AT=$(date -u -v+23H -v+30M '+%Y-%m-%dT%H:%M:%SZ')
python3 - "$FIX/company-pending.md" "$NEW_CLAIMED_AT" "$NEW_EXPIRES_AT" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
claimed_at = sys.argv[2]
expires_at = sys.argv[3]
p.write_text(p.read_text().replace('## 待折\n', f'## 待折\n<!-- friction-review-lock:v1 session=test-session claimed_at={claimed_at} expires_at={expires_at} -->\n', 1))
PY
landed_ops=$(op_json landed '- [pending_implementation proposal_source=trial-review:file-3@test; user_decision=approved@test; implementation=N-A（等待公司側落地）] alpha' '- [proposal_source=trial-review:file-3@test; user_decision=approved@test; implementation=def456:path] alpha → landed')
run_transform "$FIX/company-pending.md" "$(digest_of "$FIX/company-pending.md")" "$landed_ops" --release-lock >/dev/null
if ! grep -q 'pending_implementation.*alpha' "$FIX/company-pending.md" && grep -q 'implementation=def456:path.*alpha' "$FIX/company-pending.md"; then pass 'pending 重新認領後取得 implementation 結案'; else fail 'pending 重新認領後取得 implementation 結案'; fi

RETIRE_FIXTURE="$HOME/Desktop/projects/.claude/hooks/fixtures/friction-retire/workflow-general.md"
RETIRE_FILE="$FIX/retire-boundary/workflow-general.md"
mkdir -p "$(dirname "$RETIRE_FILE")"
cp "$RETIRE_FIXTURE" "$RETIRE_FILE"
python3 - "$RETIRE_FILE" "$CLAIMED_AT" "$EXPIRES_AT" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
claimed_at, expires_at = sys.argv[2:]
lock = f'<!-- friction-review-lock:v1 session=test-session claimed_at={claimed_at} expires_at={expires_at} -->'
path.write_text(path.read_text().replace('LOCK_PLACEHOLDER', lock, 1))
PY
RETIRE_DIGEST=$(digest_of "$RETIRE_FILE")
if python3 "$HELPER" retire --file "$RETIRE_FILE" --archive-dir "$FIX/retire-boundary/archive" --session test-session --digest "$RETIRE_DIGEST" --older-than 90d --as-of 2026-08-23 >/dev/null 2>&1; then
  pass 'retire 90 天邊界 fixture 可執行'
  if [ -f "$FIX/retire-boundary/archive/2026-Q2.md" ] && grep -q -- '- 2026-05-24 older than 90 days' "$FIX/retire-boundary/archive/2026-Q2.md" && ! grep -q -- '- 2026-05-24 older than 90 days' "$RETIRE_FILE" && grep -q -- '- 2026-05-25 exactly 90 days' "$RETIRE_FILE"; then
    pass 'retire 只搬超過 90 天條目並保留第 90 天條目'
  else
    fail 'retire 只搬超過 90 天條目並保留第 90 天條目'
  fi
else
  fail 'retire 90 天邊界 fixture 可執行'
fi

SYMLINK_ROOT="$FIX/retire-archive-dir-symlink"
SYMLINK_FILE="$SYMLINK_ROOT/workflow-general.md"
SYMLINK_ARCHIVE="$SYMLINK_ROOT/archive"
SYMLINK_EXTERNAL="$FIX/external-archive-target"
mkdir -p "$(dirname "$SYMLINK_FILE")" "$SYMLINK_EXTERNAL"
cp "$RETIRE_FIXTURE" "$SYMLINK_FILE"
python3 - "$SYMLINK_FILE" "$CLAIMED_AT" "$EXPIRES_AT" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
claimed_at, expires_at = sys.argv[2:]
lock = f'<!-- friction-review-lock:v1 session=test-session claimed_at={claimed_at} expires_at={expires_at} -->'
path.write_text(path.read_text().replace('LOCK_PLACEHOLDER', lock, 1))
PY
ln -s "$SYMLINK_EXTERNAL" "$SYMLINK_ARCHIVE"
SYMLINK_DIGEST=$(digest_of "$SYMLINK_FILE")
SYMLINK_BEFORE=$(shasum -a 256 "$SYMLINK_FILE" | cut -d ' ' -f 1)
SYMLINK_STATUS=0
python3 "$HELPER" retire --file "$SYMLINK_FILE" --archive-dir "$SYMLINK_ARCHIVE" --session test-session --digest "$SYMLINK_DIGEST" --older-than 90d --as-of 2026-08-23 >/dev/null 2>&1 || SYMLINK_STATUS=$?
SYMLINK_AFTER=$(shasum -a 256 "$SYMLINK_FILE" | cut -d ' ' -f 1)
SYMLINK_EXTERNAL_LOCKS=$(find "$SYMLINK_EXTERNAL" -maxdepth 1 -type f -name '.*.friction-review.lock' -print)
if [ "$SYMLINK_STATUS" -ne 0 ] && [ "$SYMLINK_BEFORE" = "$SYMLINK_AFTER" ] && [ ! -e "$SYMLINK_EXTERNAL/2026-Q2.md" ] && [ -z "$SYMLINK_EXTERNAL_LOCKS" ]; then
  pass 'retire 拒絕 archive-dir symlink 且不寫入外部或主檔'
else
  fail 'retire 拒絕 archive-dir symlink 且不寫入外部或主檔'
fi

SEGMENT_FIXTURE_ROOT="$HOME/Desktop/projects/.claude/hooks/fixtures/friction-retire"
SEGMENT_FILE="$FIX/retire-segment/workflow-general.md"
SEGMENT_ARCHIVE="$FIX/retire-segment/archive"
mkdir -p "$(dirname "$SEGMENT_FILE")" "$SEGMENT_ARCHIVE"
cp "$SEGMENT_FIXTURE_ROOT/segment-boundary.md" "$SEGMENT_FILE"
cp -R "$SEGMENT_FIXTURE_ROOT/archive/." "$SEGMENT_ARCHIVE/"
python3 - "$SEGMENT_FILE" "$CLAIMED_AT" "$EXPIRES_AT" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
claimed_at, expires_at = sys.argv[2:]
lock = f'<!-- friction-review-lock:v1 session=test-session claimed_at={claimed_at} expires_at={expires_at} -->'
path.write_text(path.read_text().replace('LOCK_PLACEHOLDER', lock, 1))
PY
SEGMENT_DIGEST=$(digest_of "$SEGMENT_FILE")
if python3 "$HELPER" retire --file "$SEGMENT_FILE" --archive-dir "$SEGMENT_ARCHIVE" --session test-session --digest "$SEGMENT_DIGEST" --older-than 90d --as-of 2026-08-23 >/dev/null 2>&1; then
  pass 'retire 段界 fixture 可執行'
  if grep -q -- '- 2026-01-31 already archived' "$SEGMENT_ARCHIVE/2026-Q1.md" && grep -q -- '- 2026-02-14 old entry' "$SEGMENT_ARCHIVE/2026-Q1.md" && grep -q -- '### old detail' "$SEGMENT_ARCHIVE/2026-Q1.md" && grep -q -- '#### old deeper detail' "$SEGMENT_ARCHIVE/2026-Q1.md"; then
    pass 'retire append archive 並保留條目內 H3/H4'
  else
    fail 'retire append archive 並保留條目內 H3/H4'
  fi
  if ! grep -q -- '- 2026-02-14 old entry' "$SEGMENT_FILE" && grep -q -- '- 2026-05-25 exactly 90 days' "$SEGMENT_FILE" && grep -q -- '- 2026-08-22 recent entry' "$SEGMENT_FILE"; then
    pass 'retire 保留第 90 天與近期已折條目'
  else
    fail 'retire 保留第 90 天與近期已折條目'
  fi
  if grep -q '^## 後續同層$' "$SEGMENT_FILE" && grep -q -- '- 2020-01-01 sibling must remain' "$SEGMENT_FILE" && grep -q '^## 最後同層$' "$SEGMENT_FILE" && grep -q '^## 後續同層$' "$SEGMENT_FILE" && ! grep -q '^## 後續同層$' "$SEGMENT_ARCHIVE/2026-Q1.md"; then
    pass 'retire 只以同層 H2 為段界'
  else
    fail 'retire 只以同層 H2 為段界'
  fi
else
  fail 'retire 段界 fixture 可執行'
fi

LEGACY_FILE="$FIX/retire-legacy/workflow-general.md"
LEGACY_ARCHIVE="$FIX/retire-legacy/archive"
mkdir -p "$(dirname "$LEGACY_FILE")"
cp "$SEGMENT_FIXTURE_ROOT/segment-boundary.md" "$LEGACY_FILE"
python3 - "$LEGACY_FILE" "$CLAIMED_AT" "$EXPIRES_AT" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
claimed_at, expires_at = sys.argv[2:]
lock = f'<!-- friction-review-lock:v1 session=test-session claimed_at={claimed_at} expires_at={expires_at} -->'
text = path.read_text().replace('LOCK_PLACEHOLDER', lock, 1).replace('## 已折／已否決', '## 已折 / 已否決', 1)
path.write_text(text)
PY
LEGACY_DIGEST=$(digest_of "$LEGACY_FILE")
if python3 "$HELPER" retire --file "$LEGACY_FILE" --archive-dir "$LEGACY_ARCHIVE" --session test-session --digest "$LEGACY_DIGEST" --older-than 90d --as-of 2026-08-23 >/dev/null 2>&1 && grep -q '^## 已折／已否決$' "$LEGACY_FILE" && ! grep -q '^## 已折 / 已否決$' "$LEGACY_FILE"; then
  pass 'retire 正規化舊式已折標題'
else
  fail 'retire 正規化舊式已折標題'
fi

TX_FILE="$FIX/retire-transaction/workflow-general.md"
TX_ARCHIVE="$FIX/retire-transaction/archive"
TX_RESULT="$FIX/retire-transaction/result"
mkdir -p "$(dirname "$TX_FILE")"
cp "$SEGMENT_FIXTURE_ROOT/segment-boundary.md" "$TX_FILE"
python3 - "$TX_FILE" "$CLAIMED_AT" "$EXPIRES_AT" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
claimed_at, expires_at = sys.argv[2:]
lock = f'<!-- friction-review-lock:v1 session=test-session claimed_at={claimed_at} expires_at={expires_at} -->'
path.write_text(path.read_text().replace('LOCK_PLACEHOLDER', lock, 1))
PY
TX_DIGEST=$(digest_of "$TX_FILE")
TX_BEFORE=$(shasum -a 256 "$TX_FILE" | cut -d ' ' -f 1)
python3 - "$HELPER" "$TX_FILE" "$TX_ARCHIVE" "$TX_DIGEST" "$TX_RESULT" <<'PY'
from datetime import date, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
helper, source_name, archive_name, digest, result_name = sys.argv[1:]
spec = spec_from_file_location('friction_review_state_transaction_test', helper)
module = module_from_spec(spec)
spec.loader.exec_module(module)
source = Path(source_name).resolve()
real_replace = module.os.replace
def fail_source(temp_path, target_path):
  if Path(target_path).resolve() == source:
    raise OSError('injected source replace failure')
  return real_replace(temp_path, target_path)
module.os.replace = fail_source
try:
  module.retire(source, 'test-session', digest, Path(archive_name), timedelta(days=90), date(2026, 8, 23))
except OSError as error:
  Path(result_name).write_text(f'expected-failure:{error}')
else:
  Path(result_name).write_text('unexpected-success')
PY
TX_AFTER=$(shasum -a 256 "$TX_FILE" | cut -d ' ' -f 1)
if grep -q '^expected-failure:injected source replace failure$' "$TX_RESULT" && [ "$TX_BEFORE" = "$TX_AFTER" ] && [ ! -e "$TX_ARCHIVE/2026-Q1.md" ] && grep -q -- '- 2026-02-14 old entry' "$TX_FILE" && grep -q 'friction-review-lock:v1' "$TX_FILE"; then
  pass 'retire 交易失敗會回復 archive、主檔與鎖'
else
  fail 'retire 交易失敗會回復 archive、主檔與鎖'
fi

TX2_FILE="$FIX/retire-archive-failure/workflow-general.md"
TX2_ARCHIVE="$FIX/retire-archive-failure/archive"
TX2_RESULT="$FIX/retire-archive-failure/result"
mkdir -p "$(dirname "$TX2_FILE")" "$TX2_ARCHIVE"
cp "$SEGMENT_FIXTURE_ROOT/segment-boundary.md" "$TX2_FILE"
cp "$SEGMENT_FIXTURE_ROOT/archive/2026-Q1.md" "$TX2_ARCHIVE/2026-Q1.md"
python3 - "$TX2_FILE" "$CLAIMED_AT" "$EXPIRES_AT" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
claimed_at, expires_at = sys.argv[2:]
lock = f'<!-- friction-review-lock:v1 session=test-session claimed_at={claimed_at} expires_at={expires_at} -->'
text = path.read_text().replace('LOCK_PLACEHOLDER', lock, 1)
text = text.replace('- 2026-02-14 old entry\n', '- 2026-04-30 old Q2 entry\n- 2026-02-14 old entry\n', 1)
path.write_text(text)
PY
TX2_DIGEST=$(digest_of "$TX2_FILE")
TX2_Q1_BEFORE=$(shasum -a 256 "$TX2_ARCHIVE/2026-Q1.md" | cut -d ' ' -f 1)
python3 - "$HELPER" "$TX2_FILE" "$TX2_ARCHIVE" "$TX2_DIGEST" "$TX2_RESULT" <<'PY'
from datetime import date, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
helper, source_name, archive_name, digest, result_name = sys.argv[1:]
spec = spec_from_file_location('friction_review_state_archive_failure_test', helper)
module = module_from_spec(spec)
spec.loader.exec_module(module)
fail_target = (Path(archive_name) / '2026-Q2.md').resolve()
real_replace = module.os.replace
def fail_archive(temp_path, target_path):
  if Path(target_path).resolve() == fail_target:
    raise OSError('injected archive replace failure')
  return real_replace(temp_path, target_path)
module.os.replace = fail_archive
try:
  module.retire(Path(source_name).resolve(), 'test-session', digest, Path(archive_name), timedelta(days=90), date(2026, 8, 23))
except OSError as error:
  Path(result_name).write_text(f'expected-failure:{error}')
else:
  Path(result_name).write_text('unexpected-success')
PY
TX2_Q1_AFTER=$(shasum -a 256 "$TX2_ARCHIVE/2026-Q1.md" | cut -d ' ' -f 1)
TX2_TMP_COUNT=$(find "$TX2_ARCHIVE" -maxdepth 1 -type f -name '.*.retire-*' | wc -l | tr -d ' ')
if grep -q '^expected-failure:injected archive replace failure$' "$TX2_RESULT" && [ "$TX2_Q1_BEFORE" = "$TX2_Q1_AFTER" ] && [ ! -e "$TX2_ARCHIVE/2026-Q2.md" ] && [ "$TX2_TMP_COUNT" = 0 ] && grep -q -- '- 2026-04-30 old Q2 entry' "$TX2_FILE" && grep -q 'friction-review-lock:v1' "$TX2_FILE"; then
  pass 'retire archive 交易失敗會清理暫存檔並回復'
else
  fail 'retire archive 交易失敗會清理暫存檔並回復'
fi

PERM_FILE="$FIX/retire-permissions/workflow-general.md"
PERM_ARCHIVE="$FIX/retire-permissions/archive"
mkdir -p "$(dirname "$PERM_FILE")"
cp "$SEGMENT_FIXTURE_ROOT/workflow-general.md" "$PERM_FILE"
chmod 640 "$PERM_FILE"
python3 - "$PERM_FILE" "$CLAIMED_AT" "$EXPIRES_AT" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
claimed_at, expires_at = sys.argv[2:]
lock = f'<!-- friction-review-lock:v1 session=test-session claimed_at={claimed_at} expires_at={expires_at} -->'
path.write_text(path.read_text().replace('LOCK_PLACEHOLDER', lock, 1))
PY
PERM_DIGEST=$(digest_of "$PERM_FILE")
PERM_BEFORE=$(stat -f '%Lp' "$PERM_FILE")
if python3 "$HELPER" retire --file "$PERM_FILE" --archive-dir "$PERM_ARCHIVE" --session test-session --digest "$PERM_DIGEST" --older-than 90d --as-of 2026-08-23 >/dev/null 2>&1 && [ "$PERM_BEFORE" = "$(stat -f '%Lp' "$PERM_FILE")" ]; then
  pass 'retire 保留主檔權限'
else
  fail 'retire 保留主檔權限'
fi

LOCK_SKIP_FILE="$FIX/retire-lock-skip/workflow-general.md"
LOCK_SKIP_ARCHIVE="$FIX/retire-lock-skip/archive"
mkdir -p "$(dirname "$LOCK_SKIP_FILE")"
cp "$SEGMENT_FIXTURE_ROOT/workflow-general.md" "$LOCK_SKIP_FILE"
python3 - "$LOCK_SKIP_FILE" "$CLAIMED_AT" "$EXPIRES_AT" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
claimed_at, expires_at = sys.argv[2:]
lock = f'<!-- friction-review-lock:v1 session=other-session claimed_at={claimed_at} expires_at={expires_at} -->'
path.write_text(path.read_text().replace('LOCK_PLACEHOLDER', lock, 1))
PY
LOCK_SKIP_DIGEST=$(digest_of "$LOCK_SKIP_FILE")
LOCK_SKIP_BEFORE=$(shasum -a 256 "$LOCK_SKIP_FILE" | cut -d ' ' -f 1)
LOCK_SKIP_OUTPUT=$(python3 "$HELPER" retire --file "$LOCK_SKIP_FILE" --archive-dir "$LOCK_SKIP_ARCHIVE" --session test-session --digest "$LOCK_SKIP_DIGEST" --older-than 90d --as-of 2026-08-23 2>&1)
LOCK_SKIP_AFTER=$(shasum -a 256 "$LOCK_SKIP_FILE" | cut -d ' ' -f 1)
if printf '%s' "$LOCK_SKIP_OUTPUT" | grep -q '^SKIPPED lock-active$' && [ "$LOCK_SKIP_BEFORE" = "$LOCK_SKIP_AFTER" ] && [ ! -e "$LOCK_SKIP_ARCHIVE" ]; then
  pass 'retire 遇未到期他人鎖會跳過且不寫入'
else
  fail 'retire 遇未到期他人鎖會跳過且不寫入'
fi

RACE_ROOT="$FIX/retire-cross-source"
RACE_ARCHIVE="$RACE_ROOT/archive"
RACE_A="$RACE_ROOT/source-a.md"
RACE_B="$RACE_ROOT/source-b.md"
RACE_ENTER_A="$RACE_ROOT/entered-a"
RACE_ENTER_B="$RACE_ROOT/entered-b"
RACE_GO_A="$RACE_ROOT/go-a"
RACE_GO_B="$RACE_ROOT/go-b"
RACE_LOG_A="$RACE_ROOT/result-a"
RACE_LOG_B="$RACE_ROOT/result-b"
mkdir -p "$RACE_ROOT"
cp "$SEGMENT_FIXTURE_ROOT/workflow-general.md" "$RACE_A"
cp "$SEGMENT_FIXTURE_ROOT/workflow-general.md" "$RACE_B"
python3 - "$RACE_A" "$RACE_B" "$CLAIMED_AT" "$EXPIRES_AT" <<'PY'
from pathlib import Path
import sys
source_a, source_b = Path(sys.argv[1]), Path(sys.argv[2])
claimed_at, expires_at = sys.argv[3:]
for path, session, label in ((source_a, 'race-a', 'source A'), (source_b, 'race-b', 'source B')):
  lock = f'<!-- friction-review-lock:v1 session={session} claimed_at={claimed_at} expires_at={expires_at} -->'
  text = path.read_text().replace('LOCK_PLACEHOLDER', lock, 1).replace('older than 90 days', label, 1)
  path.write_text(text)
PY
RACE_DIGEST_A=$(digest_of "$RACE_A")
RACE_DIGEST_B=$(digest_of "$RACE_B")
python3 - "$HELPER" "$RACE_A" "$RACE_ARCHIVE" "$RACE_DIGEST_A" "$RACE_ENTER_A" "$RACE_GO_A" "$RACE_LOG_A" race-a <<'PY' &
from datetime import date, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import json
import sys
import time
helper, source_name, archive_name, digest, entered_name, go_name, result_name, session = sys.argv[1:]
spec = spec_from_file_location('friction_review_state_race_a', helper)
module = module_from_spec(spec)
spec.loader.exec_module(module)
real_apply = module.apply_retire_transaction
entered = Path(entered_name)
go = Path(go_name)
def paused(*args):
  entered.write_text('entered')
  for _ in range(5000):
    if go.exists():
      return real_apply(*args)
    time.sleep(0.001)
  raise RuntimeError('race-release-timeout')
module.apply_retire_transaction = paused
try:
  receipt = module.retire(Path(source_name), session, digest, Path(archive_name), timedelta(days=90), date(2026, 8, 23))
  Path(result_name).write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
except Exception as error:
  Path(result_name).write_text(f'ERROR:{type(error).__name__}:{error}')
  raise
PY
RACE_PID_A=$!
python3 - "$HELPER" "$RACE_B" "$RACE_ARCHIVE" "$RACE_DIGEST_B" "$RACE_ENTER_B" "$RACE_GO_B" "$RACE_LOG_B" race-b <<'PY' &
from datetime import date, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import json
import sys
import time
helper, source_name, archive_name, digest, entered_name, go_name, result_name, session = sys.argv[1:]
spec = spec_from_file_location('friction_review_state_race_b', helper)
module = module_from_spec(spec)
spec.loader.exec_module(module)
real_apply = module.apply_retire_transaction
entered = Path(entered_name)
go = Path(go_name)
def paused(*args):
  entered.write_text('entered')
  for _ in range(5000):
    if go.exists():
      return real_apply(*args)
    time.sleep(0.001)
  raise RuntimeError('race-release-timeout')
module.apply_retire_transaction = paused
try:
  receipt = module.retire(Path(source_name), session, digest, Path(archive_name), timedelta(days=90), date(2026, 8, 23))
  Path(result_name).write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
except Exception as error:
  Path(result_name).write_text(f'ERROR:{type(error).__name__}:{error}')
  raise
PY
RACE_PID_B=$!
for _ in $(seq 1 1000); do
  [ -f "$RACE_ENTER_A" ] && [ -f "$RACE_GO_A" ] || { [ -f "$RACE_ENTER_A" ] && touch "$RACE_GO_A"; }
  [ -f "$RACE_ENTER_B" ] && [ -f "$RACE_GO_B" ] || { [ -f "$RACE_ENTER_B" ] && touch "$RACE_GO_B"; }
  [ -f "$RACE_LOG_A" ] && [ -f "$RACE_LOG_B" ] && break
  sleep 0.01
done
touch "$RACE_GO_A" "$RACE_GO_B"
RACE_STATUS_A=0; wait "$RACE_PID_A" || RACE_STATUS_A=$?
RACE_STATUS_B=0; wait "$RACE_PID_B" || RACE_STATUS_B=$?
RACE_ARCHIVE_FILE="$RACE_ARCHIVE/2026-Q2.md"
RACE_A_COUNT=0; [ -f "$RACE_ARCHIVE_FILE" ] && RACE_A_COUNT=$(grep -c -- '- 2026-05-24 source A' "$RACE_ARCHIVE_FILE")
RACE_B_COUNT=0; [ -f "$RACE_ARCHIVE_FILE" ] && RACE_B_COUNT=$(grep -c -- '- 2026-05-24 source B' "$RACE_ARCHIVE_FILE")
if [ "$RACE_STATUS_A" -eq 0 ] && [ "$RACE_STATUS_B" -eq 0 ] && grep -q '"status": "retired"' "$RACE_LOG_A" && grep -q '"status": "retired"' "$RACE_LOG_B" && [ "$RACE_A_COUNT" = 1 ] && [ "$RACE_B_COUNT" = 1 ] && ! grep -q -- '- 2026-05-24 source A' "$RACE_A" && ! grep -q -- '- 2026-05-24 source B' "$RACE_B"; then
  pass 'retire 穩定 lock 保留跨 source 的兩筆 archive'
else
  fail 'retire 穩定 lock 保留跨 source 的兩筆 archive'
fi

make_fixture "$FIX/concurrent.md"
SIGNAL="$FIX/write-ready"
operations=$(op_json approved '- alpha' '- [proposal_source=trial-review:file-3@test; user_decision=approved@test; implementation=abc123:path] alpha → landed')
python3 "$HELPER" transform --file "$FIX/concurrent.md" --session test-session --digest "$(digest_of "$FIX/concurrent.md")" --operations "$operations" --release-lock --before-write-signal "$SIGNAL" > "$FIX/concurrent.out" 2>&1 &
PID=$!
for _ in $(seq 1 200); do [ -f "$SIGNAL" ] && break; sleep 0.01; done
printf '%s\n' '- external update' >> "$FIX/concurrent.md"
touch "${SIGNAL}.ack"
if wait "$PID"; then
  fail '驗證後外部更新會阻止寫入'
elif grep -q -- '- external update' "$FIX/concurrent.md" && grep -q -- '- alpha' "$FIX/concurrent.md"; then
  pass '驗證後外部更新會阻止寫入'
else
  fail '驗證後外部更新會阻止寫入'
fi

make_fixture "$FIX/lock-only.md"
LOCK_ONLY_DIGEST=$(digest_of "$FIX/lock-only.md")
if run_transform "$FIX/lock-only.md" "$LOCK_ONLY_DIGEST" '[]' --release-lock >/dev/null 2>&1; then
  if ! grep -q 'friction-review-lock:v1' "$FIX/lock-only.md" \
    && grep -q -- '- alpha' "$FIX/lock-only.md" \
    && grep -q -- '- beta' "$FIX/lock-only.md" \
    && grep -q -- '- old' "$FIX/lock-only.md" \
    && [ "$(digest_of "$FIX/lock-only.md")" = "$LOCK_ONLY_DIGEST" ]; then
    pass '全項保留待折時可只釋放鎖、待折內容與 digest 不變'
  else
    fail '全項保留待折時可只釋放鎖、待折內容與 digest 不變'
  fi
else
  fail '全項保留待折時可只釋放鎖、待折內容與 digest 不變'
fi

make_fixture "$FIX/lock-only-noflag.md"
if run_transform "$FIX/lock-only-noflag.md" "$(digest_of "$FIX/lock-only-noflag.md")" '[]' >/dev/null 2>&1; then
  fail '空 operations 且未要求釋放鎖仍被拒絕'
elif grep -q 'friction-review-lock:v1' "$FIX/lock-only-noflag.md"; then
  pass '空 operations 且未要求釋放鎖仍被拒絕'
else
  fail '空 operations 且未要求釋放鎖仍被拒絕'
fi

cp "$FIX/lock-only-noflag.md" "$FIX/lock-only-other-owner.md"
python3 - "$FIX/lock-only-other-owner.md" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
p.write_text(p.read_text().replace('session=test-session', 'session=other-session'))
PY
if run_transform "$FIX/lock-only-other-owner.md" "$(digest_of "$FIX/lock-only-other-owner.md")" '[]' --release-lock >/dev/null 2>&1; then
  fail '只釋放鎖仍須通過 owner 驗證'
elif grep -q 'session=other-session' "$FIX/lock-only-other-owner.md"; then
  pass '只釋放鎖仍須通過 owner 驗證'
else
  fail '只釋放鎖仍須通過 owner 驗證'
fi

SPACED="$FIX/spaced-items.md"
mkdir -p "$(dirname "$SPACED")"
printf '# fixture\n\n## 待折\n%s\n\n- alpha\n\n- beta\n\n- gamma\n\n## 已折／已否決\n\n- old\n' "$VALID_LOCK" > "$SPACED"
max_blank_run() {
  awk '/^## 待折$/{flag=1;next}flag&&/^## /{exit}flag{if($0==""){n++;if(n>m)m=n}else n=0}END{print m+0}' "$1"
}
spaced_ops=$(op_json rejected '- beta' '- 2026-09-09 [proposal_source=trial-review:file-3@s; user_decision=rejected@t; implementation=N-A] beta')
if run_transform "$SPACED" "$(digest_of "$SPACED")" "$spaced_ops" --release-lock >/dev/null; then
  SPACED_RUN=$(max_blank_run "$SPACED")
  SPACED_ITEMS=$(awk '/^## 待折$/{flag=1;next}flag&&/^## /{exit}flag&&/^- /' "$SPACED" | tr '\n' ' ')
  if [ "$SPACED_RUN" -le 1 ] && [ "$SPACED_ITEMS" = '- alpha - gamma ' ]; then
    pass '搬走空行分隔的條目不留連續空行'
  else
    fail "搬走空行分隔的條目不留連續空行（最長空行串=$SPACED_RUN 剩餘=$SPACED_ITEMS）"
  fi
else
  fail '搬走空行分隔的條目不留連續空行'
fi

SPACED_KEEP="$FIX/spaced-items-keep.md"
mkdir -p "$(dirname "$SPACED_KEEP")"
printf '# fixture\n\n## 待折\n%s\n\n- alpha\n\n\n\n- beta\n\n## 已折／已否決\n\n- old\n' "$VALID_LOCK" > "$SPACED_KEEP"
keep_ops=$(op_json rejected '- beta' '- 2026-09-09 [proposal_source=trial-review:file-3@s; user_decision=rejected@t; implementation=N-A] beta')
if run_transform "$SPACED_KEEP" "$(digest_of "$SPACED_KEEP")" "$keep_ops" --release-lock >/dev/null; then
  KEEP_RUN=$(max_blank_run "$SPACED_KEEP")
  if [ "$KEEP_RUN" -ge 3 ]; then
    pass '既有的多行空白不被搬遷順手壓掉'
  else
    fail "既有的多行空白不被搬遷順手壓掉（最長空行串=$KEEP_RUN 期望 >=3）"
  fi
else
  fail '既有的多行空白不被搬遷順手壓掉'
fi

for EDGE in first last; do
  EDGE_FILE="$FIX/spaced-edge-$EDGE.md"
  mkdir -p "$(dirname "$EDGE_FILE")"
  printf '# fixture\n\n## 待折\n%s\n\n- alpha\n\n- beta\n\n## 已折／已否決\n\n- old\n' "$VALID_LOCK" > "$EDGE_FILE"
  [ "$EDGE" = first ] && TARGET='- alpha' || TARGET='- beta'
  [ "$EDGE" = first ] && SURVIVOR='- beta' || SURVIVOR='- alpha'
  edge_ops=$(op_json rejected "$TARGET" "- 2026-09-09 [proposal_source=trial-review:file-3@s; user_decision=rejected@t; implementation=N-A] ${TARGET#- }")
  if run_transform "$EDGE_FILE" "$(digest_of "$EDGE_FILE")" "$edge_ops" --release-lock >/dev/null 2>&1; then
    EDGE_RUN=$(max_blank_run "$EDGE_FILE")
    EDGE_ITEMS=$(awk '/^## 待折$/{flag=1;next}flag&&/^## /{exit}flag&&/^- /' "$EDGE_FILE" | tr '\n' ' ')
    if [ "$EDGE_RUN" -le 1 ] && [ "$EDGE_ITEMS" = "$SURVIVOR " ]; then
      pass "搬走待折段${EDGE}項不越界且不留連續空行"
    else
      fail "搬走待折段${EDGE}項不越界且不留連續空行（最長空行串=$EDGE_RUN 剩餘=$EDGE_ITEMS）"
    fi
  else
    fail "搬走待折段${EDGE}項不越界且不留連續空行（transform 失敗）"
  fi
done

closed_blank_run() {
  awk '/^## 已折／已否決$/{flag=1;next}flag&&/^## /{exit}flag{if($0==""){n++;if(n>m)m=n}else n=0}END{print m+0}' "$1"
}
run_tidy() {
  local file="$1"
  local digest="$2"
  shift 2
  python3 "$HELPER" tidy --file "$file" --session test-session --digest "$digest" "$@"
}
make_tidy_fixture() {
  local file="$1"
  local lock="${2:-$VALID_LOCK}"
  mkdir -p "$(dirname "$file")"
  printf '# fixture\n\n## 待折\n%s\n\n\n- alpha\n\n\n\n- beta\n\n## 已折／已否決\n\n\n- old\n' "$lock" > "$file"
}

TIDY="$FIX/tidy.md"
make_tidy_fixture "$TIDY"
if run_tidy "$TIDY" "$(digest_of "$TIDY")" --release-lock >/dev/null; then
  TIDY_RUN=$(max_blank_run "$TIDY")
  TIDY_CLOSED=$(closed_blank_run "$TIDY")
  TIDY_ITEMS=$(awk '/^## 待折$/{flag=1;next}flag&&/^## /{exit}flag&&/^- /' "$TIDY" | tr '\n' ' ')
  TIDY_LOCKS=$(grep -c 'friction-review-lock:v1' "$TIDY")
  if [ "$TIDY_RUN" -le 1 ] && [ "$TIDY_ITEMS" = '- alpha - beta ' ] && [ "$TIDY_LOCKS" -eq 0 ]; then
    pass 'tidy 把待折段連續空行壓成一行並保留全部條目'
  else
    fail "tidy 把待折段連續空行壓成一行並保留全部條目（空行串=$TIDY_RUN 條目=$TIDY_ITEMS marker=$TIDY_LOCKS）"
  fi
  if [ "$TIDY_CLOSED" -ge 2 ]; then
    pass 'tidy 不動已折段的空行'
  else
    fail "tidy 不動已折段的空行（已折段空行串=$TIDY_CLOSED 期望 >=2）"
  fi
else
  fail 'tidy 把待折段連續空行壓成一行並保留全部條目'
  fail 'tidy 不動已折段的空行'
fi

TIDY_OTHER="$FIX/tidy-other-owner.md"
make_tidy_fixture "$TIDY_OTHER"
TIDY_OTHER_DIGEST=$(digest_of "$TIDY_OTHER")
python3 - "$TIDY_OTHER" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
p.write_text(p.read_text().replace('session=test-session', 'session=other-session'))
PY
if run_tidy "$TIDY_OTHER" "$TIDY_OTHER_DIGEST" --release-lock >/dev/null 2>&1; then
  fail 'tidy 仍須通過 owner 驗證'
elif grep -q 'session=other-session' "$TIDY_OTHER" && [ "$(max_blank_run "$TIDY_OTHER")" -ge 2 ]; then
  pass 'tidy 仍須通過 owner 驗證'
else
  fail 'tidy 仍須通過 owner 驗證'
fi

TIDY_NOLOCK="$FIX/tidy-no-release.md"
make_tidy_fixture "$TIDY_NOLOCK"
if run_tidy "$TIDY_NOLOCK" "$(digest_of "$TIDY_NOLOCK")" >/dev/null 2>&1; then
  fail 'tidy 未要求釋放鎖仍被拒絕'
elif [ "$(max_blank_run "$TIDY_NOLOCK")" -ge 2 ]; then
  pass 'tidy 未要求釋放鎖仍被拒絕'
else
  fail 'tidy 未要求釋放鎖仍被拒絕'
fi

# === dormant action（2026-09-12）===
# 四件：休眠段已存在時搬入 / 休眠段缺席時就地建立 / 格式不合拒絕 / 夾帶處置欄位拒絕
DORM_OK='- alpha [dormant since=2026-09-12; wake-when=等可重現案例]'

# 1. 休眠段已存在
D1="$FIX/dormant-existing.md"
mkdir -p "$(dirname "$D1")"
printf '# fixture\n\n## 待折\n%s\n- alpha\n- beta\n\n## 休眠\n\n## 已折／已否決\n\n- old\n' "$VALID_LOCK" > "$D1"
if run_transform "$D1" "$(digest_of "$D1")" "$(op_json dormant '- alpha' "$DORM_OK")" --release-lock >/dev/null 2>&1; then
  if command grep -q '^- alpha \[dormant since=' "$D1" && ! awk '/^## 待折$/{f=1;next}f&&/^## /{f=0}f' "$D1" | command grep -q '^- alpha'; then
    pass 'dormant：項目搬進休眠段且離開待折段'
  else
    fail 'dormant：搬遷位置不正確'
  fi
else
  fail 'dormant：休眠段已存在時 transform 應成功'
fi

# 2. 休眠段缺席 → 就地建立，且仍夾在待折與已折之間
D2="$FIX/dormant-missing.md"
printf '# fixture\n\n## 待折\n%s\n- alpha\n- beta\n\n## 已折／已否決\n\n- old\n' "$VALID_LOCK" > "$D2"
if run_transform "$D2" "$(digest_of "$D2")" "$(op_json dormant '- alpha' "$DORM_OK")" --release-lock >/dev/null 2>&1; then
  ORDER=$(command grep -n '^## ' "$D2" | awk -F: '{printf "%s ", $2}')
  if [ "$ORDER" = "## 待折 ## 休眠 ## 已折／已否決 " ]; then
    pass 'dormant：休眠段缺席時就地建立且順序正確'
  else
    fail "dormant：段落順序不對（實得 '$ORDER'）"
  fi
else
  fail 'dormant：休眠段缺席時 transform 應成功'
fi

# 3. receipt 缺 wake-when → 拒絕
D3="$FIX/dormant-badfmt.md"
printf '# fixture\n\n## 待折\n%s\n- alpha\n- beta\n\n## 已折／已否決\n\n- old\n' "$VALID_LOCK" > "$D3"
if run_transform "$D3" "$(digest_of "$D3")" "$(op_json dormant '- alpha' '- alpha [dormant since=2026-09-12]')" --release-lock >/dev/null 2>&1; then
  fail 'dormant：缺 wake-when 應被拒絕'
else
  pass 'dormant：缺 wake-when 被拒絕'
fi

# 4. 形狀合法但夾帶處置欄位 → 拒絕（休眠不是處置，混進去會被誤計為已折入）
D4="$FIX/dormant-disposition.md"
printf '# fixture\n\n## 待折\n%s\n- alpha user_decision=approved@x\n- beta\n\n## 已折／已否決\n\n- old\n' "$VALID_LOCK" > "$D4"
if run_transform "$D4" "$(digest_of "$D4")" "$(op_json dormant '- alpha user_decision=approved@x' '- alpha user_decision=approved@x [dormant since=2026-09-12; wake-when=y]')" --release-lock >/dev/null 2>&1; then
  fail 'dormant：夾帶 user_decision 應被拒絕'
else
  pass 'dormant：夾帶處置欄位被拒絕'
fi

# 條目內文引用鎖字樣（例如 session 原文在討論這個機制）不是鎖；只有以 marker 開頭的行才算
QUOTED="$FIX/quoted-marker.md"
printf '# fixture\n\n## 待折\n%s\n- alpha feedback_quote="寫 <!-- friction-review-lock:v1 session=x --> 到待折"\n- beta\n\n## 已折／已否決\n\n- old 提到 friction-review-lock: 字樣\n' "$VALID_LOCK" > "$QUOTED"
if validate "$QUOTED" "$(digest_of "$QUOTED")"; then pass '條目內文引用鎖字樣不算鎖'; else fail '條目內文引用鎖字樣不算鎖'; fi
if run_transform "$QUOTED" "$(digest_of "$QUOTED")" "$(op_json dormant '- beta' '- beta [dormant since=2026-10-08; wake-when=y]')" --release-lock >/dev/null 2>&1 \
  && ! grep -q '^<!-- friction-review-lock:' "$QUOTED" && grep -q 'feedback_quote="寫 <!-- friction-review-lock' "$QUOTED"; then
  pass '條目內文引用鎖字樣時可正常搬移並釋放鎖'
else
  fail '條目內文引用鎖字樣時可正常搬移並釋放鎖'
fi

printf '%s\n' '----'
printf 'PASS=%s FAIL=%s\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
