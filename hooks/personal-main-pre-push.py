#!/usr/bin/python3
"""Protects ordinary Git pushes through an installed pre-push hook.

This gate protects an installed hook during a normal Git push when the caller
has not used --no-verify. It does not guarantee protection when --no-verify is
used, when the hook is deleted or changed, when a remote API bypasses hooks, or
when a remote force race or final-read race occurs after client evidence. force push 仍須既有 human confirm.
安裝後另設 worktree-specific core.hooksPath 會繞過，/git-closeout 要查；
命令列 -c core.hooksPath 也會繞過。 `/git-closeout` performs the fresh
reconciliation after a push.
"""
import json
import os
import pwd
import re
import signal
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


TRUSTED_GIT = "/usr/bin/git"
MAIN_REF = "refs/heads/main"
AUDIT_NAME = "personal-main-pre-push.jsonl"
TEST_MODE_ENV = "PERSONAL_MAIN_PRE_PUSH_TEST_MODE"
TEST_AUDIT_HOME_ENV = "PERSONAL_MAIN_PRE_PUSH_TEST_AUDIT_HOME"
GIT_TOTAL_DEADLINE_SECONDS = 8.0
GIT_COMMAND_TIMEOUT_SECONDS = 2.0
OID_LENGTHS = {"sha1": 40, "sha256": 64}
OID_RE = re.compile(r"^[0-9a-f]+$", re.IGNORECASE)
AUDIT_FIELDS = (
  "timestamp",
  "outcome",
  "reason",
  "remote_name",
  "remote_ref",
  "local_oid",
  "remote_oid",
)


class GateError(Exception):
  pass


def git_environment():
  environment = dict(os.environ)
  for name in list(environment):
    if name.startswith("GIT_TRACE") or name.startswith("GIT_CONFIG_"):
      environment.pop(name, None)
  for name in (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_ASKPASS",
    "SSH_ASKPASS",
    "GIT_TERMINAL_PROMPT",
    "GIT_EDITOR",
    "GIT_SEQUENCE_EDITOR",
    "GIT_PAGER",
    "PAGER",
    "GIT_SSH",
    "GIT_SSH_COMMAND",
    "GIT_PROXY_COMMAND",
    "GIT_EXTERNAL_DIFF",
    "GIT_DIFF_OPTS",
  ):
    environment.pop(name, None)
  environment["GIT_NO_REPLACE_OBJECTS"] = "1"
  environment["GIT_OPTIONAL_LOCKS"] = "0"
  return environment


def decode_git(value):
  return value.decode("utf-8", errors="surrogateescape")


def stop_process_group(process):
  try:
    os.killpg(process.pid, signal.SIGTERM)
  except OSError:
    pass
  try:
    process.communicate(timeout=0.25)
  except subprocess.TimeoutExpired:
    try:
      os.killpg(process.pid, signal.SIGKILL)
    except OSError:
      pass
    try:
      process.communicate(timeout=0.25)
    except (OSError, subprocess.TimeoutExpired):
      pass
  except OSError:
    pass


def run_git(cwd, *args, deadline=None):
  deadline = deadline if deadline is not None else time.monotonic() + GIT_TOTAL_DEADLINE_SECONDS
  remaining = deadline - time.monotonic()
  if remaining <= 0:
    raise GateError("Git deadline exceeded")
  command = [TRUSTED_GIT, "-C", str(cwd), *args]
  try:
    process = subprocess.Popen(
      command,
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
      env=git_environment(),
      start_new_session=True,
    )
  except (OSError, ValueError) as error:
    raise GateError(f"Git invocation failed: {error}") from error
  try:
    stdout, stderr = process.communicate(
      timeout=min(GIT_COMMAND_TIMEOUT_SECONDS, remaining)
    )
  except subprocess.TimeoutExpired as error:
    stop_process_group(process)
    raise GateError("Git command timed out") from error
  except (OSError, ValueError) as error:
    stop_process_group(process)
    raise GateError("Git communication failed") from error
  return subprocess.CompletedProcess(
    command,
    process.returncode,
    decode_git(stdout),
    decode_git(stderr),
  )


def remove_newline(value):
  return value[:-1] if value.endswith("\n") else value


def oid(value, expected_length=None):
  lengths = {expected_length} if expected_length is not None else set(OID_LENGTHS.values())
  return (
    value.lower()
    if isinstance(value, str)
    and len(value) in lengths
    and OID_RE.fullmatch(value)
    else None
  )


def zero_oid(value, expected_length=None):
  normalized = oid(value, expected_length)
  return normalized is not None and set(normalized) == {"0"}


def canonical_home():
  if os.environ.get(TEST_MODE_ENV) == "1":
    override = os.environ.get(TEST_AUDIT_HOME_ENV)
    if override and os.path.isabs(override):
      return Path(override).resolve()
  try:
    return Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
  except (KeyError, OSError, RuntimeError) as error:
    raise GateError("OS canonical home is unavailable") from error


