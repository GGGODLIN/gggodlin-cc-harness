#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
COMMAND="$ROOT/commands/git-closeout.md"
PASS=0
FAIL=0

check() {
  local name="$1"
  local expected="$2"
  if [[ -f "$COMMAND" ]] && grep -qF -- "$expected" "$COMMAND"; then
    PASS=$((PASS + 1))
    printf '  ok   %s\n' "$name"
  else
    FAIL=$((FAIL + 1))
    printf '  FAIL %s\n' "$name"
  fi
}

check "標示契約測試跑法" "git-closeout-contract.test.sh"
check "只允許使用者手動觸發" "disable-model-invocation: true"
check "READY 前不開始新工作" "READY 前不開始新工作"
check "提醒不是完成判定證據" "提醒只當定位線索，不當完成證據"
check "以 python3 執行 hook 建立基準" 'JSON stdin 執行 `python3 ~/.claude/hooks/personal-main-closeout.py`'
check "remote 主幹先更新" "git fetch"
check "枚舉所有 worktree" "git worktree list --porcelain"
check "檢查每個 worktree 狀態" "每個 worktree"
check "確認沒有 active agent" "ListAgents"
check "分類需要整合的成果" "INTEGRATE"
check "分類已被取代的成果" "SUPERSEDED"
check "分類可安全移除項目" "SAFE_REMOVE"
check "分類仍在使用的項目" "ACTIVE"
check "分類無法判定項目" "AMBIGUOUS"
check "領先 commit 數不足以判斷" "領先幾個 commit 不能單獨證明"
check "破壞性操作只問一次" "一次列出所有破壞性操作"
check "安全 gate 原樣轉交" "dcg allow-once"
check "忽略清單不能拿來假綠" "不能用 ignore.jsonl 讓驗收假綠"
check "完成後用 python3 重跑 hook" '重新執行 `python3 ~/.claude/hooks/personal-main-closeout.py`'
check "hook 沉默不足以單獨宣告" "hook 沉默仍不夠"
check "READY verdict" "Git closeout：READY"
check "BLOCKED verdict" "Git closeout：BLOCKED"
check "acme 樹外的公司 repo 退出" '位於 `~/Desktop/work/*` 其他位置'
check "acme 樹下標為 work scope" '標為 **work scope**'
check "work scope trunk 取 stage" 'work scope 的 trunk 取 `origin/stage`'
check "work trunk 不用 origin/HEAD" '**不要用 `origin/HEAD`**'
check "work scope 有處置邊界" "work scope 的處置邊界"
check "work scope 不寫入部署分支" "一律不做：在 \`stage\`／\`main\`／\`master\` 上產生任何新 commit"
check "本機 commit 不算例外" "**本機 commit 同樣算**"
check "停止情況有回傳格式" "Git closeout：不適用"
check "frontmatter 涵蓋 acme 樹" '涵蓋個人 repo 與 `~/Desktop/work/acme` 樹下的公司 repo'
check "work scope 的 INTEGRATE 停在 feature branch" "work scope：把成果搬到一條活的 feature branch"
check "work scope 完成判準不靠 hook 靜默" "work scope 的完成判準不同"
check "target 都要標 scope" "每個 target 都已標記 personal 或 work scope"
check "部分掃描 fail closed" "其餘 N 個未掃"
check "~/.claude 一律納入目標" '`~/.claude` 一律納入目標'
check "枚舉含 dot-prefixed 子 repo" "dot-prefixed"
check "inventory 必讀保留 policy" '把每筆已登記的 ref 當成使用者既有的 `PRESERVE` 處置'
check "ignored 只在刪除前枚舉" "刪 worktree／目錄前，先對那個範圍跑 \`git status --porcelain=v1 --ignored --untracked-files=all\`"
check "ignored 不計入 READY" "ignored path 不計入 READY 判準"
check "busy 旗標只是線索" "不能單獨把整個 repo 判成不可收"
check "ACTIVE 只認明確保留條件" "\`ACTIVE\` 只給有明確保留條件的項目"
check "staged_differs 是保留條件" "staged_differs"
check "有保留項仍可 READY 但不寫全機乾淨" "不寫「全機乾淨」"
check "不承諾持續寫入下零 dirty" "有人持續寫入時不承諾全機零 dirty"
check "worktree lock 納入 inventory" "locked／prunable"
check "locked 不得 force remove" '不得用 `--force` 繞過 lock'
check "integration 需要 provenance" "目前 session exact paths 能證明 provenance"
check "支援明確保留處置" '`PRESERVE`'
check "mutation 前重新驗證" "每批 mutation 前"
check "狀態改變使授權失效" "使原授權失效"
check "說明不加 Self-Verify" "不加 Self-Verify"
check "dirty 反查用 provenance script" "closeout-provenance.py"
check "不對 peer 發 SendMessage" "不對任何 peer session 發 SendMessage"
check "短 id 對不上標未知" "對不上就標「未知」"
check "其他 session 的 dirty 走 SNAPSHOT" "SNAPSHOT"
check "快照以工作樹為單位" "以**工作樹為單位**整包收進 commit"
check "work scope 快照 branch" "closeout/<repo>-<YYYYMMDD>"
check "報告分已保存與原處已乾淨" "原處已乾淨"
check "報告含保留欄" "保留／收尾後新增"
check "快照 commit 前核對暫存區" "git diff --cached --name-only"

printf '\n%s PASS / %s FAIL\n' "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]]
