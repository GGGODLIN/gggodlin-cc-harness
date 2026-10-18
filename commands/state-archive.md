---
description: Feature 完成前 ritual — 把 STATE.md 重要決策 promote 到永久 artifact，然後顯式 reset STATE.md（gitignored 單檔，不依賴 worktree 消失）
---

<!-- 本檔在契約測試底下：bash ~/.claude/commands/tests/state-archive-contract.test.sh -->

> 帳本生命週期：規則見 `~/.claude/references/ledger-lifecycle.md`；門檻以 `~/.claude/scripts/ledger-lifecycle/registry.json` 為準。

# State Archive

`docs/owner/STATE.md` 是 ephemeral scratchpad，feature 完成前要把重要內容 promote 到永久 artifact。

> **前提（容易踩的坑）**：`docs/owner/STATE.md` 是 **gitignored 單檔、跨 branch 共用**。普通 branch（非 git worktree）切走 / merge 後它**不會自己消失**，會帶著舊內容被下個 session 載入，handoff 指向一個已 merge 的舊 change。所以本 ritual **必須顯式 reset 它**（步驟 5），不能靠 worktree 一起消失。

> **cwd 假設**：本 command 假設當前 cwd = 目標專案 dir（直接讀寫 `docs/owner/STATE.md`）。若在別的 worktree 跑 `/state-archive`，先 `cd` 到目標專案 dir 再 invoke（未來若加 `<dir>` arg 支援對齊 `/state-update` 收 arg 的行為、參見 [state-update.md](./state-update.md)）。

## 流程

1. **Read** `docs/owner/STATE.md`，掃三段：
   - Recent Decisions
   - Blockers（已解決的）
   - Resume Notes（裡面可能有 learning）
   - 若 `docs/owner/STATE.md` 不存在，回報 `STATE_ARCHIVE: NOT_APPLICABLE missing docs/owner/STATE.md` 並停止本 command；這個 backstop 不適用其他 STATE 路徑
   - Read 成功後接 **Step 1.5（ADR lifecycle preflight）**

1.5. **ADR lifecycle preflight（任何 promote、STATE reset、worktree cleanup 前）**：
   - 只在既有 `docs/owner/STATE.md` 存在且 Read 成功時執行；preflight 只讀 Git 與 decision sources，暫存檔只放在系統 temp directory，不改 STATE 或其他 durable artifact
   - 直接執行下列固定 script。`ROOT` 是當前 cwd，`openspec/decisions/` 是唯一 decision directory；不要改成掃其他路徑或整個 decision corpus

