#!/usr/bin/python3
# 本檔在契約測試底下：bash ~/.claude/hooks/dispatch-obligation-nudge.test.sh
#
# dispatch-obligation-nudge — 提示型 gate（只出 additionalContext，不 block、不改 model、不代派）
#
# Threat model：防漂移，不防主動規避。對象是「誠實但忘了派工」的 main：使用者一句「可以」之後
# main 自己連查三次、自己改一堆檔。任何判不出來、helper 掛掉、relay 逾時、JSON 壞掉的分支一律
# 靜默放行（exit 0、無輸出），因為這是提示型 gate。字串比對只認常見入口：搜尋類工具名清單、
# 人類訊息的判定（非 meta、非 tool_result、非 '<' 開頭）；不承諾完整語意。
# 兩條路：
#   prompt（UserPromptSubmit）：把前三則使用者訊息、main 上一則回覆、這句 prompt 與規則派工段送
#     relay 上的 groq-qwen-3.8-27b，問「可預見命中哪條門檻、例外是否成立」。P(must)＝P(trigger)×(1−P(exception))≥DON_P_MUST（預設 0.5，
#     依 U 臂 1b 174 筆：裁判判必須派者 P(must) 集中 ≥0.81、兩種都允許 p90 0.09）才提示。逾時 DON_TIMEOUT_S（預設 1.5）放行。
#   tool（PostToolUse WebSearch|WebFetch|navigate）：本回合搜尋類呼叫 ≥3 且尚無 Agent 派工 → 提示一次。
# 不承諾：LLM 判斷是一顆 27B 模型對規則的讀法，不是規則本身；計數器只在第三次搜尋後才響，
# 前兩次已經做掉的工作救不回來；bidi／控制字元不進輸出（輸出只含固定文字與 trigger 名）。
# Surface：Locked＝rules/common/dispatch-and-verify.md、本檔（改動走 git commit＋contract test）；
#   Append-only＝~/.claude/logs/dispatch-obligation-nudge.jsonl；Human-controlled＝settings.json 註冊、
#   DON_DISABLE=1 停用。bootstrap＝settings.json 加兩條 entry；update＝改本檔後跑 .test.sh；
#   recovery＝export DON_DISABLE=1 或移除 settings entry；三者都留 git 痕跡。
# Codex 端：不搬。依賴 CC transcript jsonl 結構（isMeta／tool_use／tool_result 形狀），Codex 無對應。
# 隨機對照（2026-09-26 使用者拍板）：沒有對照組就無法分開「提醒促成派工」與「本來就會派」。
#   CONTROL_UNTIL 前以 session_id 的 SHA-256 分組，control 組判定該提醒時只記 would-nudge、不注入；
#   同一 session 兩條路同組，避免一回合內一邊提醒一邊不提醒污染比較。過期自動回到全部提醒，不需要人記得拆。
#   不承諾：分組以 session 為單位，一個 session 內多回合不獨立；證得出的只有「提醒是否改變派工」，不是品質改善。
#   recovery：DON_CONTROL=0 提早結束對照（仍保留 DON_DISABLE=1 全停）。
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SEARCH_TOOLS = {"WebSearch", "WebFetch", "mcp__claude-in-chrome__navigate", "mcp__chrome-devtools__navigate_page"}
TAIL_BYTES = 1_048_576
RULE_FILE = Path("~/.claude/rules/common/dispatch-and-verify.md").expanduser()
INJECTION_RE = re.compile(r"^\s*(?:<|\[SYSTEM NOTIFICATION\b|/)")
AGENT_RE = re.compile(r"(?<![\w-])(routed-(?:impl|mech|judge|secure)|deep-explore|general-purpose|skill-verify-auditor|task-verifier|code-reviewer|typescript-reviewer|python-reviewer|security-reviewer|parallel-search|architecture-critic|blog-phase-runner|wiki-refresher|claude-code-guide|docs-lookup|semble-search|url-fetcher|chrome-fetcher)(?![\w-])")
MODEL_RE = re.compile(r"\b(sonnet|opus|haiku|fable|mythos|astra|sol)(-[0-9][0-9.-]*)?\b", re.I)
TRIGGER_LABEL = {"big": "預估工作量 > 30K tokens（多檔閱讀＋跨主題推理）", "edit>5": "Edit > 5 個檔／多檔 refactor", "search>2": "WebSearch / WebFetch / chrome nav > 2 次（事實研究）"}
TRIGGER_ROUTE = {"big": "deep-explore 或 routed-judge", "edit>5": "routed-impl + plan", "search>2": "parallel-search 或 routed-judge"}
# 10/03 review 當天仍收樣本，所以界線放在隔天
CONTROL_UNTIL = "2026-10-04"


