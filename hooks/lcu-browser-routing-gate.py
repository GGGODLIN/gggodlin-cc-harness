#!/usr/bin/env python3
# 防漂移型 PreToolUse gate（lcu-browser-routing-gate）：
# Threat model：
# - 對誰有效：防誠實但手滑的模型在呼叫 `mcp__lcu__js` 時：(1) 寫出 LCU Tab 不存在的 Playwright 方法
#   （`.playwright.evaluate(`、`.evaluate(`、`tab.waitForEvent(`、`.page(`、`.waitForLoadState(`、`.setInputFiles(`；保留官方支援的
#   `tab.playwright.waitForEvent("filechooser")` 與 `tab.playwright.locator(...).click()` 上傳入口）；或 (2) 在同一次 `mcp__lcu__js` 呼叫內對數字索引連續執行
#   2 次以上點擊（`.click(56)` 緊接 `.click(65)`），未先結束本次呼叫讀回新鮮 AX 狀態再選下一個索引。
# - 明文不保證：
#   1. 字串比對型 gate 不承諾完整 JS AST 語意解析，只認常見方法呼叫形狀；認不出來或單純連續 `.setValue(`／`.paste(` 填表則放行。
#   2. 字串比對型 gate 也會攔到 `code` 字串常數中出現上述呼叫字樣的情況（替代路徑：移除無效 API 字樣，
#      或將多次數字索引點擊拆成每次「點擊＋await tab.getAXState()」的獨立 `mcp__lcu__js` 呼叫）。
# Surface 四分表：
# - Locked: ~/.claude/hooks/lcu-browser-routing-gate.py 與 ~/.claude/hooks/lcu-browser-routing-gate.test.py
# - Editable: 待檢 `mcp__lcu__js` 呼叫之 `tool_input.code`
# - Append-only: ~/.claude/logs/lcu-browser-routing-gate-audit.jsonl
# - Human-controlled: ~/.claude/settings.json hooks 註冊
# 自身生命週期三路徑：
# - bootstrap: 掛上 settings.json 前先建立本檔與測試檔並跑通契約測試
# - update: 本 gate 僅掛載於 `mcp__lcu__js`，不攔截 Edit/Write/Bash，可直接修改本檔與跑測試
# - recovery: 設環境變數 LCU_ROUTING_GATE_DISABLE=1 或從 ~/.claude/settings.json 移除本 hook
# 本檔在契約測試底下：python3 ~/.claude/hooks/lcu-browser-routing-gate.test.py
import json
import os
from pathlib import Path
import re
import stat
import sys
import time

LOG_LIMIT = 512 * 1024
LINE_COMMENT_RE = re.compile(r'(?m)^\s*//.*$')
BLOCK_COMMENT_RE = re.compile(r'/\*.*?\*/', re.DOTALL)

UNSUPPORTED_PLAYWRIGHT_RE = re.compile(
  r'(?:\.\s*playwright\s*\.\s*evaluate\s*\('
  r'|\b(?<!playwright\.)evaluate\s*\('
  r'|\.\s*page\s*\(\s*\)'
  r'|\.\s*waitForLoadState\s*\('
  r'|\.\s*setInputFiles\s*\('
  r'|\.\s*scrollIntoViewIfNeeded\s*\('
  r'|(?<!playwright)\.\s*waitForEvent\s*\('
  r'|\.\s*inputValue\s*\('
  r'|\b(?!cua\b)[A-Za-z_$][A-Za-z0-9_$]*\s*\.\s*getState\s*\('
  r'|\b(?!cua\b)[A-Za-z_$][A-Za-z0-9_$]*\s*\.\s*snapshot\s*\('
  r'|\b(?!cua\b|Promise\b)[A-Za-z_$][A-Za-z0-9_$]*\s*\.\s*wait\s*\()'
)
NUMERIC_CLICK_RE = re.compile(r'\.\s*(?:click|doubleClick|rightClick)\s*\(\s*(\d+)\b')


