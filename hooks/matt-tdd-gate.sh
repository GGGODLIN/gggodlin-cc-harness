#!/usr/bin/env bash
# 本檔在契約測試底下：bash ~/.claude/skills/implement/scripts/tests/matt-tdd-gate.test.sh && bash ~/.claude/hooks/matt-tdd-loopguard.test.sh
set -u
# 2026-09-13 修：payload 欄位為 JSON null（Codex 內部 thread 的 Stop 帶 transcript_path:null）一律視同缺欄位、不再當非法；
#   整包 JSON 解不開時只有 PreToolUse 才 deny，Stop 一律靜默放行。起因：Codex 總機把 Stop 收到的 PreToolUse 式 deny 當 block，
#   內部 thread 01a096e6 被連擋 166 次（9 分半）。Stop 段「不擋」自此涵蓋 payload 異常分支。
# 2026-09-06 拍板 a：Stop 段降為純提示型（gate-authoring §5「要降就明寫在檔頭」）。
#   原 block 路徑一律改出 systemMessage＋hookSpecificOutput.additionalContext，不再回 decision:block、不阻擋回合結束。
#   loop guard 保留、語意改為「同狀態最多提醒 3 次／總計 6 次後清 marker、記 ESCAPED」。PreToolUse 段（arming／deny）不變。
#   依據：loopguard audit 2026-08-25～09-06 共 4 次 BLOCKED 皆非真陽性（1 compact bug、2 只做 waived 票的 Routing A/B worker、1 流程順序）。
#   threat model：Stop 段自此為提示型，不承諾攔任何事；所有判不出來的分支一律只提示、不擋。PreToolUse arming 段仍為安全型（payload／marker 異常即 deny）。
# 2026-10-09 修：上面「不阻擋回合結束」不成立。官方 hooks 文件（Stop decision control）寫明 Stop 的 additionalContext 會讓對話續跑，
#   提示叫醒模型、模型回話又觸發 Stop，一個 session 8 秒內連跳 4 次，直到 loop guard 放行並刪掉 marker、後續提醒全失效。
#   修法一：stop_hook_active=true（這輪已是 hook 續跑）一律靜默、不計數，每次自然停下最多多跑一輪。
#   修法二：manifest 缺失、且 arming 後沒有 Edit／Write／NotebookEdit／Agent 時，視為仍在等使用者選測試模式（implement 契約規定此時不得建 manifest），靜默。
#   不承諾：用 Bash 改檔不算動工；transcript 讀不懂時照舊提醒。

INPUT=$(cat)
ROOT=${MATT_TDD_ROOT:-$HOME/.claude/logs/matt-tdd}
PENDING=${MATT_TDD_PENDING_DIR:-$ROOT/pending}
POLICY=${MATT_TDD_POLICY:-$HOME/.claude/skills/implement/scripts/tdd-policy.mjs}
PYTHON=${MATT_TDD_PYTHON:-$(command -v python3)}

json_output() {
  "$PYTHON" -c 'import json,sys
kind,value=sys.argv[1:3]
reason=f"[matt-tdd-gate] {value}"
if kind == "deny":
  print(json.dumps({"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":reason}}, separators=(",",":")))
elif kind == "advise":
  reason=f"[matt-tdd-gate] 提示，不擋、不需本輪處理，可繼續收尾：{value}"
  print(json.dumps({"systemMessage":reason,"hookSpecificOutput":{"hookEventName":"Stop","additionalContext":reason}}, separators=(",",":")))
elif kind == "stop-context":
  print(json.dumps({"hookSpecificOutput":{"hookEventName":"Stop","additionalContext":reason}}, separators=(",",":")))
else:
  print(json.dumps({"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":value}}, separators=(",",":")))' "$1" "$2"
}

json_fields() {
  "$PYTHON" -c 'import json,sys
try:
  value=json.loads(sys.stdin.read())
  if not isinstance(value,dict): raise ValueError()
  event=value.get("hook_event_name","")
  tool=value.get("tool_name","")
  tool_input=value.get("tool_input",{})
  skill=tool_input.get("skill","") if isinstance(tool_input,dict) else ""
  fields=[event,tool,skill,value.get("session_id",""),value.get("tool_use_id",""),value.get("transcript_path",""),value.get("agent_id","")]
  fields=["" if field is None else field for field in fields]
  if not all(isinstance(field,str) for field in fields): raise ValueError()
  print("\x1f".join(fields))
except Exception:
  sys.exit(1)'
}

