#!/usr/bin/env python3

import argparse
import hashlib
import json
import ntpath
import os
import posixpath
import re
import stat
import sys
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

LOCK_VERSION = 3
MAX_LOCK_BYTES = 1024 * 1024
MAX_TREE_DEPTH = 128
MAX_BASELINE_BYTES = 256 * 1024
BASELINE_FILE = Path(__file__).with_name("skill-lock-source-baseline.json")
TREE_HASH_PATTERN = re.compile(r"^[0-9a-f]{40}$")
PROVENANCE_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{7,64}$")
INSTALLER_EXCLUDED_PATHS = frozenset({
  "README.md",
  "metadata.json",
  "rules/_sections.md",
  "rules/_template.md",
})


class VerificationError(Exception):
  pass


def close_descriptor(descriptor):
  with suppress(OSError):
    os.close(descriptor)


@dataclass(frozen=True)
class LockEntry:
  label: str
  directory: str
  expected_hash: str
  source: str = ""
  source_url: str = ""
  skill_path: str = ""


def sanitize_name(name):
  sanitized = re.sub(r"[^a-z0-9._]+", "-", name.lower())
  sanitized = re.sub(r"^[.\-]+|[.\-]+$", "", sanitized)
  return sanitized[:255] or "unnamed-skill"


def relative_parts(path):
  normalized = path.replace("\\", "/")
  if not normalized or posixpath.isabs(normalized) or ntpath.isabs(normalized) or "\0" in normalized:
    raise VerificationError
  parts = tuple(normalized.split("/"))
  if any(part in ("", ".", "..") for part in parts):
    raise VerificationError
  return parts


def reject_duplicate_keys(pairs):
  result = {}
  for key, value in pairs:
    if key in result:
      raise VerificationError
    result[key] = value
  return result


def validate_source_metadata(value):
  keys = ("source", "sourceUrl", "skillPath")
  present = [key in value for key in keys]
  if any(present) and not all(present):
    raise VerificationError
  if not any(present):
    return "", "", ""
  source, source_url, skill_path = (value[key] for key in keys)
  if not all(isinstance(item, str) and item for item in (source, source_url, skill_path)):
    raise VerificationError
  if any("\0" in item for item in (source, source_url, skill_path)):
    raise VerificationError
  try:
    parsed_url = urlsplit(source_url)
  except ValueError as error:
    raise VerificationError from error
  scheme = parsed_url.scheme.lower()
  if source_url.startswith("git@"):
    if not re.fullmatch(r"git@[^:/\s]+:[^\s/][^\s]*", source_url):
      raise VerificationError
  elif scheme in {"http", "https", "ssh"}:
    if not parsed_url.netloc:
      raise VerificationError
  else:
    raise VerificationError
  normalized_skill_path = skill_path.replace("\\", "/")
  normalized_lower = normalized_skill_path.lower()
  if normalized_lower != "skill.md" and not normalized_lower.endswith("/skill.md"):
    raise VerificationError
  relative_parts(normalized_skill_path)
  return source, source_url, normalized_skill_path


def read_json_file(path, max_bytes, allow_missing=False):
  flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
  try:
    descriptor = os.open(path, flags)
  except FileNotFoundError:
    if allow_missing:
      return None
    raise VerificationError from None
  except OSError as error:
    raise VerificationError from error

  try:
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode):
      raise VerificationError
    chunks = []
    total = 0
    while total <= max_bytes:
      chunk = os.read(descriptor, max_bytes + 1 - total)
      if not chunk:
        break
      chunks.append(chunk)
      total += len(chunk)
      if total > max_bytes:
        raise VerificationError
    try:
      text = b"".join(chunks).decode("utf-8")
      return json.loads(text, object_pairs_hook=reject_duplicate_keys)
    except (UnicodeError, ValueError) as error:
      raise VerificationError from error
  except VerificationError:
    raise
  except OSError as error:
    raise VerificationError from error
  finally:
    close_descriptor(descriptor)