```bash
STATE_ARCHIVE_PREFLIGHT_SCRIPT=1
set -u -o pipefail
ROOT=$(pwd -P)
GIT=(env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE git -C "$ROOT" -c core.fsmonitor=false --work-tree="$ROOT")
DECISION_PATH='openspec/decisions'
STATE_PATH="$ROOT/docs/owner/STATE.md"
CHECKER="${HOME:-}/.claude/skills/domain-modeling/scripts/check-decisions"
BLOCKED() {
  printf 'STATE_ARCHIVE: BLOCKED %s\n' "$1"
  exit 1
}
if [[ ! -f "$STATE_PATH" ]]; then
  printf '%s\n' 'STATE_ARCHIVE: NOT_APPLICABLE missing docs/owner/STATE.md'
  exit 0
fi
if ! "${GIT[@]}" rev-parse --git-dir >/dev/null 2>&1; then
  BLOCKED 'change-set detection failure: not a git project'
fi
if [[ -e "$ROOT/$DECISION_PATH" && ! -d "$ROOT/$DECISION_PATH" ]]; then
  BLOCKED 'decision path is not a directory'
fi
if [[ ! -e "$ROOT/$DECISION_PATH" ]] && [[ -z "$("${GIT[@]}" log --all --format=%H -n 1 -- "$DECISION_PATH" 2>/dev/null)" ]]; then
  # 目錄不存在、而且整個 repo 歷史從未碰過這個路徑 ⇒ 不可能有 numbered ADR 來源，remote 與 merge-base 不需要解析。
  # 只看工作樹不夠：整批 ADR 被 git rm 後目錄也會消失，那種情況要照原流程走到 rename/delete 的 BLOCKED
  printf '%s\n' 'STATE_ARCHIVE: no decision changes; checker skipped'
  exit 0
fi
resolve_remote_default_ref() {
  local ref branch
  ref=$("${GIT[@]}" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null) || ref=''
  if [[ -n "$ref" ]]; then
    "${GIT[@]}" rev-parse --verify --quiet "$ref" >/dev/null || return 1
    printf '%s\n' "$ref"
    return 0
  fi
  branch=$("${GIT[@]}" remote show -n origin 2>/dev/null | sed -n 's/^[[:space:]]*HEAD branch: //p' | head -1) || return 1
  [[ -n "$branch" && "$branch" != '(unknown)' ]] || return 1
  ref="origin/$branch"
  "${GIT[@]}" rev-parse --verify --quiet "$ref" >/dev/null || return 1
  printf '%s\n' "$ref"
}
REMOTE_DEFAULT_REF=$(resolve_remote_default_ref) || BLOCKED 'remote default ref unresolved'
BASE=$("${GIT[@]}" merge-base "$REMOTE_DEFAULT_REF" HEAD 2>/dev/null) || BLOCKED 'merge-base unresolved'
[[ -n "$BASE" ]] || BLOCKED 'merge-base unresolved'
STATUS_DIR=$(mktemp -d "${TMPDIR:-/tmp}/state-archive.XXXXXX") || BLOCKED 'change-set detection failure: temp directory'
trap 'rm -rf "$STATUS_DIR"' EXIT
SOURCES=()
is_numbered() {
  [[ "$1" =~ ^openspec/decisions/[0-9]+-[^/]+\.md$ ]]
}
add_source() {
  local candidate="$ROOT/$1"
  local existing
  if [[ "${#SOURCES[@]}" -gt 0 ]]; then
    for existing in "${SOURCES[@]}"; do
      if [[ "$existing" == "$candidate" ]]; then
        return
      fi
    done
  fi
  SOURCES[${#SOURCES[@]}]="$candidate"
}
collect_diff() {
  local label="$1"
  shift
  local output="$STATUS_DIR/$label"
  if ! "$@" > "$output"; then
    BLOCKED "change-set detection failure: $label"
  fi
}
collect_diff indexed "${GIT[@]}" diff --cached --name-status -z --find-renames "$BASE" -- "$DECISION_PATH"
collect_diff unstaged "${GIT[@]}" diff --name-status -z --find-renames -- "$DECISION_PATH"
if ! "${GIT[@]}" ls-files --others -z -- "$DECISION_PATH" > "$STATUS_DIR/untracked"; then
  BLOCKED 'change-set detection failure: untracked'
fi
inspect_diff() {
  local file="$1"
  local status first second
  while IFS= read -r -d '' status; do
    IFS= read -r -d '' first || return 1
    second=''
    case "${status:0:1}" in
      R|C)
        IFS= read -r -d '' second || return 1
        ;;
    esac
    case "${status:0:1}" in
      A|M)
        if is_numbered "$first"; then
          add_source "$first"
        fi
        ;;
      D)
        if is_numbered "$first"; then
          BLOCKED "numbered ADR rename/delete: $first"
        fi
        ;;
      R)
        if is_numbered "$first" || is_numbered "$second"; then
          BLOCKED "numbered ADR rename/delete: $first -> $second"
        fi
        ;;
      *)
        if is_numbered "$first" || is_numbered "$second"; then
          BLOCKED "change-set detection failure: unsupported status $status"
        fi
        ;;
    esac
  done < "$file"
}
if ! inspect_diff "$STATUS_DIR/indexed"; then
  BLOCKED 'change-set detection failure: indexed parse'
fi
if ! inspect_diff "$STATUS_DIR/unstaged"; then
  BLOCKED 'change-set detection failure: unstaged parse'
fi
while IFS= read -r -d '' path; do
  if is_numbered "$path"; then
    add_source "$path"
  fi
done < "$STATUS_DIR/untracked"
if [[ "${#SOURCES[@]}" -eq 0 ]]; then
  printf '%s\n' 'STATE_ARCHIVE: no decision changes; checker skipped'
  exit 0
fi
if [[ ! -x "$CHECKER" ]]; then
  BLOCKED 'checker executable missing'
fi
"$CHECKER" "$ROOT/$DECISION_PATH" "${SOURCES[@]}"
CHECKER_RC=$?
if [[ "$CHECKER_RC" -ne 0 ]]; then
  BLOCKED "checker exit $CHECKER_RC"
fi
printf '%s\n' 'STATE_ARCHIVE: ADR preflight PASS'
exit 0
```

   - Git 固定清除 `GIT_DIR`／`GIT_WORK_TREE`／`GIT_INDEX_FILE`，綁定 canonical `ROOT` worktree 並停用 `core.fsmonitor`；`REMOTE_DEFAULT_REF` 與 merge-base 任一步失敗都是 `BLOCKED`（只在 `openspec/decisions/` 目錄存在時解析）
   - `openspec/decisions/` 不存在**且 repo 歷史從未有過這個路徑**（`git log --all -- openspec/decisions` 空；例如只放私人治理檔、沒有 remote 的 acme 父層）時直接輸出 `STATE_ARCHIVE: no decision changes; checker skipped`，不解析 remote 預設分支與 merge-base——沒有目錄又沒有歷史就不可能有 numbered ADR 來源。目錄在工作樹消失但歷史有它（整批 ADR 被刪）仍走原流程、照樣 `BLOCKED`；路徑存在但不是目錄仍 `BLOCKED`（2026-10-13 起）
   - source set 是三批 NUL-delimited 結果的 union：`BASE..index` committed＋staged A/M、unstaged A/M、untracked A（含 ignored）；只收直接位於 `openspec/decisions/` 且符合 numbered ADR filename 的來源
   - numbered ADR rename／delete、decision path 變成非 directory、change-set detection failure、checker missing executable，或 checker 任一非零 exit 都 `BLOCKED`
   - 有 source changes 時 checker 只收到 deduplicated changed source files；沒有 decision changes 時輸出 `STATE_ARCHIVE: no decision changes; checker skipped`，不呼叫 checker，因此 unchanged legacy violation 不阻擋
   - `BLOCKED` 時保留 `docs/owner/STATE.md` bytes 原樣，停止後續 promote、STATE reset 與 worktree cleanup；這些 durable mutation 不得先做
   - `STATE_ARCHIVE: ADR preflight PASS` 或 no-change skip 才接 **Step 2**；`BLOCKED` 不得接 Step 2、Step 5 或 Step 6