pretool_deny() {
  json_output deny "$1"
  exit 0
}

safe_id() {
  local value=$1
  [ -n "$value" ] || return 1
  case "$value" in
    .|..|*[!A-Za-z0-9._-]*) return 1 ;;
  esac
}

is_regular_file() {
  local path=$1
  [ ! -L "$path" ] && [ -f "$path" ]
}

is_owner_only_file() {
  local path=$1 owner mode
  is_regular_file "$path" || return 1
  owner=$(stat -f '%u' "$path" 2>/dev/null) || return 1
  mode=$(stat -f '%Lp' "$path" 2>/dev/null) || return 1
  [ "$owner" = "$(id -u)" ] || return 1
  [ $((mode % 100)) -eq 0 ]
}

prepare_pending_root() {
  local owner
  if [ -e "$PENDING" ] || [ -L "$PENDING" ]; then
    [ ! -L "$PENDING" ] && [ -d "$PENDING" ] || return 1
    [ -w "$PENDING" ] || return 1
  else
    mkdir -p "$PENDING" || return 1
  fi
  owner=$(stat -f '%u' "$PENDING" 2>/dev/null) || return 1
  [ "$owner" = "$(id -u)" ] || return 1
  chmod 700 "$PENDING" || return 2
}

post_arm_tdd_state() {
  local path=$1 implement_id=$2
  is_regular_file "$path" || return 1
  "$PYTHON" - "$path" "$implement_id" <<'PY'
import json,sys
path,implement_id=sys.argv[1:3]
records=[]
with open(path) as source:
  for line in source:
    if line.strip(): records.append(json.loads(line))
armed=[]
for index,record in enumerate(records):
  if record.get('type') != 'assistant': continue
  content=record.get('message',{}).get('content',[])
  if any(item.get('type') == 'tool_use' and item.get('id') == implement_id and item.get('name') == 'Skill' and item.get('input',{}).get('skill') == 'implement' for item in content if isinstance(item,dict)):
    armed.append(index)
valid=len(armed) == 1
tdd_after=False
if valid:
  for index in range(armed[0] + 1,len(records)):
    record=records[index]
    if record.get('type') != 'assistant': continue
    for item in record.get('message',{}).get('content',[]):
      if not isinstance(item,dict) or item.get('type') != 'tool_use' or item.get('name') != 'Skill' or item.get('input',{}).get('skill') != 'tdd': continue
      tool_id=item.get('id')
      for later in records[index + 1:]:
        for result in later.get('message',{}).get('content',[]):
          if not isinstance(result,dict) or result.get('type') != 'tool_result' or result.get('tool_use_id') != tool_id:
            continue
          legacy_success=result.get('is_error') is False
          runtime=later.get('toolUseResult',{})
          runtime_success=(
            isinstance(runtime,dict)
            and runtime.get('success') is True
            and runtime.get('commandName') == 'tdd'
          )
          if legacy_success or runtime_success:
            tdd_after=True
            break
        if tdd_after: break
      if tdd_after: break
    if tdd_after: break
print(json.dumps({'implement_record_valid':valid,'tdd_after':tdd_after},separators=(',',':')))
PY
}

