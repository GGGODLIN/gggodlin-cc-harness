#!/bin/bash
# Fixtures for semble-root-block.py: known-good / known-bad / boundary / lifecycle.
# Pass token printed only when every case passes: SEMBLE_ROOT_BLOCK_TESTS_OK
set -u
HOOK="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/semble-root-block.py"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
FAKE_HOME="$T/home"
mkdir -p "$FAKE_HOME/Desktop/projects/.claude" "$FAKE_HOME/Desktop/projects/watchdogs" "$FAKE_HOME/Desktop/work/acme/acme-dashboard-v2" "$FAKE_HOME/Desktop/workx" "$FAKE_HOME/code" "$T/tmp/watchdogs-ticket04-health" "$FAKE_HOME/.claude/hooks/state/semble-root-block"
ln -s "$FAKE_HOME/Desktop/work" "$T/work-link"
export SEMBLE_ROOT_BLOCK_HOME="$FAKE_HOME"
export SEMBLE_ROOT_BLOCK_SENTINEL="$FAKE_HOME/.claude/hooks/state/semble-root-block/disabled"
fail=0; n=0

run() { # name expect(allow|deny) payload
  n=$((n+1))
  out="$(printf '%s' "$3" | /usr/bin/python3 -I "$HOOK" 2>/dev/null)"; rc=$?
  if [ "$2" = deny ]; then
    if [ $rc -eq 0 ] && printf '%s' "$out" | /usr/bin/grep -q '"permissionDecision": *"deny"'; then echo "PASS  $1"; else echo "FAIL  $1 (expected deny) out=$out rc=$rc"; fail=1; fi
  else
    if [ $rc -eq 0 ] && [ -z "$out" ]; then echo "PASS  $1"; else echo "FAIL  $1 (expected allow/silent) out=$out rc=$rc"; fail=1; fi
  fi
}
mcp() { printf '{"tool_name":"%s","tool_input":{"query":"q","repo":"%s"}}' "${2:-mcp__semble__search}" "$1"; }

echo "== known-good"
run "single repo under work"            allow "$(mcp "$FAKE_HOME/Desktop/work/acme/acme-dashboard-v2")"
run "worktree in /tmp"                  allow "$(mcp "$T/tmp/watchdogs-ticket04-health")"
run "remote https url"                  allow "$(mcp "https://github.com/org/repo")"
run "find_related single repo"          allow "$(mcp "$FAKE_HOME/Desktop/projects/watchdogs" mcp__semble__find_related)"
echo "== known-bad"
run "work root"                         deny  "$(mcp "$FAKE_HOME/Desktop/work")"
run "projects root trailing slash"      deny  "$(mcp "$FAKE_HOME/Desktop/projects/")"
run "code root"                         deny  "$(mcp "$FAKE_HOME/code")"
run "acme sub-aggregation"             deny  "$(mcp "$FAKE_HOME/Desktop/work/acme")"
run "home (ancestor)"                   deny  "$(mcp "$FAKE_HOME")"
run "Desktop (ancestor)"                deny  "$(mcp "$FAKE_HOME/Desktop")"
run "filesystem root"                   deny  "$(mcp "/")"
run "symlink to work root"              deny  "$(mcp "$T/work-link")"
run "find_related on work root"         deny  "$(mcp "$FAKE_HOME/Desktop/work" mcp__semble__find_related)"
echo "== boundary"
run "projects/.claude child allowed"    allow "$(mcp "$FAKE_HOME/Desktop/projects/.claude")"
run "prefix-not-ancestor workx"         allow "$(mcp "$FAKE_HOME/Desktop/workx")"
run "missing repo param"                deny  '{"tool_name":"mcp__semble__search","tool_input":{"query":"q"}}'
run "empty repo string"                 deny  "$(mcp "")"
echo "== lifecycle"
run "malformed json -> deny (safety)"   deny  'not json'
run "non-semble tool passthrough"       allow '{"tool_name":"Edit","tool_input":{"file_path":"/Users/x/.claude/hooks/semble-root-block.py"}}'
run "bash tool untouched"               allow '{"tool_name":"Bash","tool_input":{"command":"semble search q ~/Desktop/work"}}'
touch "$SEMBLE_ROOT_BLOCK_SENTINEL"
run "sentinel present -> allow"         allow "$(mcp "$FAKE_HOME/Desktop/work")"
rm -f "$SEMBLE_ROOT_BLOCK_SENTINEL"
run "sentinel removed -> deny again"    deny  "$(mcp "$FAKE_HOME/Desktop/work")"

echo "cases=$n fail=$fail"
[ $fail -eq 0 ] && echo "SEMBLE_ROOT_BLOCK_TESTS_OK"
exit $fail
