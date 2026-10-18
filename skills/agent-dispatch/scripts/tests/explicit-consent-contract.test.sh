#!/bin/bash
set -euo pipefail

SKILL=${AGENT_DISPATCH_SKILL:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/SKILL.md}
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
require '同意只限當次具名的任務、repo、worker 數、外殼、配方與 backend'
require '使用者明說「派 worker」或「用 agent-dispatch」'
require '未回覆、拒絕或取消時不派工，也不反覆遊說'
require '任務、repo、worker 數、外殼、配方或 backend 任一增加或改變時，重新取得同意'
require '建立 worktree、寫 brief、建立收據目錄或啟動 worker 之前'

step0=$(printf '%s' "$text" | command grep -n '^## Step 0：' | cut -d: -f1)
step1=$(printf '%s' "$text" | command grep -n '^## Step 1：' | cut -d: -f1)
[ -n "$step0" ] && [ -n "$step1" ] && [ "$step0" -lt "$step1" ] || {
  printf 'FAIL consent gate must precede Step 1 side effects\n' >&2
  exit 1
}

# Codex／pi 的治理差異與推薦表指針要在同意訊息的決策點上，放到其他段落等於沒寫。
step0_text=$(printf '%s\n' "$text" | sed -n "${step0},$((step1 - 1))p")
for pattern in '不套用 repo 的 Claude Code hook、skill 與 settings' 'references/harness-recommendations.md' '未拍板'; do
  printf '%s' "$step0_text" | command grep -Fq -- "$pattern" || {
    printf 'FAIL Step 0 missing: %s\n' "$pattern" >&2
    exit 1
  }
done

table="$(dirname "$SKILL")/references/harness-recommendations.md"
[ -f "$table" ] || { printf 'FAIL missing recommendation table: %s\n' "$table" >&2; exit 1; }
rows=$(command grep -E '^\| [^-|]' "$table" | sed 1d)
[ -n "$rows" ] || { printf 'FAIL recommendation table has no rows\n' >&2; exit 1; }
command grep -Fq '| 模型 | 推薦外殼 | 理由 | 證據強度 | 出處 |' "$table" || { printf 'FAIL recommendation table header changed\n' >&2; exit 1; }
while IFS= read -r row; do
  printf '%s' "$row" | command grep -Fq '未拍板' || { printf 'FAIL row not labeled 未拍板: %s\n' "$row" >&2; exit 1; }
  [ "$(printf '%s' "$row" | awk -F'|' '{print NF}')" -eq 7 ] || { printf 'FAIL row needs five filled columns: %s\n' "$row" >&2; exit 1; }
  case "$row" in
    '| Opus'*) printf '%s' "$row" | awk -F'|' '{gsub(/^ +| +$/, "", $3); exit ($3 == "Claude Code") ? 0 : 1}' || { printf 'FAIL Opus row must recommend Claude Code only\n' >&2; exit 1; } ;;
  esac
done <<< "$rows"

printf 'agent-dispatch explicit consent contract: ok\n'
