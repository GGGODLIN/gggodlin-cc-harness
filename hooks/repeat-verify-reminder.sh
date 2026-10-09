#!/usr/bin/env python3
# repeat-verify-reminder — PostToolUse advisory hook（提醒不擋）
# 偵測：同 session 同一 Bash 指令一字不差重跑、其間無 Edit/Write/NotebookEdit
# 依據：dispatch-and-verify「Code 未變更就不重跑同一驗證指令」；30 天 161 session 實證（2026-08-14）
# 本檔在契約測試底下：~/.claude/hooks/repeat-verify-reminder.test.sh
import fcntl
import hashlib
import json
import os
import re
import sys
import time

STATE_DIR = os.path.join(os.environ.get("TMPDIR", "/tmp"), "cc-repeat-verify")
MUTATE_TOOLS = {"Edit", "Write", "NotebookEdit"}
MIN_CMD_LEN = 8
STALE_SECS = 48 * 3600


def load_state(path):
  try:
    with open(path) as f:
      return json.load(f)
  except (OSError, json.JSONDecodeError):
    return {"mut": 0, "cmds": {}}


def prune(now):
  try:
    for e in os.scandir(STATE_DIR):
      if now - e.stat().st_mtime > STALE_SECS:
        os.unlink(e.path)
  except OSError:
    pass


def is_pure_sleep(command):
  return re.fullmatch(r"sleep[ \t]+\d+(?:\.\d+)?[smhd]?", command) is not None


def process(payload, state_path):
  tool = payload.get("tool_name", "")
  state = load_state(state_path)

  if tool in MUTATE_TOOLS:
    state["mut"] += 1
  elif tool == "Bash":
    cmd = (payload.get("tool_input") or {}).get("command", "").strip()
    if len(cmd) < MIN_CMD_LEN or is_pure_sleep(cmd):
      return
    h = hashlib.sha1(cmd.encode()).hexdigest()[:16]
    entry = state["cmds"].get(h)
    next_entry = {"mut": state["mut"], "n": (entry["n"] + 1 if entry else 1)}
    if entry and "warned_mut" in entry:
      next_entry["warned_mut"] = entry["warned_mut"]
    should_warn = (
      entry
      and entry["mut"] == state["mut"]
      and entry.get("warned_mut") != state["mut"]
    )
    if should_warn:
      next_entry["warned_mut"] = state["mut"]
    state["cmds"][h] = next_entry
    if should_warn:
      msg = (
        "⚠️ repeat-verify: 這條 Bash 指令在本 session 已跑過，且其間沒有任何 Edit/Write。"
        "規則：code 未變更就不重跑同一驗證——重跑不產生新證據，要更強證據就換驗證角度。"
        "若這是刻意輪詢或等待外部狀態，忽略本提醒。"
        f"（第 {state['cmds'][h]['n']} 次執行, hash={h}）"
      )
      print(json.dumps({
        "hookSpecificOutput": {
          "hookEventName": "PostToolUse",
          "additionalContext": msg,
        }
      }, ensure_ascii=False))
  else:
    return

  try:
    with open(state_path, "w") as f:
      json.dump(state, f)
  except OSError:
    pass


def main():
  try:
    payload = json.load(sys.stdin)
  except json.JSONDecodeError:
    return
  session = payload.get("session_id", "")
  if not session:
    return
  os.makedirs(STATE_DIR, exist_ok=True)
  state_key = hashlib.sha256(session.encode()).hexdigest()
  state_path = os.path.join(STATE_DIR, f"{state_key}.json")
  try:
    with open(f"{state_path}.lock", "w") as lock:
      fcntl.flock(lock, fcntl.LOCK_EX)
      process(payload, state_path)
  except OSError:
    return
  prune(time.time())


if __name__ == "__main__":
  main()
