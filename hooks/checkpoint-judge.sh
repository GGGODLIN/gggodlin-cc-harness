#!/bin/bash
# checkpoint-judge.sh — Stop hook for user-explicit memory/closeout requests and unclosed completion turns
# 本檔在契約測試底下：bash ~/.claude/hooks/checkpoint-judge.test.sh
#
# Threat model（防漂移／提示型偏安全 Stop gate）：
# - 對誰有效：防誠實但健忘的 main session 在兩類時機漏做記憶回看或 Git 收尾檢查：
#   (1) 使用者明示「收尾／結案／記下來」等關鍵字；
#   (2) 本場對話已執行 git commit 或對專案檔執行 Edit/Write 留有髒變更、尚未跑 closeout-provenance.py（/self-closeout），
#       且當輪回覆為一般完成報告時，單次補提醒。
# - 明文不保證（Non-promises）：
#   1. 字串比對不承諾完整語意理解，只認常見完成字樣、狀態行與結尾問句；會攔到未放進程式碼區塊（```）或引言（>）的完成敘述文字
#      （替代路徑：依 /self-closeout 完成收尾、輸出 Git closeout：READY／BLOCKED，或在狀態行明寫目前／下一步）。
#   2. 不防主動規避（如偽造完成標記或句尾塞問號）；背景任務執行中、結尾有待答問題或 subagent Stop 一律放行。
#   3. 與 opus-chinese-stop.py（僅注入 additionalContext、不 block）同輪並存時不互讓、不跳過。
#
# Surface 四分表：
# - Locked: ~/.claude/hooks/checkpoint-judge.sh、~/.claude/hooks/checkpoint-judge.test.sh、~/.claude/hooks/memory_reminder_common.py
# - Editable: hooks/state 下各 session 的 sentinel 狀態檔
# - Append-only: ~/.claude/hooks/state/checkpoint.log
# - Human-controlled: ~/.claude/settings.json hooks 註冊、停用開關 GIT_CLOSEOUT_DISABLE=1 與 ~/.claude/hooks/.git-closeout-disabled
#
# Locked 自身三路徑：
# - bootstrap: 先跑過 checkpoint-judge.test.sh 全數測資，再掛入 ~/.claude/settings.json Stop 段
# - update: 本檔只掛 Stop，不攔 Edit/Write/Bash 更新自身、helper 或測試檔
# - recovery: 設 GIT_CLOSEOUT_DISABLE=1 或建立 ~/.claude/hooks/.git-closeout-disabled 可立即停用 Git closeout 探針與自動完成攔截
#
# 繞行場景表與 Stop loop guard：
# 1. 同回合重入死鎖 → TRIGGER_SENTINEL 依 USER_TURNS 去重，同回合第二次 Stop 必放行
# 2. 後續純問答反覆誤攔 → closeout_<session> 綁定對話內最近一次 commit/edit 序號 work_seq，無新修改／提交不重攔
# 3. 唯讀問答踩到共用工作樹既有髒檔 → 僅在本場 transcript 有未收尾 commit，或本場親手 Edit/Write 的非暫存檔仍 dirty 時才觸發
# 4. 病態 state 檔（symlink／FIFO／hardlink） → O_NOFOLLOW + O_NONBLOCK + S_ISREG 檢查，拒寫且不阻塞 Stop
#
# Contextual filter classify LAST_USER → silent / long / short
#   silent: 含問號 AND 長度 > 12 (討論結案 topic 而非真結案)
#   long:   短(<15) + 肯定詞開頭 + 無問號 + 同 session 第一次 OR > 50 turn ago
#   short:  其餘 ambiguous OR long-fire 過 50 turn 內 refresh window
#   compact 或規則檔更新後，下次符合觸發條件時會重新出 long 版。

