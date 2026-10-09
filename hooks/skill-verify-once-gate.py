#!/usr/bin/env python3
# 本檔在契約測試底下：python3 ~/.claude/hooks/skill-verify-once-gate.test.py
#
# Threat model（先讀這段再改規則）
#
# 型別：安全型 gate。擋的是「同一個真人回合裡對同一個 skill 做第二次 Self-Verify 稽查」。
# 判不出來的分支一律 deny。
#
# 對誰有效：防漂移——誠實但健忘的 main 在首輪 FAIL 後順手再派一次 auditor，或改去
# SendMessage 續問第一個 auditor 要它重判。這兩條是 production 真的發生過的形狀。
#
# 明文不保證：
#   - 不防主動規避。把同一份 rubric 改派給 routed-judge、task-verifier 或任何
#     subagent_type != skill-verify-auditor 的 agent，本 gate 不攔（見 test_uncovered_*）。
#     字串比對型 gate 對刻意繞行一律不承諾，這裡不假裝例外。
#   - marker 比對認的是常見入口（description、prompt 裡的 `skill-verify:<name>`），
#     不做語意理解；認不出來就 fail closed，不猜。
#   - 會攔到「談論該 marker 的文字」而不只「真的在派 auditor」：prompt 裡引用了
#     別的 skill 的 Self-Verify 段落原文，也會被算成那個 skill 的 key。替代路徑是
#     把引用內容改成不含冒號的寫法（`skill-verify 標記 foo`），deny 訊息會說。
#   - SendMessage 只精準擋已識別的 auditor（agentId 完全相符，或 target 字串帶
#     auditor 型別名）。認不出的 target 一律放行，不全域封鎖其他 SendMessage。
#     身分來源有兩個：transcript 的派工配對（主力、live 實測擋下過），以及 post-agent
#     模式的側錄快取（輔助）。auditor 走 async 派工，PostToolUse 要等 agent 跑完才觸發，
#     短命的 headless session 根本到不了那一刻——兩次 live run 都沒留下側錄，擋下 SendMessage
#     的是 transcript 那條。side 快取的 live firing 未驗證，不要當成保護的依據。
#   - 額度只記「用過沒有」，不判 PASS／FAIL／FIXED。狀態是 caller 的責任。
#   - 額度是「每個 caller（main 或單一 subagent）× 回合 × skill」一次，不是整個回合一次。
#     跨 caller 的同一份工作重審不擋，包含無心發生的：subagent 稽查 FAIL 後 main 接手再稽查、
#     main 稽查 FAIL 後另開 subagent 重做並稽查。hook 欄位看不出兩次稽查是不是同一份交付物；
#     改回整回合共用會誤擋同回合平行或先後的獨立 subagent（2026-09-22 → 09-29 觀察期 3 起）。
#   - 「回合」= 從外部發起這一輪的請求者，涵蓋真人打字／真人 slash command，以及 headless
#     的 sdk prompt（claude -p 實測 origin 缺席、turnOrigin=sdk）。只認真人會讓所有
#     headless 與 /goal 流程的 Self-Verify 全被 deny，那是靜默打斷功能、不是保護。
#   - 不依賴 settings.json 的 hook 陣列順序；三個掛點各自獨立、可並行。
#
# 自身生命週期（Locked surface 的三條路）
#   bootstrap：本檔與其 settings 註冊由一般 Edit/Write 寫入，gate 不保護自己的原始碼。
#   update：同上；改完跑 skill-verify-once-gate.test.py。
#   recovery：建立 sentinel（預設 ~/.claude/.skill-verify-once-disabled，可用
#             SKILL_VERIFY_ONCE_DISABLED 覆寫）即全模式放行；既有 claim 不清空。

import hashlib
import json
import os
import re
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path

GATE = "skill-verify-once"
AUDITOR_TYPE = "skill-verify-auditor"
AGENT_TOOLS = {"Agent", "Task"}

