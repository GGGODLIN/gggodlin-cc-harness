#!/usr/bin/env python3
import argparse
import fcntl
from contextlib import contextmanager
import json
import os
import re
import stat
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

LOCK_RE = re.compile(
  r'^<!-- friction-review-lock:v1 session=(\S+) claimed_at=(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z) expires_at=(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z) -->$'
)
RECEIPT_RE = re.compile(
  r'^- (?:\d{4}-\d{2}-\d{2} )?\[proposal_source=(?:anchor:duplicate-2|trial-review:file-3|dormant-retriage|user)@[^;\]]+; user_decision=(?:approved|rejected|superseded)@[^;\]]+; implementation=[^\]]+\] .+$'
)
PENDING_RECEIPT_RE = re.compile(
  r'^- (?:\d{4}-\d{2}-\d{2} )?\[pending_implementation proposal_source=(?:anchor:duplicate-2|trial-review:file-3|dormant-retriage|user)@[^;\]]+; user_decision=approved@[^;\]]+; implementation=N-A（等待公司側落地）\] .+$'
)
DORMANT_TITLE = '## 休眠'
DORMANT_RE = re.compile(
  r'^- (?:\d{4}-\d{2}-\d{2} )?.+ \[dormant since=\d{4}-\d{2}-\d{2}; wake-when=[^\]]+\]$'
)
GUARDED_BOUNDARY = '\n\0FRICTION-DORMANT-BOUNDARY\0\n'
ENTRY_RE = re.compile(r'^- (?P<date>\d{4}-\d{2}-\d{2})(?:\s|$)')
BRACKET_AFTER_ENTRY_DATE_RE = re.compile(r'^- \[[^\]]+\]\s+(?P<date>\d{4}-\d{2}-\d{2})(?:\s|$)')
OLDER_THAN_RE = re.compile(r'^(?P<days>[1-9]\d*)d$')
TARGET_FIELD_RE = re.compile(r'\btarget=([^;\]]+)')
TARGET_SCHEME_RE = re.compile(r'^[A-Za-z0-9_-]+:(?=[/~])')
# ISO 時間戳 `approved@2026-09-29T06:01:44Z` 中 `9` 與 `T` 皆為 \w，用 `(?!\d)` 才不會漏掉帶時間的決策紀錄。
APPROVED_DATE_RE = re.compile(r'\buser_decision=approved@(\d{4}-\d{2}-\d{2})(?!\d)')
IMPLEMENTATION_FIELD_RE = re.compile(r'\bimplementation=([^;\]]+)')
acme_PARENT_DIRS = frozenset({
  'bin',
  'cli',
  'docs',
  'knowledge',
  'side-app-records',
  'onboarding',
  'receipts',
  'scripts',
})
KNOWN_acme_SUBREPOS = frozenset({'subrepo-a', 'subrepo-b'})
COMPANY_HANDLE_COMMAND = 'cd ~/Desktop/work/acme && claude "來處理摩擦"'


SYSTEM_ALIAS_TARGETS = {
  Path('/tmp'): Path('private/tmp'),
  Path('/var'): Path('private/var'),
}


def is_allowed_system_alias(path):
  expected_target = SYSTEM_ALIAS_TARGETS.get(path)
  if expected_target is None:
    return False
  try:
    return path.readlink() == expected_target
  except OSError:
    return False


def validate_archive_path(path, final_error='archive-path-symlink'):
  expanded = Path(path).expanduser()
  absolute = expanded if expanded.is_absolute() else Path.cwd() / expanded
  current = Path(absolute.anchor)
  for component in absolute.parts[1:]:
    if component == '.':
      continue
    if component == '..':
      current = current.parent
      continue
    current /= component
    if current.is_symlink() and not is_allowed_system_alias(current):
      if current == absolute:
        raise ValueError(final_error)
      raise ValueError(f'archive-path-component-symlink:{current}')
  return absolute


def parse_time(value):
  return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)


def section_end(lines, start):
  for index in range(start + 1, len(lines)):
    if lines[index].rstrip('\n').startswith('## '):
      return index
  return len(lines)


def parse_age(value):
  match = OLDER_THAN_RE.fullmatch(value)
  if match is None:
    raise ValueError('invalid-older-than')
  return timedelta(days=int(match.group('days')))


def parse_date(value):
  try:
    return date.fromisoformat(value)
  except ValueError as error:
    raise ValueError('invalid-as-of') from error


def source_lock_path(path):
  resolved = Path(path).expanduser().resolve()
  return resolved.with_name(f'.{resolved.name}.friction-review.lock')


def archive_root_lock_path(archive_dir):
  validated = validate_archive_path(archive_dir, 'archive-dir-symlink')
  resolved = validated.resolve()
  return resolved.parent / f'.{resolved.name}.friction-review.lock'


def archive_file_lock_path(path):
  validated = validate_archive_path(path, 'archive-file-symlink')
  resolved = validated.resolve()
  return resolved.with_name(f'.{resolved.name}.friction-review.lock')


@contextmanager
def acquire_stable_locks(paths):
  handles = []
  try:
    for lock_path in sorted({Path(path) for path in paths}, key=str):
      lock_path.parent.mkdir(parents=True, exist_ok=True)
      handle = lock_path.open('a+')
      try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
      except Exception:
        handle.close()
        raise
      handles.append(handle)
    yield
  finally:
    for handle in reversed(handles):
      fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
      handle.close()


def archive_prefix_for(source_path, explicit_prefix=None):
  if explicit_prefix is not None:
    return explicit_prefix
  if source_path is not None and Path(source_path).stem == 'doc-drift':
    return 'doc-drift-'
  return ''


def quarter_path(archive_dir, entry_date, prefix=''):
  quarter = (entry_date.month - 1) // 3 + 1
  return archive_dir / f'{prefix}{entry_date.year}-Q{quarter}.md'


