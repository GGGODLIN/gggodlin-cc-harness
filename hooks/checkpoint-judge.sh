#!/bin/bash
# checkpoint-judge.sh — Stop hook for user-explicit memory and closeout requests
# Contextual filter classify LAST_USER → silent / long / short
#   silent: 含問號 AND 長度 > 12 (討論結案 topic 而非真結案)
#   long:   短(<15) + 肯定詞開頭 + 無問號 + 同 session 第一次 OR > 50 turn ago
#   short:  其餘 ambiguous OR long-fire 過 50 turn 內 refresh window
#
# Long reason: dynamic cat 'feedback_memory_cluster_maintenance.md' Tier 1 段
# Short reason: 純 reminder ~150 字

INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)
TRANSCRIPT=$(echo "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null)
CWD=$(echo "$INPUT" | jq -r '.cwd // empty' 2>/dev/null)
export GIT_OPTIONAL_LOCKS=0

[ -z "$SESSION_ID" ] && exit 0
[[ "$SESSION_ID" =~ ^[A-Za-z0-9_-]{1,128}$ ]] || exit 0
[ -z "$TRANSCRIPT" ] || [ ! -f "$TRANSCRIPT" ] && exit 0

SENTINEL_DIR="$HOME/.claude/hooks/state"
mkdir -p "$SENTINEL_DIR"
LOG="$SENTINEL_DIR/checkpoint.log"
RULE_FILE="$HOME/.claude/memory/feedback_memory_cluster_maintenance.md"
MEMORY_HELPER="$(dirname "$0")/memory_reminder_common.py"
REFRESH_WINDOW=50

log() {
  printf '{"ts":"%s","session_id":"%s","action":"%s"%s}\n' \
    "$(date -u +%FT%TZ)" "$SESSION_ID" "$1" "$2" >> "$LOG"
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

USER_TURNS=$(jq -rc 'select(.type == "user" and (.message.content | type) == "string" and (.isMeta // false | not))' "$TRANSCRIPT" 2>/dev/null | wc -l | tr -d ' ')
LAST_LONG=$(python3 "$MEMORY_HELPER" last-long --session "$SESSION_ID" --turns "$USER_TURNS" --transcript "$TRANSCRIPT" 2>/dev/null || echo 0)
LAST_TRIGGER=$(cat "$TRIGGER_SENTINEL" 2>/dev/null || echo 0)
LAST_USER=$(jq -rc 'select(.type == "user" and (.message.content | type) == "string" and (.isMeta // false | not)) | .message.content' "$TRANSCRIPT" 2>/dev/null | tail -1)

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
  if [ "$msg_len" -lt 15 ] && echo "$last_user" | head -c 12 | grep -qiE '^(行|好|ok|可以|對|嗯|那|就|刪|不|沒問題|這樣|紀錄|記下|結案|收尾|歸檔|記下來|存起來)'; then
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
  local common_dir
  common_dir=$(git_common_dir_for_cwd "$cwd") || return 1
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
      fixed='Git closeout 固定要求：先列出 exact paths，再重新執行 read-only `git -C <repo root> status --short`、`git -C <repo root> diff -- <exact paths>` 與 `git -C <repo root> diff --cached -- <exact paths>`；依 `/self-closeout` 現行規則收：共用帳本整組 checkpoint、個人 trunk 連同既有 commit 一起 push，其餘只處理能確認屬於本 session 的項目。final 必須以 `Git closeout：READY` 或 `Git closeout：BLOCKED` 開頭，並逐項列出 exact paths 與處置。pre-existing dirty、stash、merge、刪 branch、PR merge、worktree removal 與不明歸屬只回報，不由 hook mutation。'
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

# Defense 0.5: User trigger phrase
if echo "$LAST_USER" | grep -qiE '收尾|結案|save[-_ ]?session|寫.*memory|該記.{0,5}嗎|歸檔|promote.*wiki|記下來|記一下|存.{0,3}memory'; then
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
fi