MARKER_RE = re.compile(r"skill-verify:([A-Za-z0-9][A-Za-z0-9._-]{0,63})")
AGENT_ID_RE = re.compile(r"agentId:\s*([0-9A-Za-z_-]{6,64})")
LAUNCH_OK_RE = re.compile(r"agent launched successfully", re.I)
SAFE_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,128}")

TURN_ORIGINS = {"human", "sdk"}
BLOCKED_ORIGINS = {"task-notification", "peer", "system", "injection", "hook"}

TRANSCRIPT_CHUNK_BYTES = 64 * 1024

DENY_QUOTA = (
  "本回合此 skill 的 Self-Verify 額度已使用。不得重派或續問 auditor。"
  "依第一次結果處理；沒有有效結果就揭露未完成稽查，不得宣稱修正或驗證通過。"
)


def emit(payload):
  print(json.dumps(payload, ensure_ascii=False))
  return 0


def passthrough():
  return emit({})


def decision(event, value, reason):
  return emit(
    {
      "hookSpecificOutput": {
        "hookEventName": event,
        "permissionDecision": value,
        "permissionDecisionReason": f"[{GATE}] {reason}",
      }
    }
  )


def deny(reason):
  return decision("PreToolUse", "deny", reason)


def now_iso():
  return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def canonical_hash(value):
  encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
  return hashlib.sha256(encoded).hexdigest()


def key_digest(session_id, prompt_id, skill, caller=None):
  parts = (session_id, prompt_id, skill) if caller is None else (session_id, prompt_id, skill, caller)
  return hashlib.sha256("\x00".join(parts).encode()).hexdigest()


def caller_identity(payload):
  """main 的 payload 不帶 agent_id（`--agent` 開的 main 只帶 agent_type），subagent 才帶。

  agent_id 存在但形狀不對時 fail closed，不退回 main：退回 main 會讓壞掉的欄位
  悄悄併進 main 的額度，或反過來讓每次壞值都算成新 caller。
  """
  agent_id = payload.get("agent_id")
  if agent_id is None or agent_id == "":
    return "main"
  if not isinstance(agent_id, str) or SAFE_ID_RE.fullmatch(agent_id) is None:
    raise ValueError("unsafe agent id")
  return f"agent:{agent_id}"


def disabled():
  configured = os.environ.get("SKILL_VERIFY_ONCE_DISABLED")
  path = Path(configured).expanduser() if configured else Path.home() / ".claude" / ".skill-verify-once-disabled"
  try:
    metadata = path.lstat()
  except OSError:
    return False
  return stat.S_ISREG(metadata.st_mode) and metadata.st_uid == os.getuid()


def runtime_root():
  configured = os.environ.get("SKILL_VERIFY_ONCE_RUNTIME_DIR")
  root = Path(configured) if configured else Path(f"/private/tmp/claude-{GATE}-{os.getuid()}")
  try:
    metadata = root.lstat()
  except FileNotFoundError:
    root.mkdir(mode=0o700, parents=True)
    metadata = root.lstat()
  if (
    not stat.S_ISDIR(metadata.st_mode)
    or stat.S_ISLNK(metadata.st_mode)
    or metadata.st_uid != os.getuid()
    or stat.S_IMODE(metadata.st_mode) & 0o077
  ):
    raise OSError("unsafe runtime root")
  return root


def session_dir(root, session_id):
  if not isinstance(session_id, str) or SAFE_ID_RE.fullmatch(session_id) is None:
    raise ValueError("unsafe session id")
  path = root / session_id
  try:
    metadata = path.lstat()
  except FileNotFoundError:
    path.mkdir(mode=0o700)
    metadata = path.lstat()
  if (
    not stat.S_ISDIR(metadata.st_mode)
    or stat.S_ISLNK(metadata.st_mode)
    or metadata.st_uid != os.getuid()
    or stat.S_IMODE(metadata.st_mode) & 0o077
  ):
    raise OSError("unsafe session dir")
  return path


