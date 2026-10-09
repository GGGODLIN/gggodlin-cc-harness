#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
SKILL="$ROOT/skills/to-spec/SKILL.md"
PASS=0
FAIL=0

assert_contains() {
  local label="$1"
  local pattern="$2"
  if grep -qE "$pattern" "$SKILL"; then
    printf 'PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf 'FAIL: %s\n' "$label"
    FAIL=$((FAIL + 1))
  fi
}

assert_absent() {
  local label="$1"
  local pattern="$2"
  if grep -qE "$pattern" "$SKILL"; then
    printf 'FAIL: %s\n' "$label"
    FAIL=$((FAIL + 1))
  else
    printf 'PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  fi
}

line_of() {
  local needle="$1"
  grep -nFm1 "$needle" "$SKILL" | cut -d: -f1 || true
}

assert_before() {
  local label="$1"
  local first="$2"
  local second="$3"
  local first_line second_line
  first_line="$(line_of "$first")"
  second_line="$(line_of "$second")"
  if [[ -n "$first_line" && -n "$second_line" && "$first_line" -lt "$second_line" ]]; then
    printf 'PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf 'FAIL: %s\n' "$label"
    FAIL=$((FAIL + 1))
  fi
}

assert_contains "skill marks its contract test" '本檔在契約測試底下：bash skills/to-spec/scripts/tests/adr-authoring-contract\.test\.sh'
assert_contains "gate names the confirmed requirements and test seams point" 'after requirements and test seams are confirmed'
assert_contains "gate names hard-to-reverse" 'hard-to-reverse'
assert_contains "gate names surprising without context" 'surprising without context'
assert_contains "gate names real trade-off" 'real trade-off'
assert_contains "all three conditions require one domain-modeling call" 'all three.*exactly one.*domain-modeling'
assert_contains "call purpose is ADR authoring" 'domain-modeling.*ADR authoring|ADR authoring.*domain-modeling'
assert_contains "qualifying decisions travel as a candidate set" 'candidate decision set'
assert_contains "multiple decisions do not multiply calls" 'not.*once per decision'
assert_contains "non-qualifying decisions skip the call" 'zero.*invoke|invoke.*zero|skip.*invoke'
assert_contains "to-spec does not execute the ADR checker" 'does not (execute|run).*check-decisions|do not (execute|run).*check-decisions'
assert_contains "ADR gate preserves OpenSpec landing validator" 'check-decisions.*openspec validate|openspec validate.*check-decisions'
assert_absent "checker command is not an execution instruction" '^[[:space:]]*(Run|Execute).*check-decisions'
assert_before "seam confirmation precedes ADR gate" 'Check with the user that these seams match their expectations.' 'ADR authoring gate'
assert_before "ADR gate precedes drafting" 'ADR authoring gate' '3. Draft the spec'
assert_before "ADR gate precedes landing" 'ADR authoring gate' '## Landing convention'
assert_contains "seam handoff reaches ADR gate" 'user has confirmed the seams\. Then continue to step 2a\.'
assert_absent "seam handoff cannot bypass ADR gate" 'user has confirmed the seams\. Then continue to step 3\.'
assert_contains "ADR gate has a completion pointer" 'Done when: every decision has a three-condition result.*continues to step 3\.'
assert_contains "a false condition only omits its decision" 'omit only that decision.*suppress other qualifying decisions'

printf 'PASS=%s FAIL=%s\n' "$PASS" "$FAIL"

if (( FAIL > 0 )); then
  exit 1
fi
