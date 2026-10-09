#!/usr/bin/env bash
set -u

SCRIPT="${CHECKPOINT_JUDGE_SCRIPT:-$(cd "$(dirname "$0")" && pwd)/checkpoint-judge.sh}"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
pass=0
fail=0

run_case() {
  local name="$1"
  local vendor="$2"
  local user_message="$3"
  local expected_decision="$4"
  local expected_action="$5"
  local fixture_home="$TMP/$name/home"
  local transcript="$TMP/$name/transcript.jsonl"
  local input
  local output
  local decision
  local action
  local trigger_action
  local observed_action
  local first_action
  local log_count
  local expected_log_count
  local status

  mkdir -p "$fixture_home/.claude/hooks/state" "$fixture_home/.claude/memory"
  [ -f "$HOME/.claude/memory/feedback_memory_cluster_maintenance.md" ] && cp "$HOME/.claude/memory/feedback_memory_cluster_maintenance.md" "$fixture_home/.claude/memory/"
  printf '%s\n' '{"action":"seed"}' > "$fixture_home/.claude/hooks/state/checkpoint.log"
  jq -nc --arg text "$user_message" '{type:"user",message:{content:$text}}' > "$transcript"
  input=$(jq -nc --arg session "$name" --arg transcript "$transcript" '{session_id:$session,transcript_path:$transcript}')

  if [ "$vendor" = "__unset__" ]; then
    output=$(HOME="$fixture_home" env -u CC_VENDOR bash "$SCRIPT" <<< "$input")
    status=$?
  elif [ "$vendor" = "__empty__" ]; then
    output=$(HOME="$fixture_home" CC_VENDOR="" bash "$SCRIPT" <<< "$input")
    status=$?
  else
    output=$(HOME="$fixture_home" CC_VENDOR="$vendor" bash "$SCRIPT" <<< "$input")
    status=$?
  fi

  if [ -n "$output" ]; then
    decision=$(printf '%s\n' "$output" | jq -r '.decision // "none"' 2>/dev/null)
  else
    decision="none"
  fi
  action=$(jq -sr '.[-1].action // "none"' "$fixture_home/.claude/hooks/state/checkpoint.log" 2>/dev/null)
  trigger_action=$(jq -sr '[.[] | select(.action == "trigger_long" or .action == "trigger_short")] | .[-1].action // "none"' "$fixture_home/.claude/hooks/state/checkpoint.log" 2>/dev/null)
  first_action=$(jq -sr '.[0].action // "none"' "$fixture_home/.claude/hooks/state/checkpoint.log" 2>/dev/null)
  log_count=$(jq -s 'length' "$fixture_home/.claude/hooks/state/checkpoint.log" 2>/dev/null)
  observed_action="$action"
  expected_log_count=2
  if [ "$expected_action" = "trigger_long" ] || [ "$expected_action" = "trigger_short" ]; then
    observed_action="$trigger_action"
    expected_log_count=3
  fi

  if [ "$status" = "0" ] && [ "$decision" = "$expected_decision" ] && [ "$observed_action" = "$expected_action" ] && [ "$first_action" = "seed" ] && [ "$log_count" = "$expected_log_count" ]; then
    if [ "$expected_action" = "inject_long" ] && printf '%s' "$output" | grep -q 'Tier 1 段抽不到'; then
      printf 'FAIL %s inject_long 的 Tier 1 段為空（2026-08-25 反向斷言：sanitize 管線缺 LC_ALL=C 時 sed 吃掉整段）\n' "$name"
      ((fail++))
      return
    fi
    printf 'PASS %s decision=%s action=%s append=yes\n' "$name" "$decision" "$observed_action"
    ((pass++))
  else
    printf 'FAIL %s decision=%s expected=%s action=%s expected=%s first=%s count=%s\n' "$name" "$decision" "$expected_decision" "$observed_action" "$expected_action" "$first_action" "$log_count"
    ((fail++))
  fi
}

run_turn_case() {
  local name="$1"
  local vendor="$2"
  local user_turns="$3"
  local last_message="$4"
  local last_checkpoint="$5"
  local last_long="$6"
  local expected_decision="$7"
  local expected_action="$8"
  local fixture_home="$TMP/$name/home"
  local transcript="$TMP/$name/transcript.jsonl"
  local input
  local output
  local decision
  local action
  local first_action
  local log_count
  local expected_log_count
  local status
  local i
  local message

  mkdir -p "$fixture_home/.claude/hooks/state" "$fixture_home/.claude/memory"
  [ -f "$HOME/.claude/memory/feedback_memory_cluster_maintenance.md" ] && cp "$HOME/.claude/memory/feedback_memory_cluster_maintenance.md" "$fixture_home/.claude/memory/"
  printf '%s\n' '{"action":"seed"}' > "$fixture_home/.claude/hooks/state/checkpoint.log"
  : > "$transcript"
  for i in $(seq 1 "$user_turns"); do
    message="turn-$i"
    if [ "$i" = "$user_turns" ]; then
      message="$last_message"
    fi
    jq -nc --arg text "$message" '{type:"user",message:{content:$text}}' >> "$transcript"
  done
  if [ "$last_checkpoint" != "__none__" ]; then
    printf '%s\n' "$last_checkpoint" > "$fixture_home/.claude/hooks/state/checkpoint_$name"
  fi
  if [ "$last_long" != "__none__" ]; then
    printf '%s\n' "$last_long" > "$fixture_home/.claude/hooks/state/long_injected_$name"
  fi
  input=$(jq -nc --arg session "$name" --arg transcript "$transcript" '{session_id:$session,transcript_path:$transcript}')

  if [ "$vendor" = "__unset__" ]; then
    output=$(HOME="$fixture_home" env -u CC_VENDOR bash "$SCRIPT" <<< "$input")
    status=$?
  elif [ "$vendor" = "__empty__" ]; then
    output=$(HOME="$fixture_home" CC_VENDOR="" bash "$SCRIPT" <<< "$input")
    status=$?
  else
    output=$(HOME="$fixture_home" CC_VENDOR="$vendor" bash "$SCRIPT" <<< "$input")
    status=$?
  fi

  if [ -n "$output" ]; then
    decision=$(printf '%s\n' "$output" | jq -r '.decision // "none"' 2>/dev/null)
  else
    decision="none"
  fi
  action=$(jq -sr '.[-1].action // "none"' "$fixture_home/.claude/hooks/state/checkpoint.log" 2>/dev/null)
  first_action=$(jq -sr '.[0].action // "none"' "$fixture_home/.claude/hooks/state/checkpoint.log" 2>/dev/null)
  log_count=$(jq -s 'length' "$fixture_home/.claude/hooks/state/checkpoint.log" 2>/dev/null)
  expected_log_count=2
  [ "$expected_action" = "seed" ] && expected_log_count=1

  if [ "$status" = "0" ] && [ "$decision" = "$expected_decision" ] && [ "$action" = "$expected_action" ] && [ "$first_action" = "seed" ] && [ "$log_count" = "$expected_log_count" ]; then
    if [ "$expected_action" = "inject_long" ] && printf '%s' "$output" | grep -q 'Tier 1 段抽不到'; then
      printf 'FAIL %s inject_long 的 Tier 1 段為空（2026-08-25 反向斷言：sanitize 管線缺 LC_ALL=C 時 sed 吃掉整段）\n' "$name"
      ((fail++))
      return
    fi
    printf 'PASS %s decision=%s action=%s append=yes\n' "$name" "$decision" "$action"
    ((pass++))
  else
    printf 'FAIL %s decision=%s expected=%s action=%s expected=%s first=%s count=%s\n' "$name" "$decision" "$expected_decision" "$action" "$expected_action" "$first_action" "$log_count"
    ((fail++))
  fi
}

