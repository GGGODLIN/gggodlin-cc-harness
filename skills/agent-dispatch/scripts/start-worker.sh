#!/bin/bash
set -u
set -o pipefail
export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
HERE="$(cd "$(dirname "$0")" && pwd)"
fail() {
  printf '%s\n' "$*" >&2
  exit 2
}
[ "$#" -ge 3 ] || fail "usage: start-worker.sh <worker name> <worktree path> <brief file> [--harness claude|codex|pi] [--recipe JSON | --launcher NAME] [--label L] [--model M] [--effort E] [--agent NAME] [--inline-brief] [--log-dir D] [--no-watch]"
NAME="$1"
CWD="$2"
BRIEF="$3"
shift 3
LABEL="$NAME"
HARNESS="claude"
MODEL=""
MODEL_SET=0
EFFORT=""
RECIPE=""
RECIPE_SET=0
LAUNCHER=""
AGENT=""
AGENT_JSON=""
INLINE_BRIEF=0
PERMISSION_MODE=""
ALLOWED_TOOLS=()
ADD_DIRS=()
RESUME=""
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
      RECIPE_SET=1
      shift 2
      ;;
    --launcher)
      [ "$#" -ge 2 ] && [ -n "$2" ] || fail "missing value for --launcher"
      LAUNCHER="$2"
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
      MODEL_SET=1
      shift 2
      ;;
    --effort)
      [ "$#" -ge 2 ] || fail "missing value for --effort"
      EFFORT="$2"
      shift 2
      ;;
    --agent)
      [ "$#" -ge 2 ] || fail "missing value for --agent"
      AGENT="$2"
      shift 2
      ;;
    --log-dir)
      [ "$#" -ge 2 ] || fail "missing value for --log-dir"
      LOGDIR="$2"
      shift 2
      ;;
    --permission-mode)
      [ "$#" -ge 2 ] && [ -n "$2" ] || fail "missing value for --permission-mode"
      PERMISSION_MODE="$2"
      shift 2
      ;;
    --allow-tool)
      [ "$#" -ge 2 ] && [ -n "$2" ] || fail "missing value for --allow-tool"
      ALLOWED_TOOLS+=("$2")
      shift 2
      ;;
    --add-dir)
      [ "$#" -ge 2 ] && [[ "$2" = /* ]] && [ -d "$2" ] || fail "--add-dir requires an existing absolute directory"
      ADD_DIRS+=("$2")
      shift 2
      ;;
    --resume)
      [ "$#" -ge 2 ] && [ -n "$2" ] || fail "missing value for --resume"
      RESUME="$2"
      shift 2
      ;;
    --inline-brief)
      INLINE_BRIEF=1
      shift
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
reference_prompt() {
  printf '[main] Read %s and follow it. Ask your questions in plain text and stop; do not assume answers.' "$BRIEF"
}

# 終端只收啟動命令。雙引號內的 cat 輸出是單一位置參數，不會再被 shell 解析。
# inline 保留給不能用工具讀方法組的外殼。路徑與 flags 要先排除 PTY 控制字元，shell 引用不保護這一層。
build_launch_cmd() {
  python3 -I -c '
import shlex, sys
from pathlib import Path

inline, brief, reference, agent_json, *argv = sys.argv[1:]
if any(ord(c) < 32 or ord(c) == 127 for part in [brief, agent_json, *argv] for c in part):
  sys.exit("terminal launch path or option contains a control character")
if inline == "1":
  try:
    with Path(brief).open("rb") as stream:
      if argv[0] == "pi" and stream.read(1) == b"@":
        sys.exit("pi inline brief cannot begin with @ (pi interprets it as a file argument)")
  except OSError:
    sys.exit("could not open inline brief")
  prompt = f"\"$(cat {shlex.quote(brief)})\""
else:
  prompt = shlex.quote(reference)
quoted = [shlex.quote(a) for a in argv]
if agent_json:
  index = argv.index("--agent")
  quoted[index:index] = ["--agents", f"\"$(cat {shlex.quote(agent_json)})\""]
print(" ".join(quoted) + " -- " + prompt)
' "$INLINE_BRIEF" "$BRIEF" "$(reference_prompt)" "$AGENT_JSON" "${LAUNCHER:-$KIND}" ${START_ARGS[@]+"${START_ARGS[@]}"}
}

write_inline_agent() {
  python3 -I - "$HERE/../../../agents" "$AGENT" "$AGENT_JSON" <<'PY'
import json
import re
import sys
from pathlib import Path

root, agent, destination = sys.argv[1:]
if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", agent):
  sys.exit("invalid inline agent name")
path = Path(root).resolve() / f"{agent}.md"
try:
  text = path.read_text(encoding="utf-8")
except FileNotFoundError:
  sys.exit(f"agent definition not found: {path}")
except (OSError, UnicodeError):
  sys.exit(f"could not read agent definition: {path}")
try:
  import yaml
except ImportError:
  sys.exit("PyYAML is required to load inline agent frontmatter")
frontmatter = re.match(r"\A---\n(.*?)^---[ \t]*(?:\n|\Z)", text, re.DOTALL | re.MULTILINE)
try:
  metadata = yaml.safe_load(frontmatter[1]) if frontmatter else None
except yaml.YAMLError:
  sys.exit(f"invalid agent frontmatter: {path}")
description = metadata.get("description") if isinstance(metadata, dict) else None
if not isinstance(description, str) or not description.strip():
  sys.exit(f"agent definition lacks a non-empty frontmatter description: {path}")
prompt = text[frontmatter.end():]
if not prompt.strip():
  sys.exit(f"agent definition has an empty prompt body: {path}")
definition = {"description": description, "prompt": prompt}
if "model" in metadata:
  if not isinstance(metadata["model"], str) or not metadata["model"].strip():
    sys.exit(f"agent definition has an invalid model: {path}")
  definition["model"] = metadata["model"]
Path(destination).write_text(json.dumps({agent: definition}), encoding="utf-8")
PY
}
# 每個外殼決定 Herdr kind、必填配方與傳給 canonical 執行檔的參數；
# 新外殼在這裡加一個分支，start_herdr 之後不必再動。
KIND=""
START_ARGS=()
TAB_ENV_ARGS=()
PI_UUID=""
PI_PICK="${PI_PICK_BIN:-pi-pick}"
CC_PICK="${CC_PICK_BIN:-cc-pick}"
UNSET_NAMES=()
if [ -n "$LAUNCHER" ]; then
  [ "$HARNESS" = claude ] || fail "--launcher is only supported for --harness claude"
  [ "$RECIPE_SET" -eq 0 ] || fail "--launcher cannot be combined with --recipe"
  [ "$MODEL_SET" -eq 0 ] || fail "--launcher cannot be combined with --model"
fi
[ -z "$RECIPE" ] || [ "$HARNESS" = pi ] || [ "$HARNESS" = claude ] || fail "--recipe is not supported for --harness $HARNESS"
[ -z "$AGENT" ] || [ "$HARNESS" = claude ] || fail "--agent is only supported for --harness claude"
[ "${#ALLOWED_TOOLS[@]}" -eq 0 ] || [ "$PERMISSION_MODE" = tool-allowlist ] || fail "--allow-tool requires tool-allowlist mode"
[ "${#ADD_DIRS[@]}" -eq 0 ] || [ "$PERMISSION_MODE" = tool-allowlist ] || fail "--add-dir requires tool-allowlist mode"
if [ -n "$PERMISSION_MODE" ]; then
  python3 "$HERE/seat_permissions.py" "$HARNESS" "$PERMISSION_MODE" ${ALLOWED_TOOLS[@]+"${ALLOWED_TOOLS[@]}"} >/dev/null || fail "invalid seat permissions"
fi
if [ -n "$RESUME" ]; then
  [ "$HARNESS" = codex ] && [ "$PERMISSION_MODE" = codex-read-only ] || fail "--resume is only supported for read-only Codex seats"
  [[ "$RESUME" =~ ^[A-Za-z0-9_-]+$ ]] || fail "invalid resume session id"
fi

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
  # 沒帶 --approve 時，有 .pi/settings.json 的 worktree 會卡在信任對話框，首則訊息無法開始。
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
    if [ -n "$LAUNCHER" ]; then
      [ -z "$AGENT" ] || START_ARGS+=(--agent "$AGENT")
      [ -z "$EFFORT" ] || START_ARGS+=(--effort "$EFFORT")
      # The selected launcher must own its model slots even when the parent shell had another mapping.
      UNSET_NAMES+=(ANTHROPIC_MODEL ANTHROPIC_DEFAULT_FABLE_MODEL ANTHROPIC_DEFAULT_OPUS_MODEL
                    ANTHROPIC_DEFAULT_SONNET_MODEL ANTHROPIC_DEFAULT_HAIKU_MODEL CLAUDE_CODE_SUBAGENT_MODEL)
    elif [ -n "$RECIPE" ]; then
      [ -n "$AGENT" ] || { [ -z "$MODEL" ] && [ -z "$EFFORT" ]; } || fail "--model/--effort do not apply with --recipe for --harness claude without --agent; pass --agent to override --model/--effort, or omit them to use the --recipe model slots"
      command -v "$CC_PICK" >/dev/null 2>&1 || fail "cc-pick not found ($CC_PICK); cannot validate the claude recipe"
      prepare_claude_launch
      if [ -n "$AGENT" ]; then
        # 定義檔的 model:／effort: 會蓋掉配方的 ANTHROPIC_MODEL，不釘回去 worker 會靠定義檔靜默換模型。
        agent_model="$MODEL"
        if [ -z "$agent_model" ]; then
          for e in ${TAB_ENV_ARGS[@]+"${TAB_ENV_ARGS[@]}"}; do
            case "$e" in ANTHROPIC_MODEL=*) agent_model="${e#ANTHROPIC_MODEL=}" ;; esac
          done
        fi
        [ -n "$agent_model" ] || fail "--agent with --recipe needs a model: the recipe sets no ANTHROPIC_MODEL, so pass --model"
        START_ARGS+=(--agent "$AGENT" --model "$agent_model")
        [ -z "$EFFORT" ] || START_ARGS+=(--effort "$EFFORT")
        MODEL=""
        EFFORT=""
      fi
    else
      MODEL="${MODEL:-opus[1m]}"
      EFFORT="${EFFORT:-high}"
      START_ARGS=(--model "$MODEL" --effort "$EFFORT")
      [ -z "$AGENT" ] || START_ARGS+=(--agent "$AGENT")
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
    if [ "$PERMISSION_MODE" = codex-read-only ]; then
      START_ARGS=(-m "$MODEL" -c "model_reasoning_effort=$EFFORT" -c check_for_update_on_startup=false -s read-only -a never)
      [ -z "$RESUME" ] || START_ARGS=(resume "$RESUME" "${START_ARGS[@]}")
    else
      START_ARGS=(-m "$MODEL" -c "model_reasoning_effort=$EFFORT" -c check_for_update_on_startup=false --dangerously-bypass-approvals-and-sandbox)
    fi
    [ -z "${CODEX_HOME:-}" ] || TAB_ENV_ARGS+=(--env "CODEX_HOME=$CODEX_HOME")
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
if [ -n "$PERMISSION_MODE" ]; then
  while IFS= read -r -d '' permission_arg; do
    START_ARGS+=("$permission_arg")
  done < <(python3 "$HERE/seat_permissions.py" "$HARNESS" "$PERMISSION_MODE" ${ALLOWED_TOOLS[@]+"${ALLOWED_TOOLS[@]}"})
fi
for directory in ${ADD_DIRS[@]+"${ADD_DIRS[@]}"}; do
  START_ARGS+=(--add-dir "$directory")
done
[ -d "$CWD" ] || fail "worktree not found: $CWD"
[ -f "$BRIEF" ] || fail "brief not found: $BRIEF"
case "$BRIEF" in /*) ;; *) BRIEF="$PWD/$BRIEF" ;; esac
CWD="$(cd -- "$CWD" && pwd -P)"
LOGDIR="${LOGDIR:-$(dirname "$BRIEF")/watch-logs}"
mkdir -p -- "$LOGDIR" || fail "could not create log directory: $LOGDIR"
LOGDIR="$(cd -- "$LOGDIR" && pwd -P)"

# 不載入 settings 的受限席要自己提供 agent 定義。檔案保留到首回合已啟動，避免 PTY 接觸定義原文。
if [ "$HARNESS" = claude ] && [ -n "$AGENT" ] && [[ "$PERMISSION_MODE" = zero-tools || "$PERMISSION_MODE" = tool-allowlist ]]; then
  AGENT_JSON=$(mktemp "$LOGDIR/inline-agent.XXXXXX") || fail "could not create inline agent file"
  trap 'rm -f -- "$AGENT_JSON"' EXIT INT TERM
  write_inline_agent || fail "could not prepare inline agent definition"
fi

HC_BIN="${HC_BIN:-hc}"

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

if [ "$BACKEND" = herdr-core ]; then
  python3 -c 'import re,sys; n=sys.argv[1]; sys.exit(0 if re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,31}", n) and not re.fullmatch(r"t[0-9a-z]+", n) else 1)' "$NAME" || fail "invalid Herdr Core name: use 1-32 of a-z 0-9 - _ . starting with a letter or digit, not shaped like an id (t7)"
fi

if [ -n "$LAUNCHER" ]; then
  [ "$BACKEND" = herdr-core ] || fail "launcher requires Herdr App/Core; shell-function launch on legacy Herdr is not verified"
  # Herdr App/Core 打開的是互動 login zsh；launcher 可以是 .zshrc 載入的函式，不一定在 PATH。
  zsh -lic 'whence -w -- "$1"' start-worker "$LAUNCHER" >/dev/null 2>&1 || fail "launcher not found in interactive login zsh: $LAUNCHER"
fi

check_json_ok() {
  printf '%s' "$1" | python3 -I -c '
import json, sys

try:
  result = json.load(sys.stdin)
except json.JSONDecodeError:
  sys.exit(1)
sys.exit(0 if isinstance(result, dict) and result.get("ok") is not False and result.get("error") is None else 1)
'
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

fail_legacy_worker() {
  local tab="$1" reason="$2" out rc=0
  out=$(herdr tab close "$tab" 2>&1) || rc=$?
  if [ "$rc" -ne 0 ] || ! check_json_ok "$out"; then
    fail "$reason; terminal close failed for $tab (tab close rc=$rc: ${out:-no diagnostic}); watcher not armed"
  fi
  fail "$reason; tab closed, watcher not armed"
}

# agent start 會等到互動 idle；已有首則訊息的 agent 可能早已 working，應從新 pane 讀回它的身分。
poll_legacy_session() {
  local pane="$1" i agents session
  local max="${START_WORKER_SESSION_POLLS:-30}" interval="${START_WORKER_SESSION_POLL_INTERVAL:-1}"
  for ((i = 0; i < max; i++)); do
    if agents=$(herdr agent list 2>/dev/null); then
      session=$(printf '%s' "$agents" | python3 -I -c '
import json, sys
pane, kind, pi_id, resume = sys.argv[1:]
for agent in json.load(sys.stdin).get("result", {}).get("agents", []):
  if agent.get("pane_id") != pane or agent.get("agent") != kind:
    continue
  completion = agent.get("completion_seq")
  if agent.get("agent_status") != "working" and not (type(completion) is int and completion > 0):
    continue
  session = (agent.get("agent_session") or {}).get("value")
  if not isinstance(session, str) or not session:
    continue
  if kind == "pi" and not session.endswith(f"_{pi_id}.jsonl"):
    continue
  if resume and session != resume:
    continue
  print(pi_id if kind == "pi" else session)
  sys.exit(0)
sys.exit(1)
' "$pane" "$KIND" "$PI_UUID" "$RESUME" 2>/dev/null) && { printf '%s' "$session"; return 0; }
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

# 新 tab 初始化時 pane run 可能被靜默丟掉。只重送無副作用的 readiness 探針與 unset。
confirm_legacy_shell() {
  local pane tab cmd out i max
  pane="$1"
  tab="$2"
  max=5
  cmd="printf 'AGENT_DISPATCH_SHELL%s\\n' _READY"
  [ "${#UNSET_NAMES[@]}" -eq 0 ] || cmd="unset ${UNSET_NAMES[*]} && $cmd"
  for ((i = 0; i < max; i++)); do
    out=$(herdr pane run "$pane" "$cmd" 2>&1) || fail_legacy_worker "$tab" "Herdr shell readiness probe failed: $out"
    check_json_ok "$out" || fail_legacy_worker "$tab" "Herdr shell readiness probe returned ok:false: $out"
    herdr pane wait-output "$pane" --match AGENT_DISPATCH_SHELL_READY --timeout 3000 >/dev/null 2>&1 && return 0
  done
  fail_legacy_worker "$tab" "Herdr shell readiness and recipe unset were not confirmed after $max attempts in pane $pane"
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
  local main main_identity main_session ws created created_info pane tab started session launch_cmd log
  [[ "$NAME" =~ ^[a-z][a-z0-9_-]{0,31}$ ]] || fail "invalid legacy Herdr agent name"
  launch_cmd=$(build_launch_cmd) || fail "could not build worker launch command"
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
  confirm_legacy_shell "$pane" "$tab"
  started=$(herdr pane run "$pane" "$launch_cmd" 2>&1) || fail_legacy_worker "$tab" "Herdr launch failed: $started"
  check_json_ok "$started" || fail_legacy_worker "$tab" "Herdr launch returned ok:false: $started"
  session=$(poll_legacy_session "$pane") || fail_legacy_worker "$tab" "Herdr found no session with first-turn activity for $NAME"
  started=$(herdr agent rename "$pane" "$NAME" 2>&1) || fail_legacy_worker "$tab" "Herdr agent rename failed: $started"
  check_json_ok "$started" || fail_legacy_worker "$tab" "Herdr agent rename returned ok:false: $started"
  log="$LOGDIR/$NAME.log"
  if [ "$WATCH" -eq 1 ]; then
    nohup bash "$HERE/agent-watch.sh" herdr "$NAME" "$main" "$log" "$session" "$CWD" "$main_session" "$pane" >/dev/null 2>&1 &
    disown
  fi
  python3 -c 'import json,sys; print(json.dumps({"backend":sys.argv[1],"parent_backend":sys.argv[1],"worker_backend":sys.argv[1],"name":sys.argv[2],"worker_id":sys.argv[3],"parent_id":sys.argv[4],"parent_session_id":sys.argv[9],"pane_id":sys.argv[3],"tab_id":sys.argv[5],"session_id":sys.argv[6],"log":sys.argv[7],"cwd":sys.argv[8],"harness":sys.argv[10],"launch_args":sys.argv[16:],"recipe":json.loads(sys.argv[13]) if sys.argv[13] else {"model":sys.argv[11],"effort":sys.argv[12]},**({"agent":sys.argv[14]} if sys.argv[14] else {})}))' "$BACKEND" "$NAME" "$pane" "$main" "$tab" "$session" "$log" "$CWD" "$main_session" "$HARNESS" "$MODEL" "$EFFORT" "$RECIPE" "$AGENT" "$LAUNCHER" ${START_ARGS[@]+"${START_ARGS[@]}"}
}

fail_hc_worker() {
  local pane="$1" reason="$2" action out rc errors="" still_live=""
  for action in kill rm; do
    rc=0
    out=$("$HC_BIN" "$action" "$pane" 2>&1) || rc=$?
    if [ "$rc" -ne 0 ] || ! check_json_ok "$out"; then
      errors="$errors $action rc=$rc: ${out:-no diagnostic}."
    fi
  done
  if [ -z "$errors" ]; then
    still_live=$("$HC_BIN" get "$pane" 2>/dev/null | python3 -I -c '
import json, sys

try:
  d = json.load(sys.stdin)
except Exception:
  sys.exit(0)
if (
  isinstance(d, dict)
  and d.get("error") is None
  and d.get("ok") is not False
  and d.get("state") not in (None, "finished", "exited", "removed", "closed")
):
  print("terminal still live")
' 2>/dev/null) || still_live=""
    if [ -n "$still_live" ]; then
      errors=" get: $still_live."
    fi
  fi
  if [ -n "$errors" ]; then
    fail "$reason; terminal close failed for $pane:$errors watcher not armed"
  fi
  fail "$reason; terminal closed, watcher not armed"
}

build_hc_env_cmd() {
  python3 -I -c '
import re, shlex, sys

args = sys.argv[1:]
if any(ord(c) < 32 or ord(c) == 127 for arg in args for c in arg):
  sys.exit("terminal environment contains a control character")
unsets = []
exports = []
for tag, item in zip(args[::2], args[1::2]):
  name, separator, value = item.partition("=")
  if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
    sys.exit("invalid terminal environment name")
  if tag == "-u" and not separator:
    unsets.append(name)
  elif tag == "--env" and separator:
    exports.append(f"{name}={shlex.quote(value)}")
  else:
    sys.exit("invalid terminal environment argument")
parts = []
if unsets:
  parts.append("unset " + " ".join(unsets))
if exports:
  parts.append("export " + " ".join(exports))
print("; ".join(parts))
' "$@"
}

# 快回完時用已完成回合數辨識；status 與前景 process name 是不同的訊號。
poll_hc_prompt_start() {
  local pane="$1" initial_turn="$2" i out progress ready=0
  local max="${START_WORKER_PROMPT_POLLS:-21}" interval="${START_WORKER_PROMPT_POLL_INTERVAL:-1}"
  for ((i = 0; i < max; i++)); do
    if out=$("$HC_BIN" get "$pane" 2>/dev/null); then
      progress=$(printf '%s' "$out" | python3 -I -c '
import json, sys

d = json.load(sys.stdin)
if not isinstance(d, dict) or d.get("error") or d.get("ok") is False:
  sys.exit(1)
status = d.get("status")
if isinstance(status, dict):
  status = status.get("state")
if not isinstance(status, str):
  status = d.get("state")
turn = d.get("turn")
if status == "working" or (type(turn) is int and turn > int(sys.argv[1])):
  print("started")
elif status in ("idle", "done", "blocked"):
  print("ready")
' "$initial_turn" 2>/dev/null) || progress=""
      case "$progress" in
        started) return 0 ;;
        ready) ready=1 ;;
      esac
    fi
    [ "$i" -lt $((max - 1)) ] && sleep "$interval"
  done
  if [ "$HARNESS" = claude ] && [ "$ready" -eq 0 ]; then
    printf '%s' "Claude never reported ready; first turn did not start"
  else
    printf '%s' "first turn did not start (worker reported ready without progress or no turn was observed)"
  fi
  return 1
}

detect_hc_claude_trust_dialog() {
  printf '%s' "$1" | python3 -I -c '
import sys

YES = ("Yes, I trust this folder", "Yes, add it")
HEADERS = ("Accessing workspace:", "Quick safety check:", "Adding a new directory:")
# hc read 連歷史一起印，已代按過的確認框還留在上方；只看畫面底部最後一個確認框，才不會對已啟動的 TUI 重按。
bottom = "\n".join([line for line in sys.stdin.read().splitlines() if line.strip()][-25:])
start = max(bottom.rfind(header) for header in HEADERS)
if start < 0:
  sys.exit(0)
dialog = bottom[start:]
if not any(label in dialog for label in YES):
  sys.exit(0)
for line in dialog.splitlines():
  stripped = line.lstrip()
  if stripped.startswith(("❯", ">")):
    if any(label in stripped for label in YES):
      print("enter")
      sys.exit(0)
    if "No, exit" in stripped:
      print("down_enter")
      sys.exit(0)
print("down_enter")
' 2>/dev/null
}

# Codex 的 Core status 可為 null。新席只看新增的 rollout，續席只看這次附加的回合事件。
poll_codex_seat_session() {
  python3 -I - "$1" "$CWD" "$RESUME" "$INLINE_BRIEF" "$BRIEF" "$(reference_prompt)" <<'PY'
import json, math, os, re, sys, time
from pathlib import Path

before = json.loads(sys.argv[1])
cwd, resume, inline, brief, reference = sys.argv[2:]
try:
  # Quoted shell command substitution strips trailing LFs and leaves other characters intact.
  expected = Path(brief).read_bytes().rstrip(b"\n").decode("utf-8") if inline == "1" else reference
except (OSError, UnicodeError):
  sys.exit("could not read expected Codex prompt")
root = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "sessions"
try:
  polls = int(os.environ.get("START_WORKER_SESSION_POLLS", "30"))
  interval = float(os.environ.get("START_WORKER_SESSION_POLL_INTERVAL", "1"))
  if not 1 <= polls <= 30 or not math.isfinite(interval) or not 0 <= interval <= 1:
    raise ValueError
except ValueError:
  sys.exit("Codex seat polling requires 1-30 checks and an interval of 0-1 seconds")
def text_blocks(content, kind):
  if isinstance(content, list) and content and all(
      isinstance(block, dict) and block.get("type") == kind and isinstance(block.get("text"), str)
      for block in content):
    return "".join(block["text"] for block in content)
  return False


# 最多 30 次、間隔 1 秒，讓首則訊息後的非同步 rollout 落盤有時間完成；超時不猜身分。
for attempt in range(polls):
  matches = []
  for path in root.glob("**/rollout-*.jsonl"):
    offset = before.get(str(path))
    if (resume and offset is None) or (not resume and offset is not None):
      continue
    try:
      with path.open("rb") as stream:
        row = json.loads(stream.readline())
        meta = row.get("payload") if isinstance(row, dict) and row.get("type") == "session_meta" else None
        if not isinstance(meta, dict) or meta.get("cwd") != cwd:
          continue
        sid = meta.get("id")
        if not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", sid) or (resume and sid != resume):
          continue
        if offset is not None:
          stream.seek(offset)
        started = False
        first_user = None
        for line in stream:
          try:
            row = json.loads(line)
          except ValueError:
            if not line.endswith(b"\n"):
              break
            raise
          if not isinstance(row, dict) or not isinstance(payload := row.get("payload"), dict):
            continue
          if row.get("type") == "event_msg":
            kind = payload.get("type")
            if kind == "task_started" and started:
              break
            if kind in ("task_started", "task_complete"):
              started = True
            if kind == "user_message":
              first_user = payload.get("message", False)
              break
            item = payload.get("item")
            if kind == "item_completed" and isinstance(item, dict) and item.get("type") == "UserMessage":
              first_user = text_blocks(item.get("content"), "text")
              break
        # Only Codex's own user-input event counts. Raw response_item messages mix startup
        # context with user input, and guessing which is which let another seat's rollout
        # bind to this launch; a rollout without the event fails closed instead.
        if started and first_user == expected:
          matches.append(sid)
    except (OSError, UnicodeError, ValueError):
      continue
  if len(matches) == 1:
    print(matches[0])
    sys.exit(0)
  if len(matches) > 1:
    sys.exit("ambiguous Codex rollouts: multiple sessions match this launch prompt and cwd")
  if attempt + 1 < polls:
    time.sleep(interval)
sys.exit("no new Codex rollout turn matching this launch after bounded polling")
PY
}

start_herdr_core() {
  local main main_session created pane tab cc_uuid launch_cmd out log session initial_turn codex_before
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
  else
    codex_before=$(python3 -I -c '
import json, os, sys
from pathlib import Path

root = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "sessions"
resume = sys.argv[1]
pattern = f"**/rollout-*-{resume}.jsonl" if resume else "**/rollout-*.jsonl"
print(json.dumps({str(p): p.stat().st_size if resume else 0 for p in root.glob(pattern)}))
' "$RESUME") || fail "could not snapshot Codex rollouts before launch"
  fi
  launch_cmd=$(build_launch_cmd) || fail "could not build worker launch command"
  # --parent 讓 Herdr App 把 worker 列在 main 的 sub_agents 底下；刻意不加 --outlive-parent，
  # 關掉 main 的 terminal 時 worker 跟著結束。--no-notify 是因為喚醒交給 agent-watch.sh，
  # 兩邊都開 main 會被叫兩次。
  created=$("$HC_BIN" run --bg --name "$NAME" --cwd "$CWD" --parent "$main" --no-notify 2>&1) || fail "$created"
  pane=$(printf '%s' "$created" | python3 -c 'import json,re,sys; s=sys.stdin.read().strip()
try:
  d=json.loads(s); a=d.get("address","") if isinstance(d,dict) else ""
except Exception:
  m=re.search(r"(?:still running as |^)(t[0-9a-zA-Z_-]+)", s); a=m.group(1) if m else ""
print(a) if a else sys.exit(1)' 2>/dev/null) || fail "invalid hc run response: $created"
  tab="$pane"
  if [ -n "$env_cmd" ]; then
    out=$("$HC_BIN" send "$pane" "$env_cmd" 2>&1) || fail_hc_worker "$pane" "hc send env failed: $out"
  fi
  if [ "$HARNESS" != codex ]; then
    initial_turn=$("$HC_BIN" get "$pane" 2>/dev/null | python3 -I -c '
import json, sys

d = json.load(sys.stdin)
if not isinstance(d, dict) or d.get("error") or d.get("ok") is False:
  sys.exit(1)
t = d.get("turn", 0)
print(t) if type(t) is int and t >= 0 else sys.exit(1)
' 2>/dev/null) || fail_hc_worker "$pane" "hc get returned no valid initial turn"
  fi
  out=$("$HC_BIN" send "$pane" "$launch_cmd" 2>&1) || fail_hc_worker "$pane" "hc send launch failed: $out"
  if [ "$HARNESS" = codex ]; then
    session=$(poll_codex_seat_session "$codex_before" 2>&1) || fail_hc_worker "$pane" "$session"
  elif ! out=$(poll_hc_prompt_start "$pane" "$initial_turn"); then
    # 畫面可能顯示 export 出來的憑證值，只讓固定的診斷句離開這條管線，不照抄畫面。
    local screen="" trust_action="" accepted=0 polled=0
    # 工作目錄一個確認框，每個 --add-dir 再各跳一個「Yes, add it」；只代按第一個時，多目標審查席會卡在第二個。
    local max_trust=$(( ${#ADD_DIRS[@]} + 1 ))
    while :; do
      screen="" trust_action=""
      if [ "$HARNESS" = claude ] || [ -n "$LAUNCHER" ]; then
        screen=$("$HC_BIN" read "$pane" 2>/dev/null) || screen=""
      fi
      if [ "$HARNESS" = claude ] && [ -n "$screen" ]; then
        trust_action=$(detect_hc_claude_trust_dialog "$screen") || trust_action=""
      fi
      if [ -n "$trust_action" ]; then
        [ "$accepted" -lt "$max_trust" ] || fail_hc_worker "$pane" "$out; folder trust dialog remained active after auto-accept"
        if [ "$trust_action" = "down_enter" ]; then
          "$HC_BIN" keys "$pane" down >/dev/null 2>&1 || true
        fi
        "$HC_BIN" keys "$pane" enter >/dev/null 2>&1 || true
        accepted=$((accepted + 1)) polled=0
        # 下一個確認框在按下後才畫出來；先等它出現再讀，連續的確認框就不必各等一輪完整首輪輪詢。
        sleep "${START_WORKER_TRUST_SETTLE:-2}"
        continue
      fi
      if [ "$accepted" -gt 0 ] && [ "$polled" -eq 0 ]; then
        polled=1
        out=$(poll_hc_prompt_start "$pane" "$initial_turn") && break
        continue
      fi
      [ "$accepted" -eq 0 ] || fail_hc_worker "$pane" "$out; folder trust dialog remained active after auto-accept"
      if [ -n "$LAUNCHER" ] && printf '%s' "$screen" | command grep -F 'not listening' >/dev/null; then
        out="$out; launcher reported its relay is not listening"
      fi
      fail_hc_worker "$pane" "$out"
    done
  fi
  log="$LOGDIR/$NAME.log"
  if [ "$WATCH" -eq 1 ]; then
    nohup bash "$HERE/agent-watch.sh" herdr-core "$NAME" "$HC_TERMINAL_ID" "$log" "$session" "$CWD" "$main_session" "$pane" >/dev/null 2>&1 &
    disown
  fi
  python3 -c 'import json,sys; print(json.dumps({"backend":sys.argv[1],"parent_backend":sys.argv[1],"worker_backend":sys.argv[1],"name":sys.argv[2],"worker_id":sys.argv[3],"parent_id":sys.argv[4],"parent_session_id":sys.argv[9],"pane_id":sys.argv[3],"tab_id":sys.argv[5],"session_id":sys.argv[6],"log":sys.argv[7],"cwd":sys.argv[8],"harness":sys.argv[10],"launch_args":sys.argv[16:],"recipe":json.loads(sys.argv[13]) if sys.argv[13] else {"model":sys.argv[11],"effort":sys.argv[12]},**({"agent":sys.argv[14]} if sys.argv[14] else {}),**({"launcher":sys.argv[15],"launch_args":sys.argv[16:],"recipe":None} if sys.argv[15] else {})}))' "$BACKEND" "$NAME" "$pane" "$main" "$tab" "$session" "$log" "$CWD" "$main_session" "$HARNESS" "$MODEL" "$EFFORT" "$RECIPE" "$AGENT" "$LAUNCHER" ${START_ARGS[@]+"${START_ARGS[@]}"}
}

env_args=()
for name in ${UNSET_NAMES[@]+"${UNSET_NAMES[@]}"}; do
  env_args+=(-u "$name")
done
env_cmd=$(build_hc_env_cmd ${env_args[@]+"${env_args[@]}"} ${TAB_ENV_ARGS[@]+"${TAB_ENV_ARGS[@]}"}) || fail "invalid worker launch environment"
if [ "$BACKEND" = herdr ]; then
  start_herdr
else
  start_herdr_core
fi