def read_json_file(path):
  # O_NONBLOCK：目標若被換成 FIFO，O_RDONLY 會等到有 writer 才返回，等同把 hook 掛死。
  descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
  try:
    metadata = os.fstat(descriptor)
    if (
      not stat.S_ISREG(metadata.st_mode)
      or metadata.st_uid != os.getuid()
      or stat.S_IMODE(metadata.st_mode) & 0o077
      or metadata.st_nlink != 1
    ):
      raise OSError("unsafe state file")
    with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
      descriptor = -1
      return json.load(handle)
  finally:
    if descriptor >= 0:
      os.close(descriptor)


def write_new_json(path, record):
  descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
  with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
    json.dump(record, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())


def append_audit(record):
  configured = os.environ.get("SKILL_VERIFY_ONCE_AUDIT")
  path = Path(configured).expanduser() if configured else Path.home() / ".claude" / "logs" / f"{GATE}.jsonl"
  try:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # O_NONBLOCK：audit log 被換成 FIFO 時，O_WRONLY 會等到有 reader 才返回（ENXIO 直接拋出才對）。
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
      metadata = os.fstat(descriptor)
      if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid() or metadata.st_nlink != 1:
        return
      line = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
      os.write(descriptor, line.encode())
    finally:
      os.close(descriptor)
  except OSError:
    return


def text_fields(tool_input):
  for key in ("description", "prompt"):
    value = tool_input.get(key)
    if isinstance(value, str):
      yield value


def marker_skill(tool_input):
  found = set()
  for value in text_fields(tool_input):
    found.update(name.lower() for name in MARKER_RE.findall(value))
  if len(found) != 1:
    return None
  return found.pop()


def transcript_lines_reverse(transcript_path):
  if not isinstance(transcript_path, str) or not transcript_path:
    raise ValueError("no transcript path")
  path = Path(transcript_path).expanduser()
  metadata = path.lstat()
  if not stat.S_ISREG(metadata.st_mode):
    raise OSError("transcript is not a regular file")
  with path.open("rb") as handle:
    fragments = []
    end = handle.seek(0, os.SEEK_END)
    while end:
      size = min(TRANSCRIPT_CHUNK_BYTES, end)
      end -= size
      handle.seek(end)
      chunk = handle.read(size)
      if len(chunk) != size:
        raise OSError("transcript read interrupted")
      lines = chunk.split(b"\n")
      if len(lines) == 1:
        fragments.append(lines[0])
        continue
      line = b"".join([lines[-1], *reversed(fragments)])
      if line:
        yield line.decode("utf-8")
      for line in reversed(lines[1:-1]):
        if line:
          yield line.decode("utf-8")
      fragments = [lines[0]] if lines[0] else []
    if fragments:
      yield b"".join(reversed(fragments)).decode("utf-8")


def turn_prompt_id(transcript_path):
  for line in transcript_lines_reverse(transcript_path):
    try:
      event = json.loads(line)
    except json.JSONDecodeError:
      continue
    if not isinstance(event, dict) or not is_turn_boundary(event):
      continue
    prompt_id = event.get("promptId")
    if isinstance(prompt_id, str) and SAFE_ID_RE.fullmatch(prompt_id):
      return prompt_id
  raise ValueError("no turn boundary in transcript")


def normalize_kind(value):
  if isinstance(value, dict):
    value = value.get("kind")
  if not isinstance(value, str):
    return ""
  return value.strip().lower().replace("_", "-")