run_git_summary_case() {
  local name="$1"
  local user_message="$2"
  local expected_version="${3:-long}"
  local fixture_home="$TMP/$name/home"
  local repo="$fixture_home/Desktop/projects/$name-repo"
  local transcript="$TMP/$name/transcript.jsonl"
  local input
  local output
  local decision
  local reason
  local scope
  local git_closeout
  local audit_action

  mkdir -p "$fixture_home/.claude/hooks/state" "$(dirname "$repo")"
  git init -q -b main "$repo"
  git -C "$repo" -c user.name=Fixture -c user.email=fixture@example.com commit --allow-empty -qm init
  jq -nc --arg text "$user_message" '{type:"user",message:{content:$text}}' > "$transcript"
  input=$(jq -nc --arg session "$name" --arg transcript "$transcript" --arg cwd "$repo" '{session_id:$session,transcript_path:$transcript,cwd:$cwd}')
  output=$(HOME="$fixture_home" env -u CC_VENDOR bash "$SCRIPT" <<< "$input")

  if [ -n "$output" ]; then
    decision=$(printf '%s\n' "$output" | jq -r '.decision // "none"' 2>/dev/null)
    reason=$(printf '%s\n' "$output" | jq -r '.reason // empty' 2>/dev/null)
  else
    decision="none"
    reason=""
  fi
  scope=$(jq -sr '.[-1].scope // "none"' "$fixture_home/.claude/hooks/state/checkpoint.log" 2>/dev/null)
  git_closeout=$(jq -sr '.[-1].git_closeout // "none"' "$fixture_home/.claude/hooks/state/checkpoint.log" 2>/dev/null)
  audit_action=$(jq -sr '.[-1].action // "none"' "$fixture_home/.claude/hooks/state/checkpoint.log" 2>/dev/null)

  if [ "$decision" = "block" ] && printf '%s' "$reason" | grep -q "\[checkpoint:trigger:$expected_version\]" && printf '%s' "$reason" | grep -q 'Git closeout：READY' && printf '%s' "$reason" | grep -q 'Git closeout：BLOCKED' && printf '%s' "$reason" | grep -q '逐項列出 exact paths 與處置' && printf '%s' "$reason" | grep -q "$repo" && printf '%s' "$reason" | grep -q 'branch: main' && [ "$scope" = "personal" ] && [ "$git_closeout" = "included" ] && [ "$audit_action" = "git_closeout" ]; then
    printf 'PASS %s decision=%s git-summary=yes scope=%s closeout=%s\n' "$name" "$decision" "$scope" "$git_closeout"
    ((pass++))
  else
    printf 'FAIL %s decision=%s git-summary=%s scope=%s closeout=%s\n' "$name" "$decision" "$([ -n "$reason" ] && printf yes || printf no)" "$scope" "$git_closeout"
    ((fail++))
  fi
}

