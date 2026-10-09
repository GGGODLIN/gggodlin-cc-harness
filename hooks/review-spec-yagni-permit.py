#!/usr/bin/env python3
# 本檔在契約測試底下：python3 ~/.claude/hooks/review-spec-yagni-permit.test.py

import argparse
import contextlib
import fcntl
import io
import json
import os
import re
import secrets
import stat
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

BATCHES = ("stories", "decisions")
SESSION_RE = re.compile(r"^[A-Za-z0-9._-]+$")
PERMIT_RE = re.compile(r"^[0-9a-f]{32}$")
# Used only to make an event uuid safe as a tombstone filename; not a content check.
EVENT_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
MARKER_RE = re.compile(
  r"<review-spec-yagni:v1\s+permit_id=([0-9a-f]{32})\s+batch=(stories|decisions)>"
)
MENU_RE = re.compile(
  r"<review-spec-yagni-model-menu:v1\s+packet=([^\s>]+)>"
)
# The menu exists before any permit, so it names the packet path instead of a permit_id; which letters mean Fable is read from the menu itself
# so a merged seat+model menu (one letter answers both) needs no second question.
MENU_OPTION_RE = re.compile(r"(?:^|[\s；;，,、：:（(])([a-d])\.\s*([^；;\n]+)", re.MULTILINE)
# The to-spec review menu carries this marker; a human "f" right after it stands in for typing
# /review-spec yagni, so entering from that menu does not dead-end at command-missing.
ENTRY_MENU_RE = re.compile(r"<review-spec-entry-menu:v1>")
ENTRY_REPLIES = {"f", "f)", "選f", "選 f", "yagni"}
REVIEW_SPEC_ENVELOPES = (
  re.compile(
    r"^<command-message>review-spec</command-message>\s*\n<command-name>/review-spec</command-name>(?:\s*\n<command-args>(.*?)</command-args>)?\s*$",
    re.DOTALL,
  ),
  re.compile(
    r"^<command-name>/review-spec</command-name>\s*\n<command-message>review-spec</command-message>(?:\s*\n<command-args>(.*?)</command-args>)?\s*$",
    re.DOTALL,
  ),
)


def emit(payload, status=0):
  print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
  raise SystemExit(status)


def deny(reason):
  emit({"allowed": False, "reason": reason}, 3)


def now_utc():
  override = os.environ.get("REVIEW_SPEC_YAGNI_NOW")
  if override:
    return parse_time(override)
  return datetime.now(timezone.utc)


def parse_time(value):
  parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
  if parsed.utcoffset() is None:
    raise ValueError("timezone required")
  return parsed


def isoformat(value):
  return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_model_mapping(value):
  return re.sub(r"\([^()]*\)\s*$", "", value.strip()).strip()


def exact_path_count(prompt, path):
  token = re.compile(rf"(?<![A-Za-z0-9._~:/-]){re.escape(path)}(?![A-Za-z0-9._~:/-])")
  return len(token.findall(prompt))


def current_model_binding():
  vendor = os.environ.get("CC_VENDOR", "").strip()
  expected = normalize_model_mapping(os.environ.get("ANTHROPIC_DEFAULT_FABLE_MODEL", ""))
  if vendor and not expected:
    deny("fable-model-mapping-missing")
  if not vendor:
    expected = ""
  return {"vendor": vendor, "expected_fable_model": expected}


def ensure_private_directory(path, reason, parents=False):
  try:
    path.mkdir(mode=0o700, parents=parents, exist_ok=True)
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
  except OSError:
    deny(reason)
  try:
    metadata = os.fstat(descriptor)
    if metadata.st_uid != os.getuid() or not stat.S_ISDIR(metadata.st_mode):
      deny(reason)
    os.fchmod(descriptor, 0o700)
  finally:
    os.close(descriptor)
  return path


def runtime_dir():
  value = os.environ.get(
    "REVIEW_SPEC_YAGNI_RUNTIME_DIR",
    f"/private/tmp/claude-review-spec-yagni-{os.getuid()}",
  )
  return ensure_private_directory(Path(value), "untrusted-runtime", parents=True)


def issued_dir(session):
  value = os.environ.get(
    "REVIEW_SPEC_YAGNI_ISSUED_DIR",
    str(Path.home() / ".claude" / "logs" / "review-spec-yagni-issued"),
  )
  root = ensure_private_directory(Path(value), "untrusted-issued-dir", parents=True)
  return ensure_private_directory(root / session, "untrusted-issued-dir")