def is_turn_boundary(event):
  """一個回合的發起者。額度綁它，不綁「最後一個 user event」。

  允許清單只有兩種：真人（打字與 /slash 命令都是 origin.kind=human），以及 headless
  的 sdk prompt（claude -p 實測為 origin 缺席、turnOrigin=sdk、entrypoint=sdk-cli）。
  兩者扮演同一個角色——從外部發起這一輪，所以各給一次額度。

  排除的是回合「內部」產生的 user event：tool result、skill 展開與 hook 注入（isMeta）、
  別的 session 送來的 peer 訊息，以及 task notification。task notification 特別危險——
  實測 13/13 都帶全新的 promptId，用「最後一個 user event」取 key 會讓每一則背景完成
  通知免費送一次額度。

  認不出來的 origin 種類一律不算回合邊界（fail closed），由呼叫端轉成 deny。
  """
  message = event.get("message")
  is_user = event.get("type") == "user" or (isinstance(message, dict) and message.get("role") == "user")
  if not is_user or event.get("isMeta") or event.get("isSidechain"):
    return False
  content = message.get("content") if isinstance(message, dict) else None
  if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
    return False

  kind = normalize_kind(event.get("origin"))
  if kind:
    return kind in TURN_ORIGINS
  for key in ("turnOrigin", "promptSource"):
    candidate = normalize_kind(event.get(key))
    if candidate in BLOCKED_ORIGINS:
      return False
    if candidate in TURN_ORIGINS:
      return True
  return False


def attempt_identity(payload, tool_input):
  """同一個 tool event 的重放要冪等，第二次派工要擋——兩者的唯一分辨點是 tool_use_id。

  本版 PreToolUse payload 帶得到 tool_use_id（production 樣本：toolu_01TXWYA5…／call_xBBQ…）。
  拿不到時退回 tool_input 內容 hash：那會讓「內容一字不差的第二次派工」被誤判成重放，
  是刻意選的寬鬆側，因為重放誤擋會讓正常流程整個斷掉。
  """
  value = payload.get("tool_use_id")
  if isinstance(value, str) and SAFE_ID_RE.fullmatch(value):
    return f"tool_use_id:{value}"
  return f"input_sha256:{canonical_hash(tool_input)}"


def judge_existing(path, attempt_id):
  existing = read_json_file(path)
  if not isinstance(existing, dict) or existing.get("version") != 1:
    raise OSError("corrupt claim")
  if existing.get("attempt_id") == attempt_id:
    return "replay", existing
  return "spent", existing


def claim(root, session_id, prompt_id, skill, attempt_id, caller):
  directory = session_dir(root, session_id)
  # 部署 caller 分額前建的三欄 claim 不知道是誰建的（觀察期證實可能是 subagent），
  # 所以同一組 session＋回合＋skill 沿用舊的整回合共用判定，不替進行中的回合重發額度。
  # 新回合不會再產生三欄 claim；runtime 目錄在 /private/tmp，重開機後這段就不再命中。
  legacy = directory / f"claim-{key_digest(session_id, prompt_id, skill)}.json"
  try:
    return judge_existing(legacy, attempt_id)
  except FileNotFoundError:
    pass
  path = directory / f"claim-{key_digest(session_id, prompt_id, skill, caller)}.json"
  record = {
    "version": 1,
    "session_id": session_id,
    "prompt_id": prompt_id,
    "skill": skill,
    "caller": caller,
    "attempt_id": attempt_id,
    "claimed_at": now_iso(),
  }
  try:
    write_new_json(path, record)
    return "claimed", record
  except FileExistsError:
    pass
  return judge_existing(path, attempt_id)


def record_auditor(root, session_id, agent_id):
  directory = session_dir(root, session_id)
  path = directory / f"auditor-{agent_id}.json"
  record = {"version": 1, "session_id": session_id, "agent_id": agent_id, "seen_at": now_iso()}
  try:
    write_new_json(path, record)
  except FileExistsError:
    return


def known_auditor(root, session_id, target):
  directory = session_dir(root, session_id)
  path = directory / f"auditor-{target}.json"
  try:
    metadata = path.lstat()
  except OSError:
    return False
  return stat.S_ISREG(metadata.st_mode) and metadata.st_uid == os.getuid()


