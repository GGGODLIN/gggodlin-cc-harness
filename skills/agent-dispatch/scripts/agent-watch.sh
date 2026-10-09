#!/bin/bash
set -u
set -o pipefail
export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
[ "$#" -ge 4 ] || exit 2
BACKEND="$1"
WORKER="$2"
PARENT="$3"
LOG="$4"
SESSION="${5:-}"
CWD="${6:-}"
PARENT_SESSION="${7:-${CLAUDE_CODE_SESSION_ID:-}}"
WORKER_PANE="${8:-}"
log() {
  printf '%s %s\n' "$(date +%H:%M:%S)" "$*" >> "$LOG"
}
log "start waiting backend=$BACKEND worker=$WORKER parent=$PARENT session=$SESSION"
if [ "$BACKEND" = herdr ]; then
  result=$(herdr agent wait "${WORKER_PANE:-$WORKER}" --until idle --until blocked --until done 2>&1)
  rc=$?
  log "wait rc=$rc result=$(printf '%s' "$result" | head -c 300)"
  status=""
  if [ "$rc" -eq 0 ]; then
    status=$(printf '%s' "$result" | python3 -c 'import json,sys; d=json.load(sys.stdin); a=d.get("result",{}).get("agent",{}); status=a.get("agent_status"); print(status if d.get("ok") is not False and status in {"idle","blocked","done"} else "")' 2>/dev/null) || status=""
  fi
  if [ -z "$status" ]; then
    log "wait did not confirm stopped status, worker unverified"
  fi
  worker_state=unknown
  live_pane=""
  live_session=""
  if [ -n "$status" ] && [ -n "$SESSION" ] && [ -n "$WORKER_PANE" ]; then
    worker_result=$(herdr agent get "$WORKER_PANE" 2>&1)
    worker_rc=$?
    if [ "$worker_rc" -eq 0 ]; then
      worker_info=$(printf '%s' "$worker_result" | python3 -c 'import json,sys; d=json.load(sys.stdin); a=d.get("result",{}).get("agent",{}); p=a.get("pane_id",""); s=(a.get("agent_session") or {}).get("value",""); state="match" if p==sys.argv[1] and s==sys.argv[2] else "mismatch"; print("\t".join((state,p,s))) if d.get("ok") is not False and p and s else sys.exit(1)' "$WORKER_PANE" "$SESSION" 2>/dev/null) || worker_info=""
      if [ -n "$worker_info" ]; then
        IFS=$'\t' read -r worker_state live_pane live_session <<< "$worker_info"
      fi
    fi
    log "worker identity state=$worker_state receipt_pane=$WORKER_PANE receipt_session=$SESSION live_pane=$live_pane live_session=$live_session"
  else
    log "worker identity state=unknown incomplete launch receipt or unconfirmed wait"
  fi
  if [ -z "$PARENT_SESSION" ]; then
    log "未送達 main session missing from launch receipt"
    exit 1
  fi
  main_result=$(herdr agent get "$PARENT" 2>&1)
  main_rc=$?
  main_ok=0
  if [ "$main_rc" -eq 0 ]; then
    main_ok=$(printf '%s' "$main_result" | python3 -c 'import json,sys; d=json.load(sys.stdin); a=d.get("result",{}).get("agent",{}); print("1" if d.get("ok") is not False and a.get("pane_id")==sys.argv[1] and a.get("agent_session",{}).get("value")==sys.argv[2] else "0")' "$PARENT" "$PARENT_SESSION" 2>/dev/null) || main_ok=0
  fi
  if [ "$main_ok" != 1 ]; then
    log "未送達 main identity unverified parent=$PARENT lookup_rc=$main_rc worker_state=$worker_state"
    exit 1
  fi
  if [ "$worker_state" = match ]; then
    message="[watcher] worker $WORKER stopped, status=$status, $(date +%H:%M). Read its screen and jsonl, then report."
  elif [ "$worker_state" = mismatch ]; then
    message="[watcher] worker $WORKER 身分異常：啟動收據與目前 worker 不符。不要把舊結果當作本次完成；請查看 watcher log。"
  else
    message="[watcher] worker $WORKER 身分未驗證，需調查；不要認定工作已完成。請查看 watcher log。"
  fi
  prompt=$(herdr agent prompt "$PARENT" "$message" 2>&1)
  prompt_rc=$?
  log "prompt rc=$prompt_rc worker_state=$worker_state result=$(printf '%s' "$prompt" | head -c 300)"
  if [ "$prompt_rc" -ne 0 ]; then
    log "未送達 Herdr prompt failed parent=$PARENT worker_state=$worker_state"
    exit "$prompt_rc"
  fi
  if [ "$worker_state" = match ]; then
    notification=$(herdr notification show "$WORKER stopped" --body "status $status" --sound done 2>&1)
    log "notify rc=$? result=$(printf '%s' "$notification" | head -c 200)"
  fi
  exit 0
fi
log "unknown backend, no wake sent"
exit 2
