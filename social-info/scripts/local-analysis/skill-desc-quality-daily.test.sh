#!/usr/bin/env bash
set -u

WRAPPER="$(cd "$(dirname "$0")" && pwd)/skill-desc-quality-daily.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
pass=0
fail=0

record_pass() {
  printf 'PASS %s\n' "$1"
  ((pass++))
}

record_fail() {
  printf 'FAIL %s\n' "$1"
  ((fail++))
}

set_mtime() {
  python3 - "$1" "$2" <<'PY'
import os
import sys
os.utime(sys.argv[1], (int(sys.argv[2]), int(sys.argv[2])))
PY
}

extract_fixture() {
  python3 - "$WRAPPER" "$1" "$2" <<'PY'
from pathlib import Path
import sys
source = Path(sys.argv[1]).read_text()
name = sys.argv[2]
start = source.index(f'{name}_BEGIN') + len(f'{name}_BEGIN')
end = source.index(f'{name}_END')
Path(sys.argv[3]).write_text(source[start:end].strip() + '\n')
PY
}

if ! grep -Fq 'SELECTION_FIXTURE_BEGIN' "$WRAPPER" || ! grep -Fq 'STATE_COMMIT_FIXTURE_BEGIN' "$WRAPPER"; then
  record_fail 'wrapper exposes selection and state commit fixtures'
  printf '%s\n' "---- $pass pass / $fail fail ----"
  exit "$fail"
fi

extract_fixture SELECTION_FIXTURE "$TMP/selection.sh"
extract_fixture STATE_COMMIT_FIXTURE "$TMP/state-commit.sh"

root="$TMP/touch-failure"
mkdir -p "$root/state" "$root/new"
touch "$root/new/SKILL.md" "$root/state/last_run" "$root/cutoff"
printf '%s\n' "$root/new/SKILL.md" > "$root/paths"
: > "$root/state/seen"
set_mtime "$root/new/SKILL.md" 90
set_mtime "$root/state/last_run" 100
set_mtime "$root/cutoff" 110
PATHS_FILE="$root/paths" SEEN_PATHS="$root/state/seen" LAST_RUN="$root/state/last_run" CHANGED_FILE="$root/changed" bash "$TMP/selection.sh"
if PATHS_FILE="$root/paths" SEEN_NEXT="$root/seen.next" SCAN_CUTOFF="$root/cutoff" LAST_RUN_NEXT="$root/last-run.next" LAST_RUN="$root/state/last_run" SEEN_PATHS="$root/missing/seen" bash "$TMP/state-commit.sh" 2>/dev/null; then
  record_fail 'state commit surfaces snapshot replacement failure'
else
  PATHS_FILE="$root/paths" SEEN_PATHS="$root/state/seen" LAST_RUN="$root/state/last_run" CHANGED_FILE="$root/changed-again" bash "$TMP/selection.sh"
  if grep -Fxq "$root/new/SKILL.md" "$root/changed-again"; then
    record_pass 'snapshot failure leaves unseen path selectable'
  else
    record_fail 'snapshot failure hid unseen path'
  fi
fi

root="$TMP/mid-audit-change"
mkdir -p "$root/state" "$root/existing"
touch "$root/existing/SKILL.md" "$root/state/last_run" "$root/cutoff"
printf '%s\n' "$root/existing/SKILL.md" > "$root/paths" "$root/state/seen"
set_mtime "$root/state/last_run" 80
set_mtime "$root/cutoff" 100
set_mtime "$root/existing/SKILL.md" 90
PATHS_FILE="$root/paths" SEEN_PATHS="$root/state/seen" LAST_RUN="$root/state/last_run" CHANGED_FILE="$root/changed" bash "$TMP/selection.sh"
set_mtime "$root/existing/SKILL.md" 110
PATHS_FILE="$root/paths" SEEN_NEXT="$root/seen.next" SCAN_CUTOFF="$root/cutoff" LAST_RUN_NEXT="$root/last-run.next" LAST_RUN="$root/state/last_run" SEEN_PATHS="$root/state/seen" bash "$TMP/state-commit.sh"
PATHS_FILE="$root/paths" SEEN_PATHS="$root/state/seen" LAST_RUN="$root/state/last_run" CHANGED_FILE="$root/changed-again" bash "$TMP/selection.sh"
if grep -Fxq "$root/existing/SKILL.md" "$root/changed-again"; then
  record_pass 'scan-start cutoff preserves mid-audit changes'
else
  record_fail 'mid-audit change was hidden by completion cursor'
fi

root="$TMP/body-vs-desc"
mkdir -p "$root/state" "$root/s1" "$root/s2"
cat > "$root/s1/SKILL.md" <<'EOF'
---
name: s1
description: "Original description one"
---
# Body v1
EOF
cat > "$root/s2/SKILL.md" <<'EOF'
---
name: s2
description: "Original description two"
---
# Body v1
EOF
touch "$root/state/last_run" "$root/cutoff"
printf '%s\n%s\n' "$root/s1/SKILL.md" "$root/s2/SKILL.md" > "$root/paths"
set_mtime "$root/s1/SKILL.md" 80
set_mtime "$root/s2/SKILL.md" 80
set_mtime "$root/state/last_run" 90
set_mtime "$root/cutoff" 100
PATHS_FILE="$root/paths" SEEN_NEXT="$root/seen.next" SCAN_CUTOFF="$root/cutoff" LAST_RUN_NEXT="$root/last-run.next" LAST_RUN="$root/state/last_run" SEEN_PATHS="$root/state/seen" bash "$TMP/state-commit.sh"

# Body-only edit on s1, description edit on s2 (both before new scan cutoff)
cat > "$root/s1/SKILL.md" <<'EOF'
---
name: s1
description: "Original description one"
---
# Body v2 changed!
EOF
cat > "$root/s2/SKILL.md" <<'EOF'
---
name: s2
description: "Updated description two"
---
# Body v1
EOF
set_mtime "$root/s1/SKILL.md" 120
set_mtime "$root/s2/SKILL.md" 120
PATHS_FILE="$root/paths" SEEN_PATHS="$root/state/seen" LAST_RUN="$root/state/last_run" CHANGED_FILE="$root/changed-body-vs-desc" bash "$TMP/selection.sh"
if ! grep -Fxq "$root/s1/SKILL.md" "$root/changed-body-vs-desc" && grep -Fxq "$root/s2/SKILL.md" "$root/changed-body-vs-desc"; then
  record_pass 'body-only edit skipped while description edit is selected'
else
  record_fail 'body-only vs description edit selection failed'
fi

printf '%s\n' "---- $pass pass / $fail fail ----"
exit "$fail"
