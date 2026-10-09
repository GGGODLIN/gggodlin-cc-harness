#!/usr/bin/env python3
import argparse
import json
import os
import re
import stat
import sys
import tempfile
from collections import deque
from pathlib import Path


SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SKILL_RE = re.compile(r"^[A-Za-z0-9._:@/-]{1,128}$")
TOOL_USE_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,256}$")
SYSTEM_BLOCK_RE = re.compile(
  r"<(?:system-reminder|task-notification)\b[^>]*>.*?</(?:system-reminder|task-notification)>",
  re.IGNORECASE | re.DOTALL,
)
GENERATED_ENVELOPE_RE = re.compile(
  r"^\s*<(?:bash-input|bash-stdout|local-command-caveat|local-command-stdout|command-message|command-name|scheduled-task|task-notification|teammate-message)\b",
  re.IGNORECASE,
)
ASSIGNMENT_RE = re.compile(
  r"(?<![A-Za-z0-9_.-])([A-Za-z][A-Za-z0-9_.-]{0,127})\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
PRIVATE_KEY_RE = re.compile(
  r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
  re.DOTALL,
)
BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
BASIC_RE = re.compile(r"\bBasic\s+[A-Za-z0-9+/=]{8,}", re.IGNORECASE)
EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![\w.-])")
TOKEN_RE = re.compile(
  r"\b(?:sk_(?:live|test)_[A-Za-z0-9_-]{6,}|sk-(?:ant|proj)-[A-Za-z0-9_-]{10,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{20,})\b"
)
JSON_SECRET_RE = re.compile(
  r"(?i)([\"'][A-Za-z0-9_.-]*(?:password|passwd|api[_-]?key|apikey|token|secret|private[_-]?key|privatekey)[A-Za-z0-9_.-]*[\"']\s*:\s*)([\"'])([^\"']*)([\"'])"
)
AUTHORIZATION_RE = re.compile(r"(?im)\bAuthorization\s*:\s*[^\r\n]+")
COOKIE_RE = re.compile(r"(?im)\b(?:Cookie|Set-Cookie)\s*:\s*[^\r\n]+")
URI_USERINFO_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)([^/\s:@]+):([^@/\s]+)@")
JWT_RE = re.compile(
  r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}(?![A-Za-z0-9_-])"
)
PHONE_RE = re.compile(r"(?<!\w)(?:\+\d{8,15}|\(?\d{2,4}\)?[- .]\d{3,4}[- .]\d{3,4})(?!\w)")
TIMESTAMP_RE = re.compile(
  r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$"
)
SENSITIVE_KEY_SUFFIXES = (
  "API_KEY",
  "ACCESS_KEY",
  "AUTH_TOKEN",
  "ACCESS_TOKEN",
  "REFRESH_TOKEN",
  "CLIENT_SECRET",
  "PRIVATE_KEY",
  "PASSWORD",
  "PASSWD",
  "SECRET",
  "TOKEN",
)
CORRECTION_MARKERS = (
  "/wait-what",
  "不對",
  "不是",
  "看不懂",
  "沒看懂",
  "你沒有",
  "跟丟",
  "白話",
  "重新講",
  "重講",
  "錯了",
  "wrong",
  "incorrect",
  "didn't",
  "did not",
)
MAX_RECORD_BYTES = 32 * 1024 * 1024
MAX_CONTEXT_ITEMS = 5
MAX_CONTEXT_CHARS = 600
MAX_SKILL_INVOKES = 1024


class PacketError(Exception):
  pass


def reject(code):
  raise PacketError(code)


def valid_session(value):
  return bool(SESSION_RE.fullmatch(value)) and value not in {".", ".."}


def valid_skill(value):
  if not SKILL_RE.fullmatch(value):
    return False
  return all(part not in {"", ".", ".."} for part in value.split("/"))


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
    and bool(mode & stat.S_IXUSR)
    and not mode & 0o022
  )


