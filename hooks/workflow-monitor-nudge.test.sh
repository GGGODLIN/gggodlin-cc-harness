#!/usr/bin/env bash
# Contract test for workflow-monitor-nudge.sh
#
# <!-- 本檔在契約測試底下：bash ~/.claude/hooks/workflow-monitor-nudge.test.sh -->
#
# Threat model of the hook under test: 提示型 (nudge). It injects context asking the
# session to arm a watch; it never blocks and holds no authorization. So "judged
# wrong" fails open (silent), and the only real failure modes are (a) naming a
# command that does not exist, and (b) nudging a non-Anthropic vendor whose route is
# retired or whose quota shape has no limit-watch adapter.
# Both are what this test pins. Added 2026-09-02 with the fork merge: the old glm arm
# used to name /glm-workflow-monitor, a command that no longer exists.
#
# Fixture set per gate-authoring §3:
#   known-good  : CC_VENDOR unset and empty both emit the Anthropic nudge
#   known-bad   : CC_VENDOR=glm / relay / mimo / deepseek stay silent
#   boundary    : CC_VENDOR set but empty behaves as unset (Anthropic-native)
#   lifecycle   : every command name the hook emits must resolve to a file on disk,
#                 and the emitted JSON must be valid for the harness to consume
set -uo pipefail

HOOK="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/workflow-monitor-nudge.sh"
[ -f "$HOOK" ] || { echo "FAIL: $HOOK not found"; exit 1; }
COMMANDS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/commands"

PASS=0
FAIL=0

ok()   { echo "ok   - $1"; PASS=$((PASS + 1)); }
bad()  { echo "FAIL - $1"; FAIL=$((FAIL + 1)); }

# Runs the hook with a given CC_VENDOR state; echoes stdout.
run_hook() {
  if [ "$1" = "--unset" ]; then
    env -u CC_VENDOR bash "$HOOK" 2>/dev/null
  else
    env CC_VENDOR="$1" bash "$HOOK" 2>/dev/null
  fi
}

expect_nudge() {
  local name="$1" vendor="$2" want="$3"
  local out ctx
  out=$(run_hook "$vendor")
  if [ -z "$out" ]; then bad "$name (silent — expected a nudge)"; return; fi
  if ! printf '%s' "$out" | jq -e '.hookSpecificOutput.hookEventName == "PostToolUse"' >/dev/null 2>&1; then
    bad "$name (output is not valid PostToolUse hook JSON)"
    printf '%s\n' "$out" | sed 's/^/       /'
    return
  fi
  ctx=$(printf '%s' "$out" | jq -r '.hookSpecificOutput.additionalContext')
  if printf '%s' "$ctx" | grep -qF "$want"; then
    ok "$name"
  else
    bad "$name (context missing '$want')"
    printf '%s\n' "$ctx" | sed 's/^/       /'
  fi
}

expect_silent() {
  local name="$1" vendor="$2"
  local out
  out=$(run_hook "$vendor")
  if [ -z "$out" ]; then ok "$name"; else
    bad "$name (nudged when it must stay silent)"
    printf '%s\n' "$out" | sed 's/^/       /'
  fi
}

echo "── known-good: only Anthropic-native gets nudged"
expect_nudge "CC_VENDOR unset → anthropic nudge" --unset "workflow-monitor"

echo "── REGRESSION GUARD: no nudge may name a deleted sibling command"
for v in --unset; do
  ctx=$(run_hook "$v" | jq -r '.hookSpecificOutput.additionalContext // ""')
  if printf '%s' "$ctx" | grep -qE 'glm-workflow-monitor|relay-workflow-monitor'; then
    bad "vendor '$v' nudge names a command deleted 2026-09-02"
  else
    ok "vendor '$v' nudge names no deleted command"
  fi
done

echo "── known-bad: non-Anthropic vendors stay silent"
expect_silent "CC_VENDOR=glm → silent (GLM monitor retired, no adapter)" glm
expect_silent "CC_VENDOR=relay → silent (nudge route killed 2026-07-24, merge did not revive it)" relay
expect_silent "CC_VENDOR=mimo → silent (credit model, no threshold gate)" mimo
expect_silent "CC_VENDOR=deepseek → silent (PAYG, no threshold gate)" deepseek

echo "── boundary: CC_VENDOR set but empty is Anthropic-native, not 'other'"
expect_nudge "CC_VENDOR='' → anthropic nudge" "" "workflow-monitor"

echo "── lifecycle: every command the hook names must exist on disk"
for v in --unset; do
  ctx=$(run_hook "$v" | jq -r '.hookSpecificOutput.additionalContext // ""')
  # command names appear as "<name> skill" in the nudge text
  names=$(printf '%s' "$ctx" | grep -oE '[a-z-]+-monitor' | sort -u)
  if [ -z "$names" ]; then bad "vendor '$v' nudge names no command at all"; continue; fi
  for n in $names; do
    if [ -f "$COMMANDS_DIR/$n.md" ]; then
      ok "vendor '$v' names existing command: $n.md"
    else
      bad "vendor '$v' names missing command: $COMMANDS_DIR/$n.md"
    fi
  done
done

echo "── execution: hook must exit 0 on every input (提示型, never blocks)"
for v in --unset glm relay mimo ""; do
  run_hook "$v" >/dev/null 2>&1
  if [ $? -eq 0 ]; then
    ok "exit 0 for vendor '${v:-<empty>}'"
  else
    bad "non-zero exit for vendor '${v:-<empty>}' — a nudge must never block"
  fi
done

echo
echo "passed=$PASS failed=$FAIL"
[ "$FAIL" -eq 0 ]