def transcript_root():
  value = os.environ.get(
    "REVIEW_SPEC_YAGNI_TRANSCRIPT_ROOT",
    str(Path.home() / ".claude" / "projects"),
  )
  return Path(value)


def state_path(root, session):
  if not SESSION_RE.fullmatch(session):
    deny("invalid-session-id")
  return root / f"{session}.json"


def lock_path(root, session):
  return root / f"{session}.lock"


def locked(root, session):
  path = lock_path(root, session)
  try:
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
  except OSError:
    deny("untrusted-lock")
  try:
    metadata = os.fstat(descriptor)
    if (
      metadata.st_uid != os.getuid()
      or not stat.S_ISREG(metadata.st_mode)
      or metadata.st_nlink != 1
    ):
      deny("untrusted-lock")
    os.fchmod(descriptor, 0o600)
    handle = os.fdopen(descriptor, "r+")
    descriptor = -1
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    return handle
  finally:
    if descriptor >= 0:
      os.close(descriptor)


def read_owned_file(path, reason, private=False):
  try:
    before = path.lstat()
  except OSError:
    deny(reason)
  if (
    not stat.S_ISREG(before.st_mode)
    or stat.S_ISLNK(before.st_mode)
    or before.st_uid != os.getuid()
    or before.st_nlink != 1
    or stat.S_IMODE(before.st_mode) & 0o022
    or private and stat.S_IMODE(before.st_mode) & 0o077
  ):
    deny(reason)
  try:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
  except OSError:
    deny(reason)
  try:
    after = os.fstat(descriptor)
    if (
      after.st_dev != before.st_dev
      or after.st_ino != before.st_ino
      or after.st_uid != os.getuid()
      or not stat.S_ISREG(after.st_mode)
      or after.st_nlink != 1
    ):
      deny(reason)
    with os.fdopen(descriptor, "rb") as handle:
      descriptor = -1
      return handle.read()
  finally:
    if descriptor >= 0:
      os.close(descriptor)


def atomic_write(path, payload):
  descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
  try:
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
      descriptor = -1
      json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
      handle.write("\n")
      handle.flush()
      os.fsync(handle.fileno())
    os.replace(temporary, path)
  finally:
    if descriptor >= 0:
      os.close(descriptor)
    if os.path.exists(temporary):
      os.unlink(temporary)


def create_snapshot(payload, path):
  descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
  try:
    os.fchmod(descriptor, 0o400)
    with os.fdopen(descriptor, "wb") as handle:
      descriptor = -1
      handle.write(payload)
      handle.flush()
      os.fsync(handle.fileno())
    os.replace(temporary, path)
  finally:
    if descriptor >= 0:
      os.close(descriptor)
    if os.path.exists(temporary):
      os.unlink(temporary)


def read_json(path):
  raw = read_owned_file(path, "invalid-permit-state", private=True)
  try:
    value = json.loads(raw)
  except (UnicodeDecodeError, json.JSONDecodeError):
    deny("invalid-permit-state")
  if not isinstance(value, dict):
    deny("invalid-permit-state")
  return value


def trusted_directory(path):
  try:
    metadata = path.lstat()
  except OSError:
    return False
  return (
    metadata.st_uid == os.getuid()
    and stat.S_ISDIR(metadata.st_mode)
    and not stat.S_ISLNK(metadata.st_mode)
    and not stat.S_IMODE(metadata.st_mode) & 0o022
  )


def resolve_transcript(session):
  if not SESSION_RE.fullmatch(session):
    deny("invalid-session-id")
  projects = transcript_root()
  candidates = list(projects.glob(f"*/{session}.jsonl"))
  if len(candidates) != 1:
    deny("transcript-not-unique")
  path = candidates[0]
  if not trusted_directory(projects) or not trusted_directory(path.parent):
    deny("untrusted-transcript")
  return path.absolute(), read_owned_file(path, "untrusted-transcript")


def load_records(payload):
  records = []
  for line in payload.split(b"\n"):
    if not line.strip():
      continue
    try:
      record = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError):
      deny("transcript-invalid")
    if not isinstance(record, dict):
      deny("transcript-invalid")
    records.append(record)
  return records


def record_session(record):
  return record.get("sessionId", record.get("session_id"))