INPUT=$(cat)
SESSION_ID=""
TRANSCRIPT=""
CWD=""
AGENT_ID=""
{
  IFS= read -r -d '' SESSION_ID
  IFS= read -r -d '' TRANSCRIPT
  IFS= read -r -d '' CWD
  IFS= read -r -d '' AGENT_ID
} < <(printf '%s' "$INPUT" | jq -j '
  if type == "object" then
    (if (.session_id? | type) == "string" then .session_id else "" end), "\u0000",
    (if (.transcript_path? | type) == "string" then .transcript_path else "" end), "\u0000",
    (if (.cwd? | type) == "string" then .cwd else "" end), "\u0000",
    (if (.agent_id? | type) == "string" then .agent_id else "" end), "\u0000"
  else empty end
' 2>/dev/null)
export GIT_OPTIONAL_LOCKS=0

[ -z "$SESSION_ID" ] && exit 0
[[ "$SESSION_ID" =~ ^[A-Za-z0-9_-]{1,128}$ ]] || exit 0
[ -n "$AGENT_ID" ] && exit 0
[ -z "$TRANSCRIPT" ] || [ ! -f "$TRANSCRIPT" ] && exit 0

HOME_DIR="${HOME:-/tmp}"
SENTINEL_DIR="$HOME_DIR/.claude/hooks/state"
mkdir -p "$SENTINEL_DIR" 2>/dev/null || true
LOG="$SENTINEL_DIR/checkpoint.log"
RULE_FILE="$HOME_DIR/.claude/memory/feedback_memory_cluster_maintenance.md"
MEMORY_HELPER="$(dirname "$0")/memory_reminder_common.py"
REFRESH_WINDOW=50

log() {
  [ -L "$LOG" ] || [ -p "$LOG" ] && return 0
  printf '{"ts":"%s","session_id":"%s","action":"%s"%s}\n' \
    "$(date -u +%FT%TZ)" "$SESSION_ID" "$1" "$2" >> "$LOG" 2>/dev/null || true
}

# Defense 0: non-GPT vendor session skip
CC_VENDOR_VALUE="${CC_VENDOR:-}"
if [[ -n "$CC_VENDOR_VALUE" && "$CC_VENDOR_VALUE" != "gpt" ]]; then
  log "vendor_skip" ",\"vendor\":\"$CC_VENDOR_VALUE\""
  exit 0
fi

SENTINEL="$SENTINEL_DIR/checkpoint_${SESSION_ID}"
LONG_SENTINEL="$SENTINEL_DIR/long_injected_${SESSION_ID}"
TRIGGER_SENTINEL="$SENTINEL_DIR/trigger_${SESSION_ID}"
AUTO_CLOSEOUT_SENTINEL="$SENTINEL_DIR/closeout_${SESSION_ID}"

USER_TURNS="0"
LAST_USER=""
{
  IFS= read -r -d '' USER_TURNS
  IFS= read -r -d '' LAST_USER
} < <(python3 -I - "$TRANSCRIPT" <<'PY' 2>/dev/null
import json, sys
turns = 0
last_user = ""
try:
  with open(sys.argv[1], "r", encoding="utf-8", errors="replace") as fh:
    for line in fh:
      if '"user"' not in line:
        continue
      try:
        obj = json.loads(line)
      except ValueError:
        continue
      if not isinstance(obj, dict) or obj.get("type") != "user" or obj.get("isMeta"):
        continue
      msg = obj.get("message")
      if isinstance(msg, dict) and isinstance(msg.get("content"), str):
        turns += 1
        last_user = msg["content"]
except OSError:
  pass
sys.stdout.write(f"{turns}\0{last_user}\0")
PY
)
[[ "$USER_TURNS" =~ ^[0-9]+$ ]] || USER_TURNS=0
LAST_LONG=$(python3 "$MEMORY_HELPER" last-long --session "$SESSION_ID" --turns "$USER_TURNS" --transcript "$TRANSCRIPT" 2>/dev/null || echo 0)
[[ "$LAST_LONG" =~ ^[0-9]+$ ]] || LAST_LONG=0
LAST_TRIGGER=$(cat "$TRIGGER_SENTINEL" 2>/dev/null || echo 0)
[[ "$LAST_TRIGGER" =~ ^-?[0-9]+$ ]] || LAST_TRIGGER=0

# Contextual classifier: silent / long / short
classify_context() {
  local last_user="$1"
  local msg_len=${#last_user}
  local has_question=0
  if echo "$last_user" | grep -qE '？|\?'; then
    has_question=1
  fi
  local is_short_affirmative=0
  # macOS bash ${#var} = char count、threshold 按 char 算（中文一字 1 char）
  if [ "$msg_len" -lt 15 ] && echo "$last_user" | head -c 12 | grep -qiE '^(行|好|ok|可以|對|嗯|那|就|刪|不|沒問題|這樣|紀錄|記下|結案|收尾|收掉|歸檔|記下來|存起來)'; then
    is_short_affirmative=1
  fi

  # Rule B silent: 含問號 + 長度 > 12 char → 討論型疑問
  if [ "$has_question" = "1" ] && [ "$msg_len" -gt 12 ]; then
    echo "silent"
    return
  fi

  # Rule A long: 短肯定 + 無問號 + 同 session 第一次 OR > REFRESH_WINDOW
  if [ "$is_short_affirmative" = "1" ] && [ "$has_question" = "0" ]; then
    if [ "$LAST_LONG" = "0" ] || [ "$USER_TURNS" -gt "$((LAST_LONG + REFRESH_WINDOW))" ]; then
      echo "long"
      return
    fi
    echo "short"
    return
  fi

  # Rule C short: 其餘 ambiguous
  echo "short"
}

# 與自動入口共用記憶規範；helper 出錯不抹掉手動要求。
build_long_reason() {
  python3 "$MEMORY_HELPER" long --prefix "$1" 2>/dev/null ||
    printf '%s\n\n先查既有 memory；寫前讀 %s 的 Tier 1，決定更新／新增／skip。' "$1" "$RULE_FILE" | jq -Rs .
}

build_short_reason() {
  python3 "$MEMORY_HELPER" short --prefix "$1" --last-long "$LAST_LONG" 2>/dev/null ||
    printf '%s\n\n先查既有 memory；寫前讀 %s 的 Tier 1，決定更新／新增／skip。' "$1" "$RULE_FILE" | jq -Rs .
}

git_path_in_root() {
  local path="$1"
  local root="$2"
  if [ -d "$path" ]; then
    path=$(cd "$path" 2>/dev/null && pwd -P) || return 1
  fi
  if [ -d "$root" ]; then
    root=$(cd "$root" 2>/dev/null && pwd -P) || return 1
  fi
  case "$path/" in
    "$root"|"$root/"*) return 0 ;;
  esac
  return 1
}

git_common_dir_for_cwd() {
  local cwd="$1"
  local common_dir
  common_dir=$(git -C "$cwd" rev-parse --git-common-dir 2>/dev/null) || return 1
  case "$common_dir" in
    /*) ;;
    *) common_dir="$cwd/$common_dir" ;;
  esac
  if [ -d "$common_dir" ]; then
    (cd "$common_dir" 2>/dev/null && pwd -P) || return 1
  else
    printf '%s' "$common_dir"
  fi
}

git_scope_for_cwd() {
  local cwd="$1"
  local common_dir acme_git
  common_dir=$(git_common_dir_for_cwd "$cwd") || return 1
  if [ -d "$HOME/Desktop/work/acme/.git" ]; then
    acme_git=$(cd "$HOME/Desktop/work/acme/.git" 2>/dev/null && pwd -P) || acme_git=""
    if [ -n "$acme_git" ] && [ "$common_dir" = "$acme_git" ]; then
      printf 'personal'
      return 0
    fi
  fi
  if git_path_in_root "$common_dir" "$HOME/Desktop/work"; then
    printf 'company'
  elif git_path_in_root "$common_dir" "$HOME/Desktop/projects" || git_path_in_root "$common_dir" "$HOME/.claude" || git_path_in_root "$common_dir" "$HOME/code/social-info"; then
    printf 'personal'
  else
    printf 'unknown'
  fi
}

git_limited_lines() {
  local input="$1"
  local limit="$2"
  local mode="${3:-}"
  local count=0
  local line
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    count=$((count + 1))
    if [ "$count" -le "$limit" ]; then
      if [ "$mode" = "dirty" ]; then
        line="${line#?? }"
      fi
      printf '  - %s\n' "$line"
    fi
  done <<EOF
$input
EOF
  if [ "$count" -gt "$limit" ]; then
    printf '  - truncated: %s additional item(s)\n' "$((count - limit))"
  fi
}

git_limited_worktrees() {
  local input="$1"
  local limit="$2"
  local count=0
  local current_path=""
  local current_branch="detached HEAD"
  local line

  emit_worktree() {
    if [ -z "$current_path" ]; then
      return
    fi
    if [ "$count" -le "$limit" ]; then
      printf '  - %s (branch: %s)\n' "$current_path" "$current_branch"
    fi
  }

  while IFS= read -r line; do
    case "$line" in
      worktree\ *)
        if [ -n "$current_path" ]; then
          emit_worktree
        fi
        count=$((count + 1))
        current_path="${line#worktree }"
        current_branch="detached HEAD"
        ;;
      branch\ *) current_branch="${line#branch refs/heads/}" ;;
      detached) current_branch="detached HEAD" ;;
    esac
  done <<EOF
$input
EOF
  emit_worktree
  if [ "$count" -gt "$limit" ]; then
    printf '  - truncated: %s additional item(s)\n' "$((count - limit))"
  fi
}

git_cap_summary() {
  local input="$1"
  local limit=8192
  local reserve=64
  local total=0
  local truncated=0
  local line
  local bytes

  while IFS= read -r line; do
    bytes=$(printf '%s\n' "$line" | wc -c | tr -d ' ')
    if [ $((total + bytes + reserve)) -le "$limit" ]; then
      printf '%s\n' "$line"
      total=$((total + bytes))
    else
      truncated=1
    fi
  done <<EOF
$input
EOF
  if [ "$truncated" = "1" ]; then
    printf 'truncated: dynamic Git content exceeded %s bytes\n' "$limit"
  fi
}

git_readonly_summary() {
  local cwd="$1"
  local repo_root
  local common_dir
  local head
  local branch
  local scope
  local dirty_output
  local dirty_count
  local stash_output
  local stash_count
  local worktree_output
  local worktree_count
  local upstream
  local ahead
  local behind

  repo_root=$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null) || return 1
  common_dir=$(git_common_dir_for_cwd "$cwd") || return 1
  head=$(git -C "$cwd" rev-parse HEAD 2>/dev/null) || return 1
  branch=$(git -C "$cwd" symbolic-ref --quiet --short HEAD 2>/dev/null || printf 'detached HEAD')
  scope=$(git_scope_for_cwd "$cwd" 2>/dev/null || printf 'unknown')
  dirty_output=$(git -C "$cwd" status --short --untracked-files=all 2>/dev/null) || return 1
  if [ -n "$dirty_output" ]; then
    dirty_count=$(printf '%s\n' "$dirty_output" | wc -l | tr -d ' ')
  else
    dirty_count=0
  fi
  stash_output=$(git -C "$cwd" stash list --format='%gd %s' 2>/dev/null) || return 1
  if [ -n "$stash_output" ]; then
    stash_count=$(printf '%s\n' "$stash_output" | wc -l | tr -d ' ')
  else
    stash_count=0
  fi
  worktree_output=$(git -C "$cwd" worktree list --porcelain 2>/dev/null) || return 1
  worktree_count=$(printf '%s\n' "$worktree_output" | grep -c '^worktree ' 2>/dev/null || true)
  upstream=$(git -C "$cwd" rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null || true)
  ahead=0
  behind=0
  if [ -n "$upstream" ]; then
    ahead=$(git -C "$cwd" rev-list --count "$upstream..HEAD" 2>/dev/null) || return 1
    behind=$(git -C "$cwd" rev-list --count "HEAD..$upstream" 2>/dev/null) || return 1
  fi

  printf 'Git closeout 摘要（read-only）\n'
  printf 'scope: %s\n' "$scope"
  printf 'repo root: %s\n' "$repo_root"
  printf 'Git common dir: %s\n' "$common_dir"
  printf 'HEAD: %s\n' "$head"
  printf 'branch: %s\n' "$branch"
  printf 'dirty count: %s\n' "$dirty_count"
  printf 'stash count: %s\n' "$stash_count"
  printf 'worktree count: %s\n' "$worktree_count"
  printf 'cached tracking ref ahead: %s\n' "$ahead"
  printf 'cached tracking ref behind: %s\n' "$behind"
  if [ "$dirty_count" -gt 0 ]; then
    printf 'dirty paths:\n'
    git_limited_lines "$dirty_output" 20 dirty
  fi
  if [ "$stash_count" -gt 0 ]; then
    printf 'stash entries:\n'
    git_limited_lines "$stash_output" 5
  fi
  printf 'worktrees:\n'
  git_limited_worktrees "$worktree_output" 5
}

kill_probe_tree() {
  local parent="$1"
  local child
  for child in $(pgrep -P "$parent" 2>/dev/null); do
    kill_probe_tree "$child"
    kill "$child" 2>/dev/null
  done
  kill "$parent" 2>/dev/null
}

build_git_closeout_reason() {
  local probe_dir
  local summary_file
  local status_file
  local probe_pid
  local ticks
  local probe_status
  local summary
  local scope
  local fixed
  local full
  local reason

  probe_dir=$(mktemp -d "${TMPDIR:-/tmp}/checkpoint-git.XXXXXX") || return 1
  summary_file="$probe_dir/summary"
  status_file="$probe_dir/status"
  (
    git_readonly_summary "$CWD" > "$summary_file" 2>/dev/null
    printf '%s' "$?" > "$status_file"
  ) &
  probe_pid=$!
  ticks=0
  while [ ! -f "$status_file" ] && [ "$ticks" -lt 36 ]; do
    sleep 0.05
    ticks=$((ticks + 1))
  done
  if [ ! -f "$status_file" ]; then
    kill_probe_tree "$probe_pid"
    wait "$probe_pid" 2>/dev/null
    rm -rf "$probe_dir"
    return 124
  fi
  probe_status=$(cat "$status_file" 2>/dev/null || printf '1')
  wait "$probe_pid" 2>/dev/null
  if [ "$probe_status" != "0" ]; then
    rm -rf "$probe_dir"
    return 1
  fi
  summary=$(cat "$summary_file" 2>/dev/null) || {
    rm -rf "$probe_dir"
    return 1
  }
  scope=$(printf '%s\n' "$summary" | grep '^scope: ' 2>/dev/null | head -1 | sed 's/^scope: //')
  case "$scope" in
    company|unknown)
      fixed='Git closeout 固定要求（report-only）：只執行 read-only `git -C <repo root> status --short`、`git -C <repo root> diff -- <exact paths>` 與 `git -C <repo root> diff --cached -- <exact paths>`；不得 commit、push、merge、刪 branch、PR merge 或 worktree removal。先列 exact paths，再重新執行 fresh git status 與 git diff；pre-existing dirty、stash 與不明歸屬只回報，不由 hook mutation。'
      ;;
    *)
      fixed='Git closeout 固定要求：先列出 exact paths，再重新執行 read-only `git -C <repo root> status --short`、`git -C <repo root> diff -- <exact paths>` 與 `git -C <repo root> diff --cached -- <exact paths>`；依 `/self-closeout` 現行規則收：共用帳本留給 `/git-closeout` 統一備份、個人 trunk 連同既有 commit 一起 push，其餘只處理能確認屬於本 session 的項目。final 必須以 `Git closeout：READY` 或 `Git closeout：BLOCKED` 開頭，並逐項列出 exact paths 與處置。pre-existing dirty、stash、merge、刪 branch、PR merge、worktree removal 與不明歸屬只回報，不由 hook mutation。'
      ;;
  esac
  full=$(printf '%s\n\n%s' "$fixed" "$summary") || {
    rm -rf "$probe_dir"
    return 1
  }
  reason=$(git_cap_summary "$full" | jq -Rs .) || {
    rm -rf "$probe_dir"
    return 1
  }
  rm -rf "$probe_dir"
  printf '%s' "$reason"
}

build_git_unavailable_reason() {
  local scope="$1"
  printf 'Git closeout unavailable（scope: %s）\nGit 狀態未驗證：請手動執行唯讀檢查，不得宣稱 clean。hook 不執行 fetch、連網或 mutation。' "$scope" | jq -Rs .
}

git_closeout_disabled() {
  [ "${GIT_CLOSEOUT_DISABLE:-}" = "1" ] || [ -e "$HOME/.claude/hooks/.git-closeout-disabled" ]
}

detect_auto_closeout() {
  CHECKPOINT_INPUT="${3:-}" python3 -I - "$TRANSCRIPT" "$AUTO_CLOSEOUT_SENTINEL" "${1:-probe}" "${2:-0}" <<'PY'
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys
import tempfile

transcript_s, sentinel_s, mode, write_seq_s = sys.argv[1:5]
sentinel_path = Path(sentinel_s)

FENCED_RE = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)
PASTED_RE = re.compile(r"<pasted_content\b[^>]*>.*?</pasted_content>", re.DOTALL)
BLOCKQUOTE_RE = re.compile(r"(?m)^\s*>.*$")
INLINE_CODE_RE = re.compile(r"`[^`\n]{6,}`")
ALREADY_CLOSED_RE = re.compile(r"(?:Self\s*closeout|Git\s*closeout)\s*[：:]\s*(?:DONE|READY|BLOCKED)", re.IGNORECASE)
BG_WAIT_RE = re.compile(
  r"背景(?:任務|工作|測試|agent|subagent|worker)[^\n]{0,20}(?:還在跑|執行中|進行中|跑著)"
  r"|等(?:待)?[^\n]{0,15}通知"
  r"|still running in the background"
  r"|waiting for [^\n]{0,25}notification",
  re.IGNORECASE,
)
PENDING_QUESTION_RE = re.compile(
  r"(?m)"
  r"(?:^#{1,4}\s*第\s*\d+\s*/\s*\d+\s*題[^\n]*)"
  r"|(?:^(?:#{1,4}\s*|\*\*)待(?:你)?(?:拍板|決定|補確認)[^\n]*)"
  r"|(?:允許這次派工)"
  r"|(?:(?:你想選|請選擇|你要走|請問要)[^\n]{0,40}(?:還是|或))"
  r"|(?:對嗎[?？])"
)
TRAILING_Q_RE = re.compile(r"[?？][\"'」』）)*_\s]*$")
COMPLETION_RE = re.compile(
  r"(?:已|全部|全數|皆已)(?:完成|修好|修復|實作|補齊|解決|處理完畢|更新完畢|驗證完畢)"
  r"|(?:修改|實作|修復|調整|測試|驗證|檢查|變更)(?:已|皆已|全數|全部)?(?:完成|通過)"
  r"|我預期會看到[：:]"
  r"|(?i:\b(?:all (?:\d+ )?tests? pass(?:ed)?|implementation (?:is )?complete|all changes (?:are )?complete|verification passed)\b)"
)
STATUS_FIELD_RE = re.compile(r"(?:^|[｜|])\s*(目前|下一步)(?:\s*[：:｜|]|\s+)\s*([^｜|]*)")
COMBINED_STATUS_LINE_RE = re.compile(
  r"已完成\s*[｜|]\s*目前\s*[｜|]\s*下一步\s*[：:]\s*[^｜|]*[｜|]([^｜|]*)[｜|](.*)"
)
EMPTY_STEP_RE = re.compile(
  r"(?:|無|沒有|無待辦|(?:不用|不需(?:要)?)(?:再)?做|(?:已)?結案|none|done|n/?a|[-–—]+)[。.!！]?",
  re.IGNORECASE,
)
FINISHED_CURRENT_RE = re.compile(
  r"(?!(?:等|待|未|尚|還|正在|準備|開始))[^，,；;：:]*?(?:完成|完畢|結案|收尾|\bdone)[。.!！]?",
  re.IGNORECASE,
)
DEFERRED_NEXT_RE = re.compile(r"[^，,；;：:]{1,40}時再找我[。.!！]?")
GIT_COMMIT_CMD_RE = re.compile(
  r"(?:^|&&|\|\||[;|])\s*(?:env\s+|[A-Za-z_][A-Za-z0-9_]*=(?:\"[^\"]*\"|'[^']*'|\S+)\s+)*"
  r"git(?:\s+-[Cc]\s+(?:\"[^\"]*\"|'[^']*'|\S+))*\s+commit(?:\s|$)(?!\s*--help)"
)
SHELL_WORD = r"(?:\"[^\"\n]*\"|'[^'\n]*'|[^\s\"';&|<>\\]+)"
CLOSEOUT_PLAN_RE = re.compile(
  rf"(?:^|[;&|]|\bdo\b)\s*python3\s+\S*/closeout-provenance\.py\s+--repo\s+(?P<repo>{SHELL_WORD})\s+--plan(?:\s|$)"
)
CLOSEOUT_PLAN_LOOP_RE = re.compile(
  rf"(?:^|;)\s*for\s+(?P<var>[A-Za-z_]\w*)\s+in\s+(?P<repos>{SHELL_WORD}(?:[ \t]+{SHELL_WORD})*)\s*;\s*do\b"
)
LEDGER_COMMIT_RE = re.compile(
  rf"git\s+-C\s+(?P<repo>{SHELL_WORD})\s+commit\s+(?:-q\s+)?-m\s+"
  r"(?P<quote>[\"'])chore\(closeout\): checkpoint shared ledgers(?P=quote)"
)
TEMP_PREFIXES = ("/tmp/claude-", "/private/tmp/claude-")
TERMINAL_BG_STATUSES = {"completed", "done", "failed", "killed", "stopped", "cancelled"}


