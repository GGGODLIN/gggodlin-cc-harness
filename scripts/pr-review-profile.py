#!/usr/bin/env python3

import argparse
import json
import re
import sys
from pathlib import Path

import yaml


SCHEME_REMOTE = re.compile(r"^([a-z][a-z0-9+.-]*)://([^/]+)/(.+)$", re.IGNORECASE)
SCP_REMOTE = re.compile(r"^[^/@:]+@[^/:]+:(.+)$")
LIST_FIELDS = ("spec_globs", "conventions_docs")
AUTHORITY_FIELDS = ("live", "change")


def default():
  return {
    "trunk": None,
    "spec_globs": [],
    "conventions_docs": [],
    "authority": {field: [] for field in AUTHORITY_FIELDS},
    "source": "default",
  }


def remote_path(remote):
  if not isinstance(remote, str):
    return None
  raw = remote.strip()
  scheme_match = SCHEME_REMOTE.match(raw)
  if scheme_match:
    scheme, _host, path = scheme_match.groups()
    if scheme.lower() == "file":
      return None
    return re.split(r"[?#]", path, maxsplit=1)[0]
  scp_match = SCP_REMOTE.match(raw)
  if scp_match:
    return re.split(r"[?#]", scp_match.group(1), maxsplit=1)[0]
  return None


def remote_to_key(remote):
  path = remote_path(remote)
  if path is None:
    return None
  segments = [s for s in path.strip("/").split("/") if s]
  if len(segments) < 2 or any(part in (".", "..") for part in segments):
    return None
  repo = re.sub(r"\.git$", "", segments[-1])
  if not repo:
    return None
  return f"{segments[-2]}/{repo}"


def as_list(field, value):
  if value is None:
    return []
  if isinstance(value, str):
    if not value.strip():
      raise ValueError(f"{field} must be a non-empty string")
    return [value]
  if isinstance(value, (list, tuple)):
    items = []
    for item in value:
      if not isinstance(item, str) or not item.strip():
        raise ValueError(f"{field} items must be non-empty strings, got {type(item).__name__}")
      items.append(item)
    return items
  raise ValueError(f"{field} must be a string or a list, got {type(value).__name__}")


def authority_lists(value):
  if value is None:
    value = {}
  if not isinstance(value, dict):
    raise ValueError(f"authority must be a mapping, got {type(value).__name__}")
  return {field: as_list(f"authority.{field}", value.get(field)) for field in AUTHORITY_FIELDS}


def load_profiles(path):
  profile_path = Path(path).expanduser()
  if not profile_path.is_file():
    return {}
  try:
    data = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
  except yaml.YAMLError as error:
    raise ValueError(f"parse error: {error}")
  if data is None:
    return {}
  # 非 mapping 的頂層讓下游 .get 炸出 AttributeError，核驗器會誤把它當成「沒有 profile」
  if not isinstance(data, dict):
    raise ValueError(f"top level must be a mapping, got {type(data).__name__}")
  return data


def resolve(remote, profile_path):
  key = remote_to_key(remote)
  if key is None:
    return default()
  entry = load_profiles(profile_path).get(key)
  if entry is None:
    return default()
  if not isinstance(entry, dict):
    raise ValueError(f"profile entry for {key} must be a mapping, got {type(entry).__name__}")
  trunk = entry.get("trunk")
  if trunk is None:
    return default()
  if not isinstance(trunk, str):
    raise ValueError(f"trunk must be a string, got {type(trunk).__name__}")
  trunk = trunk.strip()
  if not trunk:
    return default()
  resolved = default()
  resolved["trunk"] = trunk
  for field in LIST_FIELDS:
    resolved[field] = as_list(field, entry.get(field))
  resolved["authority"] = authority_lists(entry.get("authority"))
  resolved["source"] = str(Path(profile_path).expanduser())
  return resolved


def main(argv=None):
  parser = argparse.ArgumentParser(description="Resolve /pr-review repo profile from git remote URL")
  parser.add_argument("--remote", default="", help="git remote URL (https, ssh:// or scp-like)")
  parser.add_argument("--profile", default="~/.claude/pr-review/repos.yaml", help="path to repos.yaml")
  args = parser.parse_args(argv)
  try:
    print(json.dumps(resolve(args.remote, args.profile), ensure_ascii=False))
  except (ValueError, OSError) as error:
    print(f"repos.yaml ({Path(args.profile).expanduser()}): {error}", file=sys.stderr)
    return 1
  return 0


if __name__ == "__main__":
  sys.exit(main())
