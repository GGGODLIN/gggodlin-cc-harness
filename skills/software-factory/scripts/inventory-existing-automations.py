#!/usr/bin/env python3
"""Inventory existing local automations (Claude hooks, LaunchAgents, git hooks) to prevent proposing already-automated workflows as new Software Factory candidates."""

import argparse
import base64
import json
import os
import plistlib
from datetime import date, datetime
from pathlib import Path
from typing import Any


def to_json_safe(val: Any) -> Any:
  if val is None or isinstance(val, (bool, int, float, str)):
    return val
  if isinstance(val, (datetime, date)):
    return val.isoformat()
  if isinstance(val, bytes):
    return base64.b64encode(val).decode("ascii")
  if isinstance(val, dict):
    return {str(k): to_json_safe(v) for k, v in val.items()}
  if isinstance(val, (list, tuple)):
    return [to_json_safe(v) for v in val]
  return str(val)


def scan_settings_hooks(settings_path: Path) -> list[dict[str, str]]:
  if os.path.lexists(settings_path) and not settings_path.is_file():
    return [{"event": "ERROR", "matcher": "", "command": f"Unreadable or broken settings.json: {settings_path}", "comment": ""}]
  if not settings_path.is_file():
    return []
  try:
    data = json.loads(settings_path.read_text(encoding="utf-8"))
  except Exception as exc:
    return [{"event": "ERROR", "matcher": "", "command": f"Failed to parse {settings_path}: {exc}", "comment": ""}]

  if not isinstance(data, dict):
    return [{
      "event": "ERROR",
      "matcher": "",
      "command": f"Invalid root type in {settings_path}: expected object, got {type(data).__name__}",
      "comment": "",
    }]

  hooks_Obj = data.get("hooks")
  if not isinstance(hooks_Obj, dict):
    return []

  results: list[dict[str, str]] = []
  for event_name, entries in hooks_Obj.items():
    if not isinstance(entries, list):
      continue
    for entry in entries:
      if not isinstance(entry, dict):
        continue
      matcher = str(entry.get("matcher", "*"))
      inner_hooks = entry.get("hooks", [])
      if not isinstance(inner_hooks, list):
        continue
      for h in inner_hooks:
        if not isinstance(h, dict):
          continue
        results.append({
          "event": str(event_name),
          "matcher": matcher,
          "command": str(h.get("command", "")),
          "comment": str(h.get("comment", h.get("statusMessage", ""))),
        })
  return results


def scan_launch_agents(launch_dir: Path) -> list[dict[str, Any]]:
  if os.path.lexists(launch_dir) and not launch_dir.is_dir():
    return [{"file": str(launch_dir), "label": "ERROR", "error": f"Unreadable or broken LaunchAgents path: {launch_dir}"}]
  if not launch_dir.is_dir():
    return []
  try:
    plist_names = sorted(entry.name for entry in os.scandir(launch_dir) if entry.name.endswith(".plist"))
  except OSError as exc:
    return [{"file": str(launch_dir), "label": "ERROR", "error": str(exc)}]

  results: list[dict[str, Any]] = []
  for plist_name in plist_names:
    plist_path = launch_dir / plist_name
    try:
      with plist_path.open("rb") as fp:
        pl = plistlib.load(fp)
      raw_prog_args = pl.get("ProgramArguments")
      if not raw_prog_args and pl.get("Program"):
        raw_prog_args = [pl["Program"]]
      elif raw_prog_args is None:
        raw_prog_args = []
      results.append({
        "file": plist_path.name,
        "label": str(pl.get("Label", plist_path.stem)),
        "program_arguments": to_json_safe(raw_prog_args),
        "start_calendar_interval": to_json_safe(pl.get("StartCalendarInterval")),
        "start_interval": to_json_safe(pl.get("StartInterval")),
      })
    except Exception as exc:
      results.append({
        "file": plist_path.name,
        "label": plist_path.stem,
        "error": str(exc),
      })
  return results


def main() -> int:
  parser = argparse.ArgumentParser(
    description="Scan settings.json hooks and LaunchAgents plists to identify already-automated workflows."
  )
  parser.add_argument(
    "--root",
    type=Path,
    default=None,
    help="Optional sandbox/fixture root containing settings.json and LaunchAgents/ (overrides defaults when present).",
  )
  parser.add_argument(
    "--settings",
    type=Path,
    default=None,
    help="Path to Claude settings.json (default: ~/.claude/settings.json).",
  )
  parser.add_argument(
    "--launch-agents",
    type=Path,
    default=None,
    help="Path to LaunchAgents directory (default: ~/Library/LaunchAgents).",
  )
  args = parser.parse_args()

  if args.root is not None:
    if args.settings is not None:
      settings_path = args.settings
    else:
      cand_settings = args.root / "settings.json"
      cand_claude_settings = args.root / ".claude" / "settings.json"
      if os.path.lexists(cand_settings):
        settings_path = cand_settings
      elif os.path.lexists(cand_claude_settings):
        settings_path = cand_claude_settings
      else:
        settings_path = cand_settings

    if args.launch_agents is not None:
      launch_dir = args.launch_agents
    else:
      cand_launch = args.root / "LaunchAgents"
      cand_lib_launch = args.root / "Library" / "LaunchAgents"
      if os.path.lexists(cand_launch):
        launch_dir = cand_launch
      elif os.path.lexists(cand_lib_launch):
        launch_dir = cand_lib_launch
      else:
        launch_dir = cand_launch
  else:
    settings_path = args.settings if args.settings is not None else (Path.home() / ".claude" / "settings.json")
    launch_dir = args.launch_agents if args.launch_agents is not None else (Path.home() / "Library" / "LaunchAgents")

  payload = {
    "settings_path": str(settings_path),
    "launch_agents_dir": str(launch_dir),
    "hooks": scan_settings_hooks(settings_path),
    "launch_agents": scan_launch_agents(launch_dir),
  }
  print(json.dumps(payload, ensure_ascii=False, indent=2))
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
