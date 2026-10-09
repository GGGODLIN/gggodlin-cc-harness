#!/usr/bin/env python3
"""按 model 統計 Claude Code 互動閱讀窗的可見文字負荷。"""

import collections
import glob
import json
import os
import statistics
import sys
from datetime import datetime

DEFAULT_ROOT = os.path.expanduser("~/.claude/projects")
DEFAULT_SINCE = "2026-07-18"
LOCAL_TIMEZONE = datetime.now().astimezone().tzinfo


def percentile(values, ratio):
  if not values:
    return None
  ordered = sorted(values)
  return ordered[min(len(ordered) - 1, int(len(ordered) * ratio))]


def describe(values):
  if not values:
    return None
  return {
    "n": len(values),
    "median": statistics.median(values),
    "mean": statistics.mean(values),
    "p90": percentile(values, 0.9),
    "max": max(values),
  }


def format_number(value):
  if isinstance(value, float) and not value.is_integer():
    return "%.1f" % value
  return str(int(value))


def format_stats(values):
  result = describe(values)
  if result is None:
    return "n=0"
  return "n=%-6d median=%-7s mean=%-7s p90=%-7s max=%s" % (
    result["n"],
    format_number(result["median"]),
    format_number(result["mean"]),
    format_number(result["p90"]),
    format_number(result["max"]),
  )


def parse_timestamp(value):
  if not value:
    return None
  normalized = str(value).replace("Z", "+00:00")
  try:
    result = datetime.fromisoformat(normalized)
  except ValueError:
    return None
  if result.tzinfo is None:
    result = result.replace(tzinfo=LOCAL_TIMEZONE)
  return result


def timestamp_date(entry):
  value = parse_timestamp(entry.get("timestamp"))
  if value is None:
    return ""
  return value.astimezone(LOCAL_TIMEZONE).date().isoformat()


def user_payload(message):
  content = message.get("content")
  if isinstance(content, str):
    return content, False
  if not isinstance(content, list):
    return "", False
  texts = []
  has_image = False
  for block in content:
    if not isinstance(block, dict):
      continue
    if block.get("type") == "text":
      text = block.get("text") or ""
      if text:
        texts.append(text)
    elif block.get("type") == "image":
      has_image = True
  return "\n".join(texts), has_image


def input_kind(text, has_image):
  if "<bash-input>" in text:
    return "shell"
  if text.lstrip().startswith("/") or "<command-name>" in text:
    return "slash"
  if has_image and text:
    return "mixed"
  if has_image:
    return "image"
  return "natural"


def classify_user_boundary(entry):
  if entry.get("isMeta") or entry.get("isSidechain"):
    return "none", None
  message = entry.get("message") or {}
  if message.get("role") != "user":
    return "none", None
  if entry.get("isCompactSummary"):
    return "nonhuman", None
  text, has_image = user_payload(message)
  if not text and not has_image:
    return "none", None
  origin = entry.get("origin") or {}
  origin_kind = origin.get("kind")
  prompt_source = entry.get("promptSource") or origin.get("promptSource")
  if origin_kind in {"task-notification", "peer"} or prompt_source == "system":
    return "nonhuman", None
  if origin_kind == "human" or prompt_source in {"typed", "queued"}:
    return "human", input_kind(text, has_image)
  if "<command-name>" in text:
    return "human", "slash"
  if "<bash-input>" in text:
    return "human", "shell"
  if "[Request interrupted by user" in text:
    return "human", "interrupt"
  if "<local-command-" in text or "<bash-stdout>" in text or "<bash-stderr>" in text or entry.get("sourceToolUseID"):
    return "nonhuman", None
  if text.startswith("[SYSTEM NOTIFICATION") or text.startswith("<system-reminder>") or "<task-notification>" in text:
    return "nonhuman", None
  return "uncertain", None


def assistant_text(entry):
  if entry.get("isMeta") or entry.get("isSidechain"):
    return [], None
  message = entry.get("message") or {}
  if message.get("role") != "assistant":
    return [], None
  content = message.get("content")
  if not isinstance(content, list):
    return [], None
  texts = []
  for block in content:
    if not isinstance(block, dict) or block.get("type") != "text":
      continue
    text = block.get("text") or ""
    if text:
      texts.append(text)
  return texts, message.get("model") or "?"


def new_window(entry, session_path, line_number, input_kind):
  return {
    "session_path": session_path,
    "start_line": line_number,
    "start_timestamp": entry.get("timestamp") or "",
    "start_date": timestamp_date(entry),
    "input_kind": input_kind,
    "chars": 0,
    "blocks": 0,
    "models": set(),
    "closed_by": None,
  }


def finish_window(window, closed_by):
  if window is None:
    return None
  result = dict(window)
  result["models"] = tuple(sorted(window["models"]))
  result["closed_by"] = closed_by
  return result


