#!/usr/bin/env bash
set -u

SCRIPT="${ACTIVE_MIGRATION_SCRIPT:-/Users/you/.claude/scripts/ledger-lifecycle/migrate-active.py}"
TMP=$(mktemp -d /tmp/migrate-active-test.XXXXXX)
trap 'rm -rf "$TMP"' EXIT
PASS=0
FAIL=0

ok() {
  printf 'PASS: %s\n' "$1"
  PASS=$((PASS + 1))
}
fail() {
  printf 'FAIL: %s\n' "$1"
  FAIL=$((FAIL + 1))
}

ACTIVE="$TMP/active.md"
DETAILS="$TMP/active"
printf '%s\n' \
  '# Active Trials' \
  '' \
  '## same-trial (2099-01-01 review date)' \
  '- start: 2026-08-20' \
  '- status: active' \
  '- note: first' \
  '' \
  '## same-trial (2099-01-02 review date)' \
  '- Started: 2026-08-21 01:02:03' \
  '- state: active' \
  '- note: second' \
  '' \
  '## suffix-trial (2099-01-03 review date｜round 2)' \
  '- candidate start: 2026-08-22' \
  '- note: suffix' \
  > "$ACTIVE"

OUTPUT="$TMP/migrate.log"
if python3 "$SCRIPT" --active "$ACTIVE" --details-dir "$DETAILS" --apply > "$OUTPUT" 2>&1; then
  ok 'migration fixture executes'
else
  fail 'migration fixture executes'
fi

if grep -q '^## same-trial (2099-01-01 review date)' "$ACTIVE" && grep -q '^## same-trial \[run-2\] (2099-01-02 review date)' "$ACTIVE"; then
  ok 'same-name entries remain separate with explicit suffix'
else
  fail 'same-name entries were merged or lost'
fi

if [ "$(find "$DETAILS" -maxdepth 1 -type f -name '*.md' | wc -l | tr -d ' ')" = '3' ]; then
  ok 'each legacy entry gets its own detail file'
else
  fail 'legacy entries did not get three detail files'
fi

if grep -R -q 'note: first' "$DETAILS" && grep -R -q 'note: second' "$DETAILS" && grep -R -q 'note: suffix' "$DETAILS"; then
  ok 'detail files retain legacy content'
else
  fail 'detail files lost legacy content'
fi

if [ "$(grep -R -h 'detail-key: active/' "$DETAILS" | wc -l | tr -d ' ')" = '3' ]; then
  ok 'detail files carry stable identity markers'
else
  fail 'detail files lack stable identity markers'
fi

cp "$ACTIVE" "$TMP/active-before.md"
INODE_BEFORE=$(stat -f '%i' "$ACTIVE")
if python3 "$SCRIPT" --active "$ACTIVE" --details-dir "$DETAILS" --apply > "$TMP/rerun.log" 2>&1; then
  INODE_AFTER=$(stat -f '%i' "$ACTIVE")
  if cmp -s "$TMP/active-before.md" "$ACTIVE" && [ "$INODE_BEFORE" = "$INODE_AFTER" ]; then
    ok 'migration rerun is a filesystem no-op'
  else
    fail 'migration rerun replaced unchanged active index'
  fi
else
  fail 'migration rerun failed'
fi

if grep -q '^## suffix-trial (2099-01-03 review date｜round 2)' "$ACTIVE"; then
  ok 'H2 trailing suffix survives migration'
else
  fail 'H2 trailing suffix was rewritten incorrectly'
fi

POINTER_COUNT=$(grep -oE 'active/[^`]+\.md' "$ACTIVE" | sort -u | wc -l | tr -d ' ')
if [ "$POINTER_COUNT" = "3" ] && while IFS= read -r pointer; do [ -f "$DETAILS/${pointer#active/}" ] || exit 1; done < <(grep -oE 'active/[^`]+\.md' "$ACTIVE" | sort -u); then
  ok 'each index pointer maps to a detail file'
else
  fail 'index pointers do not map to detail files'
fi