post_arm_tdd_state_v3() {
  local path=$1 implement_id=$2 prefix_bytes=$3
  is_regular_file "$path" || return 1
  "$PYTHON" - "$path" "$implement_id" "$prefix_bytes" <<'PY'
import json,sys
path,implement_id,prefix_bytes=sys.argv[1:4]
with open(path,"rb") as source:
  raw=source.read()
try:
  prefix_length=int(prefix_bytes)
except ValueError:
  prefix_length=-1
prefix_valid=prefix_length >= 0 and len(raw) >= prefix_length
if not prefix_valid:
  print(json.dumps({'prefix_valid':False,'json_valid':False,'scanner_valid':False,'implement_state':'invalid','tdd_after':False},separators=(',',':')))
  raise SystemExit(0)
records=[]
offset=0
try:
  for line in raw.splitlines(keepends=True):
    start=offset
    offset += len(line)
    if line.strip():
      record=json.loads(line)
      if not isinstance(record,dict): raise ValueError()
      records.append((start,record))
  if offset != len(raw): raise ValueError()
except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
  print(json.dumps({'prefix_valid':True,'json_valid':False,'scanner_valid':False,'implement_state':'invalid','tdd_after':False},separators=(',',':')))
  raise SystemExit(0)

def record_content(record):
  message=record.get('message',{})
  content=message.get('content',[]) if isinstance(message,dict) else []
  return content if isinstance(content,list) else []

def successful_tdd_after(start_index):
  for index in range(start_index,len(records)):
    record=records[index][1]
    if record.get('type') != 'assistant': continue
    for item in record_content(record):
      if not isinstance(item,dict) or item.get('type') != 'tool_use' or item.get('name') != 'Skill': continue
      item_input=item.get('input',{})
      if not isinstance(item_input,dict) or item_input.get('skill') != 'tdd': continue
      tool_id=item.get('id')
      for later in records[index + 1:]:
        for result in record_content(later[1]):
          if not isinstance(result,dict) or result.get('type') != 'tool_result' or result.get('tool_use_id') != tool_id:
            continue
          legacy_success=result.get('is_error') is False
          runtime=later[1].get('toolUseResult',{})
          runtime_success=(
            isinstance(runtime,dict)
            and runtime.get('success') is True
            and runtime.get('commandName') == 'tdd'
          )
          if legacy_success or runtime_success:
            return True
  return False

suffix_indices=[index for index,(start,record) in enumerate(records) if start >= prefix_length]
scanner_invalid=False
for index in suffix_indices:
  record=records[index][1]
  message=record.get('message')
  if record.get('type') == 'assistant':
    if not isinstance(message,dict) or not isinstance(message.get('content'),list):
      scanner_invalid=True
      continue
  if not isinstance(message,dict): continue
  content=message.get('content',[])
  if not isinstance(content,list): continue
  for item in content:
    if not isinstance(item,dict): continue
    if item.get('type') == 'tool_result':
      result_id=item.get('tool_use_id')
      if not isinstance(result_id,str) or not result_id:
        scanner_invalid=True
    if record.get('type') != 'assistant' or item.get('type') != 'tool_use' or item.get('name') != 'Skill': continue
    item_input=item.get('input')
    if not isinstance(item_input,dict):
      scanner_invalid=True
    elif item_input.get('skill') == 'tdd':
      tool_id=item.get('id')
      if not isinstance(tool_id,str) or not tool_id:
        scanner_invalid=True
if scanner_invalid:
  print(json.dumps({'prefix_valid':True,'json_valid':True,'scanner_valid':False,'implement_state':'invalid','tdd_after':False},separators=(',',':')))
  raise SystemExit(0)
matching=[]
shape_invalid=False
for index in suffix_indices:
  record=records[index][1]
  if record.get('type') != 'assistant': continue
  items=[item for item in record_content(record) if isinstance(item,dict) and item.get('id') == implement_id]
  if not items: continue
  if len(items) != 1:
    shape_invalid=True
    continue
  item=items[0]
  item_input=item.get('input',{})
  if item.get('type') != 'tool_use' or item.get('name') != 'Skill' or not isinstance(item_input,dict) or item_input.get('skill') != 'implement':
    shape_invalid=True
    continue
  matching.append(index)
if shape_invalid or len(matching) > 1:
  print(json.dumps({'prefix_valid':True,'json_valid':True,'scanner_valid':True,'implement_state':'invalid','tdd_after':False},separators=(',',':')))
  raise SystemExit(0)
if len(matching) == 1:
  implement_state='explicit'
  tdd_after=successful_tdd_after(matching[0] + 1)
else:
  implement_state='slash'
  tdd_after=successful_tdd_after(suffix_indices[0] if suffix_indices else len(records))
print(json.dumps({'prefix_valid':True,'json_valid':True,'scanner_valid':True,'implement_state':implement_state,'tdd_after':tdd_after},separators=(',',':')))
PY
}

stop_event_payload() {
  printf '%s' "$INPUT" | "$PYTHON" -c 'import json,sys
try:
  value=json.loads(sys.stdin.read())
  sys.exit(0 if isinstance(value,dict) and value.get("hook_event_name") == "Stop" else 1)
except Exception:
  sys.exit(1)' 2>/dev/null
}

