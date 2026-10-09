#!/usr/bin/env python3

import importlib.util
import json
import os
import tempfile
import unittest
from datetime import timedelta, timezone


MODULE_PATH = os.path.join(os.path.dirname(__file__), "measure-output-length.py")
SPEC = importlib.util.spec_from_file_location("measure_output_length", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def user(timestamp, text, origin="human", prompt_source="typed", is_meta=False, is_sidechain=False):
  entry = {
    "timestamp": timestamp,
    "message": {"role": "user", "content": text},
    "isMeta": is_meta,
    "isSidechain": is_sidechain,
  }
  if origin is not None:
    entry["origin"] = {"kind": origin}
  if prompt_source is not None:
    entry["promptSource"] = prompt_source
  return entry


def assistant(timestamp, model, blocks, is_meta=False, is_sidechain=False):
  return {
    "timestamp": timestamp,
    "message": {"role": "assistant", "model": model, "content": blocks},
    "isMeta": is_meta,
    "isSidechain": is_sidechain,
  }


def text(value):
  return {"type": "text", "text": value}


def tool_result(timestamp):
  return {
    "timestamp": timestamp,
    "message": {
      "role": "user",
      "content": [{"type": "tool_result", "tool_use_id": "tool-1", "content": "result"}],
    },
  }


def notification(timestamp):
  return {
    "timestamp": timestamp,
    "origin": {"kind": "task-notification"},
    "promptSource": "system",
    "message": {"role": "user", "content": "<task-notification>done</task-notification>"},
  }


def write_session(root, name, entries):
  project = os.path.join(root, "project")
  os.makedirs(project, exist_ok=True)
  path = os.path.join(project, name)
  with open(path, "w") as handle:
    for entry in entries:
      handle.write(json.dumps(entry) + "\n")
  return path


class MeasureOutputLengthTest(unittest.TestCase):
  def test_aggregates_visible_text_until_next_human_input(self):
    entries = [
      user("2026-07-25T10:00:00Z", "開始"),
      assistant("2026-07-25T10:00:01Z", "claude-opus-5", [text("abc"), {"type": "thinking", "thinking": "hidden"}]),
      assistant("2026-07-25T10:00:02Z", "claude-opus-5", [{"type": "tool_use", "name": "Write", "input": {"content": "ignored"}}]),
      tool_result("2026-07-25T10:00:03Z"),
      notification("2026-07-25T10:00:04Z"),
      assistant("2026-07-25T10:00:05Z", "claude-opus-5", [text("de")]),
      user("2026-07-25T10:01:00Z", "下一題"),
    ]
    windows, uncertain = MODULE.build_windows(entries, "session.jsonl")
    self.assertEqual([], uncertain)
    self.assertEqual(2, len(windows))
    self.assertEqual(5, windows[0]["chars"])
    self.assertEqual(2, windows[0]["blocks"])
    self.assertEqual(("claude-opus-5",), windows[0]["models"])
    self.assertEqual("next_human", windows[0]["closed_by"])
    self.assertEqual("right_censored", windows[1]["closed_by"])

  def test_excludes_meta_sidechain_and_non_text_content(self):
    entries = [
      user("2026-07-25T10:00:00Z", "開始"),
      assistant("2026-07-25T10:00:01Z", "claude-opus-5", [text("ok")]),
      assistant("2026-07-25T10:00:02Z", "claude-opus-5", [text("meta")], is_meta=True),
      assistant("2026-07-25T10:00:03Z", "claude-opus-5", [text("side")], is_sidechain=True),
      user("2026-07-25T10:00:04Z", "sdk", origin=None, prompt_source="sdk"),
    ]
    windows, uncertain = MODULE.build_windows(entries, "session.jsonl")
    self.assertEqual(["2026-07-25"], uncertain)
    self.assertEqual(1, len(windows))
    self.assertEqual(2, windows[0]["chars"])
    self.assertEqual(1, windows[0]["blocks"])
    self.assertEqual("uncertain_boundary", windows[0]["closed_by"])

  def test_collect_filters_by_window_timestamp_and_excludes_mixed_model(self):
    entries = [
      user("2026-07-24T10:00:00Z", "舊問題"),
      assistant("2026-07-24T10:00:01Z", "claude-opus-5", [text("old")]),
      user("2026-07-25T10:00:00Z", "新問題"),
      assistant("2026-07-25T10:00:01Z", "claude-opus-5", [text("new")]),
      user("2026-07-25T10:01:00Z", "混合問題"),
      assistant("2026-07-25T10:01:01Z", "claude-opus-5", [{"type": "tool_use", "name": "Read", "input": {}}]),
      assistant("2026-07-25T10:01:02Z", "claude-fable-5", [text("b")]),
      user("2026-07-25T10:02:00Z", "結束"),
    ]
    with tempfile.TemporaryDirectory() as root:
      write_session(root, "session.jsonl", entries)
      result = MODULE.collect(root, "2026-07-25")
    self.assertEqual(1, result["quality"]["primary"])
    self.assertEqual(1, result["quality"]["mixed_model"])
    self.assertEqual([3], result["chars_by_model"]["claude-opus-5"])
    self.assertTrue(all(window["start_date"] >= "2026-07-25" for window in result["windows"]))

  def test_classifies_production_slash_shell_and_image_inputs(self):
    slash = user(
      "2026-07-25T10:00:00Z",
      "<command-name>/trial-review</command-name>\n<command-message>trial-review</command-message>",
      origin=None,
      prompt_source=None,
    )
    self.assertEqual(("human", "slash"), MODULE.classify_user_boundary(slash))
    shell = user(
      "2026-07-25T10:00:00Z",
      "<bash-input>pwd</bash-input>",
      origin=None,
      prompt_source=None,
    )
    self.assertEqual(("human", "shell"), MODULE.classify_user_boundary(shell))
    stdout = user(
      "2026-07-25T10:00:00Z",
      "<local-command-stdout>/tmp</local-command-stdout>",
      origin=None,
      prompt_source=None,
    )
    self.assertEqual(("nonhuman", None), MODULE.classify_user_boundary(stdout))
    bash_output = user(
      "2026-07-25T10:00:00Z",
      "<bash-stdout>out</bash-stdout><bash-stderr>err</bash-stderr>",
      origin=None,
      prompt_source=None,
    )
    self.assertEqual(("nonhuman", None), MODULE.classify_user_boundary(bash_output))
    interrupted = user(
      "2026-07-25T10:00:00Z",
      "[{'type': 'text', 'text': '[Request interrupted by user for tool use]'}]",
      origin=None,
      prompt_source=None,
    )
    self.assertEqual(("human", "interrupt"), MODULE.classify_user_boundary(interrupted))
    image = user("2026-07-25T10:00:00Z", "", origin="human", prompt_source="typed")
    image["message"]["content"] = [{"type": "image", "source": {}}]
    self.assertEqual(("human", "image"), MODULE.classify_user_boundary(image))

  def test_compact_summary_does_not_close_window(self):
    compact = user("2026-07-25T10:00:02Z", "summary", origin=None, prompt_source=None)
    compact["isCompactSummary"] = True
    entries = [
      user("2026-07-25T10:00:00Z", "開始"),
      assistant("2026-07-25T10:00:01Z", "claude-opus-5", [text("a")]),
      compact,
      assistant("2026-07-25T10:00:03Z", "claude-opus-5", [text("b")]),
      user(
        "2026-07-25T10:01:00Z",
        "<command-name>/login</command-name>",
        origin=None,
        prompt_source=None,
      ),
    ]
    windows, uncertain = MODULE.build_windows(entries, "session.jsonl")
    self.assertEqual([], uncertain)
    self.assertEqual(2, windows[0]["chars"])
    self.assertEqual(2, windows[0]["blocks"])
    self.assertEqual("next_human", windows[0]["closed_by"])

  def test_uses_local_date_for_utc_timestamps(self):
    original_timezone = MODULE.LOCAL_TIMEZONE
    MODULE.LOCAL_TIMEZONE = timezone(timedelta(hours=8))
    entries = [
      user("2026-07-17T16:30:00Z", "本地七月十八日"),
      assistant("2026-07-17T16:31:00Z", "claude-opus-5", [text("visible")]),
      user("2026-07-17T17:00:00Z", "下一題"),
    ]
    try:
      with tempfile.TemporaryDirectory() as root:
        write_session(root, "session.jsonl", entries)
        result = MODULE.collect(root, "2026-07-18")
    finally:
      MODULE.LOCAL_TIMEZONE = original_timezone
    self.assertEqual(1, result["quality"]["primary"])
    self.assertEqual([7], result["chars_by_model"]["claude-opus-5"])

  def test_scans_old_mtime_files_and_honors_before_timestamp(self):
    entries = [
      user("2026-07-25T10:00:00Z", "第一題"),
      assistant("2026-07-25T10:00:01Z", "claude-opus-5", [text("first")]),
      user("2026-07-25T10:01:00Z", "第二題"),
      assistant("2026-07-26T10:00:01Z", "claude-opus-5", [text("future")]),
      user("2026-07-26T10:01:00Z", "第三題"),
    ]
    with tempfile.TemporaryDirectory() as root:
      path = write_session(root, "session.jsonl", entries)
      os.utime(path, (1, 1))
      result = MODULE.collect(root, "2026-07-25", "2026-07-26T00:00:00Z")
    self.assertEqual(1, result["quality"]["candidate_files"])
    self.assertEqual(1, result["quality"]["primary"])
    self.assertEqual([5], result["chars_by_model"]["claude-opus-5"])

  def test_percentile_uses_existing_non_interpolated_index(self):
    self.assertEqual(10, MODULE.percentile(list(range(1, 11)), 0.9))
    self.assertEqual(19, MODULE.percentile(list(range(1, 21)), 0.9))
    self.assertIsNone(MODULE.percentile([], 0.9))

  def test_zero_text_model_window_is_kept_as_zero_attention(self):
    entries = [
      user("2026-07-25T10:00:00Z", "開始"),
      assistant("2026-07-25T10:00:01Z", "claude-opus-5", [{"type": "thinking", "thinking": "hidden"}]),
      user("2026-07-25T10:01:00Z", "下一題"),
    ]
    with tempfile.TemporaryDirectory() as root:
      write_session(root, "session.jsonl", entries)
      result = MODULE.collect(root, "2026-07-25")
    self.assertEqual(1, result["quality"]["zero_text"])
    self.assertEqual(1, result["quality"]["primary"])
    self.assertEqual([0], result["chars_by_model"]["claude-opus-5"])


if __name__ == "__main__":
  unittest.main()
