#!/usr/bin/env python3
import errno
import fcntl
import os
from pathlib import Path
import runpy
import signal
import sys


mode = sys.argv[1]
original_write = os.write
original_fsync = os.fsync
original_replace = os.replace
original_flock = fcntl.flock
flocks = [0]


def flock(fd, operation):
  flocks[0] += 1
  if mode == 'confirm-lock-busy' and flocks[0] == 2:
    raise BlockingIOError(errno.EAGAIN, 'injected confirm lock contention')
  return original_flock(fd, operation)


def stop():
  os.kill(os.getpid(), signal.SIGKILL)


def write(fd, data):
  if mode == 'write-error':
    raise OSError(errno.ENOSPC, 'injected write failure')
  if mode == 'partial-write':
    original_write(fd, bytes(data[:5]))
    stop()
  return original_write(fd, data)


def fsync(fd):
  original_fsync(fd)
  if mode == 'after-fsync':
    stop()


replacements = [0]


def replace(*args, **kwargs):
  replacements[0] += 1
  count = replacements[0]
  if mode == 'before-replace':
    stop()
  if mode == 'before-second-replace' and count == 2:
    stop()
  if mode == 'before-third-replace' and count == 3:
    stop()
  original_replace(*args, **kwargs)
  if mode == 'after-replace':
    stop()
  if mode == 'after-second-replace' and count == 2:
    stop()
  if mode == 'after-third-replace' and count == 3:
    stop()


os.write = write
os.fsync = fsync
os.replace = replace
fcntl.flock = flock
runpy.run_path(str(Path(__file__).resolve().parent / 'taskoutput-dedup-hook.py'), run_name='__main__')
