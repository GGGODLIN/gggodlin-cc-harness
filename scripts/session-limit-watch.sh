#!/usr/bin/env bash
# session-limit-watch.sh [LOW_THRESHOLD] [POLL_SECONDS] [MAX_MINUTES]
#
# Dumb execution body for /session-monitor. Polls CC's quota cache (refreshed by CC
# every ~60-90s even while idle) and exits the MOMENT the CURRENTLY LOGGED-IN
# account's 5h utilization drops to <= LOW_THRESHOLD — i.e. the rolling window
# recovered. Account-aware: follows /login switches live.
#
# Reads ONLY the target account. An unreadable cache is unknown, never a number:
# it keeps polling rather than substituting another account's figure. The old
# MIN-across-all fallback was removed 2026-09-09 — with two visible accounts it
# let a read failure silently swap a strict policy ("has MY window recovered")
# for a loose one ("does anyone have room"), so a glitch, not a quota change,
# decided when to wake the session. Waking on an idle account's number tells a
# session authenticated to the exhausted one to "just continue", and it hits the
# wall again on its next request. Never observed firing (0 hits for the old
# min-fallback marker across session history), so this is a latent-path fix.
#
# If "anyone has room" is ever the goal, it needs its own explicit policy that
# also applies when the target account reads fine, plus a defined owner for the
# account switch — not a branch that only runs when a read fails.
#
# Run via the main session's Bash(run_in_background=true): its exit re-invokes the
# main session = the wake bridge. A hook/externally-launched copy does NOT get that
# bridge — must be main-session-launched.
#
# Deliberately a SEPARATE file from workflow-limit-watch.sh: workflow-monitor
# dedupes via `pgrep -f workflow-limit-watch.sh`; sharing one filename would make
# each tool falsely skip arming when the other's watcher is running.
#
# exit 0 = quota recovered. exit 2 = safety timeout (orphan guard).
set -uo pipefail
LOW=${1:-5}
POLL=${2:-60}
MAX_MINUTES=${3:-330}
shopt -s nullglob 2>/dev/null || true
deadline=$(( $(date +%s) + MAX_MINUTES * 60 ))

# 帳號解析走 lib（兩段式：CLAUDE_CONFIG_DIR 優先、$HOME 退回）——只讀 $HOME 會在
# lock session（cc -max / cc -team）盯錯帳號。2026-08-01 實錯見 lib 檔頭。
printf '%s\n' 'harness: wiring point "多帳號與帳號判定" is not provided in this public copy; see WIRING.md' >&2; exit 1
read_active_5h() {
  local f u
  f=$(cc_resolve_quota_file) || return 1
  [ -f "$f" ] || return 1
  u=$(jq -r '.data.five_hour.utilization // empty' "$f" 2>/dev/null)
  [[ "$u" =~ ^[0-9]+$ ]] || return 1
  printf '%s' "$u"
}
last_read="never"
while true; do
  if cur=$(read_active_5h); then
    last_read="$cur%"
    if (( cur <= LOW )); then
      echo "SESSION-LIMIT-WATCH: 5h=${cur}% <= ${LOW}% at $(date +%H:%M:%S) — quota window recovered"
      echo "ACTION: 額度已恢復。直接繼續被 5h 限額中斷前的工作（對話 context 都還在，不需要任何 resume 儀式）。若使用者已手動續上或沒有待續工作，簡短回報後結束即可。"
      exit 0
    fi
  else
    last_read="unreadable"
  fi
  if (( $(date +%s) >= deadline )); then
    if [[ "$last_read" == "unreadable" || "$last_read" == "never" ]]; then
      echo "session-limit-watch safety-timeout after ${MAX_MINUTES}min — target account's 5h was ${last_read}, so this timeout means the watcher went blind, NOT that quota stayed exhausted. Check cc_resolve_quota_file and ~/.claude/cache/quota-<email>.json."
    else
      echo "session-limit-watch safety-timeout after ${MAX_MINUTES}min (5h=${last_read} on the target account, never reached ${LOW}%), exiting"
    fi
    exit 2
  fi
  sleep "$POLL"
done