def archive_paths(archive_dir, entries, prefix=''):
  return sorted({quarter_path(archive_dir, entry['date'], prefix) for entry in entries}, key=str)


def find_sections(lines):
  pending_start = None
  pending_end = None
  closed_start = None
  closed_title = None
  for index, line in enumerate(lines):
    title = line.rstrip('\n')
    if pending_start is None:
      if title == '## 待折':
        pending_start = index
      continue
    if pending_end is None and title.startswith('## '):
      pending_end = index
      break
  if pending_start is None:
    raise ValueError('missing-pending-section')
  if pending_end is None:
    pending_end = len(lines)
  for index in range(pending_end, len(lines)):
    title = lines[index].rstrip('\n')
    if title in {'## 已折／已否決', '## 已折 / 已否決'}:
      closed_start = index
      closed_title = title
      break
  if closed_start is None:
    raise ValueError('missing-closed-section')
  return pending_start, pending_end, closed_start, closed_title


def find_dormant_section(lines):
  _, pending_end, closed_start, _ = find_sections(lines)
  for index in range(pending_end, closed_start):
    if lines[index].rstrip('\n') == DORMANT_TITLE:
      return index, section_end(lines, index)
  return None, None


def pending_lines(lines):
  pending_start, pending_end, _, _ = find_sections(lines)
  return lines[pending_start + 1:pending_end]


def dormant_lines(lines):
  dormant_start, dormant_end = find_dormant_section(lines)
  if dormant_start is None:
    return []
  return lines[dormant_start + 1:dormant_end]


def guarded_text(lines):
  pending_content = ''.join(line for line in pending_lines(lines) if not LOCK_RE.fullmatch(line.rstrip('\n')))
  dormant_content = ''.join(dormant_lines(lines))
  return f'{pending_content}{GUARDED_BOUNDARY}{dormant_content}'


def validate_snapshot_path(path, must_exist=False):
  validated = validate_archive_path(path, 'snapshot-path-symlink')
  if validated.is_symlink():
    raise ValueError('snapshot-path-symlink')
  if validated.exists():
    info = os.lstat(validated)
    if not stat.S_ISREG(info.st_mode):
      raise ValueError('invalid-snapshot-file')
    if info.st_nlink > 1:
      raise ValueError('snapshot-hardlink')
  elif must_exist:
    raise ValueError('missing-snapshot-file')
  return validated


def write_snapshot(snapshot_path, text):
  validated = validate_snapshot_path(snapshot_path, must_exist=False)
  validated.parent.mkdir(parents=True, exist_ok=True)
  staged = stage_text(validated.parent, validated.name, text, 0o600)
  try:
    os.replace(staged, validated)
  finally:
    if staged.exists():
      staged.unlink()
  return validated


def read_snapshot(snapshot_path):
  validated = validate_snapshot_path(snapshot_path, must_exist=True)
  flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
  fd = os.open(validated, flags)
  try:
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode):
      raise ValueError('invalid-snapshot-file')
    if info.st_nlink > 1:
      raise ValueError('snapshot-hardlink')
    with os.fdopen(fd, 'r', encoding='utf-8') as handle:
      fd = None
      return handle.read()
  finally:
    if fd is not None:
      os.close(fd)


def parse_lock(lines):
  matches = []
  pending_start, pending_end, _, _ = find_sections(lines)
  current_h2 = None
  for index, line in enumerate(lines):
    title = line.rstrip('\n')
    if title.startswith('## '):
      current_h2 = title
    # 只認以 marker 開頭的行（容許前置空白，交給 LOCK_RE 判成格式錯誤）；條目內文可能引用 session 原文裡的同一串字，那不是鎖。
    marker_like = line.lstrip().startswith('<!-- friction-review-lock:')
    match = LOCK_RE.fullmatch(title)
    if pending_start < index < pending_end:
      if match:
        matches.append((index, match))
      elif marker_like:
        raise ValueError('malformed-lock')
      continue
    if marker_like:
      if current_h2 != '## 待折':
        raise ValueError('lock-outside-pending')
      if not match:
        raise ValueError('malformed-lock')
  if len(matches) != 1:
    raise ValueError('lock-count')
  lock_index, match = matches[0]
  if lock_index != pending_start + 1:
    raise ValueError('lock-position')
  return {
    'session': match.group(1),
    'claimed_at': parse_time(match.group(2)),
    'expires_at': parse_time(match.group(3)),
  }


def validate(lines, session, expected_text, now):
  lock = parse_lock(lines)
  if lock['session'] != session:
    raise ValueError('owner-mismatch')
  if lock['claimed_at'] > now:
    raise ValueError('claim-in-future')
  if lock['expires_at'] - lock['claimed_at'] != timedelta(hours=24):
    raise ValueError('invalid-lock-window')
  if lock['expires_at'] <= now:
    raise ValueError('lock-expired')
  if guarded_text(lines) != expected_text:
    raise ValueError('snapshot-mismatch')


def strip_lock(lines):
  pending_start, pending_end, _, _ = find_sections(lines)
  return [
    line
    for index, line in enumerate(lines)
    if not (pending_start < index < pending_end and LOCK_RE.fullmatch(line.rstrip('\n')))
  ]


def replace_first_pending_item(lines, original, replacement):
  pending_start, pending_end, _, _ = find_sections(lines)
  positions = [index for index in range(pending_start + 1, pending_end) if lines[index].rstrip('\n') == original]
  if len(positions) != 1:
    raise ValueError('item-count')
  updated = list(lines)
  if replacement is None:
    index = positions[0]
    del updated[index]
    prev_blank = index - 1 > pending_start and updated[index - 1].strip() == ''
    next_blank = index < len(updated) and updated[index].strip() == ''
    if prev_blank and next_blank:
      del updated[index]
  else:
    updated[positions[0]] = replacement + '\n'
  return updated