def is_empty_status(value: str) -> bool:
  wrappers = {"（": "）", "(": ")", "【": "】", "「": "」", "[": "]"}
  while True:
    value = re.sub(r"[\s。.，,；;]+$", "", value.lstrip())
    if len(value) < 2 or wrappers.get(value[0]) != value[-1]:
      return EMPTY_STEP_RE.fullmatch(value) is not None
    value = value[1:-1]


def has_active_status(prose: str) -> bool:
  fields = {}
  for line in reversed(prose.splitlines()):
    # Inline code sometimes wraps the labels or the entire status line.
    line = line.replace("`", "").replace("**", "").strip()
    combined = COMBINED_STATUS_LINE_RE.fullmatch(line)
    entries = zip(("目前", "下一步"), combined.groups()) if combined else (
      match.groups() for match in STATUS_FIELD_RE.finditer(line)
    )
    for label, value in entries:
      fields.setdefault(label, value.strip())
    if len(fields) == 2:
      break
  current = fields.get("目前", "")
  current_finished = is_empty_status(current) or bool(FINISHED_CURRENT_RE.fullmatch(current))
  if "下一步" in fields:
    next_step = fields["下一步"]
    # A future handoff after a completed phase is separate work.
    return not (is_empty_status(next_step) or (
      current_finished and "目前" in fields and DEFERRED_NEXT_RE.fullmatch(next_step)
    ))
  return not current_finished