def direct_user_text(record):
  if record.get("type") != "user" or record.get("userType") != "external":
    return None
  origin = record.get("origin")
  if isinstance(origin, dict) and origin.get("kind") == "task-notification":
    return None
  if record.get("promptSource") == "system":
    return None
  if record.get("isCompactSummary") or record.get("isVisibleInTranscriptOnly"):
    return None
  message = record.get("message")
  if not isinstance(message, dict) or message.get("role") != "user":
    return None
  content = message.get("content")
  return content if isinstance(content, str) else None


def direct_assistant_text(record):
  if record.get("type") != "assistant" or record.get("isSidechain") is True:
    return None
  message = record.get("message")
  if not isinstance(message, dict) or message.get("role") != "assistant":
    return None
  content = message.get("content")
  if isinstance(content, str):
    return content
  if isinstance(content, list):
    values = [
      item.get("text", "")
      for item in content
      if isinstance(item, dict) and isinstance(item.get("text"), str)
    ]
    return "\n".join(values) if values else None
  return None


def review_spec_arguments(content):
  for pattern in REVIEW_SPEC_ENVELOPES:
    match = pattern.fullmatch(content)
    if match:
      return (match.group(1) or "").strip()
  return None


def normalized_reply(value):
  return value.strip().lower().rstrip("。.!！")


def find_command(records, session):
  found = None
  entry_pending = False
  for index, record in enumerate(records):
    if record_session(record) != session:
      continue
    assistant_text = direct_assistant_text(record)
    if assistant_text is not None:
      entry_pending = bool(ENTRY_MENU_RE.search(assistant_text))
      continue
    text = direct_user_text(record)
    if text is None:
      continue
    from_entry_menu = entry_pending
    entry_pending = False
    if from_entry_menu and normalized_reply(text) in ENTRY_REPLIES:
      found = (index, record)
      continue
    args = review_spec_arguments(text)
    if args is None:
      continue
    try:
      tokens = __import__("shlex").split(args)
    except ValueError:
      deny("invalid-command-arguments")
    if tokens and tokens[0] == "yagni":
      found = (index, record)
  if found is None:
    deny("review-spec-yagni-command-missing")
  index, record = found
  if not isinstance(record.get("uuid"), str) or not isinstance(record.get("timestamp"), str):
    deny("command-identity-missing")
  return index, record


def find_menu(records, session, command_index, packet):
  found = None
  for index, record in enumerate(records[command_index + 1 :], command_index + 1):
    if record_session(record) != session:
      continue
    text = direct_assistant_text(record)
    if text is None:
      continue
    matches = MENU_RE.findall(text)
    if not matches:
      continue
    if len(matches) != 1 or matches[0] != str(packet):
      deny("model-menu-invalid")
    if menu_fable_letters(text) is None:
      deny("model-menu-invalid")
    found = (index, record, text)
  if found is None:
    deny("model-menu-missing")
  index, record, text = found
  if not isinstance(record.get("uuid"), str):
    deny("model-menu-identity-missing")
  return index, record, text


def menu_fable_letters(text):
  fable, opus = set(), set()
  for letter, label in MENU_OPTION_RE.findall(text):
    lowered = label.lower()
    if "fable" in lowered and "opus" in lowered:
      return None
    if "fable" in lowered:
      fable.add(letter)
    if "opus" in lowered:
      opus.add(letter)
  if not fable or not opus or fable & opus:
    return None
  return fable


def parse_fable_selection(value, menu_text):
  letters = menu_fable_letters(menu_text) or set()
  normalized = normalized_reply(value)
  if normalized.startswith("選"):
    normalized = normalized[1:].strip()
  if normalized in {"fable", "fable 級"} or normalized in letters:
    return True
  match = re.fullmatch(r"([a-d])[.\s]\s*(.+)", normalized)
  return bool(match and match.group(1) in letters and "fable" in match.group(2) and "opus" not in match.group(2))


def find_selection(records, session, menu_index, menu_text):
  selected = None
  for index, record in enumerate(records[menu_index + 1 :], menu_index + 1):
    if record_session(record) != session:
      continue
    text = direct_user_text(record)
    if text is not None:
      selected = (index, record, text)
      break
    if direct_assistant_text(record) is not None:
      deny("model-selection-not-adjacent")
  if selected is None:
    deny("model-selection-missing")
  index, record, text = selected
  if not isinstance(record.get("uuid"), str) or not isinstance(record.get("timestamp"), str):
    deny("model-selection-identity-missing")
  if not parse_fable_selection(text, menu_text):
    deny("fable-not-selected")
  for later in records[index + 1 :]:
    if record_session(later) == session and direct_user_text(later) is not None:
      deny("model-selection-superseded")
  return index, record, text