run_git_inventory_case() {
  local name="$1"
  local fixture_home="$TMP/$name/home"
  local repo="$fixture_home/Desktop/projects/$name-repo"
  local origin="$fixture_home/origins/$name.git"
  local linked="$fixture_home/Desktop/projects/$name-linked"
  local transcript="$TMP/$name/transcript.jsonl"
  local input
  local output
  local reason
  local decision

  mkdir -p "$fixture_home/.claude/hooks/state" "$(dirname "$repo")" "$(dirname "$origin")"
  git init -q -b main "$repo"
  git -C "$repo" -c user.name=Fixture -c user.email=fixture@example.com commit --allow-empty -qm init
  git init -q --bare "$origin"
  git -C "$repo" remote add origin "$origin"
  git -C "$repo" push -q -u origin main
  git -C "$repo" remote set-head origin main
  printf 'one\n' > "$repo/one.txt"
  git -C "$repo" add one.txt
  git -C "$repo" -c user.name=Fixture -c user.email=fixture@example.com commit -qm one
  printf 'two\n' > "$repo/two.txt"
  git -C "$repo" add two.txt
  git -C "$repo" -c user.name=Fixture -c user.email=fixture@example.com commit -qm two
  printf 'stash\n' > "$repo/stash.txt"
  git -C "$repo" stash push -q -u -m 'preserve fixture'
  printf 'changed\n' > "$repo/one.txt"
  printf 'dirty-a\n' > "$repo/dirty-a.txt"
  printf 'dirty-b\n' > "$repo/dirty-b.txt"
  git -C "$repo" worktree add -q -b feature "$linked" HEAD
  jq -nc '{type:"user",message:{content:"好，那就結案"}}' > "$transcript"
  input=$(jq -nc --arg session "$name" --arg transcript "$transcript" --arg cwd "$repo" '{session_id:$session,transcript_path:$transcript,cwd:$cwd}')
  output=$(HOME="$fixture_home" env -u CC_VENDOR bash "$SCRIPT" <<< "$input")
  decision=$(printf '%s\n' "$output" | jq -r '.decision // "none"' 2>/dev/null)
  reason=$(printf '%s\n' "$output" | jq -r '.reason // empty' 2>/dev/null)

  if [ "$decision" = "block" ] && printf '%s' "$reason" | grep -q 'dirty count: 3' && printf '%s' "$reason" | grep -q 'dirty-a.txt' && printf '%s' "$reason" | grep -q 'stash count: 1' && printf '%s' "$reason" | grep -q 'preserve fixture' && printf '%s' "$reason" | grep -q 'worktree count: 2' && printf '%s' "$reason" | grep -q "$linked" && printf '%s' "$reason" | grep -q 'ahead: 2' && printf '%s' "$reason" | grep -q 'behind: 0'; then
    printf 'PASS %s decision=%s inventory=yes\n' "$name" "$decision"
    ((pass++))
  else
    printf 'FAIL %s decision=%s inventory=no\n' "$name" "$decision"
    ((fail++))
  fi
}

run_git_truncation_case() {
  local name="$1"
  local fixture_home="$TMP/$name/home"
  local repo="$fixture_home/Desktop/projects/$name-repo"
  local transcript="$TMP/$name/transcript.jsonl"
  local input
  local output
  local reason
  local decision
  local dirty_listed
  local stash_listed
  local worktree_listed
  local git_bytes
  local i

  mkdir -p "$fixture_home/.claude/hooks/state" "$(dirname "$repo")"
  git init -q -b main "$repo"
  git -C "$repo" -c user.name=Fixture -c user.email=fixture@example.com commit --allow-empty -qm init
  for i in $(seq 1 7); do
    printf 'stash-%s\n' "$i" > "$repo/stash.txt"
    git -C "$repo" stash push -q -u -m "stash-$i"
  done
  for i in $(seq 1 25); do
    printf 'dirty-%s\n' "$i" > "$repo/dirty-$i.txt"
  done
  for i in $(seq 1 7); do
    git -C "$repo" worktree add -q -b "feature-$i" "$fixture_home/Desktop/projects/$name-wt-$i" HEAD
  done
  jq -nc '{type:"user",message:{content:"好，那就結案"}}' > "$transcript"
  input=$(jq -nc --arg session "$name" --arg transcript "$transcript" --arg cwd "$repo" '{session_id:$session,transcript_path:$transcript,cwd:$cwd}')
  output=$(HOME="$fixture_home" env -u CC_VENDOR bash "$SCRIPT" <<< "$input")
  decision=$(printf '%s\n' "$output" | jq -r '.decision // "none"' 2>/dev/null)
  reason=$(printf '%s\n' "$output" | jq -r '.reason // empty' 2>/dev/null)
  dirty_listed=$(printf '%s\n' "$reason" | grep -c '^  - dirty-' 2>/dev/null || true)
  stash_listed=$(printf '%s\n' "$reason" | grep -c '^  - stash@' 2>/dev/null || true)
  worktree_listed=$(printf '%s\n' "$reason" | grep -c "^  - .*projects/$name-wt-" 2>/dev/null || true)
  git_bytes=$(printf '%s' "${reason#*Git closeout}" | wc -c | tr -d ' ')

  if [ "$decision" = "block" ] && printf '%s' "$reason" | grep -q 'dirty count: 25' && printf '%s' "$reason" | grep -q 'stash count: 7' && printf '%s' "$reason" | grep -q 'worktree count: 8' && printf '%s' "$reason" | grep -q 'truncated' && [ "$dirty_listed" -gt 0 ] && [ "$dirty_listed" -le 20 ] && [ "$stash_listed" -gt 0 ] && [ "$stash_listed" -le 5 ] && [ "$worktree_listed" -gt 0 ] && [ "$worktree_listed" -le 5 ] && [ "$git_bytes" -le 8192 ]; then
    printf 'PASS %s decision=%s dirty=%s stash=%s worktree=%s bytes=%s\n' "$name" "$decision" "$dirty_listed" "$stash_listed" "$worktree_listed" "$git_bytes"
    ((pass++))
  else
    printf 'FAIL %s decision=%s dirty=%s stash=%s worktree=%s bytes=%s\n' "$name" "$decision" "$dirty_listed" "$stash_listed" "$worktree_listed" "$git_bytes"
    ((fail++))
  fi
}

