#!/usr/bin/env python3
import copy
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import time


ENABLE_VERSION = 1
DEFAULT_ROOT = Path.home() / '.claude/cache/taskoutput-dedup'
DEFAULT_ENABLE = Path.home() / '.claude/cache/taskoutput-dedup.enable.json'
ROOT_ENV = 'TASKOUTPUT_DEDUP_ROOT'
ENABLE_ENV = 'TASKOUTPUT_DEDUP_ENABLE'
SESSION_SOURCES = {'startup', 'resume', 'clear', 'compact'}
GENERATION_FILE = 'generation.json'
LOCK_NAME = '.lock'
SENTINEL_NAME = 'invalidate'
STATE_NAME = 'state.json'
CANDIDATE_NAME = 'candidate.txt'


def enabled(enable):
  try:
    info = os.stat(enable, follow_symlinks=False)
  except OSError:
    return False
  if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
    return False
  if stat.S_IMODE(info.st_mode) & 0o077:
    return False
  try:
    with open(enable, 'rb') as handle:
      body = json.loads(handle.read())
  except (OSError, ValueError):
    return False
  if not isinstance(body, dict) or set(body) != {'version', 'started_at', 'expires_at'}:
    return False
  if body['version'] != ENABLE_VERSION:
    return False
  if not isinstance(body['started_at'], (int, float)) or not isinstance(body['expires_at'], (int, float)):
    return False
  return time.time() < float(body['expires_at'])


def regular(fd):
  info = os.fstat(fd)
  if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
    raise OSError('unsafe file')
  if stat.S_IMODE(info.st_mode) & 0o077:
    raise OSError('non-private file')


def read_file(directory, name):
  fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
  try:
    regular(fd)
    if stat.S_ISFIFO(os.fstat(fd).st_mode):
      raise OSError('unsafe file')
    with os.fdopen(fd, 'rb', closefd=False) as handle:
      return handle.read()
  finally:
    os.close(fd)


def write_new(directory, name, data, mode):
  fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_NONBLOCK, mode, dir_fd=directory)
  try:
    regular(fd)
    remaining = memoryview(data)
    while remaining:
      written = os.write(fd, remaining)
      if written <= 0:
        raise OSError('incomplete write')
      remaining = remaining[written:]
    os.fsync(fd)
  finally:
    os.close(fd)


def save_replace(directory, name, data, mode):
  pending = name.split('.', 1)[0] + '.pending'
  write_new(directory, pending, data, mode)
  os.replace(pending, name, src_dir_fd=directory, dst_dir_fd=directory)
  os.fsync(directory)


def name_of(session, task):
  return hashlib.sha256(f'{session}\n{task}'.encode()).hexdigest()[:32]


def hash_of(value):
  return hashlib.sha256(str(value or '').encode()).hexdigest()[:32]


def shape_of(payload):
  if not isinstance(payload, dict):
    return 'non_object'
  if payload.get('hook_event_name') != 'PostToolUse':
    return 'unknown_event'
  if payload.get('tool_name') != 'TaskOutput':
    return 'unknown_tool'
  response = payload.get('tool_response')
  if not isinstance(response, dict):
    return 'non_dict_response'
  task = response.get('task')
  if not isinstance(task, dict):
    return 'non_dict_task'
  session_id = payload.get('session_id')
  task_id = task.get('task_id')
  if not isinstance(session_id, str) or not session_id:
    return 'unknown_session'
  if not isinstance(task_id, str) or not task_id:
    return 'bad_task_id'
  tool_input = payload.get('tool_input')
  if not isinstance(tool_input, dict):
    return 'non_dict_tool_input'
  if tool_input.get('task_id') != task_id:
    return 'task_id_mismatch'
  output = task.get('output')
  if not isinstance(output, str) or not output:
    return 'empty_output'
  if 'result' not in task:
    return 'missing_result'
  if output != task.get('result'):
    return 'unequal_result'
  # timeout 仍是同一份 running 正文，只是這次查詢逾時；success／completed 不是這個情況。
  if response.get('retrieval_status') not in ('not_ready', 'timeout'):
    return 'bad_retrieval'
  if task.get('task_type') != 'local_agent':
    return 'bad_task_type'
  if task.get('status') != 'running':
    return 'bad_status'
  return 'accepted'


