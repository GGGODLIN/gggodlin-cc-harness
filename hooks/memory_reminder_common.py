#!/usr/bin/env python3
"""Shared reminder text and injection state; never writes memory or runs Git."""
import argparse
from contextlib import contextmanager
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import sys

REFRESH_WINDOW = 50
SESSION_RE = re.compile(r'[A-Za-z0-9_-]{1,128}\Z')
CONTROL_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u202a-\u202e\u2066-\u2069\u200e\u200f]')


class SafeDirectory:
  def __init__(self, path):
    home = Path.home()
    relative = Path(path).relative_to(home)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(home.resolve(), flags)
    try:
      for part in relative.parts:
        if part in ('.', '..'):
          raise ValueError('invalid_directory')
        try:
          child = os.open(part, flags, dir_fd=fd)
        except FileNotFoundError:
          try:
            os.mkdir(part, 0o700, dir_fd=fd)
          except FileExistsError:
            pass
          child = os.open(part, flags, dir_fd=fd)
        os.close(fd)
        fd = child
      if os.fstat(fd).st_uid != os.getuid():
        raise ValueError('foreign_directory')
      self.fd = fd
    except Exception:
      os.close(fd)
      raise

  def __enter__(self):
    return self

  def __exit__(self, *_):
    os.close(self.fd)

  def open(self, name, flags):
    if not name or '/' in name or name in ('.', '..'):
      raise ValueError('invalid_filename')
    fd = os.open(name, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=self.fd)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
      os.close(fd)
      raise ValueError('unsafe_file')
    return fd

  def read_info(self, name):
    try:
      fd = self.open(name, os.O_RDONLY)
    except FileNotFoundError:
      return None, 0
    try:
      info = os.fstat(fd)
      if info.st_size > 1048576:
        raise ValueError('oversized_state')
      return os.read(fd, 1048577).decode(), info.st_mtime
    finally:
      os.close(fd)

  def read(self, name):
    return self.read_info(name)[0]

  def write(self, name, text, append=False):
    flags = os.O_WRONLY | os.O_CREAT | (os.O_APPEND if append else 0)
    fd = self.open(name, flags)
    try:
      fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
      os.fchmod(fd, 0o600)
      if not append:
        os.ftruncate(fd, 0)
      payload = text.encode()
      while payload:
        written = os.write(fd, payload)
        if written <= 0:
          raise OSError('short_write')
        payload = payload[written:]
    finally:
      os.close(fd)

  @contextmanager
  def lock(self, name):
    fd = self.open(name, os.O_RDWR | os.O_CREAT)
    try:
      fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
      yield
    finally:
      os.close(fd)


def state_directory():
  return Path.home() / '.claude/hooks/state'


def rule_file():
  return Path.home() / '.claude/memory/feedback_memory_cluster_maintenance.md'


def last_long(session, turns, transcript):
  try:
    if not SESSION_RE.fullmatch(session):
      return 0
    with SafeDirectory(state_directory()) as directory:
      text, modified = directory.read_info('long_injected_' + session)
    value = int(text or 0)
    if not 0 < value <= turns or rule_file().stat().st_mtime > modified:
      return 0
    with open(transcript, encoding='utf8') as source:
      for line in source:
        if 'compact_boundary' not in line:
          continue
        entry = json.loads(line)
        if entry.get('type') == 'system' and entry.get('subtype') == 'compact_boundary':
          timestamp = datetime.fromisoformat(entry['timestamp'].replace('Z', '+00:00')).timestamp()
          if timestamp >= modified:
            return 0
    return value
  except Exception:
    return 0


def tier1():
  try:
    text = rule_file().read_text()
    start = text.index('## Tier 1:')
    end = text.index('## Tier 3:', start)
    return CONTROL_RE.sub('', text[start:end].rstrip())
  except Exception:
    return ''


def mark_long(session, turns):
  if not SESSION_RE.fullmatch(session) or turns < 1:
    raise ValueError('invalid_injection_identity')
  if not tier1():
    return False
  with SafeDirectory(state_directory()) as directory:
    directory.write('long_injected_' + session, str(turns) + '\n')
  return True


def reminder(version, prefix, previous=0, automatic=False):
  if version == 'long':
    tier = tier1() or '(Tier 1 段抽不到、請先讀 ' + str(rule_file()) + ' 的 Tier 1)'
    message = f'''{prefix}

先檢索既有 memory 與 index；相同主題優先更新／合併，沒有新資訊就略過，不因提醒而硬建新檔。
按內容型別路由：feedback (工作習慣/糾正/確認過的做法、附 Why+How to apply) / reference (跨任務可轉移事實/坑/工具行為) / project (進行中專案脈絡/目標) / user (本人角色/偏好/處境)。決策連 rationale 一起記。精確值 (DSN/port/seed/完整命令列/路徑/version pin) 逐字保存不准摘要改寫。

──────── 寫前必看規範（動態載入自 feedback_memory_cluster_maintenance.md Tier 1 段）────────

{tier}

──────── 絕對不做 ────────
- 直接 append MEMORY.md 跳過 cluster check
- 漏 bump cluster frontmatter (N entries) → 造 audit C mismatch
- 建新 cluster 沒在 MEMORY.md 加 pointer → cluster orphan
- \\n-prefix 增量 Edit MEMORY.md（會串接相鄰 entry）
- 精確值摘要改寫'''
  else:
    history = (f'【完整規範上次送出 @ turn {previous}；若 context 已不保留，先讀 Tier 1】'
               if previous else '【尚無有效完整版注入紀錄；寫前先讀 feedback_memory_cluster_maintenance.md 的 Tier 1】')
    message = f'''{prefix}

{history}

寫前 checklist：
- 先查既有 memory／index，相同主題更新／合併；沒有新資訊就略過
- type 路由 (feedback/reference/project/user)，先判 scope
- cluster check 對 MEMORY.md `### Cluster indexes` 段
- 跨 cluster cross-link (grep _index_*.md 看別處對位)
- bump cluster frontmatter (N entries)
- 決策保留 rationale，精確值逐字保存'''
  empty = ('這只是上一回合的可選提醒，不是寫入授權；本輪使用者要求優先。沒有候選就略過此 check，繼續本輪，不必額外回 skip。'
           if automatic else '沒東西要記 → 只回 "skip" 一字、不要解釋。')
  return CONTROL_RE.sub('', message + '\n\n' + empty)


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument('mode', choices=('long', 'short', 'last-long', 'mark-long'))
  parser.add_argument('--prefix', default='')
  parser.add_argument('--session', default='')
  parser.add_argument('--turns', type=int, default=0)
  parser.add_argument('--transcript', default='')
  parser.add_argument('--last-long', type=int, default=0)
  args = parser.parse_args()
  if args.mode == 'last-long':
    print(last_long(args.session, args.turns, args.transcript))
  elif args.mode == 'mark-long':
    mark_long(args.session, args.turns)
  else:
    print(json.dumps(reminder(args.mode, args.prefix, args.last_long), ensure_ascii=False))


if __name__ == '__main__':
  try:
    main()
  except Exception:
    sys.exit(1)