run_git_unavailable_case() {
  local name="$1"
  local mode="${2:-plain}"
  local fixture_home="$TMP/$name/home"
  local cwd="$fixture_home/Desktop/projects/plain"
  if [ "$mode" = "parent" ]; then
    cwd="$fixture_home/Desktop/projects"
  fi
  local transcript="$TMP/$name/transcript.jsonl"
  local input
  local output
  local decision
  local reason
  local scope
  local git_closeout
  local trigger_file

  mkdir -p "$fixture_home/.claude/hooks/state" "$cwd"
  jq -nc '{type:"user",message:{content:"好，那就結案"}}' > "$transcript"
  input=$(jq -nc --arg session "$name" --arg transcript "$transcript" --arg cwd "$cwd" '{session_id:$session,transcript_path:$transcript,cwd:$cwd}')
  output=$(HOME="$fixture_home" env -u CC_VENDOR bash "$SCRIPT" <<< "$input")
  decision=$(printf '%s\n' "$output" | jq -r '.decision // "none"' 2>/dev/null)
  reason=$(printf '%s\n' "$output" | jq -r '.reason // empty' 2>/dev/null)
  scope=$(jq -sr '.[-1].scope // "none"' "$fixture_home/.claude/hooks/state/checkpoint.log" 2>/dev/null)
  git_closeout=$(jq -sr '.[-1].git_closeout // "none"' "$fixture_home/.claude/hooks/state/checkpoint.log" 2>/dev/null)
  trigger_file="$fixture_home/.claude/hooks/state/trigger_$name"

  if [ "$decision" = "block" ] && printf '%s' "$reason" | grep -q '\[checkpoint:trigger:long\]' && printf '%s' "$reason" | grep -q 'Git closeout unavailable' && printf '%s' "$reason" | grep -q '唯讀檢查' && [ "$scope" = "unknown" ] && [ "$git_closeout" = "unavailable" ] && [ -e "$trigger_file" ]; then
    printf 'PASS %s decision=%s unavailable=yes sentinel=present\n' "$name" "$decision"
    ((pass++))
  else
    printf 'FAIL %s decision=%s unavailable=no scope=%s closeout=%s sentinel=%s\n' "$name" "$decision" "$scope" "$git_closeout" "$([ -e "$trigger_file" ] && printf present || printf absent)"
    ((fail++))
  fi
}

run_git_kill_switch_case() {
  local name="$1"
  local mode="$2"
  local fixture_home="$TMP/$name/home"
  local repo="$fixture_home/Desktop/projects/$name-repo"
  local transcript="$TMP/$name/transcript.jsonl"
  local bin_dir="$TMP/$name/bin"
  local real_git
  local probe_log="$TMP/$name/git-probe.log"
  local input
  local output
  local reason
  local decision
  local scope
  local git_closeout
  local probe_calls

  mkdir -p "$fixture_home/.claude/hooks/state" "$(dirname "$repo")" "$bin_dir"
  git init -q -b main "$repo"
  git -C "$repo" -c user.name=Fixture -c user.email=fixture@example.com commit --allow-empty -qm init
  real_git=$(command -v git)
  printf '%s\n' '#!/bin/bash' 'printf "%s\\n" "$*" >> "$GIT_PROBE_LOG"' 'exec "$GIT_REAL" "$@"' > "$bin_dir/git"
  chmod +x "$bin_dir/git"
  if [ "$mode" = "sentinel" ]; then
    : > "$fixture_home/.claude/hooks/.git-closeout-disabled"
  fi
  jq -nc '{type:"user",message:{content:"好，那就結案"}}' > "$transcript"
  input=$(jq -nc --arg session "$name" --arg transcript "$transcript" --arg cwd "$repo" '{session_id:$session,transcript_path:$transcript,cwd:$cwd}')
  if [ "$mode" = "env" ]; then
    output=$(GIT_CLOSEOUT_DISABLE=1 GIT_REAL="$real_git" GIT_PROBE_LOG="$probe_log" PATH="$bin_dir:$PATH" HOME="$fixture_home" env -u CC_VENDOR bash "$SCRIPT" <<< "$input")
  else
    output=$(GIT_REAL="$real_git" GIT_PROBE_LOG="$probe_log" PATH="$bin_dir:$PATH" HOME="$fixture_home" env -u CC_VENDOR -u GIT_CLOSEOUT_DISABLE bash "$SCRIPT" <<< "$input")
  fi
  decision=$(printf '%s\n' "$output" | jq -r '.decision // "none"' 2>/dev/null)
  reason=$(printf '%s\n' "$output" | jq -r '.reason // empty' 2>/dev/null)
  scope=$(jq -sr '.[-1].scope // "none"' "$fixture_home/.claude/hooks/state/checkpoint.log" 2>/dev/null)
  git_closeout=$(jq -sr '.[-1].git_closeout // "none"' "$fixture_home/.claude/hooks/state/checkpoint.log" 2>/dev/null)
  if [ -f "$probe_log" ]; then
    probe_calls=$(wc -l < "$probe_log" | tr -d ' ')
  else
    probe_calls=0
  fi

  if [ "$decision" = "block" ] && printf '%s' "$reason" | grep -q '\[checkpoint:trigger:long\]' && ! printf '%s' "$reason" | grep -q 'Git closeout 摘要' && [ "$scope" = "unknown" ] && [ "$git_closeout" = "disabled" ] && [ "$probe_calls" = "0" ]; then
    printf 'PASS %s mode=%s decision=%s disabled=yes probe_calls=%s\n' "$name" "$mode" "$decision" "$probe_calls"
    ((pass++))
  else
    printf 'FAIL %s mode=%s decision=%s scope=%s closeout=%s probe_calls=%s\n' "$name" "$mode" "$decision" "$scope" "$git_closeout" "$probe_calls"
    ((fail++))
  fi
}