def open_root(path):
  os.makedirs(path, mode=0o700, exist_ok=True)
  directory = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
  info = os.fstat(directory)
  if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
    os.close(directory)
    raise OSError('unsafe root')
  return directory


def open_workdir(root_fd, session, task):
  name = name_of(session, task)
  try:
    os.mkdir(name, 0o700, dir_fd=root_fd)
  except FileExistsError:
    pass
  return safe_open_workdir(root_fd, name)


def list_workdirs(root_fd):
  names = []
  try:
    entries = os.listdir(root_fd)
  except OSError:
    return names
  for name in entries:
    if name.startswith('audit-') or name.startswith('.'):
      continue
    try:
      info = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
    except OSError:
      continue
    if stat.S_ISDIR(info.st_mode):
      names.append(name)
  return names


class LockBusy(Exception):
  pass


def acquire_lock(directory):
  fd = os.open(LOCK_NAME, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=directory)
  try:
    regular(fd)
    try:
      fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
      raise LockBusy
    except OSError as error:
      if error.errno in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK):
        raise LockBusy
      raise
  except LockBusy:
    os.close(fd)
    raise
  except OSError:
    os.close(fd)
    raise
  return fd


def exists(directory, name):
  try:
    os.stat(name, dir_fd=directory, follow_symlinks=False)
  except FileNotFoundError:
    return False
  return True


def read_generation_file(directory):
  try:
    raw = read_file(directory, GENERATION_FILE)
  except FileNotFoundError:
    return 0
  except OSError:
    return None
  try:
    body = json.loads(raw)
  except (ValueError, json.JSONDecodeError):
    return None
  if isinstance(body, dict) and set(body) == {'generation'} and isinstance(body['generation'], int) and body['generation'] >= 0:
    return body['generation']
  return None


def read_generation(directory):
  if exists(directory, SENTINEL_NAME):
    return -1
  return read_generation_file(directory)


def bump_generation(directory, base):
  if not isinstance(base, int) or base < 0:
    raise OSError('unreadable generation')
  save_replace(directory, GENERATION_FILE, json.dumps({'generation': base + 1}, sort_keys=True).encode(), 0o600)


def write_sentinel(directory):
  try:
    write_new(directory, SENTINEL_NAME, b'1', 0o600)
  except FileExistsError:
    pass
  os.fsync(directory)


def clear_sentinel(directory):
  try:
    os.unlink(SENTINEL_NAME, dir_fd=directory)
  except FileNotFoundError:
    pass
  os.fsync(directory)


def append_row(root_fd, session, row):
  name = f'audit-{hashlib.sha256(session.encode()).hexdigest()[:32]}.jsonl'
  data = (json.dumps(row, ensure_ascii=False) + '\n').encode()
  fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=root_fd)
  try:
    regular(fd)
    remaining = memoryview(data)
    while remaining:
      written = os.write(fd, remaining)
      if written <= 0:
        raise OSError('incomplete append')
      remaining = remaining[written:]
    os.fsync(fd)
  finally:
    os.close(fd)


def base_row(payload, action, reason, elapsed_ms, shape, event='PostToolUse', body_bytes=0, marker_bytes=0, rewrite_requested=False):
  response = payload.get('tool_response') if isinstance(payload, dict) else None
  task = response.get('task') if isinstance(response, dict) else None
  task_id = task.get('task_id') if isinstance(task, dict) else None
  session_id = payload.get('session_id') if isinstance(payload, dict) else None
  return {
    'timestamp': time.time(),
    'session_hash': hash_of(session_id) if isinstance(session_id, str) and session_id else None,
    'task_hash': hash_of(task_id) if isinstance(task_id, str) and task_id else None,
    'tool_use_id': payload.get('tool_use_id'),
    'transcript_path': payload.get('transcript_path'),
    'event': event,
    'source': payload.get('source') if event == 'SessionStart' else None,
    'shape': shape,
    'action': action,
    'reason': reason,
    'body_bytes': body_bytes,
    'marker_bytes': marker_bytes,
    'elapsed_ms': elapsed_ms,
    'rewrite_requested': rewrite_requested,
  }


def pending_present(workdir):
  for pending in ('state.pending', 'candidate.pending', 'generation.pending', 'invalidate.pending'):
    if exists(workdir, pending):
      return True
  return False


def empty_workdir(workdir):
  try:
    entries = os.listdir(workdir)
  except OSError:
    return False
  return not [name for name in entries if name != LOCK_NAME]


