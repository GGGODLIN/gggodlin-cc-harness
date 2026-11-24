#!/usr/bin/env bash
# 本檔在契約測試底下：bash ~/.claude/skills/hillclimb/scripts/tests/hillclimb-contract.test.sh
set -euo pipefail

SKILL="${HOME}/.claude/skills/hillclimb/SKILL.md"
PASS=0
FAIL=0

assert_grep() {
  local label="$1"
  local pattern="$2"
  if command grep -qE "$pattern" "$SKILL"; then
    printf 'PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf 'FAIL: %s\n' "$label"
    FAIL=$((FAIL + 1))
  fi
}

assert_grep "declares contract test" '本檔在契約測試底下.*hillclimb-contract\.test\.sh'
assert_grep "requires clean isolated worktree and current_best_sha" 'current_best_sha=\$\(git rev-parse HEAD\)'
assert_grep "forbids dirty shared worktree" 'Never run a hillclimb loop inside a dirty shared worktree'
assert_grep "links to benchmark verification recipe" '~/.claude/references/verification-recipes-and-probes\.md.*效能宣稱核驗'
assert_grep "links to pure-compute oracle replay recipe" '~/.claude/references/verification-recipes-and-probes\.md.*純計算／解析器爬山前導配方'
assert_grep "links to isolated-copy sensitivity proof" '~/.claude/references/verification-recipes-and-probes\.md.*驗證配方維護.*第 3 點'
assert_grep "requires one-time human checkpoint to freeze harness" 'One-time human checkpoint to freeze the ruler'
assert_grep "locks harness read-only after approval" 'frozen \(read-only\)'
assert_grep "initializes 8-column decision.tsv outside git" 'iter\thypothesis\tchange\tbefore\tafter\tdelta\ttests\tverdict'
assert_grep "reads decision.tsv before each iteration" 'Read `decision\.tsv` in full first'
assert_grep "enforces single-variable change" 'change one variable'
assert_grep "reverts losing rounds to current_best_sha" 'Reset the isolated worktree back to `current_best_sha`'
assert_grep "logs both keep and revert rounds" 'both `keep` and `revert`'

printf 'PASS=%s FAIL=%s\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