FIELDS=$(printf '%s' "$INPUT" | json_fields 2>/dev/null) || {
  stop_event_payload && exit 0
  pretool_deny 'invalid hook payload.'
}
IFS=$'\x1f' read -r EVENT TOOL SKILL SESSION TOOL_USE TRANSCRIPT AGENT_ID <<< "$FIELDS"

[ -z "$AGENT_ID" ] || exit 0

if [ "$EVENT" = "PreToolUse" ]; then
  [ -n "$TOOL" ] && [ -n "$SKILL" ] && [ -n "$SESSION" ] && [ -n "$TOOL_USE" ] && [ -n "$TRANSCRIPT" ] || pretool_deny 'required arming payload is missing or invalid.'
  [ "$TOOL" = "Skill" ] && [ -n "$SKILL" ] && [ -n "$SESSION" ] && [ -n "$TOOL_USE" ] && [ -n "$TRANSCRIPT" ] && is_regular_file "$TRANSCRIPT" || pretool_deny 'required arming payload is missing or invalid.'
  safe_id "$SESSION" || pretool_deny 'session id is invalid or dot/dot-dot.'
  safe_id "$TOOL_USE" || pretool_deny 'tool use id is invalid or dot/dot-dot.'
  [ "$SKILL" = "implement" ] || exit 0
  MARKER="$PENDING/$SESSION.json"
  if [ -e "$MARKER" ] || [ -L "$MARKER" ]; then
    pretool_deny 'Matt conditional TDD gate is already pending for this session; the first manifest remains unchanged.'
  fi
  prepare_pending_root
  PREPARED=$?
  [ "$PREPARED" -eq 0 ] || {
    [ "$PREPARED" -eq 2 ] && pretool_deny 'pending root chmod failure prevented arming.'
    pretool_deny 'pending root is invalid, symlinked, non-directory, or unwritable.'
  }
  umask 077
  TEMP=$(mktemp "$PENDING/.pending.XXXXXX") || pretool_deny 'temp creation failure prevented arming.'
  "$PYTHON" -c 'import json,sys
session,run,transcript,implement=sys.argv[1:5]
with open(transcript,"rb") as source:
  prefix=source.read()
try:
  offset=0
  for line in prefix.splitlines(keepends=True):
    offset += len(line)
    if line.strip():
      record=json.loads(line)
      if not isinstance(record,dict): raise ValueError()
  if offset != len(prefix): raise ValueError()
except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
  raise SystemExit(2)
print(json.dumps({"contract":"MATT_TDD_PENDING v3","session_id":session,"run_id":run,"transcript_path":transcript,"implement_tool_use_id":implement,"transcript_prefix_bytes":len(prefix)},indent=2))' "$SESSION" "$TOOL_USE" "$TRANSCRIPT" "$TOOL_USE" > "$TEMP"
  MARKER_WRITE_STATUS=$?
  if [ "$MARKER_WRITE_STATUS" -ne 0 ]; then
    unlink "$TEMP" 2>/dev/null || true
    if [ "$MARKER_WRITE_STATUS" -eq 2 ]; then
      pretool_deny 'transcript prefix contains malformed or incomplete JSONL.'
    fi
    pretool_deny 'pending marker write failure prevented arming.'
  fi
  if ! chmod 600 "$TEMP"; then
    unlink "$TEMP" 2>/dev/null || true
    pretool_deny 'pending marker chmod failure prevented arming.'
  fi
  READY="$TEMP.ready"
  if ! mv "$TEMP" "$READY"; then
    unlink "$TEMP" 2>/dev/null || true
    pretool_deny 'pending marker rename failure prevented arming.'
  fi
  if ! ln "$READY" "$MARKER"; then
    unlink "$READY" 2>/dev/null || true
    if [ -e "$MARKER" ] || [ -L "$MARKER" ]; then
      pretool_deny 'Matt conditional TDD gate is already pending for this session; the first manifest remains unchanged.'
    fi
    pretool_deny 'exclusive pending marker creation failed.'
  fi
  if ! unlink "$READY"; then
    unlink "$MARKER" 2>/dev/null || true
    pretool_deny 'pending marker temp cleanup failed after exclusive creation.'
  fi
  json_output context "Matt conditional TDD gate armed. After the approved ticket breakdown, run: node $POLICY init --session $SESSION --run $TOOL_USE --tickets <approved-ticket-set>. Scratch must pass the complete issues directory; OpenSpec must pass the combined tasks.md. If preflight ends without implementation, write a not-started decision with an allowed reason."
  exit 0
