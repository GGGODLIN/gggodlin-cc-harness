#!/usr/bin/env python3
import argparse
import fcntl
from contextlib import contextmanager
import hashlib
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
  r'^- (?:\d{4}-\d{2}-\d{2} )?\[proposal_source=(?:anchor:duplicate-2|trial-review:file-3|user)@[^;\]]+; user_decision=(?:approved|rejected)@[^;\]]+; implementation=[^\]]+\] .+$'
)
PENDING_RECEIPT_RE = re.compile(
  r'^- (?:\d{4}-\d{2}-\d{2} )?\[pending_implementation proposal_source=(?:anchor:duplicate-2|trial-review:file-3|user)@[^;\]]+; user_decision=approved@[^;\]]+; implementation=N-A（等待公司側落地）\] .+$'
)
DORMANT_TITLE = '## 休眠'
DORMANT_RE = re.compile(
  r'^- (?:\d{4}-\d{2}-\d{2} )?.+ \[dormant since=\d{4}-\d{2}-\d{2}; wake-when=[^\]]+\]$'
)
ENTRY_RE = re.compile(r'^- (?P<date>\d{4}-\d{2}-\d{2})(?:\s|$)')
OLDER_THAN_RE = re.compile(r'^(?P<days>[1-9]\d*)d$')


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


def quarter_path(archive_dir, entry_date):
  quarter = (entry_date.month - 1) // 3 + 1
  return archive_dir / f'{entry_date.year}-Q{quarter}.md'


def archive_paths(archive_dir, entries):
  return sorted({quarter_path(archive_dir, entry['date']) for entry in entries}, key=str)


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


def pending_lines(lines):
  pending_start, pending_end, _, _ = find_sections(lines)
  return lines[pending_start + 1:pending_end]


def digest(lines):
  content = ''.join(line for line in pending_lines(lines) if not LOCK_RE.fullmatch(line.rstrip('\n')))
  return hashlib.sha256(content.encode()).hexdigest()


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


def validate(lines, session, expected_digest, now):
  lock = parse_lock(lines)
  if lock['session'] != session:
    raise ValueError('owner-mismatch')
  if lock['claimed_at'] > now:
    raise ValueError('claim-in-future')
  if lock['expires_at'] - lock['claimed_at'] != timedelta(hours=24):
    raise ValueError('invalid-lock-window')
  if lock['expires_at'] <= now:
    raise ValueError('lock-expired')
  if digest(lines) != expected_digest:
    raise ValueError('digest-mismatch')


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
  if action in {'approved', 'rejected', 'landed'} and not RECEIPT_RE.fullmatch(receipt):
    raise ValueError('invalid-receipt')
  if action == 'company-pending' and not PENDING_RECEIPT_RE.fullmatch(receipt):
    raise ValueError('invalid-pending-receipt')
  if action == 'dormant':
    # 休眠不是處置：不得帶 user_decision／proposal_source／implementation，否則會被誤計為已折入
    if not DORMANT_RE.fullmatch(receipt):
      raise ValueError('invalid-dormant-receipt')
    if any(token in receipt for token in ('user_decision=', 'proposal_source=', 'implementation=')):
      raise ValueError('dormant-carries-disposition')
    return append_dormant_item(replace_first_pending_item(lines, original, None), receipt)
  if action in {'approved', 'rejected', 'landed'}:
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


def build_archive_updates(archive_dir, entries):
  archive_dir = validate_archive_path(archive_dir, 'archive-dir-symlink')
  if archive_dir.is_symlink():
    raise ValueError('archive-dir-symlink')
  if archive_dir.exists() and not archive_dir.is_dir():
    raise ValueError('invalid-archive-dir')
  grouped = {}
  for entry in entries:
    grouped.setdefault(quarter_path(archive_dir, entry['date']), []).append(entry)
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