def replace_first_dormant_item(lines, original, replacement):
  dormant_start, dormant_end = find_dormant_section(lines)
  if dormant_start is None:
    raise ValueError('missing-dormant-section')
  positions = [index for index in range(dormant_start + 1, dormant_end) if lines[index].rstrip('\n') == original]
  if len(positions) != 1:
    raise ValueError('item-count')
  updated = list(lines)
  if replacement is None:
    index = positions[0]
    del updated[index]
    prev_blank = index - 1 > dormant_start and updated[index - 1].strip() == ''
    next_blank = index < len(updated) and updated[index].strip() == ''
    if prev_blank and next_blank:
      del updated[index]
  else:
    updated[positions[0]] = replacement + '\n'
  return updated


def append_pending_item(lines, item):
  pending_start, pending_end, _, _ = find_sections(lines)
  updated = list(lines)
  insert_at = pending_end
  while insert_at > pending_start + 1 and updated[insert_at - 1].strip() == '':
    insert_at -= 1
  if insert_at > pending_start + 1 and not updated[insert_at - 1].endswith('\n'):
    updated[insert_at - 1] += '\n'
  updated.insert(insert_at, item + '\n')
  if insert_at + 1 < len(updated) and updated[insert_at + 1].rstrip('\n').startswith('## '):
    updated.insert(insert_at + 1, '\n')
  return updated


def normalize_closed_title(lines):
  _, _, closed_start, closed_title = find_sections(lines)
  updated = list(lines)
  if closed_title == '## 已折 / 已否決':
    updated[closed_start] = '## 已折／已否決\n'
  return updated


def append_closed_item(lines, item):
  _, _, closed_start, _ = find_sections(lines)
  updated = normalize_closed_title(lines)
  updated.insert(closed_start + 1, '\n' + item + '\n')
  return updated


def append_dormant_item(lines, item):
  # 休眠段位於待折段與已折段之間；不存在時就地建立，避免呼叫端各自補標題造成位置漂移。
  pending_start, pending_end, closed_start, _ = find_sections(lines)
  dormant_start = None
  for index in range(pending_end, closed_start):
    if lines[index].rstrip('\n') == DORMANT_TITLE:
      dormant_start = index
      break
  updated = list(lines)
  if dormant_start is None:
    updated.insert(pending_end, DORMANT_TITLE + '\n')
    updated.insert(pending_end + 1, '\n')
    dormant_start = pending_end
  updated.insert(dormant_start + 1, '\n' + item + '\n')
  return updated


def apply_operation(lines, action, original, receipt):
  if '\n' in original or '\r' in original or '\n' in receipt or '\r' in receipt:
    raise ValueError('multiline-value')
  if not original.startswith('- '):
    raise ValueError('invalid-item-line')
  if action in {'approved', 'rejected', 'landed', 'superseded', 'close-dormant'} and not RECEIPT_RE.fullmatch(receipt):
    raise ValueError('invalid-receipt')
  if action == 'superseded' and 'user_decision=superseded@' not in receipt:
    raise ValueError('invalid-receipt')
  if action == 'close-dormant' and '[dormant ' in receipt:
    raise ValueError('dormant-suffix-remaining')
  if action in {'company-pending', 'dormant-to-company-pending'}:
    if not PENDING_RECEIPT_RE.fullmatch(receipt):
      raise ValueError('invalid-pending-receipt')
    if '[dormant ' in receipt:
      raise ValueError('dormant-suffix-remaining')
  if action in {'dormant', 'update-dormant'}:
    # 休眠不是處置：不得帶 user_decision／proposal_source／implementation，否則會被誤計為已折入
    if not DORMANT_RE.fullmatch(receipt):
      raise ValueError('invalid-dormant-receipt')
    if any(token in receipt for token in ('user_decision=', 'proposal_source=', 'implementation=')):
      raise ValueError('dormant-carries-disposition')
    if action == 'dormant':
      return append_dormant_item(replace_first_pending_item(lines, original, None), receipt)
    return replace_first_dormant_item(lines, original, receipt)
  if action == 'wake-dormant':
    if not receipt.startswith('- '):
      raise ValueError('invalid-wake-receipt')
    if '[dormant ' in receipt or any(token in receipt for token in ('user_decision=', 'proposal_source=', 'implementation=')):
      raise ValueError('wake-carries-state')
    return append_pending_item(replace_first_dormant_item(lines, original, None), receipt)
  if action == 'close-dormant':
    return append_closed_item(replace_first_dormant_item(lines, original, None), receipt)
  if action == 'dormant-to-company-pending':
    return append_pending_item(replace_first_dormant_item(lines, original, None), receipt)
  if action in {'approved', 'rejected', 'landed', 'superseded'}:
    return append_closed_item(replace_first_pending_item(lines, original, None), receipt)
  if action == 'company-pending':
    return replace_first_pending_item(lines, original, receipt)
  raise ValueError('unsupported-action')


def transform(lines, operations, release_lock):
  if not operations and not release_lock:
    raise ValueError('empty-operations')
  updated = list(lines)
  for operation in operations:
    if set(operation) != {'action', 'original', 'receipt'}:
      raise ValueError('invalid-operation-shape')
    updated = apply_operation(updated, operation['action'], operation['original'], operation['receipt'])
  return strip_lock(updated) if release_lock else updated


