#!/usr/bin/env bash
set -u

ROOT=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../../.." && pwd)
SKILL="$ROOT/skills/implement/SKILL.md"
STAGE="$ROOT/skills/review-implement/SKILL.md"
TEST="$ROOT/skills/implement/scripts/tests/review-implement-handoff-contract.test.sh"
PASS=0
FAIL=0

pass() {
  printf 'PASS: %s\n' "$1"
  PASS=$((PASS + 1))
}

fail() {
  printf 'FAIL: %s\n' "$1"
  FAIL=$((FAIL + 1))
}

assert_file() {
  local label="$1"
  local path="$2"
  if [ -f "$path" ]; then
    pass "$label"
  else
    fail "$label"
  fi
}

assert_contains_in() {
  local label="$1"
  local pattern="$2"
  local path="$3"
  if grep -Fq -- "$pattern" "$path" 2>/dev/null; then
    pass "$label"
  else
    fail "$label"
  fi
}

assert_absent_in() {
  local label="$1"
  local pattern="$2"
  local path="$3"
  if grep -Fq -- "$pattern" "$path" 2>/dev/null; then
    fail "$label"
  else
    pass "$label"
  fi
}

line_for_in() {
  grep -nFm 1 -- "$1" "$2" 2>/dev/null | cut -d: -f1
}

assert_order_in() {
  local label="$1"
  local first="$2"
  local second="$3"
  local path="$4"
  local first_line second_line
  first_line=$(line_for_in "$first" "$path")
  second_line=$(line_for_in "$second" "$path")
  if [ -n "$first_line" ] && [ -n "$second_line" ] && [ "$first_line" -lt "$second_line" ]; then
    pass "$label"
  else
    fail "$label"
  fi
}

byte_offset_for_in() {
  grep -boFm 1 -- "$1" "$2" 2>/dev/null | cut -d: -f1
}

assert_byte_order_in() {
  local label="$1"
  local first="$2"
  local second="$3"
  local path="$4"
  local first_offset second_offset
  first_offset=$(byte_offset_for_in "$first" "$path")
  second_offset=$(byte_offset_for_in "$second" "$path")
  if [ -n "$first_offset" ] && [ -n "$second_offset" ] && [ "$first_offset" -lt "$second_offset" ]; then
    pass "$label"
  else
    fail "$label"
  fi
}

assert_file "implement skill exists" "$SKILL"
assert_file "review-implement skill exists" "$STAGE"
assert_file "handoff contract test exists" "$TEST"
assert_contains_in "implement marks handoff contract" 'bash ~/.claude/skills/implement/scripts/tests/review-implement-handoff-contract.test.sh' "$SKILL"
assert_contains_in "stage marks its contract" 'bash ~/.claude/skills/review-implement/scripts/tests/review-implement-contract.test.sh' "$STAGE"

assert_contains_in "canonical stage owns axis question" 'Choose review axes:' "$STAGE"
assert_contains_in "canonical stage owns recommendation" 'long-axis signal' "$STAGE"
assert_contains_in "canonical stage owns status vocabulary" 'Run status: PASS | BLOCKED | WAIVED' "$STAGE"
assert_contains_in "canonical stage owns report schema" 'resolved_models' "$STAGE"
assert_contains_in "canonical stage owns finding mapping" 'Scope finding 用 `S1`、`S2`' "$STAGE"
assert_contains_in "canonical stage owns skip waiver" 'explicit `WAIVED` Run event' "$STAGE"
assert_contains_in "implement points to canonical review semantics" 'canonical owner of the fixed user-facing preface, axis question, recommendation, Scope／YAGNI mapping, `WAIVED`／`BLOCKED`／`PASS` status, and report schema' "$SKILL"
assert_contains_in "implement follows canonical stage contract" 'Follow `review-implement` Step 1 verbatim as the sole user-facing SSOT rather than duplicating those details in implement' "$SKILL"
assert_contains_in "implement carries selected seats" 'It also owns the model matrix, selected `<model, axis>` seats, and resolved-model attribution for this stage' "$SKILL"
assert_contains_in "handoff carries selected models" 'Implement must carry the selected seats and resolved models from the stage report forward' "$SKILL"
assert_contains_in "handoff does not assume Fable" 'must not assume a fixed Fable seat' "$SKILL"
assert_absent_in "implement does not duplicate axis question" 'Choose review axes:' "$SKILL"
assert_absent_in "implement does not duplicate axis status schema" 'scope: completed | failed | waived' "$SKILL"