def literal_repo(word: str) -> str | None:
  if any(char in word for char in "$`*?[\\"):
    return None
  path = os.path.expanduser(word)
  return os.path.normpath(path) if os.path.isabs(path) else None


def planned_repos(command: str) -> set[str]:
  repos = set()
  for plan in CLOSEOUT_PLAN_RE.finditer(command):
    word = plan["repo"]
    if path := literal_repo(word.strip("\"'")):
      repos.add(path)
      continue
    # Some closeouts plan several literal repos in one Bash call.
    for loop in CLOSEOUT_PLAN_LOOP_RE.finditer(command, 0, plan.end()):
      variable = "$" + loop["var"]
      if word not in (variable, f'"{variable}"') or re.search(r";\s*done\b", command[loop.end():plan.start()]):
        continue
      try:
        repos.update(path for item in shlex.split(loop["repos"]) if (path := literal_repo(item)))
      except ValueError:
        continue
  return repos


def valid_regular_stat(st) -> bool:
  return stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and st.st_uid == os.getuid()


def check_safe_sentinel_parent(parent: Path) -> bool:
  try:
    if parent.is_symlink():
      return False
    st = parent.lstat()
    return stat.S_ISDIR(st.st_mode) and st.st_uid == os.getuid()
  except OSError:
    return False