fi

[ "$EVENT" = "Stop" ] || exit 0

stop_continuation() {
  printf '%s' "$INPUT" | "$PYTHON" -c 'import json,sys
try:
  value=json.loads(sys.stdin.read())
  sys.exit(0 if value.get("stop_hook_active") in (True,"true") else 1)
except Exception:
  sys.exit(1)' 2>/dev/null
}
stop_continuation && exit 0

work_started_after_arm() {
  local path=$1 implement_id=$2 prefix_bytes=$3
  "$PYTHON" - "$path" "$implement_id" "$prefix_bytes" <<'PY' 2>/dev/null || printf 'started'
import json,sys
path,implement_id,prefix_bytes=sys.argv[1:4]
WORK={"Edit","MultiEdit","Write","NotebookEdit","Agent","Task"}
def content_of(record):
  message=record.get("message")
  content=message.get("content") if isinstance(message,dict) else None
  return content if isinstance(content,list) else []
try:
  with open(path,"rb") as source:
    raw=source.read()
  records=[]
  offset=0
  for line in raw.splitlines(keepends=True):
    start=offset
    offset += len(line)
    if line.strip():
      record=json.loads(line)
      if not isinstance(record,dict): raise ValueError()
      records.append((start,record))
  if prefix_bytes:
    prefix=int(prefix_bytes)
    if prefix < 0 or prefix > len(raw): raise ValueError()
    after=[record for start,record in records if start >= prefix]
  else:
    armed=[index for index,(start,record) in enumerate(records) if record.get("type") == "assistant" and any(isinstance(item,dict) and item.get("type") == "tool_use" and item.get("id") == implement_id for item in content_of(record))]
    if len(armed) != 1: raise ValueError()
    after=[record for start,record in records[armed[0] + 1:]]
  started=any(isinstance(item,dict) and item.get("type") == "tool_use" and item.get("name") in WORK for record in after if record.get("type") == "assistant" for item in content_of(record))
  print("started" if started else "idle")
except Exception:
  print("started")
PY
}

# Stop loop guard（2026-08-25 拍板 1.b 兩層自動放行；2026-09-06 拍板 a 後 block 已是提示，guard 轉為提醒上限）
#   fp    = {advise reason, pending marker mtime_ns, marker size}：同一失敗原因＋marker 未變 ＝ 狀態未變
#   same  = 指紋連續未變次數；變了歸零   total = 無條件累計
#   same>3 或 total>6 → 清 marker、停止提醒、記 loopguard/audit.jsonl ESCAPED；未達上限 → 出提示、記 BLOCKED（欄名沿用、語意＝已提醒）
LOOPGUARD_DIR=${MATT_TDD_LOOPGUARD_DIR:-$ROOT/loopguard}
LOOPGUARD_SAME=${MATT_TDD_LOOPGUARD_SAME:-3}
LOOPGUARD_TOTAL=${MATT_TDD_LOOPGUARD_TOTAL:-6}
MARKER=""
advise() {
  local reason=$1 verdict
  verdict=$("$PYTHON" - "$LOOPGUARD_DIR" "$SESSION" "${MARKER:-}" "$reason" "$LOOPGUARD_SAME" "$LOOPGUARD_TOTAL" <<'PY' 2>/dev/null
import hashlib, json, os, sys, time
d, session, marker, reason, same_lim, total_lim = sys.argv[1:7]
os.makedirs(d, mode=0o700, exist_ok=True)
key = hashlib.sha256(session.encode()).hexdigest()[:24]
path = os.path.join(d, key + ".json")
marker_stat = os.stat(marker) if marker and os.path.isfile(marker) and not os.path.islink(marker) else None
# "Same state" is the advise reason plus an unchanged marker; mtime+size stand in for the marker bytes
# so no content digest is stored (ADR 0003). A legacy state carrying "fp" never matches and restarts at 1.
fp = {
  "reason": reason,
  "marker_mtime_ns": marker_stat.st_mtime_ns if marker_stat else None,
  "marker_size": marker_stat.st_size if marker_stat else None,
}
state = {}
if os.path.isfile(path) and not os.path.islink(path):
  try:
    state = json.load(open(path))
    if not isinstance(state, dict): state = {}
  except Exception:
    state = {}
same = int(state.get("same", 0)) + 1 if state.get("fp") == fp else 1
total = int(state.get("total", 0)) + 1
release = same > int(same_lim) or total > int(total_lim)
audit = os.path.join(d, "audit.jsonl")
def log(event):
  if os.path.lexists(audit) and (os.path.islink(audit) or not os.path.isfile(audit)): return
  fd = os.open(audit, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
  with os.fdopen(fd, "a") as f:
    f.write(json.dumps({"ts": int(time.time()), "session": key, "event": event, "same": same, "total": total, "reason": reason[:200]}) + "\n")
if release:
  log("ESCAPED")
  try: os.unlink(path)
  except Exception: pass
  print(f"release same={same} total={total}")
else:
  tmp = path + ".tmp"
  fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
  with os.fdopen(fd, "w") as f:
    json.dump({"fp": fp, "same": same, "total": total}, f)
  os.replace(tmp, path)
  log("BLOCKED")
  print(f"block same={same} total={total}")
PY
) || { json_output advise "$reason"; exit 0; }
  case "$verdict" in
    release*)
      [ -n "${MARKER:-}" ] && [ -e "$MARKER" ] && unlink "$MARKER" 2>/dev/null
      exit 0 ;;
  esac
  json_output advise "$reason [loop guard: $verdict]"
  exit 0
}

