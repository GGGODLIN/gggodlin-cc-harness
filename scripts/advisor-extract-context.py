#!/usr/bin/env python3
"""Extract a Claude Code session's conversation text for an advisor to read.

Usage:
  advisor-extract-context.py [--session <id>] [--out <path>] [--max-bytes N]

Why this exists as a script rather than instructions in /advisor:
a 2026-09-03 Fable review of the command found that the prose version ("take
message.content blocks where type == 'text'") silently drops every user message.
User turns store content as a bare string, not a block list, so a fresh agent
following the prose literally produces a transcript containing only Claude's own
side -- exactly the framing contamination --full exists to avoid. It also found
that isMeta turns (hook-injected skill bodies) accounted for ~44% of the bytes.
Both are handled here so no one has to remember them.

Output goes to stdout unless --out is given. Stats always go to stderr.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

SYSTEM_BLOCK_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
COMMAND_TAG_RE = re.compile(r"<command-(message|name|args)>.*?</command-\1>", re.S)


def resolve_session_path(session_id):
    """Locate this session's jsonl. Never guess by mtime: the project dir holds
    over a thousand sessions and the newest one is usually somebody else's."""
    if not session_id:
        session_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
    if not session_id:
        sys.exit(
            "no session id: pass --session <id>, or run where CLAUDE_CODE_SESSION_ID is set.\n"
            "Do NOT fall back to the newest jsonl in the project dir -- it is usually a different session."
        )
    root = Path.home() / ".claude" / "projects"
    hits = list(root.glob("*/%s.jsonl" % session_id))
    if not hits:
        sys.exit("no jsonl found for session %s under %s" % (session_id, root))
    return hits[0]


def extract_text(message):
    """Handle both content shapes. User turns are plain strings; assistant turns
    are block lists. Dropping either shape loses one whole side of the dialogue."""
    if not isinstance(message, dict):
        return ""
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        return "\n".join(parts)
    return ""


def clean(text):
    text = SYSTEM_BLOCK_RE.sub("", text)
    text = COMMAND_TAG_RE.sub("", text)
    return text.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default="", help="session id; defaults to CLAUDE_CODE_SESSION_ID")
    ap.add_argument("--out", default="", help="write here instead of stdout")
    ap.add_argument("--max-bytes", type=int, default=190000,
                    help="truncate to the most recent turns above this; 0 disables")
    args = ap.parse_args()

    path = resolve_session_path(args.session)
    turns, skipped_meta, meta_bytes = [], 0, 0

    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                event = json.loads(line)
            except Exception:
                continue
            message = event.get("message")
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            if role not in ("user", "assistant"):
                continue
            text = extract_text(message)
            if not text.strip():
                continue
            # isMeta turns are hook-injected skill bodies and command payloads, not
            # anything either party said. They dominate the byte count if kept.
            if event.get("isMeta"):
                skipped_meta += 1
                meta_bytes += len(text.encode("utf-8"))
                continue
            text = clean(text)
            if text:
                turns.append((role, text))

    label = {"user": "使用者", "assistant": "Claude"}
    body = "\n\n".join("### %s\n%s" % (label[r], t) for r, t in turns)
    truncated = 0
    if args.max_bytes and len(body.encode("utf-8")) > args.max_bytes:
        kept = []
        total = 0
        for r, t in reversed(turns):
            chunk = "### %s\n%s" % (label[r], t)
            size = len(chunk.encode("utf-8")) + 2
            if total + size > args.max_bytes:
                break
            kept.append((r, t))
            total += size
        truncated = len(turns) - len(kept)
        kept.reverse()
        # The advisor has to know its view is partial, otherwise it will reason
        # about "the whole discussion" while holding only the tail of it.
        notice = ("[!] 這份對話已截斷：省略了最早的 %d 個回合，只保留最近的 %d 個。"
                  "任何關於「討論初期」的判斷都缺乏依據。\n\n" % (truncated, len(kept)))
        body = notice + "\n\n".join("### %s\n%s" % (label[r], t) for r, t in kept)

    data = body.encode("utf-8")
    if args.out:
        Path(args.out).write_bytes(data)
    else:
        sys.stdout.write(body)

    print("session      : %s" % path.name, file=sys.stderr)
    print("turns kept   : %d%s" % (len(turns) - truncated,
                                   (" (truncated %d)" % truncated) if truncated else ""),
          file=sys.stderr)
    print("isMeta 濾除  : %d turns / %d bytes" % (skipped_meta, meta_bytes), file=sys.stderr)
    print("bytes        : %d (%.1f KB)" % (len(data), len(data) / 1024), file=sys.stderr)
    if args.out:
        print("written to   : %s" % args.out, file=sys.stderr)


if __name__ == "__main__":
    main()
