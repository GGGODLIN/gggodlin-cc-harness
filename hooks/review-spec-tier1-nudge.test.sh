#!/bin/bash

set -euo pipefail

HOOK=~/.claude/hooks/review-spec-tier1-nudge.sh
PASSES=0
FAILURES=0

hook_output() {
  local file_path=$1
  jq -nc --arg file_path "$file_path" '{tool_input:{file_path:$file_path}}' | "$HOOK"
}

context_for() {
  local output
  output=$(hook_output "$1")
  if [ -n "$output" ]; then
    printf '%s' "$output" | jq -r '.hookSpecificOutput.additionalContext'
  fi
}

assert_contains() {
  local label=$1 actual=$2 needle=$3
  if printf '%s' "$actual" | grep -Fq "$needle"; then
    PASSES=$((PASSES + 1))
    printf 'PASS %s\n' "$label"
  else
    FAILURES=$((FAILURES + 1))
    printf 'FAIL %s\n' "$label"
  fi
}

assert_silent() {
  local label=$1 actual=$2
  if [ -z "$actual" ]; then
    PASSES=$((PASSES + 1))
    printf 'PASS %s\n' "$label"
  else
    FAILURES=$((FAILURES + 1))
    printf 'FAIL %s\n' "$label"
  fi
}

OPEN_SPEC_CONTEXT=$(context_for '/tmp/project/openspec/changes/example/design.md')
assert_contains 'local openspec design path fires' "$OPEN_SPEC_CONTEXT" '/review-spec 3 <本次 file_path 的絕對路徑>'
assert_contains 'Tier 3 waits for real invocation' "$OPEN_SPEC_CONTEXT" '只有使用者真正送出 command 才執行'
assert_contains 'review can be skipped' "$OPEN_SPEC_CONTEXT" 'e) 跳過 review、直接進 to-tickets'
assert_contains 'skip does not reprompt' "$OPEN_SPEC_CONTEXT" '不再重問'
assert_contains 'YAGNI review is offered' "$OPEN_SPEC_CONTEXT" 'f) YAGNI 軸'
assert_contains 'model-written spec recommends YAGNI' "$OPEN_SPEC_CONTEXT" '模型代寫 spec 建議至少先跑'
assert_contains 'YAGNI stays separate from tiers' "$OPEN_SPEC_CONTEXT" '與 T1–T4 分開執行'
assert_contains 'menu ends with the YAGNI entry marker' "$OPEN_SPEC_CONTEXT" '選單最後一行固定放 `<review-spec-entry-menu:v1>`'

SCRATCH_SPEC_CONTEXT=$(context_for '/tmp/project/.scratch/example/spec.md')
assert_contains 'local scratch spec path fires' "$SCRATCH_SPEC_CONTEXT" 'design/spec doc 落檔'

TASK_CONTEXT=$(context_for '/tmp/project/openspec/changes/example/tasks.md')
assert_contains 'local openspec tasks path fires' "$TASK_CONTEXT" 'best-of-N 候選拍板'

UNRELATED_CONTEXT=$(context_for '/tmp/project/docs/design.md')
assert_silent 'unrelated path stays silent' "$UNRELATED_CONTEXT"

LEGACY_CONTEXT=$(context_for '/tmp/project/docs/superpowers/specs/example-design.md')
assert_silent 'legacy docs/superpowers boundary stays silent' "$LEGACY_CONTEXT"

SCRATCH_TICKET_CONTEXT=$(context_for '/tmp/project/.scratch/example/issues/001.md')
assert_silent 'scratch ticket path stays silent' "$SCRATCH_TICKET_CONTEXT"

printf 'RESULT %d/%d\n' "$PASSES" "$((PASSES + FAILURES))"
[ "$FAILURES" -eq 0 ]
