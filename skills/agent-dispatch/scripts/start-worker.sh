#!/bin/bash
set -u
set -o pipefail
export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
HERE="$(cd "$(dirname "$0")" && pwd)"
fail() {
  printf '%s\n' "$*" >&2
  exit 2
}
[ "$#" -ge 3 ] || fail "usage: start-worker.sh <worker name> <worktree path> <brief file> [--harness claude|codex|pi] [--recipe JSON] [--label L] [--model M] [--effort E] [--log-dir D] [--no-watch]"
NAME="$1"
CWD="$2"
BRIEF="$3"
shift 3
LABEL="$NAME"
HARNESS="claude"
MODEL=""
EFFORT=""
RECIPE=""
LOGDIR=""
WATCH=1
while [ "$#" -gt 0 ]; do
  case "$1" in
    --harness)
      [ "$#" -ge 2 ] || fail "missing value for --harness"
      HARNESS="$2"
      shift 2
      ;;
    --recipe)
      [ "$#" -ge 2 ] || fail "missing value for --recipe"
      RECIPE="$2"
      shift 2
      ;;
    --label)
      [ "$#" -ge 2 ] || fail "missing value for --label"
      LABEL="$2"
      shift 2
      ;;
    --model)
      [ "$#" -ge 2 ] || fail "missing value for --model"
      MODEL="$2"
      shift 2
      ;;
    --effort)
      [ "$#" -ge 2 ] || fail "missing value for --effort"
      EFFORT="$2"
      shift 2
      ;;
    --log-dir)
      [ "$#" -ge 2 ] || fail "missing value for --log-dir"
      LOGDIR="$2"
      shift 2
      ;;
    --no-watch)
      WATCH=0
      shift
      ;;
    *)
      fail "unknown arg $1"
      ;;
  esac
done
# 每個外殼決定 Herdr kind、必填配方與傳給 canonical 執行檔的參數；
# 新外殼在這裡加一個分支，start_herdr 之後不必再動。
KIND=""
START_ARGS=()
TAB_ENV_ARGS=()
PI_UUID=""
PI_PICK="${PI_PICK_BIN:-pi-pick}"
CC_PICK="${CC_PICK_BIN:-cc-pick}"
UNSET_NAMES=()
[ -z "$RECIPE" ] || [ "$HARNESS" = pi ] || [ "$HARNESS" = claude ] || fail "--recipe is not supported for --harness $HARNESS"

# pi-pick 的 dry-run 是配方的唯一驗證者；它失敗就一律不建 tab。
# 成功時把 args 與 environment 攤成 NUL 分隔的 A／E 項目，bash 3.2 沒有 mapfile 所以逐項 read。
prepare_pi_launch() {
  local out err_file rc err item tag val
  err_file=$(mktemp "${TMPDIR:-/tmp}/start-worker-pi-pick.XXXXXX") || fail "could not create temp file"
  out=$("$PI_PICK" --recipe "$RECIPE" --dry-run 2>"$err_file")
  rc=$?
  err=$(cat "$err_file")
  rm -f "$err_file"
  [ "$rc" -eq 0 ] || fail "pi-pick rejected the recipe (rc=$rc): $err"
  [ -z "$err" ] || printf '%s\n' "$err" >&2
  # pi-pick 在 relay 來源失敗時只警告仍 rc=0，此時 PI_RELAY_CATALOG 是空字串，代表 relay 檢查根本沒跑。
  printf '%s' "$out" | python3 -c '
import json, re, sys
try:
  d = json.loads(sys.stdin.read())
except json.JSONDecodeError as e:
  sys.exit("pi-pick dry-run output is not JSON: %s" % e)
args = d.get("args") if isinstance(d, dict) else None
env = d.get("environment") if isinstance(d, dict) else None
# NUL 是下面攤平串流的分隔符；值裡夾帶會讓 tag 與值錯位，多出沒檢查過的項目。
clean = lambda s: isinstance(s, str) and "\x00" not in s
if not isinstance(args, list) or not all(clean(a) for a in args):
  sys.exit("pi-pick dry-run output has no valid args array (non-string or NUL character)")
if not isinstance(env, dict) or not all(clean(v) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k) for k, v in env.items()):
  sys.exit("pi-pick dry-run output has no valid environment object (bad name, non-string or NUL character)")
