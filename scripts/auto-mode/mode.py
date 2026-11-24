#!/usr/bin/env python3
import argparse
import errno
import fcntl
import importlib.util
import json
import os
import re
import secrets
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

STATE_DIR = Path.home() / ".claude" / "logs" / "auto-mode" / "modes"
TERMINAL_RE = re.compile(r"[A-Za-z0-9_/-]{1,72}")
SLASH_RE = re.compile(
  r"^(?:/auto-(on|off)"
  r"|<command-name>/auto-(on|off)</command-name>"
  r"|<command-message>auto-(on|off)</command-message>\n<command-name>/auto-\3</command-name>"
  r"(?:\n<command-args></command-args>)?)$"
)


class CorruptState(Exception):
  pass


class PiModeUnavailable(Exception):
  pass


class _FallbackPiMode:
  # Self-contained fallback when sibling pi-subtask/mode.py is absent in standalone checkouts.
  EVENT_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
  )

  class UsageError(Exception):
    def __init__(self, reason="usage-error"):
      super().__init__(reason)
      self.reason = reason

  class Blocked(Exception):
    def __init__(self, reason="blocked"):
      super().__init__(reason)
      self.reason = reason

  def parse_session(self, session):
    if not isinstance(session, str) or not self.EVENT_UUID_RE.fullmatch(session):
      raise self.UsageError("bad-session")
    return session.lower()

  def same_session(self, a, b):
    try:
      return self.parse_session(a) == self.parse_session(b)
    except self.UsageError:
      return False

  def child_caller(self):
    return bool(os.environ.get("CLAUDE_AGENT_ID"))

  def open_nofollow(self, path):
    try:
      info = os.lstat(path)
    except FileNotFoundError as error:
      raise self.Blocked("transcript-missing") from error
    except OSError as error:
      raise self.Blocked("transcript-unsafe") from error
    if stat.S_ISLNK(info.st_mode) or stat.S_ISFIFO(info.st_mode) or not stat.S_ISREG(info.st_mode):
      raise self.Blocked("transcript-unsafe")
    if info.st_nlink != 1 or info.st_uid != os.getuid():
      raise self.Blocked("transcript-unsafe")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
      finfo = os.fstat(descriptor)
      if not stat.S_ISREG(finfo.st_mode) or finfo.st_nlink != 1 or finfo.st_uid != os.getuid():
        raise self.Blocked("transcript-unsafe")
    except BaseException:
      os.close(descriptor)
      raise
    return descriptor

  def find_transcripts(self, expected_uuid, projects_dir):
    root = Path(projects_dir)
    try:
      if not root.is_dir():
        return []
    except OSError:
      return []
    target_name = f"{expected_uuid.lower()}.jsonl"
    matches = []
    stack = [root]
    while stack:
      current = stack.pop()
      try:
        with os.scandir(current) as entries:
          for entry in entries:
            if entry.is_symlink():
              continue
            if entry.is_dir(follow_symlinks=False):
              stack.append(Path(entry.path))
            elif entry.is_file(follow_symlinks=False) and entry.name.lower() == target_name:
              matches.append(Path(entry.path))
      except OSError:
        continue
    return sorted(matches)

  def check_event_session(self, row, expected):
    if "sessionId" not in row:
      return False
    sid = row.get("sessionId")
    if not isinstance(sid, str) or not self.same_session(sid, expected):
      raise self.Blocked("transcript-session-mismatch")
    return True

  def is_pi_human(self, row):
    if row.get("isMeta") or row.get("isSidechain") or row.get("isCompactSummary"):
      return False
    if row.get("compactMetadata") is not None:
      return False
    if row.get("turnOrigin") not in (None, "human"):
      return False
    origin = row.get("origin")
    if origin is not None and (not isinstance(origin, dict) or origin.get("kind") != "human"):
      return False
    message = row.get("message")
    if isinstance(message, dict) and message.get("role") != "user":
      return False
    return True

  def message_text(self, row):
    message = row.get("message")
    if not isinstance(message, dict):
      return "", False
    content = message.get("content")
    if isinstance(content, str):
      return content, True
    if isinstance(content, list) and content:
      parts = []
      for item in content:
        if not isinstance(item, dict) or item.get("type") != "text" or not isinstance(item.get("text"), str):
          return "", False
        parts.append(item["text"])
      return "\n".join(parts), True
    return "", False

  def open_root(self, root, create):
    root_path = Path(root)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
      dirfd = os.open(root_path, flags)
    except FileNotFoundError:
      if not create:
        return None
      raise self.Blocked("root-unsafe")
    except OSError as exc:
      if exc.errno in (errno.ELOOP, errno.ENOTDIR):
        raise self.Blocked("state-unsafe") from exc
      raise
    try:
      info = os.fstat(dirfd)
      if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or (stat.S_IMODE(info.st_mode) & 0o077):
        raise self.Blocked("root-unsafe")
      return dirfd
    except BaseException:
      os.close(dirfd)
      raise