def tidy_pending_blanks(lines, release_lock):
  if not release_lock:
    raise ValueError('tidy-requires-release-lock')
  stripped = strip_lock(lines)
  pending_start, pending_end, _, _ = find_sections(stripped)
  collapsed = []
  for line in stripped[pending_start + 1:pending_end]:
    if line.strip() == '' and collapsed and collapsed[-1].strip() == '':
      continue
    collapsed.append(line)
  return stripped[:pending_start + 1] + collapsed + stripped[pending_end:]


def closed_entries(lines):
  _, _, closed_start, _ = find_sections(lines)
  closed_end = section_end(lines, closed_start)
  starts = []
  for index in range(closed_start + 1, closed_end):
    match = ENTRY_RE.match(lines[index].rstrip('\n'))
    if match is None:
      continue
    try:
      entry_date = date.fromisoformat(match.group('date'))
    except ValueError as error:
      raise ValueError(f'invalid-entry-date:{match.group("date")}') from error
    starts.append((index, entry_date))
  entries = []
  for position, (start, entry_date) in enumerate(starts):
    end = starts[position + 1][0] if position + 1 < len(starts) else closed_end
    entries.append({
      'start': start,
      'end': end,
      'date': entry_date,
      'lines': lines[start:end],
    })
  return entries


def retire_lines(lines, cutoff):
  entries = closed_entries(lines)
  selected = [entry for entry in entries if entry['date'] < cutoff]
  if not selected:
    return list(lines), selected
  ranges = [(entry['start'], entry['end']) for entry in selected]
  updated = [
    line
    for index, line in enumerate(lines)
    if not any(start <= index < end for start, end in ranges)
  ]
  return updated, selected


def append_archive_content(existing, entries):
  content = existing
  for entry in entries:
    block = ''.join(entry['lines'])
    if not block.endswith('\n'):
      block += '\n'
    if not content:
      content = block
    elif content.endswith('\n\n'):
      content += block.lstrip('\n')
    elif content.endswith('\n'):
      content += '\n' + block.lstrip('\n')
    else:
      content += '\n\n' + block.lstrip('\n')
  return content


def build_archive_updates(archive_dir, entries, prefix=''):
  archive_dir = validate_archive_path(archive_dir, 'archive-dir-symlink')
  if archive_dir.is_symlink():
    raise ValueError('archive-dir-symlink')
  if archive_dir.exists() and not archive_dir.is_dir():
    raise ValueError('invalid-archive-dir')
  grouped = {}
  for entry in entries:
    grouped.setdefault(quarter_path(archive_dir, entry['date'], prefix), []).append(entry)
  updates = {}
  for path, grouped_entries in grouped.items():
    validate_archive_path(path, 'archive-file-symlink')
    if path.is_symlink():
      raise ValueError(f'archive-file-symlink:{path}')
    if path.exists() and not path.is_file():
      raise ValueError(f'invalid-archive-file:{path}')
    existing = path.read_text(encoding='utf-8') if path.exists() else ''
    updates[path] = {
      'existing': existing,
      'updated': append_archive_content(existing, grouped_entries),
      'count': len(grouped_entries),
    }
  return updates


def write_open_file(file, text):
  file.seek(0)
  file.write(text)
  file.truncate()
  file.flush()
  os.fsync(file.fileno())


def wait_before_write(signal):
  signal_path = Path(signal)
  signal_path.write_text('READY')
  ack_path = signal_path.with_suffix(signal_path.suffix + '.ack')
  for _ in range(500):
    if ack_path.exists():
      return
    import time
    time.sleep(0.01)
  raise ValueError('before-write-timeout')


def stage_text(directory, name, text, mode=None):
  handle = tempfile.NamedTemporaryFile(
    mode='w',
    encoding='utf-8',
    dir=str(directory),
    prefix=f'.{name}.retire-',
    delete=False,
  )
  staged = Path(handle.name)
  try:
    handle.write(text)
    handle.flush()
    os.fsync(handle.fileno())
    if mode is not None:
      os.chmod(staged, mode)
  finally:
    handle.close()
  return staged


def cleanup_staged(paths):
  for path in paths:
    if path.exists():
      path.unlink()


def rollback_replaced(replaced):
  errors = []
  for path, existed, original, mode in reversed(replaced):
    try:
      if existed:
        rollback = stage_text(path.parent, path.name, original, mode)
        try:
          os.replace(rollback, path)
        finally:
          if rollback.exists():
            rollback.unlink()
      elif path.exists() or path.is_symlink():
        path.unlink()
    except OSError as error:
      errors.append(f'{path}: {error}')
  if errors:
    raise RuntimeError(f"rollback-incomplete: {'; '.join(errors)}")


def apply_retire_transaction(path, original_text, updated_text, updates):
  archive_states = []
  staged = []
  replaced = []
  try:
    for archive_path in sorted(updates, key=str):
      validate_archive_path(archive_path, 'archive-file-symlink')
      archive_path.parent.mkdir(parents=True, exist_ok=True)
      existed = archive_path.exists()
      current = archive_path.read_text(encoding='utf-8') if existed else ''
      expected = updates[archive_path]['existing']
      if current != expected:
        raise ValueError(f'archive-concurrent-change:{archive_path}')
      mode = stat.S_IMODE(archive_path.stat().st_mode) if existed else None
      archive_states.append((archive_path, existed, current, mode))

    for archive_path, _, _, mode in archive_states:
      validate_archive_path(archive_path, 'archive-file-symlink')
      archive_stage = stage_text(archive_path.parent, archive_path.name, updates[archive_path]['updated'], mode)
      staged.append(archive_stage)

    source_mode = stat.S_IMODE(path.stat().st_mode)
    source_stage = stage_text(path.parent, path.name, updated_text, source_mode)
    staged.append(source_stage)

    for index, (archive_path, existed, current, mode) in enumerate(archive_states):
      validate_archive_path(archive_path, 'archive-file-symlink')
      archive_stage = staged[index]
      os.replace(archive_stage, archive_path)
      replaced.append((archive_path, existed, current, mode))

    os.replace(source_stage, path)
    replaced.append((path, True, original_text, source_mode))
  except Exception as error:
    rollback_error = None
    try:
      rollback_replaced(replaced)
    except RuntimeError as rollback_failure:
      rollback_error = rollback_failure
    try:
      for archive_path, existed, current, _ in archive_states:
        if not existed and archive_path.exists() and archive_path.is_file() and archive_path.read_text(encoding='utf-8') == current:
          archive_path.unlink()
    except OSError as cleanup_error:
      rollback_error = rollback_error or cleanup_error
    if rollback_error is not None:
      raise RuntimeError(f'rollback-incomplete: {rollback_error}') from error
    raise
  finally:
    cleanup_staged(staged)


