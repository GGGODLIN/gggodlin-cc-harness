#!/usr/bin/env python3
# 防漂移型提示 gate：
# 1. 字串比對 $PIPESTATUS（外層 shell 非 bash 時 deny）；
# 2. 掃描單引號 `python3 -c '...'`（含可忠實還原的單雙引號／`'\''`／Python 字串內簡單變數拼接，亦支援 `-W` 警告旗標）內含 `\"` 的腳本並以 `ast.parse` 驗證語法，若因反斜線跳脫雙引號觸發 SyntaxError 則 deny；
# 3. 掃描常見測試／型別檢查／lint／格式化／建置／相依安裝與具名驗收命令（含 prettier／eslint／stylelint／biome、pnpm exec、含 `--prefix`/`--dir`/`--cwd`/`-C` 旗標的 npm/pnpm/yarn/bun test|install|ci、外包一層 `bash <wrapper.sh>` 的測試命令、Node 測試與 `*e2e*.[cm]js`／`tdd-policy.mjs`／`check_ui.mjs`、直接執行的 Python 測試檔、`session-retro.py validate`、`openspec validate`、`test-*.sh`、`pack-clean-archive.sh`、`playwright test`、以變數指向的 `$PY -m pytest|unittest`、react-doctor、herdr-app check；前綴 `time` 或包在 `{ … }` 內亦同）直接 `| tail`／`| head`／`| grep`（含 command 前綴）且未設 pipefail 或 PIPESTATUS 的吞錯寫法並 deny；
# 4. 掃描測試／型別檢查／建置／具名驗收命令後段以分號直接接輸出指令或 eslint／prettier，讓後段狀態覆蓋前段退出碼的寫法並 deny（`else` 分支內亦同）；換行分隔只在測試失敗後仍會往下執行時算（該行已接 `||`、`&&` 或續行就不算）；第一句是 `set -e` 且測試段沒有 `||` 時放行。
# 5. 掃描測試命令（不含 lint／格式化／建置／打包腳本）直接接 `|| true`（或 `|| :`）把失敗改成成功的寫法並 deny；測試先 pipe 給 grep 等、管線末端才接 `|| true` 的不在此列（未設 pipefail 時仍由第 3 條處理）。
# 抓取與發布類命令（git push、curl）接 tail/head 的退出碼契約不同，刻意不納入。
# 不承諾完整 shell 語意，也會攔到只是談論該指令的文字（替代路徑：改用 Write/Edit 落檔或 `python3 - <<'PY'` 單引號 heredoc）。
# Surface table: Locked = 本 gate 與測試檔；Editable = 待檢 Bash 指令；Append-only = 審計 JSONL；Human-controlled = settings.json hooks 註冊。
# Locked lifecycle: bootstrap 由 settings.json 掛載；update 直接編輯本檔並跑 pipestatus-zsh-gate.test.py；recovery 從 settings.json 移除或改用落檔執行。
import ast
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time

