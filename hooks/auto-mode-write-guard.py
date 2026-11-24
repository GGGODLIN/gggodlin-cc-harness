#!/usr/bin/env python3
"""Protect the human-controlled auto-mode switch from accidental agent writes.

This lexical Bash check recognizes common forms, not full shell semantics or
intentional circumvention. It fails closed on unreadable hook input. Commands
embedded as text can match too; documentation can be written with Edit/Write.
The guard, wiring and tests remain editable through the normal checked-in update
path. A human can revert the registration from outside Claude Code for recovery.
"""

import ast
import json
import os
import re
import shlex
import sys
from pathlib import Path

TOOLS = {"Bash", "Edit", "Write"}
COPY_TO_LAST = {"cp", "install", "ln"}
MUTATORS = {"mv", "tee", "rm", "unlink", "truncate", "touch", "chmod", "chown", "rmdir", "mkdir"}
OUTPUT_REDIRECT = re.compile(r"(?:>|>>|>\||<>|&>|&>>)$")
SEPARATOR = re.compile(r"^(?:[;()\n]+|&&|\|\||\||\|&|&)$")
HEREDOC_OPENER = re.compile(
  r"<<<|\\.|'[^']*'|\"(?:\\.|[^\"\\])*\"|(?<![^\s;&|()<>])#.*"
  r"|<<(?P<strip_tabs>-?)[ \t]*(?:(?P<quote>['\"])(?P<quoted>.*?)(?P=quote)"
  r"|(?P<bare>[A-Za-z0-9_.-]+))(?=$|[\s;&|()<>])"
)
BUTTON_SOURCE = re.compile(r"(?<![\w-])--source(?:\s+|=)button(?=$|[\s'\";&|()<>])")


def require_text(mapping, name, empty=False):
  value = mapping.get(name)
  if not isinstance(value, str) or "\x00" in value or (not empty and not value.strip()):
    raise ValueError(name)
  return value


def resolve_arg(word, cwd):
  home = str(Path.home())
  for prefix in ("$HOME", "${HOME}"):
    if word == prefix or word.startswith(prefix + "/"):
      word = home + word[len(prefix):]
      break
  return cwd / os.path.expanduser(word)


def is_within(path, root):
  return path == root or root in path.parents


def protected(word, cwd, root):
  path = resolve_arg(word, cwd)
  return (is_within(Path(os.path.abspath(path)), root.parent)
          or is_within(path.resolve(), root.parent.resolve()))


def skip_literal_heredoc_bodies(command):
  lines = iter(command.splitlines(keepends=True))
  for line in lines:
    # Retain the entire opener so redirects on either side still get checked.
    yield line
    for match in HEREDOC_OPENER.finditer(line):
      quoted, bare = match.group("quoted", "bare")
      if quoted is None and bare is None:
        continue
      delimiter = quoted if quoted is not None else bare
      for body in lines:
        if quoted is None:
          yield body
        candidate = body.lstrip("\t") if match.group("strip_tabs") else body
        if candidate.rstrip("\r\n") == delimiter:
          break


def segments(command):
  lexer = shlex.shlex("".join(skip_literal_heredoc_bodies(command)), posix=True, punctuation_chars=";&|()<>\n")
  lexer.whitespace = " \t\r"
  lexer.whitespace_split = True
  words = []
  for token in lexer:
    if SEPARATOR.fullmatch(token):
      if words:
        yield words
        words = []
    else:
      words.append(token)
  if words:
    yield words


def literal_string(node):
  return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else ""


def inline_python_targets(source):
  try:
    tree = ast.parse(source)
  except SyntaxError:
    return
  for node in ast.walk(tree):
    if not isinstance(node, ast.Call) or not node.args:
      continue
    fn = node.func
    if isinstance(fn, ast.Name) and fn.id == "open":
      mode = node.args[1] if len(node.args) > 1 else next(
        (kw.value for kw in node.keywords if kw.arg == "mode"), None)
      if any(flag in literal_string(mode) for flag in "wax+"):
        yield literal_string(node.args[0])
    if isinstance(fn, ast.Attribute) and fn.attr in {"write_text", "write_bytes"}:
      path = fn.value
      if isinstance(path, ast.Call) and path.args and isinstance(path.func, ast.Name) and path.func.id == "Path":
        yield literal_string(path.args[0])