def retire(path, session, expected_text, archive_dir, older_than, as_of, before_write_signal=None, archive_prefix=None):
  archive_dir = validate_archive_path(archive_dir.expanduser(), 'archive-dir-symlink')
  archive_dir = archive_dir.resolve()
  prefix = archive_prefix_for(path, archive_prefix)
  base_locks = [source_lock_path(path), archive_root_lock_path(archive_dir)]
  with acquire_stable_locks(base_locks):
    for _ in range(3):
      with path.open('r+', encoding='utf-8') as file:
        initial_text = file.read()
        initial_lines = initial_text.splitlines(keepends=True)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        initial_lock = parse_lock(initial_lines)
        if initial_lock['session'] != session and initial_lock['expires_at'] > now:
          return {'status': 'skipped', 'reason': 'lock-active'}
        validate(initial_lines, session, expected_text, now)
        _, initial_selected = retire_lines(initial_lines, as_of - older_than)
        planned_archives = archive_paths(archive_dir, initial_selected, prefix)

      quarter_locks = [archive_file_lock_path(archive_path) for archive_path in planned_archives]
      with acquire_stable_locks(quarter_locks):
        with path.open('r+', encoding='utf-8') as file:
          original_text = file.read()
          lines = original_text.splitlines(keepends=True)
          now = datetime.now(timezone.utc).replace(microsecond=0)
          lock = parse_lock(lines)
          if lock['session'] != session and lock['expires_at'] > now:
            return {'status': 'skipped', 'reason': 'lock-active'}
          validate(lines, session, expected_text, now)
          updated, selected = retire_lines(lines, as_of - older_than)
          current_archives = archive_paths(archive_dir, selected, prefix)
          if current_archives != planned_archives:
            continue
          updates = build_archive_updates(archive_dir, selected, prefix)
          if before_write_signal:
            wait_before_write(before_write_signal)
          file.seek(0)
          current_text = file.read()
          if current_text != original_text:
            raise ValueError('concurrent-change')
          validate(
            current_text.splitlines(keepends=True),
            session,
            expected_text,
            datetime.now(timezone.utc).replace(microsecond=0),
          )
          updated_text = ''.join(normalize_closed_title(strip_lock(updated)))
          apply_retire_transaction(path, original_text, updated_text, updates)
        return {
          'status': 'retired',
          'entries': len(selected),
          'archives': {str(path): value['count'] for path, value in updates.items()},
        }
  raise ValueError('lock-plan-changed')


def is_valid_iso_date(value):
  try:
    date.fromisoformat(value)
    return True
  except ValueError:
    return False


def extract_leading_date(line):
  for pattern in (ENTRY_RE, BRACKET_AFTER_ENTRY_DATE_RE):
    match = pattern.match(line)
    if match is not None and is_valid_iso_date(match.group('date')):
      return match.group('date')
  return None


def is_path_under(path, root):
  try:
    path.resolve().relative_to(root.resolve())
    return True
  except (OSError, ValueError):
    return False


def extract_target_value(line):
  match = TARGET_FIELD_RE.search(line)
  if match is None:
    return None
  raw = match.group(1).strip().strip('"\'')
  return TARGET_SCHEME_RE.sub('', raw)


def has_company_target(line, work_root):
  target = extract_target_value(line)
  if not target:
    return False
  expanded = str(Path(target).expanduser()) if target.startswith('~') else target
  work_prefix = str(work_root).rstrip('/')
  return (
    '/Desktop/work/' in target
    or '/Desktop/work/' in expanded
    or expanded == work_prefix
    or expanded.startswith(work_prefix + '/')
  )


def resolve_company_repo(line, work_root):
  target = extract_target_value(line)
  if not target or '/' not in target:
    return 'company-other'
  expanded = str(Path(target).expanduser()) if target.startswith('~') else target
  work_prefix = str(work_root).rstrip('/')
  rel = None
  if expanded == work_prefix:
    rel = ''
  elif expanded.startswith(work_prefix + '/'):
    rel = expanded[len(work_prefix) + 1:]
  elif '/Desktop/work/acme/' in expanded:
    rel = expanded.split('/Desktop/work/acme/', 1)[1]
  elif expanded.endswith('/Desktop/work/acme'):
    rel = ''

  if rel is not None:
    rel = rel.strip('/')
    if not rel:
      return 'acme'
    if '/' not in rel:
      if rel.startswith('acme-') or rel in KNOWN_acme_SUBREPOS or (work_root / rel / '.git').exists():
        return rel
      return 'acme'
    first_seg = rel.split('/', 1)[0]
    if first_seg.startswith('.') or first_seg in acme_PARENT_DIRS:
      return 'acme'
    candidate_dir = work_root / first_seg
    if (work_root / '.git').exists() and candidate_dir.exists() and not (candidate_dir / '.git').exists():
      return 'acme'
    return first_seg

  if '/Desktop/work/' in expanded:
    after_work = expanded.split('/Desktop/work/', 1)[1].strip('/')
    if after_work:
      return after_work.split('/', 1)[0]
  return 'company-other'


