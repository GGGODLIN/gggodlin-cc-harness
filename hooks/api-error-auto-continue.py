#!/usr/bin/env python3
# 提示型 hook：互動 session 因可重試的 API 錯誤結束回合時，經 Herdr 在原 pane 代打接續句。
# 不承諾辨認所有暫時性錯誤，只認下方白名單；判不出來就什麼都不做（不打字）。
# 不保證接續後會成功：15 分鐘串流上限類的斷線，重試仍可能再撞同一上限，由連續上限止損。
# 不防使用者正在輸入時的字元交錯；送字前只確認 pane 內是同一個 session 且處於 idle/done。
# 停用：touch ~/.claude/state/api-error-auto-continue/DISABLED，或設環境變數 CC_AUTO_CONTINUE=0。
# 本檔在契約測試底下：python3 ~/.claude/hooks/api-error-auto-continue.test.py
import json
import math
import os
import re
import stat
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

CONTINUE_TEXT = "繼續原本的工作。（上一輪因系統斷線中斷，不是任務完成）"
MAX_CONSECUTIVE = 2
SEND_DELAY_SECONDS = 3
RATE_LIMIT_DELAY_SECONDS = 30
MAX_RATE_LIMIT_DELAY_SECONDS = 960
READY_POLL_SECONDS = 15
RETRYABLE_TYPES = {"server_error", "overloaded"}
# 中繼站在上游串流沒送完就斷線時固定回這句，CC 把它歸成 error=unknown
STREAM_CUT_MARKER = "stream disconnected before completion"
# 只收上游 HTTP 429 的 API Error，排除 Claude 訂閱自身的 "You've hit your ... limit"（由 cc-seat-swap 處理）
RATE_LIMIT_MARKER = "API Error: Request rejected (429)"
HELD_UNTIL_RE = re.compile(
  r"not asked again before (?:([A-Z][a-z]{2})\s+(\d{1,2})\s+)?(\d{2}):(\d{2})\s+UTC([+-])(\d{1,2})(?::(\d{2}))?"
)
MONTHS = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
          "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}


def state_dir():
  return Path(os.environ.get("CC_AUTO_CONTINUE_STATE_DIR") or Path.home() / ".claude/state/api-error-auto-continue")


def log_path():
  return Path(os.environ.get("CC_AUTO_CONTINUE_LOG") or Path.home() / ".claude/logs/api-error-auto-continue.jsonl")


def herdr_bin():
  return os.environ.get("HERDR_BIN_PATH") or "herdr"


def classify(payload):
  error = payload.get("error") or ""
  message = payload.get("last_assistant_message") or ""
  if error in RETRYABLE_TYPES:
    return error
  if error == "unknown" and STREAM_CUT_MARKER in message:
    return "stream_cut"
  if error == "rate_limit" and RATE_LIMIT_MARKER in message:
    return "rate_limit"
  return None


def rate_limit_delay(message, now=None):
  base = RATE_LIMIT_DELAY_SECONDS
  m = HELD_UNTIL_RE.search(message or "")
  if not m:
    return base
  mon_str, day_str, hh_str, mm_str, sign, off_h_str, off_m_str = m.groups()
  off_mins = int(off_h_str) * 60 + int(off_m_str or 0)
  tz = timezone(timedelta(minutes=off_mins if sign == "+" else -off_mins))
  cur = (now or datetime.now(timezone.utc)).astimezone(tz)
  month = MONTHS.get(mon_str, cur.month) if mon_str else cur.month
  day = int(day_str) if day_str else cur.day
  year = cur.year
  try:
    target = datetime(year, month, day, int(hh_str), int(mm_str), tzinfo=tz)
  except ValueError:
    return base
  if not mon_str and target < cur - timedelta(hours=12):
    target += timedelta(days=1)
  wait = math.ceil((target - cur).total_seconds()) + 2
  if wait <= base:
    return base
  return min(wait, MAX_RATE_LIMIT_DELAY_SECONDS)


def is_regular_or_absent(path):
  try:
    mode = os.lstat(path).st_mode
  except FileNotFoundError:
    return True
  return stat.S_ISREG(mode)


def log(record):
  path = log_path()
  try:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not is_regular_or_absent(path):
      return
    record = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **record}
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o644)
    with os.fdopen(fd, "a") as f:
      f.write(json.dumps(record, ensure_ascii=False) + "\n")
  except OSError:
    pass


# 只看結尾 64KB：對話記錄可達數 MB，entrypoint 每行都有，最後幾行就夠判斷
def transcript_entrypoint(path):
  if not path or not is_regular_or_absent(path) or not os.path.exists(path):
    return None
  with open(path, "rb") as f:
    f.seek(0, os.SEEK_END)
    f.seek(max(0, f.tell() - 65536))
    lines = f.read().decode("utf-8", "replace").splitlines()
  for line in reversed(lines):
    try:
      entry = json.loads(line)
    except ValueError:
      continue
    if entry.get("entrypoint"):
      return entry["entrypoint"]
  return None


def counter_path(session_id):
  return state_dir() / f"{session_id}.count"


def read_count(session_id):
  path = counter_path(session_id)
  if not is_regular_or_absent(path) or not path.exists():
    return 0
  try:
    return int(path.read_text().strip() or 0)
  except ValueError:
    return 0