if not env.get("PI_RELAY_CATALOG"):
  sys.exit("pi-pick did not verify the relay (PI_RELAY_CATALOG is empty); refusing to start without a verified recipe")
' || fail "pi-pick dry-run output unusable (see message above)"
  PI_UUID=$(python3 -c 'import uuid; print(uuid.uuid4())') || fail "could not generate a pi session id"
  while IFS= read -r -d '' tag && IFS= read -r -d '' val; do
    if [ "$tag" = A ]; then
      START_ARGS+=("$val")
    else
      TAB_ENV_ARGS+=(--env "$val")
    fi
  done < <(printf '%s' "$out" | python3 -c '
import json, sys
d = json.loads(sys.stdin.read())
w = sys.stdout.buffer.write
for a in d["args"]:
  w(b"A\0" + a.encode() + b"\0")
for k, v in d["environment"].items():
  w(b"E\0" + (k + "=" + v).encode() + b"\0")
')
  # --approve：沒帶時 pi 對有 .pi/settings.json 的 worktree 跳信任框，Herdr 卻回報 idle，brief 會被打進確認框。
  START_ARGS+=(--approve --session-id "$PI_UUID")
}

# cc-pick 的 dry-run 是 claude 配方的唯一驗證者；它失敗就一律不建 tab。
# env 變數用 tab create --env 設；unset 沒有 --env 可表達，由 start_herdr 在 agent start 前用 pane run 清掉。
prepare_claude_launch() {
  local out err_file rc err tag val
  err_file=$(mktemp "${TMPDIR:-/tmp}/start-worker-cc-pick.XXXXXX") || fail "could not create temp file"
  out=$("$CC_PICK" --recipe "$RECIPE" --dry-run 2>"$err_file")
  rc=$?
  err=$(cat "$err_file")
  rm -f "$err_file"
  [ "$rc" -eq 0 ] || fail "cc-pick rejected the recipe (rc=$rc): $err"
  [ -z "$err" ] || printf '%s\n' "$err" >&2
  printf '%s' "$out" | python3 -c '
import json, re, sys
try:
  d = json.loads(sys.stdin.read())
except json.JSONDecodeError as e:
  sys.exit("cc-pick dry-run output is not JSON: %s" % e)
d = d if isinstance(d, dict) else {}
args, env, unset = d.get("args"), d.get("env"), d.get("unset")
name = r"[A-Za-z_][A-Za-z0-9_]*"
# NUL 是下面攤平串流的分隔符；值裡夾帶會讓 tag 與值錯位，多出沒檢查過的 unset 名稱或 --env 項目。
clean = lambda s: isinstance(s, str) and "\x00" not in s
if not isinstance(args, list) or not all(clean(a) for a in args):
  sys.exit("cc-pick dry-run output has no valid args array (non-string or NUL character)")
if not isinstance(env, dict) or not all(clean(v) and re.fullmatch(name, k) for k, v in env.items()):
  sys.exit("cc-pick dry-run output has no valid env object (bad name, non-string or NUL character)")
if not isinstance(unset, list) or not all(clean(k) and re.fullmatch(name, k) for k in unset):
  sys.exit("cc-pick dry-run output has no valid unset array (bad name, non-string or NUL character)")
' || fail "cc-pick dry-run output unusable (see message above)"
  while IFS= read -r -d '' tag && IFS= read -r -d '' val; do
    case "$tag" in
      A) START_ARGS+=("$val") ;;
      E) TAB_ENV_ARGS+=(--env "$val") ;;
      U) UNSET_NAMES+=("$val") ;;
    esac
  done < <(printf '%s' "$out" | python3 -c '
import json, sys
d = json.loads(sys.stdin.read())
w = sys.stdout.buffer.write
for a in d["args"]:
  w(b"A\0" + a.encode() + b"\0")
for k, v in d["env"].items():
  w(b"E\0" + (k + "=" + v).encode() + b"\0")
for k in d["unset"]:
  w(b"U\0" + k.encode() + b"\0")
')
}

