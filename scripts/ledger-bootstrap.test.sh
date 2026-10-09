#!/usr/bin/env bash
# 本檔在契約測試底下：bash ~/.claude/scripts/ledger-bootstrap.test.sh
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="$ROOT/scripts/ledger-bootstrap.py"
FIX="$(mktemp -d)"
trap 'rm -R "$FIX"' EXIT

FIX_HOME="$FIX/home"
REPO="$FIX_HOME/Desktop/projects/demo"
IGNORE="$FIX_HOME/.claude/state/ledger-bootstrap-ignore.txt"
mkdir -p "$REPO" "$(dirname "$IGNORE")"
git -C "$REPO" init -q

ROOT_OUTPUT=$(HOME="$FIX_HOME" python3 "$CLI" repo-root "$REPO")
EXPECTED_ROOT=$(python3 - "$REPO" <<'PY'
import os
import sys
print(os.path.realpath(sys.argv[1]))
PY
)
[ "$ROOT_OUTPUT" = "$EXPECTED_ROOT" ] || {
  printf 'FAIL repo-root canonical output: %s\n' "$ROOT_OUTPUT"
  exit 1
}
printf 'PASS repo-root canonical output\n'

printf '%s\n%s\n%s\n' "$REPO/../demo" "$REPO" 'relative/path' > "$IGNORE"
if HOME="$FIX_HOME" python3 "$CLI" is-ignored "$REPO" --ignore-file "$IGNORE" >/dev/null; then
  printf 'PASS canonical ignore parser matches absolute repo\n'
else
  printf 'FAIL canonical ignore parser did not match\n'
  exit 1
fi

HOME="$FIX_HOME" python3 "$CLI" add-ignore "$REPO" --ignore-file "$IGNORE" >/dev/null
COUNT=$(python3 - "$IGNORE" "$EXPECTED_ROOT" <<'PY'
import sys
from pathlib import Path
lines = [line.strip() for line in Path(sys.argv[1]).read_text().splitlines() if line.strip() == sys.argv[2]]
print(len(lines))
PY
)
[ "$COUNT" = 1 ] || {
  printf 'FAIL ignore parser did not deduplicate canonical path: %s\n' "$COUNT"
  exit 1
}
printf 'PASS ignore parser deduplicates canonical path\n'

SIBLING="$FIX_HOME/Desktop/projects/demo-copy"
mkdir -p "$SIBLING"
git -C "$SIBLING" init -q
if HOME="$FIX_HOME" python3 "$CLI" is-ignored "$SIBLING" --ignore-file "$IGNORE" >/dev/null; then
  printf 'FAIL child-name collision treated as ignored\n'
  exit 1
fi
printf 'PASS ignore parser uses exact repo root\n'

OUTSIDE="$FIX_HOME/Desktop/other"
mkdir -p "$OUTSIDE"
git -C "$OUTSIDE" init -q
if HOME="$FIX_HOME" python3 "$CLI" add-ignore "$OUTSIDE" --ignore-file "$IGNORE" >/dev/null 2>&1; then
  printf 'FAIL outside repo accepted by add-ignore\n'
  exit 1
fi
printf 'PASS add-ignore rejects repo outside bootstrap scope\n'

printf 'All ledger bootstrap parser tests passed\n'
