#!/usr/bin/env bash
# Threat model: this提示型 gate protects honest agents that forget to rerun a contract test after an edit. It does not prevent deliberate bypasses through an uncovered tool, a direct filesystem write, or a fabricated receipt.
# This gate uses literal path and file-content matching rather than a shell parser. It recognises common entry points only, 不承諾 grep 找得到用變數拼檔名的引用, and may match text that merely discusses a command or path.
# Surface table: Locked = this gate, its wrapper, and fixtures; Editable = command/SKILL.md targets; Append-only = session receipt JSONL; Human-controlled = the disabled sentinel.
# Locked lifecycle: bootstrap is the normal settings.json install; update edits this gate, its wrapper, or its fixture and reruns the fixture; recovery uses contract-test-gate.disabled and leaves the allow decision in stderr.
# Bypass table: a bare test command does not create a receipt; a changed target mtime or size invalidates an older receipt; a broken receipt path is rejected without blocking on FIFO I/O.
# Stop loop guard: same>=3／total>=6 are the two release thresholds; the first three or six calls block, then the next call releases, deliberately lowering this gate to提示型偏安全.
set -u

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PAYLOAD=$(cat 2>/dev/null) || exit 0
command -v jq >/dev/null 2>&1 || exit 0

EVENT=""
TOOL=""
FILE_PATH=""
SESSION_ID=""
CWD=""
if ! {
  IFS= read -r -d '' EVENT
  IFS= read -r -d '' TOOL
  IFS= read -r -d '' FILE_PATH
  IFS= read -r -d '' SESSION_ID
  IFS= read -r -d '' CWD
} < <(printf '%s' "$PAYLOAD" | jq -j '
  if type == "object" then
    (if (.hook_event_name? | type) == "string" then .hook_event_name else "" end), "\u0000",
    (if (.tool_name? | type) == "string" then .tool_name else "" end), "\u0000",
    (if (.tool_input? | type) == "object" and (.tool_input.file_path? | type) == "string" then .tool_input.file_path else "" end), "\u0000",
    (if (.session_id? | type) == "string" then .session_id else "" end), "\u0000",
    (if (.cwd? | type) == "string" then .cwd else "" end), "\u0000"
  else empty end
' 2>/dev/null); then
  exit 0
fi

HOME_DIR="${HOME:-}"
RUNS_DIR="${CONTRACT_TEST_RUNS_DIR:-${HOME_DIR:+$HOME_DIR/.claude/logs/contract-test-runs}}"
PENDING_DIR="${CONTRACT_TEST_PENDING_DIR:-${HOME_DIR:+$HOME_DIR/.claude/logs/contract-test-pending}}"
STATE_DIR="${CONTRACT_TEST_STATE_DIR:-${HOME_DIR:+$HOME_DIR/.claude/hooks/state}}"
DISABLED="${CONTRACT_TEST_DISABLED_SENTINEL:-${STATE_DIR:+$STATE_DIR/contract-test-gate.disabled}}"
RUNNER="${CONTRACT_TEST_RUNNER:-$HOOK_DIR/../scripts/contract-test-run}"

if [ -n "$DISABLED" ] && { [ -e "$DISABLED" ] || [ -L "$DISABLED" ]; }; then
  printf 'contract-test-receipt-gate disabled by %s; allowing hook.\n' "$DISABLED" >&2
  exit 0
fi

if [ "$EVENT" = "PostToolUse" ]; then
  case "$TOOL" in
    Edit|Write) ;;
    *) exit 0 ;;
  esac
  [ -n "$FILE_PATH" ] || exit 0
  [ -n "$SESSION_ID" ] || exit 0
  case "$FILE_PATH" in
    *.md) ;;
    *)
      _RAW_CHECK="$FILE_PATH"
      case "$_RAW_CHECK" in
        /*|~*) ;;
        *) _RAW_CHECK="${CWD:-.}/$_RAW_CHECK" ;;
      esac
      if [ ! -L "$_RAW_CHECK" ]; then
        exit 0
      fi
      ;;
  esac
  CANONICAL_PATH=$(python3 - "$FILE_PATH" "$CWD" <<'PY' 2>/dev/null
import os
import sys

path, cwd = sys.argv[1:3]
path = os.path.expanduser(path)
if not os.path.isabs(path):
  path = os.path.join(cwd or os.getcwd(), path)
print(os.path.realpath(path))
PY
  ) || exit 0
  TARGET=0
  case "$CANONICAL_PATH" in
    */SKILL.md) TARGET=1 ;;
  esac
  if [[ "$CANONICAL_PATH" =~ /\.claude(-max)?/commands/[^/]+\.md$ ]]; then
    TARGET=1
  fi
  [ "$TARGET" -eq 1 ] || exit 0
  [ -x "$RUNNER" ] || {
    printf '%s\n' '[contract-test-receipt-gate] contract-test wrapper unavailable; allowing edit.' >&2
    exit 0
  }
  # 失敗不當場提醒：避免把 agent 引去查無關問題；沒有收據時由 Stop 檢查攔。
  CONTRACT_TEST_SESSION_ID="$SESSION_ID" \
  CONTRACT_TEST_CWD="$CWD" \
  CONTRACT_TEST_RUNS_DIR="$RUNS_DIR" \
  CONTRACT_TEST_PENDING_DIR="$PENDING_DIR" \
  CONTRACT_TEST_STATE_DIR="$STATE_DIR" \
  CONTRACT_TEST_DISABLED_SENTINEL="$DISABLED" \
  CONTRACT_TEST_TIMEOUT_SECONDS="${CONTRACT_TEST_TIMEOUT_SECONDS:-${CONTRACT_TEST_TIMEOUT:-30}}" \
  CONTRACT_TEST_TOTAL_TIMEOUT_SECONDS="${CONTRACT_TEST_TOTAL_TIMEOUT_SECONDS:-${CONTRACT_TEST_TOTAL_TIMEOUT:-30}}" \
  "$RUNNER" "$CANONICAL_PATH" >/dev/null || true
  exit 0