def load_lock(lock_file):
  data = read_json_file(lock_file, MAX_LOCK_BYTES)

  if not isinstance(data, dict) or data.get("version") != LOCK_VERSION:
    raise VerificationError
  skills = data.get("skills")
  if not isinstance(skills, dict):
    raise VerificationError

  entries = []
  directories = set()
  for name, value in skills.items():
    if not isinstance(name, str) or not name or "/" in name or "\\" in name or "\0" in name:
      raise VerificationError
    if not isinstance(value, dict):
      raise VerificationError
    source, source_url, skill_path = validate_source_metadata(value)
    expected_hash = value.get("skillFolderHash")
    if expected_hash == "":
      continue
    if not isinstance(expected_hash, str) or not TREE_HASH_PATTERN.fullmatch(expected_hash):
      raise VerificationError
    directory = sanitize_name(name)
    if directory == "unnamed-skill" and name != directory:
      raise VerificationError
    if directory in directories:
      raise VerificationError
    directories.add(directory)
    entries.append(LockEntry(directory, directory, expected_hash, source, source_url, skill_path))
  return tuple(sorted(entries, key=lambda entry: entry.directory.encode()))


def load_baseline(baseline_file=BASELINE_FILE, lock_entries=None):
  data = read_json_file(baseline_file, MAX_BASELINE_BYTES)
  lock_by_skill = None
  if lock_entries is not None:
    lock_by_skill = {
      entry.directory: (entry.directory, entry.source, entry.source_url, entry.skill_path, entry.expected_hash)
      for entry in lock_entries
    }

  if not isinstance(data, dict) or data.get("version") != 1:
    raise VerificationError
  scope = data.get("scope")
  if not isinstance(scope, list) or not scope:
    raise VerificationError
  scope_skills = set()
  for skill in scope:
    if not isinstance(skill, str) or not skill or sanitize_name(skill) != skill or skill in scope_skills:
      raise VerificationError
    scope_skills.add(skill)
  records = data.get("entries")
  if not isinstance(records, list):
    raise VerificationError

  baseline = {}
  baseline_skills = set()
  for record in records:
    if not isinstance(record, dict):
      raise VerificationError
    skill = record.get("skill")
    if (
      not isinstance(skill, str)
      or not skill
      or sanitize_name(skill) != skill
      or skill not in scope_skills
      or skill in baseline_skills
    ):
      raise VerificationError
    baseline_skills.add(skill)
    source, source_url, skill_path = validate_source_metadata(record)
    source_hash = record.get("sourceTreeHash")
    runtime_hash = record.get("runtimeTreeHash")
    provenance_commit = record.get("provenanceCommit")
    provenance_reason = record.get("provenanceReason")
    if (
      not source
      or not source_url
      or not skill_path
      or not isinstance(source_hash, str)
      or not TREE_HASH_PATTERN.fullmatch(source_hash)
      or not isinstance(runtime_hash, str)
      or not TREE_HASH_PATTERN.fullmatch(runtime_hash)
      or not isinstance(provenance_commit, str)
      or not PROVENANCE_COMMIT_PATTERN.fullmatch(provenance_commit)
      or not isinstance(provenance_reason, str)
      or not provenance_reason.strip()
    ):
      raise VerificationError
    key = (skill, source, source_url, skill_path, source_hash)
    if lock_by_skill is not None and skill in lock_by_skill and key != lock_by_skill[skill]:
      raise VerificationError
    if key in baseline:
      raise VerificationError
    baseline[key] = runtime_hash
  if baseline_skills != scope_skills:
    raise VerificationError
  return baseline


def object_hash(kind, content):
  header = kind + b" " + str(len(content)).encode() + b"\0"
  return hashlib.sha1(header + content).digest()


def read_file(directory_fd, name):
  flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
  try:
    descriptor = os.open(name, flags, dir_fd=directory_fd)
    with os.fdopen(descriptor, "rb") as handle:
      mode = os.fstat(handle.fileno()).st_mode
      if not stat.S_ISREG(mode):
        raise VerificationError
      return mode, handle.read()
  except OSError as error:
    raise VerificationError from error


def symlink_stays_within_root(relative_directory, target):
  if posixpath.isabs(target) or ntpath.isabs(target):
    return False
  normalized_target = target.replace("\\", "/")
  joined = posixpath.normpath(posixpath.join(relative_directory, normalized_target))
  return joined != ".." and not joined.startswith("../")


