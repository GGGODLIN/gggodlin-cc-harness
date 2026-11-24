#!/usr/bin/env python3
"""讀 worker session 的 jsonl，把「人打的」與「main 轉達的」分開列出來。

用法：worker-turns.py <worktree path 或 jsonl 路徑> [--session <id>] [--grep <關鍵詞>] [--last-assistant]
      worker-turns.py --harness codex|pi --session <id>

--harness codex|pi 只輸出 session、harness、jsonl、last_assistant（交付訊息，不截斷）；human／main 分流只有 CC 紀錄做。
pi 的最後一則 assistant 訊息以 stopReason error／aborted 收場時，非零結束、stdout 不輸出，stderr 印
「pi session <id> ended with <stop_reason>: <errorMessage 或 no message>」；錯誤之後有成功重試、最後一則正常收場則照常輸出。
Codex 根目錄用 CODEX_HOME（預設 ~/.codex），pi 用 PI_CODING_AGENT_DIR（預設 ~/.pi/agent）。

判定：type=user 且非 isSidechain 的文字訊息；先剝除開閉 id 一致的 pasted_content 外層，再判定直接或在 hc 包裝內以 [main] 開頭的是 main 送進去的，其餘算使用者本人在 pane 打的。
輸出 JSON：session、human（人類 turn 清單）、main（main 轉達清單）、last_assistant（最後一則 assistant 文字，--last-assistant 才給）。
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

from seat_text import unwrap_transport

MAIN_PREFIX = "[main]"
SKIP_PREFIXES = ("<", "Base directory for this skill", "[Request interrupted")


def encode_project_dir(path: str) -> Path:
  base = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser()
  return base / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(Path(path).resolve()))


def pick_jsonl(target: str, session: str | None) -> Path:
  p = Path(target).expanduser()
  if p.suffix == ".jsonl" and p.is_file():
    return p
  slug = re.sub(r"[^A-Za-z0-9]", "-", str(Path(target).resolve()))
  primary = encode_project_dir(target)
  fallback = Path.home() / ".claude" / "projects" / slug
  dirs = [primary] if primary == fallback else [primary, fallback]
  if session:
    for d in dirs:
      f = d / f"{session}.jsonl"
      if f.is_file():
        return f
    sys.exit(f"session jsonl not found: {primary / (session + '.jsonl')}")
  for d in dirs:
    files = sorted(d.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
    if files:
      return files[0]
  sys.exit(f"no jsonl under {primary}")


def text_of(content) -> str:
  if isinstance(content, str):
    return content
  if isinstance(content, list):
    # text 欄位可能是 null 或別的型別；只收字串，否則 join 會 TypeError。
    return "\n".join(b["text"] for b in content if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str))
  return ""


def read_lines(f: Path) -> list:
  try:
    with f.open(encoding="utf-8") as fh:
      return list(fh)
  except UnicodeDecodeError as e:
    sys.exit(f"cannot decode {f} as UTF-8: {e.reason} at byte {e.start}")


def find_session_file(root: Path, pattern: str, what: str) -> Path:
  files = sorted(root.glob(pattern), key=lambda f: f.stat().st_mtime, reverse=True)
  if not files:
    sys.exit(f"{what} session jsonl not found: {root}/{pattern}")
  return files[0]


def codex_last_message(lines) -> str:
  # task_complete 是 Codex 自己標的回合交付訊息；沒有它（回合還在跑、被中斷）時退回最後一筆 assistant output_text。
  # 取檔案順序最後出現者：回合進行中時，新的 assistant 訊息比上一回合的 task_complete 更新。
  last = ""
  for r in lines:
    p = r.get("payload")
    if not isinstance(p, dict):
      continue
    if r.get("type") == "event_msg" and p.get("type") == "task_complete":
      t = p.get("last_agent_message")
    elif r.get("type") == "response_item" and p.get("type") == "message" and p.get("role") == "assistant":
      content = p.get("content")
      t = "\n".join(b["text"] for b in (content if isinstance(content, list) else []) if isinstance(b, dict) and b.get("type") == "output_text" and isinstance(b.get("text"), str))
    else:
      continue
    if isinstance(t, str) and t.strip():
      last = t
  return last


def pi_last_message(lines) -> tuple:
  # pi 碰到 429／provider 錯誤時記一則 content 為空、stopReason 為 error／aborted 的 assistant 訊息；
  # 只取最後一則有文字的訊息會把更早回合的舊答案當成本回合交付，所以回傳最後一則 assistant 的收場錯誤，由呼叫端拒絕交付。
  last, final = "", None
  for r in lines:
    m = r.get("message")
    if r.get("type") != "message" or not isinstance(m, dict) or m.get("role") != "assistant":
      continue
    final = m
    t = text_of(m.get("content"))
    if t.strip():
      last = t
  error = None
  if final is not None and final.get("stopReason") in ("error", "aborted"):
    message = final.get("errorMessage")
    error = (final["stopReason"], message if isinstance(message, str) and message.strip() else "no message")
  return last, error


def read_records(f: Path) -> list:
  out = []
  for line in read_lines(f):
    try:
      r = json.loads(line)
    except json.JSONDecodeError:
      continue
    if isinstance(r, dict):
      out.append(r)
  return out


def run_foreign_harness(harness: str, session: str) -> None:
  # session 會進 glob，限制成編號字元，避免 * ? / 之類誤配到別的 session 檔。
  if not re.fullmatch(r"[A-Za-z0-9._-]+", session):
    sys.exit(f"invalid session id: {session!r}")
  if harness == "codex":
    root = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "sessions"
    f = find_session_file(root, f"**/rollout-*-{session}.jsonl", "codex")
    last = codex_last_message(read_records(f))
  else:
    root = Path(os.environ.get("PI_CODING_AGENT_DIR") or Path.home() / ".pi" / "agent") / "sessions"
    f = find_session_file(root, f"*/*_{session}.jsonl", "pi")
    last, error = pi_last_message(read_records(f))
    # 錯誤收場時就算沒有任何文字訊息也走這條，否則錯誤原因會被「沒有 assistant 訊息」蓋掉。
    if error:
      sys.exit(f"pi session {session} ended with {error[0]}: {error[1]}")
  if not last:
    sys.exit(f"no assistant message in {f}")
  print(json.dumps({"session": session, "harness": harness, "jsonl": str(f), "last_assistant": last}, ensure_ascii=False, indent=1))


def read_records_strict(path: Path) -> tuple[list[dict] | None, str | None]:
  try:
    with path.open(encoding="utf-8") as fh:
      raw_lines = list(fh)
  except (OSError, UnicodeDecodeError) as exc:
    return None, f"這次讀不到：{exc}"
  records = []
  for number, line in enumerate(raw_lines, 1):
    if not line.strip():
      continue
    try:
      obj = json.loads(line)
    except ValueError as exc:
      return None, f"這次讀不到：第 {number} 行 JSON 解析失敗（可能寫到一半）：{exc}"
    if not isinstance(obj, dict):
      return None, f"這次讀不到：第 {number} 行不是 JSON 物件"
    records.append(obj)
  if not records:
    return None, f"這次讀不到：紀錄檔是空的（{path.name}）"
  return records, None


def locate_turn_file(harness: str, session: str, cwd: str | None) -> tuple[Path | None, str | None]:
  if not re.fullmatch(r"[A-Za-z0-9._-]+", session):
    return None, f"這次讀不到：無效的 session id ({session!r})"
  if harness == "claude":
    if not cwd:
      return None, "這次讀不到：讀 Claude Code 紀錄檔需要 --cwd"
    p = encode_project_dir(cwd) / f"{session}.jsonl"
    return (p, None) if p.is_file() else (None, f"這次讀不到：找不到 Claude Code 紀錄檔 {p}")
  if harness == "codex":
    root = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "sessions"
    matches = sorted(root.glob(f"**/rollout-*-{session}.jsonl"))
    if len(matches) != 1:
      return None, f"這次讀不到：Codex rollout 找不到或不唯一（命中 {len(matches)} 筆）"
    return matches[0], None
  root = Path(os.environ.get("PI_CODING_AGENT_DIR") or Path.home() / ".pi" / "agent") / "sessions"
  matches = sorted(root.glob(f"*/*_{session}.jsonl"))
  if len(matches) != 1:
    return None, f"這次讀不到：pi session 紀錄檔找不到或不唯一（命中 {len(matches)} 筆）"
  return matches[0], None


def extract_pi_turn(records: list[dict], session: str, turn: int) -> tuple[str | None, str | None]:
  matched_header = False
  for r in records:
    if r.get("type") == "session":
      rid = r.get("id")
      if not isinstance(rid, str) or rid != session:
        return None, f"這次讀不到：pi 紀錄檔 session id 不符（預期 {session}，實際 {rid!r}）"
      matched_header = True
  if not matched_header:
    return None, f"這次讀不到：pi 紀錄檔缺少 session 檔頭（預期 {session}）"
  turns: list[list[dict]] = []
  for r in records:
    if r.get("type") != "message":
      continue
    m = r.get("message")
    if not isinstance(m, dict):
      return None, "這次讀不到：pi message 欄位型別不符（非物件）"
    role = m.get("role")
    if role == "user":
      turns.append([])
    elif role == "assistant" and turns:
      turns[-1].append(m)
  if len(turns) < turn:
    return None, f"紀錄檔還沒有第 {turn} 輪的回覆（目前只有 {len(turns)} 輪）"
  assistants = turns[turn - 1]
  if not assistants:
    return None, f"第 {turn} 輪尚未有 assistant 回覆"
  final = assistants[-1]
  stop_reason = final.get("stopReason")
  if stop_reason in ("error", "aborted"):
    err_msg = final.get("errorMessage")
    detail = err_msg if isinstance(err_msg, str) and err_msg.strip() else "no message"
    return None, f"pi 第 {turn} 輪以 {stop_reason} 結束：{detail}"
  if stop_reason not in ("stop", "end_turn", "stop_sequence"):
    return None, f"pi 第 {turn} 輪尚未正常收尾（stopReason={stop_reason!r}）"
  content = final.get("content")
  if content is not None and not isinstance(content, (str, list)):
    return None, "這次讀不到：pi assistant content 型別不符"
  final_text = text_of(content)
  if not final_text.strip():
    return None, f"第 {turn} 輪回覆是空白"
  return final_text, None


def is_real_cc_user_prompt(rec: dict) -> tuple[bool, str | None]:
  if rec.get("type") != "user" or rec.get("isSidechain"):
    return False, None
  msg = rec.get("message")
  if not isinstance(msg, dict):
    return False, "這次讀不到：Claude Code user message 欄位型別不符（非物件）"
  content = msg.get("content")
  if isinstance(content, list):
    non_tool_results = [b for b in content if not (isinstance(b, dict) and b.get("type") == "tool_result")]
    if not non_tool_results:
      return False, None
    text = text_of(non_tool_results)
  elif isinstance(content, str):
    text = content
  else:
    return False, "這次讀不到：Claude Code user content 欄位型別不符"
  unwrapped = unwrap_transport(text).lstrip()
  return (bool(unwrapped) and not unwrapped.startswith(SKIP_PREFIXES)), None


def extract_cc_turn(records: list[dict], session: str, turn: int) -> tuple[str | None, str | None]:
  sids = set()
  for r in records:
    if "sessionId" in r and r["sessionId"] is not None:
      if not isinstance(r["sessionId"], str) or not r["sessionId"].strip():
        return None, "這次讀不到：Claude Code sessionId 欄位型別不符"
      sids.add(r["sessionId"])
  if not sids:
    return None, f"這次讀不到：Claude Code 紀錄檔缺少 sessionId（預期 {session}）"
  if sids != {session}:
    return None, f"這次讀不到：Claude Code 紀錄檔 sessionId 不符或混雜（預期 {session}，實際 {sorted(sids)}）"
  turns: list[dict] = []
  for r in records:
    if r.get("isSidechain"):
      continue
    if r.get("type") == "user":
      is_prompt, shape_err = is_real_cc_user_prompt(r)
      if shape_err:
        return None, shape_err
      if is_prompt:
        turns.append({"assistants": [], "pending": set()})
        continue
    if not turns:
      continue
    cur = turns[-1]
    rtype = r.get("type")
    if rtype not in ("assistant", "user"):
      continue
    m = r.get("message")
    if not isinstance(m, dict):
      return None, f"這次讀不到：Claude Code {rtype} message 欄位型別不符"
    content = m.get("content")
    if content is not None and not isinstance(content, (str, list)):
      return None, f"這次讀不到：Claude Code {rtype} content 欄位型別不符"
    if rtype == "assistant":
      cur["assistants"].append(m)
      for block in content if isinstance(content, list) else []:
        if isinstance(block, dict) and block.get("type") == "tool_use" and isinstance(block.get("id"), str):
          cur["pending"].add(block["id"])
    elif rtype == "user" and isinstance(content, list):
      for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_result" and isinstance(block.get("tool_use_id"), str):
          cur["pending"].discard(block["tool_use_id"])
  if len(turns) < turn:
    return None, f"紀錄檔還沒有第 {turn} 輪的回覆（目前只有 {len(turns)} 輪）"
  cur = turns[turn - 1]
  assistants = cur["assistants"]
  if not assistants:
    return None, f"第 {turn} 輪尚未有 assistant 回覆"
  final = assistants[-1]
  if cur["pending"]:
    return None, f"第 {turn} 輪仍有未完成的工具呼叫（{len(cur['pending'])} 筆）"
  stop = final.get("stop_reason")
  if stop not in ("end_turn", "stop_sequence"):
    return None, f"第 {turn} 輪尚未正常收尾（stop_reason={stop!r}）"
  final_id = final.get("id")
  if isinstance(final_id, str) and final_id:
    chunks = [text_of(m.get("content")) for m in assistants if m.get("id") == final_id]
    final_text = "\n".join(c for c in chunks if c)
  else:
    final_text = text_of(final.get("content"))
  if not final_text.strip():
    return None, f"第 {turn} 輪回覆是空白"
  return final_text, None


def extract_codex_turn(records: list[dict], session: str, turn: int) -> tuple[str | None, str | None]:
  matched_meta = False
  for r in records:
    if r.get("type") == "session_meta":
      pl = r.get("payload")
      if not isinstance(pl, dict) or not isinstance(pl.get("id"), str) or pl["id"] != session:
        return None, f"這次讀不到：Codex rollout session_meta id 不符（預期 {session}）"
      matched_meta = True
  if not matched_meta:
    return None, f"這次讀不到：Codex rollout 缺少 session_meta（預期 {session}）"
  turns: list[dict] = []
  by_turn_id: dict[str, dict] = {}
  for r in records:
    rtype = r.get("type")
    if rtype not in ("event_msg", "response_item"):
      continue
    pl = r.get("payload")
    if not isinstance(pl, dict):
      return None, f"這次讀不到：Codex {rtype} payload 欄位型別不符"
    if rtype == "event_msg":
      kind = pl.get("type")
      if kind == "task_started":
        tid = pl.get("turn_id")
        entry = {"turn_id": tid if isinstance(tid, str) and tid else None, "terminal_event": None, "complete_text": None, "assistant_text": ""}
        turns.append(entry)
        if entry["turn_id"]:
          by_turn_id[entry["turn_id"]] = entry
      elif turns and kind in ("task_complete", "turn_aborted", "error"):
        tid = pl.get("turn_id")
        if isinstance(tid, str) and tid:
          target_turn = by_turn_id.get(tid)
          if target_turn is None:
            continue
        else:
          # 有 turn_id 的輪次絕不接受缺 turn_id 的完成事件，避免無法歸屬的舊事件滿足新輪。
          if turns[-1]["turn_id"] is not None:
            continue
          target_turn = turns[-1]
        target_turn["terminal_event"] = kind
        if kind == "task_complete" and "last_agent_message" in pl:
          msg = pl.get("last_agent_message")
          if msg is not None and not isinstance(msg, str):
            return None, "這次讀不到：Codex task_complete.last_agent_message 型別不符"
          target_turn["complete_text"] = msg
    elif turns and rtype == "response_item" and pl.get("type") == "message" and pl.get("role") == "assistant":
      content = pl.get("content")
      if content is not None and not isinstance(content, list):
        return None, "這次讀不到：Codex assistant content 欄位型別不符"
      t = "\n".join(
        b["text"]
        for b in content or []
        if isinstance(b, dict) and b.get("type") == "output_text" and isinstance(b.get("text"), str)
      )
      turns[-1]["assistant_text"] = t
  if len(turns) < turn:
    return None, f"紀錄檔還沒有第 {turn} 輪的回覆（目前只有 {len(turns)} 輪）"
  cur = turns[turn - 1]
  if cur["terminal_event"] != "task_complete":
    return None, f"第 {turn} 輪尚未完成（最後狀態：{cur['terminal_event']!r}）"
  # last_agent_message 有明確鍵值（含空字串）時不回退到較早的 assistant 訊息，避免空白交付被舊文字蓋過。
  text = cur["complete_text"] if cur["complete_text"] is not None else cur["assistant_text"]
  if not text.strip():
    return None, f"第 {turn} 輪回覆是空白"
  return text, None


def classify_reply(text: str) -> dict:
  lines = text.splitlines()
  first_line = lines[0].strip() if lines else ""
  if re.fullmatch(r"做完了[。.!！\s]*", first_line):
    return {"delivered": True, "status": "delivered", "reply": text}
  stuck = re.match(r"^卡住了[:：]\s*(.+)$", first_line)
  if stuck:
    missing = stuck.group(1).strip()
    return {
      "delivered": False,
      "status": "stuck",
      "missing": missing,
      "reason": f"受派者卡住了：{missing}",
      "reply": text,
    }
  return {
    "delivered": False,
    "status": "not_delivered",
    "reason": f"回覆第一行不是「做完了」或「卡住了：缺什麼」（實際：{first_line[:60]!r}）",
    "reply": text,
  }


def run_turn_receipt(harness: str, session: str, turn: int, cwd: str | None) -> int:
  base = {"harness": harness, "session": session, "turn": turn}
  if turn < 1:
    print(json.dumps({**base, "delivered": False, "status": "unreadable", "reason": "這次讀不到：turn 必須 >= 1"}, ensure_ascii=False))
    return 2
  path, loc_err = locate_turn_file(harness, session, cwd)
  if loc_err or path is None:
    print(json.dumps({**base, "delivered": False, "status": "unreadable", "reason": loc_err}, ensure_ascii=False))
    return 2
  records, read_err = read_records_strict(path)
  if read_err or records is None:
    print(json.dumps({**base, "jsonl": str(path), "delivered": False, "status": "unreadable", "reason": read_err}, ensure_ascii=False))
    return 2
  if harness == "pi":
    text, err = extract_pi_turn(records, session, turn)
  elif harness == "claude":
    text, err = extract_cc_turn(records, session, turn)
  else:
    text, err = extract_codex_turn(records, session, turn)
  if err is not None or text is None:
    status = "unreadable" if (err or "").startswith("這次讀不到") else "not_delivered"
    print(json.dumps({**base, "jsonl": str(path), "delivered": False, "status": status, "reason": err}, ensure_ascii=False))
    return 2 if status == "unreadable" else 1
  verdict = classify_reply(text)
  print(json.dumps({**base, "jsonl": str(path), **verdict}, ensure_ascii=False))
  return 0 if verdict["delivered"] else 1


def main() -> None:
  ap = argparse.ArgumentParser()
  ap.add_argument("target", nargs="?")
  ap.add_argument("--session")
  ap.add_argument("--grep")
  ap.add_argument("--last-assistant", action="store_true")
  ap.add_argument("--full", action="store_true", help="搭配 --last-assistant 回傳完整末則回覆，不截斷於 3,000 字元")
  ap.add_argument("--harness", choices=["claude", "codex", "pi"], default="claude")
  ap.add_argument("--turn", type=int, help="新路收件模式：指定 1-based 輪次並依首行契約判定交付")
  ap.add_argument("--cwd", help="Claude Code 紀錄檔對應的工作目錄（搭配 CLAUDE_CONFIG_DIR）")
  a = ap.parse_args()
  if a.turn is not None:
    if not a.session:
      ap.error("--session is required when using --turn")
    sys.exit(run_turn_receipt(a.harness, a.session, a.turn, a.cwd))
  if a.harness != "claude":
    if not a.session:
      ap.error(f"--session is required for --harness {a.harness}")
    run_foreign_harness(a.harness, a.session)
    return
  if not a.target:
    ap.error("the following arguments are required: target")
  f = pick_jsonl(a.target, a.session)
  human, relayed, last_assistant = [], [], ""
  for line in read_lines(f):
    try:
      r = json.loads(line)
    except json.JSONDecodeError:
      continue
    if not isinstance(r, dict) or r.get("isSidechain"):
      continue
    msg = r.get("message")
    if not isinstance(msg, dict):
      continue
    t = text_of(msg.get("content"))
    if not t.strip():
      continue
    if r.get("type") == "assistant":
      last_assistant = t
      continue
    # transport 包裝不能讓 main brief 或真人貼文被當成 XML 控制訊息略過。
    t = unwrap_transport(t)
    if r.get("type") != "user" or t.lstrip().startswith(SKIP_PREFIXES):
      continue
    if a.grep and a.grep not in t:
      continue
    entry = {"ts": r.get("timestamp"), "text": t[:400]}
    (relayed if t.lstrip().startswith(MAIN_PREFIX) else human).append(entry)
  out = {"session": f.stem, "jsonl": str(f), "human": human, "main": relayed}
  if a.last_assistant:
    if a.full or len(last_assistant) <= 3000:
      out["last_assistant"] = last_assistant
    else:
      out["last_assistant"] = last_assistant[:3000]
      out["last_assistant_truncated"] = True
      out["last_assistant_total_chars"] = len(last_assistant)
  print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
  main()