run_git_kill_switch_recovery_case() {
  local name="$1"
  local mode="$2"
  local fixture_home="$TMP/$name/home"
  local repo="$fixture_home/Desktop/projects/$name-repo"
  local transcript="$TMP/$name/transcript.jsonl"
  local input
  local first_output
  local second_output
  local third_output
  local fourth_output
  local first_decision
  local second_decision
  local third_decision
  local fourth_decision
  local first_reason
  local third_reason

  mkdir -p "$fixture_home/.claude/hooks/state" "$(dirname "$repo")"
  git init -q -b main "$repo"
  git -C "$repo" -c user.name=Fixture -c user.email=fixture@example.com commit --allow-empty -qm init
  if [ "$mode" = "sentinel" ]; then
    : > "$fixture_home/.claude/hooks/.git-closeout-disabled"
  fi
  jq -nc '{type:"user",message:{content:"好，那就結案"}}' > "$transcript"
  input=$(jq -nc --arg session "$name" --arg transcript "$transcript" --arg cwd "$repo" '{session_id:$session,transcript_path:$transcript,cwd:$cwd}')
  if [ "$mode" = "env" ]; then
    first_output=$(GIT_CLOSEOUT_DISABLE=1 HOME="$fixture_home" env -u CC_VENDOR bash "$SCRIPT" <<< "$input")
    second_output=$(GIT_CLOSEOUT_DISABLE=1 HOME="$fixture_home" env -u CC_VENDOR bash "$SCRIPT" <<< "$input")
  else
    first_output=$(HOME="$fixture_home" env -u CC_VENDOR -u GIT_CLOSEOUT_DISABLE bash "$SCRIPT" <<< "$input")
    second_output=$(HOME="$fixture_home" env -u CC_VENDOR -u GIT_CLOSEOUT_DISABLE bash "$SCRIPT" <<< "$input")
    rm -f "$fixture_home/.claude/hooks/.git-closeout-disabled"
  fi
  third_output=$(HOME="$fixture_home" env -u CC_VENDOR -u GIT_CLOSEOUT_DISABLE bash "$SCRIPT" <<< "$input")
  fourth_output=$(HOME="$fixture_home" env -u CC_VENDOR -u GIT_CLOSEOUT_DISABLE bash "$SCRIPT" <<< "$input")
  first_decision=$(printf '%s\n' "$first_output" | jq -r '.decision // "none"' 2>/dev/null)
  second_decision=$(printf '%s\n' "$second_output" | jq -r '.decision // "none"' 2>/dev/null)
  third_decision=$(printf '%s\n' "$third_output" | jq -r '.decision // "none"' 2>/dev/null)
  fourth_decision=$(printf '%s\n' "$fourth_output" | jq -r '.decision // "none"' 2>/dev/null)
  first_decision=${first_decision:-none}
  second_decision=${second_decision:-none}
  third_decision=${third_decision:-none}
  fourth_decision=${fourth_decision:-none}
  first_reason=$(printf '%s\n' "$first_output" | jq -r '.reason // empty' 2>/dev/null)
  third_reason=$(printf '%s\n' "$third_output" | jq -r '.reason // empty' 2>/dev/null)

  if [ "$first_decision" = "block" ] && printf '%s' "$first_reason" | grep -q '\[checkpoint:trigger:long\]' && ! printf '%s' "$first_reason" | grep -q 'Git closeout 摘要' && [ "$second_decision" = "none" ] && [ "$third_decision" = "block" ] && printf '%s' "$third_reason" | grep -q 'Git closeout 摘要' && [ "$fourth_decision" = "none" ]; then
    printf 'PASS %s mode=%s first=%s second=%s restored=%s final=%s\n' "$name" "$mode" "$first_decision" "$second_decision" "$third_decision" "$fourth_decision"
    ((pass++))
  else
    printf 'FAIL %s mode=%s first=%s second=%s restored=%s final=%s\n' "$name" "$mode" "$first_decision" "$second_decision" "$third_decision" "$fourth_decision"
    ((fail++))
  fi
}

run_git_timeout_case() {
  local name="$1"
  local fixture_home="$TMP/$name/home"
  local cwd="$fixture_home/Desktop/projects/plain"
  local transcript="$TMP/$name/transcript.jsonl"
  local bin_dir="$TMP/$name/bin"
  local input
  local output
  local reason
  local decision
  local start
  local elapsed

  mkdir -p "$fixture_home/.claude/hooks/state" "$cwd" "$bin_dir"
  printf '%s\n' '#!/bin/bash' 'sleep 5' 'exit 1' > "$bin_dir/git"
  chmod +x "$bin_dir/git"
  jq -nc '{type:"user",message:{content:"好，那就結案"}}' > "$transcript"
  input=$(jq -nc --arg session "$name" --arg transcript "$transcript" --arg cwd "$cwd" '{session_id:$session,transcript_path:$transcript,cwd:$cwd}')
  start=$(date +%s)
  output=$(PATH="$bin_dir:$PATH" HOME="$fixture_home" env -u CC_VENDOR bash "$SCRIPT" <<< "$input")
  elapsed=$(( $(date +%s) - start ))
  decision=$(printf '%s\n' "$output" | jq -r '.decision // "none"' 2>/dev/null)
  reason=$(printf '%s\n' "$output" | jq -r '.reason // empty' 2>/dev/null)

  if [ "$decision" = "block" ] && printf '%s' "$reason" | grep -q 'Git closeout unavailable' && [ "$elapsed" -lt 4 ]; then
    printf 'PASS %s decision=%s timeout=%ss\n' "$name" "$decision" "$elapsed"
    ((pass++))
  else
    printf 'FAIL %s decision=%s timeout=%ss\n' "$name" "$decision" "$elapsed"
    ((fail++))
  fi
}

