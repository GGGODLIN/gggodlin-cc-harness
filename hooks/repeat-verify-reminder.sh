#!/usr/bin/env python3
# repeat-verify-reminder — PostToolUse advisory hook（提醒不擋）
# 偵測：同 session 同一 Bash 指令一字不差重跑、其間無 Edit/Write/NotebookEdit
# 依據：dispatch-and-verify「Code 未變更就不重跑同一驗證指令」；30 天 161 session 實證（2026-08-14）
# 提示型：字串比對只認常見入口，認不出來就放行（不提醒）。
# 不承諾完整語意；含 push／deploy 文字但不執行已知入口的，不重置。
# 部署只認既有 dev-lane 完成回件或同一 Collie 健康端點的版本變動；不把啟動中當完成。
# 本檔在契約測試底下：~/.claude/hooks/repeat-verify-reminder.test.sh
import fcntl
import hashlib
import json
import os
import re
import shlex
import stat
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


# 只認整段都是這幾種純指令。含 &&、;、換行或參數展開就不算。
FOCUS_RE = re.compile(r'open(?:[ \t]+-g)?[ \t]+-a[ \t]+(?:"[^"\n]+"|\'[^\'\n]+\')\Z')
# -C 只認絕對路徑；引號僅容許路徑含空格，不接受 shell 展開或串接。
GIT_PREFIX = (
  r'''git(?:[ \t]+-C[ \t]+(?:/[^\s;&|`$<>"'\\()]+|"/[^"\n;&|`$<>\\()]*"|'/[^'\n;&|`$<>\\()]*'))?'''
)
STATUS_RE = re.compile(
  r"(?:"
  + GIT_PREFIX + r"[ \t]+(?:status|diff|rev-parse|rev-list|log|show|ls-files|ls-remote)"
  r"|gh[ \t]+(?:run[ \t]+view|pr[ \t]+(?:view|checks|status)|run[ \t]+list)"
  r''')(?:[ \t]+(?!(?:-[Cc]|--exec|--output)(?:=|[ \t]))[^\s;&|`$<>"'\\()]+)*\Z'''
)
PUSH_RE = re.compile(
  GIT_PREFIX + r'''[ \t]+push(?:[ \t]+(?!(?:-[Cc]|--exec|--delete)(?:\b|=|[ \t]))[^\s;&|`$<>"'\\()]+)*\Z'''
)


def is_pure_focus_or_status(command):
  return FOCUS_RE.fullmatch(command) is not None or STATUS_RE.fullmatch(command) is not None


def is_completed_bash(payload):
  response = payload.get("tool_response")
  if payload.get("hook_event_name") != "PostToolUse" or not isinstance(response, dict):
    return False
  # PostToolUse 是成功回件，但背景啟動也會回傳；沒有完成形狀就不重置。
  if response.get("interrupted") is not False:
    return False
  if not all(isinstance(response.get(key), str) for key in ("stdout", "stderr")):
    return False
  if any(response.get(key) for key in (
    "backgroundTaskId", "backgroundedByUser", "backgroundedByTurnAbort",
    "backgroundedToDeliverMessage", "timedOutAfterMs", "backgroundEndsWithFinalResponse",
  )):
    return False
  if "exit_code" in response and response["exit_code"] != 0:
    return False
  return True


def is_dev_lane(payload, command):
  try:
    args = shlex.split(command)
  except ValueError:
    return False
  lane = os.path.join(os.path.expanduser("~"), "Desktop/projects/collie-example-owner/docs/owner/dev-lane.sh")
  repo = os.path.normpath(os.path.dirname(os.path.dirname(os.path.dirname(lane))))
  cwd = os.path.normpath(payload.get("cwd", ""))
  if args[:3] == ["cd", repo, "&&"]:
    cwd, args = repo, args[3:]
  # 日常部署以 tail 保留末尾輸出，管線成功仍需核對腳本自己的完成文字。
  if len(args) >= 4 and args[-4:-1] == ["2>&1", "|", "tail"] and re.fullmatch(r'-\d+', args[-1]):
    args = args[:-4]
  commands = ([lane], ["bash", lane])
  if cwd == repo:
    commands += (["docs/owner/dev-lane.sh"], ["bash", "docs/owner/dev-lane.sh"])
  return args in commands