safe_id "$SESSION" || advise 'session id is invalid.'
MARKER="$PENDING/$SESSION.json"
if [ ! -e "$MARKER" ] && [ ! -L "$MARKER" ]; then
  exit 0
fi

is_owner_only_file "$MARKER" || advise 'pending marker is not a regular owner-only control file.'
MARKER_FIELDS=$("$PYTHON" -c 'import json,sys
try:
  value=json.load(open(sys.argv[1]))
  fields=[value.get("contract",""),value.get("session_id",""),value.get("run_id",""),value.get("transcript_path",""),value.get("implement_tool_use_id","")]
  if not all(isinstance(field,str) for field in fields): raise ValueError()
  if fields[0] == "MATT_TDD_PENDING v3":
    prefix_bytes=value.get("transcript_prefix_bytes")
    if isinstance(prefix_bytes,bool) or not isinstance(prefix_bytes,int) or prefix_bytes < 0: raise ValueError()
    fields.append(str(prefix_bytes))
  elif fields[0] == "MATT_TDD_PENDING v2":
    fields.append("")
  else:
    raise ValueError()
  print("\x1f".join(fields))
except Exception:
  sys.exit(1)' "$MARKER" 2>/dev/null) || advise 'pending marker is malformed.'
IFS=$'\x1f' read -r MARKER_CONTRACT MARKER_SESSION RUN_ID MARKER_TRANSCRIPT IMPLEMENT_TOOL_USE PREFIX_BYTES <<< "$MARKER_FIELDS"
case "$MARKER_CONTRACT" in
  'MATT_TDD_PENDING v2'|'MATT_TDD_PENDING v3') ;;
  *) advise 'pending marker is malformed.' ;;
esac
[ "$MARKER_SESSION" = "$SESSION" ] || advise 'pending marker is bound to another session.'
safe_id "$RUN_ID" && safe_id "$IMPLEMENT_TOOL_USE" || advise 'pending marker implement tool_use_id is invalid.'
[ "$RUN_ID" = "$IMPLEMENT_TOOL_USE" ] && [ "$MARKER_TRANSCRIPT" = "$TRANSCRIPT" ] || advise 'pending marker transcript binding is invalid.'

VALIDATION=$(node "$POLICY" validate --session "$SESSION" --run "$RUN_ID" 2>&1) || {
  if [ "$VALIDATION" = 'decision manifest is missing' ] && [ "$(work_started_after_arm "$MARKER_TRANSCRIPT" "$IMPLEMENT_TOOL_USE" "$PREFIX_BYTES")" = idle ]; then
    exit 0
  fi
  advise "decision manifest is missing or invalid. validator: $VALIDATION"
}
VALIDATION_FIELDS=$(printf '%s' "$VALIDATION" | "$PYTHON" -c 'import json,sys
try:
  value=json.load(sys.stdin)
  status=value.get("status","")
  required=value.get("tdd_required_count", value.get("required_count", ""))
  if not isinstance(status,str) or not isinstance(required,int): raise ValueError()
  print(f"{status}\x1f{required}")
except Exception:
  sys.exit(1)' 2>/dev/null) || advise 'decision manifest validation output is malformed.'
IFS=$'\x1f' read -r STATUS REQUIRED <<< "$VALIDATION_FIELDS"
case "$REQUIRED" in
  ''|*[!0-9]*) advise 'decision manifest validation output is malformed.' ;;