def invoking_top_level(deadline=None):
  result = run_git(Path.cwd(), "rev-parse", "--show-toplevel", deadline=deadline)
  if result.returncode != 0:
    raise GateError("Git could not resolve the invoking worktree")
  value = remove_newline(result.stdout)
  if not value:
    raise GateError("Git returned an empty worktree path")
  return Path(value)


def object_format_length(repo, deadline=None):
  result = run_git(repo, "rev-parse", "--show-object-format", deadline=deadline)
  if result.returncode != 0:
    raise GateError("Git object format is unavailable")
  value = remove_newline(result.stdout)
  if value not in OID_LENGTHS:
    raise GateError("Git object format is unsupported")
  return OID_LENGTHS[value]


def common_git_dir(repo, deadline=None):
  result = run_git(
    repo,
    "rev-parse",
    "--path-format=absolute",
    "--git-common-dir",
    deadline=deadline,
  )
  if result.returncode != 0:
    raise GateError("Git common directory is unavailable")
  value = remove_newline(result.stdout)
  if not os.path.isabs(value):
    raise GateError("Git common directory is not absolute")
  return Path(value)


def reject_grafts(repo, deadline=None):
  grafts = common_git_dir(repo, deadline=deadline) / "info" / "grafts"
  try:
    os.lstat(grafts)
  except FileNotFoundError:
    return
  except OSError as error:
    raise GateError("Git grafts file cannot be inspected") from error
  raise GateError("Git grafts file is present")


def read_local_main(repo, oid_length, deadline=None):
  result = run_git(
    repo,
    "rev-parse",
    "--verify",
    f"{MAIN_REF}^{{commit}}",
    deadline=deadline,
  )
  if result.returncode != 0:
    raise GateError("canonical local main ref is unavailable")
  value = oid(remove_newline(result.stdout), oid_length)
  if value is None:
    raise GateError("canonical local main ref is invalid")
  return value


def parse_updates(stream):
  updates = []
  for raw_line in stream:
    line = raw_line.strip()
    if not line:
      continue
    fields = line.split()
    if len(fields) != 4:
      raise GateError("invalid pre-push input")
    local_ref, local_oid, remote_ref, remote_oid = fields
    if not local_ref or not remote_ref:
      raise GateError("invalid pre-push ref input")
    updates.append(
      {
        "local_ref": local_ref,
        "local_oid": local_oid,
        "remote_ref": remote_ref,
        "remote_oid": remote_oid,
      }
    )
  return updates


def require_commit(repo, value, oid_length, deadline=None):
  normalized = oid(value, oid_length)
  if normalized is None:
    raise GateError("new OID is invalid")
  result = run_git(repo, "cat-file", "-t", normalized, deadline=deadline)
  if result.returncode != 0:
    raise GateError("new OID cannot be read")
  if remove_newline(result.stdout) != "commit":
    raise GateError("new OID is not a commit")
  return normalized


def require_ancestor(repo, ancestor, descendant, reason, deadline=None):
  result = run_git(
    repo,
    "merge-base",
    "--is-ancestor",
    ancestor,
    descendant,
    deadline=deadline,
  )
  if result.returncode == 0:
    return
  if result.returncode == 1:
    raise GateError(reason)
  raise GateError(f"Git could not verify {reason}")


def validate_main_update(repo, update, local_main, oid_length, deadline=None):
  local_oid = oid(update["local_oid"], oid_length)
  if local_oid is None or zero_oid(local_oid, oid_length):
    raise GateError("main deletion or zero local OID is denied")
  new_oid = require_commit(repo, local_oid, oid_length, deadline=deadline)
  remote_oid = oid(update["remote_oid"], oid_length)
  if remote_oid is None or zero_oid(remote_oid, oid_length):
    raise GateError("remote old OID is missing or zero")
  require_ancestor(
    repo,
    local_main,
    new_oid,
    "local main is not an ancestor of new OID",
    deadline=deadline,
  )
  require_ancestor(
    repo,
    remote_oid,
    new_oid,
    "remote old OID is not an ancestor of new OID",
    deadline=deadline,
  )
  return {
    "local_oid": new_oid,
    "remote_oid": remote_oid,
    "remote_ref": update["remote_ref"],
  }


def check_main_updates(
  repo,
  updates,
  after_first_read=None,
  read_main=read_local_main,
  oid_length=None,
  deadline=None,
):
  deadline = deadline if deadline is not None else time.monotonic() + GIT_TOTAL_DEADLINE_SECONDS
  oid_length = oid_length if oid_length is not None else object_format_length(repo, deadline=deadline)
  local_main_before = read_main(repo, oid_length, deadline)
  validated = [
    validate_main_update(repo, update, local_main_before, oid_length, deadline=deadline)
    for update in updates
  ]
  if after_first_read is not None:
    after_first_read(repo, deadline)
  local_main_after = read_main(repo, oid_length, deadline)
  if local_main_before != local_main_after:
    raise GateError("canonical local main changed during pre-push check")
  return validated