def lane_completed(stdout):
  match = re.search(r'^next is on (\S+) \(dev HEAD ([0-9a-f]{8})\)$', stdout, re.M)
  return bool(match and re.search(r'\+' + match[2] + r'(?:-dirty)?$', match[1]))


def deployment_observation(payload, command):
  if not is_completed_bash(payload):
    return None
  stdout = payload["tool_response"]["stdout"]
  if is_dev_lane(payload, command):
    return ("completed", None) if lane_completed(stdout) else None
  if re.search(r'[;&|`$<>\\\n\r()]', command):
    return None
  try:
    args = shlex.split(command)
  except ValueError:
    return None
  if len(args) != 3 or args[0] != "curl" or args[1] not in ("-fsS", "-sf", "-fs"):
    return None
  if not re.fullmatch(r'http://127\.0\.0\.1:(?:8787|8790)/api/health', args[2]):
    return None
  try:
    health = json.loads(stdout)
  except ValueError:
    return None
  if not isinstance(health, dict) or health.get("ok") is not True or health.get("deposed") is not False:
    return None
  version = health.get("version")
  if not isinstance(version, str) or not version:
    return None
  return ("health", (args[2], version))


def read_regular_tail(path):
  try:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as f:
      if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
        return ""
      f.seek(max(0, os.fstat(f.fileno()).st_size - 262144))
      return f.read(262144).decode("utf-8", errors="replace")
  except (OSError, ValueError, TypeError):
    return ""


def observe_background_deployments(payload, state):
  pending = state.get("pending_deployments", [])
  if not pending:
    return
  transcript = read_regular_tail(payload.get("transcript_path", ""))
  for line in transcript.splitlines():
    try:
      row = json.loads(line)
    except ValueError:
      continue
    if not isinstance(row, dict) or row.get("type") != "user":
      continue
    if row.get("sessionId") != payload.get("session_id"):
      continue
    if row.get("origin", {}).get("kind") != "task-notification" or row.get("promptSource") != "system":
      continue
    text = row.get("message", {}).get("content", "")
    if not isinstance(text, str):
      continue
    task = re.search(r'<task-id>([A-Za-z0-9_-]+)</task-id>', text)
    if not task or task[1] not in pending:
      continue
    if "<status>failed</status>" in text:
      pending.remove(task[1])
    elif "<status>completed</status>" in text and "(exit code 0)" in text:
      output = re.search(r'<output-file>([^\n<]+)</output-file>', text)
      if output and os.path.basename(output[1]) == task[1] + ".output":
        if lane_completed(read_regular_tail(output[1])):
          state["mut"] += 1
      pending.remove(task[1])


def save_state(path, state):
  try:
    with open(path, "w") as f:
      json.dump(state, f)
  except OSError:
    pass


def process(payload, state_path):
  tool = payload.get("tool_name", "")
  state = load_state(state_path)
  observe_background_deployments(payload, state)

  if tool in MUTATE_TOOLS:
    state["mut"] += 1
  elif tool == "Bash":
    cmd = (payload.get("tool_input") or {}).get("command", "").strip()
    response = payload.get("tool_response") or {}
    task = response.get("backgroundTaskId")
    if (payload.get("hook_event_name") == "PostToolUse" and response.get("interrupted") is False
        and isinstance(task, str) and re.fullmatch(r'[A-Za-z0-9_-]+', task) and is_dev_lane(payload, cmd)):
      pending = state.setdefault("pending_deployments", [])
      if task not in pending:
        pending.append(task)
    deployment = deployment_observation(payload, cmd)
    deployed = False
    if deployment:
      kind, value = deployment
      if kind == "completed":
        deployed = True
      else:
        endpoint, version = value
        versions = state.setdefault("deployment_versions", {})
        previous = versions.get(endpoint)
        deployed = previous is not None and previous != version
        versions[endpoint] = version
    if deployed or (is_completed_bash(payload) and PUSH_RE.fullmatch(cmd)):
      state["mut"] += 1
    elif len(cmd) < MIN_CMD_LEN or is_pure_sleep(cmd) or is_pure_focus_or_status(cmd):
      save_state(state_path, state)
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

  save_state(state_path, state)


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
