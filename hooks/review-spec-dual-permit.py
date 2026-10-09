#!/usr/bin/env python3

import argparse
import fcntl
import json
import os
import re
import secrets
import shlex
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

LENSES = ("simplify", "failure", "repo", "compat")
MODELS = ("opus", "fable")
MARKER_RE = re.compile(
  r"<review-spec-dual:v1\s+permit_id=([0-9a-f]{32})\s+lens=(simplify|failure|repo|compat)>"
)
RECOMMENDATION_RE = re.compile(
  r"<review-spec-recommendation:v1\s+permit_id=([0-9a-f]{32})\s+seats=([^>]+)>"
)
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
SESSION_RE = re.compile(r"^[A-Za-z0-9._-]+$")
AGENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def now_utc():
  override = os.environ.get("REVIEW_SPEC_DUAL_NOW")
  if override:
    return parse_time(override)
  return datetime.now(timezone.utc)


def isoformat(value):
  return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(value):
  parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
  if parsed.utcoffset() is None:
    raise ValueError("timezone required")
  return parsed


def canonical_lenses(lenses):
  selected = set(lenses)
  return [lens for lens in LENSES if lens in selected]


def seat_key(lens, model):
  return f"{lens}:{model}"


def parse_seat(value):
  parts = value.split(":")
  if len(parts) != 2 or parts[0] not in LENSES or parts[1] not in MODELS:
    return None
  return seat_key(parts[0], parts[1])


def canonical_seats(seats):
  selected = set(seats)
  return [seat_key(lens, model) for lens in LENSES for model in MODELS if seat_key(lens, model) in selected]


def seats_for_lenses(lenses):
  return [seat_key(lens, model) for lens in canonical_lenses(lenses) for model in MODELS]


def lenses_for_seats(seats):
  return canonical_lenses(seat.split(":", 1)[0] for seat in seats)


def fable_seats_for_seats(seats):
  return [seat for seat in canonical_seats(seats) if seat.endswith(":fable")]


def normalize_model_mapping(value):
  return re.sub(r"\([^()]*\)\s*$", "", value.strip()).strip()


def current_model_binding():
  vendor = os.environ.get("CC_VENDOR", "").strip()
  if not vendor:
    return {"vendor": "", "expected_opus_model": "", "expected_fable_model": ""}
  opus = normalize_model_mapping(os.environ.get("ANTHROPIC_DEFAULT_OPUS_MODEL", ""))
  fable = normalize_model_mapping(os.environ.get("ANTHROPIC_DEFAULT_FABLE_MODEL", ""))
  if not opus or not fable or opus == fable:
    deny("vendor-model-mapping-invalid")
  return {"vendor": vendor, "expected_opus_model": opus, "expected_fable_model": fable}


def require_current_model_binding(state):
  binding = current_model_binding()
  if any(state.get(key, "") != value for key, value in binding.items()):
    deny("vendor-model-binding-mismatch")
  return binding


def emit(payload, status=0):
  print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
  raise SystemExit(status)


def deny(reason):
  emit({"allowed": False, "reason": reason}, 3)


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
  path = Path(
    os.environ.get(
      "REVIEW_SPEC_DUAL_RUNTIME_DIR",
      f"/private/tmp/claude-review-spec-dual-{os.getuid()}",
    )
  )
  return ensure_private_directory(path, "untrusted-runtime", parents=True)


def trusted_parent_chain(path):
  current = Path(path.anchor)
  for part in path.parts[1:-1]:
    current /= part
    try:
      metadata = current.lstat()
    except OSError:
      return False
    if stat.S_ISLNK(metadata.st_mode):
      if metadata.st_uid != 0:
        return False
      continue
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid not in {0, os.getuid()} or stat.S_IMODE(metadata.st_mode) & 0o022:
      return False
  return True


def same_directory(left, right):
  try:
    return os.path.samefile(left, right)
  except OSError:
    return False


def session_path(root, session):
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
    if metadata.st_uid != os.getuid() or not stat.S_ISREG(metadata.st_mode):
      deny("untrusted-lock")
    os.fchmod(descriptor, 0o600)
    handle = os.fdopen(descriptor, "r+")
    descriptor = -1
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    return handle
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


def atomic_write_bytes(path, payload):
  descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
  try:
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
      descriptor = -1
      handle.write(payload)
      handle.flush()
      os.fsync(handle.fileno())
      os.fchmod(handle.fileno(), 0o400)
    os.replace(temporary, path)
  finally:
    if descriptor >= 0:
      os.close(descriptor)
    if os.path.exists(temporary):
      os.unlink(temporary)


def spent_command_path(session, command_uuid):
  root = Path.home() / ".claude" / "logs" / "review-spec-dual-issued"
  ensure_private_directory(root, "untrusted-tombstone-dir", parents=True)
  session_dir = ensure_private_directory(root / session, "untrusted-tombstone-dir")
  # 轉義後才當檔名：transcript 來的 uuid 不能帶出 session 目錄；cmd- 前綴避開 "." 與 ".."
  return session_dir / f"cmd-{quote(command_uuid, safe='')}"