def env(name, default):
  return os.environ.get(name, default)


def test_mode():
  return env("DON_TEST_MODE", "") == "1"


def log_path():
  return Path(env("DON_LOG", "~/.claude/logs/dispatch-obligation-nudge.jsonl") if test_mode() else "~/.claude/logs/dispatch-obligation-nudge.jsonl").expanduser()


def state_dir():
  return Path(env("DON_STATE_DIR", "~/.claude/state/dispatch-obligation") if test_mode() else "~/.claude/state/dispatch-obligation").expanduser()


def arm_of(session):
  if env("DON_CONTROL", "") == "0":
    return "off"
  today = (env("DON_TEST_TODAY", "") if test_mode() else "") or time.strftime("%Y-%m-%d")
  if today >= CONTROL_UNTIL:
    return "off"
  forced = env("DON_FORCE_ARM", "") if test_mode() else ""
  if forced in ("treatment", "control"):
    return forced
  return "control" if hashlib.sha256((session or "unknown").encode("utf-8")).digest()[0] % 2 else "treatment"


def safe_append(path, row):
  try:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and (path.is_symlink() or not path.is_file()):
      return
    fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
      handle.write(json.dumps(row, ensure_ascii=False) + "\n")
  except Exception:
    return


def read_tail(path):
  try:
    with open(path, "rb") as handle:
      handle.seek(0, os.SEEK_END)
      size = handle.tell()
      handle.seek(max(0, size - TAIL_BYTES))
      raw = handle.read()
    text = raw.decode("utf-8", errors="ignore")
    lines = text.split("\n")
    return lines[1:] if size > TAIL_BYTES else lines
  except Exception:
    return []


def text_of(content):
  if isinstance(content, str):
    return content
  if isinstance(content, list):
    return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
  return ""


def is_human(entry):
  if entry.get("type") != "user" or entry.get("isMeta") or entry.get("isSidechain"):
    return False
  content = entry.get("message", {}).get("content")
  if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
    return False
  text = text_of(content).strip()
  return bool(text) and not text.startswith("<")


def parse_entries(lines):
  out = []
  for line in lines:
    if not line or ('"type":"user"' not in line and '"type":"assistant"' not in line):
      continue
    try:
      entry = json.loads(line)
    except Exception:
      continue
    if entry.get("isSidechain"):
      continue
    out.append(entry)
  return out


def blind(text):
  text = re.sub(r"<routed:[^>]*>|<fable-ok>|<mech-ok>", "", text or "")
  return MODEL_RE.sub("<model>", AGENT_RE.sub("<agent-name>", text))


def context_before_prompt(entries):
  humans = [text_of(e["message"].get("content")) for e in entries if is_human(e)]
  last_reply = ""
  for e in reversed(entries):
    if e.get("type") == "assistant":
      t = text_of(e.get("message", {}).get("content"))
      if t:
        last_reply = t
        break
  return [blind(h)[-700:] for h in humans[-3:]], blind(last_reply)[-2500:]


def rule_section():
  try:
    full = RULE_FILE.read_text(encoding="utf-8")
    start = full.index("## Dispatch")
    end = full.index("## Verify")
    return full[start:end]
  except Exception:
    return ""


