#!/usr/bin/env python3
"""Always-on 規則檔淨增型體積閘門（PreToolUse: Write / Edit / MultiEdit）。

0. Threat model：
- 防漂移型安全閘門：防誠實但健忘的 agent 在寫入或編輯 always-on 規則檔案
  （<CLAUDE_HOME>/CLAUDE.md、<CLAUDE_HOME>/rules/common/*.md、<CLAUDE_HOME>/rules/external/*.md）
  時造成單檔或總量超過體積門檻（14000 / 9728 / 46080 bytes），同時確保減肥與等長重構
  （net_delta <= 0）永遠不被阻擋。
- 明文不承諾：
  1. 不承諾防 Bash / python / cp / mv 等其他寫檔路徑或同一 OS 使用者刻意主動規避；
     本閘門僅監控 PreToolUse 的 Write、Edit、MultiEdit。
  2. 不承諾防假 suppress（例如 agent 填入敷衍但滿足長度要求的理由）；suppress 僅作緊急逃生口並
     寫入審計 log 供事後檢視。
  3. 非 scope 檔案（包含本 gate 自身、測試檔、memory、references、一般專案檔）一律秒放行；
     但一旦路徑判定進入 scope，若 payload 缺欄位、讀取原檔失敗、總量掃描失敗或 cap 設定異常，
     一律 fail-closed deny（唯獨 Edit/MultiEdit 因 old_string 不在原檔而必然失敗時，可安全放行
     交由 CC 回報 Edit 錯誤並記錄）。

1. Surface 四分表：
| 類別 | 範圍 |
|---|---|
| Locked | <CLAUDE_HOME>/hooks/always-on-size-gate.py、<CLAUDE_HOME>/hooks/always-on-size-gate.test.py |
| Editable | <CLAUDE_HOME>/CLAUDE.md、<CLAUDE_HOME>/rules/common/*.md、<CLAUDE_HOME>/rules/external/*.md、其餘非 scope 檔案 |
| Append-only | <CLAUDE_HOME>/logs/always-on-size-gate.jsonl |
| Human-controlled | <CLAUDE_HOME>/settings.json hooks 註冊、<CLAUDE_HOME>/hooks/state/always-on-size-gate.disabled、env ALWAYS_ON_SIZE_GATE_DISABLE=1 |

Locked 面自身生命週期三路徑：
- bootstrap：掛入 settings.json 前先建立本檔與測試檔，跑通 always-on-size-gate.test.py 後再由人控掛載。
- update：本檔與測試檔位於 hooks/，不屬於 always-on scope，修改本檔、helper 或測試檔直接放行，
  並以 `python3 ~/.claude/hooks/always-on-size-gate.test.py` 驗證。
- recovery：設 env `ALWAYS_ON_SIZE_GATE_DISABLE=1` 或建立 `<CLAUDE_HOME>/hooks/state/always-on-size-gate.disabled`
  立即停用放行；緊急單次放行可在寫入內容附 `<!-- size-gate-suppress: 具體理由 -->`（至少 4 個非空白有效字元）；
  或從 settings.json 移除本 hook。

4. 繞行場景表：
1. 改走 Bash（`cat >>` / `python3 -c`）寫入 CLAUDE.md → 本 gate 明文不承諾防 Bash 繞過，僅攔 Write/Edit/MultiEdit。
2. 以 symlink 指向 scope 檔或經 symlink farm 進入 CLAUDE_HOME → 使用 os.path.realpath 正規化目標與 CLAUDE_HOME 後比對，仍攔截。
3. 塞入空白、純符號或過短的 `size-gate-suppress:`（如 `<!-- size-gate-suppress: -->` 或 `ok`）→ 排除空白、符號與控制字元後不足 4 字元仍 deny。
4. 用 MultiEdit 分段累加或 Edit `replace_all=True` 重複展開導致超標 → 依序模擬套用全數 edits 與 replace_all 後重算總 bytes。
5. 損毀環境變數 cap 或原檔無法解析（在 scope 內）→ scope 判定後 fail-closed deny，不因例外靜默放行。
"""

from __future__ import annotations

import json
import os
import re
import stat
import sys
import time
import unicodedata
from pathlib import Path


DEFAULT_CLAUDE_CAP = 14000
DEFAULT_RULE_CAP = 9728
DEFAULT_TOTAL_CAP = 46080
MONITORED_TOOLS = frozenset({"Write", "Edit", "MultiEdit"})
MIN_SUPPRESS_CHARS = 4