def expected_packet_path(session):
  return Path.home() / ".claude" / ".scratch" / f"review-spec-yagni-packet-{session}.md"


def snapshot_path(root, state):
  return root / f"{state['session_id']}.{state['permit_id']}.packet"


def tombstone_path(session, selection_uuid):
  if not EVENT_KEY_RE.fullmatch(selection_uuid):
    deny("model-selection-identity-missing")
  return issued_dir(session) / selection_uuid


def spend_selection(session, selection_uuid, issued_at):
  path = tombstone_path(session, selection_uuid)
  payload = json.dumps(
    {"session_id": session, "selection_uuid": selection_uuid, "issued_at": issued_at},
    ensure_ascii=False,
    separators=(",", ":"),
  )
  try:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
  except FileExistsError:
    return False
  except OSError:
    deny("tombstone-write-failed")
  try:
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
      descriptor = -1
      handle.write(payload + "\n")
      handle.flush()
      os.fsync(handle.fileno())
  finally:
    if descriptor >= 0:
      os.close(descriptor)
  return True


def validate_state(state):
  required = (
    "permit_id",
    "session_id",
    "transcript_path",
    "command_uuid",
    "menu_uuid",
    "selection_uuid",
    "packet_path",
    "snapshot_path",
    "issued_at",
    "expires_at",
    "vendor",
    "expected_fable_model",
  )
  if state.get("version") != 1 or any(not isinstance(state.get(key), str) for key in required):
    deny("invalid-permit-state")
  if not PERMIT_RE.fullmatch(state["permit_id"]):
    deny("invalid-permit-state")
  remaining = state.get("remaining_batches")
  consumed = state.get("consumed_batches")
  if (
    not isinstance(remaining, list)
    or any(batch not in BATCHES for batch in remaining)
    or remaining != [batch for batch in BATCHES if batch in remaining]
    or len(remaining) != len(set(remaining))
    or not isinstance(consumed, dict)
    or any(batch not in BATCHES or not isinstance(tool_id, str) for batch, tool_id in consumed.items())
  ):
    deny("invalid-permit-state")
  if set(remaining) & set(consumed):
    deny("invalid-permit-state")


def validate_session(state, session):
  if state["session_id"] != session:
    deny("permit-session-mismatch")


def validate_binding(state):
  binding = current_model_binding()
  if state["vendor"] != binding["vendor"] or state["expected_fable_model"] != binding["expected_fable_model"]:
    deny("fable-model-binding-mismatch")


def validate_snapshot(root, state, current):
  try:
    expires = parse_time(state["expires_at"])
  except ValueError:
    deny("invalid-permit-state")
  if expires <= current:
    deny("permit-expired")
  path = Path(state["snapshot_path"])
  if path != snapshot_path(root, state):
    deny("snapshot-path-mismatch")
  return read_owned_file(path, "snapshot-invalid", private=True)


def validate_transcript_state(state):
  transcript, payload = resolve_transcript(state["session_id"])
  if str(transcript) != state["transcript_path"]:
    deny("permit-context-mismatch")
  records = load_records(payload)
  indexes = {}
  texts = {}
  for index, record in enumerate(records):
    uuid = record.get("uuid")
    if uuid == state["command_uuid"]:
      indexes["command"] = index
    elif uuid == state["menu_uuid"]:
      indexes["menu"] = index
      texts["menu"] = direct_assistant_text(record)
    elif uuid == state["selection_uuid"]:
      indexes["selection"] = index
      texts["selection"] = direct_user_text(record)
  if set(indexes) != {"command", "menu", "selection"}:
    deny("selection-context-missing")
  if not indexes["command"] < indexes["menu"] < indexes["selection"]:
    deny("selection-context-invalid")
  if not isinstance(texts.get("menu"), str) or MENU_RE.findall(texts["menu"]) != [state["packet_path"]]:
    deny("model-menu-changed")
  if not isinstance(texts.get("selection"), str):
    deny("model-selection-changed")
  if not parse_fable_selection(texts["selection"], texts["menu"]):
    deny("fable-not-selected")
  for record in records[indexes["selection"] + 1 :]:
    if record_session(record) == state["session_id"] and direct_user_text(record) is not None:
      deny("model-selection-superseded")