CUSTOM_ACTIVE="$TMP/custom.md"
CUSTOM_DETAILS="$TMP/custom-details"
printf '%s\n' '# Active Trials' '## custom-trial (2099-01-05)' '- start: 2026-08-23' '- note: custom root' > "$CUSTOM_ACTIVE"
if python3 "$SCRIPT" --active "$CUSTOM_ACTIVE" --details-dir "$CUSTOM_DETAILS" --apply > "$TMP/custom.log" 2>&1 && [ -f "$CUSTOM_DETAILS/custom-trial-2026-08-23.md" ] && python3 "$SCRIPT" --active "$CUSTOM_ACTIVE" --details-dir "$CUSTOM_DETAILS" --apply > "$TMP/custom-rerun.log" 2>&1; then
  ok 'custom detail root reruns cleanly'
else
  fail 'custom detail root did not rerun cleanly'
fi

COLLISION_ACTIVE="$TMP/collision.md"
COLLISION_DETAILS="$TMP/collision-details"
printf '%s\n' '# Active Trials' '## alpha (2099-01-06)' '- start: 2026-08-24' '- note: one' '' '## alpha (2099-01-07)' '- start: 2026-08-25' '- note: two' '' '## alpha-2 (2099-01-08)' '- start: 2026-08-26' '- note: three' > "$COLLISION_ACTIVE"
if python3 "$SCRIPT" --active "$COLLISION_ACTIVE" --details-dir "$COLLISION_DETAILS" --apply > "$TMP/collision.log" 2>&1 && [ "$(find "$COLLISION_DETAILS" -maxdepth 1 -type f -name '*.md' | wc -l | tr -d ' ')" = '3' ]; then
  ok 'slug collisions keep every detail file'
else
  fail 'slug collisions lost a detail file'
fi

INTERNAL_ACTIVE="$TMP/internal.md"
printf '%s\n' '# Active Trials' '## outer (2099-01-09)' '- start: 2026-08-27' '- note: outer' '## internal note (2099-01-10)' '- note: nested date-shaped heading' > "$INTERNAL_ACTIVE"
if python3 "$SCRIPT" --active "$INTERNAL_ACTIVE" --details-dir "$TMP/internal-details" --apply > "$TMP/internal.log" 2>&1; then
  fail 'date-shaped internal H2 was treated as a trial'
else
  if grep -q 'unclassified-h2:## internal note' "$TMP/internal.log"; then
    ok 'date-shaped internal H2 is not silently split'
  else
    fail 'internal H2 failure lacked explicit diagnostic'
  fi
fi

BAD_ACTIVE="$TMP/bad-path.md"
printf '%s\n' '# Active Trials' '## bad-path (2099-01-11)' '- started: 2026-08-28' '- status: active' '- detail: `active/../outside.md`' > "$BAD_ACTIVE"
if python3 "$SCRIPT" --active "$BAD_ACTIVE" --details-dir "$TMP/bad-details" > "$TMP/bad.log" 2>&1; then
  fail 'detail path traversal was accepted'
else
  if grep -q 'detail-path-invalid' "$TMP/bad.log"; then
    ok 'detail path traversal is rejected'
  else
    fail 'detail path traversal lacked explicit diagnostic'
  fi
fi

SYMLINK_ACTIVE="$TMP/symlink.md"
SYMLINK_DETAILS="$TMP/symlink-details"
OUTSIDE="$TMP/outside.md"
printf 'outside\n' > "$OUTSIDE"
mkdir -p "$SYMLINK_DETAILS"
ln -s "$OUTSIDE" "$SYMLINK_DETAILS/link.md"
printf '%s\n' '# Active Trials' '## symlink (2099-01-12)' '- started: 2026-08-29' '- status: active' '- detail: `active/link.md`' > "$SYMLINK_ACTIVE"
if python3 "$SCRIPT" --active "$SYMLINK_ACTIVE" --details-dir "$SYMLINK_DETAILS" > "$TMP/symlink.log" 2>&1; then
  fail 'detail symlink was accepted'
else
  if grep -q 'detail-path-symlink' "$TMP/symlink.log" && grep -q '^outside$' "$OUTSIDE"; then
    ok 'detail symlink is rejected without outside write'
  else
    fail 'detail symlink handling was unsafe'
  fi
fi