def tree_hash(directory_fd, relative_directory="", depth=0, excluded_paths=frozenset()):
  if depth > MAX_TREE_DEPTH:
    raise VerificationError
  try:
    names = os.listdir(directory_fd)
  except OSError as error:
    raise VerificationError from error

  entries = []
  for name in names:
    try:
      metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except OSError as error:
      raise VerificationError from error
    encoded_name = os.fsencode(name)
    child_relative = posixpath.join(relative_directory, name)
    if child_relative in excluded_paths:
      if not stat.S_ISREG(metadata.st_mode):
        raise VerificationError
      continue

    if stat.S_ISDIR(metadata.st_mode):
      flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
      try:
        child_fd = os.open(name, flags, dir_fd=directory_fd)
      except OSError as error:
        raise VerificationError from error
      try:
        child_hash, child_has_entries = tree_hash(
          child_fd, child_relative, depth + 1, excluded_paths
        )
      finally:
        os.close(child_fd)
      if child_has_entries:
        entries.append((encoded_name, True, b"40000", child_hash))
    elif stat.S_ISREG(metadata.st_mode):
      file_mode, content = read_file(directory_fd, name)
      mode = b"100755" if file_mode & 0o111 else b"100644"
      entries.append((encoded_name, False, mode, object_hash(b"blob", content)))
    elif stat.S_ISLNK(metadata.st_mode):
      try:
        target = os.readlink(name, dir_fd=directory_fd)
      except OSError as error:
        raise VerificationError from error
      if not symlink_stays_within_root(relative_directory, target):
        raise VerificationError
      entries.append((encoded_name, False, b"120000", object_hash(b"blob", os.fsencode(target))))
    else:
      raise VerificationError

  entries.sort(key=lambda entry: entry[0] + (b"/" if entry[1] else b""))
  content = b"".join(mode + b" " + name + b"\0" + digest for name, _, mode, digest in entries)
  return object_hash(b"tree", content), bool(entries)


def hash_skill(root_fd, directory, excluded_paths=frozenset()):
  try:
    metadata = os.stat(directory, dir_fd=root_fd, follow_symlinks=False)
  except FileNotFoundError:
    return None
  except OSError as error:
    raise VerificationError from error
  if not stat.S_ISDIR(metadata.st_mode):
    raise VerificationError

  flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
  try:
    directory_fd = os.open(directory, flags, dir_fd=root_fd)
  except OSError as error:
    raise VerificationError from error
  try:
    digest, _ = tree_hash(directory_fd, excluded_paths=excluded_paths)
    return digest.hex()
  finally:
    os.close(directory_fd)


def source_runtime_hash(entry, baseline=None):
  baseline = baseline or {}
  return baseline.get((entry.directory, entry.source, entry.source_url, entry.skill_path, entry.expected_hash))


def stable_runtime_matches(root_fd, directory, full_before, expected_runtime_hash):
  projected_hash = hash_skill(root_fd, directory, INSTALLER_EXCLUDED_PATHS)
  full_after = hash_skill(root_fd, directory)
  if full_before != full_after:
    raise VerificationError
  return projected_hash == expected_runtime_hash


def verify(skills_dir, entries, baseline=None):
  baseline = baseline or {}
  try:
    canonical_root = Path(skills_dir).resolve(strict=True)
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    root_fd = os.open(canonical_root, flags)
  except OSError as error:
    raise VerificationError from error

  findings = []
  try:
    for entry in entries:
      actual_hash = hash_skill(root_fd, entry.directory)
      if actual_hash is None:
        findings.append(f"- ⚠️ **{entry.label}** — lock 有紀錄，但已安裝 skill 目錄不存在")
      elif actual_hash != entry.expected_hash:
        expected_runtime_hash = source_runtime_hash(entry, baseline)
        if expected_runtime_hash is not None and stable_runtime_matches(
          root_fd, entry.directory, actual_hash, expected_runtime_hash
        ):
          continue
        findings.append(f"- ⚠️ **{entry.label}** — installed skill 與 lock hash 不符（只通報、不自動修復）")
  finally:
    os.close(root_fd)
  return findings


def parse_args(argv):
  parser = argparse.ArgumentParser()
  parser.add_argument("--skills-dir", required=True)
  parser.add_argument("--lock-file", required=True)
  parser.add_argument("--baseline-file", default=str(BASELINE_FILE))
  return parser.parse_args(argv)


def main(argv):
  args = parse_args(argv)
  try:
    entries = load_lock(args.lock_file)
    baseline = load_baseline(args.baseline_file, entries)
    findings = verify(args.skills_dir, entries, baseline)
  except (VerificationError, RecursionError):
    print("- ⚠️ installed skill lock 驗證失敗 — lock schema、entry 或 skill 路徑不安全")
    return 2
  print("\n".join(findings))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