case "$HARNESS" in
  claude)
    KIND=claude
    if [ -n "$RECIPE" ]; then
      [ -z "$MODEL" ] && [ -z "$EFFORT" ] || fail "--model/--effort do not apply with --recipe for --harness claude; model and effort are slots in the --recipe JSON"
      command -v "$CC_PICK" >/dev/null 2>&1 || fail "cc-pick not found ($CC_PICK); cannot validate the claude recipe"
      prepare_claude_launch
    else
      MODEL="${MODEL:-opus[1m]}"
      EFFORT="${EFFORT:-high}"
      START_ARGS=(--model "$MODEL" --effort "$EFFORT")
    fi
    # Herdr 新分頁不繼承 main 的 CLAUDE_CONFIG_DIR；沒帶過去就落在預設 ~/.claude，
    # 那份登入失效時 worker 一開就回 Login expired。main 在跑就代表它的設定目錄是登入中的。
    [ -z "${CLAUDE_CONFIG_DIR:-}" ] || TAB_ENV_ARGS+=(--env "CLAUDE_CONFIG_DIR=$CLAUDE_CONFIG_DIR")
    ;;
  codex)
    [ -n "$MODEL" ] || fail "--harness codex requires --model (the default opus[1m] is meaningless for codex)"
    [ -n "$EFFORT" ] || fail "--harness codex requires --effort"
    command -v codex >/dev/null 2>&1 || fail "codex executable not found in PATH; cannot start a codex worker"
    KIND=codex
    # check_for_update_on_startup=false：否則 Codex 啟動先跳更新選單，Herdr 回 agent_not_ready。
    START_ARGS=(-m "$MODEL" -c "model_reasoning_effort=$EFFORT" -c check_for_update_on_startup=false --dangerously-bypass-approvals-and-sandbox)
    ;;
  pi)
    [ -n "$RECIPE" ] || fail "--harness pi requires --recipe (a pi-pick recipe JSON)"
    [ -z "$MODEL" ] && [ -z "$EFFORT" ] || fail "--model/--effort do not apply to --harness pi; put them in the --recipe JSON"
    command -v pi >/dev/null 2>&1 || fail "pi executable not found in PATH; cannot start a pi worker"
    command -v "$PI_PICK" >/dev/null 2>&1 || fail "pi-pick not found ($PI_PICK); cannot validate the pi recipe"
    KIND=pi
    prepare_pi_launch
    ;;
  *)
    fail "unknown harness: $HARNESS"
    ;;
esac
[ -d "$CWD" ] || fail "worktree not found: $CWD"
[ -f "$BRIEF" ] || fail "brief not found: $BRIEF"
CWD="$(cd "$CWD" && pwd -P)"
LOGDIR="${LOGDIR:-$(dirname "$BRIEF")/watch-logs}"
mkdir -p "$LOGDIR" || fail "could not create log directory: $LOGDIR"

HC_BIN="${HC_BIN:-hc}"
HERDR_APP_BIN="${HERDR_APP_BIN:-herdr-app}"

HERDR_ANY=0
if [ -n "${HERDR_PANE_ID:-}" ] || [ -n "${HERDR_WORKSPACE_ID:-}" ]; then
  [ -n "${HERDR_PANE_ID:-}" ] && [ -n "${HERDR_WORKSPACE_ID:-}" ] || fail "incomplete Herdr parent identity"
  HERDR_ANY=1
fi
# 若 hc serve 從舊版 herdr 內啟動，子程序會同時帶完整 HERDR_PANE_ID/HERDR_WORKSPACE_ID 與 HC_TERMINAL_ID；內層 HC_TERMINAL_ID 優先。
if [ -n "${HC_TERMINAL_ID:-}" ]; then
  BACKEND=herdr-core
