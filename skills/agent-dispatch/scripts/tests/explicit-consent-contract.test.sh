#!/bin/bash
set -euo pipefail

SKILL=${AGENT_DISPATCH_SKILL:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/SKILL.md}
text=$(<"$SKILL")
ROOT=$(cd "$(dirname "$SKILL")/../.." && pwd)
FAIL=0
CHECKS=0

require_text() {
  local source=$1 pattern=$2
  CHECKS=$((CHECKS + 1))
  if ! printf '%s\n' "$source" | command grep -Fq -- "$pattern"; then
    printf 'FAIL missing: %s\n' "$pattern" >&2
    FAIL=$((FAIL + 1))
  fi
}

require() {
  require_text "$text" "$1"
}

require '本檔在契約測試底下：bash ~/.claude/skills/agent-dispatch/scripts/tests/explicit-consent-contract.test.sh'
require '一般實作授權不等於 agent-dispatch 派工授權'
require '允許這次派工'
require '同意只限當次具名的任務、repo、worker 數。'
require '外殼、配方與 backend 寫在同一則同意訊息'
require '如果同意後只換配方，就告知新配方後繼續，不得重新詢問派工同意。'
require '如果同意後只換外殼，就告知新外殼後繼續，不得重新詢問派工同意。'
require '如果換到 Codex 或 pi，就在告知訊息附治理差異'
require '小改 main 自己做'
require '只有 main 能開 Herdr session；subagent、workflow agent、受委派 worker 都不開。'
require '唯讀單席不另問派工同意'
require '外部額度席未被使用者明確選定時不開'
require '同模型的搜尋或盤點用 subagent，不開 Herdr'
require '如果席位目錄沒有該席或尚未啟用，就回報該席目前不可用，不退回 headless 或換模型。'
require 'python3 scripts/open-seat.py <seat-id> <brief-file> <cwd> --log-dir <收據目錄>'
require 'python3 scripts/finish-seat.py <receipt.json>'
require '--keep-open'
require '--list'
for pattern in '--permission-mode zero-tools|codex-read-only|tool-allowlist' '--allow-tool' '--resume' '"type":"codex","model":"GPT_ASTRA"' 'config/gpt-models.env' '啟動參數＋零工具使用'; do
  require "$pattern"
done
require '--agent <agent-name>'
require '--inline-brief'
require '--agent` 搭配 `--recipe` 時，可再指定 `--model`／`--effort`'
require '--launcher <name>'
require 'launcher 不存在時不建 terminal，並指名缺哪一個'
# 04 併入後 launcher 已可用；留著舊句會讓 main 把 Gemini 席回報成不可用。
CHECKS=$((CHECKS + 1))
if printf '%s\n' "$text" | command grep -Fq -- 'Ticket 04 實作前不可用'; then
  printf 'FAIL stale: Ticket 04 實作前不可用\n' >&2
  FAIL=$((FAIL + 1))
fi

# 使用者當輪點名的 headless 呼叫照做並提醒映射；顧問建議與模糊授權不算點名。
headless_named='如果使用者在當輪明確點名要用 `claude -p`、`codex exec` 這類 headless 呼叫，就照做'
headless_warn='會繼承本 session 的模型映射'
headless_not_named='顧問建議、上一輪的指定或「用什麼都行」不算點名'
# 尚未遷移的呼叫端路徑要寫在決策點旁；只寫在 references 時，05 RED runner 把 advisor 原生 Fable 與 Codex 判成不可用。
unmigrated='尚未遷移的呼叫端既有路徑照舊'
for pattern in "$headless_named" "$headless_warn" "$headless_not_named" "$unmigrated"; do
  require "$pattern"
done
require '使用者明說「派 worker」或「用 agent-dispatch」'
require '未回覆、拒絕或取消時不派工，也不反覆遊說'
require '如果任務或 repo 改變，或 worker 數增加，就在副作用前重新取得同意。'
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

