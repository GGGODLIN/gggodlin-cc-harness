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
      # pi 的 live session 是紀錄檔路徑（檔名結尾 _<uuid>.jsonl），收據的 session_id 是 uuid，所以也接受以該 uuid 結尾的路徑。
      worker_info=$(printf '%s' "$worker_result" | python3 -c 'import json,sys; d=json.load(sys.stdin); a=d.get("result",{}).get("agent",{}); p=a.get("pane_id",""); s=(a.get("agent_session") or {}).get("value",""); state="match" if p==sys.argv[1] and (s==sys.argv[2] or s.endswith("_"+sys.argv[2]+".jsonl")) else "mismatch"; print("\t".join((state,p,s))) if d.get("ok") is not False and p and s else sys.exit(1)' "$WORKER_PANE" "$SESSION" 2>/dev/null) || worker_info=""
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
elif [ "$BACKEND" = herdr-core ]; then
  HC_BIN="${HC_BIN:-hc}"
  target="${WORKER_PANE:-$WORKER}"
  max_timeouts="${HC_WAIT_MAX_TIMEOUTS:-40}"
  transition_sleep="${HC_WAIT_TRANSITION_SLEEP:-1}"
  idle_polls="${HC_AWAIT_NEXT_TURN_POLLS:-1200}"
  idle_interval="${HC_AWAIT_NEXT_TURN_INTERVAL:-3}"
  last_notified_turn=""
  if [ -f "$LOG" ]; then
    last_notified_turn=$(python3 -c '
import json, re, sys
path, target = sys.argv[1], sys.argv[2]
last_wait_turn = ""
notified = ""
try:
  lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
except OSError:
  lines = []
for line in lines:
  m = re.search(r"\bnotified target=(\S+) worker_turn=(\d+)\b", line)
  if m and m.group(1) == target:
    notified = m.group(2)
    continue
  if "wait rc=0 result=" in line:
    raw = line.split("wait rc=0 result=", 1)[1].strip()
    try:
      d = json.loads(raw)
      if isinstance(d, dict) and d.get("terminal") in ("", None, target) and isinstance(d.get("turn"), int):
        last_wait_turn = str(d["turn"])
    except Exception:
      pass
  elif "send rc=0 status=" in line and last_wait_turn:
    if re.search(r"\bsend rc=0 status=(idle|done|blocked|error)\b", line):
      notified = last_wait_turn
print(notified)
' "$LOG" "$target" 2>/dev/null) || last_notified_turn=""
  fi
  status=""
  worker_turn=""
  for ((i = 0; i < max_timeouts; i++)); do
    result=$("$HC_BIN" wait "$target" 2>&1)
    rc=$?
    log "wait rc=$rc result=$(printf '%s' "$result" | head -c 300)"
    if [ "$rc" -ne 0 ]; then
      status=""
      break
    fi
    parsed=$(printf '%s' "$result" | python3 -c '
import json, sys
d = json.load(sys.stdin)
if not isinstance(d, dict) or d.get("ok") is False or d.get("error"):
  sys.exit(1)
st = d.get("status")
if isinstance(st, dict):
  st = st.get("state")
if not isinstance(st, str):
  st = ""
w = d.get("wait")
if not st and isinstance(w, dict):
  wst = w.get("status")
  st = wst.get("state") if isinstance(wst, dict) else (wst if isinstance(wst, str) else "")
reason = d.get("reason") or (w.get("reason") if isinstance(w, dict) else "") or ""
turn = d.get("turn")
if not isinstance(turn, int) and isinstance(w, dict) and isinstance(w.get("turn"), int):
  turn = w.get("turn")
turn_s = str(turn) if isinstance(turn, int) and not isinstance(turn, bool) else ""
if reason == "timeout" or d.get("ended") is False:
  print(f"TIMEOUT\t{turn_s}")
  sys.exit(0)
# hc wait 撞上剛從 done 切回 working 的瞬間會回 ended=true 但 status=working；當成未驗證退場會誤報並掉哨兵。
if st in {"working", "starting", "running"}:
  print(f"WORKING\t{turn_s}")
elif st in {"idle", "done", "blocked", "error"}:
  print(f"{st}\t{turn_s}")
elif reason in {"idle", "done", "blocked", "exited", "exit", "error"}:
  out_st = "exited" if reason == "exit" else reason
  print(f"{out_st}\t{turn_s}")
else:
  print(f"\t{turn_s}")
' 2>/dev/null) || parsed=""
    parsed_state="${parsed%%$'\t'*}"
    parsed_turn=""
    if [[ "$parsed" == *$'\t'* ]]; then
      parsed_turn="${parsed#*$'\t'}"
    fi
    if [ "$parsed_state" = "TIMEOUT" ]; then
      last_notified_turn=""
      continue
    fi
    if [ "$parsed_state" = "WORKING" ]; then
      log "wait caught working transition turn=$parsed_turn, continuing"
      last_notified_turn=""
      sleep "$transition_sleep"
      continue
    fi
    # worker 丟背景測試後停在 done，main 立刻重掛時 turn 尚未推進；若當場報 stopped 會把單發 watcher 提早消耗掉。
    if { [ "$parsed_state" = "done" ] || [ "$parsed_state" = "idle" ]; } && [ -n "$last_notified_turn" ] && [ -n "$parsed_turn" ] && [ "$parsed_turn" = "$last_notified_turn" ]; then
      log "worker still at already-notified turn=$parsed_turn ($parsed_state), waiting for background task or next turn"
      advanced=0
      immediate_stop=""
      for ((p = 0; p < idle_polls; p++)); do
        sleep "$idle_interval"
        poll_raw=$("$HC_BIN" get "$target" 2>&1) || { immediate_stop="exited"; break; }
        poll_info=$(printf '%s' "$poll_raw" | python3 -c '
import json, sys
d = json.load(sys.stdin)
if not isinstance(d, dict) or d.get("ok") is False or d.get("error"):
  sys.exit(1)
live = d.get("state")
live_s = str(live).replace("\x1f", "").replace("\n", "").replace("\r", "") if isinstance(live, str) else ""
st = d.get("status")
if isinstance(st, dict):
  st = st.get("state")
st_s = st.replace("\x1f", "").replace("\n", "").replace("\r", "") if isinstance(st, str) else ""
turn = d.get("turn")
turn_s = str(turn) if isinstance(turn, int) and not isinstance(turn, bool) else ""
print(f"{live_s}\x1f{st_s}\x1f{turn_s}")
' 2>/dev/null) || { immediate_stop="exited"; break; }
        # Use non-whitespace US (\x1f) so empty st does not collapse adjacent delimiters and drop poll_turn.
        IFS=$'\x1f' read -r poll_live poll_st poll_turn <<< "$poll_info"
        if [ "$poll_live" != "live" ]; then
          immediate_stop="exited"
          break
        fi
        if [ "$poll_st" = "working" ] || [ "$poll_st" = "starting" ] || [ "$poll_st" = "running" ] || { [ -n "$poll_turn" ] && [ "$poll_turn" != "$last_notified_turn" ]; }; then
          log "worker resumed activity state=$poll_st turn=$poll_turn, re-entering wait"
          last_notified_turn=""
          advanced=1
          break
        fi
        if [ "$poll_st" = "blocked" ] || [ "$poll_st" = "error" ]; then
          immediate_stop="$poll_st"
          worker_turn="$poll_turn"
          last_notified_turn=""
          break
        fi
      done
      if [ "$advanced" -eq 1 ]; then
        continue
      fi
      if [ -n "$immediate_stop" ]; then
        status="$immediate_stop"
        break
      fi
      log "await_next_turn timed out at turn=$parsed_turn, exiting without duplicate wake"
      exit 0
    fi
    status="$parsed_state"
    worker_turn="$parsed_turn"
    break
  done
  if [ -z "$status" ]; then
    log "wait did not confirm stopped status, worker unverified"
  fi
  main_result=$("$HC_BIN" get "$PARENT" 2>&1)
  main_rc=$?
  main_ok=0
  if [ "$main_rc" -eq 0 ]; then
    main_ok=$(printf '%s' "$main_result" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("1" if isinstance(d,dict) and d.get("state")=="live" and d.get("address",sys.argv[1])==sys.argv[1] else "0")' "$PARENT" 2>/dev/null) || main_ok=0
  fi
  if [ "$main_ok" != 1 ]; then
    log "未送達 main identity unverified parent=$PARENT lookup_rc=$main_rc"
    exit 1
  fi
  if [ -n "$status" ]; then
    message="[watcher] worker $WORKER stopped, status=$status, $(date +%H:%M). Read its screen and jsonl, then report."
  else
    message="[watcher] worker $WORKER 身分未驗證，需調查；不要認定工作已完成。請查看 watcher log。"
  fi
  prompt=$("$HC_BIN" send "$PARENT" "$message" 2>&1)
  prompt_rc=$?
  log "send rc=$prompt_rc status=$status result=$(printf '%s' "$prompt" | head -c 300)"
  if [ "$prompt_rc" -ne 0 ]; then
    log "未送達 hc send failed parent=$PARENT status=$status"
    exit "$prompt_rc"
  fi
  if [ -n "$status" ] && [ -n "$worker_turn" ]; then
    log "notified target=$target worker_turn=$worker_turn status=$status"
  fi
  exit 0
fi
log "unknown backend, no wake sent"
exit 2