def fold(workdir, root_path, payload, session, task, generation, elapsed_ms):
  data = payload['tool_response']['task']['output'].encode()
  current = {'session': session, 'task': task, 'generation': generation, 'bytes': len(data), 'confirmed': False}
  if pending_present(workdir):
    return base_row(payload, 'pass_through', 'pending_state', elapsed_ms, 'accepted', body_bytes=len(data))
  try:
    previous = json.loads(read_file(workdir, STATE_NAME))
  except FileNotFoundError:
    previous = None
  except (OSError, ValueError, json.JSONDecodeError):
    return base_row(payload, 'pass_through', 'state_unreadable', elapsed_ms, 'accepted', body_bytes=len(data))
  if previous is None and not empty_workdir(workdir):
    return base_row(payload, 'pass_through', 'partial_state', elapsed_ms, 'accepted')
  valid_schema = (
    isinstance(previous, dict)
    and set(previous) == {'session', 'task', 'generation', 'bytes', 'confirmed'}
    and isinstance(previous['session'], str)
    and isinstance(previous['task'], str)
    and isinstance(previous['generation'], int)
    and isinstance(previous['bytes'], int)
    and isinstance(previous['confirmed'], bool)
  )
  identity_ok = valid_schema and previous['session'] == session and previous['task'] == task
  if previous is None or identity_ok:
    pass
  else:
    return base_row(payload, 'pass_through', 'state_mismatch', elapsed_ms, 'accepted', body_bytes=len(data))
  stale_generation = identity_ok and previous['generation'] != generation
  if previous is None or stale_generation:
    save_replace(workdir, CANDIDATE_NAME, data, 0o600)
    save_replace(workdir, STATE_NAME, json.dumps(current, sort_keys=True).encode(), 0o600)
    if not exists(workdir, GENERATION_FILE):
      save_replace(workdir, GENERATION_FILE, json.dumps({'generation': generation}, sort_keys=True).encode(), 0o600)
    row = base_row(payload, 'first_full', 'created' if previous is None else 'generation_reset', elapsed_ms, 'accepted', body_bytes=len(data))
    return row, {}, (session, task, generation, len(data))
  try:
    candidate = read_file(workdir, CANDIDATE_NAME)
  except (FileNotFoundError, OSError):
    return base_row(payload, 'pass_through', 'candidate_unreadable', elapsed_ms, 'accepted', body_bytes=len(data))
  if previous['bytes'] != len(candidate):
    return base_row(payload, 'pass_through', 'candidate_mismatch', elapsed_ms, 'accepted', body_bytes=len(data))
  if candidate != data and not previous['confirmed']:
    save_replace(workdir, CANDIDATE_NAME, data, 0o600)
    save_replace(workdir, STATE_NAME, json.dumps(current, sort_keys=True).encode(), 0o600)
    row = base_row(payload, 'changed_full', 'unconfirmed_replaced', elapsed_ms, 'accepted', body_bytes=len(data))
    return row, {}, (session, task, generation, len(data))
  if not previous['confirmed']:
    row = base_row(payload, 'pass_through', 'unconfirmed', elapsed_ms, 'accepted', body_bytes=len(data))
    return row, {}, (session, task, generation, len(data))
  if candidate != data:
    save_replace(workdir, CANDIDATE_NAME, data, 0o600)
    save_replace(workdir, STATE_NAME, json.dumps(current, sort_keys=True).encode(), 0o600)
    row = base_row(payload, 'changed_full', 'replaced', elapsed_ms, 'accepted', body_bytes=len(data))
    return row, {}, (session, task, generation, len(data))
  # 內容雜湊只當快照檔名：相同內容共用一份、不同內容各自保留；不用來驗證任何檔案。
  digest = hashlib.sha256(data).hexdigest()
  snapshot_name = f'snapshot-{digest}.txt'
  snapshot_path = str(Path(root_path) / name_of(session, task) / snapshot_name)
  try:
    stored = read_file(workdir, snapshot_name)
  except FileNotFoundError:
    write_new(workdir, snapshot_name, data, 0o400)
    os.fsync(workdir)
    stored = read_file(workdir, snapshot_name)
  except OSError:
    return base_row(payload, 'pass_through', 'snapshot_unreadable', elapsed_ms, 'accepted', body_bytes=len(data))
  if stored != data:
    return base_row(payload, 'pass_through', 'snapshot_mismatch', elapsed_ms, 'accepted', body_bytes=len(data))
  marker = f'相同本文，當次狀態仍在外層。此提示不是本文證據。\n若回答所需內容不在現有 context，先查原文快照，不以猜測或另找來源代替。先用 grep/rg 限定輸出範圍搜尋，再用 Read(offset, limit) 分段讀；無搜尋工具時直接分段讀。\n不要一次讀回全文；需要完整內容時持續分段讀完。\n原文快照：{snapshot_path}'
  if len(marker.encode()) >= len(data):
    return base_row(payload, 'pass_through', 'marker_not_shorter', elapsed_ms, 'accepted', body_bytes=len(data))
  row = base_row(payload, 'rewrite_requested', 'identical', elapsed_ms, 'accepted', body_bytes=len(data), marker_bytes=len(marker.encode()), rewrite_requested=True)
  replaced = copy.deepcopy(payload['tool_response'])
  replaced['task']['output'] = marker
  replaced['task']['result'] = marker
  return row, {'hookSpecificOutput': {'hookEventName': 'PostToolUse', 'updatedToolOutput': replaced}}