def trusted_file(path):
  try:
    metadata = path.lstat()
  except OSError:
    return False
  return (
    metadata.st_uid == os.getuid()
    and stat.S_ISREG(metadata.st_mode)
    and not stat.S_ISLNK(metadata.st_mode)
    and not stat.S_IMODE(metadata.st_mode) & 0o022
  )


def locate_transcript(session):
  root = Path.home() / ".claude" / "projects"
  if not trusted_directory(root):
    reject("untrusted-transcript-root")
  candidates = []
  try:
    projects = sorted(root.iterdir(), key=lambda item: item.name)
  except OSError:
    reject("transcript-scan-failed")
  for project in projects:
    try:
      project_metadata = project.lstat()
    except OSError:
      reject("transcript-scan-failed")
    if not trusted_directory(project):
      if stat.S_ISDIR(project_metadata.st_mode) or stat.S_ISLNK(project_metadata.st_mode):
        reject("untrusted-transcript-directory")
      continue
    candidate = project / f"{session}.jsonl"
    try:
      candidate_present = candidate.exists() or candidate.is_symlink()
    except OSError:
      reject("transcript-scan-failed")
    if candidate_present:
      if not trusted_file(candidate):
        reject("untrusted-transcript")
      candidates.append(candidate)
  if not candidates:
    reject("transcript-not-found")
  if len(candidates) != 1:
    reject("transcript-not-unique")
  return candidates[0]


def direct_user_text(record):
  if record.get("type") != "user" or record.get("userType") != "external":
    return None
  origin = record.get("origin")
  if isinstance(origin, dict) and origin.get("kind") == "task-notification":
    return None
  if record.get("promptSource") in {"system", "sdk"}:
    return None
  if record.get("isCompactSummary") or record.get("isVisibleInTranscriptOnly") or record.get("isMeta"):
    return None
  message = record.get("message")
  if not isinstance(message, dict) or message.get("role") != "user":
    return None
  content = message.get("content")
  if isinstance(content, str):
    return content
  if not isinstance(content, list):
    return None
  parts = []
  for item in content:
    if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
      parts.append(item["text"])
  return "\n".join(parts) if parts else None


def clean_user_text(value):
  if GENERATED_ENVELOPE_RE.search(value):
    return None
  text = SYSTEM_BLOCK_RE.sub(" ", value).strip()
  return text or None


def sensitive_assignment(match):
  key = re.sub(r"[^A-Za-z0-9]+", "_", match.group(1)).upper().strip("_")
  return any(key == suffix or key.endswith(f"_{suffix}") for suffix in SENSITIVE_KEY_SUFFIXES)


def sanitize_excerpt(value):
  def replace_assignment(match):
    if sensitive_assignment(match):
      return f"{match.group(1)}=[REDACTED]"
    return match.group(0)

  text = PRIVATE_KEY_RE.sub("[PRIVATE_KEY_REDACTED]", value)
  text = JSON_SECRET_RE.sub(
    lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]{match.group(4)}",
    text,
  )
  text = ASSIGNMENT_RE.sub(replace_assignment, text)
  text = AUTHORIZATION_RE.sub("Authorization: [REDACTED]", text)
  text = COOKIE_RE.sub("Cookie: [REDACTED]", text)
  text = URI_USERINFO_RE.sub(lambda match: f"{match.group(1)}[REDACTED]:[REDACTED]@", text)
  text = BEARER_RE.sub("Bearer [REDACTED]", text)
  text = BASIC_RE.sub("Basic [REDACTED]", text)
  text = TOKEN_RE.sub("[REDACTED]", text)
  text = JWT_RE.sub("[JWT_REDACTED]", text)
  text = EMAIL_RE.sub("[EMAIL]", text)
  text = PHONE_RE.sub("[PHONE]", text)
  text = " ".join(text.split())
  if len(text) > MAX_CONTEXT_CHARS:
    return text[: MAX_CONTEXT_CHARS - 1] + "…"
  return text


def correction_candidate(value):
  lowered = value.casefold()
  return any(marker.casefold() in lowered for marker in CORRECTION_MARKERS)


