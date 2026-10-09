#!/usr/bin/env python3
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path('~/Desktop/projects/.claude')
HELPER = ROOT / 'hooks/trial-archive-resources.py'
ACTIVE = ROOT / 'trials/active.md'
PASS = 0


def check(condition, message):
  global PASS
  if not condition:
    raise AssertionError(message)
  PASS += 1
  print(f'PASS: {message}')


def expect_error(fn, message):
  try:
    fn()
  except ValueError:
    check(True, message)
    return
  check(False, message)


def expect_archive_failure(fn, message):
  try:
    fn()
  except (OSError, RuntimeError, ValueError):
    check(True, message)
    return
  check(False, message)


def load_helper():
  spec = importlib.util.spec_from_file_location('trial_archive_resources', HELPER)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def new_roots(base):
  roots = [base / 'home-trials', base / 'project-trials']
  for root in roots:
    root.mkdir(parents=True)
  return roots


def main():
  check(HELPER.exists(), 'trial archive helper exists')
  module = load_helper()
  temp_root = Path(tempfile.mkdtemp(prefix='trial-archive-test.'))
  try:
    roots = new_roots(temp_root / 'valid')
    source = roots[0] / 'sample-trial'
    source.mkdir()
    (source / 'snapshot.txt').write_text('evidence')
    receipt = module.archive_trial('sample-trial', roots)
    destination = roots[0] / 'archive/sample-trial'
    check(receipt['status'] == 'archived', 'valid trial returns archived receipt')
    check(not source.exists(), 'valid archive removes source path')
    check(destination.is_dir(), 'valid archive creates destination directory')
    check((destination / 'snapshot.txt').read_text() == 'evidence', 'valid archive preserves contents')
    check(receipt['source'] == str(source), 'receipt names exact source')
    check(receipt['destination'] == str(destination), 'receipt names exact destination')

    rewrite_roots = new_roots(temp_root / 'rewrite')
    rewrite_source = rewrite_roots[0] / 'rewrite-trial'
    rewrite_source.mkdir()
    rewrite_restore = rewrite_source / 'restore.sh'
    unrelated = '/absolute/keep/path'
    rewrite_restore.write_text(
      f"run cp '{rewrite_source}/snapshot/before' '{rewrite_source}/snapshot/after'\\n"
      f"run cp '{rewrite_source}-sibling/file' '{unrelated}'\\n"
      f"run cp '{rewrite_source}/../outside' '{unrelated}'\\n"
    )
    rewrite_receipt = module.archive_trial('rewrite-trial', rewrite_roots)
    rewrite_destination = rewrite_roots[0] / 'archive/rewrite-trial'
    rewritten = (rewrite_destination / 'restore.sh').read_text()
    check(rewrite_receipt['restore_rewritten'] is True, 'archive receipt reports restore rewrite')
    check(f"{rewrite_destination}/snapshot" in rewritten, 'restore rewrites moved trial paths')
    check(f"{rewrite_source}/snapshot" not in rewritten, 'restore removes old trial path references')
    check(f"{rewrite_source}-sibling/file" in rewritten, 'restore leaves similarly named paths unchanged')
    check(f"{rewrite_source}/../outside" in rewritten, 'restore leaves traversal paths unchanged')
    check(f"{rewrite_destination}/../outside" not in rewritten, 'restore does not relocate traversal paths')
    check(unrelated in rewritten, 'restore leaves unrelated absolute paths unchanged')

    shorthand_source = Path.home() / 'Desktop/projects/.claude/trials/shorthand-trial'
    shorthand_destination = Path.home() / 'Desktop/projects/.claude/trials/archive/shorthand-trial'
    shorthand_restore = temp_root / 'shorthand-restore.sh'
    shorthand_restore.write_text(
      "run cp '~/Desktop/projects/.claude/trials/shorthand-trial/snapshot' '$HOME/Desktop/projects/.claude/trials/shorthand-trial/file'\\n"
    )
    shorthand_changed = module.rewrite_restore_path(shorthand_restore, shorthand_source, shorthand_destination)
    shorthand_text = shorthand_restore.read_text()
    check(shorthand_changed is True, 'restore rewrites home shorthand paths')
    check('~/Desktop/projects/.claude/trials/archive/shorthand-trial/snapshot' in shorthand_text, 'restore preserves tilde shorthand')
    check('$HOME/Desktop/projects/.claude/trials/archive/shorthand-trial/file' in shorthand_text, 'restore preserves HOME shorthand')

    symlink_restore_roots = new_roots(temp_root / 'restore-symlink')
    symlink_restore_source = symlink_restore_roots[0] / 'symlink-restore-trial'
    symlink_restore_source.mkdir()
    external_restore = temp_root / 'external-restore.sh'
    external_content = f"run cp '{symlink_restore_source}/old' '{unrelated}'\\n"
    external_restore.write_text(external_content)
    (symlink_restore_source / 'restore.sh').symlink_to(external_restore)
    expect_archive_failure(lambda: module.archive_trial('symlink-restore-trial', symlink_restore_roots), 'symlink restore blocks archive')
    check(symlink_restore_source.is_dir(), 'symlink restore leaves source intact')
    check(external_restore.read_text() == external_content, 'symlink restore target is not modified')

    failure_roots = new_roots(temp_root / 'rename-failure')
    failure_source = failure_roots[0] / 'rename-failure-trial'
    failure_source.mkdir()
    failure_restore = failure_source / 'restore.sh'
    failure_original = f"run cp '{failure_source}/snapshot' '{unrelated}'\\n"
    failure_restore.write_text(failure_original)
    failure_archive = failure_roots[0] / 'archive'
    failure_archive.mkdir()
    failure_archive.chmod(0o500)
    try:
      expect_archive_failure(lambda: module.archive_trial('rename-failure-trial', failure_roots), 'rename failure returns error')
    finally:
      failure_archive.chmod(0o700)
    failure_destination = failure_archive / 'rename-failure-trial'
    check(failure_source.is_dir(), 'rename failure leaves source intact')
    check(not failure_destination.exists(), 'rename failure leaves destination absent')
    check(failure_restore.read_text() == failure_original, 'rename failure restores original restore script')

    absent_roots = new_roots(temp_root / 'absent')
    absent = module.archive_trial('missing-trial', absent_roots)
    check(absent['status'] == 'absent', 'missing resource returns absent receipt')
    check(absent['slug'] == 'missing-trial', 'absent receipt keeps requested slug')

    for slug in ['/', '.', '..', '../escape', 'nested/trial', 'trial..name', 'archive', '']:
      expect_error(lambda value=slug: module.archive_trial(value, absent_roots), f'invalid slug rejected: {slug!r}')

    duplicate_roots = new_roots(temp_root / 'duplicate')
    for root in duplicate_roots:
      (root / 'same-trial').mkdir()
    expect_error(lambda: module.archive_trial('same-trial', duplicate_roots), 'duplicate sources are rejected')
    check(all((root / 'same-trial').is_dir() for root in duplicate_roots), 'duplicate rejection leaves both sources intact')

    collision_roots = new_roots(temp_root / 'collision')
    collision_source = collision_roots[0] / 'collision-trial'
    collision_source.mkdir()
    collision_destination = collision_roots[0] / 'archive/collision-trial'
    collision_destination.mkdir(parents=True)
    expect_error(lambda: module.archive_trial('collision-trial', collision_roots), 'existing destination is rejected')
    check(collision_source.is_dir(), 'destination collision leaves source intact')

    symlink_roots = new_roots(temp_root / 'source-symlink')
    real_source = temp_root / 'real-source'
    real_source.mkdir()
    (symlink_roots[0] / 'linked-trial').symlink_to(real_source, target_is_directory=True)
    expect_error(lambda: module.archive_trial('linked-trial', symlink_roots), 'symlink source is rejected')
    check(real_source.is_dir(), 'symlink rejection leaves target intact')

    archive_link_roots = new_roots(temp_root / 'archive-symlink')
    archive_source = archive_link_roots[0] / 'archive-link-trial'
    archive_source.mkdir()
    external_archive = temp_root / 'external-archive'
    external_archive.mkdir()
    (archive_link_roots[0] / 'archive').symlink_to(external_archive, target_is_directory=True)
    expect_error(lambda: module.archive_trial('archive-link-trial', archive_link_roots), 'symlink archive root is rejected')
    check(archive_source.is_dir(), 'archive symlink rejection leaves source intact')

    invalid_cli = subprocess.run(
      [sys.executable, str(HELPER), '../escape'],
      capture_output=True,
      text=True,
      check=False,
    )
    check(invalid_cli.returncode != 0, 'CLI rejects traversal slug')

    active = ACTIVE.read_text()
    sop_start = active.index('## 結案 SOP')
    sop_end = active.index('\n## ', sop_start + 4)
    sop = active[sop_start:sop_end]
    check('trial-archive-resources.py <trial-slug>' in sop, 'active SOP calls the dedicated helper')
    check('mv ~/.claude/trials' not in sop, 'active SOP no longer asks Claude to move trial resources directly')
  finally:
    shutil.rmtree(temp_root, ignore_errors=True)

  print(json.dumps({'checks': PASS, 'status': 'pass'}, ensure_ascii=False))


if __name__ == '__main__':
  main()