def workdir_session(workdir):
  try:
    previous = json.loads(read_file(workdir, STATE_NAME))
  except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
    return None
  if isinstance(previous, dict) and isinstance(previous.get('session'), str):
    return previous['session']
  return None


def reset_reason(matched):
  return 'no_match' if matched == 0 else 'reset_skipped'


def safe_open_workdir(root_fd, name):
  directory = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
  try:
    info = os.fstat(directory)
  except OSError:
    os.close(directory)
    raise
  if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
    os.close(directory)
    raise OSError('unsafe workdir')
  return directory


def session_start(payload, root_fd):
  session = payload.get('session_id')
  source = payload.get('source')
  if not isinstance(session, str) or not session:
    return base_row(payload, 'pass_through', 'no_session', 0, 'no_session', event='SessionStart')
  if not isinstance(source, str) or not source:
    return base_row(payload, 'pass_through', 'no_source', 0, 'accepted', event='SessionStart')
  busy = False
  uncertain = False
  reset = 0
  matched = 0
  for entry in list_workdirs(root_fd):
    try:
      workdir = safe_open_workdir(root_fd, entry)
    except OSError:
      uncertain = True
      continue
    try:
      if workdir_session(workdir) != session:
        continue
      matched += 1
      lock = None
      try:
        lock = acquire_lock(workdir)
      except LockBusy:
        try:
          write_sentinel(workdir)
          busy = True
        except OSError:
          uncertain = True
        continue
      except OSError:
        uncertain = True
        continue
      try:
        try:
          bump_generation(workdir, read_generation_file(workdir))
          reset += 1
        except OSError:
          try:
            write_sentinel(workdir)
          except OSError:
            pass
          uncertain = True
      finally:
        if lock is not None:
          os.close(lock)
    finally:
      os.close(workdir)
  if uncertain:
    return base_row(payload, 'pass_through', 'generation_uncertain', 0, 'accepted', event='SessionStart')
  if busy:
    return base_row(payload, 'pass_through', 'lock_busy', 0, 'accepted', event='SessionStart')
  if reset == 0:
    return base_row(payload, 'pass_through', reset_reason(matched), 0, 'accepted', event='SessionStart')
  return base_row(payload, 'pass_through', 'generation_reset', 0, 'accepted', event='SessionStart')