fi

[ "$EVENT" = "Stop" ] || exit 0
[ -n "$SESSION_ID" ] || exit 0

if [[ "$SESSION_ID" =~ ^[A-Za-z0-9._-]+$ ]]; then
  SESSION_KEY="$SESSION_ID"
else
  SESSION_KEY=$(python3 - "$SESSION_ID" <<'PY' 2>/dev/null
import hashlib
import re
import sys

value = sys.argv[1]
print(value if re.fullmatch(r'[A-Za-z0-9._-]+', value) else hashlib.sha256(value.encode()).hexdigest()[:24])
PY
  ) || exit 0
fi
PENDING="$PENDING_DIR/$SESSION_KEY.jsonl"
if [ ! -e "$PENDING" ] && [ ! -L "$PENDING" ]; then
  exit 0
fi
LOOPGUARD_DIR="${CONTRACT_TEST_LOOPGUARD_DIR:-$STATE_DIR/contract-test-loopguard}"
SAME_LIMIT="${CONTRACT_TEST_LOOPGUARD_SAME:-3}"
TOTAL_LIMIT="${CONTRACT_TEST_LOOPGUARD_TOTAL:-6}"

python3 - "$PENDING" "$RUNS_DIR" "$SESSION_ID" "$LOOPGUARD_DIR" "$SAME_LIMIT" "$TOTAL_LIMIT" "$RUNNER" <<'PY'
import hashlib
import json
import os
import shlex
import stat
import sys
import tempfile
import time

pending_path, runs_dir, session_id, loopguard_dir, same_limit, total_limit, runner = sys.argv[1:8]


def regular(path):
  try:
    value = os.lstat(path)
  except OSError:
    return False
  return stat.S_ISREG(value.st_mode) and value.st_nlink == 1


def open_regular(path):
  descriptor = -1
  try:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
      os.close(descriptor)
      return -1
    return descriptor
  except OSError:
    if descriptor >= 0:
      try:
        os.close(descriptor)
      except OSError:
        pass
    return -1


def read_jsonl(path):
  if not os.path.lexists(path):
    return []
  descriptor = open_regular(path)
  if descriptor < 0:
    return None
  try:
    with os.fdopen(descriptor, "r", encoding="utf-8") as source:
      descriptor = -1
      rows = []
      for line in source:
        if not line.strip():
          continue
        value = json.loads(line)
        if not isinstance(value, dict):
          return None
        rows.append(value)
      return rows
  except (OSError, ValueError, TypeError, UnicodeError):
    return None
  finally:
    if descriptor >= 0:
      os.close(descriptor)


def file_stamp(path):
  descriptor = open_regular(path)
  if descriptor < 0:
    return None
  try:
    metadata = os.fstat(descriptor)
    return [metadata.st_mtime_ns, metadata.st_size]
  except OSError:
    return None
  finally:
    os.close(descriptor)


def receipt_path():
  key = session_id if all(c.isalnum() or c in "._-" for c in session_id) else hashlib.sha256(session_id.encode()).hexdigest()[:24]
  return os.path.join(runs_dir, key + ".jsonl")


def guard_path():
  key = session_id if all(c.isalnum() or c in "._-" for c in session_id) else hashlib.sha256(session_id.encode()).hexdigest()[:24]
  return os.path.join(loopguard_dir, key + ".json")


def append_audit(event, same, total):
  if not os.path.isdir(loopguard_dir) or os.path.islink(loopguard_dir):
    return
  path = os.path.join(loopguard_dir, "audit.jsonl")
  if os.path.lexists(path) and not regular(path):
    return
  descriptor = -1
  try:
    os.makedirs(loopguard_dir, mode=0o700, exist_ok=True)
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags, 0o600)
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
      return
    with os.fdopen(descriptor, "a", encoding="utf-8") as target:
      descriptor = -1
      target.write(json.dumps({"event": event, "session_id": session_id, "same": same, "total": total, "ts": int(time.time())}, separators=(",", ":")) + "\n")
      target.flush()
  except OSError:
    pass
  finally:
    if descriptor >= 0:
      try:
        os.close(descriptor)
      except OSError:
        pass