def read_sentinel_seq(path: Path) -> int | None:
  if not check_safe_sentinel_parent(path.parent):
    return None
  try:
    st = path.lstat()
  except FileNotFoundError:
    return 0
  except OSError:
    return None
  if not valid_regular_stat(st):
    return None
  fd = -1
  try:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(str(path), flags)
    if not valid_regular_stat(os.fstat(fd)):
      return None
    raw = os.read(fd, 128).decode("utf-8", "replace").strip()
    parts = raw.split(":")
    return int(parts[-1]) if parts and parts[-1].isdigit() else 0
  except (OSError, ValueError):
    return None
  finally:
    if fd >= 0:
      try:
        os.close(fd)
      except OSError:
        pass


def write_sentinel_seq(path: Path, turn_s: str, seq_s: str) -> bool:
  if not check_safe_sentinel_parent(path.parent):
    return False
  if (path.exists() or path.is_symlink()):
    try:
      if not valid_regular_stat(path.lstat()):
        return False
    except OSError:
      return False
  wfd, tmp_name = -1, ""
  try:
    wfd, tmp_name = tempfile.mkstemp(prefix=".closeout-seq.", dir=str(path.parent))
    os.fchmod(wfd, 0o600)
    os.write(wfd, f"{turn_s}:{seq_s}\n".encode("utf-8"))
    os.close(wfd)
    wfd = -1
    os.replace(tmp_name, str(path))
    tmp_name = ""
    return True
  except OSError:
    return False
  finally:
    if wfd >= 0:
      try:
        os.close(wfd)
      except OSError:
        pass
    if tmp_name:
      try:
        os.unlink(tmp_name)
      except OSError:
        pass


