#!/usr/bin/env python3
"""Hint-only: async Stop judge, local next-human-prompt delivery. See auto-memory-jev.md."""
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request

try:
  from memory_reminder_common import SafeDirectory, SESSION_RE, last_long, mark_long, reminder
except ImportError:
  if __name__ == '__main__':
    sys.exit(0)
  raise

PPLX_MODEL = 'openrouter/perplexity/pplx-decider-v1.3:free'
PPLX_BASE = 'http://127.0.0.1:8317'
PPLX_TIMEOUT = 3.0
PPLX_FALLS_TO_NEXT = ('pplx_quota_cooldown', 'missing_pplx_key', 'missing_zero_cost_evidence', 'unexpected_model')
VERCEL_MODEL = 'vercel-decide/perplexity/pplx-decider-v1.3'
VERCEL_CREDITS_BASE = 'https://ai-gateway.vercel.sh'
VERCEL_CREDITS_TIMEOUT = 2.0
VERCEL_TIMEOUT = 2.5
VERCEL_MAX_FREE_USD = 5.0
VERCEL_FALLS_TO_JEV = ('vercel_quota_cooldown', 'missing_pplx_key', 'missing_vercel_key',
                       'vercel_free_not_confirmed', 'vercel_bad_response', 'unexpected_model')
AMD_MODEL = 'amd-tokenlab/d3'
AMD_TIMEOUT = 4.5
AMD_MIN_BUDGET_S = 0.8
AMD_POINTS_PER_INPUT_TOKEN = 3.5e-8  # AMD Token Lab input token 估算權重
STOP_HOOK_BUDGET_S = 9.2
TAIL_LEGS_RESERVE_S = 2.5
AMD_FALLS_TO_JEV = ('amd_quota_cooldown', 'missing_pplx_key', 'missing_amd_key',
                    'amd_bad_response', 'amd_budget_tight', 'unexpected_model')
MODEL = 'type-safe/jev-latest:free'
BASE = 'https://api.experientiallabs.ai'
TIMEOUT = 1.2
THRESHOLD = 0.5
TAIL_FROM_BYTES = 64 * 1024 * 1024
TAIL_START_BYTES = 8 * 1024 * 1024
# 五腿順序（總逾時控制在 settings.json Stop 10 秒上限內）：1) OpenRouter Perplexity Decider v1.3 (:free)
# → 2) Magpie vercel-decide/v1.3（使用免費點數層，每小時快取查 /v1/credits 確認為免費層且尚有餘額）
# → 3) Magpie amd-tokenlab/d3（使用免費贈點備援，無 usage.cost 欄，剩餘時間夾限上限 4.5 秒）
# → 4) Experiential Jev (:free) → 5) Drex（nace 贈額）。
# 選 v2.0 不選 v1.5：2026-10-17 用本 hook 的 packet 對 120 個真實回合並列，v2.0 在 0.5 門檻觸發 11 次對 Jev 16 次、
# 一致 107/120；v1.5 要 0.8 才對齊，而且多抓的是結案狀態回報。題目與門檻沿用、不另校。
DREX_MODEL = 'drex-v2.0'
DREX_BASE = 'https://console.nace.ai'
DREX_USD_PER_INPUT_TOKEN = 6e-8  # console.nace.ai/docs/drex/reference/pricing：60 nUSD／input token，output 免費
# 這些 Jev 失敗才換腿；nonzero_cost／missing_zero_cost_evidence 是免費契約被破壞，照舊停用或冷卻中止、不讓 Drex 蓋過去。
JEV_FALLS_TO_DREX = ('quota_cooldown', 'missing_key', 'free_lane_not_confirmed', 'unexpected_model')
# 題目唯一來源；凍結靠 auto-memory-jev.md 的 Locked 欄，hook 不自驗。
QUESTION_FILE = Path(__file__).with_name('auto-memory-jev-question.json')
SECRET = re.compile(r'sk-[A-Za-z0-9_-]{16,}|vck_[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{30,}|gsk_[A-Za-z0-9]{20,}|Bearer\s+[A-Za-z0-9._-]{24,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|(?:api[_-]?key|secret|token|password|passwd)["\']?\s*[:=]\s*["\']?[A-Za-z0-9_./+=-]{20,}', re.I)
MANUAL = re.compile(r'收尾|結案|save[-_ ]?session|寫.*memory|該記.{0,5}嗎|歸檔|promote.*wiki|記下來|記一下|存.{0,3}memory', re.I)
PRIVATE = re.compile(r'不要(?:記|存)|別(?:記|存)|do not (?:remember|save)|don.t (?:remember|save)', re.I)
SYNTHETIC = re.compile(r'^\s*(?:<|/|\[SYSTEM NOTIFICATION|\[Request interrupted)', re.I)


