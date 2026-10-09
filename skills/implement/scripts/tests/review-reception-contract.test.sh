#!/usr/bin/env bash
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
IMPLEMENT="$ROOT/skills/implement/SKILL.md"
RECEIVING="$ROOT/skills/receiving-code-review/SKILL.md"
PASS=0
FAIL=0

assert_file() {
  local label=$1 path=$2
  if [ -f "$path" ]; then
    printf 'PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf 'FAIL: %s\n' "$label"
    FAIL=$((FAIL + 1))
  fi
}

assert_grep() {
  local label=$1 pattern=$2 path=$3
  if grep -qE "$pattern" "$path" 2>/dev/null; then
    printf 'PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf 'FAIL: %s\n' "$label"
    FAIL=$((FAIL + 1))
  fi
}

assert_file "receiving-code-review fork exists" "$RECEIVING"
assert_grep "fork marks its contract test" '本檔在契約測試底下.*review-reception-contract\.test\.sh' "$RECEIVING"
assert_grep "fork records upstream repo" 'upstream: obra/superpowers' "$RECEIVING"
assert_grep "fork records upstream path" 'upstream-path: skills/receiving-code-review/SKILL\.md' "$RECEIVING"
assert_grep "fork records pinned commit" 'upstream-pinned: b36e082' "$RECEIVING"
assert_grep "implement marks review reception contract" '本檔在契約測試底下.*review-reception-contract\.test\.sh' "$IMPLEMENT"
assert_grep "implement waits for current review round" 'Collect every reviewer result from the current review round' "$IMPLEMENT"
assert_grep "zero findings skip reception skill" 'If every reviewer reports no findings.*do not invoke' "$IMPLEMENT"
assert_grep "first non-empty finding invokes reception skill" 'first review round with one or more findings.*Skill\(receiving-code-review\)' "$IMPLEMENT"
assert_grep "reception skill succeeds before triage" 'matching tool result succeeds before triaging' "$IMPLEMENT"
assert_grep "later review rounds reuse loaded method" 'Later review rounds in the same implement run reuse the loaded method' "$IMPLEMENT"
assert_grep "next implement run loads again" 'A later .*Skill\(implement\).* invocation starts a new run' "$IMPLEMENT"
assert_grep "fix threshold remains current policy" 'does not change the current severity or scope policy' "$IMPLEMENT"
assert_grep "review reception does not restart full review" 'Do not start a new full review solely because findings were fixed' "$IMPLEMENT"

printf '%s\n' '----'
printf 'PASS=%s FAIL=%s\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
