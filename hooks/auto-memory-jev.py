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

MODEL = 'type-safe/jev-latest:free'
BASE = 'https://api.experientiallabs.ai'
TIMEOUT = 1.5
THRESHOLD = 0.5
# 題目唯一來源；凍結靠 auto-memory-jev.md 的 Locked 欄，hook 不自驗。
QUESTION_FILE = Path(__file__).with_name('auto-memory-jev-question.json')
COMPANY = re.compile(r'acme|oldco|oldco-shop|Desktop[/\\-]work|work-user|example-work-account|公司付', re.I)
SECRET = re.compile(r'sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{30,}|gsk_[A-Za-z0-9]{20,}|Bearer\s+[A-Za-z0-9._-]{24,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|(?:api[_-]?key|secret|token|password|passwd)\s*[:=]\s*[\"\']?[A-Za-z0-9_./+=-]{20,}', re.I)
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
    if not stat.S_ISREG(info.st_mode) or info.st_size > 64 * 1024 * 1024:
      raise ValueError('unsafe_transcript')
    with os.fdopen(fd, encoding='utf8', errors='replace') as source:
      fd = None
      records = []
      turns = 0
      compact = ''
      owner = True
      seen = set()
      message_id = None
      for line in source:
        try:
          entry = json.loads(line)
        except ValueError:
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
  finally:
    if fd is not None:
      os.close(fd)


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
  raw = '\n'.join((row['user'], final, previous['user'], previous['assistant']))
  if COMPANY.search(raw) or SECRET.search(raw):
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
  if COMPANY.search(serialized) or SECRET.search(serialized):
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
    'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
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
    if state.get('cooldown_until', 0) > time.time():
      raise ValueError('quota_cooldown')
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


def cooldown(directory, paid=False):
  with directory.lock('budget.lock'):
    budget = json.loads(directory.read('budget.json') or '{}')
    budget['cooldown_until'] = time.time() + 3600
    directory.write('budget.json', dump(budget))
  if paid:
    with SafeDirectory(Path.home() / '.claude/hooks/state') as root:
      root.write('auto-memory-jev.disabled', 'Unexpected nonzero usage.cost; inspect billing before enabling.\n')


def run_stop(payload, directory, state, name):
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
  body = {'model': MODEL, 'state': candidate, 'questions': questions}
  base, key = endpoint()
  free_guard(directory, base, key)
  reserve(directory, len(dump(body).encode()))
  started = time.monotonic()
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
  audit(payload, 'pending' if score >= THRESHOLD else 'quiet', turn=current['turn'][:16],
        score=score, model=MODEL, usage=safe_usage, ms=round((time.monotonic()-started)*1000, 1))


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
  if MANUAL.search(prompt) or PRIVATE.search(prompt) or COMPANY.search(prompt) or SECRET.search(prompt):
    audit(payload, 'delivery_skip_current_request')
    return
  if (not source or source['saved'] or pending['compact'] != context['compact'] or time.time()-pending['created_at'] > 86400
      or source['terminal'] and reply_text(source['assistant']) != pending.get('reply_text')):
    audit(payload, 'delivery_stale')
    return
  previous = last_long(payload['session_id'], context['turns'], payload['transcript_path'])
  version = 'short' if previous and context['turns'] <= previous + 50 else 'long'
  message = reminder(version, '[auto-memory:jev:' + version + '] 上一人類回合可能有新且已確認、可跨回合使用的偏好／決策／技術教訓，值得回查既有 memory。', previous, automatic=True)
  if len(message) > 9500:
    raise ValueError('oversized_reminder')
  # Preflight the shared marker before printing; a pathological target must not count as injected.
  if version == 'long':
    with SafeDirectory(Path.home() / '.claude/hooks/state') as shared:
      shared.read_info('long_injected_' + payload['session_id'])
  state['delivered'] = (state.get('delivered', []) + [pending['packet_sha']])[-20:]
  directory.write(name, dump(state))
  message += '\n\n來源回合 hash：' + pending['turn'][:16]
  print(dump({'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': message}}), flush=True)
  if version == 'long' and not mark_long(payload['session_id'], max(1, context['turns'])):
    version = 'reference'
  audit(payload, 'delivered', turn=pending['turn'][:16], version=version, score=pending['score'])


def main(payload, mode):
  if disabled() or payload.get('agent_id') or payload.get('agent_type'):
    return
  session = payload.get('session_id', '')
  if not isinstance(session, str) or not SESSION_RE.fullmatch(session):
    return
  cwd = Path(payload.get('cwd') or '/').resolve()
  roots = (Path.home().resolve() / 'Desktop/projects', Path.home().resolve() / '.claude')
  if not any(cwd == r or r in cwd.parents for r in roots) or 'subagents' in Path(payload.get('transcript_path', '')).parts:
    return
  # Detect unsafe audit targets before any model call, not only after classification.
  audit(payload, 'entered')
  with SafeDirectory(automatic_dir()) as directory:
    name = 'session-' + sha(session)[:24] + '.json'
    with directory.lock(name + '.lock'):
      state = json.loads(directory.read(name) or '{}')
      if mode == 'stop':
        run_stop(payload, directory, state, name)
      elif mode == 'deliver':
        run_deliver(payload, directory, state, name)


if __name__ == '__main__':
  payload = {}
  started = time.monotonic()
  try:
    raw = sys.stdin.read(1048577)
    if len(raw) <= 1048576:
      payload = json.loads(raw)
      main(payload, sys.argv[1] if len(sys.argv) > 1 else 'stop')
  except Exception as error:
    try:
      status = str(error) if isinstance(error, ValueError) and re.fullmatch('[a-z_]{1,50}', str(error)) else type(error).__name__
      audit(payload, 'unavailable', error=status, ms=round((time.monotonic()-started)*1000, 1))
    except Exception:
      pass
  sys.exit(0)