def strip_comments(code):
  return LINE_COMMENT_RE.sub('', BLOCK_COMMENT_RE.sub('', code))


def append_audit(session_id, reason, detail):
  audit_path = Path(
    os.environ.get(
      'LCU_ROUTING_GATE_AUDIT',
      str(Path.home() / '.claude/logs/lcu-browser-routing-gate-audit.jsonl'),
    )
  )
  row = {
    'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    'session': session_id,
    'action': 'deny',
    'reason': reason,
    'detail': detail[:80],
  }
  try:
    audit_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    parent_info = audit_path.parent.lstat()
    if not stat.S_ISDIR(parent_info.st_mode) or parent_info.st_uid != os.getuid():
      return
    fd = os.open(
      audit_path,
      os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
      0o600,
    )
    with os.fdopen(fd, 'a', encoding='utf-8') as handle:
      info = os.fstat(handle.fileno())
      if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_nlink != 1
        or info.st_size > LOG_LIMIT
      ):
        return
      handle.write(json.dumps(row, ensure_ascii=False) + '\n')
  except OSError:
    return


def inspect_lcu_code(code):
  cleaned = strip_comments(code)
  bad_api = UNSUPPORTED_PLAYWRIGHT_RE.search(cleaned)
  if bad_api:
    token = bad_api.group(0).strip()
    return (
      'unsupported-playwright-api',
      token,
      (
        '偵測到 `mcp__lcu__js` 呼叫了 LCU Tab 不支援的 Playwright 方法（`'
        + token
        + '`）。依 `browser-routing.md`，LCU Tab 不提供 `.playwright.evaluate`、`tab.evaluate`、`.page()`、'
        '`waitForLoadState` 或 `setInputFiles`；請改用 LCU 原生方法（如 `await tab.getAXState()`、'
        '`await tab.click(uid)`、`await tab.setValue(uid, text)`；僅無 AX input 的檔案上傳例外可用 '
        '`tab.playwright.locator(...).click()`）。'
      ),
    )
  clicks = [m.group(0).strip() for m in NUMERIC_CLICK_RE.finditer(cleaned)]
  if len(clicks) >= 2:
    joined = ' -> '.join(clicks[:3])
    return (
      'chained-numeric-clicks-in-single-call',
      joined,
      (
        '偵測到單次 `mcp__lcu__js` 呼叫中連續預寫了多個數字索引點擊（`'
        + joined
        + '`）。點擊會改變頁面與無障礙樹（AX）狀態，即使在同段 code 中間插入 `getAXState()`，'
        '第二個數字索引仍是看到新畫面之前盲猜的舊編號；請在第一次點擊並呼叫 `await tab.getAXState()` 後結束本次呼叫，'
        '等讀回最新元素索引後，再於下一次呼叫執行下一個點擊。'
      ),
    )
  return None


def main():
  if os.environ.get('LCU_ROUTING_GATE_DISABLE') == '1':
    return
  try:
    payload = json.load(sys.stdin)
  except (json.JSONDecodeError, OSError):
    return
  if not isinstance(payload, dict):
    return
  if payload.get('tool_name') != 'mcp__lcu__js':
    return
  tool_input = payload.get('tool_input')
  if not isinstance(tool_input, dict):
    return
  code = tool_input.get('code')
  if not isinstance(code, str) or not code.strip():
    return
  finding = inspect_lcu_code(code)
  if finding is None:
    return
  reason_code, detail, message = finding
  append_audit(str(payload.get('session_id', '')), reason_code, detail)
  print(
    json.dumps(
      {
        'hookSpecificOutput': {
          'hookEventName': 'PreToolUse',
          'permissionDecision': 'deny',
          'permissionDecisionReason': message,
        }
      },
      ensure_ascii=False,
    )
  )


if __name__ == '__main__':
  main()
