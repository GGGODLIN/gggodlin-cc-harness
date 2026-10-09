#!/usr/bin/env python3
"""semble-root-block — PreToolUse hook for mcp__semble__search / mcp__semble__find_related.

Threat model: 防漂移（誠實但忘記 scope 的 agent 把 aggregation root 丟給常駐 semble MCP，
造成大索引留在 MCP process 記憶體）。只比對 MCP `repo` 參數解析後的實體路徑，
不承諾防刻意規避、不掃 Bash（semble CLI 一次性 process 結束即釋放記憶體，屬可接受形狀）、
不判斷未列在 ROOTS 的其他大目錄。判不出來一律 deny（安全型）。

Recovery：建立 sentinel 檔 `~/.claude/hooks/state/semble-root-block/disabled` 即整支放行；
或從 settings.json PreToolUse 移除本 matcher。Update：本檔與測試不在 matcher 範圍內，直接 Edit。
Tests: bash ~/.claude/hooks/semble-root-block.test.sh
"""
import json
import os
import sys
from pathlib import Path

HOME = Path(os.environ.get("SEMBLE_ROOT_BLOCK_HOME") or Path.home())
ROOTS = [
  HOME / "Desktop" / "projects",
  HOME / "Desktop" / "work",
  HOME / "Desktop" / "work" / "acme",
  HOME / "code",
]
SENTINEL = Path(os.environ.get("SEMBLE_ROOT_BLOCK_SENTINEL") or (HOME / ".claude" / "hooks" / "state" / "semble-root-block" / "disabled"))
TOOLS = {"mcp__semble__search", "mcp__semble__find_related"}
TAG = "[semble-root-block]"


def emit_deny(reason):
  print(json.dumps({
    "hookSpecificOutput": {
      "hookEventName": "PreToolUse",
      "permissionDecision": "deny",
      "permissionDecisionReason": f"{TAG} {reason}",
    }
  }, ensure_ascii=False))


def resolve(raw):
  text = str(raw).strip()
  if not text:
    return None
  lowered = text.lower()
  if lowered.startswith(("http://", "https://", "git@", "ssh://")):
    return "remote"
  expanded = os.path.expanduser(text)
  try:
    return Path(expanded).resolve(strict=False)
  except (OSError, RuntimeError, ValueError):
    return None


def is_root_or_ancestor(path):
  for root in ROOTS:
    try:
      real_root = root.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
      real_root = root
    if path == real_root or path in real_root.parents:
      return real_root
  return None


def main():
  try:
    payload = json.load(sys.stdin)
  except (json.JSONDecodeError, ValueError):
    emit_deny("payload 不是合法 JSON，安全型 gate 拒絕")
    return
  if not isinstance(payload, dict) or payload.get("tool_name") not in TOOLS:
    return
  if SENTINEL.exists():
    print(f"{TAG} sentinel 存在，放行", file=sys.stderr)
    return
  tool_input = payload.get("tool_input")
  if not isinstance(tool_input, dict):
    emit_deny("tool_input 缺失或非物件，拒絕")
    return
  repo = tool_input.get("repo")
  if repo is None:
    emit_deny("repo 參數缺失；semble MCP 必須指定單一 repo 路徑")
    return
  resolved = resolve(repo)
  if resolved is None:
    emit_deny(f"repo 無法解析：{str(repo)[:120]!r}")
    return
  if resolved == "remote":
    return
  hit = is_root_or_ancestor(resolved)
  if hit is None:
    return
  emit_deny(
    f"拒絕對聚合根目錄建 semble MCP 索引（repo={str(repo)[:120]} 涵蓋 {hit}）。"
    "替代：1) 點名單一 git repo 再呼叫 semble；2) 跨 repo 用 grep -r／rg；"
    "3) 真要跨 repo 語意搜，用一次性 CLI `semble search \"<query>\" <root> -k 5`，process 結束記憶體即釋放。"
  )


if __name__ == "__main__":
  main()