run_git_rev_list_failure_case() {
  local name="$1"
  local fixture_home="$TMP/$name/home"
  local repo="$fixture_home/Desktop/projects/$name-repo"
  local origin="$fixture_home/origins/$name.git"
  local transcript="$TMP/$name/transcript.jsonl"
  local bin_dir="$TMP/$name/bin"
  local real_git
  local input
  local output
  local decision
  local reason
  local git_closeout

  mkdir -p "$fixture_home/.claude/hooks/state" "$(dirname "$repo")" "$(dirname "$origin")" "$bin_dir"
  git init -q -b main "$repo"
  git -C "$repo" -c user.name=Fixture -c user.email=fixture@example.com commit --allow-empty -qm init
  git init -q --bare "$origin"
  git -C "$repo" remote add origin "$origin"
  git -C "$repo" push -q -u origin main
  printf 'ahead\n' > "$repo/ahead.txt"
  git -C "$repo" add ahead.txt
  git -C "$repo" -c user.name=Fixture -c user.email=fixture@example.com commit -qm ahead
  real_git=$(command -v git)
  printf '%s\n' '#!/bin/bash' 'case "$*" in *"rev-list --count"*) exit 1 ;; esac' 'exec "$GIT_REAL" "$@"' > "$bin_dir/git"
  chmod +x "$bin_dir/git"
  jq -nc '{type:"user",message:{content:"好，那就結案"}}' > "$transcript"
  input=$(jq -nc --arg session "$name" --arg transcript "$transcript" --arg cwd "$repo" '{session_id:$session,transcript_path:$transcript,cwd:$cwd}')
  output=$(GIT_REAL="$real_git" PATH="$bin_dir:$PATH" HOME="$fixture_home" env -u CC_VENDOR bash "$SCRIPT" <<< "$input")
  decision=$(printf '%s\n' "$output" | jq -r '.decision // "none"' 2>/dev/null)
  reason=$(printf '%s\n' "$output" | jq -r '.reason // empty' 2>/dev/null)
  git_closeout=$(jq -sr '.[-1].git_closeout // "none"' "$fixture_home/.claude/hooks/state/checkpoint.log" 2>/dev/null)

  if [ "$decision" = "block" ] && printf '%s' "$reason" | grep -q 'Git closeout unavailable' && [ "$git_closeout" = "unavailable" ]; then
    printf 'PASS %s decision=%s rev-list-failure=unavailable\n' "$name" "$decision"
    ((pass++))
  else
    printf 'FAIL %s decision=%s rev-list-failure=%s closeout=%s\n' "$name" "$decision" "$([ -n "$reason" ] && printf included || printf absent)" "$git_closeout"
    ((fail++))
  fi
}

run_git_reentry_case() {
  local name="$1"
  local fixture_home="$TMP/$name/home"
  local repo="$fixture_home/Desktop/projects/$name-repo"
  local transcript="$TMP/$name/transcript.jsonl"
  local input
  local reentry_input
  local first_output
  local second_output
  local first_decision
  local second_decision
  local trigger_count
  local reentry_count

  mkdir -p "$fixture_home/.claude/hooks/state" "$(dirname "$repo")"
  git init -q -b main "$repo"
  git -C "$repo" -c user.name=Fixture -c user.email=fixture@example.com commit --allow-empty -qm init
  jq -nc '{type:"user",message:{content:"好，那就結案"}}' > "$transcript"
  input=$(jq -nc --arg session "$name" --arg transcript "$transcript" --arg cwd "$repo" '{session_id:$session,transcript_path:$transcript,cwd:$cwd,stop_hook_active:false}')
  reentry_input=$(jq -nc --arg session "$name" --arg transcript "$transcript" --arg cwd "$repo" '{session_id:$session,transcript_path:$transcript,cwd:$cwd,stop_hook_active:true}')
  first_output=$(HOME="$fixture_home" env -u CC_VENDOR bash "$SCRIPT" <<< "$input")
  second_output=$(HOME="$fixture_home" env -u CC_VENDOR bash "$SCRIPT" <<< "$reentry_input")
  first_decision=$(printf '%s\n' "$first_output" | jq -r '.decision // "none"' 2>/dev/null)
  if [ -n "$second_output" ]; then
    second_decision=$(printf '%s\n' "$second_output" | jq -r '.decision // "none"' 2>/dev/null)
  else
    second_decision="none"
  fi
  trigger_count=$(jq -s '[.[] | select(.action == "trigger_long")] | length' "$fixture_home/.claude/hooks/state/checkpoint.log" 2>/dev/null)
  reentry_count=$(jq -s '[.[] | select(.git_closeout == "reentry")] | length' "$fixture_home/.claude/hooks/state/checkpoint.log" 2>/dev/null)

  if [ "$first_decision" = "block" ] && [ "$second_decision" = "none" ] && [ "$trigger_count" = "1" ] && [ "$reentry_count" = "1" ]; then
    printf 'PASS %s first=%s second=%s reentry=%s\n' "$name" "$first_decision" "$second_decision" "$reentry_count"
    ((pass++))
  else
    printf 'FAIL %s first=%s second=%s trigger=%s reentry=%s\n' "$name" "$first_decision" "$second_decision" "$trigger_count" "$reentry_count"
    ((fail++))
  fi
}

run_git_json_failure_case() {
  local name="$1"
  local fixture_home="$TMP/$name/home"
  local repo="$fixture_home/Desktop/projects/$name-repo"
  local transcript="$TMP/$name/transcript.jsonl"
  local bin_dir="$TMP/$name/bin"
  local real_jq
  local input
  local output
  local reason
  local decision
  local scope
  local git_closeout
  local trigger_file

  mkdir -p "$fixture_home/.claude/hooks/state" "$(dirname "$repo")" "$bin_dir"
  git init -q -b main "$repo"
  git -C "$repo" -c user.name=Fixture -c user.email=fixture@example.com commit --allow-empty -qm init
  real_jq=$(command -v jq)
  printf '%s\n' '#!/bin/bash' 'if [ "$1" = "-n" ]; then exit 1; fi' 'exec "$JQ_REAL" "$@"' > "$bin_dir/jq"
  chmod +x "$bin_dir/jq"
  jq -nc '{type:"user",message:{content:"好，那就結案"}}' > "$transcript"
  input=$(jq -nc --arg session "$name" --arg transcript "$transcript" --arg cwd "$repo" '{session_id:$session,transcript_path:$transcript,cwd:$cwd}')
  output=$(JQ_REAL="$real_jq" PATH="$bin_dir:$PATH" HOME="$fixture_home" env -u CC_VENDOR bash "$SCRIPT" <<< "$input")
  decision=$(printf '%s\n' "$output" | jq -r '.decision // "none"' 2>/dev/null)
  reason=$(printf '%s\n' "$output" | jq -r '.reason // empty' 2>/dev/null)
  scope=$(jq -sr '.[-1].scope // "none"' "$fixture_home/.claude/hooks/state/checkpoint.log" 2>/dev/null)
  git_closeout=$(jq -sr '.[-1].git_closeout // "none"' "$fixture_home/.claude/hooks/state/checkpoint.log" 2>/dev/null)
  trigger_file="$fixture_home/.claude/hooks/state/trigger_$name"

  if [ "$decision" = "block" ] && printf '%s' "$reason" | grep -q '\[checkpoint:trigger:long\]' && ! printf '%s' "$reason" | grep -q 'Git closeout 摘要' && [ "$scope" = "personal" ] && [ "$git_closeout" = "unavailable" ] && [ ! -e "$trigger_file" ]; then
    printf 'PASS %s decision=%s json-fallback=memory-only sentinel=absent\n' "$name" "$decision"
    ((pass++))
  else
    printf 'FAIL %s decision=%s scope=%s closeout=%s sentinel=%s\n' "$name" "$decision" "$scope" "$git_closeout" "$([ -e "$trigger_file" ] && printf present || printf absent)"
    ((fail++))
  fi
}

