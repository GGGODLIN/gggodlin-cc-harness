#!/usr/bin/env python3
"""讀 worker session 的 jsonl，把「人打的」與「main 轉達的」分開列出來。

用法：worker-turns.py <worktree path 或 jsonl 路徑> [--session <id>] [--grep <關鍵詞>] [--last-assistant]

判定：type=user 且非 isSidechain 的文字訊息；以 [main] 開頭的是 main 送進去的，其餘算使用者本人在 pane 打的。
輸出 JSON：session、human（人類 turn 清單）、main（main 轉達清單）、last_assistant（最後一則 assistant 文字，--last-assistant 才給）。
"""
import argparse
import json
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
    return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
  return ""


def main() -> None:
  ap = argparse.ArgumentParser()
  ap.add_argument("target")
  ap.add_argument("--session")
  ap.add_argument("--grep")
  ap.add_argument("--last-assistant", action="store_true")
  a = ap.parse_args()
  f = pick_jsonl(a.target, a.session)
  human, relayed, last_assistant = [], [], ""
  for line in f.open(encoding="utf-8"):
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