PIPESTATUS_USE = re.compile(r'\$(?:\{PIPESTATUS(?:\[[^\]]+\])?\}|PIPESTATUS\b)')
BASH_PREFIX = re.compile(
  r'^\s*(?:[A-Za-z_][A-Za-z0-9_]*=\S+\s+)*(?:command\s+)?(?:/[^\s]*/)?bash\s+(?:-[A-Za-z]*c\b|<<)'
)
_PYTHON_FLAGS = r'(?:(?:-[IubBdEJsSOqVv]+|-W\s*(?:default|error|ignore|always|module|once|all)[^\s;|&]*)\s+)*'
PYTHON_C_START = re.compile(
  r'(?:^|[;&|()\s"])(?:/[^\s;()|&"]*/)?python(?:3(?:\.\d+)?)?\s+' + _PYTHON_FLAGS + r'-c\s+(?=\')'
)
# 值的三種寫法互斥（未加引號的值不能以引號開頭）：重疊時一長串 VAR=… 會讓失敗的比對指數回溯，拖住每次 Bash 呼叫。
_ENV_VALUE = r'(?:\"[^\"]*\"|\'[^\']*\'|[^\s\"\']\S*)'
_ENV_PREFIX = (
  r'(?:env\s+(?:[A-Za-z_][A-Za-z0-9_]*=' + _ENV_VALUE + r'\s+)*|(?:[A-Za-z_][A-Za-z0-9_]*=' + _ENV_VALUE + r'\s+)+)?'
)
_LAUNCHER_PREFIX = (
  r'(?:(?:uv|poetry|pipenv)\s+run\s+|(?:npx|pnpm|yarn|bunx)\s+(?:--no-install\s+|--yes\s+|-[sSy]\s+|--silent\s+)*(?:exec\s+)?|(?:[^\s;|&\n]*/)?(?:bash|sh)\s+(?:[^\s;|&\n]*/)?[^\s;|&\n]+\.sh\s+)?'
)
_PKG_FLAGS = r'(?:(?:-[sS]|--silent)\s+|(?:--prefix|--dir|--cwd|-C)(?:=|\s+)[^\s;|&]+\s+)*'
_COMMON_RUNNERS = (
  r'|(?:[^\s;|&\n]*/)?python(?:3(?:\.\d+)?)?\s+' + _PYTHON_FLAGS + r'-m\s+(?:pytest|unittest)\b'
  r'|(?:[^\s;|&\n]*/)?node\s+(?:(?!(?:-e|-p|--eval|--print)\b)-[A-Za-z0-9_-]+(?:=[^\s;|&]+)?\s+)*(?:--test\b|--check\b|[\"\']?(?:[^\s;|&\n\"\']*/)?(?:test|tdd-policy|check_ui|[^\s;|&/\"\']+\.(?:test|spec)|(?:[^\s;|&/\"\']*[-_.]e2e|e2e)[^\s;|&/\"\']*)\.[cm]?js(?=$|[\s;|&\"\']))'
  r'|(?:bun|npm|pnpm|yarn|cargo|go)\s+' + _PKG_FLAGS + r'(?:run\s+)?(?:-[sS]\s+|--silent\s+)*(?:test(?::[^\s;|&]+)?|typecheck|lint|check|build)\b'
  r'|(?:[^\s;|&\n]*/)?claude\s+plugin\s+(?:test|validate)\b'
  r'|(?:[^\s;|&\n]*/)?openspec\s+validate\b'
  r'|(?:[^\s;|&\n]*/)?python(?:3(?:\.\d+)?)?\s+' + _PYTHON_FLAGS + r'(?:[\"\']?(?:[^\s;|&\n\"\']*/)?(?:test_[^\s;|&/\"\']*|[^\s;|&/\"\']*[._-]test)\.py(?=$|[\s;|&\"\'])|[\"\']?(?:[^\s;|&\n\"\']*/)?session-retro\.py[\"\']?\s+validate\b)'
  r'|(?:[^\s;|&\n]*/)?react-doctor(?:@[^\s;|&\n]+)?'
  r'|(?:[^\s;|&\n]*/)?herdr-app\s+check\b'
)
_SH_TEST_FILE = r'|(?:[^\s;|&\n]*/)?(?:bash|sh)\s+[^\n;|&\s]*\.(?:test|spec)\.sh\b'
# 共用於「接 tail」與「`|| true`」兩條測試規則：只收看得出在跑測試的入口，`playwright install`、`$PY build.py`、`test_x.sh` 不算。
_SH_TEST_FILE_WIDE = (
  r'|(?:[^\s;|&\n]*/)?(?:bash|sh)\s+[\"\']?(?:[^\n;|&\s\"\']*/)?(?:[^\n;|&\s/\"\']*\.(?:test|spec)|test-[^\n;|&\s/\"\']*)\.sh\b'
)
# 只進 `_PIPE_RUNNERS`（接 tail/head/grep），不進 `_TEST_ONLY_RUNNERS`（`|| true`）。
_PACK_SCRIPT_PIPE = (
  r'|(?:[^\s;|&\n]*/)?(?:bash|sh)\s+[\"\']?(?:[^\n;|&\s\"\']*/)?pack-clean-archive\.sh(?=$|[\s;|&\"\'])'
  r'|(?:bun|npm|pnpm|yarn)\s+' + _PKG_FLAGS + r'(?:install|ci)\b'
)
_VAR_PYTHON_TEST = r'|\"?\$\{?[A-Za-z_][A-Za-z0-9_]*\}?\"?\s+' + _PYTHON_FLAGS + r'-m\s+(?:pytest|unittest)\b'
_PLAYWRIGHT_TEST = r'|(?:[^\s;|&\n]*/)?playwright\s+test\b'
_PIPE_RUNNERS = (
  r'(?:[^\s;|&\n]*/)?(?:pytest|py\.test|vitest|jest|tsc|prettier|eslint|stylelint|biome)\b'
  + _COMMON_RUNNERS + _SH_TEST_FILE_WIDE + _PACK_SCRIPT_PIPE + _PLAYWRIGHT_TEST + _VAR_PYTHON_TEST
)
# 只收真的在跑測試的入口：`prettier --write || true`、`npm run build || true` 這類刻意容錯的非測試步驟不擋。
_TEST_ONLY_RUNNERS = (
  r'(?:[^\s;|&\n]*/)?(?:pytest|py\.test|vitest|jest)\b'
  r'|(?:[^\s;|&\n]*/)?python(?:3(?:\.\d+)?)?\s+' + _PYTHON_FLAGS + r'-m\s+(?:pytest|unittest)\b'
  r'|(?:[^\s;|&\n]*/)?node\s+(?:[^\n;|&\s]+\s+)*(?:--test\b|(?:[^\s;|&\n]*/)?(?:test|[^\s;|&/]+\.(?:test|spec))\.[cm]?js\b)'
  r'|(?:bun|npm|pnpm|yarn|cargo|go)\s+' + _PKG_FLAGS + r'(?:run\s+)?(?:-[sS]\s+|--silent\s+)*test(?::[^\s;|&]+)?\b'
  r'|(?:[^\s;|&\n]*/)?claude\s+plugin\s+test\b'
  r'|(?:[^\s;|&\n]*/)?python(?:3(?:\.\d+)?)?\s+' + _PYTHON_FLAGS + r'(?:[^\s;|&\n]*/)?(?:test_[^\s;|&/]*|[^\s;|&/]*[._-]test)\.py\b'
  + _SH_TEST_FILE_WIDE + _PLAYWRIGHT_TEST + _VAR_PYTHON_TEST
)
# `time` 前綴與 `{ … }` 群組只是包一層，測試退出碼照樣會被後段吞掉。
_TEST_START = r'(?:^|[;&(){\n]|&&|\|\|)\s*(?:time\s+(?:-p\s+)?)?' + _ENV_PREFIX + _LAUNCHER_PREFIX
# 中段 `|` 後的空白只交給 `[^;&|\n]` 吃，不讓 `|[ \t]*` 也能吃：兩條路都能吃同一段空白時，一長串 `| cat` 會指數回溯。
TEST_PIPE_SWALLOW = re.compile(
  _TEST_START + r'(?P<runner>' + _PIPE_RUNNERS + r')'
  r'(?:[^;&|\n]|(?<=>)&|\|(?!\|)(?![ \t]*(?:command\s+)?(?:[^\s;|&\n]*/)?(?:tail|head|grep)\b))*\|(?!\|)[ \t]*(?:command\s+)?(?:[^\s;|&\n]*/)?(?P<sink>tail|head|grep)\b'
)
# 只認 `|| true` 直接接在測試本身：中間隔了 pipe（例如先 grep 篩失敗再容錯）是使用者選擇保留的診斷寫法。
TEST_OR_TRUE = re.compile(
  r'(?:^|[;&(){\n]|&&|\|\|)\s*(?:else\s+)?(?:time\s+(?:-p\s+)?)?' + _ENV_PREFIX + _LAUNCHER_PREFIX +
  r'(?P<runner>' + _TEST_ONLY_RUNNERS + r')'
  r'(?:[^;&|\n]|(?<=>)&)*\|\|\s*(?P<fallback>true|:)(?=[\s;)&|]|$)'
)
TEST_TRAILING_MASK = re.compile(
  r'(?:^|[;&()\n]|&&|\|\|)\s*(?:else\s+)?' + _ENV_PREFIX + _LAUNCHER_PREFIX +
  r'(?P<runner>'
  r'(?:[^\s;|&\n]*/)?(?:pytest|py\.test|vitest|jest|tsc|prettier)\b' + _COMMON_RUNNERS + _SH_TEST_FILE +
  r')'
  r'(?P<tail>[^\n;]*)(?P<sep>[;\n])\s*(?P<mask>(?:(?:npx|pnpm|yarn|bunx)\s+(?:exec\s+)?)?(?:/[^\s;|&\n]*/)?(?:ls|echo|printf|true|pwd|date|cat|eslint|prettier)\b[^\n;]*)(?:[;\n]|\s*$)'
)
LEADING_COMMENTS = re.compile(r'^(?:[ \t]*(?:#[^\n]*)?\n)+')
TRAILING_COMMENT = re.compile(r'\s#.*$')
PIPEFAIL_GUARD = re.compile(r'\b(?:set\s+-[A-Za-z]*o\s+pipefail|PIPESTATUS|pipestatus)\b')
# 只認第一句就是 `set -e`（或 -eu、-euo pipefail、-o errexit）：放在後面或包在子 shell 裡，生效範圍就看不出來。
TOP_LEVEL_ERREXIT = re.compile(
  r'^\s*set\s+(?:-[A-Za-z]*e[A-Za-z]*|-o\s+errexit)(?:\s+(?:-[A-Za-z]+|[A-Za-z]+))*\s*(?:;|&&|\n)'
)
# 管線中段的 `| timeout …` 一樣會在本機報 127；ssh 遠端字串內的 timeout 看不出來，屬已知誤擋邊角。
BARE_TIMEOUT_PREFIX = re.compile(
  r'(?:^|[;&()\n|]|&&|\|\|)\s*' + _ENV_PREFIX +
  r'(?P<cmd>timeout\s+(?:-[A-Za-z0-9-]+\s+)*\d+(?:\.\d+)?[smhd]?\s+\S+)'
)
SAFE_QUOTED_HEREDOC = re.compile(
  r'^(?P<prefix>\s*[^<#\r\n]*\S)\s*(?<!\\)<<(?P<strip_tabs>-)?\s*'
  r'(?P<quote>[\'\"])(?P<delimiter>[^\'\"\r\n]+)(?P=quote)\s*$'
)