def spend_command(session, authorization, current):
  path = spent_command_path(session, authorization["command_uuid"])
  payload = json.dumps(
    {
      "session_id": session,
      "command_uuid": authorization["command_uuid"],
      "issued_at": isoformat(current),
    },
    ensure_ascii=False,
    separators=(",", ":"),
  )
  try:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
  except FileExistsError:
    return None
  except OSError:
    deny("tombstone-write-failed")
  try:
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
      descriptor = -1
      handle.write(payload + "\n")
      handle.flush()
      os.fsync(handle.fileno())
  except OSError:
    path.unlink(missing_ok=True)
    deny("tombstone-write-failed")
  finally:
    if descriptor >= 0:
      os.close(descriptor)
  return path


def read_json(path):
  data = read_owned_file(path, "invalid-permit-state", private=True)
  try:
    payload = json.loads(data)
  except (UnicodeDecodeError, json.JSONDecodeError):
    deny("invalid-permit-state")
  if not isinstance(payload, dict):
    deny("invalid-permit-state")
  return payload


def validate_state_schema(state):
  strings = (
    "session_id",
    "transcript_path",
    "command_uuid",
    "spec_path",
    "snapshot_path",
    "issued_at",
    "expires_at",
  )
  if state.get("version") != 1:
    deny("invalid-permit-state")
  if any(not isinstance(state.get(key), str) or not state[key] for key in strings):
    deny("invalid-permit-state")
  vendor = state.get("vendor", "")
  expected_opus = state.get("expected_opus_model", "")
  expected_fable = state.get("expected_fable_model", "")
  if any(not isinstance(value, str) for value in (vendor, expected_opus, expected_fable)):
    deny("invalid-permit-state")
  state["vendor"] = vendor
  state["expected_opus_model"] = expected_opus
  state["expected_fable_model"] = expected_fable
  if vendor:
    if not expected_opus or not expected_fable or expected_opus == expected_fable:
      deny("invalid-permit-state")
  elif expected_opus or expected_fable:
    deny("invalid-permit-state")
  permit_id = state.get("permit_id")
  authorized = state.get("authorized_lenses")
  remaining = state.get("remaining_lenses")
  finalized = state.get("finalized")
  if not isinstance(finalized, bool):
    deny("invalid-permit-state")
  if not isinstance(permit_id, str) or not re.fullmatch(r"[0-9a-f]{32}", permit_id):
    deny("invalid-permit-state")
  for lenses in (authorized, remaining):
    if not isinstance(lenses, list) or any(not isinstance(lens, str) for lens in lenses):
      deny("invalid-permit-state")
    if len(lenses) != len(set(lenses)) or any(lens not in LENSES for lens in lenses):
      deny("invalid-permit-state")
  if authorized != canonical_lenses(authorized) or remaining != canonical_lenses(remaining):
    deny("invalid-permit-state")

  authorized_seats = state.get("authorized_seats")
  selection_event_uuid = state.get("selection_event_uuid", "")
  recommendation_event_uuid = state.get("recommendation_event_uuid", "")
  if any(not isinstance(value, str) for value in (selection_event_uuid, recommendation_event_uuid)):
    deny("invalid-permit-state")
  if authorized_seats is None:
    authorized_seats = seats_for_lenses(authorized)
    state["authorized_seats"] = authorized_seats
  if not isinstance(authorized_seats, list) or any(not isinstance(seat, str) for seat in authorized_seats):
    deny("invalid-permit-state")
  if len(authorized_seats) != len(set(authorized_seats)) or any(parse_seat(seat) is None for seat in authorized_seats):
    deny("invalid-permit-state")
  if authorized_seats != canonical_seats(authorized_seats):
    deny("invalid-permit-state")
  if lenses_for_seats(authorized_seats) != authorized:
    deny("invalid-permit-state")
  if finalized and any(seat_key(lens, "fable") not in authorized_seats for lens in remaining):
    deny("invalid-permit-state")

  if finalized:
    if any(lens not in authorized for lens in remaining):
      deny("invalid-permit-state")
    if not authorized_seats:
      deny("invalid-permit-state")
  elif authorized or authorized_seats:
    deny("invalid-permit-state")


def read_owned_file(path, reason, private=False):
  try:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
  except OSError:
    deny(reason)
  try:
    metadata = os.fstat(descriptor)
    mode = stat.S_IMODE(metadata.st_mode)
    if metadata.st_uid != os.getuid() or not stat.S_ISREG(metadata.st_mode):
      deny(reason)
    if mode & 0o022 or private and mode & 0o077:
      deny(reason)
    with os.fdopen(descriptor, "rb") as handle:
      descriptor = -1
      return handle.read()
  finally:
    if descriptor >= 0:
      os.close(descriptor)


def create_snapshot(source_bytes, destination):
  descriptor, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
  try:
    # Read-only like the yagni snapshot and the packet file: with no digest left, the copy's
    # immutability rests on this mode, and the gate below refuses a snapshot anyone can write.
    os.fchmod(descriptor, 0o400)
    with os.fdopen(descriptor, "wb") as output_handle:
      descriptor = -1
      output_handle.write(source_bytes)
      output_handle.flush()
      os.fsync(output_handle.fileno())
    os.replace(temporary, destination)
  finally:
    if descriptor >= 0:
      os.close(descriptor)
    if os.path.exists(temporary):
      os.unlink(temporary)