DANGLING_ACTIVE="$TMP/dangling.md"
DANGLING_DETAILS="$TMP/dangling-details"
DANGLING_TARGET="$TMP/not-created"
ln -s "$DANGLING_TARGET" "$DANGLING_DETAILS"
printf '%s\n' '# Active Trials' '## dangling (2099-01-12)' '- start: 2026-08-29' '- note: dangling root' > "$DANGLING_ACTIVE"
if python3 "$SCRIPT" --active "$DANGLING_ACTIVE" --details-dir "$DANGLING_DETAILS" --apply > "$TMP/dangling.log" 2>&1; then
  fail 'dangling detail root was accepted'
else
  if grep -q 'details-dir-symlink' "$TMP/dangling.log" && [ ! -e "$DANGLING_TARGET" ]; then
    ok 'dangling detail root is rejected without outside creation'
  else
    fail 'dangling detail root handling was unsafe'
  fi
fi

ORDER_ACTIVE="$TMP/order.md"
ORDER_DETAILS="$TMP/order-details"
ORDER_EVENTS="$TMP/order-events"
printf '%s\n' '# Active Trials' '## order (2099-01-12)' '- start: 2026-08-29' '- note: order' > "$ORDER_ACTIVE"
python3 - "$SCRIPT" "$ORDER_ACTIVE" "$ORDER_DETAILS" "$ORDER_EVENTS" <<'PY'
from contextlib import redirect_stderr, redirect_stdout
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path
import sys
script, active, details, events_path = sys.argv[1:]
spec = spec_from_file_location('migrate_active_order', script)
module = module_from_spec(spec)
spec.loader.exec_module(module)
events = []
real_replace = module.os.replace
def record(source, target):
    events.append(str(target))
    return real_replace(source, target)
module.os.replace = record
with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
    result = module.main(['--active', active, '--details-dir', details, '--apply'])