def cleanup_expired(root, current, exclude_session):
  for path in root.glob("*.json"):
    if path.stem == exclude_session or not SESSION_RE.fullmatch(path.stem):
      continue
    with locked(root, path.stem):
      if not path.exists():
        continue
      try:
        with contextlib.redirect_stdout(io.StringIO()):
          state = read_json(path)
          validate_state(state)
          expires = parse_time(state["expires_at"])
      except (ValueError, SystemExit):
        continue
      if expires > current:
        continue
      snapshot = Path(state["snapshot_path"])
      if snapshot.parent == root:
        snapshot.unlink(missing_ok=True)
      path.unlink(missing_ok=True)


def issue(args):
  if args.ttl <= 0 or args.max_selection_age <= 0:
    deny("invalid-time-limit")
  session = args.session
  transcript, transcript_payload = resolve_transcript(session)
  packet = Path(os.path.abspath(os.path.expanduser(args.packet)))
  if packet != expected_packet_path(session):
    deny("packet-path-mismatch")
  packet_payload = read_owned_file(packet, "packet-untrusted")
  records = load_records(transcript_payload)
  command_index, command = find_command(records, session)
  menu_index, menu, menu_text = find_menu(records, session, command_index, packet)
  _, selection, _ = find_selection(records, session, menu_index, menu_text)
  current = now_utc()
  try:
    command_time = parse_time(command["timestamp"])
    selection_time = parse_time(selection["timestamp"])
  except ValueError:
    deny("event-time-invalid")
  if command_time - current > timedelta(minutes=5) or selection_time - current > timedelta(minutes=5):
    deny("event-in-future")
  if current - selection_time > timedelta(seconds=args.max_selection_age):
    deny("model-selection-stale")
  root = runtime_dir()
  cleanup_expired(root, current, session)
  path = state_path(root, session)
  with locked(root, session):
    if path.exists():
      previous = read_json(path)
      validate_state(previous)
      validate_session(previous, session)
      if previous["selection_uuid"] == selection["uuid"]:
        validate_binding(previous)
        validate_snapshot(root, previous, current)
        validate_transcript_state(previous)
        emit(issue_response(previous))
      deny("permit-already-active")
    if tombstone_path(session, selection["uuid"]).exists():
      deny("selection-already-issued")
    permit_id = secrets.token_hex(16)
    snapshot = root / f"{session}.{permit_id}.packet"
    create_snapshot(packet_payload, snapshot)
    binding = current_model_binding()
    state = {
      "version": 1,
      "permit_id": permit_id,
      "session_id": session,
      "transcript_path": str(transcript),
      "command_uuid": command["uuid"],
      "menu_uuid": menu["uuid"],
      "selection_uuid": selection["uuid"],
      "packet_path": str(packet),
      "snapshot_path": str(snapshot),
      "issued_at": isoformat(current),
      "expires_at": isoformat(current + timedelta(seconds=args.ttl)),
      "vendor": binding["vendor"],
      "expected_fable_model": binding["expected_fable_model"],
      "remaining_batches": list(BATCHES),
      "consumed_batches": {},
    }
    try:
      atomic_write(path, state)
      if not spend_selection(session, selection["uuid"], state["issued_at"]):
        deny("selection-already-issued")
    except BaseException:
      path.unlink(missing_ok=True)
      snapshot.unlink(missing_ok=True)
      raise
  emit(issue_response(state))


def issue_response(state):
  return {
    "allowed": True,
    "permit_id": state["permit_id"],
    "snapshot_path": state["snapshot_path"],
    "expires_at": state["expires_at"],
    "batches": state["remaining_batches"],
    "vendor": state["vendor"],
    "expected_fable_model": state["expected_fable_model"],
  }


def marker(args):
  session = args.session
  current = now_utc()
  root = runtime_dir()
  path = state_path(root, session)
  with locked(root, session):
    if not path.exists():
      deny("permit-missing")
    state = read_json(path)
    validate_state(state)
    validate_session(state, session)
    if state["permit_id"] != args.permit_id:
      deny("permit-id-mismatch")
    validate_binding(state)
    validate_snapshot(root, state, current)
    validate_transcript_state(state)
    if args.batch not in state["remaining_batches"]:
      deny("batch-already-consumed")
    value = (
      f"<review-spec-yagni:v1 permit_id={state['permit_id']} "
      f"batch={args.batch}>"
    )
  emit({
    "allowed": True,
    "marker": value,
    "batch": args.batch,
    "snapshot_path": state["snapshot_path"],
    "expires_at": state["expires_at"],
  })