run_git_scope_case() {
  local name="$1"
  local relative="$2"
  local expected_scope="$3"
  local fixture_home="$TMP/$name/home"
  local repo="$fixture_home/$relative"
  local transcript="$TMP/$name/transcript.jsonl"
  local input
  local output
  local reason
  local decision
  local scope
  local git_closeout

  mkdir -p "$fixture_home/.claude/hooks/state" "$(dirname "$repo")"
  git init -q -b main "$repo"
  git -C "$repo" -c user.name=Fixture -c user.email=fixture@example.com commit --allow-empty -qm init
  jq -nc '{type:"user",message:{content:"好，那就結案"}}' > "$transcript"
  input=$(jq -nc --arg session "$name" --arg transcript "$transcript" --arg cwd "$repo" '{session_id:$session,transcript_path:$transcript,cwd:$cwd}')
  output=$(HOME="$fixture_home" env -u CC_VENDOR bash "$SCRIPT" <<< "$input")
  decision=$(printf '%s\n' "$output" | jq -r '.decision // "none"' 2>/dev/null)
  reason=$(printf '%s\n' "$output" | jq -r '.reason // empty' 2>/dev/null)
  scope=$(jq -sr '.[-1].scope // "none"' "$fixture_home/.claude/hooks/state/checkpoint.log" 2>/dev/null)
  git_closeout=$(jq -sr '.[-1].git_closeout // "none"' "$fixture_home/.claude/hooks/state/checkpoint.log" 2>/dev/null)

  if [ "$decision" = "block" ] && printf '%s' "$reason" | grep -q "scope: $expected_scope" && printf '%s' "$reason" | grep -q 'report-only' && printf '%s' "$reason" | grep -q 'fresh git status' && [ "$scope" = "$expected_scope" ] && [ "$git_closeout" = "included" ]; then
    printf 'PASS %s scope=%s report-only=yes\n' "$name" "$scope"
    ((pass++))
  else
    printf 'FAIL %s scope=%s expected=%s report-only=no closeout=%s\n' "$name" "$scope" "$expected_scope" "$git_closeout"
    ((fail++))
  fi
}

run_git_byte_cap_case() {
  local name="$1"
  local fixture_home="$TMP/$name/home"
  local repo="$fixture_home/Desktop/projects/$name-repo"
  local transcript="$TMP/$name/transcript.jsonl"
  local input
  local output
  local reason
  local decision
  local git_bytes
  local long_text
  local i

  mkdir -p "$fixture_home/.claude/hooks/state" "$(dirname "$repo")"
  git init -q -b main "$repo"
  git -C "$repo" -c user.name=Fixture -c user.email=fixture@example.com commit --allow-empty -qm init
  long_text=$(printf '%02000d' 0 | tr '0' 'x')
  for i in $(seq 1 5); do
    printf 'stash-%s\n' "$i" > "$repo/stash.txt"
    git -C "$repo" stash push -q -u -m "stash-$long_text-$i"
  done
  for i in $(seq 1 20); do
    printf 'dirty-%s\n' "$i" > "$repo/dirty-$i.txt"
  done
  jq -nc '{type:"user",message:{content:"好，那就結案"}}' > "$transcript"
  input=$(jq -nc --arg session "$name" --arg transcript "$transcript" --arg cwd "$repo" '{session_id:$session,transcript_path:$transcript,cwd:$cwd}')
  output=$(HOME="$fixture_home" env -u CC_VENDOR bash "$SCRIPT" <<< "$input")
  decision=$(printf '%s\n' "$output" | jq -r '.decision // "none"' 2>/dev/null)
  reason=$(printf '%s\n' "$output" | jq -r '.reason // empty' 2>/dev/null)
  git_bytes=$(printf '%s' "${reason#*Git closeout}" | wc -c | tr -d ' ')

  if [ "$decision" = "block" ] && printf '%s' "$reason" | grep -q 'stash count: 5' && printf '%s' "$reason" | grep -q 'truncated: dynamic Git content' && [ "$git_bytes" -le 8192 ]; then
    printf 'PASS %s decision=%s git_bytes=%s\n' "$name" "$decision" "$git_bytes"
    ((pass++))
  else
    printf 'FAIL %s decision=%s git_bytes=%s\n' "$name" "$decision" "$git_bytes"
    ((fail++))
  fi
}

