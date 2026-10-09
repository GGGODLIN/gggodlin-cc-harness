#!/bin/bash
set -uo pipefail

COMMAND="$HOME/Desktop/projects/.claude/commands/trial-review.md"
ACTIVE="$HOME/Desktop/projects/.claude/trials/active.md"
CLI="$HOME/.claude/scripts/ledger-lifecycle/ledger-index.py"
TMP="$(cd "$(mktemp -d)" && pwd -P)"
trap 'rm -rf "$TMP"' EXIT

for pair in "$COMMAND|ledger-index.py append" "$COMMAND|index-pending" "$COMMAND|reconcile" "$ACTIVE|ledger-index.py append" "$ACTIVE|trial-archive-resources.py" "$ACTIVE|detail"; do
  file="${pair%%|*}"
  needle="${pair#*|}"
  grep -F -- "$needle" "$file" >/dev/null || {
    printf 'FAIL missing trial review contract: %s in %s\n' "$needle" "$file"
    exit 1
  }
done

SOURCE="$TMP/archived.md"
INDEX="$TMP/missing/index.md"
printf '%s\n' '### ✅ [結案 2026-02-03 · KEEP — fixture] fixture trial (原 review 2026-02-01)' > "$SOURCE"
LINE='fixture-trial｜KEEP｜2026-02-03｜fixture reason｜### ✅ [結案 2026-02-03 · KEEP — fixture] fixture trial (原 review 2026-02-01)'
if python3 "$CLI" append --kind archived --source "$SOURCE" --index "$INDEX" --anchor '### ✅ [結案 2026-02-03 · KEEP — fixture] fixture trial (原 review 2026-02-01)' --line "$LINE" >/dev/null 2>&1; then
  printf '%s\n' 'FAIL trial review append failure unexpectedly passed'
  exit 1
fi
grep -F '[index-pending]' "$SOURCE" >/dev/null || {
  printf '%s\n' 'FAIL trial review append failure did not mark source'
  exit 1
}
printf '%s\n' 'trial-review ledger append contract: PASS'
