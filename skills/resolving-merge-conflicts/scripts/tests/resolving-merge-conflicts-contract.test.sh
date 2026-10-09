#!/usr/bin/env bash
set -euo pipefail

SKILL="${HOME}/.claude/skills/resolving-merge-conflicts/SKILL.md"
PASS=0
FAIL=0

assert_grep() {
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

assert_order() {
  local label="$1"
  local first="$2"
  local second="$3"
  local first_line
  local second_line
  first_line="$(grep -nE "$first" "$SKILL" | cut -d: -f1 | sort -n | first_line_value || true)"
  second_line="$(grep -nE "$second" "$SKILL" | cut -d: -f1 | sort -n | first_line_value || true)"
  if [[ -n "$first_line" && -n "$second_line" && "$first_line" -lt "$second_line" ]]; then
    printf 'PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf 'FAIL: %s\n' "$label"
    FAIL=$((FAIL + 1))
  fi
}

first_line_value() {
  IFS= read -r line || true
  printf '%s' "$line"
}

assert_grep "skill marks its contract test" '本檔在契約測試底下.*resolving-merge-conflicts-contract\.test\.sh'
assert_grep "summary invokes bundled helper" 'extract_conflict_context\.py --repo \.($|`)'
assert_grep "detail inspects one file" 'extract_conflict_context\.py --repo \. --file <path>'
assert_grep "history intent remains required" 'commit messages.*PRs.*issues/tickets'
assert_grep "full file is an explicit fallback" 'Read the full file only when the compact output is insufficient'
assert_grep "non-text conflicts require more evidence" 'binary.*rename.*submodule.*not sufficient'
assert_grep "resolution is staged one file at a time" 'Stage that file alone'
assert_grep "unresolved conflicts are rechecked" 'Re-check unresolved conflicts after each file'
assert_order "summary precedes per-file detail" '^1\. \*\*Start with a compact summary' '^3\. \*\*Inspect one conflicted file'

printf 'PASS=%s FAIL=%s\n' "$PASS" "$FAIL"

if (( FAIL > 0 )); then
  exit 1
fi
