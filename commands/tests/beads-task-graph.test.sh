#!/bin/bash
set -uo pipefail

STATE="$HOME/.claude/commands/state-update.md"
SAVE="$HOME/.claude/commands/save-session.md"
RESUME="$HOME/.claude/commands/resume-session.md"
PASS=0
FAIL=0

check() {
  local name="$1"
  shift
  if "$@"; then
    PASS=$((PASS + 1))
    printf '  ok   %s\n' "$name"
  else
    FAIL=$((FAIL + 1))
    printf '  FAIL %s\n' "$name"
  fi
}

has() {
  grep -qF -- "$2" "$1"
}

line_of() {
  grep -nF -- "$2" "$1" | cut -d: -f1 | head -1
}

check "state frontmatter 保持第一行" test "$(python3 -c "print(open('$STATE').readline().rstrip())")" = "---"
check "save frontmatter 保持第一行" test "$(python3 -c "print(open('$SAVE').readline().rstrip())")" = "---"
check "resume frontmatter 保持第一行" test "$(python3 -c "print(open('$RESUME').readline().rstrip())")" = "---"
check "state 標示契約測試跑法" has "$STATE" "beads-task-graph.test.sh"
check "save 標示契約測試跑法" has "$SAVE" "beads-task-graph.test.sh"
check "resume 標示契約測試跑法" has "$RESUME" "beads-task-graph.test.sh"
check "state 保留至少兩支線門檻" has "$STATE" "≥2 條"
check "state 捕捉包含 Follow-ups" has "$STATE" "Follow-ups"
check "state 使用穩定 bd marker" has "$STATE" "<!-- bd:<id> -->"
check "state 全量讀取既有 beads" has "$STATE" "bd list --json --readonly --limit 0"
check "state 有 created 收據" has "$STATE" "BD_CAPTURE: created"
check "state 有 existing 收據" has "$STATE" "BD_CAPTURE: existing"
check "state 有 not-needed 收據" has "$STATE" "BD_CAPTURE: not-needed"
check "state 有 skipped-error 收據" has "$STATE" "BD_CAPTURE: skipped-error"
check "state 有 not-evaluated 收據" has "$STATE" "BD_CAPTURE: not-evaluated"
check "state 非 git 退出也有收據" has "$STATE" "not a git project"
check "state create 確認前零 mutation" has "$STATE" "確認前不得建立目錄、改 .gitignore 或寫檔"
CONFIRM_LINE=$(line_of "$STATE" "確認完整 draft 後")
MKDIR_LINE=$(line_of "$STATE" 'mkdir -p <dir>/docs/owner')
check "state create 確認早於 mkdir" bash -c "test -n '$CONFIRM_LINE' -a -n '$MKDIR_LINE' && test '$CONFIRM_LINE' -lt '$MKDIR_LINE'"
check "state stale marker 明確失敗" has "$STATE" "stale-marker"
check "state marker 回填失敗不得成功" has "$STATE" "marker-write-failed"
check "state marker 跨 row id 唯一" has "$STATE" "used_ids"
check "state preflight 早於任何 bd mutation" has "$STATE" "preflight 在任何 bd mutation 前"
check "state 預掃整份 STATE markers" has "$STATE" "整份 STATE.md 所有 marker"
check "state 精確標題多筆拒絕" has "$STATE" "ambiguous-title-match"
check "state 成功收據前驗完 markers" has "$STATE" "全部 marker 回讀驗證"
check "state 初始 Read 失敗有固定收據" has "$STATE" "BD_CAPTURE: not-evaluated STATE read failed"
check "state partial Edit 有固定退出收據" has "$STATE" "BD_CAPTURE: not-evaluated STATE patch incomplete"
check "state 無 marker 候選先完成綁定規劃" has "$STATE" "所有無 marker 候選先完成綁定規劃"
check "state 同輪同標題候選明確拒絕" has "$STATE" "duplicate-source-title"
check "state 新建 bead 同步進記憶體集合" has "$STATE" "立即加入 client-side 未關閉集合"
check "state marker-write rollback 會回讀驗證" has "$STATE" "marker-write-failed rollback"
check "state rollback 失敗會進收據" has "$STATE" "marker-write-failed rollback-failed"
DUPLICATE_TITLE_LINE=$(line_of "$STATE" "duplicate-source-title")
BD_INIT_LINE=$(line_of "$STATE" "bd init --stealth")
check "state 同輪同標題檢查早於 bd init" bash -c "test -n '$DUPLICATE_TITLE_LINE' -a -n '$BD_INIT_LINE' && test '$DUPLICATE_TITLE_LINE' -lt '$BD_INIT_LINE'"
check "save 驗收 BD_CAPTURE" has "$SAVE" "BD_CAPTURE"
check "save 缺收據時標未驗證" has "$SAVE" "beads 捕捉未驗證"
check "save 收據固定在最後一行" has "$SAVE" "最終訊息最後一行"
check "save Project 寫 owning repo 絕對路徑" has "$SAVE" "Project 欄必須寫入 owning git repo 的絕對路徑"
check "save 不包含任何 bd CLI" bash -c "! grep -qF 'bd ' '$SAVE'"
check "resume 明確 session path 的 Project 優先" has "$RESUME" "session file 的 Project 優先於 cwd"
check "resume legacy Project 不以 cwd 猜 repo" has "$RESUME" "legacy session 缺絕對 path → unresolved，不以 cwd fallback"
check "resume unresolved 明確跳過 state 與 bd" has "$RESUME" "owning project unresolved 或明確為無 → 跳過 Step 2.7 與 Step 2.8"
check "resume 不 inline 編輯 STATE" has "$RESUME" "不 inline 編輯 STATE.md"
check "resume 全量唯讀 ready" has "$RESUME" "bd ready --json --readonly --limit 0"
check "resume 另讀 deferred 供到期判斷" has "$RESUME" "bd list --json --readonly --limit 0 --status deferred"
check "resume 排除未到 defer 日期" has "$RESUME" "defer_until"
check "resume 使用台北日曆日期" has "$RESUME" "Asia/Taipei"
check "resume malformed defer 不冒充空資料" has "$RESUME" "defer-parse-failed"
check "resume 單一來源失敗會顯示警告" has "$RESUME" "BD 讀取不完整"
check "resume 最多顯示三筆" has "$RESUME" "最多 3 筆"
check "resume 回報其餘數量" has "$RESUME" "其餘"
RESUME_BD_COMMANDS=$(grep -oE 'bd [a-z][a-z-]*' "$RESUME" | grep -vF 'bd task-graph' | sort -u | tr '\n' '|')
check "resume 的 bd CLI 只有 ready/list" test "$RESUME_BD_COMMANDS" = "bd list|bd ready|"
check "resume 不含帶 global option 的 bd CLI" bash -c "! grep -qE 'bd -' '$RESUME'"
check "state 是唯一 mutation owner" has "$STATE" "bd create"
check "state stall 計數步驟存在" has "$STATE" "Stall 計數維護"
check "state Edit 成功後接 stall 步驟" has "$STATE" "Step 7.5（stall 計數維護）"
check "state stall marker 格式固定" has "$STATE" "<!-- stall:N -->"
check "state 被更新 row 歸零" has "$STATE" "移除其 stall marker"
check "state 拒絕 patch 不計輪" has "$STATE" "本輪不計、不動任何 marker"
check "resume 掃 stall marker" has "$RESUME" "<!-- stall:N -->"
check "resume stall 閾值為 3" has "$RESUME" "N ≥ 3"
check "resume stall 升級為固定問句" has "$RESUME" "這條卡 N 輪了：繼續等／改路／砍掉？"
check "resume stall 問句附不動作後果" has "$RESUME" "一句不動作的後果"
check "resume stall 與 bd 解耦" has "$RESUME" "不存在也照跑"
STATE_UPDATE_RETURN_LINE=$(line_of "$RESUME" 'After `/state-update` returns')
FINAL_STALL_READ_LINE=$(line_of "$RESUME" "重新 Read 最終 STATE.md")
check "resume stall 最終掃描在 state-update 返回後" bash -c "test -n '$STATE_UPDATE_RETURN_LINE' -a -n '$FINAL_STALL_READ_LINE' && test '$FINAL_STALL_READ_LINE' -gt '$STATE_UPDATE_RETURN_LINE'"
check "resume 明寫重新讀最終 STATE" has "$RESUME" "重新 Read 最終 STATE.md"
check "resume stall 不沿用 Step 2.5 舊快照" has "$RESUME" "不得沿用 Step 2.5 的舊快照"
check "resume 舊 stall2 本輪升 3 必提醒" has "$RESUME" '舊 `stall:2` 更新成 `stall:3`，本輪必須提醒'
check "resume 舊 stall3 本輪移除不得提醒" has "$RESUME" '舊 `stall:3` marker 被移除，本輪不得提醒'

printf '\n%s PASS / %s FAIL\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