def write_count(session_id, count):
  path = counter_path(session_id)
  path.parent.mkdir(parents=True, exist_ok=True)
  if not is_regular_or_absent(path):
    raise OSError("counter path is not a regular file")
  tmp = path.with_suffix(".tmp")
  tmp.write_text(str(count))
  os.replace(tmp, path)


def disabled():
  return os.environ.get("CC_AUTO_CONTINUE") == "0" or (state_dir() / "DISABLED").exists()


def spawn(args):
  subprocess.Popen(
    [sys.executable, os.path.abspath(__file__), *args],
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    start_new_session=True,
  )


def on_failure(payload):
  session_id = payload.get("session_id")
  kind = classify(payload)
  base = {"event": "failure", "session": session_id, "error": payload.get("error"), "kind": kind}
  if not kind or not session_id:
    log({**base, "action": "ignore"})
    return
  if disabled():
    log({**base, "action": "disabled"})
    return
  pane = os.environ.get("HERDR_PANE_ID")
  if os.environ.get("HERDR_ENV") != "1" or not pane:
    log({**base, "action": "no_herdr"})
    return
  # claude -p 子程序也會繼承 HERDR_PANE_ID；不擋的話它斷線時會把字打進父 pane。
  # 互動 session 的第一回合，hook 觸發時對話記錄常還沒落檔（讀到 None），留給 send 延遲後再判
  transcript = payload.get("transcript_path") or ""
  entrypoint = transcript_entrypoint(transcript)
  if entrypoint not in ("cli", None):
    log({**base, "action": "not_interactive", "entrypoint": entrypoint})
    return
  count = read_count(session_id)
  if count >= MAX_CONSECUTIVE:
    log({**base, "action": "cap_reached", "count": count})
    spawn(["--notify", session_id])
    return
  write_count(session_id, count + 1)
  if kind == "rate_limit":
    delay = rate_limit_delay(payload.get("last_assistant_message") or "")
    log({**base, "action": "continue_scheduled", "count": count + 1, "pane": pane, "delay": delay})
    spawn(["--send", pane, session_id, transcript, str(delay)])
  else:
    log({**base, "action": "continue_scheduled", "count": count + 1, "pane": pane})
    spawn(["--send", pane, session_id, transcript])


def herdr_json(*args):
  out = subprocess.run([herdr_bin(), *args], capture_output=True, text=True, timeout=10)
  return json.loads(out.stdout) if out.returncode == 0 and out.stdout.strip() else None


def send(pane, session_id, transcript, delay=None):
  time.sleep(SEND_DELAY_SECONDS if delay is None else float(delay))
  entrypoint = transcript_entrypoint(transcript)
  if entrypoint != "cli":
    log({"event": "send", "session": session_id, "action": "skip_not_interactive", "entrypoint": entrypoint, "pane": pane})
    return
  deadline = time.time() + READY_POLL_SECONDS
  status = None
  while time.time() < deadline:
    info = herdr_json("agent", "get", pane) or {}
    agent = (info.get("result") or {}).get("agent") or {}
    if (agent.get("agent_session") or {}).get("value") != session_id:
      log({"event": "send", "session": session_id, "action": "skip_session_mismatch", "pane": pane})
      return
    status = agent.get("agent_status")
    if status in ("idle", "done"):
      result = subprocess.run([herdr_bin(), "agent", "prompt", pane, CONTINUE_TEXT], capture_output=True, text=True, timeout=15)
      action = "sent" if result.returncode == 0 else "send_failed"
      log({"event": "send", "session": session_id, "action": action, "pane": pane, "stderr": result.stderr[-300:]})
      return
    time.sleep(1)
  log({"event": "send", "session": session_id, "action": "skip_not_ready", "status": status, "pane": pane})


def notify(session_id):
  result = subprocess.run(
    [herdr_bin(), "notification", "show", "API 錯誤自動接續已達上限",
     "--body", f"連續 {MAX_CONSECUTIVE} 次接續後仍斷線，請回 session 手動處理（{session_id[:8]}）",
     "--sound", "request"],
    capture_output=True, text=True, timeout=10,
  )
  log({"event": "notify", "session": session_id, "action": "notified" if result.returncode == 0 else "notify_failed", "stderr": result.stderr[-300:]})


def on_stop(payload):
  session_id = payload.get("session_id")
  if not session_id:
    return
  path = counter_path(session_id)
  if path.exists() and is_regular_or_absent(path):
    count = read_count(session_id)
    path.unlink()
    log({"event": "reset", "session": session_id, "count": count})


def main(argv):
  try:
    if argv[:1] == ["--send"]:
      delay = float(argv[4]) if len(argv) > 4 else None
      send(argv[1], argv[2], argv[3], delay)
      return
    if argv[:1] == ["--notify"]:
      notify(argv[1])
      return
    payload = json.load(sys.stdin)
    if argv[:1] == ["stop"]:
      on_stop(payload)
    else:
      on_failure(payload)
  except Exception as exc:
    # 提示型：自己出錯就什麼都不做，不擋 session，也不打字
    log({"event": "internal_error", "error": repr(exc)[:300]})


if __name__ == "__main__":
  main(sys.argv[1:])
  sys.exit(0)