def strip_safe_single_quoted_heredoc(command):
  if command.count('<<') != 1:
    return command
  lines = command.splitlines(keepends=True)
  for opener_index, line in enumerate(lines):
    match = SAFE_QUOTED_HEREDOC.match(line.rstrip('\r\n'))
    if not match:
      continue
    delimiter = match.group('delimiter')
    strip_tabs = bool(match.group('strip_tabs'))
    for terminator_index in range(opener_index + 1, len(lines)):
      candidate = lines[terminator_index].rstrip('\r\n')
      if strip_tabs:
        candidate = candidate.lstrip('\t')
      if candidate != delimiter:
        continue
      output = lines.copy()
      for body_index in range(opener_index + 1, terminator_index):
        output[body_index] = '\n' if output[body_index].endswith(('\n', '\r')) else ''
      return ''.join(output)
    return command
  return command


def read_payload():
  try:
    payload = json.load(sys.stdin)
  except json.JSONDecodeError:
    return None
  return payload if isinstance(payload, dict) else None


def outer_shell():
  return os.environ.get('SHELL', '')


def outer_shell_is_bash(shell):
  return os.path.basename(shell.strip()) == 'bash'


def append_audit(command, session, shell, reason='outer-zsh-pipestatus'):
  path = Path(os.environ.get('PIPESTATUS_GATE_AUDIT', os.path.expanduser('~/.claude/logs/pipestatus-zsh-gate-audit.jsonl')))
  row = {
    'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    'session': session,
    'action': 'deny',
    'reason': reason,
    'shell': shell,
  }
  try:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as handle:
      handle.write(json.dumps(row, ensure_ascii=False) + '\n')
  except OSError as error:
    print(f'[pipestatus-zsh-gate] audit write failed: {error}', file=sys.stderr)


