#!/usr/bin/env python3
# 提示型 hook，防一般模式與自動模式的規則漂移。工具權限和程式 gate 仍由各自判定，狀態讀取失敗就不注入。
# 通知喚醒的主 session 也需要規則，因為壓縮後可能沒有前一回合的注入。子代理與 SDK 只靠既有身分訊號辨識。
# Surface：hook、測試與 settings 註冊走正常版本控制。開關由真人控制，hook 只讀狀態，不寫紀錄。
# 接線後跑契約測試，更新 hook 或狀態 helper 時重跑。復原可關閉自動模式或移除 settings 註冊。
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import UUID

AUTO_MODE_DIR = Path(__file__).resolve().parents[1] / "scripts" / "auto-mode"
MODE = AUTO_MODE_DIR / "mode.py"
sys.path.insert(0, str(AUTO_MODE_DIR))
from decision import DOWNWEIGHTED_ACTIONS, WEB_GPT_PRO  # noqa: E402

CHILD_ENV = ("CLAUDE_AGENT_ID", "CLAUDE_CODE_AGENT_ID", "PI_SUBTASK_JOB_ID")
_DOWNWEIGHT_CSV = ", ".join(sorted(DOWNWEIGHTED_ACTIONS))
RULE = f"""自動模式已開啟。以下 CLI 在 ~/.claude/scripts/auto-mode/；以 python3 -IB 執行，無終端機鍵時用 --session 帶本回合 session ID。
每個停點先以 mode.py status 的 enabled 呼叫 decision.py decide（命中壓低或特檢操作時 action 欄必須逐字使用此標準清單：壓低清單 {_DOWNWEIGHT_CSV}；工作區特檢 {WEB_GPT_PRO}；其餘非壓低停點填描述性非空 ID）。壓低清單優先：不做，走保守替代（如不 push、留本機分支；第三方 Fable 改派 Codex Astra）。只在 allow-auto 時依序採用選單標示的推薦 → 該停點既有的『沒回覆就走 X』預設，不等回覆。兩者皆無就照一般模式問；require-human 也照常問。
外部審查與顧問選席預設 Codex Astra；預檢確認個人工作區且 decision.py 放行才加開網頁 GPT Pro，材料範圍按 context_mode。
覆寫只限依推薦或預設處理且未壓低的停點，優先於各檔「照推薦不算授權／沉默不授權／需使用者明選」；其他停點照舊。見 ADR 0012（openspec/decisions/0012-auto-mode-standing-authorization.md）。
每筆照推薦或預設及每筆壓低都以 records.py append 記錄；文字停點可同回合批次寫，結案前寫完。呼叫 review-spec Tier 3 finalize 時帶 --task <本任務 task>。結案用 records.py closeout --task 列本任務清單（壓低在前），即使中途關閉也要列，並用 records.py stats 回報維持率、未審數與已審涵蓋率。"""


def is_main_prompt_submit(payload):
  if not isinstance(payload, dict) or payload.get("hook_event_name") != "UserPromptSubmit":
    return False
  if (payload.get("agent_id") or payload.get("isSidechain")
      or any(os.environ.get(name) for name in CHILD_ENV)
      or os.environ.get("CLAUDE_CODE_ENTRYPOINT", "").startswith("sdk")):
    return False
  transcript = payload.get("transcript_path")
  if isinstance(transcript, str) and "subagents" in Path(transcript).parts:
    return False
  origin = payload.get("origin")
  return not (payload.get("turnOrigin") == "sdk" or payload.get("promptSource") == "sdk"
              or (isinstance(origin, dict) and origin.get("kind") == "sdk"))


def main():
  try:
    payload = json.load(sys.stdin)
    if not is_main_prompt_submit(payload):
      return
    session = payload.get("session_id")
    if not isinstance(session, str):
      return
    session = UUID(session)
    # A slow or unreadable state must not hold up the prompt or imply standing authorization.
    result = subprocess.run(
      [sys.executable, "-IB", str(MODE), "--session", str(session), "status"],
      stdin=subprocess.DEVNULL, capture_output=True, timeout=2, check=True,
    )
    status = json.loads(result.stdout)
  except (OSError, ValueError, RecursionError, subprocess.SubprocessError):
    return
  if isinstance(status, dict) and status.get("enabled") is True:
    print(json.dumps({"hookSpecificOutput": {
      "hookEventName": "UserPromptSubmit", "additionalContext": RULE,
    }}, ensure_ascii=False))


if __name__ == "__main__":
  main()