def sha(text):
  return hashlib.sha256(text.encode()).hexdigest()


def dump(value):
  return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def automatic_dir():
  return Path.home() / '.claude/hooks/state/auto-memory-jev'


def disabled():
  marker = Path.home() / '.claude/hooks/state/auto-memory-jev.disabled'
  return os.environ.get('JEV_MEMORY_DISABLE') == '1' or marker.exists() or marker.is_symlink()


def audit(payload, status, **extra):
  row = {'ts': datetime.now(timezone.utc).isoformat(), 'event': payload.get('hook_event_name'),
         'session': sha(str(payload.get('session_id', '')))[:16], 'status': status, **extra}
  with SafeDirectory(Path.home() / '.claude/logs') as directory:
    directory.write('auto-memory-jev.jsonl', dump(row) + '\n', append=True)


def text_of(content):
  if isinstance(content, str):
    return content
  if isinstance(content, list):
    return '\n'.join(b.get('text', '') for b in content if isinstance(b, dict) and b.get('type') == 'text')
  return ''


def human(entry):
  if entry.get('type') != 'user' or entry.get('isMeta') or entry.get('isSidechain'):
    return False
  if (entry.get('origin') or {}).get('kind') not in (None, 'human', 'sdk'):
    return False
  if entry.get('turnOrigin') not in (None, 'human', 'sdk') or entry.get('promptSource') not in (None, 'typed', 'sdk'):
    return False
  content = (entry.get('message') or {}).get('content')
  if isinstance(content, list) and any(isinstance(b, dict) and b.get('type') == 'tool_result' for b in content):
    return False
  text = text_of(content).strip()
  return bool(text) and not SYNTHETIC.match(text)


def snapshot(path):
  fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
  try:
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode):
      raise ValueError('unsafe_transcript')
    with os.fdopen(fd, 'rb') as source:
      fd = None
      if info.st_size <= TAIL_FROM_BYTES:
        return scan(source)
      return tail_snapshot(source, info.st_size)
  finally:
    if fd is not None:
      os.close(fd)


def tail_snapshot(source, size):
  # 截圖驗收型 session 常到幾百 MB，整份解析會超過 deliver 的 3 秒上限；原本整份跳過，提醒就停擺。
  # 只解析檔尾：從 8MB 起倍增到含兩個人類回合為止。回合數與最後一次 compact 改用只解析
  # 少數候選行的全檔快掃補上，與整份解析同一套判斷（跨窗口的重複 uuid 不去重，僅影響回合數）。
  window = TAIL_START_BYTES
  while True:
    start = max(0, size - window)
    source.seek(start)
    if start:
      source.readline()
    context = scan(source)
    if start == 0:
      return context
    if len(context['records']) >= 2:
      break
    window *= 2
  source.seek(0)
  context['turns'], context['compact'] = count_turns(source)
  return context


def count_turns(source):
  turns = 0
  compact = ''
  seen = set()
  for line in source:
    # 回合是字串內容的 user 紀錄，不會含 tool_result 區塊；圖片多半在 tool_result 行，略過它們才快
    if b'compact_boundary' not in line and (b'"user"' not in line or b'"tool_result"' in line):
      continue
    try:
      entry = json.loads(line.decode('utf8', 'replace'))
    except ValueError:
      continue
    if not isinstance(entry, dict) or entry.get('isSidechain'):
      continue
    uid = entry.get('uuid')
    if uid and uid in seen:
      continue
    if uid:
      seen.add(uid)
    content = (entry.get('message') or {}).get('content')
    if entry.get('type') == 'user' and isinstance(content, str) and not entry.get('isMeta'):
      turns += 1
    if entry.get('type') == 'system' and entry.get('subtype') == 'compact_boundary':
      compact = str(uid or entry.get('timestamp', ''))
  return turns, compact