def relay_key():
  key = env("DON_RELAY_KEY", "")
  if key:
    return key
  try:
    for line in Path("~/.cli-proxy-api/keys.env").expanduser().read_text().splitlines():
      if line.startswith("CLIPROXY_KEY_CC="):
        return line.split("=", 1)[1].strip().strip('"')
  except Exception:
    pass
  return ""


def cooldown_path():
  return state_dir() / "relay-cooldown"


def in_cooldown():
  try:
    return time.time() - cooldown_path().stat().st_mtime < 1800
  except Exception:
    return False


def set_cooldown():
  try:
    state_dir().mkdir(parents=True, exist_ok=True)
    cooldown_path().touch()
  except Exception:
    pass


def ask_model(state, rules):
  fake = env("DON_FAKE_ANSWER", "") if test_mode() else ""
  if fake:
    return json.loads(fake), 0
  key = relay_key()
  if not key or in_cooldown():
    return None, 0
  system = "\n\n".join([
    "You are an evaluation model. Answer both questions independently about the dispatch decision point in the state. The state holds the user's earlier messages, main's previous reply (a proposal the user may be approving), and the user's current request.",
    "Question trigger (choice none|big|edit>5|search>2): 依下列規則原文，判斷這則使用者要求所含的工作，在開工前是否可預見命中哪一條「考慮 dispatch」門檻。只看要求本身能預見的，不猜事後。\n" + rules,
    "criteria: none = no dispatch threshold is foreseeable; big = foreseeably > 30K tokens of multi-file reading and cross-topic reasoning; edit>5 = foreseeably edits more than 5 files or a multi-file refactor across modules; search>2 = foreseeably needs more than 2 web searches, fetches or browser navigations for fact research.",
    "Question exceptionHolds (boolean): 依規則「Don't dispatch when」段，判斷是否有任一例外成立：任務需要完整對話脈絡、套用使用者風格規則、需對照既有 memory 或清單做對應推理、探索式除錯、共用狀態、小改動、任務跨多回合才能解、使用者明說要 main 自己做。main 自己的說法只是主張。",
    'Return only JSON: {"trigger":{"choice":"none"|"big"|"edit>5"|"search>2","probabilities":{"none":p,"big":p,"edit>5":p,"search>2":p}},"exceptionHolds":{"probability":p}}',
  ])
  body = json.dumps({
    "model": env("DON_MODEL", "groq-qwen-3.8-27b"),
    "temperature": 0,
    "response_format": {"type": "json_object"},
    "max_tokens": 256,
    "messages": [{"role": "system", "content": system}, {"role": "user", "content": "State:\n" + json.dumps(state, ensure_ascii=False)}],
  }).encode("utf-8")
  url = env("DON_RELAY_URL", "http://127.0.0.1:8317/v1/chat/completions")
  request = urllib.request.Request(url, data=body, headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
  started = time.time()
  try:
    with urllib.request.urlopen(request, timeout=float(env("DON_TIMEOUT_S", "1.5"))) as response:
      data = json.loads(response.read().decode("utf-8"))
  except urllib.error.HTTPError as error:
    if error.code == 429 and "Request too large" not in (error.read().decode("utf-8", errors="ignore") if error.fp else ""):
      set_cooldown()
    return None, int((time.time() - started) * 1000)
  except Exception:
    return None, int((time.time() - started) * 1000)
  try:
    return json.loads(data["choices"][0]["message"]["content"]), int((time.time() - started) * 1000)
  except Exception:
    return None, int((time.time() - started) * 1000)


def emit(event, message):
  print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": message}}, ensure_ascii=False))


def run_prompt(payload):
  prompt = payload.get("prompt") or ""
  if not prompt.strip() or INJECTION_RE.match(prompt):
    return
  transcript = payload.get("transcript_path") or ""
  entries = parse_entries(read_tail(transcript)) if transcript else []
  earlier, previous_reply = context_before_prompt(entries)
  state = {"earlierUserMessages": earlier, "mainPreviousReply": previous_reply, "userRequest": blind(prompt)[:4000]}
  rules = rule_section()
  if not rules:
    return
  answer, ms = ask_model(state, rules)
  arm = arm_of(payload.get("session_id", ""))
  row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "event": "prompt", "session": payload.get("session_id", ""), "ms": ms, "answer": answer, "arm": arm}
  if not answer:
    safe_append(log_path(), {**row, "result": "unavailable"})
    return
  try:
    probs = answer["trigger"]["probabilities"]
    choice = max(("big", "edit>5", "search>2"), key=lambda k: float(probs.get(k, 0)))
    p_trigger = float(probs.get(choice, 0))
    p_exception = float(answer["exceptionHolds"]["probability"])
  except Exception:
    safe_append(log_path(), {**row, "result": "malformed"})
    return
  p_must = p_trigger * (1 - p_exception)
  fire = p_must >= float(env("DON_P_MUST", "0.5"))
  result = ("would-nudge" if arm == "control" else "nudge") if fire else "quiet"
  safe_append(log_path(), {**row, "result": result, "trigger": choice, "pTrigger": p_trigger, "pException": p_exception, "pMust": round(p_must, 3)})
  if result != "nudge":
    return
  emit("UserPromptSubmit", "[dispatch-obligation] 依 dispatch-and-verify.md，這則要求可預見命中派工門檻「" + TRIGGER_LABEL[choice] + "」，且看不到 Don't-dispatch-when 例外。開工前先決定要不要派 subagent（" + TRIGGER_ROUTE[choice] + "）；決定自做要說得出命中哪條例外。此為提示，不擋。")