def _in_outer_double_quotes(command, pos):
  # 檢查從該行開頭到 pos 之間是否處於未閉合的外層雙引號內（如 `bash -c "python3 -c '...'"`）；
  # 處於外層雙引號時，遇到 `"` 視為外層結尾而非拼接段，避免跨分號誤吞後續指令。
  line_start = command.rfind('\n', 0, pos) + 1
  in_double = False
  in_single = False
  i = line_start
  while i < pos:
    ch = command[i]
    if in_single:
      if ch == "'":
        in_single = False
    elif in_double:
      if ch == '\\' and i + 1 < pos:
        i += 2
        continue
      if ch == '"':
        in_double = False
    else:
      if ch == '\\' and i + 1 < pos:
        i += 2
        continue
      if ch == "'":
        in_single = True
      elif ch == '"':
        in_double = True
    i += 1
  return in_double


def _in_python_string_quote(prefix):
  # 粗判已累積的 Python 程式碼末尾是否正落在未閉合的單/雙引號字串內（只在引號內才允許用佔位字 `X` 代替動態 shell 變數）。
  quote = None
  i = 0
  n = len(prefix)
  while i < n:
    ch = prefix[i]
    if quote is None:
      if ch == '#':
        nl = prefix.find('\n', i + 1)
        if nl < 0:
          break
        i = nl + 1
        continue
      if ch in ("'", '"'):
        if prefix[i:i + 3] == ch * 3:
          quote = ch * 3
          i += 3
          continue
        quote = ch
    else:
      if ch == '\\' and i + 1 < n:
        i += 2
        continue
      if len(quote) == 3 and prefix[i:i + 3] == quote:
        quote = None
        i += 3
        continue
      if len(quote) == 1 and ch == quote:
        quote = None
    i += 1
  return quote is not None


