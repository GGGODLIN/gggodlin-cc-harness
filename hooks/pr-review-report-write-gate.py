#!/usr/bin/env python3

import json
import os
import re
import stat
import sys
import time
from pathlib import Path


CLAUDE_ROOT = Path(__file__).resolve().parent.parent
REPORT_ROOT = (CLAUDE_ROOT / "pr-review-reports").resolve()
LOG_PATH = CLAUDE_ROOT / "logs" / "pr-review-report-write-gate.jsonl"
REPORT_PATTERNS = (
  ("final", re.compile(r"pr-(\d+)-review\.md")),
  ("audit", re.compile(r"pr-(\d+)-review\.audit\.md")),
  ("draft", re.compile(r"pr-(\d+)-review\.audit\.draft\.md")),
)


def silent():
  print("{}")
  return 0


def report_kind(name):
  for index, candidate in enumerate((name, name.casefold())):
    for kind, pattern in REPORT_PATTERNS:
      match = pattern.fullmatch(candidate)
      if match:
        return kind, int(match.group(1)), index == 0
  return None


def lexical_path(payload, file_path):
  path = Path(file_path)
  if not path.is_absolute():
    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or not cwd:
      return None
    path = Path(cwd) / path
  return Path(os.path.abspath(path))


def is_canonical_draft(path):
  try:
    relative = path.relative_to(REPORT_ROOT)
  except ValueError:
    return False
  return len(relative.parts) == 2


def append_denial(payload, path, reason_code):
  row = {
    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "session_id": str(payload.get("session_id") or ""),
    "tool_name": str(payload.get("tool_name") or ""),
    "path": str(path),
    "reason_code": reason_code,
  }
  descriptor = -1
  try:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if LOG_PATH.is_symlink():
      raise OSError
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(LOG_PATH, flags, 0o600)
    metadata = os.fstat(descriptor)
    if (
      metadata.st_uid != os.getuid()
      or not stat.S_ISREG(metadata.st_mode)
      or metadata.st_nlink != 1
    ):
      raise OSError
    with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
      descriptor = -1
      handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
  except OSError:
    pass
  finally:
    if descriptor >= 0:
      os.close(descriptor)


def deny(payload, path, reason_code, reason):
  append_denial(payload, path, reason_code)
  print(json.dumps({
    "hookSpecificOutput": {
      "hookEventName": "PreToolUse",
      "permissionDecision": "deny",
      "permissionDecisionReason": f"[pr-review-report-write-gate] {reason}",
    }
  }, ensure_ascii=False))
  return 0


def main():
  try:
    payload = json.load(sys.stdin)
  except (json.JSONDecodeError, OSError):
    return silent()
  if not isinstance(payload, dict) or payload.get("tool_name") not in {"Write", "Edit"}:
    return silent()
  tool_input = payload.get("tool_input")
  if not isinstance(tool_input, dict):
    return silent()
  file_path = tool_input.get("file_path")
  if not isinstance(file_path, str) or not file_path:
    return silent()
  try:
    lexical = lexical_path(payload, file_path)
  except (OSError, ValueError):
    return silent()
  if lexical is None:
    return silent()
  matched = report_kind(lexical.name)
  if matched is None:
    return silent()
  kind, _, exact = matched
  try:
    path = lexical.resolve(strict=False)
  except (OSError, RuntimeError, ValueError):
    return deny(
      payload,
      lexical,
      "REPORT_PATH_UNRESOLVED",
      "Protected PR review report paths must resolve safely before writing.",
    )
  if kind in {"final", "audit"}:
    return deny(
      payload,
      path,
      "FINAL_REPORT_PATH",
      "Final PR review reports may only be produced by the projection helper.",
    )
  if not exact or not is_canonical_draft(path):
    return deny(
      payload,
      path,
      "DRAFT_REPORT_PATH",
      "PR review drafts may only be written under the canonical report root with exactly one repository directory.",
    )
  return silent()


if __name__ == "__main__":
  raise SystemExit(main())