def scan(source):
  records = []
  turns = 0
  compact = ''
  owner = True
  seen = set()
  message_id = None
  for line in source:
    try:
      entry = json.loads(line.decode('utf8', 'replace'))
    except ValueError:
      continue
    if not isinstance(entry, dict):
      continue
    if entry.get('isSidechain'):
      continue
    uid = entry.get('uuid')
    if uid and uid in seen:
      continue
    if uid:
      seen.add(uid)
    content = (entry.get('message') or {}).get('content')
    # This counter deliberately matches checkpoint's legacy sentinel unit.
    if entry.get('type') == 'user' and isinstance(content, str) and not entry.get('isMeta'):
      turns += 1
    if entry.get('type') == 'system' and entry.get('subtype') == 'compact_boundary':
      compact = str(uid or entry.get('timestamp', ''))
    if human(entry):
      user = text_of(content)
      records.append({'turn': sha(str(uid or turns) + '\n' + user), 'user': user,
                      'assistant': '', 'saved': False, 'tools': set(), 'terminal': False})
      records = records[-2:]
      message_id = None
      owner = True
      continue
    if entry.get('type') == 'user' and (entry.get('origin') or {}).get('kind') not in (None, 'human', 'sdk'):
      owner = False
    if entry.get('type') == 'user' and (entry.get('turnOrigin') not in (None, 'human', 'sdk')
        or entry.get('promptSource') not in (None, 'typed', 'sdk')):
      owner = False
    if entry.get('type') == 'user' and not entry.get('isMeta') and SYNTHETIC.match(text_of(content)):
      owner = False
    if not records or entry.get('type') != 'assistant':
      continue
    row = records[-1]
    message = entry.get('message') or {}
    text = text_of(content)
    if text:
      mid = message.get('id', uid)
      row['assistant'] = (row['assistant'] + '\n' + text) if mid == message_id else text
      message_id = mid
      row['terminal'] = message.get('stop_reason') == 'end_turn'
    for block in content if isinstance(content, list) else []:
      if not isinstance(block, dict) or block.get('type') != 'tool_use':
        continue
      name = block.get('name', '')
      row['tools'].add(name)
      inp = block.get('input') or {}
      fp = str(inp.get('file_path', '')) if isinstance(inp, dict) else ''
      if name in ('Write', 'Edit', 'MultiEdit') and '/.claude/memory/' in fp:
        row['saved'] = True
  return {'records': records, 'turns': turns, 'compact': compact, 'owner': owner}