def optional_sections(lines):
  # 舊摩擦檔或 acme/docs/owner/harness-friction.md 可能尚未補齊三段標題，唯讀彙整不得因缺段拋錯。
  pending_start = None
  for index, raw in enumerate(lines):
    if raw.rstrip('\n') == '## 待折':
      pending_start = index
      break
  pending_end = section_end(lines, pending_start) if pending_start is not None else 0
  pending_slice = lines[pending_start + 1:pending_end] if pending_start is not None else []

  dormant_slice = []
  closed_slice = []
  search_from = pending_end if pending_start is not None else 0
  for index in range(search_from, len(lines)):
    title = lines[index].rstrip('\n')
    if not dormant_slice and title == DORMANT_TITLE:
      dormant_slice = lines[index + 1:section_end(lines, index)]
    elif not closed_slice and title in {'## 已折／已否決', '## 已折 / 已否決'}:
      closed_slice = lines[index + 1:section_end(lines, index)]
  return pending_slice, dormant_slice, closed_slice


def collect_company_friction_files(scan_home, work_root):
  candidates = []
  friction_dir = scan_home / 'friction'
  if friction_dir.is_dir():
    candidates.extend(
      path for path in sorted(friction_dir.glob('*.md')) if path.name != 'PROTOCOL.md' and path.is_file()
    )
  skills_dir = scan_home / 'skills'
  if skills_dir.is_dir():
    candidates.extend(path for path in sorted(skills_dir.glob('*/friction-log.md')) if path.is_file())
  pr_review_file = scan_home / 'pr-review' / 'friction.md'
  if pr_review_file.is_file():
    candidates.append(pr_review_file)
  harness_friction = work_root / 'docs' / 'owner' / 'harness-friction.md'
  if harness_friction.is_file():
    candidates.append(harness_friction)

  seen = set()
  unique = []
  for candidate in candidates:
    key = str(candidate.resolve())
    if key not in seen:
      seen.add(key)
      unique.append(candidate)
  return unique, harness_friction


def extract_closed_company_date(line):
  if 'user_decision=approved@' not in line or '[pending_implementation ' in line:
    return None
  impl_match = IMPLEMENTATION_FIELD_RE.search(line)
  if impl_match is None:
    return None
  impl_value = impl_match.group(1).strip()
  if not impl_value or impl_value.startswith('N-A'):
    return None
  approved_match = APPROVED_DATE_RE.search(line)
  if approved_match is not None and is_valid_iso_date(approved_match.group(1)):
    return approved_match.group(1)
  return extract_leading_date(line)


def lint_single_file(file_path):
  lines = file_path.read_text(encoding='utf-8').splitlines(keepends=True)
  issues = []
  pending_start = None
  closed_start = None
  for index, raw in enumerate(lines):
    title = raw.rstrip('\n')
    if pending_start is None and title == '## 待折':
      pending_start = index
    if pending_start is not None and closed_start is None and index > pending_start and title in {'## 已折／已否決', '## 已折 / 已否決'}:
      closed_start = index

  bullet_lines = [index + 1 for index, raw in enumerate(lines) if raw.startswith('- ')]
  if pending_start is None:
    if bullet_lines:
      issues.append({
        'file': str(file_path),
        'kind': 'missing-pending-section',
        'count': len(bullet_lines),
        'lines': bullet_lines[:10],
      })
    return issues

  if closed_start is None:
    issues.append({
      'file': str(file_path),
      'kind': 'missing-closed-section',
      'count': 1,
      'lines': [pending_start + 1],
    })
    return issues

  unattributed = []
  for index in range(closed_start + 1, len(lines)):
    line = lines[index].rstrip('\n')
    if not line.startswith('- '):
      continue
    if 'source_ref=' in line and 'user_decision=' not in line:
      unattributed.append(index + 1)
  if unattributed:
    issues.append({
      'file': str(file_path),
      'kind': 'unattributed-after-closed',
      'count': len(unattributed),
      'lines': unattributed[:20],
    })
  return issues


def lint_friction_files(scan_home, work_root):
  scan_home = Path(scan_home).expanduser()
  work_root = Path(work_root).expanduser()
  files, _ = collect_company_friction_files(scan_home, work_root)
  issues = []
  for file_path in files:
    issues.extend(lint_single_file(file_path))
  return {
    'files_scanned': len(files),
    'issue_count': len(issues),
    'affected_entries': sum(item['count'] for item in issues),
    'issues': issues,
  }


def format_lint_summary_text(report):
  if report['issue_count'] == 0:
    return ''
  parts = []
  for item in report['issues']:
    name = Path(item['file']).name
    parent = Path(item['file']).parent.name
    parts.append(f"{parent}/{name}({item['kind']}:{item['count']})")
  return f"⚠️ 摩擦結構異常：{report['issue_count']} 項（影響 {report['affected_entries']} 筆）：{'、'.join(parts)}"