elif [ "$HERDR_ANY" -eq 1 ]; then
  BACKEND=herdr
else
  fail "no supported parent terminal identity; use Herdr"
fi

check_json_ok() {
  printf '%s' "$1" | python3 -c 'import json,sys; s=sys.stdin.read().strip();
try:
 d=json.loads(s); raise SystemExit(1 if d.get("ok") is False else 0)
except json.JSONDecodeError:
 raise SystemExit(0)'
}

herdr_parent_is_live() {
  local result
  result=$(herdr pane get "$HERDR_PANE_ID" 2>&1) || return 1
  printf '%s' "$result" | python3 -c 'import json,sys; d=json.load(sys.stdin); p=d.get("result",{}).get("pane",{}); ok=p.get("pane_id")==sys.argv[1] and p.get("workspace_id")==sys.argv[2]; raise SystemExit(0 if ok else 1)' "$HERDR_PANE_ID" "$HERDR_WORKSPACE_ID"
}

hc_parent_is_live() {
  local result
  result=$("$HC_BIN" get "$HC_TERMINAL_ID" 2>&1) || return 1
  printf '%s' "$result" | python3 -c 'import json,sys; d=json.load(sys.stdin); ok=isinstance(d,dict) and d.get("address")==sys.argv[1] and d.get("state")=="live"; raise SystemExit(0 if ok else 1)' "$HC_TERMINAL_ID" 2>/dev/null
}

if [ "$BACKEND" = herdr ]; then
  herdr_parent_is_live || fail "Herdr parent target is not live: $HERDR_PANE_ID"
else
  hc_parent_is_live || fail "Herdr-core parent target is not live: $HC_TERMINAL_ID"
fi

cleanup_herdr_tab() {
  [ -n "${1:-}" ] && herdr tab close "$1" >/dev/null 2>&1 || true
}

# 回傳 0＝stdout 是 session；2＝herdr 失敗、stdout 是錯誤文字；其他＝還沒有 session。
# agent_session 可能是 null（Codex 剛啟動時），所以用 `or {}` 取值。
lookup_session() {
  local agents
  agents=$(herdr agent list 2>&1) || { printf '%s' "$agents"; return 2; }
  printf '%s' "$agents" | python3 -c '
import json, sys
try:
  d = json.load(sys.stdin)
except Exception as e:
  sys.stdout.write(f"invalid herdr agent list JSON: {e}")
  sys.exit(2)
name, pane = sys.argv[1], sys.argv[2]
xs = [x for x in d.get("result", {}).get("agents", []) if x.get("name") == name and x.get("pane_id") == pane]
r = (xs[0].get("agent_session") or {}).get("value", "") if xs else ""
print(r) if r else sys.exit(1)
' "$NAME" "$pane"
}

# Codex 送出第一則 prompt 後約 2 秒才有 session，所以在送 brief 之後有限次輪詢。
poll_session() {
  local i max interval out rc
  max="${START_WORKER_SESSION_POLLS:-30}"
  interval="${START_WORKER_SESSION_POLL_INTERVAL:-1}"
  for ((i = 0; i < max; i++)); do
    rc=0
    out=$(lookup_session) || rc=$?
    if [ "$rc" -eq 0 ]; then
      printf '%s' "$out"
      return 0
    elif [ "$rc" -eq 2 ]; then
      printf '%s' "$out"
      return 2
    fi
    [ "$i" -lt $((max - 1)) ] && sleep "$interval"
  done
  return 1
}