ANSI_ESCAPE_RE = re.compile(
  r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-Z\\-_])"
)
CONTROL_BIDI_RE = re.compile(
  r"[\x00-\x1f\x7f-\x9f؜‎‏‪-‮⁦-⁩﻿]"
)
SUPPRESS_RE = re.compile(r"size-gate-suppress:([^\r\n]*)")
HTML_COMMENT_CLOSE_RE = re.compile(r"-->.*$")

STABLE_DENY_PREFIX = (
  "[always-on-size-gate] Always-on 規則檔淨增後超過體積門檻，已攔截本次寫入。"
  "減肥或等長修改（net_delta <= 0）一律放行。\n"
  "兩條正路：\n"
  "1. 先刪減現有條目或將細節下放到 ~/.claude/references/，確認淨增後不超標再寫入。\n"
  "2. 緊急必要新增時，在寫入內容附註 `<!-- size-gate-suppress: 具體理由 -->`（至少 4 個非空白有效字元）即可放行並留存稽核紀錄。"
)


def silent() -> int:
  print("{}")
  return 0


def sanitize_text(value: object) -> str:
  text = "" if value is None else str(value)
  text = ANSI_ESCAPE_RE.sub("", text)
  return CONTROL_BIDI_RE.sub("", text)


def resolve_claude_home() -> str:
  raw = os.environ.get("ALWAYS_ON_SIZE_GATE_CLAUDE_HOME", "").strip()
  base = raw if raw else os.path.join("~", ".claude")
  return os.path.realpath(os.path.expanduser(base))


def resolve_log_path(claude_home_real: str) -> Path:
  override = os.environ.get("ALWAYS_ON_SIZE_GATE_LOG_PATH", "").strip()
  if override:
    return Path(os.path.expanduser(override))
  return Path(claude_home_real) / "logs" / "always-on-size-gate.jsonl"


def resolve_target_path(payload: dict, raw_file_path: str) -> str | None:
  expanded = os.path.expanduser(raw_file_path)
  if not os.path.isabs(expanded):
    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or not cwd:
      return None
    expanded = os.path.join(os.path.expanduser(cwd), expanded)
  return os.path.abspath(expanded)


def parse_positive_int_env(name: str, default: int) -> int:
  raw = os.environ.get(name)
  if raw is None or raw.strip() == "":
    return default
  value = int(raw.strip())
  if value <= 0:
    raise ValueError(f"{name} must be positive")
  return value


def load_caps() -> tuple[int, int, int]:
  claude_cap = parse_positive_int_env("ALWAYS_ON_SIZE_GATE_CLAUDE_CAP", DEFAULT_CLAUDE_CAP)
  rule_cap = parse_positive_int_env("ALWAYS_ON_SIZE_GATE_RULE_CAP", DEFAULT_RULE_CAP)
  total_cap = parse_positive_int_env("ALWAYS_ON_SIZE_GATE_TOTAL_CAP", DEFAULT_TOTAL_CAP)
  return claude_cap, rule_cap, total_cap


def classify_scope(
  lexical_abs: str,
  claude_home_real: str,
) -> tuple[str, str, int] | None:
  """回傳 (canonical_target_path, scope_kind, cap_kind)；非 scope 回傳 None。

  cap_kind: 0 代表 CLAUDE_CAP，1 代表 RULE_CAP。
  """
  claude_md_real = os.path.join(claude_home_real, "CLAUDE.md")
  common_dir_real = os.path.realpath(os.path.join(claude_home_real, "rules", "common"))
  external_dir_real = os.path.realpath(os.path.join(claude_home_real, "rules", "external"))

  target_real = os.path.realpath(lexical_abs)
  if target_real == claude_md_real:
    return target_real, "CLAUDE.md", 0

  target_real_parent = os.path.dirname(target_real)
  target_real_name = os.path.basename(target_real)
  if target_real_name.endswith(".md"):
    if target_real_parent == common_dir_real:
      return target_real, "rules/common", 1
    if target_real_parent == external_dir_real:
      return target_real, "rules/external", 1

  # 若 scope 內放了一個指向外部的 symlink 規則檔，寫入該 symlink 仍會改變 CC 載入體積
  parent_real = os.path.realpath(os.path.dirname(lexical_abs))
  base_name = os.path.basename(lexical_abs)
  if parent_real == claude_home_real and base_name == "CLAUDE.md":
    return os.path.join(parent_real, base_name), "CLAUDE.md", 0
  if base_name.endswith(".md"):
    if parent_real == common_dir_real:
      return os.path.join(parent_real, base_name), "rules/common", 1
    if parent_real == external_dir_real:
      return os.path.join(parent_real, base_name), "rules/external", 1
  return None