def session_has_verify_activity(root, session_id):
  """本 session 有沒有派過 Self-Verify。沒有就沒有要保護的 auditor。"""
  directory = session_dir(root, session_id)
  return any(directory.glob("claim-*.json")) or any(directory.glob("auditor-*.json"))


def transcript_has_auditor(transcript_path, targets):
  pending = {}
  for line in transcript_lines_reverse(transcript_path):
    event = json.loads(line)
    message = event.get("message") if isinstance(event, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list):
      continue
    for block in reversed(content):
      if not isinstance(block, dict):
        continue
      if block.get("type") == "tool_result":
        payload = block.get("content")
        if isinstance(payload, list):
          payload = " ".join(part.get("text", "") for part in payload if isinstance(part, dict))
        if isinstance(payload, str):
          matches = set(AGENT_ID_RE.findall(payload)) & targets
          if matches:
            pending[block.get("tool_use_id")] = matches
      elif block.get("type") == "tool_use":
        matches = pending.pop(block.get("id"), None)
        tool_input = block.get("input")
        if matches and block.get("name") in AGENT_TOOLS and isinstance(tool_input, dict) and tool_input.get("subagent_type") == AUDITOR_TYPE:
          return True
  return False


def send_targets(tool_input):
  for key in ("to", "recipient"):
    value = tool_input.get(key)
    if isinstance(value, str) and value.strip():
      yield value.strip()


def load_payload():
  try:
    payload = json.load(sys.stdin)
  except (json.JSONDecodeError, ValueError):
    return None
  return payload if isinstance(payload, dict) else None


def pre_agent(payload):
  tool_input = payload.get("tool_input")
  if payload.get("tool_name") not in AGENT_TOOLS or not isinstance(tool_input, dict):
    return passthrough()
  if tool_input.get("subagent_type") != AUDITOR_TYPE:
    return passthrough()

  skill = marker_skill(tool_input)
  if skill is None:
    append_audit({"ts": now_iso(), "mode": "pre-agent", "result": "deny", "reason": "missing-marker"})
    return deny(
      "找不到唯一的 `skill-verify:<skill>` marker（description 與 prompt 都掃過）。"
      "Self-Verify 派工必須在 description 帶恰好一個 marker；引用別的 skill 原文時改寫成不含冒號的形式。"
    )

  try:
    session_id = payload.get("session_id")
    caller = caller_identity(payload)
    prompt_id = turn_prompt_id(payload.get("transcript_path"))
    root = runtime_root()
    state, record = claim(root, session_id, prompt_id, skill, attempt_identity(payload, tool_input), caller)
  except (OSError, TypeError, ValueError) as error:
    append_audit({"ts": now_iso(), "mode": "pre-agent", "result": "deny", "reason": f"state:{type(error).__name__}"})
    return deny(
      f"無法確認回合邊界或額度狀態（{type(error).__name__}），依安全型 gate 規則 fail closed。"
      f"這不影響 main 交付其他內容；要暫停本 gate 請建立 recovery sentinel。"
    )

  append_audit(
    {
      "ts": now_iso(),
      "mode": "pre-agent",
      "result": state,
      "skill": skill,
      "session": session_id,
      "prompt": prompt_id,
      "caller": caller,
      "agent_type": payload.get("agent_type") if isinstance(payload.get("agent_type"), str) else None,
    }
  )
  if state == "spent":
    return deny(f"{DENY_QUOTA}（skill={skill}，首次派工於 {record.get('claimed_at')}）")
  return passthrough()