2. **逐項分類 + 提議 promote 目標**：

   | STATE.md 內容類型 | Promote 到 |
   |---|---|
   | 設計決策（為什麼選 A 不選 B）| `openspec/changes/<change>/design.md` |
   | Spec 變更影響（API / schema 改了什麼）| `openspec/changes/<change>/proposal.md` |
   | 為什麼這樣做 + trade-off | Commit message body 或 PR description |
   | 個人 learning（踩坑、新工具發現）| `~/.claude/wiki/` 或 memory（提議 invoke `/wiki-promote` 或建 memory entry）|
   | 純 process 細節（debug 流水帳 / 上次停哪）| 不 promote，STATE.md reset 時丟棄 |

3. **對每項問使用者要不要 promote**，逐項 confirm。

4. **Confirm 後執行**：
   - OpenSpec target：Read 現有 `design.md` / `proposal.md`，Edit append section
   - Commit message：output 文字給使用者貼到下次 commit
   - Wiki / memory：提示使用者 invoke 對應 skill（不自動寫 wiki，那是 user-triggered）
   - 完成後接步驟 5 reset STATE.md，不要在 promote 問完就停

5. **顯式 reset `docs/owner/STATE.md`（不依賴 worktree，不可跳過）**：
   - 確認步驟 2-4 的 promote 已完成（決策已落 durable 層）
   - **Carry-over 掃描（reset 前必跑）**：grep frontmatter 找欄位值含「carry-over」標記者（如 `standing_pointer:`），這些欄位**原樣帶進 reset 後的新檔**——重 init 與清空兩條路都適用，不隨 reset 丟棄。找到 0 個 → 明說「無 carry-over 欄位」再往下
   - 問使用者：下一個 active change 是什麼？
     - **有下一個 change** → 用 `/state-update` 的 `## Template（新建用）` 段（`~/.claude/commands/state-update.md`）把 STATE.md **重 init** 成那個 change（`current_change` / `status` / Resume Notes 全換新）
     - **沒有下一個 change** → 清空成 `current_change: none` frontmatter + 一行「上一個 change 已 archive，無 active work」
   - 這步爛掉就是這個 ritual 過去的根因：gitignored 單檔、普通 branch 切走不帶走它，不顯式 reset 下個 session handoff 就指向已 merge 的舊 change

6. **完成後問是否清理 worktree**（僅當真的在 worktree）：
   - 跑 `git worktree list` 確認當前是 worktree（不是 main checkout）
   - 是 worktree → 提示「Feature merged 了？要 `git worktree remove <path>` 清掉嗎？」
   - 不是 worktree → 跳過（STATE.md 已在步驟 5 顯式 reset，不靠 worktree 消失）

## 規則

- 不自動 commit
- 不自動 `git worktree remove`（destructive，等 user 點頭）
- 不寫 wiki（user-triggered only，呼應 [feedback_memory_to_wiki_promotion.md](file://~/.claude/memory/feedback_memory_to_wiki_promotion.md)）