def build_windows(entries, session_path):
  windows = []
  uncertain_boundaries = []
  current = None
  for line_number, entry in enumerate(entries, 1):
    boundary, input_kind = classify_user_boundary(entry)
    if boundary == "human":
      finished = finish_window(current, "next_human")
      if finished is not None:
        windows.append(finished)
      current = new_window(entry, session_path, line_number, input_kind)
      continue
    if boundary == "uncertain":
      uncertain_boundaries.append(timestamp_date(entry))
      finished = finish_window(current, "uncertain_boundary")
      if finished is not None:
        windows.append(finished)
      current = None
      continue
    if current is None:
      continue
    texts, model = assistant_text(entry)
    if model is None:
      continue
    current["models"].add(model)
    if not texts:
      continue
    current["chars"] += sum(len(text) for text in texts)
    current["blocks"] += len(texts)
  finished = finish_window(current, "right_censored")
  if finished is not None:
    windows.append(finished)
  return windows, uncertain_boundaries


def read_entries(path, before=None):
  entries = []
  try:
    handle = open(path, "r", errors="replace")
  except OSError:
    return entries
  with handle:
    for line in handle:
      try:
        entry = json.loads(line)
      except Exception:
        continue
      if not isinstance(entry, dict):
        continue
      timestamp = parse_timestamp(entry.get("timestamp"))
      if before is not None and timestamp is not None and timestamp >= before:
        continue
      entries.append(entry)
  return entries


def candidate_files(root):
  return sorted(glob.glob(os.path.join(root, "*", "*.jsonl")))


def primary_model(window):
  if window["closed_by"] != "next_human" or len(window["models"]) != 1:
    return None
  model = window["models"][0]
  if model in {"?", "<synthetic>"}:
    return None
  return model


def collect(root, since, before=None):
  before_timestamp = parse_timestamp(before)
  if before and before_timestamp is None:
    raise ValueError("invalid before timestamp: %s" % before)
  files = candidate_files(root)
  windows = []
  uncertain_boundaries = []
  for path in files:
    session_windows, session_uncertain = build_windows(read_entries(path, before_timestamp), path)
    windows.extend(session_windows)
    uncertain_boundaries.extend(session_uncertain)
  relevant = [window for window in windows if window["start_date"] >= since]
  primary = [window for window in relevant if primary_model(window) is not None]
  chars_by_model = collections.defaultdict(list)
  blocks_by_model = collections.defaultdict(list)
  days_by_model = collections.defaultdict(set)
  for window in primary:
    model = primary_model(window)
    chars_by_model[model].append(window["chars"])
    blocks_by_model[model].append(window["blocks"])
    if window["start_date"]:
      days_by_model[model].add(window["start_date"])
  quality = {
    "candidate_files": len(files),
    "windows": len(relevant),
    "primary": len(primary),
    "right_censored": sum(window["closed_by"] == "right_censored" for window in relevant),
    "uncertain_windows": sum(window["closed_by"] == "uncertain_boundary" for window in relevant),
    "uncertain_boundaries": sum(date >= since for date in uncertain_boundaries if date),
    "mixed_model": sum(window["closed_by"] == "next_human" and len(window["models"]) > 1 for window in relevant),
    "synthetic": sum(window["closed_by"] == "next_human" and window["models"] == ("<synthetic>",) for window in relevant),
    "unknown_model": sum(window["closed_by"] == "next_human" and window["models"] == ("?",) for window in relevant),
    "zero_text": sum(window["closed_by"] == "next_human" and window["chars"] == 0 for window in relevant),
    "slash": sum(window["input_kind"] == "slash" for window in relevant),
    "shell": sum(window["input_kind"] == "shell" for window in relevant),
    "interrupt": sum(window["input_kind"] == "interrupt" for window in relevant),
  }
  return {
    "files": files,
    "windows": relevant,
    "primary": primary,
    "chars_by_model": chars_by_model,
    "blocks_by_model": blocks_by_model,
    "days_by_model": days_by_model,
    "quality": quality,
    "before": before,
  }


def print_report(result, since):
  quality = result["quality"]
  print("scanned files: %d (all main-session JSONL; local date >= %s; before=%s)" % (
    quality["candidate_files"], since, result["before"] or "none"))
  print()
  print("=== 互動閱讀窗可見文字總量（原始字元）===")
  for model in sorted(result["chars_by_model"], key=lambda key: -len(result["chars_by_model"][key])):
    days = sorted(result["days_by_model"][model])
    print("%-34s %s | blocks %s | days=%s..%s" % (
      model,
      format_stats(result["chars_by_model"][model]),
      format_stats(result["blocks_by_model"][model]),
      days[0] if days else "?",
      days[-1] if days else "?",
    ))
  print()
  print("=== 資料品質 ===")
  print("windows=%d primary=%d right_censored=%d uncertain_windows=%d uncertain_boundaries=%d" % (
    quality["windows"],
    quality["primary"],
    quality["right_censored"],
    quality["uncertain_windows"],
    quality["uncertain_boundaries"],
  ))
  print("mixed_model=%d synthetic=%d unknown_model=%d zero_text=%d slash=%d shell=%d interrupt=%d" % (
    quality["mixed_model"],
    quality["synthetic"],
    quality["unknown_model"],
    quality["zero_text"],
    quality["slash"],
    quality["shell"],
    quality["interrupt"],
  ))


def main(argv=None):
  args = list(sys.argv[1:] if argv is None else argv)
  since = args[0] if args else DEFAULT_SINCE
  datetime.strptime(since, "%Y-%m-%d")
  before = args[1] if len(args) > 1 else None
  print_report(collect(DEFAULT_ROOT, since, before), since)


if __name__ == "__main__":
  main()