def clean(text, cap):
  text = re.sub(r'<pasted_content\b[^>]*>.*?</pasted_content>', '[pasted content omitted]', text, flags=re.S)
  text = re.sub(r'```.*?```', '[code omitted]', text, flags=re.S)
  text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b', '[email redacted]', text)
  text = text.replace(str(Path.home()), '~')
  return text if len(text) <= cap else text[:cap // 2] + '\n[content clipped]\n' + text[-cap // 2:]


def packet(context, final):
  rows = context['records']
  row = rows[-1]
  previous = rows[-2] if len(rows) > 1 else {'user': '', 'assistant': ''}
  if PRIVATE.search(previous['user']):
    previous = {'user': '', 'assistant': ''}
  raw = '\n'.join((row['user'], final, previous['user'], previous['assistant']))
  if SECRET.search(raw):
    raise ValueError('sensitive_packet')
  if PRIVATE.search(row['user']):
    raise ValueError('do_not_save')
  if row['saved'] or MANUAL.search(row['user']):
    raise ValueError('already_handled')
  state = {'previous_user': clean(previous['user'], 1000), 'previous_assistant': clean(previous['assistant'], 1800),
           'user': clean(row['user'], 1600), 'assistant': clean(final, 4000),
           'observed_tool_names': sorted(row['tools']), 'memory_write_observed_this_turn': False,
           'explicit_memory_request': False}
  serialized = dump(state)
  if SECRET.search(serialized):
    raise ValueError('sensitive_packet')
  return state


def reply_text(text):
  # Normalised reply text, compared verbatim; a digest here would be a content hash of our own
  # pending state (ADR 0003). A legacy pending record carrying reply_sha simply reads as stale.
  return re.sub(r'\s+', ' ', clean(text, 4000)).strip()


def endpoint():
  test_url = os.environ.get('JEV_MEMORY_TEST_URL', '') if os.environ.get('JEV_MEMORY_TEST_MODE') == '1' else ''
  if test_url:
    if not re.fullmatch(r'http://127\.0\.0\.1:\d+', test_url):
      raise ValueError('invalid_test_endpoint')
    return test_url, 'test-only-not-a-secret'
  key = subprocess.run(['security', 'find-generic-password', '-s', 'experiential-api-key', '-w'],
                       capture_output=True, text=True, timeout=1, check=True).stdout.strip()
  if not key:
    raise ValueError('missing_key')
  return BASE, key


class NoRedirect(urllib.request.HTTPRedirectHandler):
  def redirect_request(self, *_args, **_kwargs):
    return None


def http(base, path, key, body=None, timeout=TIMEOUT):
  data = dump(body).encode() if body is not None else None
  request = urllib.request.Request(base + path, data=data, headers={
    'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json', 'User-Agent': 'auto-memory-jev'})
  opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
  try:
    with opener.open(request, timeout=timeout) as response:
      raw = response.read(2 * 1024 * 1024 + 1)
  except urllib.error.HTTPError as error:
    error.close()
    raise
  if len(raw) > 2 * 1024 * 1024:
    raise ValueError('oversized_response')
  return json.loads(raw)


def is_zero(value):
  try:
    return not isinstance(value, bool) and value is not None and math.isfinite(float(value)) and float(value) == 0
  except (ValueError, TypeError):
    return False


def free_guard(directory, base, key):
  cache = json.loads(directory.read('free-price.json') or '{}')
  if cache.get('model') == MODEL and 0 <= time.time() - cache.get('checked_at', 0) < 3600:
    return
  data = http(base, '/api/v1/models', key, timeout=5)
  matches = [r for r in data.get('data', []) if r.get('id') == MODEL]
  if len(matches) != 1 or not all(is_zero(matches[0].get('pricing', {}).get(k)) for k in ('prompt', 'completion')):
    raise ValueError('free_lane_not_confirmed')
  directory.write('free-price.json', dump({'model': MODEL, 'checked_at': time.time()}))


def reserve(directory, size):
  with directory.lock('budget.lock'):
    state = json.loads(directory.read('budget.json') or '{}')
    now = datetime.now(timezone.utc)
    day, hour = now.strftime('%Y-%m-%d'), now.strftime('%Y-%m-%dT%H')
    if state.get('day') != day:
      state.update(day=day, daily_calls=0, daily_bytes=0)
    if state.get('hour') != hour:
      state.update(hour=hour, hourly_calls=0, hourly_bytes=0)
    if state['daily_calls'] >= 1000 or state['daily_bytes'] + size > 4000000:
      raise ValueError('daily_budget')
    if state['hourly_calls'] >= 250 or state['hourly_bytes'] + size > 1000000:
      raise ValueError('hourly_budget')
    for name in ('daily_calls', 'hourly_calls'):
      state[name] += 1
    for name in ('daily_bytes', 'hourly_bytes'):
      state[name] += size
    directory.write('budget.json', dump(state))


def pplx_cooling(directory):
  return json.loads(directory.read('budget.json') or '{}').get('pplx_cooldown_until', 0) > time.time()


def pplx_endpoint():
  if os.environ.get('JEV_MEMORY_TEST_MODE') == '1':
    test_url = os.environ.get('JEV_MEMORY_PPLX_TEST_URL', '')
    if not test_url:
      raise ValueError('missing_pplx_key')
    if not re.fullmatch(r'http://127\.0\.0\.1:\d+', test_url):
      raise ValueError('invalid_test_endpoint')
    return test_url, 'test-only-pplx'
  keys_file = Path.home() / '.cli-proxy-api/keys.env'
  if not keys_file.is_file():
    raise ValueError('missing_pplx_key')
  parsed = {}
  for line in keys_file.read_text(encoding='utf-8', errors='replace').splitlines():
    if '=' in line and not line.lstrip().startswith('#'):
      k, v = line.split('=', 1)
      parsed[k.strip()] = v.strip().strip('"').strip("'")
  key = parsed.get('CLIPROXY_KEY_CC') or parsed.get('CLIPROXY_KEY_ADMIN') or ''
  if not key:
    raise ValueError('missing_pplx_key')
  return PPLX_BASE, key


def ask_pplx(directory, candidate, questions):
  if pplx_cooling(directory):
    raise ValueError('pplx_quota_cooldown')
  base, key = pplx_endpoint()
  try:
    data = http(base, '/v1/systemone', key, {'model': PPLX_MODEL, 'state': candidate, 'questions': questions}, timeout=PPLX_TIMEOUT)
  except urllib.error.HTTPError as error:
    error.close()
    if error.code in (400, 404, 429):
      cooldown(directory, field='pplx_cooldown_until')
    raise
  usage = data.get('usage') or {}
  cost = usage.get('cost')
  if not is_zero(cost):
    try:
      paid = not isinstance(cost, bool) and math.isfinite(float(cost)) and float(cost) > 0
    except (ValueError, TypeError):
      paid = False
    cooldown(directory, paid=paid, field='pplx_cooldown_until')
    raise ValueError('nonzero_cost' if paid else 'missing_zero_cost_evidence')
  returned = str(data.get('model') or '')
  if returned != PPLX_MODEL and not returned.startswith('perplexity/pplx-decider-v1.3'):
    raise ValueError('unexpected_model')
  return data, PPLX_MODEL


def vercel_cooling(directory):
  try:
    state = json.loads(directory.read('budget.json') or '{}')
  except (json.JSONDecodeError, UnicodeDecodeError):
    return False
  until = state.get('vercel_cooldown_until', 0) if isinstance(state, dict) else 0
  return isinstance(until, (int, float)) and not isinstance(until, bool) and until > time.time()


def vercel_credits_endpoint():
  if os.environ.get('JEV_MEMORY_TEST_MODE') == '1':
    test_url = os.environ.get('JEV_MEMORY_VERCEL_CREDITS_TEST_URL', '')
    if not test_url:
      raise ValueError('missing_vercel_key')
    if not re.fullmatch(r'http://127\.0\.0\.1:\d+', test_url):
      raise ValueError('invalid_test_endpoint')
    return test_url, 'test-only-vercel-credits'
  key = subprocess.run(['security', 'find-generic-password', '-s', 'jev-api-key', '-w'],
                       capture_output=True, text=True, timeout=1, check=True).stdout.strip()
  if not key:
    raise ValueError('missing_vercel_key')
  return VERCEL_CREDITS_BASE, key


def vercel_free_guard(directory, base, key):
  try:
    cache = json.loads(directory.read('vercel-free-credits.json') or '{}')
  except (json.JSONDecodeError, UnicodeDecodeError):
    cache = {}
  if not isinstance(cache, dict):
    cache = {}
  checked_at = cache.get('checked_at', 0)
  if (cache.get('model') == VERCEL_MODEL and isinstance(checked_at, (int, float))
      and not isinstance(checked_at, bool) and 0 <= time.time() - checked_at < 3600):
    if cache.get('free_ok') is False:
      raise ValueError('vercel_free_not_confirmed')
    if cache.get('free_ok') is True:
      return
  try:
    data = http(base, '/v1/credits', key, timeout=VERCEL_CREDITS_TIMEOUT)
  except (json.JSONDecodeError, UnicodeDecodeError) as error:
    raise ValueError('vercel_bad_response') from error
  except ValueError as error:
    if str(error) == 'oversized_response':
      raise ValueError('vercel_bad_response') from error
    raise
  if not isinstance(data, dict):
    raise ValueError('vercel_bad_response')
  raw_bal = data.get('balance')
  try:
    bal = float(raw_bal) if not isinstance(raw_bal, bool) and raw_bal is not None else float('nan')
  except (ValueError, TypeError):
    bal = float('nan')
  # 僅在明確帶 token_pass: null 且餘額位於 (0, 5.0] 區間時確認為月贈免費點數池；正負結果皆快取一小時防重複外呼
  free_ok = ('token_pass' in data and data['token_pass'] is None
             and math.isfinite(bal) and (0.0 < bal <= VERCEL_MAX_FREE_USD))
  directory.write('vercel-free-credits.json', dump({'model': VERCEL_MODEL, 'checked_at': time.time(), 'free_ok': free_ok}))
  if not free_ok:
    raise ValueError('vercel_free_not_confirmed')


def ask_vercel(directory, candidate, questions):
  if vercel_cooling(directory):
    raise ValueError('vercel_quota_cooldown')
  base, key = pplx_endpoint()
  vc_base, vc_key = vercel_credits_endpoint()
  vercel_free_guard(directory, vc_base, vc_key)
  try:
    data = http(base, '/v1/systemone', key, {'model': VERCEL_MODEL, 'state': candidate, 'questions': questions}, timeout=VERCEL_TIMEOUT)
  except urllib.error.HTTPError as error:
    error.close()
    if error.code == 402:
      try:
        directory.write('vercel-free-credits.json', dump({'model': VERCEL_MODEL, 'checked_at': time.time(), 'free_ok': False}))
      except OSError:
        pass
    if error.code in (402, 403, 404, 429):
      cooldown(directory, field='vercel_cooldown_until')
    raise
  except (json.JSONDecodeError, UnicodeDecodeError) as error:
    raise ValueError('vercel_bad_response') from error
  except ValueError as error:
    if str(error) == 'oversized_response':
      raise ValueError('vercel_bad_response') from error
    raise
  if not isinstance(data, dict):
    raise ValueError('vercel_bad_response')
  answers = data.get('answers')
  nudge = answers.get('direct_nudge') if isinstance(answers, dict) else None
  if not isinstance(nudge, dict) or 'noul' not in nudge:
    raise ValueError('vercel_bad_response')
  returned = str(data.get('model') or '')
  if returned != VERCEL_MODEL and not returned.startswith('perplexity/pplx-decider-v1.3'):
    raise ValueError('unexpected_model')
  return data, VERCEL_MODEL


def amd_cooling(directory):
  try:
    state = json.loads(directory.read('budget.json') or '{}')
  except (json.JSONDecodeError, UnicodeDecodeError):
    return False
  until = state.get('amd_cooldown_until', 0) if isinstance(state, dict) else 0
  return isinstance(until, (int, float)) and not isinstance(until, bool) and until > time.time()


def amd_endpoint():
  if os.environ.get('JEV_MEMORY_TEST_MODE') == '1':
    test_url = os.environ.get('JEV_MEMORY_AMD_TEST_URL', '')
    if not test_url:
      raise ValueError('missing_amd_key')
    if not re.fullmatch(r'http://127\.0\.0\.1:\d+', test_url):
      raise ValueError('invalid_test_endpoint')
    return test_url, 'test-only-amd'
  return pplx_endpoint()


def ask_amd(directory, candidate, questions, hook_started=None):
  if amd_cooling(directory):
    raise ValueError('amd_quota_cooldown')
  leg_timeout = AMD_TIMEOUT
  if hook_started is not None:
    avail = STOP_HOOK_BUDGET_S - (time.monotonic() - hook_started) - TAIL_LEGS_RESERVE_S
    if avail < AMD_MIN_BUDGET_S:
      raise ValueError('amd_budget_tight')
    leg_timeout = min(AMD_TIMEOUT, avail)
  base, key = amd_endpoint()
  try:
    data = http(base, '/v1/systemone', key, {'model': AMD_MODEL, 'state': candidate, 'questions': questions}, timeout=leg_timeout)
  except urllib.error.HTTPError as error:
    error.close()
    if error.code in (400, 402, 403, 404, 429):
      cooldown(directory, field='amd_cooldown_until')
    raise
  except (json.JSONDecodeError, UnicodeDecodeError) as error:
    raise ValueError('amd_bad_response') from error
  except ValueError as error:
    if str(error) == 'oversized_response':
      raise ValueError('amd_bad_response') from error
    raise
  if not isinstance(data, dict):
    raise ValueError('amd_bad_response')
  answers = data.get('answers')
  nudge = answers.get('direct_nudge') if isinstance(answers, dict) else None
  score = nudge.get('noul') if isinstance(nudge, dict) else None
  if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1:
    raise ValueError('amd_bad_response')
  returned = str(data.get('model') or '')
  if returned not in (AMD_MODEL, 'd3', 'vllm-sr/d3'):
    raise ValueError('unexpected_model')
  return data, AMD_MODEL


def jev_cooling(directory):
  # 冷卻各自鎖該腿；預算（reserve）五腿共用，所以不放在這裡
  return json.loads(directory.read('budget.json') or '{}').get('cooldown_until', 0) > time.time()


def ask_jev(directory, candidate, questions):
  if jev_cooling(directory):
    raise ValueError('quota_cooldown')
  body = {'model': MODEL, 'state': candidate, 'questions': questions}
  base, key = endpoint()
  free_guard(directory, base, key)
  try:
    data = http(base, '/v1/systemone', key, body)
  except urllib.error.HTTPError as error:
    error.close()
    if error.code == 429:
      cooldown(directory)
    raise
  usage = data.get('usage') or {}
  cost = usage.get('cost')
  if not is_zero(cost):
    try:
      paid = not isinstance(cost, bool) and math.isfinite(float(cost)) and float(cost) > 0
    except (ValueError, TypeError):
      paid = False
    cooldown(directory, paid=paid)
    raise ValueError('nonzero_cost' if paid else 'missing_zero_cost_evidence')
  if data.get('model') not in ('jev-latest', MODEL, 'type-safe/jev-latest'):
    raise ValueError('unexpected_model')
  return data, MODEL


def drex_endpoint():
  test_url = os.environ.get('JEV_MEMORY_DREX_TEST_URL', '') if os.environ.get('JEV_MEMORY_TEST_MODE') == '1' else ''
  if test_url:
    if not re.fullmatch(r'http://127\.0\.0\.1:\d+', test_url):
      raise ValueError('invalid_test_endpoint')
    return test_url, 'test-only-not-a-secret'
  key = subprocess.run(['security', 'find-generic-password', '-s', 'nace-api-key', '-w'],
                       capture_output=True, text=True, timeout=1, check=True).stdout.strip()
  if not key:
    raise ValueError('missing_drex_key')
  return DREX_BASE, key


def ask_drex(candidate, questions):
  base, key = drex_endpoint()
  data = http(base, '/v1/systemone', key, {'model': DREX_MODEL, 'state': candidate, 'questions': questions})
  if data.get('model') != DREX_MODEL:
    raise ValueError('unexpected_model')
  return data, DREX_MODEL


def cooldown(directory, paid=False, field='cooldown_until'):
  with directory.lock('budget.lock'):
    budget = json.loads(directory.read('budget.json') or '{}')
    budget[field] = time.time() + 3600
    directory.write('budget.json', dump(budget))
  if paid:
    with SafeDirectory(Path.home() / '.claude/hooks/state') as root:
      root.write('auto-memory-jev.disabled', 'Unexpected nonzero usage.cost; inspect billing before enabling.\n')


def ask_judge_chain(directory, candidate, questions, hook_started=None):
  try:
    return ask_pplx(directory, candidate, questions)
  except ValueError as error:
    if str(error) not in PPLX_FALLS_TO_NEXT:
      raise
  except OSError:
    pass
  try:
    return ask_vercel(directory, candidate, questions)
  except ValueError as error:
    if str(error) not in VERCEL_FALLS_TO_JEV:
      raise
  except (OSError, subprocess.SubprocessError):
    pass
  try:
    return ask_amd(directory, candidate, questions, hook_started=hook_started)
  except ValueError as error:
    if str(error) not in AMD_FALLS_TO_JEV:
      raise
  except OSError:
    pass
  try:
    return ask_jev(directory, candidate, questions)
  except ValueError as error:
    if str(error) not in JEV_FALLS_TO_DREX:
      raise
    return ask_drex(candidate, questions)
  except (OSError, subprocess.SubprocessError):
    # HTTPError／URLError／socket timeout 都是 OSError；Keychain 讀不到或逾時是 SubprocessError
    return ask_drex(candidate, questions)


def run_stop(payload, directory, state, name, hook_started=None):
  if hook_started is None:
    hook_started = time.monotonic()
  if payload.get('stop_hook_active'):
    return
  context = snapshot(payload['transcript_path'])
  if not context['records'] or not context['owner']:
    audit(payload, 'nonhuman_turn')
    return
  current = context['records'][-1]
  if state.get('last_checked') == current['turn']:
    audit(payload, 'turn_dedup', turn=current['turn'][:16])
    return
  state.update(last_checked=current['turn'])
  state.pop('pending', None)
  directory.write(name, dump(state))
  final = payload.get('last_assistant_message')
  if not isinstance(final, str) or not final.strip():
    raise ValueError('missing_final_payload')
  candidate = packet(context, final)
  fingerprint = sha(candidate['user'] + '\n' + candidate['assistant'])
  if fingerprint in state.get('delivered', []):
    raise ValueError('packet_repeat')
  questions = json.loads(QUESTION_FILE.read_text())
  reserve(directory, len(dump({'model': PPLX_MODEL, 'state': candidate, 'questions': questions}).encode()))
  started = time.monotonic()
  data, judge = ask_judge_chain(directory, candidate, questions, hook_started=hook_started)
  raw_usage = data.get('usage')
  usage = raw_usage if isinstance(raw_usage, dict) else {}
  score = data['answers']['direct_nudge']['noul']
  if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1:
    raise ValueError('invalid_probability')
  fresh = snapshot(payload['transcript_path'])
  if not fresh['records'] or fresh['records'][-1]['turn'] != current['turn'] or fresh['compact'] != context['compact']:
    raise ValueError('stale_turn')
  if fresh['records'][-1]['saved']:
    raise ValueError('already_handled')
  if fresh['records'][-1]['terminal'] and reply_text(fresh['records'][-1]['assistant']) != reply_text(final):
    raise ValueError('stale_reply')
  if score >= THRESHOLD:
    state['pending'] = {'turn': current['turn'], 'packet_sha': fingerprint, 'reply_text': reply_text(final), 'score': score,
                        'created_at': time.time(), 'compact': context['compact']}
    directory.write(name, dump(state))
  safe_usage = {k: v for k, v in usage.items() if k in ('input_tokens', 'output_tokens', 'cost')
                and isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)}
  if judge == VERCEL_MODEL:
    pm = data.get('provider_metadata')
    gw = pm.get('gateway') if isinstance(pm, dict) else None
    gw_cost = gw.get('cost') if isinstance(gw, dict) else None
    try:
      if not isinstance(gw_cost, bool) and gw_cost is not None and math.isfinite(float(gw_cost)):
        safe_usage['vercel_credit_cost'] = round(float(gw_cost), 8)
    except (ValueError, TypeError):
      pass
  if judge == AMD_MODEL and isinstance(safe_usage.get('input_tokens'), int):
    safe_usage['amd_points_est'] = round(safe_usage['input_tokens'] * AMD_POINTS_PER_INPUT_TOKEN, 8)
  if judge == DREX_MODEL and isinstance(safe_usage.get('input_tokens'), int):
    safe_usage['cost_usd_est'] = round(safe_usage['input_tokens'] * DREX_USD_PER_INPUT_TOKEN, 8)
  audit(payload, 'pending' if score >= THRESHOLD else 'quiet', turn=current['turn'][:16],
        score=score, model=judge, usage=safe_usage, ms=round((time.monotonic()-started)*1000, 1))


