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
# Added 2026-10-14: a merge whose tests were green had silently dropped one side's change in four
# places (Collie upstream 1.21.0); only a per-file review against both sides found them.
assert_grep "conflicted paths are kept for the review" 'Keep the list of conflicted paths'
assert_grep "review uses three diffs per file" 'base to ours.*base to theirs.*base to the result'
assert_grep "review invokes prepare_merge_review helper for staged and committed merges" 'prepare_merge_review\.py --repo \. --staged'
assert_grep "review supports committed merge or worker handoff" 'prepare_merge_review\.py --repo \. --commit HEAD'
assert_grep "reviewer has no conversation context" 'fresh reviewer.*no conversation context'
assert_grep "reviewer looks for a disappeared side" 'whose change disappeared'
assert_grep "mechanical conflicts are checked by a script" 'mechanical.*checked by a script, not an agent'
assert_grep "main owns fresh reviewer completion across worker handoffs" 'delegated worker.*main must obtain that fresh reviewer'
assert_order "checks precede the side review" '^6\. Discover the project' '^7\. \*\*Review every conflicted file'
assert_order "side review precedes finishing" '^7\. \*\*Review every conflicted file' '^8\. \*\*Finish the merge'

python3 "${HOME}/.claude/skills/resolving-merge-conflicts/scripts/tests/test_prepare_merge_review.py"

printf 'PASS=%s FAIL=%s\n' "$PASS" "$FAIL"

if (( FAIL > 0 )); then
  exit 1
fi