# worker 專屬的 provider 重試只寫進 worktree 的專案設定，不碰全域 ~/.pi/agent/settings.json。
# 已存在的 .pi/settings.json 可能是 repo 自己 commit 的，不覆寫也不合併。
prepare_pi_worktree() {
  local settings exclude line
  settings="$CWD/.pi/settings.json"
  line="/.pi/settings.json"
  if [ -e "$settings" ]; then
    printf '%s\n' "warning: 沿用既有 .pi/settings.json，未加 worker 專屬重試" >&2
    return 0
  fi
  exclude=$(git -C "$CWD" rev-parse --path-format=absolute --git-path info/exclude 2>/dev/null) || fail "cannot resolve info/exclude for pi worktree: $CWD"
  mkdir -p "$(dirname "$exclude")" "$CWD/.pi" || fail "could not create .pi in $CWD"
  if ! command grep -qxF "$line" "$exclude" 2>/dev/null; then
    if [ -s "$exclude" ] && [ -n "$(tail -c1 "$exclude")" ]; then
      printf '\n' >> "$exclude" || fail "could not update $exclude"
    fi
    printf '%s\n' "$line" >> "$exclude" || fail "could not update $exclude"
  fi
  printf '%s\n' '{"retry":{"provider":{"maxRetries":30,"maxRetryDelayMs":0}}}' > "$settings" || fail "could not write $settings"
}

# 不依賴使用者 shell 設定：配方要求清掉的變數，在 claude 啟動前由 shell 自己 unset。
# 新 tab 的 shell 還在初始化時，pane run 會被靜默丟掉（rc=0），所以只信回顯不含的完成標記，沒等到就重送。
confirm_pane_unset() {
  local pane tab cmd out i max
  pane="$1"
  tab="$2"
  max=5
  cmd="unset ${UNSET_NAMES[*]}; printf 'AGENT_DISPATCH_UNSET%s\\n' _DONE"
  for ((i = 0; i < max; i++)); do
    out=$(herdr pane run "$pane" "$cmd" 2>&1) || { cleanup_herdr_tab "$tab"; fail "Herdr pane run unset failed: $out"; }
    [ -z "$out" ] || check_json_ok "$out" || { cleanup_herdr_tab "$tab"; fail "Herdr pane run unset returned ok:false: $out"; }
    herdr pane wait-output "$pane" --match AGENT_DISPATCH_UNSET_DONE --timeout 3000 >/dev/null 2>&1 && return 0
  done
  cleanup_herdr_tab "$tab"
  fail "unset of recipe variables was not confirmed after $max attempts in pane $pane; tab closed"
}

session_continued_into() {
  local old_sid="$1" target_sid="$2"
  python3 -I - "$old_sid" "$target_sid" <<'PY'
import glob, json, os, sys
from pathlib import Path

old_sid, target_sid = sys.argv[1], sys.argv[2]
roots = []
for base in [os.environ.get("CLAUDE_CONFIG_DIR"), os.path.expanduser("~/.claude")]:
  if base:
    p = Path(base) / "projects"
    if p.is_dir() and p not in roots:
      roots.append(p)
for root in roots:
  for start_file in root.glob(f"*/{old_sid}.jsonl"):
    proj_dir = start_file.parent
    cur = old_sid
    seen = {cur}
    for _ in range(10):
      cur_file = proj_dir / f"{cur}.jsonl"
      if not cur_file.is_file():
        break
      nxt = None
      try:
        with cur_file.open(encoding="utf-8", errors="replace") as fh:
          for line in fh:
            if '"continued-in"' not in line:
              continue
            try:
              obj = json.loads(line)
            except ValueError:
              continue
            if obj.get("type") == "continued-in" and obj.get("sessionId") == cur:
              cand = obj.get("continuedInSessionId")
              if isinstance(cand, str) and cand:
                nxt = cand
      except OSError:
        break
      if not nxt or nxt in seen:
        break
      if nxt == target_sid and (proj_dir / f"{target_sid}.jsonl").is_file():
        sys.exit(0)
      seen.add(nxt)
      cur = nxt
sys.exit(1)
PY
}

