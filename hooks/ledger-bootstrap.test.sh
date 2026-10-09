#!/usr/bin/env bash
# 本檔在契約測試底下：bash ~/.claude/hooks/ledger-bootstrap.test.sh
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK="$ROOT/hooks/ledger-bootstrap.sh"
HELPER="$ROOT/scripts/ledger-bootstrap.py"
FIX="$(mktemp -d)"
trap 'rm -R "$FIX"' EXIT

FIX_HOME="$FIX/home"
IGNORE="$FIX_HOME/.claude/state/ledger-bootstrap-ignore.txt"
MARKERS="$FIX/tmp"
mkdir -p "$FIX_HOME/Desktop/work" "$FIX_HOME/Desktop/projects" "$FIX_HOME/Desktop/other" "$(dirname "$IGNORE")" "$MARKERS"

run_hook() {
  local event=$1
  local source=$2
  local session=$3
  local cwd=$4
  printf '{"hook_event_name":"%s","source":"%s","session_id":"%s","cwd":"%s"}' "$event" "$source" "$session" "$cwd" | \
    HOME="$FIX_HOME" LEDGER_BOOTSTRAP_HELPER="$HELPER" LEDGER_BOOTSTRAP_IGNORE_FILE="$IGNORE" \
    LEDGER_BOOTSTRAP_MARKER_ROOT="$MARKERS" bash "$HOOK"
}

make_git_repo() {
  local path=$1
  mkdir -p "$path"
  git -C "$path" init -q
}

assert_fires() {
  local label=$1
  local output=$2
  local repo=$3
  local session=$4
  if printf '%s' "$output" | python3 -c 'import json,sys; p=json.load(sys.stdin); m=p.get("systemMessage", ""); raise SystemExit(0 if m.startswith("此 repo 尚未建立 docs/owner/STATE.md。") and "/init-project-docs" in m and "/ledger-ignore" in m and sys.argv[1] in m and sys.argv[2] in m else 1)' "$repo" "$session"; then
    printf 'PASS %s\n' "$label"
  else
    printf 'FAIL %s: %s\n' "$label" "$output"
    exit 1
  fi
}

assert_silent() {
  local label=$1
  local output=$2
  if [ -z "$output" ]; then
    printf 'PASS %s\n' "$label"
  else
    printf 'FAIL %s: %s\n' "$label" "$output"
    exit 1
  fi
}

QUALIFYING="$FIX_HOME/Desktop/work/demo"
make_git_repo "$QUALIFYING"
assert_fires "qualifying repo emits bootstrap reminder" "$(run_hook SessionStart startup session-first "$QUALIFYING")" "$QUALIFYING" session-first
mkdir -p "$QUALIFYING/src"
assert_fires "repo subdirectory resolves to git root" "$(run_hook SessionStart resume session-subdir "$QUALIFYING/src")" "$QUALIFYING" session-subdir

OUTSIDE="$FIX_HOME/Desktop/other/demo"
make_git_repo "$OUTSIDE"
assert_silent "repo outside allowed roots is silent" "$(run_hook SessionStart startup session-outside "$OUTSIDE")"

NON_GIT="$FIX_HOME/Desktop/work/not-git"
mkdir -p "$NON_GIT"
assert_silent "non-git directory is silent" "$(run_hook SessionStart startup session-non-git "$NON_GIT")"

WITH_STATE="$FIX_HOME/Desktop/work/with-state"
make_git_repo "$WITH_STATE"
mkdir -p "$WITH_STATE/docs/owner"
printf '%s\n' 'state' > "$WITH_STATE/docs/owner/STATE.md"
assert_silent "existing STATE.md is silent" "$(run_hook SessionStart startup session-state "$WITH_STATE")"

STATE_SYMLINK="$FIX_HOME/Desktop/work/state-symlink"
STATE_SECRET="$FIX/state-secret"
make_git_repo "$STATE_SYMLINK"
printf '%s\n' 'synthetic state secret' > "$STATE_SECRET"
mkdir -p "$STATE_SYMLINK/docs/owner"
ln -s "$STATE_SECRET" "$STATE_SYMLINK/docs/owner/STATE.md"
assert_silent "STATE.md symlink is silent" "$(run_hook SessionStart startup session-state-symlink "$STATE_SYMLINK")"

DOCS_ONLY="$FIX_HOME/Desktop/work/docs-only"
make_git_repo "$DOCS_ONLY"
mkdir -p "$DOCS_ONLY/docs/owner"
assert_fires "docs directory without STATE.md still fires" "$(run_hook SessionStart startup session-docs-only "$DOCS_ONLY")" "$DOCS_ONLY" session-docs-only

IGNORED="$FIX_HOME/Desktop/projects/ignored"
make_git_repo "$IGNORED"
HOME="$FIX_HOME" python3 "$HELPER" add-ignore "$IGNORED" --ignore-file "$IGNORE" >/dev/null
assert_silent "ignored repo is silent" "$(run_hook SessionStart startup session-ignored "$IGNORED")"

SIBLING="$FIX_HOME/Desktop/projects/ignored-copy"
make_git_repo "$SIBLING"
assert_fires "ignored child name does not suppress sibling repo" "$(run_hook SessionStart startup session-sibling "$SIBLING")" "$SIBLING" session-sibling

MARKER_REPO="$FIX_HOME/Desktop/work/marker"
make_git_repo "$MARKER_REPO"
FIRST="$(run_hook SessionStart startup session-marker "$MARKER_REPO")"
assert_fires "first session marker call fires" "$FIRST" "$MARKER_REPO" session-marker
assert_silent "same session second call is silent" "$(run_hook SessionStart startup session-marker "$MARKER_REPO")"
assert_silent "compact source does not repeat marker reminder" "$(run_hook SessionStart compact session-marker "$MARKER_REPO")"
[ -f "$MARKERS/ledger-bootstrap-session-session-marker" ] || {
  printf 'FAIL marker path\n'
  exit 1
}

OLD_MARKER="$MARKERS/ledger-bootstrap-session-old"
printf '%s\n' old > "$OLD_MARKER"
python3 - "$OLD_MARKER" <<'PY'
import os
import sys
import time
path = sys.argv[1]
old = time.time() - (2 * 86400)
os.utime(path, (old, old))
PY
NEW_REPO="$FIX_HOME/Desktop/work/gc"
make_git_repo "$NEW_REPO"
assert_fires "old marker is garbage collected before firing" "$(run_hook SessionStart startup session-gc "$NEW_REPO")" "$NEW_REPO" session-gc
[ ! -e "$OLD_MARKER" ] || {
  printf 'FAIL old marker was not garbage collected\n'
  exit 1
}

assert_silent "malformed session payload is silent" "$(printf '%s' '{not-json}' | HOME="$FIX_HOME" LEDGER_BOOTSTRAP_HELPER="$HELPER" LEDGER_BOOTSTRAP_IGNORE_FILE="$IGNORE" LEDGER_BOOTSTRAP_MARKER_ROOT="$MARKERS" bash "$HOOK")"
assert_silent "unknown SessionStart source is silent" "$(run_hook SessionStart unknown session-unknown-source "$NEW_REPO")"

printf 'All bootstrap hook tests passed\n'