def _decode_posix_double_quoted(raw):
  # 不含未跳脫 `$` 與反引號的純字面雙引號片段：按 POSIX 雙引號規則還原 `\"`、`\\`、`\$`、`` \` ``。
  out = []
  i = 0
  n = len(raw)
  has_dynamic = False
  while i < n:
    ch = raw[i]
    if ch == '\\' and i + 1 < n and raw[i + 1] in ('"', '\\', '$', '`', '\n'):
      if raw[i + 1] != '\n':
        out.append(raw[i + 1])
      i += 2
      continue
    if ch in ('$', '`'):
      has_dynamic = True
    out.append(ch)
    i += 1
  return ''.join(out), has_dynamic


def extract_python_c_single_quoted_scripts(command):
  # 單調前進掃描單引號 `-c '...'` 及緊鄰的可還原拼接段（`'\''`、純字面 `"..."`、以及 Python 字串引號內的簡單 `$VAR`/`${VAR}`）；
  # 外層已被雙引號包住時遇 `"` 即停，遇無法忠實還原的動態展開則放棄語法誤殺判定。
  scripts = []
  n = len(command)
  cursor = 0
  while cursor < n:
    match = PYTHON_C_START.search(command, cursor)
    if not match:
      break
    i = match.end()
    in_outer_double = _in_outer_double_quotes(command, match.end())
    parts = []
    closed = False
    unfaithful = False
    while i < n:
      ch = command[i]
      if ch == "'":
        end = command.find("'", i + 1)
        if end < 0:
          closed = False
          break
        parts.append(command[i + 1:end])
        i = end + 1
        closed = True
      elif ch == '\\' and i + 1 < n and command[i + 1] == "'" and parts:
        parts.append("'")
        i += 2
      elif ch == '$' and parts:
        j = i + 1
        if j < n and command[j] == '{':
          j += 1
          start_name = j
          while j < n and (command[j].isalnum() or command[j] == '_'):
            j += 1
          if j == start_name or j >= n or command[j] != '}':
            unfaithful = True
            break
          i = j + 1
        else:
          while j < n and (command[j].isalnum() or command[j] == '_'):
            j += 1
          if j == i + 1:
            unfaithful = True
            break
          i = j
        if _in_python_string_quote(''.join(parts)):
          parts.append('X')
        else:
          unfaithful = True
          break
      elif ch == '"' and parts and not in_outer_double:
        j = i + 1
        while j < n and command[j] != '"':
          if command[j] == '\\' and j + 1 < n:
            j += 2
          else:
            j += 1
        if j >= n:
          unfaithful = True
          break
        literal, has_dynamic = _decode_posix_double_quoted(command[i + 1:j])
        i = j + 1
        if not has_dynamic:
          parts.append(literal)
        elif _in_python_string_quote(''.join(parts)):
          parts.append('X')
        else:
          unfaithful = True
          break
      else:
        break
    cursor = max(i, match.end())
    if closed and parts and not unfaithful:
      scripts.append(''.join(parts))
  return scripts


def find_python_c_escaped_quote_error(command):
  for code in extract_python_c_single_quoted_scripts(command):
    if '\\"' not in code:
      continue
    try:
      ast.parse(code)
    except SyntaxError as err:
      return err.msg or 'SyntaxError'
  return None


