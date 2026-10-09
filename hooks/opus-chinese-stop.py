#!/usr/bin/env python3
# 提示型 Stop hook：只認常見的整段英文結案，不承諾完整語意；判不出來就放行。
# 不能阻止第一份英文顯示，也不能保證 Opus 接受提醒；不處理中途進度或刻意繞過。
# 本檔在契約測試底下：python3 ~/.claude/hooks/opus-chinese-stop.test.py
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
from datetime import datetime
from pathlib import Path

OPUS = "claude-opus-5-5"
HAN = re.compile(r"[㐀-鿿]")
LATIN = re.compile(r"[A-Za-z]")
WORDS = re.compile(r"\b[A-Za-z]{2,}\b")
ENGLISH_REQUEST = re.compile(
  r"(?:請|麻煩|要|用|以|改用|回答|回覆|輸出|翻譯|寫|改寫).{0,15}(?:英文|英語|English)"
  r"|\b(?:answer|respond|reply|write|output|draft|summarize|translate)\b.{0,60}\b(?:in|to|into)\s+English\b"
  r"|\bEnglish\s+please\b",
  re.IGNORECASE,
)
NEGATIVE_ENGLISH = re.compile(
  r"(?:不要|別|避免|不得|禁止|勿)[^，。；;,\n]{0,15}(?:英文|英語|English)"
  r"|\b(?:do not|don't|never|avoid|no)\b[^,;.!?\n]{0,40}\bEnglish\b",
  re.IGNORECASE,
)
REMINDER = (
  "[opus-chinese-stop] 使用者的預設回覆語言是繁體中文；剛才的結案說明主要是英文。"
  "請以繁體中文重述相同的結論與必要資訊，不增減內容，也不要重跑已完成的工具工作。"
)


def natural_text(text):
  text = re.sub(r"<pasted_content\b[^>]*>.*?</pasted_content>", "", text, flags=re.DOTALL)
  text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
  text = re.sub(r"(?m)^\s*>.*$", "", text)
  text = re.sub(r"`[^`\n]*`", "", text)
  text = re.sub(r"(?:https?://|file://)\S+", "", text)
  return text


def english_dominant(text):
  prose = natural_text(text)
  latin = len(LATIN.findall(prose))
  han = len(HAN.findall(prose))
  return latin >= 45 and len(WORDS.findall(prose)) >= 7 and latin / (latin + han) >= 0.9


def user_wants_chinese(text):
  text = natural_text(text)
  return not ENGLISH_REQUEST.search(NEGATIVE_ENGLISH.sub("", text))


# 背景通知喚醒的回合常是長任務真正的結案；語言意圖沿用前一則人類訊息，
# 提醒次數也記在那則人類訊息上，避免每個通知回合各提醒一次。
def transcript_turn(path, prompt_id):
  human_text = None
  human_id = None
  user_text = None
  anchor_id = None
  user_time = None
  model = None
  with open(path, encoding="utf-8") as source:
    for raw in source:
      try:
        entry = json.loads(raw)
      except json.JSONDecodeError:
        continue
      if entry.get("isSidechain") or entry.get("isMeta"):
        continue
      message = entry.get("message")
      if not isinstance(message, dict):
        continue
      origin = entry.get("origin")
      kind = origin.get("kind") if isinstance(origin, dict) else None
      if entry.get("type") == "user" and kind in ("human", "task-notification"):
        if kind == "human":
          content = message.get("content")
          human_text = content if isinstance(content, str) else None
          human_id = entry.get("promptId")
        current_turn = entry.get("promptId") == prompt_id
        user_text = human_text if current_turn else None
        anchor_id = human_id if current_turn else None
        user_time = entry.get("timestamp") if current_turn else None
        model = None
      elif user_text is not None and entry.get("type") == "assistant":
        current = message.get("model")
        if isinstance(current, str) and current:
          model = current
  return user_text, anchor_id, user_time, model


def normalized_model(value):
  return value.removesuffix("[1m]") if isinstance(value, str) else ""


def active_model(payload, transcript_model, user_time):
  session_id = payload["session_id"]
  cache_root = Path(os.environ.get("OPUS_CHINESE_STOP_MODEL_CACHE_DIR", "/tmp/cc-widget-cache"))
  cache = cache_root / f"model-{session_id}.txt"
  cached = ""
  cached_time = 0
  try:
    if cache.is_file() and not cache.is_symlink():
      cached = normalized_model(cache.read_text().strip())
      cached_time = cache.stat().st_mtime
  except OSError:
    pass
  recorded = normalized_model(transcript_model)
  if recorded and cached and recorded != cached:
    return ""
  if recorded:
    return recorded
  try:
    submitted = datetime.fromisoformat(user_time.replace("Z", "+00:00")).timestamp()
  except (AttributeError, ValueError):
    return ""
  return cached if cached_time >= submitted else ""


def mark_once(root, session_id, prompt_id):
  try:
    root.mkdir(mode=0o700, exist_ok=True)
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
      return False
    name = hashlib.sha256(session_id.encode()).hexdigest() + ".json"
    fd = os.open(root / name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(fd, "r+", encoding="utf-8") as marker:
      fcntl.flock(marker, fcntl.LOCK_EX)
      info = os.fstat(marker.fileno())
      if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_mode & 0o077:
        return False
      previous = marker.read(4097)
      if len(previous) > 4096:
        return False
      saved = json.loads(previous) if previous else {}
      if not isinstance(saved, dict) or saved.get("prompt_id") == prompt_id:
        return False
      marker.seek(0)
      marker.write(json.dumps({"prompt_id": prompt_id}))
      marker.truncate()
      return True
  except (OSError, ValueError, UnicodeError):
    return False


def main():
  try:
    payload = json.load(sys.stdin)
    if not isinstance(payload, dict) or payload.get("hook_event_name") != "Stop" or payload.get("agent_id"):
      return
    tasks = payload.get("background_tasks")
    crons = payload.get("session_crons")
    if not isinstance(tasks, list) or not isinstance(crons, list) or tasks or crons:
      return
    session_id = payload.get("session_id")
    prompt_id = payload.get("prompt_id")
    transcript = payload.get("transcript_path")
    text = payload.get("last_assistant_message")
    if not all(isinstance(value, str) and value for value in (session_id, prompt_id, transcript, text)):
      return
    if not english_dominant(text):
      return
    user_text, anchor_id, user_time, transcript_model = transcript_turn(transcript, prompt_id)
    if user_text is None or not isinstance(anchor_id, str) or not user_wants_chinese(user_text):
      return
    if active_model(payload, transcript_model, user_time) != OPUS:
      return
    root = Path(os.environ.get("OPUS_CHINESE_STOP_STATE_DIR", str(Path.home() / ".claude/hooks/state/opus-chinese-stop")))
    if not mark_once(root, session_id, anchor_id):
      return
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": REMINDER}}, ensure_ascii=False))
  except (OSError, ValueError, TypeError, AttributeError, UnicodeError):
    return


if __name__ == "__main__":
  main()