def read_cleanup_state(state_path):
  try:
    descriptor = os.open(state_path, os.O_RDONLY | os.O_NOFOLLOW)
  except OSError:
    return None
  try:
    metadata = os.fstat(descriptor)
    if metadata.st_uid != os.getuid() or not stat.S_ISREG(metadata.st_mode):
      return None
    with os.fdopen(descriptor, "rb") as handle:
      descriptor = -1
      data = handle.read()
  finally:
    if descriptor >= 0:
      os.close(descriptor)
  try:
    state = json.loads(data)
    expires_at = parse_time(state.get("expires_at", ""))
    snapshot_path = Path(state.get("snapshot_path", ""))
  except (AttributeError, TypeError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
    return None
  if not isinstance(state, dict):
    return None
  return state, expires_at, snapshot_path


def cleanup_runtime(root, current, exclude_session):
  referenced = set()
  for state_path in root.glob("*.json"):
    session = state_path.stem
    if not SESSION_RE.fullmatch(session):
      continue
    with locked(root, session):
      if not state_path.exists():
        continue
      loaded = read_cleanup_state(state_path)
      if loaded is None:
        continue
      state, expires_at, snapshot_path = loaded
      permit_id = state.get("permit_id", "")
      packet_paths = [root / f"{session}.{permit_id}.{lens}.packet" for lens in LENSES] if isinstance(permit_id, str) and re.fullmatch(r"[0-9a-f]{32}", permit_id) else []
      if snapshot_path.parent == root:
        referenced.add(snapshot_path)
      referenced.update(packet_paths)
      if session == exclude_session or expires_at > current:
        continue
      if snapshot_path.parent == root:
        snapshot_path.unlink(missing_ok=True)
      for path in packet_paths:
        path.unlink(missing_ok=True)
      state_path.unlink(missing_ok=True)
      referenced.discard(snapshot_path)
      referenced.difference_update(packet_paths)
  cutoff = current.timestamp() - 300
  for snapshot_path in root.glob("*.snapshot"):
    try:
      metadata = snapshot_path.lstat()
    except OSError:
      continue
    if snapshot_path in referenced or metadata.st_mtime > cutoff:
      continue
    if metadata.st_uid == os.getuid() and stat.S_ISREG(metadata.st_mode):
      snapshot_path.unlink(missing_ok=True)
  for path in root.glob("*.packet"):
    try:
      metadata = path.lstat()
    except OSError:
      continue
    if path in referenced or metadata.st_mtime > cutoff:
      continue
    if metadata.st_uid == os.getuid() and stat.S_ISREG(metadata.st_mode):
      path.unlink(missing_ok=True)
  for temporary in root.glob(".*.json.*"):
    try:
      metadata = temporary.lstat()
    except OSError:
      continue
    if metadata.st_mtime <= cutoff and metadata.st_uid == os.getuid() and stat.S_ISREG(metadata.st_mode):
      temporary.unlink(missing_ok=True)


def build_packet(state, lens, artifact_bytes):
  try:
    artifact = artifact_bytes.decode("utf-8")
  except UnicodeDecodeError:
    deny("snapshot-not-utf8")
  permit_id = state["permit_id"]
  return (
    f"REVIEW_SPEC_PERMIT_ID={permit_id}\n"
    f"REVIEW_SPEC_EXPIRES_AT={state['expires_at']}\n"
    f"REVIEW_SPEC_LENS={lens}\n"
    f"REVIEW_SPEC_ARTIFACT_BEGIN={permit_id}\n"
    f"{artifact}\n"
    f"REVIEW_SPEC_ARTIFACT_END={permit_id}"
  )


def canonical_reference_packet(value):
  return value.replace("\r\n", "\n").replace("\r", "\n")


def packet_path(root, state, lens):
  return root / f"{state['session_id']}.{state['permit_id']}.{lens}.packet"


def build_packet_reference(state, lens, path):
  return (
    f"REVIEW_SPEC_PACKET_PATH={path}\n"
    f"REVIEW_SPEC_PERMIT_ID={state['permit_id']}\n"
    f"REVIEW_SPEC_EXPIRES_AT={state['expires_at']}\n"
    f"REVIEW_SPEC_LENS={lens}"
  )


def remove_packet_files(root, state):
  paths = [packet_path(root, state, lens) for lens in LENSES]
  existing = []
  for path in paths:
    try:
      metadata = path.lstat()
    except FileNotFoundError:
      continue
    except OSError:
      deny("packet-cleanup-failed")
    if metadata.st_uid != os.getuid() or not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
      deny("packet-cleanup-failed")
    existing.append(path)
  for path in existing:
    try:
      path.unlink()
    except OSError:
      deny("packet-cleanup-failed")


def trusted_directory(path):
  try:
    metadata = path.lstat()
  except OSError:
    return False
  mode = stat.S_IMODE(metadata.st_mode)
  return (
    metadata.st_uid == os.getuid()
    and stat.S_ISDIR(metadata.st_mode)
    and not stat.S_ISLNK(metadata.st_mode)
    and not mode & 0o022
  )


def resolve_transcript(session):
  if not SESSION_RE.fullmatch(session):
    deny("invalid-session-id")
  projects = Path.home() / ".claude" / "projects"
  candidates = list(projects.glob(f"*/{session}.jsonl"))
  if len(candidates) != 1:
    deny("transcript-not-unique")
  raw_path = candidates[0]
  if not trusted_directory(projects) or not trusted_directory(raw_path.parent):
    deny("untrusted-transcript")
  transcript_bytes = read_owned_file(raw_path, "untrusted-transcript")
  return raw_path.absolute(), transcript_bytes


def load_records(data):
  records = []
  for line in data.split(b"\n"):
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


def review_spec_arguments(content):
  for pattern in REVIEW_SPEC_ENVELOPES:
    match = pattern.fullmatch(content)
    if match:
      return (match.group(1) or "").strip()
  return None


def parse_args(value):
  try:
    return shlex.split(value)
  except ValueError:
    deny("invalid-command-arguments")


def command_path(record, args):
  tokens = parse_args(args)
  if not tokens:
    return None
  path_tokens = tokens[1:] if tokens[0] in {"1", "2", "3", "4"} else tokens
  if not path_tokens:
    return None
  raw = " ".join(path_tokens)
  cwd = record.get("cwd")
  if not isinstance(cwd, str) or not cwd:
    deny("command-cwd-missing")
  path = Path(raw).expanduser()
  if not path.is_absolute():
    path = Path(cwd) / path
  return Path(os.path.abspath(path))


def find_authorization(records, session, allow_followup=False):
  command_index = None
  command_record = None
  args = None
  for index, record in enumerate(records):
    text = direct_user_text(record)
    if text is None:
      continue
    parsed_args = review_spec_arguments(text)
    if parsed_args is None:
      continue
    record_session = record.get("sessionId")
    if record_session is None:
      record_session = record.get("session_id")
    if record_session != session:
      continue
    command_index = index
    command_record = record
    args = parsed_args
  if command_record is None or args is None:
    deny("review-spec-command-missing")

  tokens = parse_args(args)
  if not tokens or tokens[0] not in {"1", "2", "3", "4"}:
    deny("tier3-must-be-explicit")
  if tokens[0] != "3":
    deny("tier3-not-authorized")
  if len(tokens) < 2:
    deny("tier3-spec-path-required")
  superseded = any(direct_user_text(record) is not None for record in records[command_index + 1 :])
  if superseded and not allow_followup:
    deny("authorization-superseded")
  command_uuid = command_record.get("uuid")
  timestamp = command_record.get("timestamp")
  if not isinstance(command_uuid, str):
    deny("authorization-identity-missing")
  if not isinstance(timestamp, str):
    deny("authorization-time-missing")
  try:
    command_time = parse_time(timestamp)
  except ValueError:
    deny("authorization-time-invalid")

  return {
    "command_uuid": command_uuid,
    "command_time": command_time,
    "expected_spec": command_path(command_record, args),
    "superseded": superseded,
  }


def direct_assistant_text(record):
  if record.get("type") != "assistant" or record.get("isSidechain") is True:
    return None
  if record.get("sessionId", record.get("session_id")) is None:
    return None
  message = record.get("message")
  if not isinstance(message, dict) or message.get("role") != "assistant":
    return None
  content = message.get("content")
  if isinstance(content, str):
    return content
  if isinstance(content, list):
    texts = [item.get("text", "") for item in content if isinstance(item, dict) and isinstance(item.get("text"), str)]
    return "\n".join(texts) if texts else None
  return None


def find_selection_event(records, session, command_uuid, requested_uuid=None):
  if records is None:
    deny("transcript-invalid")
  command_index = None
  for index, record in enumerate(records):
    if record.get("uuid") == command_uuid and record.get("sessionId", record.get("session_id")) == session:
      command_index = index
      break
  if command_index is None:
    deny("review-spec-command-missing")
  candidates = []
  for index, record in enumerate(records[command_index + 1 :], command_index + 1):
    if record.get("sessionId", record.get("session_id")) != session:
      continue
    text = direct_user_text(record)
    if text is None:
      continue
    record_uuid = record.get("uuid")
    if not isinstance(record_uuid, str) or not record_uuid:
      deny("selection-identity-missing")
    candidates.append((record_uuid, text, index))
  if not candidates:
    deny("selection-missing" if requested_uuid is None else "selection-event-missing")
  latest = candidates[-1]
  if requested_uuid is not None and requested_uuid != latest[0]:
    deny("selection-event-superseded")
  return latest


def find_recommendation_event(records, session, command_uuid, selection_index, requested_uuid, permit_id):
  command_index = None
  for index, record in enumerate(records):
    if record.get("uuid") == command_uuid and record.get("sessionId", record.get("session_id")) == session:
      command_index = index
      break
  if command_index is None:
    deny("review-spec-command-missing")
  candidates = []
  for index, record in enumerate(records[command_index + 1 : selection_index], command_index + 1):
    if record.get("sessionId", record.get("session_id")) != session:
      continue
    text = direct_assistant_text(record)
    if text is None:
      continue
    match = RECOMMENDATION_RE.search(text)
    if match is None:
      continue
    if match.group(1) != permit_id:
      continue
    values = [value.strip() for value in match.group(2).split(",") if value.strip()]
    seats = []
    for value in values:
      seat = parse_seat(value)
      if seat is None:
        deny("recommendation-invalid")
      seats.append(seat)
    if not seats or len(seats) != len(set(seats)):
      deny("recommendation-invalid")
    record_uuid = record.get("uuid")
    if not isinstance(record_uuid, str) or not record_uuid:
      deny("recommendation-identity-missing")
    candidates.append((record_uuid, canonical_seats(seats)))
  if not candidates:
    deny("recommendation-required")
  latest_uuid, latest_seats = candidates[-1]
  if requested_uuid is None:
    deny("recommendation-required")
  if requested_uuid != latest_uuid:
    deny("recommendation-event-superseded")
  return latest_uuid, latest_seats


LENS_SELECTION_ALIASES = {
  "simplify": ("simplify", "簡化"),
  "failure": ("failure", "失敗", "弱點"),
  "repo": ("repo", "一致性"),
  "compat": ("compat", "相容", "契約"),
}
MODEL_SELECTION_ALIASES = {
  "opus": ("opus",),
  "fable": ("fable",),
}


def parse_user_selection_seats(text):
  normalized = text.lower()
  canonical_matches = re.findall(
    r"(?i)(simplify|failure|repo|compat)\s*[:：]\s*(opus|fable)",
    text,
  )
  if canonical_matches:
    return canonical_seats(seat_key(lens.lower(), model.lower()) for lens, model in canonical_matches)
  candidates = []
  for lens, aliases in LENS_SELECTION_ALIASES.items():
    positions = [normalized.find(alias.lower()) for alias in aliases if normalized.find(alias.lower()) >= 0]
    if not positions:
      continue
    start = min(positions)
    window = normalized[max(0, start - 36) : start + 72]
    models = [model for model, model_aliases in MODEL_SELECTION_ALIASES.items() if any(alias in window for alias in model_aliases)]
    if len(models) != 1:
      return None
    candidates.append(seat_key(lens, models[0]))
  if not candidates or len(candidates) != len(set(candidates)):
    return None
  return canonical_seats(candidates)


def issue_response(state):
  return {
    "allowed": True,
    "permit_id": state["permit_id"],
    "snapshot_path": state["snapshot_path"],
    "expires_at": state["expires_at"],
    "lenses": state["remaining_lenses"],
    "seats": state.get("authorized_seats", []),
    "vendor": state["vendor"],
    "expected_opus_model": state["expected_opus_model"],
    "expected_fable_model": state["expected_fable_model"],
  }


def issue(args):
  if args.ttl <= 0:
    deny("invalid-ttl")
  if args.max_command_age <= 0:
    deny("invalid-max-command-age")
  session = args.session
  transcript, transcript_bytes = resolve_transcript(session)
  spec = Path(os.path.abspath(os.path.expanduser(args.spec)))
  if not trusted_parent_chain(spec):
    deny("untrusted-spec")
  authorization = find_authorization(load_records(transcript_bytes), session, allow_followup=True)
  current = now_utc()
  if authorization["command_time"] - current > timedelta(minutes=5):
    deny("authorization-in-future")
  if current - authorization["command_time"] > timedelta(seconds=args.max_command_age):
    deny("authorization-stale")
  expected_spec = authorization["expected_spec"]
  if expected_spec is not None and expected_spec != spec:
    deny("spec-path-mismatch")
  binding = current_model_binding()

  root = runtime_dir()
  cleanup_runtime(root, current, session)
  state_path = session_path(root, session)
  with locked(root, session):
    previous = read_json(state_path) if state_path.exists() else None
    if previous is not None:
      validate_state_schema(previous)
    tombstone_path = spent_command_path(session, authorization["command_uuid"])
    if previous is not None and previous.get("command_uuid") == authorization["command_uuid"]:
      require_current_model_binding(previous)
      validate_state(root, state_path, previous, current)
      if not tombstone_path.exists():
        created = spend_command(session, authorization, current)
        if created is None:
          deny("command-already-issued")
      emit(issue_response(previous))
    if tombstone_path.exists():
      deny("command-already-issued")
    if authorization["superseded"]:
      deny("authorization-superseded")
    if previous is not None:
      remove_packet_files(root, previous)

    spec_bytes = read_owned_file(spec, "untrusted-spec")
    permit_id = secrets.token_hex(16)
    snapshot_path = root / f"{session}.{permit_id}.snapshot"
    try:
      create_snapshot(spec_bytes, snapshot_path)
    except OSError:
      snapshot_path.unlink(missing_ok=True)
      deny("spec-unreadable")
    expires = current + timedelta(seconds=args.ttl)
    state = {
      "version": 1,
      "permit_id": permit_id,
      "session_id": session,
      "transcript_path": str(transcript),
      "command_uuid": authorization["command_uuid"],
      "spec_path": str(spec),
      "snapshot_path": str(snapshot_path),
      "issued_at": isoformat(current),
      "expires_at": isoformat(expires),
      "vendor": binding["vendor"],
      "expected_opus_model": binding["expected_opus_model"],
      "expected_fable_model": binding["expected_fable_model"],
      "finalized": False,
      "authorized_lenses": [],
      "remaining_lenses": list(LENSES),
      "authorized_seats": [],
      "selection_event_uuid": "",
      "recommendation_event_uuid": "",
    }
    try:
      atomic_write(state_path, state)
    except OSError:
      snapshot_path.unlink(missing_ok=True)
      deny("permit-write-failed")
    try:
      created = spend_command(session, authorization, current)
    except SystemExit:
      if previous is None:
        state_path.unlink(missing_ok=True)
      else:
        atomic_write(state_path, previous)
      snapshot_path.unlink(missing_ok=True)
      raise
    if created is None:
      if previous is None:
        state_path.unlink(missing_ok=True)
      else:
        atomic_write(state_path, previous)
      snapshot_path.unlink(missing_ok=True)
      deny("command-already-issued")
    if previous is not None:
      previous_snapshot = Path(previous.get("snapshot_path", ""))
      if previous_snapshot.parent == root and previous_snapshot != snapshot_path:
        previous_snapshot.unlink(missing_ok=True)

  emit(issue_response(state))


def validate_state(root, state_path, state, current):
  snapshot_path = Path(state.get("snapshot_path", ""))
  try:
    expires_at = parse_time(state.get("expires_at", ""))
  except (AttributeError, TypeError, ValueError):
    deny("invalid-permit-state")
  if expires_at <= current:
    remove_packet_files(root, state)
    if snapshot_path.parent == root:
      snapshot_path.unlink(missing_ok=True)
    state_path.unlink(missing_ok=True)
    deny("permit-expired")
  if snapshot_path.parent != root:
    deny("snapshot-missing")
  try:
    descriptor = os.open(snapshot_path, os.O_RDONLY | os.O_NOFOLLOW)
  except OSError:
    deny("snapshot-missing")
  try:
    metadata = os.fstat(descriptor)
    if metadata.st_uid != os.getuid() or not stat.S_ISREG(metadata.st_mode):
      deny("untrusted-snapshot")
    if stat.S_IMODE(metadata.st_mode) & 0o277:
      deny("snapshot-permissions")
    with os.fdopen(descriptor, "rb") as handle:
      descriptor = -1
      artifact_bytes = handle.read()
  finally:
    if descriptor >= 0:
      os.close(descriptor)
  return artifact_bytes


def finalize_selection(args):
  raw_seats = []
  if args.seats is not None:
    raw_seats.extend(args.seats.split(","))
  raw_seats.extend(args.seat or [])
  if raw_seats:
    parsed = []
    for value in raw_seats:
      seat = parse_seat(value.strip())
      if seat is None:
        deny("invalid-seat-selection")
      parsed.append(seat)
    if len(parsed) != len(set(parsed)):
      deny("invalid-seat-selection")
    selected = canonical_seats(parsed)
    if not selected or len(selected) != len(parsed):
      deny("invalid-seat-selection")
    return selected
  if args.lenses is None:
    deny("selection-required")
  requested = args.lenses.split(",")
  if not requested or any(lens not in LENSES for lens in requested) or len(requested) != len(set(requested)):
    deny("invalid-lens-selection")
  return seats_for_lenses(requested)


def finalize(args):
  seat_selection = args.seats is not None or bool(args.seat)
  selected_seats = finalize_selection(args)
  selected_lenses = lenses_for_seats(selected_seats)
  session = args.session
  transcript, transcript_bytes = resolve_transcript(session)
  current = now_utc()
  root = runtime_dir()
  cleanup_runtime(root, current, session)
  state_path = session_path(root, session)
  with locked(root, session):
    if not state_path.exists():
      deny("permit-missing")
    state = read_json(state_path)
    validate_state_schema(state)
    require_current_model_binding(state)
    if state.get("session_id") != session or state.get("transcript_path") != str(transcript):
      deny("permit-context-mismatch")
    validate_state(root, state_path, state, current)
    if state["finalized"]:
      deny("permit-already-finalized")
    selection_uuid = ""
    selection_text = ""
    recommendation_uuid = ""
    recommendation_seats = []
    records = load_records(transcript_bytes)
    selection_uuid, selection_text, selection_index = find_selection_event(
      records,
      session,
      state["command_uuid"],
      args.selection_event,
    )
    if seat_selection or args.recommendation_event:
      recommendation_uuid, recommendation_seats = find_recommendation_event(
        records,
        session,
        state["command_uuid"],
        selection_index,
        args.recommendation_event,
        state["permit_id"],
      )
    follow_recommendation = args.follow_recommendation or selection_text.strip().rstrip("。") == "照推薦"
    if follow_recommendation:
      if not recommendation_seats or selected_seats != recommendation_seats:
        deny("recommendation-selection-mismatch")
    else:
      parsed_user_seats = parse_user_selection_seats(selection_text)
      if parsed_user_seats is None or parsed_user_seats != selected_seats:
        deny("selection-mismatch")
    state["finalized"] = True
    state["authorized_lenses"] = selected_lenses
    state["remaining_lenses"] = canonical_lenses(
      seat.split(":", 1)[0] for seat in fable_seats_for_seats(selected_seats)
    )
    state["authorized_seats"] = selected_seats
    state["selection_event_uuid"] = selection_uuid
    state["recommendation_event_uuid"] = recommendation_uuid
    try:
      atomic_write(state_path, state)
    except OSError:
      deny("permit-write-failed")
  emit({"allowed": True, "reason": "permit-finalized", "lenses": selected_lenses, "seats": selected_seats})


def packet(args):
  session = args.session
  transcript, _ = resolve_transcript(session)
  current = now_utc()
  root = runtime_dir()
  cleanup_runtime(root, current, session)
  state_path = session_path(root, session)
  with locked(root, session):
    if not state_path.exists():
      deny("permit-missing")
    state = read_json(state_path)
    validate_state_schema(state)
    require_current_model_binding(state)
    if state.get("session_id") != session or state.get("transcript_path") != str(transcript):
      deny("permit-context-mismatch")
    artifact_bytes = validate_state(root, state_path, state, current)
    if not state["finalized"]:
      deny("permit-not-finalized")
    if args.lens not in state["authorized_lenses"]:
      deny("lens-not-authorized")
    if seat_key(args.lens, args.model) not in state["authorized_seats"]:
      deny("seat-not-authorized")
    if args.model == "fable" and args.lens not in state["remaining_lenses"]:
      deny("lens-already-consumed")
    value = build_packet(state, args.lens, artifact_bytes)
    if args.reference:
      payload = canonical_reference_packet(value).encode("utf-8")
      path = packet_path(root, state, args.lens)
      try:
        atomic_write_bytes(path, payload)
      except OSError:
        deny("packet-write-failed")
      print(build_packet_reference(state, args.lens, path))
      return
    print(value)


def validate_receipt(root, state, session, receipt_value):
  expected_path = root / f"{session}.{state['permit_id']}.receipt"
  supplied_path = Path(os.path.abspath(os.path.expanduser(receipt_value)))
  if supplied_path != expected_path:
    deny("receipt-missing")
  data = read_owned_file(supplied_path, "receipt-missing", private=True)
  try:
    receipt = json.loads(data)
  except (UnicodeDecodeError, json.JSONDecodeError):
    deny("receipt-invalid")
  if not isinstance(receipt, dict):
    deny("receipt-invalid")
  expected = {
    "version": 1,
    "session_id": session,
    "permit_id": state["permit_id"],
    "lenses": state["authorized_lenses"],
  }
  if any(receipt.get(key) != value for key, value in expected.items()):
    deny("receipt-mismatch")
  authorized_seats = state.get("authorized_seats", seats_for_lenses(state["authorized_lenses"]))
  receipt_seats = receipt.get("seats")
  if receipt_seats is None:
    receipt_pairs = receipt.get("pairs")
    if not isinstance(receipt_pairs, list) or any(not isinstance(pair, str) for pair in receipt_pairs):
      deny("receipt-invalid")
    receipt_seats = []
    for pair in receipt_pairs:
      parts = pair.split(":")
      if len(parts) != 3 or parts[0] not in LENSES or not AGENT_ID_RE.fullmatch(parts[1]) or not AGENT_ID_RE.fullmatch(parts[2]):
        deny("receipt-invalid")
      receipt_seats.extend((f"{parts[0]}:opus:{parts[1]}", f"{parts[0]}:fable:{parts[2]}"))
  if not isinstance(receipt_seats, list) or any(not isinstance(seat, str) for seat in receipt_seats):
    deny("receipt-invalid")
  parsed_seats = []
  for value in receipt_seats:
    parts = value.split(":")
    if len(parts) != 3 or parse_seat(f"{parts[0]}:{parts[1]}") is None or not AGENT_ID_RE.fullmatch(parts[2]):
      deny("receipt-invalid")
    parsed_seats.append(value)
  expected_seat_keys = canonical_seats(authorized_seats)
  if [seat.split(":", 2)[:2] for seat in parsed_seats] != [seat.split(":", 2)[:2] for seat in expected_seat_keys]:
    deny("receipt-mismatch")
  if len({seat.split(":", 2)[2] for seat in parsed_seats}) != len(parsed_seats):
    deny("receipt-invalid")
  pairs = receipt.get("pairs")
  if not isinstance(pairs, list) or any(not isinstance(pair, str) for pair in pairs):
    deny("receipt-invalid")
  expected_pairs = []
  by_seat = {tuple(value.split(":", 2)[:2]): value.split(":", 2)[2] for value in parsed_seats}
  for lens in lenses_for_seats(authorized_seats):
    opus_id = by_seat.get((lens, "opus"))
    fable_id = by_seat.get((lens, "fable"))
    if opus_id is not None and fable_id is not None:
      expected_pairs.append(f"{lens}:{opus_id}:{fable_id}")
  if pairs != expected_pairs:
    deny("receipt-mismatch")
  try:
    verified_at = parse_time(receipt.get("verified_at", ""))
    issued_at = parse_time(state["issued_at"])
    expires_at = parse_time(state["expires_at"])
  except (AttributeError, TypeError, ValueError):
    deny("receipt-invalid")
  if verified_at < issued_at or verified_at > expires_at:
    deny("receipt-invalid")
  return supplied_path, pairs, [f"{lens}:{model}:{agent_id}" for lens, model, agent_id in (value.split(":", 2) for value in parsed_seats)]


def verify_receipt_again(state, pairs, seats):
  command = [
    sys.executable,
    str(Path(__file__).with_name("review-spec-dual-verify.py")),
    "--session",
    state["session_id"],
    "--permit-id",
    state["permit_id"],
    "--expires-at",
    state["expires_at"],
    "--snapshot",
    state["snapshot_path"],
    "--check-only",
  ]
  if seats:
    for seat in seats:
      command.extend(("--seat", seat))
  else:
    for pair in pairs:
      command.extend(("--pair", pair))
  try:
    completed = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
  except (OSError, subprocess.TimeoutExpired):
    return False
  if completed.returncode != 0:
    return False
  try:
    payload = json.loads(completed.stdout)
  except json.JSONDecodeError:
    return False
  return isinstance(payload, dict) and payload.get("valid") is True


def close(args):
  session = args.session
  transcript, _ = resolve_transcript(session)
  current = now_utc()
  root = runtime_dir()
  cleanup_runtime(root, current, session)
  state_path = session_path(root, session)
  with locked(root, session):
    if not state_path.exists():
      deny("permit-missing")
    state = read_json(state_path)
    validate_state_schema(state)
    if state.get("session_id") != session or state.get("transcript_path") != str(transcript):
      deny("permit-context-mismatch")
    if state["permit_id"] != args.permit_id:
      deny("permit-id-mismatch")
    if not state["finalized"]:
      deny("permit-not-finalized")
    if state["remaining_lenses"]:
      deny("lenses-incomplete")
    receipt_path, pairs, seats = validate_receipt(root, state, session, args.receipt)
    if not verify_receipt_again(state, pairs, seats):
      deny("receipt-verification-failed")
    snapshot_path = Path(state["snapshot_path"])
    remove_packet_files(root, state)
    state_path.unlink(missing_ok=True)
    receipt_path.unlink(missing_ok=True)
    if same_directory(snapshot_path.parent, root):
      snapshot_path.unlink(missing_ok=True)
  emit({"allowed": True, "reason": "permit-closed"})


def consume():
  try:
    payload = json.load(sys.stdin)
  except json.JSONDecodeError:
    deny("invalid-hook-payload")
  if not isinstance(payload, dict):
    deny("invalid-hook-payload")

  session = payload.get("session_id")
  transcript_value = payload.get("transcript_path")
  tool_input = payload.get("tool_input")
  if not isinstance(session, str) or not isinstance(transcript_value, str):
    deny("hook-context-missing")
  if not isinstance(tool_input, dict):
    deny("tool-input-missing")
  if payload.get("tool_name") not in {"Agent", "Task"}:
    deny("wrong-tool")
  if tool_input.get("subagent_type") != "architecture-critic" or tool_input.get("model") != "fable":
    deny("wrong-agent-or-model")

  description = tool_input.get("description")
  prompt = tool_input.get("prompt")
  if not isinstance(description, str) or not isinstance(prompt, str):
    deny("agent-fields-missing")
  matches = MARKER_RE.findall(description)
  if len(matches) != 1:
    deny("malformed-marker")
  permit_id, lens = matches[0]

  transcript, _ = resolve_transcript(session)
  supplied_transcript = Path(os.path.abspath(os.path.expanduser(transcript_value)))
  if transcript != supplied_transcript:
    deny("permit-context-mismatch")
  current = now_utc()
  root = runtime_dir()
  cleanup_runtime(root, current, session)
  state_path = session_path(root, session)
  with locked(root, session):
    if not state_path.exists():
      deny("permit-missing")
    state = read_json(state_path)
    validate_state_schema(state)
    require_current_model_binding(state)
    if state.get("session_id") != session or state.get("transcript_path") != str(transcript):
      deny("permit-context-mismatch")
    artifact_bytes = validate_state(root, state_path, state, current)
    if state.get("permit_id") != permit_id:
      deny("permit-id-mismatch")
    if not state["finalized"]:
      deny("permit-not-finalized")
    if lens not in state["authorized_lenses"]:
      deny("lens-not-authorized")
    if seat_key(lens, "fable") not in state["authorized_seats"]:
      deny("seat-not-authorized")
    expected_packet = build_packet(state, lens, artifact_bytes)
    if not prompt.startswith(expected_packet):
      if not prompt.startswith("REVIEW_SPEC_PACKET_PATH="):
        deny("prompt-packet-mismatch")
      path = packet_path(root, state, lens)
      packet_bytes = read_owned_file(path, "packet-file-missing", private=True)
      expected_bytes = canonical_reference_packet(expected_packet).encode("utf-8")
      if packet_bytes != expected_bytes:
        deny("packet-file-mismatch")
      expected_reference = build_packet_reference(state, lens, path)
      if not prompt.startswith(expected_reference):
        deny("prompt-packet-mismatch")
    remaining = state.get("remaining_lenses")
    if not isinstance(remaining, list) or lens not in remaining:
      deny("lens-already-consumed")
    remaining.remove(lens)
    state["remaining_lenses"] = remaining
    try:
      atomic_write(state_path, state)
    except OSError:
      deny("permit-write-failed")

  emit(
    {
      "allowed": True,
      "reason": "permit-consumed",
      "lens": lens,
      "remaining": len(remaining),
    }
  )


def parser():
  root = argparse.ArgumentParser()
  subparsers = root.add_subparsers(dest="action", required=True)
  issue_parser = subparsers.add_parser("issue")
  issue_parser.add_argument("--session", required=True)
  issue_parser.add_argument("--spec", required=True)
  issue_parser.add_argument("--ttl", type=int, default=7200)
  issue_parser.add_argument("--max-command-age", type=int, default=14400)
  finalize_parser = subparsers.add_parser("finalize")
  finalize_parser.add_argument("--session", required=True)
  finalize_parser.add_argument("--lenses")
  finalize_parser.add_argument("--seats")
  finalize_parser.add_argument("--seat", action="append")
  finalize_parser.add_argument("--selection-event")
  finalize_parser.add_argument("--recommendation-event")
  finalize_parser.add_argument("--follow-recommendation", action="store_true")
  packet_parser = subparsers.add_parser("packet")
  packet_parser.add_argument("--session", required=True)
  packet_parser.add_argument("--lens", choices=sorted(LENSES), required=True)
  packet_parser.add_argument("--model", choices=sorted(MODELS), default="fable")
  packet_parser.add_argument("--reference", action="store_true")
  close_parser = subparsers.add_parser("close")
  close_parser.add_argument("--session", required=True)
  close_parser.add_argument("--permit-id", required=True)
  close_parser.add_argument("--receipt", required=True)
  subparsers.add_parser("consume")
  return root


def main():
  args = parser().parse_args()
  if args.action == "issue":
    issue(args)
  if args.action == "finalize":
    finalize(args)
  if args.action == "packet":
    packet(args)
    return
  if args.action == "close":
    close(args)
  consume()


if __name__ == "__main__":
  main()