def bootstrap_file(path):
  with acquire_stable_locks([source_lock_path(path)]):
    with path.open('r+', encoding='utf-8') as file:
      original_text = file.read()
      lines = original_text.splitlines(keepends=True)
      updated = list(lines)

      # 先正規化舊式非標準標題
      for index, raw in enumerate(updated):
        title = raw.rstrip('\n')
        if title == '## 待拍板':
          updated[index] = '## 待折\n'
        elif title in {'## 已折入', '## 已折 / 已否決'}:
          updated[index] = '## 已折／已否決\n'

      has_pending = any(raw.rstrip('\n') == '## 待折' for raw in updated)
      if not has_pending:
        first_bullet = next((i for i, raw in enumerate(updated) if raw.startswith('- ')), None)
        if first_bullet is None:
          if updated and not updated[-1].endswith('\n'):
            updated[-1] += '\n'
          updated.extend(['\n', '## 待折\n', '\n'])
        else:
          prefix = updated[:first_bullet]
          if prefix and not prefix[-1].endswith('\n'):
            prefix[-1] += '\n'
          if prefix and prefix[-1].strip() != '':
            prefix.append('\n')
          updated = prefix + ['## 待折\n', '\n'] + updated[first_bullet:]

      pending_start = next(i for i, raw in enumerate(updated) if raw.rstrip('\n') == '## 待折')
      has_closed = any(
        raw.rstrip('\n') in {'## 已折／已否決', '## 已折 / 已否決'}
        for raw in updated[pending_start + 1:]
      )
      if not has_closed:
        if updated and not updated[-1].endswith('\n'):
          updated[-1] += '\n'
        if updated and updated[-1].strip() != '':
          updated.append('\n')
        updated.append('## 已折／已否決\n')

      new_text = ''.join(updated)
      if new_text == original_text:
        return 'UNCHANGED'
      write_open_file(file, new_text)
      return 'BOOTSTRAPPED'


def build_company_summary(scan_home, work_root):
  scan_home = Path(scan_home).expanduser()
  work_root = Path(work_root).expanduser()
  files, harness_friction = collect_company_friction_files(scan_home, work_root)
  harness_resolved = harness_friction.resolve() if harness_friction.exists() else None

  pending_impl_count = 0
  by_repo = {}
  unreviewed_by_repo = {}
  dormant_by_repo = {}
  unreviewed_company_count = 0
  dormant_company_count = 0
  open_company_dates = []
  handled_dates = []

  for file_path in files:
    lines = file_path.read_text(encoding='utf-8').splitlines(keepends=True)
    pending_slice, dormant_slice, closed_slice = optional_sections(lines)
    is_work_file = is_path_under(file_path, work_root)
    is_harness_friction = harness_resolved is not None and file_path.resolve() == harness_resolved

    for raw_line in pending_slice:
      line = raw_line.rstrip('\n')
      if not line.startswith('- '):
        continue
      if '[pending_implementation ' in line:
        pending_impl_count += 1
        repo = resolve_company_repo(line, work_root)
        by_repo[repo] = by_repo.get(repo, 0) + 1
        entry_date = extract_leading_date(line)
        if entry_date is not None:
          open_company_dates.append(entry_date)
      elif is_harness_friction or has_company_target(line, work_root):
        unreviewed_company_count += 1
        repo = 'harness-friction' if is_harness_friction and not has_company_target(line, work_root) else resolve_company_repo(line, work_root)
        unreviewed_by_repo[repo] = unreviewed_by_repo.get(repo, 0) + 1
        entry_date = extract_leading_date(line)
        if entry_date is not None:
          open_company_dates.append(entry_date)

    for raw_line in dormant_slice:
      line = raw_line.rstrip('\n')
      if line.startswith('- ') and (is_work_file or has_company_target(line, work_root)):
        dormant_company_count += 1
        repo = resolve_company_repo(line, work_root)
        dormant_by_repo[repo] = dormant_by_repo.get(repo, 0) + 1

    for raw_line in closed_slice:
      line = raw_line.rstrip('\n')
      if not line.startswith('- '):
        continue
      if not (is_work_file or has_company_target(line, work_root)):
        continue
      closed_date = extract_closed_company_date(line)
      if closed_date is not None:
        handled_dates.append(closed_date)

  sorted_by_repo = dict(sorted(by_repo.items(), key=lambda item: (-item[1], item[0])))
  sorted_unreviewed_by_repo = dict(sorted(unreviewed_by_repo.items(), key=lambda item: (-item[1], item[0])))
  sorted_dormant_by_repo = dict(sorted(dormant_by_repo.items(), key=lambda item: (-item[1], item[0])))
  if handled_dates:
    last_handled = max(handled_dates)
  elif open_company_dates:
    last_handled = f'尚無紀錄（最早累積自 {min(open_company_dates)}）'
  else:
    last_handled = '尚無紀錄'

  total_pending = pending_impl_count + unreviewed_company_count
  return {
    'has_company_pending': total_pending > 0,
    'pending_impl_count': pending_impl_count,
    'by_repo': sorted_by_repo,
    'unreviewed_company_count': unreviewed_company_count,
    'unreviewed_by_repo': sorted_unreviewed_by_repo,
    'dormant_company_count': dormant_company_count,
    'dormant_by_repo': sorted_dormant_by_repo,
    'last_handled': last_handled,
  }


def format_company_summary_text(summary):
  if not summary['has_company_pending']:
    return ''
  total_pending = summary['pending_impl_count'] + summary['unreviewed_company_count']
  segments = []
  if summary['pending_impl_count'] > 0:
    pending_groups = '、'.join(f'{repo} {count}' for repo, count in summary['by_repo'].items())
    segments.append(f"待開 PR {summary['pending_impl_count']}（{pending_groups}）")
  if summary['unreviewed_company_count'] > 0:
    unrev_map = summary.get('unreviewed_by_repo') or {}
    if unrev_map:
      unrev_groups = '、'.join(f'{repo} {count}' for repo, count in unrev_map.items())
      segments.append(f"未審待決 {summary['unreviewed_company_count']}（{unrev_groups}）")
    else:
      segments.append(f"未審待決 {summary['unreviewed_company_count']}")
  breakdown = '；'.join(segments)
  if summary['dormant_company_count'] > 0:
    breakdown = f"{breakdown}；另有休眠待決 {summary['dormant_company_count']} 項"
  line1 = f"🏢 公司側待處理：共 {total_pending} 項（{breakdown}）｜上次處理：{summary['last_handled']}"
  line2 = f'   處理指令：{COMPANY_HANDLE_COMMAND}'
  return f'{line1}\n{line2}'