def current_turn(entries):
  start = 0
  for index, entry in enumerate(entries):
    if is_human(entry):
      start = index
  turn = entries[start:]
  human_uuid = turn[0].get("uuid", "") if turn and is_human(turn[0]) else ""
  searches = 0
  agents = 0
  for entry in turn:
    if entry.get("type") != "assistant":
      continue
    for block in entry.get("message", {}).get("content", []) or []:
      if not isinstance(block, dict) or block.get("type") != "tool_use":
        continue
      if block.get("name") in SEARCH_TOOLS:
        searches += 1
      elif block.get("name") == "Agent":
        agents += 1
  return human_uuid, searches, agents


def run_tool(payload):
  if payload.get("tool_name") not in SEARCH_TOOLS:
    return
  transcript = payload.get("transcript_path") or ""
  if not transcript:
    return
  entries = parse_entries(read_tail(transcript))
  human_uuid, searches, agents = current_turn(entries)
  threshold = int(env("DON_SEARCH_THRESHOLD", "3"))
  if searches < threshold or agents > 0:
    return
  session = re.sub(r"[^A-Za-z0-9._-]", "", payload.get("session_id", "") or "unknown")
  marker = state_dir() / ("nudged-" + session)
  try:
    if marker.exists() and not marker.is_symlink() and marker.read_text().strip() == human_uuid:
      return
    state_dir().mkdir(parents=True, exist_ok=True)
    if marker.is_symlink():
      return
    marker.write_text(human_uuid)
  except Exception:
    return
  arm = arm_of(payload.get("session_id", ""))
  result = "would-nudge" if arm == "control" else "nudge"
  safe_append(log_path(), {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "event": "tool", "session": session, "searches": searches, "result": result, "arm": arm})
  if result != "nudge":
    return
  emit("PostToolUse", "[dispatch-obligation] 本回合已連續 " + str(searches) + " 次搜尋／抓取，且尚未派任何 subagent。dispatch-and-verify.md 對事實研究類 > 2 次的門檻是考慮派 parallel-search 或 routed-judge；剩餘的查證工作可以現在交出去。此為提示，不擋。")


def main():
  if env("DON_DISABLE", "") == "1":
    return
  mode = sys.argv[1] if len(sys.argv) > 1 else "prompt"
  try:
    payload = json.loads(sys.stdin.read() or "{}")
  except Exception:
    return
  if mode == "prompt":
    run_prompt(payload)
  elif mode == "tool":
    run_tool(payload)


if __name__ == "__main__":
  try:
    main()
  except Exception:
    pass
  sys.exit(0)