def consume():
  try:
    payload = json.load(sys.stdin)
  except (UnicodeDecodeError, json.JSONDecodeError):
    deny("hook-payload-invalid")
  if not isinstance(payload, dict):
    deny("hook-payload-invalid")
  if payload.get("tool_name") not in {"Agent", "Task"}:
    deny("tool-type-invalid")
  tool_input = payload.get("tool_input")
  if not isinstance(tool_input, dict):
    deny("tool-input-invalid")
  session = payload.get("session_id", "")
  description = tool_input.get("description", "")
  prompt = tool_input.get("prompt", "")
  tool_id = payload.get("tool_use_id", "")
  if (
    tool_input.get("subagent_type") != "routed-judge"
    or tool_input.get("model") != "fable"
    or not isinstance(description, str)
    or not isinstance(prompt, str)
    or not isinstance(tool_id, str)
    or not tool_id
  ):
    deny("agent-shape-invalid")
  if "<fable-ok>" in description:
    deny("generic-fable-marker-forbidden")
  matches = MARKER_RE.findall(description)
  if len(matches) != 1:
    deny("marker-invalid")
  permit_id, batch = matches[0]
  current = now_utc()
  root = runtime_dir()
  path = state_path(root, session)
  with locked(root, session):
    if not path.exists():
      deny("permit-missing")
    state = read_json(path)
    validate_state(state)
    validate_session(state, session)
    if state["permit_id"] != permit_id:
      deny("permit-marker-mismatch")
    validate_binding(state)
    validate_snapshot(root, state, current)
    validate_transcript_state(state)
    if batch not in state["remaining_batches"]:
      deny("batch-already-consumed")
    expected_sentinel = str(Path.home() / ".claude" / ".scratch" / f"yagni-c-{batch}-{session}.started")
    expected_report = str(Path.home() / ".claude" / ".scratch" / f"yagni-c-{batch}-{session}.report.md")
    for required in (state["snapshot_path"], expected_sentinel, expected_report):
      if exact_path_count(prompt, required) != 1:
        deny("prompt-binding-mismatch")
    state["remaining_batches"] = [value for value in state["remaining_batches"] if value != batch]
    state["consumed_batches"][batch] = tool_id
    atomic_write(path, state)
  emit({"allowed": True, "reason": "permit-consumed", "batch": batch})


def close(args):
  session = args.session
  current = now_utc()
  root = runtime_dir()
  path = state_path(root, session)
  with locked(root, session):
    if not path.exists():
      deny("permit-missing")
    state = read_json(path)
    validate_state(state)
    validate_session(state, session)
    if state["permit_id"] != args.permit_id:
      deny("permit-id-mismatch")
    validate_binding(state)
    validate_snapshot(root, state, current)
    if state["remaining_batches"]:
      deny("permit-still-active")
    Path(state["snapshot_path"]).unlink(missing_ok=True)
    path.unlink(missing_ok=True)
  emit({"allowed": True, "reason": "permit-closed"})


def build_parser():
  root = argparse.ArgumentParser()
  actions = root.add_subparsers(dest="action", required=True)

  issue_parser = actions.add_parser("issue")
  issue_parser.add_argument("--session", required=True)
  issue_parser.add_argument("--packet", required=True)
  issue_parser.add_argument("--ttl", type=int, default=3600)
  issue_parser.add_argument("--max-selection-age", type=int, default=900)

  marker_parser = actions.add_parser("marker")
  marker_parser.add_argument("--session", required=True)
  marker_parser.add_argument("--permit-id", required=True)
  marker_parser.add_argument("--batch", choices=BATCHES, required=True)

  close_parser = actions.add_parser("close")
  close_parser.add_argument("--session", required=True)
  close_parser.add_argument("--permit-id", required=True)

  actions.add_parser("consume")
  return root


def main():
  args = build_parser().parse_args()
  if args.action == "issue":
    issue(args)
  if args.action == "marker":
    marker(args)
  if args.action == "close":
    close(args)
  if args.action == "consume":
    consume()
  deny("unsupported-action")


if __name__ == "__main__":
  main()