def run_deliver(payload, directory, state, name):
  prompt = payload.get('prompt')
  if payload.get('isMeta') or not isinstance(prompt, str) or not prompt.strip() or SYNTHETIC.match(prompt):
    return
  if (payload.get('origin') or {}).get('kind') not in (None, 'human', 'sdk'):
    return
  if payload.get('turnOrigin') not in (None, 'human', 'sdk') or payload.get('promptSource') not in (None, 'typed', 'sdk'):
    return
  pending = state.get('pending')
  if not pending:
    return
  context = snapshot(payload['transcript_path'])
  source = next((r for r in context['records'] if r['turn'] == pending['turn']), None)
  state.pop('pending', None)
  directory.write(name, dump(state))
  if MANUAL.search(prompt) or PRIVATE.search(prompt) or SECRET.search(prompt):
    audit(payload, 'delivery_skip_current_request')
    return
  if (not source or source['saved'] or pending['compact'] != context['compact'] or time.time()-pending['created_at'] > 86400
      or source['terminal'] and reply_text(source['assistant']) != pending.get('reply_text')):
    audit(payload, 'delivery_stale')
    return
  previous = last_long(payload['session_id'], context['turns'], payload['transcript_path'])
  version = 'short'
  message = reminder(version, '[auto-memory:jev:' + version + '] 上一人類回合可能有新且已確認、可跨回合使用的偏好／決策／技術教訓，值得回查既有 memory。', previous, automatic=True)
  if len(message) > 9500:
    raise ValueError('oversized_reminder')
  state['delivered'] = (state.get('delivered', []) + [pending['packet_sha']])[-20:]
  directory.write(name, dump(state))
  message += '\n\n來源回合 hash：' + pending['turn'][:16]
  print(dump({'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': message}}), flush=True)
  audit(payload, 'delivered', turn=pending['turn'][:16], version=version, score=pending['score'])