def main():
  parser = argparse.ArgumentParser()
  subparsers = parser.add_subparsers(dest='command', required=True)

  inspect_parser = subparsers.add_parser('inspect')
  inspect_parser.add_argument('--file', required=True)
  inspect_parser.add_argument('--snapshot')

  validate_parser = subparsers.add_parser('validate')
  validate_parser.add_argument('--file', required=True)
  validate_parser.add_argument('--session', required=True)
  validate_parser.add_argument('--snapshot', required=True)

  transform_parser = subparsers.add_parser('transform')
  transform_parser.add_argument('--file', required=True)
  transform_parser.add_argument('--session', required=True)
  transform_parser.add_argument('--snapshot', required=True)
  transform_parser.add_argument('--operations', required=True)
  transform_parser.add_argument('--release-lock', action='store_true')
  transform_parser.add_argument('--before-write-signal')

  tidy_parser = subparsers.add_parser('tidy')
  tidy_parser.add_argument('--file', required=True)
  tidy_parser.add_argument('--session', required=True)
  tidy_parser.add_argument('--snapshot', required=True)
  tidy_parser.add_argument('--release-lock', action='store_true')
  tidy_parser.add_argument('--before-write-signal')

  retire_parser = subparsers.add_parser('retire')
  retire_parser.add_argument('--file', required=True)
  retire_parser.add_argument('--archive-dir')
  retire_parser.add_argument('--archive-prefix')
  retire_parser.add_argument('--session', required=True)
  retire_parser.add_argument('--snapshot', required=True)
  retire_parser.add_argument('--older-than', required=True)
  retire_parser.add_argument('--as-of')
  retire_parser.add_argument('--release-lock', action='store_true')
  retire_parser.add_argument('--before-write-signal')

  company_parser = subparsers.add_parser('company-summary')
  company_parser.add_argument('--scan-home', default=str(Path('~/.claude').expanduser()))
  company_parser.add_argument('--work-root', default=str(Path('~/Desktop/work/acme').expanduser()))
  company_parser.add_argument('--json', action='store_true', dest='as_json')

  lint_parser = subparsers.add_parser('lint')
  lint_parser.add_argument('--scan-home', default=str(Path('~/.claude').expanduser()))
  lint_parser.add_argument('--work-root', default=str(Path('~/Desktop/work/acme').expanduser()))
  lint_parser.add_argument('--json', action='store_true', dest='as_json')

  bootstrap_parser = subparsers.add_parser('bootstrap')
  bootstrap_parser.add_argument('--file', required=True)

  args = parser.parse_args()
  if args.command == 'company-summary':
    summary = build_company_summary(args.scan_home, args.work_root)
    if args.as_json:
      print(json.dumps(summary, ensure_ascii=False))
    else:
      text = format_company_summary_text(summary)
      if text:
        print(text)
    return

  if args.command == 'lint':
    report = lint_friction_files(args.scan_home, args.work_root)
    if args.as_json:
      print(json.dumps(report, ensure_ascii=False))
    else:
      text = format_lint_summary_text(report)
      if text:
        print(text)
    return

  path = Path(args.file)
  if args.command == 'bootstrap':
    print(bootstrap_file(path))
    return

  if args.command == 'inspect':
    lines = path.read_text(encoding='utf-8').splitlines(keepends=True)
    pending_start, pending_end, closed_start, closed_title = find_sections(lines)
    dormant_start, _ = find_dormant_section(lines)
    print(f'pending_start={pending_start + 1}')
    print(f'pending_end={pending_end + 1}')
    print(f"dormant_start={dormant_start + 1 if dormant_start is not None else 'none'}")
    print(f'closed_start={closed_start + 1}')
    print(f'closed_title={closed_title}')
    if args.snapshot:
      saved = write_snapshot(args.snapshot, guarded_text(lines))
      print(f'snapshot={saved}')
    return

  expected_text = read_snapshot(args.snapshot)
  now = datetime.now(timezone.utc).replace(microsecond=0)
  if args.command == 'validate':
    lines = path.read_text(encoding='utf-8').splitlines(keepends=True)
    validate(lines, args.session, expected_text, now)
    print('VALID')
    return

  if args.command == 'retire':
    older_than = parse_age(args.older_than)
    as_of = parse_date(args.as_of) if args.as_of else now.date()
    archive_dir = Path(args.archive_dir).expanduser() if args.archive_dir else path.parent / 'archive'
    receipt = retire(
      path,
      args.session,
      expected_text,
      archive_dir,
      older_than,
      as_of,
      args.before_write_signal,
      args.archive_prefix,
    )
    if receipt['status'] == 'skipped':
      print('SKIPPED lock-active')
      return
    print(f"RETIRED entries={receipt['entries']}")
    for archive_path, count in sorted(receipt['archives'].items()):
      print(f'ARCHIVE {archive_path} entries={count}')
    return

  with acquire_stable_locks([source_lock_path(path)]):
    with path.open('r+', encoding='utf-8') as file:
      original_text = file.read()
      lines = original_text.splitlines(keepends=True)
      validate(lines, args.session, expected_text, now)
      if args.command == 'tidy':
        updated = tidy_pending_blanks(lines, args.release_lock)
      else:
        operations = json.loads(args.operations)
        if not isinstance(operations, list):
          raise ValueError('operations-not-list')
        updated = transform(lines, operations, args.release_lock)
      if args.before_write_signal:
        wait_before_write(args.before_write_signal)
      file.seek(0)
      current_text = file.read()
      if current_text != original_text:
        raise ValueError('concurrent-change')
      write_open_file(file, ''.join(updated))
  print('UPDATED')


if __name__ == '__main__':
  main()