if mode == "record":
  turn_part, _, seq_part = write_seq_s.partition(":")
  sys.exit(0 if write_sentinel_seq(sentinel_path, turn_part, seq_part) else 1)

prev_seq = read_sentinel_seq(sentinel_path)
if prev_seq is None:
  sys.exit(1)

try:
  raw_in = os.environ.get("CHECKPOINT_INPUT", "")
  payload = json.loads(raw_in) if raw_in.strip() else {}
except (OSError, ValueError):
  sys.exit(1)
if not isinstance(payload, dict) or payload.get("agent_id"):
  sys.exit(1)

bg_tasks = payload.get("background_tasks")
if isinstance(bg_tasks, list):
  for task in bg_tasks:
    if not isinstance(task, dict):
      sys.exit(1)
    st = str(task.get("status") or "running").strip().lower()
    if st not in TERMINAL_BG_STATUSES:
      sys.exit(1)

assistant_text = payload.get("last_assistant_message")
if not isinstance(assistant_text, str):
  assistant_text = ""

tfd = -1
try:
  tflags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
  tfd = os.open(transcript_s, tflags)
  if not stat.S_ISREG(os.fstat(tfd).st_mode):
    sys.exit(1)
  with os.fdopen(tfd, "rb") as tf:
    tfd = -1
    if not assistant_text:
      tf.seek(0, os.SEEK_END)
      size = tf.tell()
      tf.seek(max(0, size - 65536))
      tail_lines = [ln for ln in tf.read().splitlines() if ln.strip()]
      if tail_lines and b'"assistant"' in tail_lines[-1]:
        try:
          last_obj = json.loads(tail_lines[-1].decode("utf-8", "replace"))
        except ValueError:
          last_obj = {}
        if isinstance(last_obj, dict) and last_obj.get("type") == "assistant" and not last_obj.get("isSidechain"):
          msg_content = (last_obj.get("message") or {}).get("content")
          if isinstance(msg_content, str):
            assistant_text = msg_content
          elif isinstance(msg_content, list):
            assistant_text = "\n".join(
              b.get("text", "") for b in msg_content if isinstance(b, dict) and b.get("type") == "text"
            )
    if not assistant_text.strip():
      sys.exit(1)
    prose = BLOCKQUOTE_RE.sub("", FENCED_RE.sub("", PASTED_RE.sub("", assistant_text)))
    if not prose.strip() or ALREADY_CLOSED_RE.search(prose):
      sys.exit(1)
    clean_prose = INLINE_CODE_RE.sub("", prose)
    if BG_WAIT_RE.search(clean_prose) or PENDING_QUESTION_RE.search(clean_prose):
      sys.exit(1)
    non_empty = [ln.strip() for ln in clean_prose.splitlines() if ln.strip()]
    if not non_empty or TRAILING_Q_RE.search(non_empty[-1]) or not COMPLETION_RE.search(clean_prose):
      sys.exit(1)
    if has_active_status(prose):
      sys.exit(1)

    tf.seek(0)
    seq = 0
    last_commit_seq = 0
    last_edit_seq = 0
    last_closeout_seq = 0
    closeout_repos = set()
    edited_paths = set()
    for raw_line in tf:
      seq += 1
      if b'"tool_use"' not in raw_line and b"closeout" not in raw_line and b"Git closeout" not in raw_line:
        continue
      try:
        entry = json.loads(raw_line.decode("utf-8", "replace"))
      except ValueError:
        continue
      if not isinstance(entry, dict) or entry.get("isSidechain") or entry.get("type") != "assistant":
        continue
      content = (entry.get("message") or {}).get("content")
      if isinstance(content, str):
        if ALREADY_CLOSED_RE.search(content):
          last_closeout_seq = seq
          edited_paths.clear()
          closeout_repos.clear()
        continue
      if not isinstance(content, list):
        continue
      for block in content:
        if not isinstance(block, dict):
          continue
        btype = block.get("type")
        if btype == "text":
          if ALREADY_CLOSED_RE.search(str(block.get("text") or "")):
            last_closeout_seq = seq
            edited_paths.clear()
            closeout_repos.clear()
        elif btype == "tool_use":
          tname = str(block.get("name") or "")
          tinp = block.get("input") if isinstance(block.get("input"), dict) else {}
          if tname == "Skill" and tinp.get("skill") in ("self-closeout", "git-closeout"):
            last_closeout_seq = seq
            edited_paths.clear()
            closeout_repos.clear()
          elif tname == "Bash":
            head_cmd = str(tinp.get("command") or "").split("<<", 1)[0]
            if "closeout-provenance.py" in head_cmd:
              last_closeout_seq = seq
              edited_paths.clear()
              if "--self-repos" in head_cmd:
                closeout_repos.clear()
              closeout_repos.update(planned_repos(head_cmd))
            elif GIT_COMMIT_CMD_RE.search(head_cmd):
              ledger = LEDGER_COMMIT_RE.fullmatch(head_cmd.strip()) if closeout_repos else None
              if not ledger or literal_repo(ledger["repo"].strip("\"'")) not in closeout_repos:
                last_commit_seq = seq
          elif tname in ("Edit", "Write", "NotebookEdit"):
            fp = str(tinp.get("file_path") or tinp.get("notebook_path") or "")
            if fp and not fp.startswith(TEMP_PREFIXES):
              last_edit_seq = seq
              edited_paths.add(fp)