# worker 交回 main 的稽核要在 Step 4 收工前接手；放到 Step 5 以後，2026-10 的 5 次交回全沒人補（RED 2/2）。
step4=$(printf '%s' "$text" | command grep -n '^## Step 4：' | cut -d: -f1)
step5=$(printf '%s' "$text" | command grep -n '^## Step 5：' | cut -d: -f1)
[ -n "$step4" ] && [ -n "$step5" ] && [ "$step4" -lt "$step5" ] || { printf 'FAIL Step 4/5 headings missing\n' >&2; exit 1; }
step4_text=$(printf '%s\n' "$text" | sed -n "${step4},$((step5 - 1))p")
for pattern in '接手 worker 交回的稽核' 'NEEDS_DELEGATION' '不重派' '每個 skill 各派一次' '沒處理完不算收工' '每條稽核都已派出並收回結果，或已列進待拍板'; do
  printf '%s' "$step4_text" | command grep -Fq -- "$pattern" || {
    printf 'FAIL Step 4 missing: %s\n' "$pattern" >&2
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

# herdr-core (hc) 與舊版 herdr 在 Step 3-5 的讀取、送訊、關工位與續接都要對齊。
for pattern in 'hc read <pane_id>' 'hc send <pane_id>' 'hc kill <pane_id>' 'hc rm <pane_id>'; do
  require "$pattern"
done

routing=$(<"$ROOT/rules/common/terminal-backend-routing.md")
description=$(sed -n '3p' "$SKILL")
for source in "$description" "$routing"; do
  for pattern in 'HC_TERMINAL_ID' 'HERDR_PANE_ID' 'HERDR_WORKSPACE_ID' '不同模型' 'Codex／pi' 'agent-dispatch' '不必點名 Herdr'; do
    require_text "$source" "$pattern"
  done
done
for pattern in 'claude -p' 'codex exec' 'launcher 加 `-p`' '不照貼顧問給的 headless 指令' '不自寫啟動器' 'config/second-opinion-seats.json' '該席目前不可用' '不自動拉起 Herdr server' "$headless_named" "$headless_warn" "$headless_not_named" "$unmigrated"; do
  require_text "$routing" "$pattern"
done

# 第二階段後 pr-review 與 review-spec Tier 4 的 Gemini 席已走目錄席；決策點旁留著「第二階段前…」時，
# runner 會引這條例外照舊跑 headless（回歸測試），GREEN runner 也指出它與 command 新路徑矛盾。
unmigrated_now='尚未遷移的呼叫端既有路徑照舊（advisor 的原生 Fable Agent 與網頁 GPT Pro）'
session_routing=$(<"$ROOT/skills/agent-dispatch/references/session-routing.md")
forbid_text() {
  local source=$1 pattern=$2
  CHECKS=$((CHECKS + 1))
  if printf '%s\n' "$source" | command grep -Fq -- "$pattern"; then
    printf 'FAIL stale: %s\n' "$pattern" >&2
    FAIL=$((FAIL + 1))
  fi
}
for source in "$text" "$routing"; do
  require_text "$source" "$unmigrated_now"
  forbid_text "$source" '第二階段前的 pr-review'
done
for seat in review-spec-gemini-flash review-spec-gemini-pro pr-review-gemini-pro pr-review-gemini-flash; do
  require_text "$session_routing" "$seat"
done
require_text "$session_routing" '如果這兩處的席位開不起來、執行出錯或收席檢查失敗，就標該軸 FAILED，不改跑 agy 或其他無頭指令。'
forbid_text "$session_routing" 'agy 備援'
forbid_text "$session_routing" '在第二階段才遷移'

if [ "$FAIL" -ne 0 ]; then
  printf 'agent-dispatch explicit consent contract: %s failed / %s checks\n' "$FAIL" "$CHECKS" >&2
  exit 1
fi
printf 'agent-dispatch explicit consent contract: ok (%s checks)\n' "$CHECKS"