assert_contains_in "closeout invokes auto-choice before commit" 'Invoke `Skill(auto-choice)` on this run'"'"'s work' "$SKILL"
assert_contains_in "handback cites auto-choice ledger" 'cite the Step 6 auto-choice presentation and its ledger link' "$SKILL"
assert_contains_in "closeout invokes review stage" 'Skill(review-implement)' "$SKILL"
assert_contains_in "handoff requires successful local commit" 'After the local commit succeeds' "$SKILL"
assert_contains_in "matching stage result is required" 'wait for its matching tool result' "$SKILL"
assert_contains_in "handoff waits for terminal outcome" 'wait for its top-level answer and terminal outcome' "$SKILL"
assert_contains_in "handoff is before final shipping" 'Keep final push／PR handback／archive／completed 宣告 behind the terminal outcome' "$SKILL"
assert_contains_in "unanswered state remains pending" 'an unanswered stage keeps implement at `implementation-complete / review-pending` and stops closeout' "$SKILL"
assert_contains_in "blocked outcome stops closeout" 'a `BLOCKED` outcome also stops closeout' "$SKILL"
assert_contains_in "blocked repair loop is bounded" 'A `BLOCKED` Run may continue only through an accepted-obligation repair loop' "$SKILL"
assert_contains_in "blocked repair does not closeout" 'final shipping／closeout remains prohibited' "$SKILL"
assert_contains_in "only pass or waived can closeout" 'continue only for `PASS` or an explicitly recorded `WAIVED` outcome' "$SKILL"
assert_contains_in "skip requires recorded waiver" 'A `skip` completes only after the waiver is recorded' "$SKILL"
assert_contains_in "skip is not pass" 'never claim review `PASS`' "$SKILL"
assert_contains_in "handoff records stable range" 'review target `base_sha／head_sha`' "$SKILL"
assert_contains_in "moving target is blocked" 'an uncommitted target-scope is `BLOCKED`' "$SKILL"
assert_contains_in "moving working tree is not reviewed" 'must not be reviewed as a moving working tree' "$SKILL"
assert_contains_in "closeout reuses git-closeout ground truth" '/git-closeout' "$SKILL"
assert_contains_in "closeout checks raw gate deny" 'raw gate deny' "$SKILL"
assert_contains_in "closeout checks remote merge-tree" 'remote merge-tree' "$SKILL"
assert_contains_in "closeout checks local dirty path overlap" 'local dirty 與部署路徑的交集' "$SKILL"
assert_contains_in "only path overlap waits for owner" '只有交集非空才等待 local dirty owner' "$SKILL"

assert_contains_in "accepted obligations return to implement" 'accepted repair obligation returned by the stage' "$SKILL"
assert_contains_in "repair runs focused verification" 'run focused verification first' "$SKILL"
assert_contains_in "failed verification stays blocked" 'If focused verification fails, do not commit or run a targeted recheck; return the same finding-ID within the existing per-root-cause correction budget and keep Run `BLOCKED`' "$SKILL"
assert_contains_in "repair follows existing commit policy" 'follow the existing commit policy' "$SKILL"
assert_contains_in "repair gets stable commit head" 'new stable commit and `head_sha`' "$SKILL"
assert_contains_in "commit policy is unchanged" 'do not change that policy' "$SKILL"
assert_contains_in "moving repair stays blocked" 'A working-tree-only repair stays `BLOCKED` without rechecking' "$SKILL"
assert_contains_in "main owns targeted recheck" 'Main performs a read-only targeted recheck against the original finding ID and acceptance evidence' "$SKILL"
assert_contains_in "recheck cannot add findings" 'it cannot add findings, dispatch a reviewer, or start a new axis selection' "$SKILL"
assert_contains_in "failed recheck uses existing budget" 'A failed recheck returns the same ID within budget' "$SKILL"
assert_contains_in "budget and scope expansion wait for user" 'Ask the top-level user only for budget exhaustion or scope expansion' "$SKILL"
assert_contains_in "expanded repair waits for decision" 'until the decision, do not expand, commit, or recheck' "$SKILL"
assert_contains_in "independent obligations survive unresolved decision" 'independent obligations may continue and dependent obligations wait' "$SKILL"
assert_contains_in "obligations trigger final suite" "After all accepted obligations' targeted rechecks pass" "$SKILL"
assert_contains_in "final suite uses new head" 'run the final full suite against the new `head_sha`' "$SKILL"
assert_contains_in "red final suite blocks" 'a red suite keeps Run `BLOCKED`' "$SKILL"
assert_contains_in "targeted recheck forbids second review" 'Do not automatically start a full review after a targeted recheck' "$SKILL"
assert_contains_in "new review needs user entry" "a new round requires the user's explicit invocation through the same stage entry" "$SKILL"

assert_order_in "review stage follows local commit" 'Then commit only when' 'Skill(review-implement)' "$SKILL"
assert_byte_order_in "auto-choice precedes local commit" 'Invoke `Skill(auto-choice)`' 'Then commit only when' "$SKILL"
assert_byte_order_in "matching result precedes terminal outcome" 'After the matching tool result succeeds' 'terminal outcome' "$SKILL"
assert_order_in "stage invocation precedes final shipping" 'Skill(review-implement)' 'Keep final push／PR handback／archive／completed 宣告 behind the terminal outcome' "$SKILL"
assert_order_in "focused verification precedes stable commit" 'run focused verification first' 'After focused verification passes, follow the existing commit policy' "$SKILL"
assert_order_in "stable commit precedes targeted recheck" 'new stable commit and `head_sha`' 'Only after the stable commit, Main performs' "$SKILL"
assert_byte_order_in "stable rechecks precede final suite" "After all accepted obligations' targeted rechecks pass" 'run the final full suite against the new `head_sha`' "$SKILL"
assert_byte_order_in "final suite follows targeted rechecks" "After all accepted obligations' targeted rechecks pass" 'run the final full suite against the new `head_sha`' "$SKILL"

printf '%s\n' '----'
printf 'PASS=%s FAIL=%s\n' "$PASS" "$FAIL"
if [ "$FAIL" -ne 0 ]; then
  exit 1
fi
printf '%s\n' 'IMPLEMENT_REVIEW_HANDOFF_CONTRACT_ALL_PASS'