esac

if [ "$STATUS" != 'not-started' ] && [ "$REQUIRED" -gt 0 ]; then
  if [ "$MARKER_CONTRACT" = 'MATT_TDD_PENDING v2' ]; then
    TDD_STATE=$(post_arm_tdd_state "$MARKER_TRANSCRIPT" "$IMPLEMENT_TOOL_USE") || advise 'session transcript is not a regular file or contains malformed JSON.'
    TDD_FIELDS=$(printf '%s' "$TDD_STATE" | "$PYTHON" -c 'import json,sys
value=json.load(sys.stdin)
print(f"{str(value.get('"'"'implement_record_valid'"'"',False)).lower()}\x1f{str(value.get('"'"'tdd_after'"'"',False)).lower()}")' 2>/dev/null) || advise 'session transcript is not a regular file or contains malformed JSON.'
    IFS=$'\x1f' read -r IMPLEMENT_VALID TDD_AFTER <<< "$TDD_FIELDS"
    [ "$IMPLEMENT_VALID" = true ] || advise 'armed implement tool_use_id is missing or invalid in the assistant transcript.'
  else
    TDD_STATE=$(post_arm_tdd_state_v3 "$MARKER_TRANSCRIPT" "$IMPLEMENT_TOOL_USE" "$PREFIX_BYTES") || advise 'session transcript is not a regular file or contains malformed JSON.'
    TDD_FIELDS=$(printf '%s' "$TDD_STATE" | "$PYTHON" -c 'import json,sys
value=json.load(sys.stdin)
print(f"{str(value.get('"'"'prefix_valid'"'"',False)).lower()}\x1f{str(value.get('"'"'json_valid'"'"',False)).lower()}\x1f{str(value.get('"'"'scanner_valid'"'"',False)).lower()}\x1f{value.get('"'"'implement_state'"'"','"'"'invalid'"'"')}\x1f{str(value.get('"'"'tdd_after'"'"',False)).lower()}")' 2>/dev/null) || advise 'session transcript is not a regular file or contains malformed JSON.'
    IFS=$'\x1f' read -r PREFIX_VALID JSON_VALID SCANNER_VALID IMPLEMENT_STATE TDD_AFTER <<< "$TDD_FIELDS"
    [ "$PREFIX_VALID" = true ] || advise 'transcript prefix is missing or was modified after arming.'
    [ "$JSON_VALID" = true ] || advise 'session transcript contains malformed JSON.'
    [ "$SCANNER_VALID" = true ] || advise 'required tickets need a successful Skill(tdd): assistant transcript scanner/schema is invalid.'
    [ "$IMPLEMENT_STATE" != invalid ] || advise 'post-arm implement record is malformed or duplicated.'
  fi
  [ "$TDD_AFTER" = true ] || advise 'required tickets need a successful Skill(tdd): a real tool invocation in a strictly later assistant record plus a later matching non-error tool_result; denied, errored, prose, and the same message do not count.'
fi

CLEANUP_BACKUP="$MARKER.$RUN_ID.cleanup"
ln "$MARKER" "$CLEANUP_BACKUP" || advise 'validated session could not prepare recoverable cleanup.'
if ! unlink "$MARKER"; then
  unlink "$CLEANUP_BACKUP" 2>/dev/null || true
  advise 'validated session could not clear its pending marker.'
fi
if [ "$STATUS" = 'not-started' ]; then
  CONSUMED=$(node "$POLICY" consume --session "$SESSION" --run "$RUN_ID" 2>&1) || {
    ln "$CLEANUP_BACKUP" "$MARKER" 2>/dev/null || true
    unlink "$CLEANUP_BACKUP" 2>/dev/null || true
    advise "validated decision manifest could not be consumed. validator: $CONSUMED"
  }
fi
if ! unlink "$CLEANUP_BACKUP"; then
  json_output stop-context "validated session completed; cleanup backup remains at $CLEANUP_BACKUP. Remove it after inspection."
  exit 0
fi
exit 0