def find_unprotected_test_pipe(command):
  if PIPEFAIL_GUARD.search(command):
    return None
  match = TEST_PIPE_SWALLOW.search(command)
  if not match:
    return None
  return f"{match.group('runner').strip()} | {match.group('sink')}"


def find_trailing_test_mask(command):
  errexit = bool(TOP_LEVEL_ERREXIT.match(LEADING_COMMENTS.sub('', command)))
  position = 0
  while True:
    match = TEST_TRAILING_MASK.search(command, position)
    if not match:
      return None
    tail = match.group('tail')
    code_tail = TRAILING_COMMENT.sub('', tail).rstrip()
    # 換行不同於分號：該行已接 `||`（如 `|| exit $?`）、`&&` 或續行時，測試失敗走不到下一行，不算遮蔽。
    exempt = match.group('sep') == '\n' and ('||' in code_tail or code_tail.endswith(('&&', '|', '\\')))
    # 頂層 set -e 讓測試一失敗 shell 就退出；只看測試這一段自己有沒有 `||`，下一行指令自帶的 fallback 不影響。
    exempt = exempt or (errexit and '||' not in tail)
    if not exempt:
      mask_cmd = match.group('mask').strip().split()[0]
      separator = ';' if match.group('sep') == ';' else '⏎'
      return f"{match.group('runner').strip()} ...{separator} {mask_cmd}"
    # 從分隔符號重找：被當成 mask 的那一行本身也可能是下一段檢查（如 `prettier --check`）。
    position = match.start('sep')


def find_test_or_true(command):
  match = TEST_OR_TRUE.search(command)
  if not match:
    return None
  return f"{match.group('runner').strip()} ... || {match.group('fallback')}"


def find_missing_bare_timeout(command):
  search_path = os.environ.get('PIPESTATUS_TIMEOUT_PATH', os.environ.get('PATH', ''))
  if shutil.which('timeout', path=search_path) is not None:
    return None
  match = BARE_TIMEOUT_PREFIX.search(command)
  if not match:
    return None
  return match.group('cmd').strip()