def main(payload, mode, hook_started=None):
  if hook_started is None:
    hook_started = time.monotonic()
  if disabled() or payload.get('agent_id') or payload.get('agent_type'):
    return
  session = payload.get('session_id', '')
  if not isinstance(session, str) or not SESSION_RE.fullmatch(session):
    return
  if 'subagents' in Path(payload.get('transcript_path', '')).parts:
    return
  # Detect unsafe audit targets before any model call, not only after classification.
  audit(payload, 'entered')
  with SafeDirectory(automatic_dir()) as directory:
    name = 'session-' + sha(session)[:24] + '.json'
    with directory.lock(name + '.lock'):
      state = json.loads(directory.read(name) or '{}')
      if mode == 'stop':
        run_stop(payload, directory, state, name, hook_started=hook_started)
      elif mode == 'deliver':
        run_deliver(payload, directory, state, name)


if __name__ == '__main__':
  payload = {}
  started = time.monotonic()
  try:
    raw = sys.stdin.read(1048577)
    if len(raw) <= 1048576:
      payload = json.loads(raw)
      main(payload, sys.argv[1] if len(sys.argv) > 1 else 'stop', hook_started=started)
  except Exception as error:
    try:
      status = str(error) if isinstance(error, ValueError) and re.fullmatch('[a-z_]{1,50}', str(error)) else type(error).__name__
      audit(payload, 'unavailable', error=status, ms=round((time.monotonic()-started)*1000, 1))
    except Exception:
      pass
  sys.exit(0)