def taskoutput(payload, root_path):
  reason = shape_of(payload)
  if reason != 'accepted':
    return base_row(payload, 'pass_through', reason, 0, 'other'), {}, None
  session = payload['session_id']
  task = payload['tool_response']['task']['task_id']
  root_fd = open_root(root_path)
  try:
    try:
      workdir = open_workdir(root_fd, session, task)
    except OSError:
      return base_row(payload, 'pass_through', 'workdir_unreadable', 0, 'accepted'), {}, None
    lock = None
    try:
      try:
        lock = acquire_lock(workdir)
      except LockBusy:
        return base_row(payload, 'lock_busy', 'lock_busy', 0, 'accepted'), {}, None
      except OSError:
        return base_row(payload, 'pass_through', 'lock_unreadable', 0, 'accepted'), {}, None
      if exists(workdir, SENTINEL_NAME):
        try:
          bump_generation(workdir, read_generation_file(workdir))
        except OSError:
          return base_row(payload, 'pass_through', 'sentinel_error', 0, 'accepted'), {}, None
        try:
          clear_sentinel(workdir)
        except OSError:
          return base_row(payload, 'pass_through', 'sentinel_error', 0, 'accepted'), {}, None
      if pending_present(workdir):
        return base_row(payload, 'pass_through', 'pending_state', 0, 'accepted'), {}, None
      generation = read_generation(workdir)
      if not isinstance(generation, int):
        return base_row(payload, 'pass_through', 'generation_unreadable', 0, 'accepted'), {}, None
      result = fold(workdir, root_path, payload, session, task, generation, 0)
      if isinstance(result, tuple):
        if len(result) == 3:
          return result[0], result[1], result[2]
        return result[0], result[1], None
      return result, {}, None
    finally:
      if lock is not None:
        os.close(lock)
      os.close(workdir)
  finally:
    os.close(root_fd)


def handle(payload, root_path, enable_path):
  started = time.monotonic()
  if not enabled(enable_path):
    return {}, None
  if not isinstance(payload, dict):
    return {}, None
  if payload.get('hook_event_name') == 'SessionStart':
    session = payload.get('session_id')
    source = payload.get('source')
    if not isinstance(session, str) or not session:
      return {}, None
    if not isinstance(source, str) or not source:
      return {}, None
    root_fd = open_root(root_path)
    try:
      row = session_start(payload, root_fd)
      record(root_fd, session, row, started)
    finally:
      os.close(root_fd)
    return {}, None
  session = payload.get('session_id')
  if not isinstance(session, str) or not session:
    return {}, None
  row, output, confirm = taskoutput(payload, root_path)
  row['elapsed_ms'] = max(row['elapsed_ms'], int((time.monotonic() - started) * 1000))
  root_fd = open_root(root_path)
  try:
    record(root_fd, session, row, started)
  finally:
    os.close(root_fd)
  return output, confirm


def record(root_fd, session, row, started):
  row['elapsed_ms'] = max(row['elapsed_ms'], int((time.monotonic() - started) * 1000))
  append_row(root_fd, session, row)


def confirm_state(root_path, session, task, confirm):
  try:
    root_fd = open_root(root_path)
  except OSError:
    return
  try:
    try:
      workdir = open_workdir(root_fd, session, task)
    except OSError:
      return
    lock = None
    try:
      lock = acquire_lock(workdir)
    except (LockBusy, OSError):
      return
    try:
      confirm_locked(workdir, confirm)
    finally:
      if lock is not None:
        os.close(lock)
      os.close(workdir)
  finally:
    os.close(root_fd)


def confirm_locked(workdir, confirm):
  try:
    previous = json.loads(read_file(workdir, STATE_NAME))
  except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
    return
  if not isinstance(previous, dict) or not isinstance(previous.get('confirmed'), bool):
    return
  if previous.get('confirmed'):
    return
  session, task, generation, length = confirm
  if (
    previous.get('session') != session
    or previous.get('task') != task
    or previous.get('generation') != generation
    or previous.get('bytes') != length
  ):
    return
  marker = dict(previous)
  marker['confirmed'] = True
  try:
    save_replace(workdir, STATE_NAME, json.dumps(marker, sort_keys=True).encode(), 0o600)
  except OSError:
    pass


def main():
  root_path = os.path.abspath(os.environ.get(ROOT_ENV) or str(DEFAULT_ROOT))
  enable_path = os.path.abspath(os.environ.get(ENABLE_ENV) or str(DEFAULT_ENABLE))
  try:
    payload = json.load(sys.stdin)
  except (ValueError, UnicodeDecodeError):
    print('{}')
    return
  confirm = None
  try:
    output, confirm = handle(payload, root_path, enable_path)
  except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
    output = {}
  sys.stdout.write(json.dumps(output, ensure_ascii=False))
  sys.stdout.flush()
  if confirm is not None and output == {}:
    session = payload.get('session_id') if isinstance(payload, dict) else None
    task_id = None
    if isinstance(payload, dict):
      task_id = payload.get('tool_response', {}).get('task', {}).get('task_id') if isinstance(payload.get('tool_response'), dict) else None
    if isinstance(session, str) and isinstance(task_id, str):
      confirm_state(root_path, session, task_id, confirm)


if __name__ == '__main__':
  main()