def loop_guard(missing):
  try:
    same_cap = int(same_limit)
    total_cap = int(total_limit)
    if same_cap <= 0 or total_cap <= 0:
      raise ValueError
  except ValueError:
    same_cap, total_cap = 3, 6
  try:
    if os.path.lexists(loopguard_dir) and (os.path.islink(loopguard_dir) or not os.path.isdir(loopguard_dir)):
      return "allow"
    os.makedirs(loopguard_dir, mode=0o700, exist_ok=True)
    path = guard_path()
    if os.path.lexists(path) and not regular(path):
      return "allow"
    # The repeat detector stores the missing-test list itself and compares it as text; a digest here
    # would be a content hash of the gate's own state (ADR 0003). Legacy state carrying "fingerprint"
    # simply never matches, so the counter restarts at 1.
    missing_key = json.dumps(missing, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    state = {}
    descriptor = open_regular(path)
    if descriptor >= 0:
      try:
        with os.fdopen(descriptor, encoding="utf-8") as source:
          descriptor = -1
          value = json.load(source)
        if isinstance(value, dict):
          state = value
      except (OSError, ValueError, TypeError):
        state = {}
      finally:
        if descriptor >= 0:
          os.close(descriptor)
    same = int(state.get("same", 0)) + 1 if state.get("missing") == missing_key else 1
    total = int(state.get("total", 0)) + 1
    if same > same_cap or total > total_cap:
      append_audit("ESCAPED", same, total)
      try:
        os.unlink(path)
      except OSError:
        pass
      return "release"
    descriptor, temporary = tempfile.mkstemp(prefix=".contract-test-loopguard.", dir=loopguard_dir)
    try:
      os.fchmod(descriptor, 0o600)
      with os.fdopen(descriptor, "w", encoding="utf-8") as target:
        descriptor = -1
        json.dump({"missing": missing_key, "same": same, "total": total}, target, separators=(",", ":"))
        target.flush()
        os.fsync(target.fileno())
      os.replace(temporary, path)
      temporary = ""
    finally:
      if descriptor >= 0:
        os.close(descriptor)
      if temporary:
        try:
          os.unlink(temporary)
        except OSError:
          pass
    append_audit("BLOCKED", same, total)
    return f"block same={same} total={total}"
  except (OSError, ValueError, TypeError):
    return "allow"

pending = read_jsonl(pending_path)
receipts = read_jsonl(receipt_path())
latest_receipts = {}
if isinstance(receipts, list):
  for row in receipts:
    if isinstance(row, dict):
      key = (str(row.get("target_path", "")), str(row.get("test_path", "")), row.get("target_mtime_ns"), row.get("target_size"))
      latest_receipts[key] = row
missing = []
if pending is None:
  recovery = " ".join(shlex.quote(value) for value in (runner, "--session", session_id, pending_path))
  missing.append({"target": pending_path, "expected_stamp": None, "current_stamp": None, "tests": ["pending state unreadable"], "commands": [recovery]})
else:
  for entry in pending:
    if not isinstance(entry, dict):
      continue
    target = str(entry.get("target_path", ""))
    expected_stamp = [entry.get("target_mtime_ns"), entry.get("target_size")]
    current_stamp = file_stamp(target)
    tests = entry.get("test_paths", [])
    if not isinstance(tests, list) or not tests:
      tests = [entry.get("test_path", "")]
    tests = [str(test) for test in tests if test]
    absent = []
    for test in tests:
      current_test_stamp = file_stamp(test)
      row = latest_receipts.get((target, test, expected_stamp[0], expected_stamp[1]))
      if current_test_stamp is None or not isinstance(row, dict) or row.get("exit") != 0 or row.get("exit_code") != 0 or row.get("timeout") is not False or [row.get("test_mtime_ns"), row.get("test_size")] != current_test_stamp:
        absent.append(test)
    if current_stamp != expected_stamp or absent:
      commands = entry.get("commands", [])
      if not isinstance(commands, list):
        commands = []
      commands = [str(command) for command in commands]
      wrapper = " ".join(shlex.quote(value) for value in (runner, "--session", session_id, target))
      if wrapper not in commands:
        commands.append(wrapper)
      missing.append({"target": target, "expected_stamp": expected_stamp, "current_stamp": current_stamp, "tests": absent or tests, "commands": commands})

if not missing:
  try:
    os.unlink(pending_path)
  except OSError:
    pass
  raise SystemExit(0)

verdict = loop_guard(missing)
if verdict == "release" or verdict == "allow":
  if verdict == "release":
    try:
      os.unlink(pending_path)
    except OSError:
      pass
  raise SystemExit(0)

items = []
for entry in missing:
  commands = "；".join(entry["commands"])
  tests = "、".join(entry["tests"])
  items.append(f"{entry['target']}（{tests}；{commands}）")
reason = (
  "contract-test 收據 gate：本 session 改過有契約考卷的檔案，但沒有每個測試對應的 exit 0 收據，"
  "或收據記的 mtime／size 已不是現檔的 mtime／size。先跑下列指令，長測試請用 wrapper：" + "；".join(items)
  + " [loop guard: " + verdict + "]"
)
print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
PY
exit 0