def match_bash(command, cwd, root):
  try:
    parsed = list(segments(command))
  except ValueError:
    if "logs/auto-mode/modes" in command:
      return "state"
    if "auto-mode/mode.py" in command and BUTTON_SOURCE.search(command):
      return "button"
    return None
  relative_mode = Path("scripts/auto-mode/mode.py")
  modes = {(Path.home() / ".claude" / relative_mode).resolve(),
           (Path(__file__).resolve().parents[1] / relative_mode).resolve()}
  for words in parsed:
    for operator, target in zip(words, words[1:]):
      if OUTPUT_REDIRECT.fullmatch(operator) and protected(target, cwd, root):
        return "state"
    program = next((i for i, word in enumerate(words)
                    if "=" not in word and Path(word).name not in {"command", "env", "sudo"}), None)
    if program is None:
      continue
    verb = Path(words[program]).name
    args = words[program + 1:]
    if verb == "cd" and len(args) == 1:
      cwd = resolve_arg(args[0], cwd).resolve()
      continue
    if verb in COPY_TO_LAST | MUTATORS or (verb in {"sed", "perl"} and any(
        re.match(r"^-[a-zA-Z]*i|^--in-place(?:=|$)", arg) for arg in args)):
      targets = args[-1:] if verb in COPY_TO_LAST else args
      for target in targets:
        if protected(target, cwd, root):
          return "state"
    if re.fullmatch(r"python(?:3(?:\.\d+)?)?", verb) and "-c" in args:
      source = args[args.index("-c") + 1:][:1]
      if any(target and protected(target, cwd, root) for snippet in source for target in inline_python_targets(snippet)):
        return "state"
    if "--source=button" in words or any(
        option == "--source" and arg == "button" for option, arg in zip(words, words[1:])):
      if any(resolve_arg(word, cwd).resolve() in modes for word in words):
        return "button"
  return None


def decide(payload):
  if not isinstance(payload, dict):
    raise ValueError("payload")
  if require_text(payload, "hook_event_name") != "PreToolUse":
    raise ValueError("hook_event_name")
  tool = require_text(payload, "tool_name")
  if tool not in TOOLS:
    return None
  require_text(payload, "session_id")
  cwd = Path(require_text(payload, "cwd"))
  if not cwd.is_absolute():
    raise ValueError("cwd")
  tool_input = payload.get("tool_input")
  if not isinstance(tool_input, dict):
    raise ValueError("tool_input")
  root = Path.home() / ".claude" / "logs" / "auto-mode" / "modes"
  if tool == "Bash":
    return match_bash(require_text(tool_input, "command"), cwd, root)
  path = require_text(tool_input, "file_path")
  if tool == "Write":
    require_text(tool_input, "content", empty=True)
  else:
    require_text(tool_input, "old_string", empty=True)
    require_text(tool_input, "new_string", empty=True)
  return "state" if protected(path, cwd, root) else None


def main():
  reasons = {
    "state": "不可直接寫入自動模式狀態。請使用真人的切換指令，再執行 sync。",
    "button": "自動模式按鈕來源只供 Herdr 使用。請執行 sync 同步真人指令。",
    "invalid": "無法驗證自動模式防寫檢查的輸入。請提供有效工具參數。",
  }
  try:
    reason = decide(json.load(sys.stdin))
  except (ValueError, OSError, RuntimeError):
    reason = "invalid"
  if reason:
    print(json.dumps({"hookSpecificOutput": {
      "hookEventName": "PreToolUse",
      "permissionDecision": "deny",
      "permissionDecisionReason": reasons[reason] + " 如果 Bash 內只是文件文字，請用 Edit 或 Write 寫入一般檔案。",
    }}, ensure_ascii=False))


if __name__ == "__main__":
  main()
