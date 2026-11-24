#!/usr/bin/env python3
# 提示型 UserPromptSubmit hook。threat model：防漂移、不防規避——Opus 5.5 在背景任務通知喚醒的回合會跟著英文通知回英文
# （統計顯示背景通知喚醒後容易意外切換回英文回覆；
# opus-chinese-stop.py 當時跳過背景任務進行中的回合，所以事後提醒接不到這些；2026-10-13 起 stop hook 已改為背景任務進行中照常送出單次提醒），本 hook 改在回合開始前注入一行繁中提醒。
# 只認常見入口：prompt 含 <task-notification> 或 [SYSTEM NOTIFICATION 才算通知回合，不承諾完整語意；
# 判不出來（模型未知、transcript 讀不到、匯入 stop hook 失敗）一律不注入——提示型 gate 判不出來放行。
# 不保證：人類 prompt 內引用通知字樣會被當通知（代價是多一行看不見的注入）；session 中途 /model 切換後第一回合按舊模型判；
# 不證明注入後模型一定用中文，效果看 trial 的 rule-adherence ledger。
# 停用：環境變數 OPUS_CHINESE_NUDGE_OFF=1，或 touch ~/.claude/state/opus-chinese-nudge.off（刪掉即恢復）。
# 本檔在契約測試底下：python3 ~/.claude/hooks/opus-chinese-nudge.test.py
import importlib.util
import json
import os
import sys
from pathlib import Path

MARKERS = ("<task-notification>", "[SYSTEM NOTIFICATION")
REMINDER = (
  "[opus-chinese-nudge] 這個回合是背景任務通知喚醒的。使用者的預設回覆語言是繁體中文："
  "進度回報、等待說明與結案都用繁體中文；通知內容是英文不代表要用英文回。"
)


def load_stop_hook():
  path = Path(__file__).with_name("opus-chinese-stop.py")
  spec = importlib.util.spec_from_file_location("opus_chinese_stop", path)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


# 只看主線最後一則 assistant 的 model 欄；sidechain（subagent）不算，和 stop hook 的 transcript_turn 同口徑。
def transcript_model(path):
  model = None
  with open(path, encoding="utf-8") as source:
    for raw in source:
      try:
        entry = json.loads(raw)
      except json.JSONDecodeError:
        continue
      if entry.get("isSidechain") or entry.get("type") != "assistant":
        continue
      message = entry.get("message")
      current = message.get("model") if isinstance(message, dict) else None
      if isinstance(current, str) and current:
        model = current
  return model


def disabled():
  if os.environ.get("OPUS_CHINESE_NUDGE_OFF") == "1":
    return True
  state_dir = Path(os.environ.get("OPUS_CHINESE_NUDGE_STATE_DIR", str(Path.home() / ".claude/state")))
  return (state_dir / "opus-chinese-nudge.off").exists()


def main():
  try:
    payload = json.load(sys.stdin)
    if not isinstance(payload, dict) or payload.get("hook_event_name") != "UserPromptSubmit" or payload.get("agent_id"):
      return
    prompt = payload.get("prompt")
    transcript = payload.get("transcript_path")
    session_id = payload.get("session_id")
    if not all(isinstance(value, str) and value for value in (prompt, transcript, session_id)):
      return
    if not any(marker in prompt for marker in MARKERS):
      return
    if disabled():
      return
    stop = load_stop_hook()
    # user_time 給 None：通知回合一定在 assistant 講過話之後，沒有 model 欄就不靠快取補位、直接不注入。
    if stop.active_model(payload, transcript_model(transcript), None) != stop.OPUS:
      return
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": REMINDER}}, ensure_ascii=False))
  except Exception:
    return


if __name__ == "__main__":
  main()