def secure_dir(path):
  path = Path(path)
  if not path.is_absolute() or not hasattr(os, "O_NOFOLLOW"):
    raise GateError("audit directory is unavailable")
  flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW
  parent_fd = os.open("/", flags)
  try:
    for part in path.parts[1:]:
      try:
        child_fd = os.open(part, flags, dir_fd=parent_fd)
      except FileNotFoundError:
        try:
          os.mkdir(part, 0o700, dir_fd=parent_fd)
        except FileExistsError:
          pass
        child_fd = os.open(part, flags, dir_fd=parent_fd)
      os.close(parent_fd)
      parent_fd = child_fd
    directory_stat = os.fstat(parent_fd)
    if not stat.S_ISDIR(directory_stat.st_mode) or directory_stat.st_uid != os.getuid():
      raise GateError("audit directory is unsafe")
    return parent_fd
  except Exception:
    os.close(parent_fd)
    raise


def audit_path(home=None):
  if home is None:
    base = canonical_home()
  else:
    base = Path(home)
    if not base.is_absolute():
      raise GateError("audit home must be absolute")
    base = base.resolve()
  return base / ".claude" / "logs"


def append_bytes(fd, payload):
  offset = 0
  while offset < len(payload):
    written = os.write(fd, payload[offset:])
    if written <= 0:
      raise OSError("audit short write")
    offset += written


def append_audit(record, home=None):
  parent_fd = None
  fd = None
  try:
    parent_fd = secure_dir(audit_path(home))
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK
    fd = os.open(AUDIT_NAME, flags, 0o600, dir_fd=parent_fd)
    file_stat = os.fstat(fd)
    if (
      not stat.S_ISREG(file_stat.st_mode)
      or file_stat.st_uid != os.getuid()
      or file_stat.st_nlink != 1
    ):
      raise OSError("audit file is not a regular uniquely owned file")
    os.fchmod(fd, 0o600)
    payload = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    append_bytes(fd, payload)
  except Exception as error:
    try:
      sys.stderr.write(
        f"personal-main-pre-push: WARN: audit unavailable ({type(error).__name__})\n"
      )
    except Exception:
      pass
  finally:
    if fd is not None:
      try:
        os.close(fd)
      except OSError:
        pass
    if parent_fd is not None:
      try:
        os.close(parent_fd)
      except OSError:
        pass


def audit_record(remote_name, update, outcome, reason):
  update = update or {}
  record = {
    "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "outcome": outcome,
    "reason": reason,
    "remote_name": remote_name,
    "remote_ref": update.get("remote_ref", ""),
    "local_oid": update.get("local_oid", ""),
    "remote_oid": update.get("remote_oid", ""),
  }
  return {field: record[field] for field in AUDIT_FIELDS}


def emit_denial(remote_name, updates, reason, audit_home=None):
  targets = [update for update in updates if update.get("remote_ref") == MAIN_REF]
  if not targets:
    targets = [None]
  for update in targets:
    append_audit(audit_record(remote_name, update, "deny", reason), home=audit_home)
  sys.stderr.write(f"personal-main-pre-push: DENY: {reason}\n")
  return 1


def main(argv=None, stdin=None, audit_home=None, after_first_read=None):
  argv = sys.argv[1:] if argv is None else argv
  stdin = sys.stdin if stdin is None else stdin
  remote_name = argv[0] if argv else ""
  updates = []
  try:
    if len(argv) != 2:
      raise GateError("pre-push remote arguments are invalid")
    updates = parse_updates(stdin)
    main_updates = [update for update in updates if update["remote_ref"] == MAIN_REF]
    if not main_updates:
      append_audit(
        audit_record(remote_name, updates[0] if updates else None, "allow", "non_main_ref"),
        home=audit_home,
      )
      return 0
    deadline = time.monotonic() + GIT_TOTAL_DEADLINE_SECONDS
    repo = invoking_top_level(deadline=deadline)
    oid_length = object_format_length(repo, deadline=deadline)
    reject_grafts(repo, deadline=deadline)
    validated = check_main_updates(
      repo,
      main_updates,
      after_first_read=after_first_read,
      oid_length=oid_length,
      deadline=deadline,
    )
    for update, values in zip(main_updates, validated):
      update_for_audit = {
        **update,
        "local_oid": values["local_oid"],
        "remote_oid": values["remote_oid"],
      }
      append_audit(
        audit_record(remote_name, update_for_audit, "allow", "main_update_valid"),
        home=audit_home,
      )
    return 0
  except (GateError, OSError, ValueError, subprocess.SubprocessError) as error:
    return emit_denial(remote_name, updates, str(error), audit_home=audit_home)


if __name__ == "__main__":
  raise SystemExit(main())
