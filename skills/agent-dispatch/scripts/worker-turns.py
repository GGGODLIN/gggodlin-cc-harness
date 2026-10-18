#!/usr/bin/env python3
"""讀 worker session 的 jsonl，把「人打的」與「main 轉達的」分開列出來。

用法：worker-turns.py <worktree path 或 jsonl 路徑> [--session <id>] [--grep <關鍵詞>] [--last-assistant]
      worker-turns.py --harness codex|pi --session <id>

--harness codex|pi 只輸出 session、harness、jsonl、last_assistant（交付訊息，不截斷）；human／main 分流只有 CC 紀錄做。
pi 的最後一則 assistant 訊息以 stopReason error／aborted 收場時，非零結束、stdout 不輸出，stderr 印
「pi session <id> ended with <stop_reason>: <errorMessage 或 no message>」；錯誤之後有成功重試、最後一則正常收場則照常輸出。
Codex 根目錄用 CODEX_HOME（預設 ~/.codex），pi 用 PI_CODING_AGENT_DIR（預設 ~/.pi/agent）。

判定：type=user 且非 isSidechain 的文字訊息；以 [main] 開頭的是 main 送進去的，其餘算使用者本人在 pane 打的。
輸出 JSON：session、human（人類 turn 清單）、main（main 轉達清單）、last_assistant（最後一則 assistant 文字，--last-assistant 才給）。
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

MAIN_PREFIX = "[main]"
SKIP_PREFIXES = ("<", "Base directory for this skill", "[Request interrupted")


def encode_project_dir(path: str) -> Path:
  return Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(Path(path).resolve()))


def pick_jsonl(target: str, session: str | None) -> Path:
  p = Path(target).expanduser()
  if p.suffix == ".jsonl" and p.is_file():
    return p
  d = encode_project_dir(target)
  if session:
    f = d / f"{session}.jsonl"
    if f.is_file():
      return f
    sys.exit(f"session jsonl not found: {f}")
  files = sorted(d.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
  if not files:
    sys.exit(f"no jsonl under {d}")
  return files[0]


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
      t = "\n".join(b["text"] for b in p.get("content") or [] if isinstance(b, dict) and b.get("type") == "output_text" and isinstance(b.get("text"), str))
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


def main() -> None:
  ap = argparse.ArgumentParser()
  ap.add_argument("target", nargs="?")
  ap.add_argument("--session")
  ap.add_argument("--grep")
  ap.add_argument("--last-assistant", action="store_true")
  ap.add_argument("--harness", choices=["claude", "codex", "pi"], default="claude")
  a = ap.parse_args()
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
    if r.get("isSidechain"):
      continue
    t = text_of(r.get("message", {}).get("content"))
    if not t.strip():
      continue
    if r.get("type") == "assistant":
      last_assistant = t
      continue
    if r.get("type") != "user" or t.lstrip().startswith(SKIP_PREFIXES):
      continue
    if a.grep and a.grep not in t:
      continue
    entry = {"ts": r.get("timestamp"), "text": t[:400]}
    (relayed if t.lstrip().startswith(MAIN_PREFIX) else human).append(entry)
  out = {"session": f.stem, "jsonl": str(f), "human": human, "main": relayed}
  if a.last_assistant:
    out["last_assistant"] = last_assistant[:3000]
  print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
  main()
