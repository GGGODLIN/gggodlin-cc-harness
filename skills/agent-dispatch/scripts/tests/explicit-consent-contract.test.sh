#!/bin/bash
set -euo pipefail

SKILL=${AGENT_DISPATCH_SKILL:-/Users/you/.claude/skills/agent-dispatch/SKILL.md}
text=$(<"$SKILL")

require() {
  local pattern=$1
  printf '%s' "$text" | command grep -Fq -- "$pattern" || {
    printf 'FAIL missing: %s\n' "$pattern" >&2
    exit 1
  }
}

require '本檔在契約測試底下：bash ~/.claude/skills/agent-dispatch/scripts/tests/explicit-consent-contract.test.sh'
require '一般實作授權不等於 agent-dispatch 派工授權'
require '允許這次派工'
require '同意只限當次具名的任務、repo、worker 數、model 與 backend'
require '使用者明說「派 worker」或「用 agent-dispatch」'
require '未回覆、拒絕或取消時不派工，也不反覆遊說'
require '任務、repo、worker 數、model 或 backend 任一增加或改變時，重新取得同意'
require '建立 worktree、寫 brief、建立收據目錄或啟動 worker 之前'

step0=$(printf '%s' "$text" | command grep -n '^## Step 0：' | cut -d: -f1)
step1=$(printf '%s' "$text" | command grep -n '^## Step 1：' | cut -d: -f1)
[ -n "$step0" ] && [ -n "$step1" ] && [ "$step0" -lt "$step1" ] || {
  printf 'FAIL consent gate must precede Step 1 side effects\n' >&2
  exit 1
}

printf 'agent-dispatch explicit consent contract: ok\n'
