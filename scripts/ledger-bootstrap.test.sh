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

FAILED=0

# F7a: trailing whitespace in repo path must survive repo-root and ignore round-trip
SPACE_REPO="$FIX_HOME/Desktop/projects/demo-space "
mkdir -p "$SPACE_REPO"
git -C "$SPACE_REPO" init -q
SPACE_ROOT_OUT=$(HOME="$FIX_HOME" python3 "$CLI" repo-root "$SPACE_REPO" 2>&1 || true)
EXPECTED_SPACE_ROOT=$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$SPACE_REPO")
if [ "$SPACE_ROOT_OUT" = "$EXPECTED_SPACE_ROOT" ] && \
   HOME="$FIX_HOME" python3 "$CLI" add-ignore "$SPACE_REPO" --ignore-file "$IGNORE" >/dev/null 2>&1 && \
   HOME="$FIX_HOME" python3 "$CLI" is-ignored "$SPACE_REPO" --ignore-file "$IGNORE" >/dev/null 2>&1; then
  printf 'PASS F7 trailing whitespace repo path preserved\n'
else
  printf 'FAIL F7 trailing whitespace repo path lost: got=[%s] expected=[%s]\n' "$SPACE_ROOT_OUT" "$EXPECTED_SPACE_ROOT"
  FAILED=1
fi

# F7b: newline in repo path must be rejected by add-ignore without line injection
VICTIM="$FIX_HOME/Desktop/projects/victim-f7"
mkdir -p "$VICTIM"
git -C "$VICTIM" init -q
VICTIM_CANONICAL=$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$VICTIM")
EVIL_NL="$FIX_HOME/Desktop/projects/evil-f7"$'\n'"$VICTIM_CANONICAL"
mkdir -p "$EVIL_NL"
git -C "$EVIL_NL" init -q
if HOME="$FIX_HOME" python3 "$CLI" add-ignore "$EVIL_NL" --ignore-file "$IGNORE" >/dev/null 2>&1; then
  printf 'FAIL F7 newline repo path accepted by add-ignore\n'
  FAILED=1
elif HOME="$FIX_HOME" python3 "$CLI" is-ignored "$VICTIM" --ignore-file "$IGNORE" >/dev/null 2>&1; then
  printf 'FAIL F7 newline repo path injected victim into ignore file\n'
  FAILED=1
else
  printf 'PASS F7 newline repo path rejected without line injection\n'
fi

# F8: non-ASCII repo path must work under PYTHONUTF8=0 LC_ALL=C
UTF8_REPO="$FIX_HOME/Desktop/projects/測試"
UTF8_MARKERS="$FIX/markers-f8"
mkdir -p "$UTF8_REPO" "$UTF8_MARKERS"
git -C "$UTF8_REPO" init -q
EXPECTED_UTF8_ROOT=$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$UTF8_REPO")
if UTF8_OUT=$(PYTHONUTF8=0 LC_ALL=C HOME="$FIX_HOME" python3 "$CLI" repo-root "$UTF8_REPO" 2>&1) && \
   [ "$UTF8_OUT" = "$EXPECTED_UTF8_ROOT" ] && \
   UTF8_SESSION_OUT=$(printf '{"hook_event_name":"SessionStart","source":"startup","session_id":"f8-utf8","cwd":"%s"}' "$UTF8_REPO" | \
     PYTHONUTF8=0 LC_ALL=C HOME="$FIX_HOME" LEDGER_BOOTSTRAP_IGNORE_FILE="$IGNORE" LEDGER_BOOTSTRAP_MARKER_ROOT="$UTF8_MARKERS" python3 "$CLI" session 2>&1) && \
   printf '%s\n' "$UTF8_SESSION_OUT" | grep -qF 'systemMessage' && \
   [ -f "$UTF8_MARKERS/ledger-bootstrap-session-f8-utf8" ] && \
   PYTHONUTF8=0 LC_ALL=C HOME="$FIX_HOME" python3 "$CLI" init-project-docs "$UTF8_REPO" >/dev/null 2>&1 && \
   [ -f "$UTF8_REPO/docs/owner/STATE.md" ]; then
  printf 'PASS F8 non-ASCII repo path works under PYTHONUTF8=0 LC_ALL=C\n'
else
  printf 'FAIL F8 non-ASCII repo path failed under PYTHONUTF8=0 LC_ALL=C: %s\n' "${UTF8_OUT:-${UTF8_SESSION_OUT:-error}}"
  FAILED=1
fi