def load_pi_mode():
  override = os.environ.get("AUTO_MODE_PI_MODULE")
  path = Path(override) if override else Path(__file__).resolve().parents[1] / "pi-subtask" / "mode.py"
  if path.exists():
    spec = importlib.util.spec_from_file_location("pi_subtask_mode", path)
    if spec is None or spec.loader is None:
      raise PiModeUnavailable(f"cannot load pi-subtask mode module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
  return _FallbackPiMode()


def state_key(pi, session, terminal=None):
  terminal = os.environ.get("HC_TERMINAL_ID") if terminal is None else terminal
  if terminal is not None and not isinstance(terminal, str):
    raise pi.UsageError("bad-terminal")
  if terminal:
    if not TERMINAL_RE.fullmatch(terminal):
      raise pi.UsageError("bad-terminal")
    return f"terminal-{quote(terminal, safe='')}"
  return f"session-{pi.parse_session(session)}"


def parse_timestamp(value):
  if not isinstance(value, str):
    return None
  try:
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return timestamp.astimezone(timezone.utc) if timestamp.tzinfo is not None else None
  except (ValueError, OverflowError):
    return None


def latest_toggle(pi, session):
  expected = pi.parse_session(session)
  active = os.environ.get("CLAUDE_SESSION_ID")
  if active and not pi.same_session(active, expected):
    raise pi.Blocked("transcript-session-mismatch")
  config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
  # Team profiles can share the canonical projects directory through a symlink.
  projects = (config / "projects").resolve()
  matches = pi.find_transcripts(str(expected), projects)
  if len(matches) != 1:
    raise pi.Blocked("transcript-missing" if not matches else "transcript-ambiguous")
  latest = None
  with os.fdopen(pi.open_nofollow(matches[0]), "rb") as handle:
    for raw_line in handle:
      try:
        row = json.loads(raw_line.decode("utf-8"))
      except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        continue
      if not isinstance(row, dict) or not pi.check_event_session(row, expected):
        continue
      if row.get("type") != "user" or not pi.is_pi_human(row):
        continue
      text, pure = pi.message_text(row)
      found = SLASH_RE.fullmatch(text.strip()) if pure else None
      event_id = row.get("uuid")
      if found and isinstance(event_id, str) and pi.EVENT_UUID_RE.fullmatch(event_id):
        enabled = next(group for group in found.groups() if group) == "on"
        latest = enabled, event_id.lower(), parse_timestamp(row.get("timestamp"))
  return latest


def read_json(pi, dirfd, filename):
  descriptor = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dirfd)
  with os.fdopen(descriptor, encoding="utf-8") as handle:
    info = os.fstat(handle.fileno())
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600):
      raise pi.Blocked("state-unsafe")
    try:
      return json.load(handle)
    except (ValueError, RecursionError) as error:
      raise CorruptState from error


def read_state(pi, dirfd, filename):
  try:
    data = read_json(pi, dirfd, filename)
  except FileNotFoundError:
    return False, [], None
  if not isinstance(data, dict) or set(data) - {"recovered_at"} != {"enabled", "applied_events"}:
    raise CorruptState
  events = data["applied_events"]
  recovered_at = parse_timestamp(data.get("recovered_at"))
  if (type(data["enabled"]) is not bool or not isinstance(events, list)
      or any(not isinstance(event, str) or not pi.EVENT_UUID_RE.fullmatch(event) for event in events)
      or ("recovered_at" in data and recovered_at is None)):
    raise CorruptState
  return data["enabled"], [event.lower() for event in events], recovered_at


def write_json(dirfd, filename, payload):
  temporary = f".{filename}.{secrets.token_hex(8)}.tmp"
  descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dirfd)
  try:
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
      os.fchmod(handle.fileno(), 0o600)
      json.dump(payload, handle)
      handle.write("\n")
      handle.flush()
      os.fsync(handle.fileno())
    os.replace(temporary, filename, src_dir_fd=dirfd, dst_dir_fd=dirfd)
    os.fsync(dirfd)
  finally:
    try:
      os.unlink(temporary, dir_fd=dirfd)
    except FileNotFoundError:
      pass


def write_state(dirfd, filename, enabled, events, recovered_at):
  payload = {"enabled": enabled, "applied_events": events}
  if recovered_at is not None:
    payload["recovered_at"] = recovered_at.isoformat()
  write_json(dirfd, filename, payload)


def _ensure_private_tree(pi, root_path):
  # Under restrictive umask (e.g. 0o177), Path.mkdir(parents=True, mode=0o700) creates
  # intermediate dirs as 0o600 (missing +x), causing child mkdir to fail with EACCES.
  missing = []
  cur = root_path
  while cur != cur.parent:
    try:
      info = cur.lstat()
      if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise pi.Blocked("root-unsafe")
      break
    except FileNotFoundError:
      missing.append(cur)
      cur = cur.parent
    except OSError as error:
      raise pi.Blocked("root-unsafe") from error
  for directory in reversed(missing):
    try:
      os.mkdir(directory, 0o700)
    except FileExistsError:
      continue
    except OSError as error:
      raise pi.Blocked("root-unsafe") from error
    dirfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
      info = os.fstat(dirfd)
      if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise pi.Blocked("root-unsafe")
      os.fchmod(dirfd, 0o700)
    finally:
      os.close(dirfd)