finally:
  if tfd >= 0:
    try:
      os.close(tfd)
    except OSError:
      pass

work_seq = max(last_commit_seq, last_edit_seq)
if work_seq == 0 or work_seq <= last_closeout_seq or work_seq <= prev_seq:
  sys.exit(1)

if last_commit_seq > last_closeout_seq:
  print(f"commit\t{work_seq}")
  sys.exit(0)

env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
for fp in sorted(edited_paths):
  parent_dir = os.path.dirname(fp)
  if not parent_dir or not os.path.isdir(parent_dir):
    continue
  try:
    res = subprocess.run(
      ["git", "-C", parent_dir, "status", "--porcelain", "--untracked-files=all", "--", fp],
      capture_output=True, text=True, env=env, timeout=1.5,
    )
    if res.returncode == 0 and res.stdout.strip():
      print(f"dirty_edit\t{work_seq}")
      sys.exit(0)
  except (OSError, subprocess.SubprocessError):
    continue

sys.exit(1)
PY
}

# Defense 0.5: User trigger phrase
if echo "$LAST_USER" | grep -qiE '收尾|結案|收掉.{0,6}部分|save[-_ ]?session|寫.*memory|該記.{0,5}嗎|歸檔|promote.*wiki|記下來|記一下|存.{0,3}memory'; then
  if [ "$LAST_TRIGGER" = "-$USER_TURNS" ] && git_closeout_disabled; then
    log "trigger_dedup" ",\"user_turns\":$USER_TURNS,\"last_trigger\":$LAST_TRIGGER,\"git_closeout\":\"disabled\""
  elif [ "$USER_TURNS" -gt "$LAST_TRIGGER" ]; then
    VERSION=$(classify_context "$LAST_USER")

    if [ "$VERSION" = "silent" ]; then
      echo "$USER_TURNS" > "$TRIGGER_SENTINEL"
      log "trigger_silent_ctx" ",\"user_turns\":$USER_TURNS,\"reason\":\"discussion_topic_question\""
      exit 0
    fi

    GIT_SCOPE="unknown"
    GIT_STATUS="unavailable"
    GIT_REASON=""
    REASON_OK=1
    if git_closeout_disabled; then
      GIT_STATUS="disabled"
    else
      if GIT_REASON=$(build_git_closeout_reason); then
        GIT_STATUS="included"
        GIT_SCOPE=$(printf '%s\n' "$GIT_REASON" | jq -r 'split("\n")[] | select(startswith("scope: ")) | sub("^scope: "; "")' 2>/dev/null | tail -1)
        [ -z "$GIT_SCOPE" ] && GIT_SCOPE="unknown"
      else
        GIT_REASON=$(build_git_unavailable_reason "$GIT_SCOPE" 2>/dev/null || true)
      fi
    fi

    if [ "$VERSION" = "long" ]; then
      MEMORY_REASON=$(build_long_reason "[checkpoint:trigger:long] User trigger phrase → 強制 memory check。")
    else
      MEMORY_REASON=$(build_short_reason "[checkpoint:trigger:short] User trigger phrase 命中 ambiguous context。")
    fi

    if [ "$GIT_STATUS" != "disabled" ] && [ -n "$GIT_REASON" ]; then
      if REASON=$(jq -n --argjson memory "$MEMORY_REASON" --argjson git "$GIT_REASON" '$memory + "\n\n" + $git'); then
        :
      else
        GIT_STATUS="unavailable"
        REASON_OK=0
        REASON="$MEMORY_REASON"
      fi
    else
      if [ "$GIT_STATUS" != "disabled" ] && [ -z "$GIT_REASON" ]; then
        REASON_OK=0
      fi
      REASON="$MEMORY_REASON"
    fi

    echo "$USER_TURNS" > "$SENTINEL"
    if [ "$REASON_OK" = "1" ]; then
      if [ "$GIT_STATUS" = "disabled" ]; then
        echo "-$USER_TURNS" > "$TRIGGER_SENTINEL"
      else
        echo "$USER_TURNS" > "$TRIGGER_SENTINEL"
      fi
    fi
    if [ "$VERSION" = "long" ]; then
      python3 "$MEMORY_HELPER" mark-long --session "$SESSION_ID" --turns "$USER_TURNS" 2>/dev/null || true
      log "trigger_long" ",\"user_turns\":$USER_TURNS,\"scope\":\"$GIT_SCOPE\",\"git_closeout\":\"$GIT_STATUS\""
    else
      log "trigger_short" ",\"user_turns\":$USER_TURNS,\"last_long\":$LAST_LONG,\"scope\":\"$GIT_SCOPE\",\"git_closeout\":\"$GIT_STATUS\""
    fi
    log "git_closeout" ",\"scope\":\"$GIT_SCOPE\",\"status\":\"$GIT_STATUS\",\"git_closeout\":\"$GIT_STATUS\""

    printf '{"decision":"block","reason":%s}\n' "$REASON"
    exit 0
  else
    log "trigger_dedup" ",\"user_turns\":$USER_TURNS,\"last_trigger\":$LAST_TRIGGER,\"git_closeout\":\"reentry\""
  fi
  exit 0