# M1: existing CLAUDE.md and log files are preserved on init-project-docs
PRESERVE_REPO="$FIX_HOME/Desktop/projects/preserve-existing"
mkdir -p "$PRESERVE_REPO/docs/owner"
git -C "$PRESERVE_REPO" init -q
printf '%s\n' '# Existing Project Guide' > "$PRESERVE_REPO/CLAUDE.md"
printf '%s\n' '# Existing Factcheck Log' > "$PRESERVE_REPO/docs/owner/factcheck-log.md"
if HOME="$FIX_HOME" python3 "$CLI" init-project-docs "$PRESERVE_REPO" >/dev/null 2>&1 && \
   grep -qF '# Existing Project Guide' "$PRESERVE_REPO/CLAUDE.md" && \
   grep -qF '帳本生命週期' "$PRESERVE_REPO/CLAUDE.md" && \
   grep -qF '# Existing Factcheck Log' "$PRESERVE_REPO/docs/owner/factcheck-log.md" && \
   [ -f "$PRESERVE_REPO/docs/owner/STATE.md" ] && \
   [ -f "$PRESERVE_REPO/docs/owner/proofread-log.md" ]; then
  printf 'PASS M1 existing CLAUDE.md and logs preserved on init-project-docs\n'
else
  printf 'FAIL M1 existing CLAUDE.md or logs not preserved\n'
  FAILED=1
fi

# M7: non-SessionStart hook_event_name stays silent and creates no marker
SESSION_REPO="$FIX_HOME/Desktop/projects/session-filter"
MARKERS_DIR="$FIX/markers-m7"
mkdir -p "$SESSION_REPO" "$MARKERS_DIR"
git -C "$SESSION_REPO" init -q
PRETOOL_OUT=$(printf '{"hook_event_name":"PreToolUse","source":"startup","session_id":"m7-pretool","cwd":"%s"}' "$SESSION_REPO" | \
  HOME="$FIX_HOME" LEDGER_BOOTSTRAP_IGNORE_FILE="$IGNORE" LEDGER_BOOTSTRAP_MARKER_ROOT="$MARKERS_DIR" python3 "$CLI" session)
STOP_OUT=$(printf '{"hook_event_name":"Stop","source":"startup","session_id":"m7-stop","cwd":"%s"}' "$SESSION_REPO" | \
  HOME="$FIX_HOME" LEDGER_BOOTSTRAP_IGNORE_FILE="$IGNORE" LEDGER_BOOTSTRAP_MARKER_ROOT="$MARKERS_DIR" python3 "$CLI" session)
START_OUT=$(printf '{"hook_event_name":"SessionStart","source":"startup","session_id":"m7-start","cwd":"%s"}' "$SESSION_REPO" | \
  HOME="$FIX_HOME" LEDGER_BOOTSTRAP_IGNORE_FILE="$IGNORE" LEDGER_BOOTSTRAP_MARKER_ROOT="$MARKERS_DIR" python3 "$CLI" session)
if [ -z "$PRETOOL_OUT" ] && [ ! -e "$MARKERS_DIR/ledger-bootstrap-session-m7-pretool" ] && \
   [ -z "$STOP_OUT" ] && [ ! -e "$MARKERS_DIR/ledger-bootstrap-session-m7-stop" ] && \
   [ -n "$START_OUT" ] && [ -f "$MARKERS_DIR/ledger-bootstrap-session-m7-start" ]; then
  printf 'PASS M7 non-SessionStart events stay silent while SessionStart emits\n'
else
  printf 'FAIL M7 hook_event_name filter broken (pretool=[%s] stop=[%s] start=[%s])\n' "$PRETOOL_OUT" "$STOP_OUT" "$START_OUT"
  FAILED=1
fi

# Edge case: non-string SessionStart source stays silent and exits 0 without TypeError
NONSTR_OUT=$(printf '{"hook_event_name":"SessionStart","source":["startup"],"session_id":"sol13-list","cwd":"%s"}' "$SESSION_REPO" | \
  HOME="$FIX_HOME" LEDGER_BOOTSTRAP_IGNORE_FILE="$IGNORE" LEDGER_BOOTSTRAP_MARKER_ROOT="$MARKERS_DIR" python3 "$CLI" session)
if [ -z "$NONSTR_OUT" ] && [ ! -e "$MARKERS_DIR/ledger-bootstrap-session-sol13-list" ]; then
  printf 'PASS Sol13 non-string SessionStart source stays silent and leaves session unmarked\n'
else
  printf 'FAIL Sol13 non-string SessionStart source broke: [%s]\n' "$NONSTR_OUT"
  FAILED=1
fi

[ "$FAILED" -eq 0 ] || exit 1
printf 'All ledger bootstrap parser tests passed\n'