def main():
  payload = read_payload()
  if payload is None:
    return
  if payload.get('tool_name', 'Bash') != 'Bash':
    return
  tool_input = payload.get('tool_input')
  if not isinstance(tool_input, dict):
    return
  command = tool_input.get('command', '')
  if not isinstance(command, str):
    return
  scan_command = strip_safe_single_quoted_heredoc(command)
  shell = outer_shell()
  py_err = find_python_c_escaped_quote_error(scan_command)
  if py_err is not None:
    append_audit(command, payload.get('session_id', ''), shell, reason='python-c-escaped-quote-syntax-error')
    reason = (
      f'單引號 `python3 -c \'...\'` 內含 `\\"` 且無法通過 Python AST 語法解析（{py_err}）。'
      '在單引號腳本的雙引號 f-string 表達式內寫 `\\"` 會直接觸發 SyntaxError；'
      '請改用 `python3 - <<\'PY\'` 多行單引號 heredoc、在 f-string 內改用單引號（或 Python 3.12+ 直接不加反斜線），或先抽為局部變數。'
    )
    print(json.dumps({
      'hookSpecificOutput': {
        'hookEventName': 'PreToolUse',
        'permissionDecision': 'deny',
        'permissionDecisionReason': reason,
      }
    }, ensure_ascii=False))
    return
  swallowed = find_unprotected_test_pipe(scan_command)
  if swallowed is not None:
    append_audit(command, payload.get('session_id', ''), shell, reason='unprotected-test-pipe-tail-head')
    reason = (
      f'偵測到測試／檢查命令直接 pipe 給 tail/head/grep（`{swallowed}`），但未設定 `set -o pipefail`。'
      '這會讓 tail/head/grep 自己的退出碼取代上游測試或編譯失敗的退出碼；'
      '請在實際執行該管線的 shell 內加上 `set -o pipefail;`（若管線包在 `bash -c` 內，須加在內層 shell，或先執行測試保存退出碼再處理輸出；直接移除 `| tail`／`| head`／`| grep` 亦可），若只是寫文件或測試資料請改用 Write/Edit 落檔或 `<<\'EOF\'` 單引號 heredoc。'
    )
    print(json.dumps({
      'hookSpecificOutput': {
        'hookEventName': 'PreToolUse',
        'permissionDecision': 'deny',
        'permissionDecisionReason': reason,
      }
    }, ensure_ascii=False))
    return
  trailing_mask = find_trailing_test_mask(scan_command)
  if trailing_mask is not None:
    append_audit(command, payload.get('session_id', ''), shell, reason='trailing-command-masks-test-exit')
    reason = (
      f'偵測到測試／檢查命令後段直接用分號 `;` 或換行尾接可能遮住前段狀態的指令（`{trailing_mask}`）。'
      '即使前段已設 `set -o pipefail`，尾段的 `ls`／`echo`／`true` 或成功的 eslint／prettier 仍會把整個 shell 的退出碼覆蓋為 0（吞掉測試紅燈）；'
      '請改用 `&&` 串接、拆成獨立呼叫，或顯式保存 `rc=$?; ...; exit $rc`，若只是寫文件或測試資料請改用 Write/Edit 落檔或 `<<\'EOF\'` 單引號 heredoc。'
    )
    print(json.dumps({
      'hookSpecificOutput': {
        'hookEventName': 'PreToolUse',
        'permissionDecision': 'deny',
        'permissionDecisionReason': reason,
      }
    }, ensure_ascii=False))
    return
  missing_timeout = find_missing_bare_timeout(scan_command)
  if missing_timeout is not None:
    append_audit(command, payload.get('session_id', ''), shell, reason='missing-gnu-timeout-command')
    reason = (
      f'偵測到命令使用裸 `timeout` 前綴（`{missing_timeout}`），但目前 macOS 環境 PATH 未安裝 GNU `timeout`（執行會報 Exit 127 command not found）。'
      '若需要「到期強制終止子程序」，請改用該命令自帶的限時旗標（如 `curl -m`）或 `python3 -I -c "import subprocess; subprocess.run([\'...\'], timeout=N, check=True)"`；'
      '若只需設定「前景等待上限」（注意：Bash 工具的 `timeout` 參數逾時後會將命令轉入背景繼續執行，不會自動終止子程序），請改填 Bash 工具的 `timeout` 參數，若只是寫文件或測試資料請改用 Write/Edit 落檔或 `<<\'EOF\'` 單引號 heredoc。'
    )
    print(json.dumps({
      'hookSpecificOutput': {
        'hookEventName': 'PreToolUse',
        'permissionDecision': 'deny',
        'permissionDecisionReason': reason,
      }
    }, ensure_ascii=False))
    return
  # 排在既有規則之後：同一呼叫同時命中時，保留原本的拒絕原因。
  test_or_true = find_test_or_true(scan_command)
  if test_or_true is not None:
    append_audit(command, payload.get('session_id', ''), shell, reason='test-or-true-swallow')
    reason = (
      f'偵測到測試命令直接接 `|| true`／`|| :`（`{test_or_true}`），測試失敗會被改成成功退出，外層看不到紅燈。'
      '請改成 `cmd; rc=$?; ...; exit $rc` 保存退出碼，或拆成獨立呼叫直接看結果；'
      '若只是寫文件或測試資料請改用 Write/Edit 落檔或 `<<\'EOF\'` 單引號 heredoc。'
    )
    print(json.dumps({
      'hookSpecificOutput': {
        'hookEventName': 'PreToolUse',
        'permissionDecision': 'deny',
        'permissionDecisionReason': reason,
      }
    }, ensure_ascii=False))
    return
  if not PIPESTATUS_USE.search(scan_command):
    return
  if BASH_PREFIX.search(scan_command):
    return
  if outer_shell_is_bash(shell):
    return

  append_audit(command, payload.get('session_id', ''), shell)
  reason = (
    'PIPESTATUS 是 Bash 專屬變數，但偵測不到 Bash tool 的外層 shell 是 bash（多半是 zsh），這條指令會失敗。'
    '請改用明確的 if 分支保存 exit code，或把整段指令包進 `bash -lc`／`/bin/bash -c` 後重試。'
    f'偵測值 SHELL={shell or "(未設定)"}'
  )
  print(json.dumps({
    'hookSpecificOutput': {
      'hookEventName': 'PreToolUse',
      'permissionDecision': 'deny',
      'permissionDecisionReason': reason,
    }
  }, ensure_ascii=False))


if __name__ == '__main__':
  main()