def valid_timestamp(value):
  return isinstance(value, str) and len(value) <= 35 and bool(TIMESTAMP_RE.fullmatch(value))


def user_item(line_number, record):
  raw = direct_user_text(record)
  if raw is None:
    return None
  cleaned = clean_user_text(raw)
  if cleaned is None:
    return None
  if any(0xD800 <= ord(character) <= 0xDFFF for character in cleaned):
    reject("transcript-invalid-unicode")
  text = sanitize_excerpt(cleaned)
  if not text:
    return None
  item = {
    "record_index": line_number,
    "text": text,
    "correction_candidate": correction_candidate(cleaned),
  }
  timestamp = record.get("timestamp")
  if valid_timestamp(timestamp):
    item["timestamp"] = timestamp
  return item


def skill_invokes(line_number, record):
  if record.get("type") != "assistant":
    return []
  message = record.get("message")
  content = message.get("content") if isinstance(message, dict) else None
  if not isinstance(content, list):
    return []
  result = []
  for item in content:
    if not isinstance(item, dict) or item.get("type") != "tool_use" or item.get("name") != "Skill":
      continue
    tool_use_id = item.get("id")
    tool_input = item.get("input")
    skill = tool_input.get("skill") if isinstance(tool_input, dict) else None
    if not isinstance(tool_use_id, str) or not TOOL_USE_ID_RE.fullmatch(tool_use_id):
      continue
    if not isinstance(skill, str) or not valid_skill(skill):
      continue
    result.append(
      {
        "record_index": line_number,
        "skill": skill,
        "tool_use_id": tool_use_id,
      }
    )
  return result


def context_entry(kind, item):
  entry = {
    "correction_candidate": item["correction_candidate"],
    "kind": kind,
    "record_index": item["record_index"],
    "text": item["text"],
  }
  if "timestamp" in item:
    entry["timestamp"] = item["timestamp"]
  return entry


def final_context(target_found, source, corrections, tail, recent_before):
  if not target_found:
    return [context_entry("tail", item) for item in recent_before]
  selected = {}
  for item in tail:
    kind = "correction" if item["correction_candidate"] else "tail"
    selected[item["record_index"]] = (kind, item)
  if source is not None and len(selected) < MAX_CONTEXT_ITEMS:
    selected[source["record_index"]] = ("source", source)
  for item in corrections:
    if len(selected) >= MAX_CONTEXT_ITEMS:
      break
    selected.setdefault(item["record_index"], ("correction", item))
  return [context_entry(kind, item) for _, (kind, item) in sorted(selected.items())]


def extract_transcript(path, target_skill):
  flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
  try:
    descriptor = os.open(path, flags)
  except OSError:
    reject("transcript-read-failed")
  invokes = []
  distinct_skills = []
  seen_invokes = set()
  recent_before = deque(maxlen=3)
  corrections = []
  tail = deque(maxlen=2)
  source = None
  target_found = False
  try:
    before = os.fstat(descriptor)
    if before.st_uid != os.getuid() or not stat.S_ISREG(before.st_mode) or stat.S_IMODE(before.st_mode) & 0o022:
      reject("untrusted-transcript")
    with os.fdopen(descriptor, "rb") as handle:
      descriptor = -1
      line_number = 0
      while True:
        raw = handle.readline(MAX_RECORD_BYTES + 1)
        if not raw:
          break
        line_number += 1
        if len(raw) > MAX_RECORD_BYTES:
          reject("transcript-record-too-large")
        if not raw.strip():
          continue
        try:
          record = json.loads(raw)
        except (UnicodeDecodeError, ValueError, RecursionError):
          reject("transcript-invalid")
        if not isinstance(record, dict):
          reject("transcript-invalid")
        for invoke in skill_invokes(line_number, record):
          tool_use_id = invoke["tool_use_id"]
          if tool_use_id in seen_invokes:
            continue
          if len(invokes) >= MAX_SKILL_INVOKES:
            reject("too-many-skill-invokes")
          seen_invokes.add(tool_use_id)
          invokes.append(invoke)
          if invoke["skill"] not in distinct_skills:
            distinct_skills.append(invoke["skill"])
          if invoke["skill"] == target_skill and not target_found:
            target_found = True
            source = recent_before[-1] if recent_before else None
        item = user_item(line_number, record)
        if item is None:
          continue
        if not target_found:
          recent_before.append(item)
          continue
        tail.append(item)
        if item["correction_candidate"] and len(corrections) < 3:
          corrections.append(item)
      after = os.fstat(handle.fileno())
  except OSError:
    reject("transcript-read-failed")
  finally:
    if descriptor >= 0:
      try:
        os.close(descriptor)
      except OSError:
        pass
  if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
    reject("transcript-changed")
  return {
    "context": final_context(target_found, source, corrections, tail, recent_before),
    "distinct_skills": distinct_skills,
    "skill_invoked": target_found,
    "skill_invokes": invokes,
  }