def is_disabled(claude_home_real: str) -> bool:
  if os.environ.get("ALWAYS_ON_SIZE_GATE_DISABLE", "").strip() == "1":
    return True
  sentinel = os.path.join(
    claude_home_real, "hooks", "state", "always-on-size-gate.disabled"
  )
  return os.path.lexists(sentinel)


def append_audit_log(
  claude_home_real: str,
  payload: dict,
  target_path: str,
  status: str,
  reason: str,
  pre_bytes: int | None = None,
  post_bytes: int | None = None,
  net_delta: int | None = None,
  post_total: int | None = None,
) -> None:
  log_path = resolve_log_path(claude_home_real)
  row = {
    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "session_id": sanitize_text(payload.get("session_id") or "")[:128],
    "tool_name": sanitize_text(payload.get("tool_name") or "")[:32],
    "path": sanitize_text(target_path)[:512],
    "status": sanitize_text(status)[:32],
    "pre_bytes": pre_bytes,
    "post_bytes": post_bytes,
    "net_delta": net_delta,
    "post_total": post_total,
    "reason": sanitize_text(reason)[:256],
  }
  fd = -1
  try:
    log_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.path.islink(log_path):
      return
    flags = (
      os.O_WRONLY
      | os.O_APPEND
      | os.O_CREAT
      | getattr(os, "O_NOFOLLOW", 0)
      | getattr(os, "O_NONBLOCK", 0)
    )
    fd = os.open(log_path, flags, 0o600)
    info = os.fstat(fd)
    if (
      not stat.S_ISREG(info.st_mode)
      or info.st_uid != os.getuid()
      or info.st_nlink != 1
    ):
      return
    line_bytes = (
      json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    os.write(fd, line_bytes)
  except OSError:
    return
  finally:
    if fd >= 0:
      try:
        os.close(fd)
      except OSError:
        pass


def emit_deny(reason_detail: str) -> int:
  safe_detail = sanitize_text(reason_detail)
  full_reason = f"{STABLE_DENY_PREFIX}\n詳情：{safe_detail}"
  print(
    json.dumps(
      {
        "hookSpecificOutput": {
          "hookEventName": "PreToolUse",
          "permissionDecision": "deny",
          "permissionDecisionReason": full_reason,
        }
      },
      ensure_ascii=False,
    )
  )
  return 0


def compute_current_total(claude_home_real: str, extra_target: str | None = None) -> int:
  candidates: list[str] = []
  claude_md = os.path.join(claude_home_real, "CLAUDE.md")
  if os.path.isfile(claude_md):
    candidates.append(claude_md)

  for sub in ("common", "external"):
    rule_dir = os.path.realpath(os.path.join(claude_home_real, "rules", sub))
    if not os.path.isdir(rule_dir):
      continue
    with os.scandir(rule_dir) as entries:
      for entry in entries:
        if not entry.name.endswith(".md"):
          continue
        full = os.path.join(rule_dir, entry.name)
        if os.path.isfile(full):
          candidates.append(full)

  # 用 realpath 去重，確保 symlink farm 或交叉 symlink 不重複計數
  seen: set[str] = set()
  total = 0
  for path in candidates:
    real_p = os.path.realpath(path)
    if real_p in seen:
      continue
    seen.add(real_p)
    total += os.path.getsize(path)

  if extra_target and os.path.isfile(extra_target):
    extra_real = os.path.realpath(extra_target)
    if extra_real not in seen and extra_target not in seen:
      total += os.path.getsize(extra_target)
  return total


def apply_single_edit(
  content: str, old_string: object, new_string: object, replace_all: object
) -> tuple[bool, str]:
  """回傳 (matched, updated_content)。"""
  if not isinstance(old_string, str) or not isinstance(new_string, str):
    raise ValueError("Edit old_string/new_string must be strings")
  if not isinstance(replace_all, bool):
    raise ValueError("Edit replace_all must be a boolean")
  if old_string == "":
    if content == "":
      return True, new_string
    raise ValueError("Edit old_string cannot be empty for non-empty file")
  if old_string not in content:
    return False, content
  if replace_all:
    return True, content.replace(old_string, new_string)
  return True, content.replace(old_string, new_string, 1)


def simulate_write(
  tool_name: str, tool_input: dict, target_path: str
) -> tuple[bool, int, int, list[str], list[str]]:
  """模擬寫入並回傳 (can_apply, pre_bytes, post_bytes, candidate_suppress_texts, existing_suppress_texts)。

  can_apply=False 只代表 Edit/MultiEdit 的 old_string 不在原檔（CC 本身將報錯）。
  """
  if tool_name == "Write":
    content = tool_input.get("content")
    if not isinstance(content, str):
      raise ValueError("Write tool_input.content must be a string")
    if os.path.lexists(target_path):
      raw_bytes = Path(target_path).read_bytes()
      pre_bytes = len(raw_bytes)
      existing_texts = [raw_bytes.decode("utf-8", errors="replace")]
    else:
      pre_bytes = 0
      existing_texts = []
    post_bytes = len(content.encode("utf-8"))
    return True, pre_bytes, post_bytes, [content], existing_texts

  raw_bytes = Path(target_path).read_bytes()
  pre_bytes = len(raw_bytes)
  working = raw_bytes.decode("utf-8")

  if tool_name == "Edit":
    old_string = tool_input.get("old_string")
    new_string = tool_input.get("new_string")
    replace_all = tool_input.get("replace_all", False)
    matched, updated = apply_single_edit(working, old_string, new_string, replace_all)
    if not matched:
      return False, pre_bytes, pre_bytes, [], []
    return True, pre_bytes, len(updated.encode("utf-8")), [new_string], []

  if tool_name == "MultiEdit":
    edits = tool_input.get("edits")
    if not isinstance(edits, list):
      raise ValueError("MultiEdit tool_input.edits must be a list")
    suppress_texts: list[str] = []
    for edit in edits:
      if not isinstance(edit, dict):
        raise ValueError("MultiEdit item must be an object")
      old_string = edit.get("old_string")
      new_string = edit.get("new_string")
      replace_all = edit.get("replace_all", False)
      matched, working = apply_single_edit(working, old_string, new_string, replace_all)
      if not matched:
        return False, pre_bytes, pre_bytes, [], []
      suppress_texts.append(new_string)
    return True, pre_bytes, len(working.encode("utf-8")), suppress_texts, []

  raise ValueError(f"Unsupported tool: {tool_name}")


def extract_valid_suppress_reasons(texts: list[str]) -> list[str]:
  reasons: list[str] = []
  for text in texts:
    for match in SUPPRESS_RE.finditer(text):
      raw = HTML_COMMENT_CLOSE_RE.sub("", match.group(1))
      clean = " ".join(sanitize_text(raw).split())
      effective = [
        ch for ch in clean if unicodedata.category(ch)[0] in ("L", "N")
      ]
      if len(effective) >= MIN_SUPPRESS_CHARS:
        reasons.append(clean[:256])
  return reasons


def extract_valid_suppress(
  texts: list[str], existing_texts: list[str] | None = None
) -> str | None:
  post_reasons = extract_valid_suppress_reasons(texts)
  if not existing_texts:
    return post_reasons[0] if post_reasons else None

  # 整檔 Write 不得沿用舊檔既有 suppress；僅認列新出現或次數增加的有效理由
  remaining: dict[str, int] = {}
  for reason in extract_valid_suppress_reasons(existing_texts):
    remaining[reason] = remaining.get(reason, 0) + 1

  for reason in post_reasons:
    if remaining.get(reason, 0) > 0:
      remaining[reason] -= 1
    else:
      return reason
  return None


def main() -> int:
  try:
    payload = json.load(sys.stdin)
  except (json.JSONDecodeError, OSError, ValueError):
    return silent()

  if not isinstance(payload, dict):
    return silent()
  tool_name = payload.get("tool_name")
  if tool_name not in MONITORED_TOOLS:
    return silent()
  tool_input = payload.get("tool_input")
  if not isinstance(tool_input, dict):
    return silent()
  raw_file_path = tool_input.get("file_path")
  if not isinstance(raw_file_path, str) or not raw_file_path.strip():
    return silent()

  try:
    claude_home_real = resolve_claude_home()
    lexical_abs = resolve_target_path(payload, raw_file_path)
  except (OSError, ValueError):
    return silent()
  if lexical_abs is None:
    return silent()

  scope = classify_scope(lexical_abs, claude_home_real)
  if scope is None:
    return silent()

  canonical_target, scope_kind, cap_kind = scope

  # 已進入 scope：先檢查停用逃生開關
  try:
    if is_disabled(claude_home_real):
      append_audit_log(
        claude_home_real,
        payload,
        canonical_target,
        status="disabled_bypass",
        reason="disabled",
      )
      return silent()
  except OSError as exc:
    append_audit_log(
      claude_home_real,
      payload,
      canonical_target,
      status="error_deny",
      reason=f"disable_check_failed:{type(exc).__name__}",
    )
    return emit_deny(
      f"target={canonical_target} | error=disable_check_failed ({type(exc).__name__})"
    )

  # 進入 scope 後，任何解析、讀檔或計數失敗一律 fail-closed deny
  try:
    can_apply, pre_bytes, post_bytes, suppress_texts, existing_suppress_texts = (
      simulate_write(tool_name, tool_input, canonical_target)
    )
    if not can_apply:
      append_audit_log(
        claude_home_real,
        payload,
        canonical_target,
        status="edit_noop_allow",
        reason="old_string_not_found",
        pre_bytes=pre_bytes,
        post_bytes=pre_bytes,
        net_delta=0,
      )
      return silent()

    net_delta = post_bytes - pre_bytes
    # 核心防誤吵規則：減肥或等長修改一律立即放行，不依賴 cap 解析或其他受控檔總量掃描
    if net_delta <= 0:
      allow_status = "allow_shrink" if net_delta < 0 else "allow_same"
      append_audit_log(
        claude_home_real,
        payload,
        canonical_target,
        status=allow_status,
        reason=f"scope={scope_kind}",
        pre_bytes=pre_bytes,
        post_bytes=post_bytes,
        net_delta=net_delta,
      )
      return silent()

    claude_cap, rule_cap, total_cap = load_caps()
    file_cap = claude_cap if cap_kind == 0 else rule_cap
    current_total = compute_current_total(claude_home_real, extra_target=canonical_target)
  except (OSError, ValueError, UnicodeDecodeError) as exc:
    append_audit_log(
      claude_home_real,
      payload,
      canonical_target,
      status="error_deny",
      reason=f"parse_or_count_failed:{type(exc).__name__}",
    )
    return emit_deny(
      f"target={canonical_target} | scope={scope_kind} | error=parse_or_count_failed ({type(exc).__name__})"
    )

  post_total = current_total - pre_bytes + post_bytes

  violations: list[str] = []
  if post_bytes > file_cap:
    violations.append(f"file_cap({post_bytes}>{file_cap})")
  if post_total > total_cap:
    violations.append(f"total_cap({post_total}>{total_cap})")

  if not violations:
    append_audit_log(
      claude_home_real,
      payload,
      canonical_target,
      status="allow_within_cap",
      reason=f"scope={scope_kind}",
      pre_bytes=pre_bytes,
      post_bytes=post_bytes,
      net_delta=net_delta,
      post_total=post_total,
    )
    return silent()

  suppress_reason = extract_valid_suppress(
    suppress_texts, existing_texts=existing_suppress_texts
  )
  if suppress_reason is not None:
    append_audit_log(
      claude_home_real,
      payload,
      canonical_target,
      status="suppressed",
      reason=suppress_reason,
      pre_bytes=pre_bytes,
      post_bytes=post_bytes,
      net_delta=net_delta,
      post_total=post_total,
    )
    return silent()

  violations_str = ",".join(violations)
  append_audit_log(
    claude_home_real,
    payload,
    canonical_target,
    status="deny",
    reason=violations_str,
    pre_bytes=pre_bytes,
    post_bytes=post_bytes,
    net_delta=net_delta,
    post_total=post_total,
  )
  return emit_deny(
    f"target={canonical_target} | scope={scope_kind} | pre={pre_bytes}B | "
    f"post={post_bytes}B | delta=+{net_delta}B | file_cap={file_cap}B | "
    f"total_post={post_total}B | total_cap={total_cap}B | violations={violations_str}"
  )


if __name__ == "__main__":
  raise SystemExit(main())