start_herdr() {
  local main main_identity main_session ws created created_info pane tab started agents session prompt log first_error
  main="$HERDR_PANE_ID"
  ws="$HERDR_WORKSPACE_ID"
  main_identity=$(herdr agent get "$main" 2>&1) || fail "Herdr main identity unavailable: $main_identity"
  main_session=$(printf '%s' "$main_identity" | python3 -c 'import json,sys; d=json.load(sys.stdin); a=d.get("result",{}).get("agent",{}); s=a.get("agent_session",{}).get("value",""); print(s) if a.get("pane_id")==sys.argv[1] and s else sys.exit(1)' "$main") || fail "Herdr main session unavailable: $main_identity"
  if [ -n "${CLAUDE_CODE_SESSION_ID:-}" ] && [ "$main_session" != "$CLAUDE_CODE_SESSION_ID" ]; then
    if session_continued_into "$main_session" "$CLAUDE_CODE_SESSION_ID"; then
      main_session="$CLAUDE_CODE_SESSION_ID"
    else
      fail "Herdr main pane belongs to another session"
    fi
  fi
  tab=""
  [ "$HARNESS" != pi ] || prepare_pi_worktree
  created=$(herdr tab create --workspace "$ws" --cwd "$CWD" --label "$LABEL" --no-focus ${TAB_ENV_ARGS[@]+"${TAB_ENV_ARGS[@]}"} 2>&1) || fail "$created"
  created_info=$(printf '%s' "$created" | python3 -c 'import json,sys; d=json.load(sys.stdin); r=d.get("result",{}); print(r["root_pane"]["pane_id"] + "\t" + r["tab"]["tab_id"])') || fail "invalid Herdr tab create response: $created"
  IFS=$'\t' read -r pane tab <<< "$created_info"
  [ -n "$pane" ] && [ -n "$tab" ] || fail "Herdr tab create returned no target"
  [ "${#UNSET_NAMES[@]}" -eq 0 ] || confirm_pane_unset "$pane" "$tab"
  started=$(herdr agent start "$NAME" --kind "$KIND" --pane "$pane" -- ${START_ARGS[@]+"${START_ARGS[@]}"} 2>&1)
  if [ "$?" -ne 0 ]; then
    first_error="$started"
    if printf '%s' "$first_error" | command grep -Eq 'agent_pane_busy|not an available shell'; then
      herdr pane process-info --pane "$pane" >/dev/null 2>&1 || { cleanup_herdr_tab "$tab"; fail "Herdr pane was not ready: $first_error"; }
      started=$(herdr agent start "$NAME" --kind "$KIND" --pane "$pane" -- ${START_ARGS[@]+"${START_ARGS[@]}"} 2>&1) || { cleanup_herdr_tab "$tab"; fail "Herdr agent start failed after pane check: $started"; }
    else
      cleanup_herdr_tab "$tab"
      fail "$first_error"
    fi
  fi
  [ -z "$started" ] || check_json_ok "$started" || { cleanup_herdr_tab "$tab"; fail "Herdr agent start returned ok:false: $started"; }
  session=""
  if [ "$HARNESS" != codex ]; then
    session=$(lookup_session)
    case "$?" in
      0) ;;
      2) cleanup_herdr_tab "$tab"; fail "$session" ;;
      *) cleanup_herdr_tab "$tab"; fail "Herdr agent list returned no session for $NAME" ;;
    esac
  fi
  if [ "$HARNESS" = pi ]; then
    # pi 的 agent_session 是紀錄檔路徑；結尾不是本次 uuid 就不是我們剛起的 session。
    case "$session" in
      *_"$PI_UUID".jsonl) session="$PI_UUID" ;;
      *) cleanup_herdr_tab "$tab"; fail "Herdr agent list returned no session for $NAME matching pi session $PI_UUID: $session" ;;
    esac
  fi
  prompt="[main] Read $BRIEF and follow it. Ask your questions in plain text and stop; do not assume answers."
  started=$(herdr agent prompt "$NAME" "$prompt" --wait --until working 2>&1) || { cleanup_herdr_tab "$tab"; fail "prompt failed: $started"; }
  [ -z "$started" ] || check_json_ok "$started" || { cleanup_herdr_tab "$tab"; fail "Herdr prompt returned ok:false: $started"; }
  if [ "$HARNESS" = codex ]; then
    session=$(poll_session) || { cleanup_herdr_tab "$tab"; fail "Herdr agent list returned no session for $NAME after prompt"; }
  fi
  log="$LOGDIR/$NAME.log"
  if [ "$WATCH" -eq 1 ]; then
    nohup bash "$HERE/agent-watch.sh" herdr "$NAME" "$main" "$log" "$session" "$CWD" "$main_session" "$pane" >/dev/null 2>&1 &
    disown
  fi
  python3 -c 'import json,sys; print(json.dumps({"backend":sys.argv[1],"parent_backend":sys.argv[1],"worker_backend":sys.argv[1],"name":sys.argv[2],"worker_id":sys.argv[3],"parent_id":sys.argv[4],"parent_session_id":sys.argv[9],"pane_id":sys.argv[3],"tab_id":sys.argv[5],"session_id":sys.argv[6],"log":sys.argv[7],"cwd":sys.argv[8],"harness":sys.argv[10],"recipe":json.loads(sys.argv[13]) if sys.argv[13] else {"model":sys.argv[11],"effort":sys.argv[12]}}))' "$BACKEND" "$NAME" "$pane" "$main" "$tab" "$session" "$log" "$CWD" "$main_session" "$HARNESS" "$MODEL" "$EFFORT" "$RECIPE"
}