run_git_readonly_case() {
  local name="$1"
  local fixture_home="$TMP/$name/home"
  local repo="$fixture_home/Desktop/projects/$name-repo"
  local transcript="$TMP/$name/transcript.jsonl"
  local bin_dir="$TMP/$name/bin"
  local probe_log="$TMP/$name/git-probe.log"
  local real_git
  local input
  local output
  local decision
  local commands

  mkdir -p "$fixture_home/.claude/hooks/state" "$(dirname "$repo")" "$bin_dir"
  git init -q -b main "$repo"
  git -C "$repo" -c user.name=Fixture -c user.email=fixture@example.com commit --allow-empty -qm init
  real_git=$(command -v git)
  printf '%s\n' '#!/bin/bash' 'printf "%s %s\\n" "$GIT_OPTIONAL_LOCKS" "$*" >> "$GIT_PROBE_LOG"' 'exec "$GIT_REAL" "$@"' > "$bin_dir/git"
  chmod +x "$bin_dir/git"
  jq -nc '{type:"user",message:{content:"好，那就結案"}}' > "$transcript"
  input=$(jq -nc --arg session "$name" --arg transcript "$transcript" --arg cwd "$repo" '{session_id:$session,transcript_path:$transcript,cwd:$cwd}')
  output=$(GIT_REAL="$real_git" GIT_PROBE_LOG="$probe_log" PATH="$bin_dir:$PATH" HOME="$fixture_home" env -u CC_VENDOR bash "$SCRIPT" <<< "$input")
  decision=$(printf '%s\n' "$output" | jq -r '.decision // "none"' 2>/dev/null)
  commands=$(printf '%s\n' "$(cat "$probe_log" 2>/dev/null || true)")

  if [ "$decision" = "block" ] && printf '%s' "$commands" | grep -q '0 -C .* status --short' && printf '%s' "$commands" | grep -q '0 -C .* stash list' && printf '%s' "$commands" | grep -q '0 -C .* worktree list' && ! printf '%s' "$commands" | grep -qE ' (fetch|commit|push|merge|reset|checkout)($| )' && ! printf '%s' "$commands" | grep -qE 'worktree (add|remove)|stash (push|pop|drop)'; then
    printf 'PASS %s decision=%s read-only=yes\n' "$name" "$decision"
    ((pass++))
  else
    printf 'FAIL %s decision=%s read-only=no\n' "$name" "$decision"
    ((fail++))
  fi
}

if [ ! -f "$SCRIPT" ]; then
  printf 'FAIL missing hook: %s\n' "$SCRIPT"
  exit 1
fi

run_git_reentry_case "native-git-reentry"
run_git_symlink_scope_case() {
  local name="$1"
  local fixture_home="$TMP/$name/home"
  local repo="$fixture_home/Desktop/work/company"
  local link="$fixture_home/Desktop/projects/company-link"
  local transcript="$TMP/$name/transcript.jsonl"
  local input
  local output
  local reason
  local scope

  mkdir -p "$fixture_home/.claude/hooks/state" "$(dirname "$repo")" "$(dirname "$link")"
  git init -q -b main "$repo"
  git -C "$repo" -c user.name=Fixture -c user.email=fixture@example.com commit --allow-empty -qm init
  ln -s "$repo" "$link"
  jq -nc '{type:"user",message:{content:"好，那就結案"}}' > "$transcript"
  input=$(jq -nc --arg session "$name" --arg transcript "$transcript" --arg cwd "$link" '{session_id:$session,transcript_path:$transcript,cwd:$cwd}')
  output=$(HOME="$fixture_home" env -u CC_VENDOR bash "$SCRIPT" <<< "$input")
  reason=$(printf '%s\n' "$output" | jq -r '.reason // empty' 2>/dev/null)
  scope=$(jq -sr '.[-1].scope // "none"' "$fixture_home/.claude/hooks/state/checkpoint.log" 2>/dev/null)

  if printf '%s' "$reason" | grep -q 'scope: company' && printf '%s' "$reason" | grep -q 'report-only' && [ "$scope" = "company" ]; then
    printf 'PASS %s symlink-scope=%s\n' "$name" "$scope"
    ((pass++))
  else
    printf 'FAIL %s symlink-scope=%s\n' "$name" "$scope"
    ((fail++))
  fi
}

run_git_symlink_scope_case "native-git-symlink-company"
run_git_json_failure_case "native-git-json-failure"
run_git_scope_case "native-git-company" "Desktop/work/company" "company"
run_git_scope_case "native-git-unknown" "Downloads/scratch" "unknown"
run_git_rev_list_failure_case "native-git-rev-list-failure"
run_git_timeout_case "native-git-timeout"
run_git_kill_switch_case "native-git-disabled-env" "env"
run_git_kill_switch_case "native-git-disabled-sentinel" "sentinel"
run_git_kill_switch_recovery_case "native-git-recovery-env" "env"
run_git_kill_switch_recovery_case "native-git-recovery-sentinel" "sentinel"
run_git_unavailable_case "native-git-parent" "parent"
run_git_unavailable_case "native-git-unavailable"
run_git_readonly_case "native-git-readonly"
run_git_byte_cap_case "native-git-byte-cap"
run_git_truncation_case "native-git-truncation"
run_git_inventory_case "native-git-inventory"
run_git_summary_case "native-git-short" "我要收尾嗎" "short"
run_git_summary_case "native-git-summary" "好，那就結案"
run_case "native-conclusion" "__unset__" "好，那就結案" "block" "trigger_long"
run_case "native-empty-conclusion" "__empty__" "好，那就結案" "block" "trigger_long"
run_case "gpt-conclusion" "gpt" "好，那就結案" "block" "trigger_long"
run_case "other-vendor-conclusion" "glm" "好，那就結案" "none" "vendor_skip"
run_case "gpt-discussion-question" "gpt" "現在有觸發結案記憶的 hook 嗎？" "none" "trigger_silent_ctx"
run_turn_case "native-cooldown-49" "__unset__" "49" "繼續" "__none__" "__none__" "none" "seed"
run_turn_case "native-cooldown-50" "__unset__" "50" "繼續" "__none__" "__none__" "none" "seed"
run_turn_case "gpt-cooldown-49" "gpt" "49" "繼續" "__none__" "__none__" "none" "seed"
run_turn_case "gpt-cooldown-50" "gpt" "50" "繼續" "__none__" "__none__" "none" "seed"
run_turn_case "native-refresh-49" "__unset__" "60" "可以" "11" "11" "none" "seed"
run_turn_case "native-refresh-50" "__unset__" "60" "可以" "10" "10" "none" "seed"
run_turn_case "native-refresh-51" "__unset__" "60" "可以" "9" "9" "none" "seed"

printf '%s\n' "---- $pass pass / $fail fail ----"
exit "$fail"