def post_agent(payload):
  tool_input = payload.get("tool_input")
  if payload.get("tool_name") not in AGENT_TOOLS or not isinstance(tool_input, dict):
    return passthrough()
  if tool_input.get("subagent_type") != AUDITOR_TYPE:
    return passthrough()

  response = payload.get("tool_response")
  if isinstance(response, (dict, list)):
    response = json.dumps(response, ensure_ascii=False)
  if not isinstance(response, str) or not LAUNCH_OK_RE.search(response):
    return passthrough()
  match = AGENT_ID_RE.search(response)
  if match is None:
    return passthrough()

  try:
    root = runtime_root()
    record_auditor(root, payload.get("session_id"), match.group(1))
  except (OSError, TypeError, ValueError):
    return passthrough()
  append_audit({"ts": now_iso(), "mode": "post-agent", "result": "recorded", "agent_id": match.group(1)})
  return passthrough()


def pre_sendmessage(payload):
  tool_input = payload.get("tool_input")
  if payload.get("tool_name") != "SendMessage" or not isinstance(tool_input, dict):
    return passthrough()

  targets = list(send_targets(tool_input))
  if not targets:
    return passthrough()
  if any(AUDITOR_TYPE in target.lower() for target in targets):
    append_audit({"ts": now_iso(), "mode": "pre-sendmessage", "result": "deny", "reason": "auditor-name"})
    return deny(f"{DENY_QUOTA}（target 指向 {AUDITOR_TYPE}）")

  try:
    root = runtime_root()
    session_id = payload.get("session_id")
    hit = any(known_auditor(root, session_id, target) for target in targets)
    protected = hit or session_has_verify_activity(root, session_id)
  except (OSError, TypeError, ValueError) as error:
    append_audit({"ts": now_iso(), "mode": "pre-sendmessage", "result": "deny", "reason": f"state:{type(error).__name__}"})
    return deny(
      f"無法確認 SendMessage target 是否為本 session 的 Self-Verify auditor（{type(error).__name__}），"
      f"依安全型 gate 規則 fail closed。要暫停本 gate 請建立 recovery sentinel。"
    )

  if not hit and protected:
    # 只有「本 session 確實派過 Self-Verify」時才需要讀 transcript 確認 target 身分。
    # 沒派過就沒有要保護的對象，transcript 讀不到也不該牽連其他 SendMessage。
    try:
      hit = transcript_has_auditor(payload.get("transcript_path"), set(targets))
    except (OSError, TypeError, ValueError) as error:
      append_audit(
        {"ts": now_iso(), "mode": "pre-sendmessage", "result": "deny", "reason": f"transcript:{type(error).__name__}"}
      )
      return deny(
        f"本 session 已派過 Self-Verify auditor，但無法讀 transcript 確認 target 身分"
        f"（{type(error).__name__}），依安全型 gate 規則 fail closed。"
      )

  if hit:
    append_audit({"ts": now_iso(), "mode": "pre-sendmessage", "result": "deny", "reason": "auditor-id"})
    return deny(f"{DENY_QUOTA}（target 是本 session 派出的 auditor）")
  append_audit({"ts": now_iso(), "mode": "pre-sendmessage", "result": "allow", "reason": "target-not-auditor"})
  return passthrough()


MODES = {"pre-agent": pre_agent, "post-agent": post_agent, "pre-sendmessage": pre_sendmessage}


def main(argv):
  mode = argv[1] if len(argv) > 1 else ""
  handler = MODES.get(mode)
  if handler is None:
    print(f"usage: {Path(argv[0]).name} {{{'|'.join(sorted(MODES))}}}", file=sys.stderr)
    return 2
  # recovery sentinel 先判：它是文件承諾的唯一逃生門，連 payload 壞掉那條 deny 也要救得回來。
  if disabled():
    return passthrough()
  payload = load_payload()
  if payload is None:
    if mode == "post-agent":
      return passthrough()
    return deny("hook 輸入不是合法 JSON object，fail closed。")
  try:
    return handler(payload)
  except Exception as error:  # noqa: BLE001 - 安全型 gate：任何未預期例外都要倒向 deny
    if mode == "post-agent":
      return passthrough()
    return deny(f"gate 內部錯誤（{type(error).__name__}），fail closed。")


if __name__ == "__main__":
  raise SystemExit(main(sys.argv))