def open_root(pi, create, *, root=STATE_DIR):
  root_path = Path(root)
  if create and not root_path.exists():
    _ensure_private_tree(pi, root_path)
  try:
    return pi.open_root(root, create)
  except pi.Blocked as error:
    # The other writer may have just created the directory on first use.
    if create and isinstance(error.__cause__, FileExistsError):
      return pi.open_root(root, False)
    raise


def lock_state(pi, dirfd, key, *, shared=False):
  name = f"{key}.lock"
  flags = os.O_NOFOLLOW | os.O_NONBLOCK
  try:
    # On macOS concurrent non-exclusive O_CREAT with O_NOFOLLOW can return ENOENT.
    descriptor = os.open(name, flags | os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=dirfd)
    try:
      os.fchmod(descriptor, 0o600)
    except BaseException:
      os.close(descriptor)
      raise
  except FileExistsError:
    descriptor = os.open(name, flags | (os.O_RDONLY if shared else os.O_RDWR), dir_fd=dirfd)
  lock = os.fdopen(descriptor, "rb")
  try:
    info = os.fstat(descriptor)
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600):
      raise pi.Blocked("state-unsafe")
    fcntl.flock(descriptor, fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
    return lock
  except BaseException:
    lock.close()
    raise


def view(key, enabled=False, events=()):
  return {"key": key, "enabled": enabled, "source_event": events[-1] if events else None}


def status(pi, key):
  try:
    dirfd = open_root(pi, False)
    if dirfd is not None:
      try:
        enabled, events, _ = read_state(pi, dirfd, f"{key}.json")
        return view(key, enabled, events)
      finally:
        os.close(dirfd)
  except (OSError, pi.Blocked, CorruptState):
    pass
  return view(key)


def mutate(pi, key, command, session):
  dirfd = open_root(pi, True)
  try:
    with lock_state(pi, dirfd, key):
      filename = f"{key}.json"
      try:
        enabled, events, recovered_at = read_state(pi, dirfd, filename)
      except CorruptState:
        recovered_at = datetime.now(timezone.utc)
        if command != "sync":
          enabled = command == "on"
          write_state(dirfd, filename, enabled, [], recovered_at)
          return view(key, enabled)
        latest = latest_toggle(pi, session)
        if latest is None:
          return view(key)
        next_enabled, event_id, timestamp = latest
        # The lost history cannot tell which toggles typed before the file broke were applied,
        # but one typed after the last write cannot have been, so the /auto-on that asked for
        # this rebuild still takes effect instead of needing a second /auto-on.
        broken_at = datetime.fromtimestamp(os.stat(filename, dir_fd=dirfd, follow_symlinks=False).st_mtime, timezone.utc)
        applied = [event_id] if timestamp is not None and timestamp > broken_at else []
        enabled = next_enabled if applied else False
        write_state(dirfd, filename, enabled, applied, recovered_at)
        return view(key, enabled, applied)
      if command == "sync":
        latest = latest_toggle(pi, session)
        if latest is None:
          return view(key, enabled, events)
        next_enabled, event_id, timestamp = latest
        if event_id in events or (recovered_at is not None and (timestamp is None or timestamp <= recovered_at)):
          return view(key, enabled, events)
        enabled = next_enabled
        events.append(event_id)
      else:
        enabled = command == "on"
      write_state(dirfd, filename, enabled, events, recovered_at)
      return view(key, enabled, events)
  finally:
    os.close(dirfd)


def main():
  parser = argparse.ArgumentParser(allow_abbrev=False,
                                   description="Read or change the human-controlled auto mode switch.")
  parser.add_argument("command", choices=("status", "sync", "on", "off"))
  parser.add_argument("--session", default=os.environ.get("CLAUDE_SESSION_ID"))
  parser.add_argument("--source", choices=("button",), help="required for on and off from Herdr")
  args = parser.parse_args()
  # Status must not create a bytecode cache through the shared helpers.
  sys.dont_write_bytecode = True
  try:
    pi = load_pi_mode()
  except PiModeUnavailable:
    print(json.dumps({"enabled": False, "error": "pi-mode-unavailable"}))
    return 1
  try:
    if pi.child_caller() and args.command != "status":
      raise pi.Blocked("child-caller")
    button = args.command in {"on", "off"}
    if button != (args.source == "button") or (button and not os.environ.get("HC_TERMINAL_ID")):
      raise pi.UsageError("button-source-and-terminal-required-for-direct-write")
    key = state_key(pi, args.session)
    payload = status(pi, key) if args.command == "status" else mutate(pi, key, args.command, args.session)
  except (pi.Blocked, pi.UsageError, OSError, ValueError, RuntimeError) as error:
    print(json.dumps({"enabled": False, "error": getattr(error, "reason", "state-or-transcript-unavailable")}))
    return 1
  print(json.dumps(payload))
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