fi

# Defense 0.6: Unclosed session commit/edit on general completion turn
if ! git_closeout_disabled; then
  LAST_TRIGGER_ABS="${LAST_TRIGGER#-}"
  if [ "$USER_TURNS" -gt "$LAST_TRIGGER_ABS" ]; then
    HAS_CANDIDATE_MSG=0
    case "$INPUT" in
      *'"last_assistant_message"'*) HAS_CANDIDATE_MSG=1 ;;
      *)
        TAIL_LINE=$(tail -n 1 "$TRANSCRIPT" 2>/dev/null || true)
        case "$TAIL_LINE" in
          *'"assistant"'*) HAS_CANDIDATE_MSG=1 ;;
        esac
        ;;
    esac
    if [ "$HAS_CANDIDATE_MSG" = "1" ]; then
      if AUTO_HIT=$(detect_auto_closeout probe 0 "$INPUT" 2>/dev/null); then
        AUTO_KIND="${AUTO_HIT%%	*}"
        AUTO_SEQ="${AUTO_HIT#*	}"
        GIT_SCOPE="unknown"
        GIT_STATUS="unavailable"
        GIT_REASON=""
        REASON_OK=1
        if GIT_REASON=$(build_git_closeout_reason); then
          GIT_STATUS="included"
          GIT_SCOPE=$(printf '%s\n' "$GIT_REASON" | jq -r 'split("\n")[] | select(startswith("scope: ")) | sub("^scope: "; "")' 2>/dev/null | tail -1)
          [ -z "$GIT_SCOPE" ] && GIT_SCOPE="unknown"
        else
          GIT_REASON=$(build_git_unavailable_reason "$GIT_SCOPE" 2>/dev/null || true)
        fi

        if [ "$LAST_LONG" = "0" ] || [ "$USER_TURNS" -gt "$((LAST_LONG + REFRESH_WINDOW))" ]; then
          AUTO_VERSION="long"
          MEMORY_REASON=$(build_long_reason "[checkpoint:auto-closeout:long] 偵測到本場已完成修改／提交並回報完成（${AUTO_KIND}），請補做記憶與 Git closeout 檢查。")
        else
          AUTO_VERSION="short"
          MEMORY_REASON=$(build_short_reason "[checkpoint:auto-closeout:short] 偵測到本場已完成修改／提交並回報完成（${AUTO_KIND}），請補做記憶與 Git closeout 檢查。")
        fi

        if [ -n "$GIT_REASON" ]; then
          if REASON=$(jq -n --argjson memory "$MEMORY_REASON" --argjson git "$GIT_REASON" '$memory + "\n\n" + $git'); then
            :
          else
            GIT_STATUS="unavailable"
            REASON_OK=0
            REASON="$MEMORY_REASON"
          fi
        else
          REASON_OK=0
          REASON="$MEMORY_REASON"
        fi

        [ ! -L "$SENTINEL" ] && [ ! -p "$SENTINEL" ] && echo "$USER_TURNS" > "$SENTINEL"
        if [ "$REASON_OK" = "1" ]; then
          [ ! -L "$TRIGGER_SENTINEL" ] && [ ! -p "$TRIGGER_SENTINEL" ] && echo "$USER_TURNS" > "$TRIGGER_SENTINEL"
          detect_auto_closeout record "${USER_TURNS}:${AUTO_SEQ}" </dev/null >/dev/null 2>&1 || true
        fi
        if [ "$AUTO_VERSION" = "long" ]; then
          python3 "$MEMORY_HELPER" mark-long --session "$SESSION_ID" --turns "$USER_TURNS" 2>/dev/null || true
        fi
        log "auto_closeout" ",\"user_turns\":$USER_TURNS,\"kind\":\"$AUTO_KIND\",\"work_seq\":$AUTO_SEQ,\"scope\":\"$GIT_SCOPE\",\"git_closeout\":\"$GIT_STATUS\""
        log "git_closeout" ",\"scope\":\"$GIT_SCOPE\",\"status\":\"$GIT_STATUS\",\"git_closeout\":\"$GIT_STATUS\""

        printf '{"decision":"block","reason":%s}\n' "$REASON"
        exit 0
      fi
    fi
  elif [ -f "$AUTO_CLOSEOUT_SENTINEL" ] && [ ! -L "$AUTO_CLOSEOUT_SENTINEL" ] && [ ! -p "$AUTO_CLOSEOUT_SENTINEL" ]; then
    AUTO_SAVED=$(head -c 64 "$AUTO_CLOSEOUT_SENTINEL" 2>/dev/null || true)
    if [ "${AUTO_SAVED%%:*}" = "$USER_TURNS" ]; then
      log "auto_closeout_dedup" ",\"user_turns\":$USER_TURNS,\"last_trigger\":$LAST_TRIGGER,\"git_closeout\":\"reentry\""
    fi
  fi
fi