def retire(path, session, expected_digest, archive_dir, older_than, as_of, before_write_signal=None):
  archive_dir = validate_archive_path(archive_dir.expanduser(), 'archive-dir-symlink')
  archive_dir = archive_dir.resolve()
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
        validate(initial_lines, session, expected_digest, now)
        _, initial_selected = retire_lines(initial_lines, as_of - older_than)
        planned_archives = archive_paths(archive_dir, initial_selected)

      quarter_locks = [archive_file_lock_path(archive_path) for archive_path in planned_archives]
      with acquire_stable_locks(quarter_locks):
        with path.open('r+', encoding='utf-8') as file:
          original_text = file.read()
          lines = original_text.splitlines(keepends=True)
          now = datetime.now(timezone.utc).replace(microsecond=0)
          lock = parse_lock(lines)
          if lock['session'] != session and lock['expires_at'] > now:
            return {'status': 'skipped', 'reason': 'lock-active'}
          validate(lines, session, expected_digest, now)
          updated, selected = retire_lines(lines, as_of - older_than)
          current_archives = archive_paths(archive_dir, selected)
          if current_archives != planned_archives:
            continue
          updates = build_archive_updates(archive_dir, selected)
          if before_write_signal:
            wait_before_write(before_write_signal)
          file.seek(0)
          current_text = file.read()
          if current_text != original_text:
            raise ValueError('concurrent-change')
          validate(
            current_text.splitlines(keepends=True),
            session,
            expected_digest,
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


def main():
  parser = argparse.ArgumentParser()
  subparsers = parser.add_subparsers(dest='command', required=True)

  inspect_parser = subparsers.add_parser('inspect')
  inspect_parser.add_argument('--file', required=True)

  validate_parser = subparsers.add_parser('validate')
  validate_parser.add_argument('--file', required=True)
  validate_parser.add_argument('--session', required=True)
  validate_parser.add_argument('--digest', required=True)

  transform_parser = subparsers.add_parser('transform')
  transform_parser.add_argument('--file', required=True)
  transform_parser.add_argument('--session', required=True)
  transform_parser.add_argument('--digest', required=True)
  transform_parser.add_argument('--operations', required=True)
  transform_parser.add_argument('--release-lock', action='store_true')
  transform_parser.add_argument('--before-write-signal')

  tidy_parser = subparsers.add_parser('tidy')
  tidy_parser.add_argument('--file', required=True)
  tidy_parser.add_argument('--session', required=True)
  tidy_parser.add_argument('--digest', required=True)
  tidy_parser.add_argument('--release-lock', action='store_true')
  tidy_parser.add_argument('--before-write-signal')

  retire_parser = subparsers.add_parser('retire')
  retire_parser.add_argument('--file', required=True)
  retire_parser.add_argument('--archive-dir')
  retire_parser.add_argument('--session', required=True)
  retire_parser.add_argument('--digest', required=True)
  retire_parser.add_argument('--older-than', required=True)
  retire_parser.add_argument('--as-of')
  retire_parser.add_argument('--release-lock', action='store_true')
  retire_parser.add_argument('--before-write-signal')

  args = parser.parse_args()
  path = Path(args.file)

  if args.command == 'inspect':
    lines = path.read_text().splitlines(keepends=True)
    pending_start, pending_end, closed_start, closed_title = find_sections(lines)
    print(f'pending_start={pending_start + 1}')
    print(f'pending_end={pending_end + 1}')
    print(f'closed_start={closed_start + 1}')
    print(f'closed_title={closed_title}')
    print(f'digest={digest(lines)}')
    return

  now = datetime.now(timezone.utc).replace(microsecond=0)
  if args.command == 'validate':
    lines = path.read_text().splitlines(keepends=True)
    validate(lines, args.session, args.digest, now)
    print('VALID')
    return

  if args.command == 'retire':
    older_than = parse_age(args.older_than)
    as_of = parse_date(args.as_of) if args.as_of else now.date()
    archive_dir = Path(args.archive_dir).expanduser() if args.archive_dir else path.parent / 'archive'
    receipt = retire(
      path,
      args.session,
      args.digest,
      archive_dir,
      older_than,
      as_of,
      args.before_write_signal,
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
      validate(lines, args.session, args.digest, now)
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