Path(events_path).write_text('\n'.join(events) + '\n')
raise SystemExit(result)
PY
ORDER_FIRST=$(python3 -c 'from pathlib import Path; print(Path(__import__("sys").argv[1]).read_text().splitlines()[0])' "$ORDER_EVENTS")
ORDER_LAST=$(python3 -c 'from pathlib import Path; print(Path(__import__("sys").argv[1]).read_text().splitlines()[-1])' "$ORDER_EVENTS")
ORDER_FIRST_REAL=$(python3 -c 'from pathlib import Path; print(Path(__import__("sys").argv[1]).resolve())' "$ORDER_FIRST")
ORDER_LAST_REAL=$(python3 -c 'from pathlib import Path; print(Path(__import__("sys").argv[1]).resolve())' "$ORDER_LAST")
ORDER_DETAILS_REAL=$(python3 -c 'from pathlib import Path; print(Path(__import__("sys").argv[1]).resolve())' "$ORDER_DETAILS")
ORDER_ACTIVE_REAL=$(python3 -c 'from pathlib import Path; print(Path(__import__("sys").argv[1]).resolve())' "$ORDER_ACTIVE")
case "$ORDER_FIRST_REAL" in
  "$ORDER_DETAILS_REAL"/*) ORDER_FIRST_OK=yes ;;
  *) ORDER_FIRST_OK=no ;;
esac
if [ "$ORDER_FIRST_OK" = yes ] && [ "$ORDER_LAST_REAL" = "$ORDER_ACTIVE_REAL" ]; then
  ok 'detail files commit before active index replacement'
else
  fail 'active index replacement preceded detail files'
fi

ATOMIC_PARENT="$TMP/atomic-parent"
ATOMIC_DETAILS="$TMP/atomic-details"
ATOMIC_ACTIVE="$ATOMIC_PARENT/active.md"
mkdir -p "$ATOMIC_PARENT" "$ATOMIC_DETAILS"
printf '%s\n' '# Active Trials' '## atomic (2099-01-13)' '- start: 2026-08-30' '- note: atomic' > "$ATOMIC_ACTIVE"
chmod 500 "$ATOMIC_PARENT"
if python3 "$SCRIPT" --active "$ATOMIC_ACTIVE" --details-dir "$ATOMIC_DETAILS" --apply > "$TMP/atomic.log" 2>&1; then
  fail 'atomic failure fixture unexpectedly succeeded'
else
  chmod 700 "$ATOMIC_PARENT"
  if [ "$(find "$ATOMIC_DETAILS" -maxdepth 1 -type f -name '*.md' | wc -l | tr -d ' ')" = '0' ] && grep -q '## atomic (2099-01-13)' "$ATOMIC_ACTIVE"; then
    ok 'atomic failure leaves active and detail roots unchanged'
  else
    fail 'atomic failure left partial migration output'
  fi
fi

FAIL_AFTER_DETAILS_ACTIVE="$TMP/fail-after-details.md"
FAIL_AFTER_DETAILS_DIR="$TMP/fail-after-details"
printf '%s\n' '# Active Trials' '## fail-after-details (2099-01-14)' '- start: 2026-08-31' '- note: fail after details' > "$FAIL_AFTER_DETAILS_ACTIVE"
python3 - "$SCRIPT" "$FAIL_AFTER_DETAILS_ACTIVE" "$FAIL_AFTER_DETAILS_DIR" <<'PY'
from contextlib import redirect_stderr, redirect_stdout
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path
import sys
script, active, details = sys.argv[1:]
spec = spec_from_file_location('migrate_active_fail_after_details', script)
module = module_from_spec(spec)
spec.loader.exec_module(module)
real_replace = module.os.replace
def fail_active(source, target):
    if Path(target).resolve() == Path(active).resolve():
        raise OSError('injected active replace failure')
    return real_replace(source, target)
module.os.replace = fail_active
with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
    result = module.main(['--active', active, '--details-dir', details, '--apply'])
raise SystemExit(0 if result != 0 and not list(Path(details).glob('*.md')) and '## fail-after-details (2099-01-14)' in Path(active).read_text() else 1)
PY
if [ "$?" -eq 0 ]; then
  ok 'active replace failure cleans committed detail files'
else
  fail 'active replace failure left partial migration output'
fi

CLEANUP_FAIL_ACTIVE="$TMP/cleanup-fail.md"
CLEANUP_FAIL_DETAILS="$TMP/cleanup-fail-details"
CLEANUP_FAIL_LOG="$TMP/cleanup-fail.log"
printf '%s\n' '# Active Trials' '## cleanup-fail (2099-01-14)' '- start: 2026-08-31' '- note: cleanup failure' > "$CLEANUP_FAIL_ACTIVE"
python3 - "$SCRIPT" "$CLEANUP_FAIL_ACTIVE" "$CLEANUP_FAIL_DETAILS" "$CLEANUP_FAIL_LOG" <<'PY'
from contextlib import redirect_stderr, redirect_stdout
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path
import sys
script, active, details, log = sys.argv[1:]
spec = spec_from_file_location('migrate_active_cleanup_failure', script)
module = module_from_spec(spec)
spec.loader.exec_module(module)
real_replace = module.os.replace
real_unlink = module.Path.unlink
def fail_active(source, target):
    if Path(target).resolve() == Path(active).resolve():
        raise OSError('injected active replace failure')
    return real_replace(source, target)
def fail_detail_unlink(path, *args, **kwargs):
    if str(path).startswith(str(Path(details).resolve())):
        raise OSError('injected detail cleanup failure')
    return real_unlink(path, *args, **kwargs)
module.os.replace = fail_active
module.Path.unlink = fail_detail_unlink
stdout = StringIO()
stderr = StringIO()
with redirect_stdout(stdout), redirect_stderr(stderr):
    result = module.main(['--active', active, '--details-dir', details, '--apply'])
Path(log).write_text(stdout.getvalue() + stderr.getvalue())
raise SystemExit(0 if result != 0 and 'rollback-incomplete' in Path(log).read_text() else 1)
PY
if [ "$?" -eq 0 ] && grep -q 'rollback-incomplete' "$CLEANUP_FAIL_LOG"; then
  ok 'detail cleanup failure is explicit and nonzero'
else
  fail 'detail cleanup failure was silently swallowed'
fi

MALFORMED_H2_ACTIVE="$TMP/malformed-h2.md"
printf '%s\n' '# Active Trials' '## malformed (2099-01-15) (round 2)' '- start: 2026-09-01' '- note: malformed heading' > "$MALFORMED_H2_ACTIVE"
if python3 "$SCRIPT" --active "$MALFORMED_H2_ACTIVE" --details-dir "$TMP/malformed-details" --apply > "$TMP/malformed-h2.log" 2>&1; then
  fail 'unrecognized dated H2 was silently accepted'
else
  if grep -q 'unclassified-h2:## malformed' "$TMP/malformed-h2.log"; then
    ok 'unrecognized dated H2 is rejected explicitly'
  else
    fail 'unrecognized dated H2 lacked explicit diagnostic'
  fi
fi

PARENT_LINK_ACTIVE="$TMP/parent-link.md"
PARENT_LINK_TARGET="$TMP/parent-link-target"
PARENT_LINK="$TMP/parent-link"
mkdir -p "$PARENT_LINK_TARGET"
ln -s "$PARENT_LINK_TARGET" "$PARENT_LINK"
printf '%s\n' '# Active Trials' '## parent-link (2099-01-16)' '- start: 2026-09-02' '- note: parent link' > "$PARENT_LINK_ACTIVE"
if python3 "$SCRIPT" --active "$PARENT_LINK_ACTIVE" --details-dir "$PARENT_LINK/active" --apply > "$TMP/parent-link.log" 2>&1; then
  fail 'details parent symlink was accepted'
else
  if grep -q 'details-dir-symlink' "$TMP/parent-link.log" && [ "$(find "$PARENT_LINK_TARGET" -type f | wc -l | tr -d ' ')" = '0' ]; then
    ok 'details parent symlink is rejected without external write'
  else
    fail 'details parent symlink handling was unsafe'
  fi
fi

ACTIVE_PARENT_TARGET="$TMP/active-parent-target"
ACTIVE_PARENT_LINK="$TMP/active-parent"
ACTIVE_PARENT="$ACTIVE_PARENT_LINK/active.md"
ACTIVE_PARENT_DETAILS="$TMP/active-parent-details"
mkdir -p "$ACTIVE_PARENT_TARGET"
ln -s "$ACTIVE_PARENT_TARGET" "$ACTIVE_PARENT_LINK"
printf '%s\n' '# Active Trials' '## active-parent (2099-01-19)' '- start: 2026-09-04' '- note: active parent symlink' > "$ACTIVE_PARENT_TARGET/active.md"
cp "$ACTIVE_PARENT_TARGET/active.md" "$TMP/active-parent-before.md"
if python3 "$SCRIPT" --active "$ACTIVE_PARENT" --details-dir "$ACTIVE_PARENT_DETAILS" --apply > "$TMP/active-parent.log" 2>&1; then
  fail 'active parent symlink was accepted'
else
  if grep -q 'symlink' "$TMP/active-parent.log" && cmp -s "$TMP/active-parent-before.md" "$ACTIVE_PARENT_TARGET/active.md" && [ -L "$ACTIVE_PARENT_LINK" ] && [ "$(find "$ACTIVE_PARENT_TARGET" -type f | wc -l | tr -d ' ')" = '1' ]; then
    ok 'active parent symlink is rejected without external write'
  else
    fail 'active parent symlink handling was unsafe'
  fi
fi

EXISTING_INDEX_ACTIVE="$TMP/existing-index.md"
EXISTING_INDEX_DETAILS="$TMP/existing-index-details"
mkdir -p "$EXISTING_INDEX_DETAILS"
printf '%s\n' 'detail-key: active/alpha-2026-08-23.md' 'detail-title: alpha' '# existing alpha' > "$EXISTING_INDEX_DETAILS/alpha-2026-08-23.md"
printf '%s\n' \
  '# Active Trials' \
  '## alpha (2099-01-18)' \
  '- start: 2026-09-03' \
  '- note: legacy duplicate' \
  '' \
  '## alpha (2099-01-17)' \
  '- started: 2026-08-23' \
  '- status: active' \
  '- detail: `active/alpha-2026-08-23.md`' \
  > "$EXISTING_INDEX_ACTIVE"
if python3 "$SCRIPT" --active "$EXISTING_INDEX_ACTIVE" --details-dir "$EXISTING_INDEX_DETAILS" --apply > "$TMP/existing-index.log" 2>&1 && grep -q '^## alpha \[run-2\]' "$EXISTING_INDEX_ACTIVE" && grep -q 'duplicate-slug:alpha' "$TMP/existing-index.log"; then
  ok 'indexed and legacy entries share duplicate slug allocation'
else
  fail 'indexed and legacy entries collided silently'
fi

MISMATCH_ACTIVE="$TMP/mismatch.md"
MISMATCH_DETAILS="$TMP/mismatch-details"
mkdir -p "$MISMATCH_DETAILS"
printf '%s\n' 'detail-key: active/other-2026-08-23.md' > "$MISMATCH_DETAILS/mismatch-2026-08-23.md"
printf '%s\n' \
  '# Active Trials' \
  '## mismatch (2099-01-04)' \
  '- started: 2026-08-23' \
  '- status: active' \
  '- detail: `active/mismatch-2026-08-23.md`' \
  > "$MISMATCH_ACTIVE"
if python3 "$SCRIPT" --active "$MISMATCH_ACTIVE" --details-dir "$MISMATCH_DETAILS" > "$TMP/mismatch.log" 2>&1; then
  fail 'mismatched detail identity was silently accepted'
else
  if grep -q 'detail-mismatch' "$TMP/mismatch.log"; then
    ok 'mismatched detail identity is reported explicitly'
  else
    fail 'mismatched detail identity lacked explicit diagnostic'
  fi
fi

DATE_ONLY_ACTIVE="$TMP/date-only-pointer.md"
DATE_ONLY_DETAILS="$TMP/date-only-pointer-details"
mkdir -p "$DATE_ONLY_DETAILS"
printf '%s\n' 'detail-key: active/date-only-2026-08-22.md' 'detail-title: date-only' > "$DATE_ONLY_DETAILS/date-only-2026-08-22.md"
printf '%s\n' \
  '# Active Trials' \
  '## date-only (2099-01-05)' \
  '- started: 2026-08-23' \
  '- status: active' \
  '- detail: `active/date-only-2026-08-22.md`' \
  > "$DATE_ONLY_ACTIVE"
if python3 "$SCRIPT" --active "$DATE_ONLY_ACTIVE" --details-dir "$DATE_ONLY_DETAILS" > "$TMP/date-only.log" 2>&1; then
  fail 'self-consistent detail with wrong basename date was accepted'
else
  if grep -q 'detail-mismatch' "$TMP/date-only.log"; then
    ok 'detail basename date must equal started'
  else
    fail 'wrong detail basename date lacked explicit diagnostic'
  fi
fi

FOREIGN_ACTIVE="$TMP/foreign-pointer.md"
FOREIGN_DETAILS="$TMP/foreign-pointer-details"
mkdir -p "$FOREIGN_DETAILS"
printf '%s\n' 'detail-key: active/trial-b-2026-08-23.md' 'detail-title: trial-b' > "$FOREIGN_DETAILS/trial-b-2026-08-23.md"
printf '%s\n' \
  '# Active Trials' \
  '## trial-a (2099-01-04)' \
  '- started: 2026-08-23' \
  '- status: active' \
  '- detail: `active/trial-b-2026-08-23.md`' \
  > "$FOREIGN_ACTIVE"
if python3 "$SCRIPT" --active "$FOREIGN_ACTIVE" --details-dir "$FOREIGN_DETAILS" > "$TMP/foreign-pointer.log" 2>&1; then
  fail 'self-consistent foreign detail pointer was accepted'
else
  if grep -q 'detail-mismatch' "$TMP/foreign-pointer.log"; then
    ok 'foreign detail pointer is rejected'
  else
    fail 'foreign detail pointer lacked explicit diagnostic'
  fi
fi

MISSING_ACTIVE="$TMP/missing.md"
printf '%s\n' \
  '# Active Trials' \
  '## missing-detail (2099-01-04)' \
  '- started: 2026-08-23' \
  '- status: active' \
  '- detail: `active/missing-detail-2026-08-23.md`' \
  > "$MISSING_ACTIVE"
if python3 "$SCRIPT" --active "$MISSING_ACTIVE" --details-dir "$TMP/missing-active" > "$TMP/missing.log" 2>&1; then
  fail 'missing detail file was silently accepted'
else
  if grep -q 'detail-missing' "$TMP/missing.log"; then
    ok 'missing detail file is reported explicitly'
  else
    fail 'missing detail file failed without explicit report'
  fi
fi

printf '%s\n' '----'
printf 'PASS=%s FAIL=%s\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