cleanup_hc_worker() {
  local pane="${1:-}" tab="${2:-}"
  if [ -n "$tab" ] && [ "$tab" != "$pane" ]; then
    "$HERDR_APP_BIN" do tab.close --id "$tab" --confirmed true >/dev/null 2>&1 || true
  fi
  if [ -n "$pane" ]; then
    "$HC_BIN" kill "$pane" >/dev/null 2>&1 || true
    "$HC_BIN" rm "$pane" >/dev/null 2>&1 || true
  fi
}

build_hc_env_cmd() {
  python3 -c '
import shlex, sys
unsets = []
exports = []
i = 1
while i < len(sys.argv):
  tag = sys.argv[i]
  if tag == "-u":
    unsets.append(sys.argv[i + 1])
    i += 2
  elif tag == "--env":
    k, v = sys.argv[i + 1].split("=", 1)
    exports.append(f"{k}={shlex.quote(v)}")
    i += 2
  else:
    i += 1
parts = []
if unsets:
  parts.append("unset " + " ".join(unsets))
if exports:
  parts.append("export " + " ".join(exports))
print("; ".join(parts))
' "$@"
}

start_herdr_core() {
  local main main_session space app_status created created_info pane tab cc_uuid env_args env_cmd launch_cmd out prompt log session u e
  main="$HC_TERMINAL_ID"
  main_session="${CLAUDE_CODE_SESSION_ID:-hc:$HC_TERMINAL_ID}"
  [ "$HARNESS" != pi ] || prepare_pi_worktree
  session=""
  if [ "$HARNESS" = claude ]; then
    cc_uuid=$(python3 -c 'import uuid; print(uuid.uuid4())') || fail "could not generate a claude session id"
    START_ARGS+=(--session-id "$cc_uuid")
    session="$cc_uuid"
  elif [ "$HARNESS" = pi ]; then
    session="$PI_UUID"
  fi
  pane=""
  tab=""
  space=""
  if app_status=$("$HERDR_APP_BIN" status 2>/dev/null); then
    space=$(printf '%s' "$app_status" | python3 -c 'import json,sys; d=json.load(sys.stdin); s=d.get("space") if isinstance(d,dict) else ""; print(s if isinstance(s,str) and s else "")' 2>/dev/null) || space=""
  fi
  if [ -n "$space" ]; then
    if created=$("$HERDR_APP_BIN" do tab.new --space "$space" --name "$LABEL" --folder "$CWD" 2>/dev/null); then
      created_info=$(printf '%s' "$created" | python3 -c 'import json,sys; d=json.load(sys.stdin); t=d.get("terminal",""); b=d.get("tab",""); print(t + "\t" + b) if isinstance(d,dict) and t and b and not d.get("error") else sys.exit(1)' 2>/dev/null) || created_info=""
      if [ -n "$created_info" ]; then
        IFS=$'\t' read -r pane tab <<< "$created_info"
        "$HC_BIN" label "$pane" "name=$NAME" >/dev/null 2>&1 || true
      fi
    fi
  fi
  if [ -z "$pane" ]; then
    created=$("$HC_BIN" run --bg --name "$NAME" --cwd "$CWD" 2>&1) || fail "$created"
    pane=$(printf '%s' "$created" | python3 -c 'import json,re,sys; s=sys.stdin.read().strip()
try:
  d=json.loads(s); a=d.get("address","") if isinstance(d,dict) else ""
except Exception:
  m=re.search(r"(?:still running as |^)(t[0-9a-zA-Z_-]+)", s); a=m.group(1) if m else ""
print(a) if a else sys.exit(1)' 2>/dev/null) || fail "invalid hc run response: $created"
    tab="$pane"
  fi
  env_args=()
  for u in ${UNSET_NAMES[@]+"${UNSET_NAMES[@]}"}; do
    env_args+=(-u "$u")
  done
  for e in ${TAB_ENV_ARGS[@]+"${TAB_ENV_ARGS[@]}"}; do
    env_args+=("$e")
  done
  if [ "${#env_args[@]}" -gt 0 ]; then
    env_cmd=$(build_hc_env_cmd "${env_args[@]}")
    if [ -n "$env_cmd" ]; then
      out=$("$HC_BIN" send "$pane" "$env_cmd" 2>&1) || { cleanup_hc_worker "$pane" "$tab"; fail "hc send env failed: $out"; }
    fi
  fi
  launch_cmd=$(python3 -c 'import shlex,sys; print(" ".join(shlex.quote(a) for a in sys.argv[1:]))' "$KIND" ${START_ARGS[@]+"${START_ARGS[@]}"})
  out=$("$HC_BIN" send "$pane" "$launch_cmd" 2>&1) || { cleanup_hc_worker "$pane" "$tab"; fail "hc send launch failed: $out"; }
  out=$("$HC_BIN" wait "$pane" 2>&1) || { cleanup_hc_worker "$pane" "$tab"; fail "hc wait ready failed: $out"; }
  prompt="[main] Read $BRIEF and follow it. Ask your questions in plain text and stop; do not assume answers."
  out=$("$HC_BIN" send "$pane" "$prompt" 2>&1) || { cleanup_hc_worker "$pane" "$tab"; fail "prompt failed: $out"; }
  if [ "$HARNESS" = codex ]; then
    session=$("$HC_BIN" get "$pane" 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); s=(d.get("session_id") or (d.get("labels") or {}).get("session_id") or "") if isinstance(d,dict) else ""; print(s)' 2>/dev/null) || session=""
    [ -n "$session" ] || session="hc-$pane"
  fi
  log="$LOGDIR/$NAME.log"
  if [ "$WATCH" -eq 1 ]; then
    nohup bash "$HERE/agent-watch.sh" herdr-core "$NAME" "$HC_TERMINAL_ID" "$log" "$session" "$CWD" "$main_session" "$pane" >/dev/null 2>&1 &
    disown
  fi
  python3 -c 'import json,sys; print(json.dumps({"backend":sys.argv[1],"parent_backend":sys.argv[1],"worker_backend":sys.argv[1],"name":sys.argv[2],"worker_id":sys.argv[3],"parent_id":sys.argv[4],"parent_session_id":sys.argv[9],"pane_id":sys.argv[3],"tab_id":sys.argv[5],"session_id":sys.argv[6],"log":sys.argv[7],"cwd":sys.argv[8],"harness":sys.argv[10],"recipe":json.loads(sys.argv[13]) if sys.argv[13] else {"model":sys.argv[11],"effort":sys.argv[12]}}))' "$BACKEND" "$NAME" "$pane" "$main" "$tab" "$session" "$log" "$CWD" "$main_session" "$HARNESS" "$MODEL" "$EFFORT" "$RECIPE"
}

if [ "$BACKEND" = herdr ]; then
  start_herdr
else
  start_herdr_core
fi