def ensure_output_path(path):
  try:
    raw = Path(path).expanduser()
  except (OSError, RuntimeError, ValueError):
    reject("output-path-invalid")
  if not raw.is_absolute():
    reject("output-path-not-absolute")
  root = Path.home() / ".claude" / ".scratch"
  if not trusted_directory(root):
    reject("untrusted-output-root")
  try:
    parent = raw.parent.resolve(strict=True)
    root_resolved = root.resolve(strict=True)
    relative = parent.relative_to(root_resolved)
  except (OSError, ValueError):
    reject("output-outside-allowed-root")
  current = root_resolved
  if not trusted_directory(current):
    reject("untrusted-output-directory")
  for part in relative.parts:
    current = current / part
    if not trusted_directory(current):
      reject("untrusted-output-directory")
  target = parent / raw.name
  if target.exists() or target.is_symlink():
    if not trusted_file(target):
      reject("untrusted-output-file")
  return target


def atomic_write(path, payload):
  descriptor = -1
  temporary = None
  try:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
      descriptor = -1
      json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
      handle.write("\n")
      handle.flush()
      os.fsync(handle.fileno())
    os.replace(temporary, path)
    temporary = None
  except (OSError, UnicodeError, ValueError):
    reject("output-write-failed")
  finally:
    if descriptor >= 0:
      try:
        os.close(descriptor)
      except OSError:
        pass
    if temporary is not None:
      try:
        os.unlink(temporary)
      except OSError:
        pass


def build_packet(session, skill):
  transcript = locate_transcript(session)
  extracted = extract_transcript(transcript, skill)
  return {
    "bounds": {
      "max_context_chars": MAX_CONTEXT_CHARS,
      "max_context_items": MAX_CONTEXT_ITEMS,
      "max_skill_invokes": MAX_SKILL_INVOKES,
    },
    "context": extracted["context"],
    "context_is_untrusted": True,
    "distinct_skills": extracted["distinct_skills"],
    "owning_skill": skill,
    "schema_version": 1,
    "skill_invoked": extracted["skill_invoked"],
    "skill_invokes": extracted["skill_invokes"],
    "source_session": session,
  }


def parse_args(argv):
  parser = argparse.ArgumentParser()
  parser.add_argument("--session", required=True)
  parser.add_argument("--skill", required=True)
  parser.add_argument("--output", required=True)
  return parser.parse_args(argv)


def main(argv=None):
  args = parse_args(argv)
  try:
    if not valid_session(args.session):
      reject("invalid-session-id")
    if not valid_skill(args.skill):
      reject("invalid-skill-id")
    output = ensure_output_path(args.output)
    packet = build_packet(args.session, args.skill)
    atomic_write(output, packet)
  except PacketError as error:
    print(f"ERROR {error}", file=sys.stderr)
    return 2
  except OSError:
    print("ERROR io-failed", file=sys.stderr)
    return 2
  print(f"PACKET {output}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
