#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path
import re
import sys

DEFAULT_ROOTS = (
  Path.home() / '.claude/trials',
  Path.home() / 'Desktop/projects/.claude/trials',
)
SLUG = re.compile(r'^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$')


def validate_slug(slug):
  if not isinstance(slug, str) or not SLUG.fullmatch(slug) or '..' in slug or slug == 'archive':
    raise ValueError('invalid-trial-slug')


def inspect_root(root):
  root = Path(root).expanduser()
  if root.is_symlink():
    raise ValueError(f'symlink-trial-root:{root}')
  if not root.exists():
    return None
  if not root.is_dir():
    raise ValueError(f'invalid-trial-root:{root}')
  return root


def rewrite_restore_path(restore_path, source, destination):
  if restore_path.is_symlink():
    raise ValueError(f'symlink-restore:{restore_path}')
  if not restore_path.is_file():
    return False
  original = restore_path.read_text()
  source_root = Path(os.path.normpath(str(source)))
  aliases = [(str(source), str(destination))]
  home = Path.home()
  try:
    source_relative = source.relative_to(home)
    destination_relative = destination.relative_to(home)
  except ValueError:
    pass
  else:
    for prefix in ('~', '$HOME', '${HOME}'):
      aliases.append(
        (
          f'{prefix}/{source_relative.as_posix()}',
          f'{prefix}/{destination_relative.as_posix()}',
        )
      )

  path_suffix = r'''[^\s'"`)\]}:,;#]*'''

  def rewrite_alias(text, source_alias, destination_alias):
    old = re.escape(source_alias)
    pattern = re.compile(
      r'''(?<![A-Za-z0-9_.-])(?P<path>''' + old + r'''(?P<suffix>/''' + path_suffix + r''')?)(?=$|[\s'"`)\]}:,;#])'''
    )

    def replace_path(match):
      token = match.group('path')
      expanded = token
      if token.startswith('~/'):
        expanded = str(home / token[2:])
      elif token.startswith('$HOME/'):
        expanded = str(home / token[6:])
      elif token.startswith('${HOME}/'):
        expanded = str(home / token[8:])
      candidate = Path(os.path.normpath(expanded))
      try:
        candidate.relative_to(source_root)
      except ValueError:
        return token
      return destination_alias + (match.group('suffix') or '')

    return pattern.sub(replace_path, text)

  rewritten = original
  for source_alias, destination_alias in aliases:
    rewritten = rewrite_alias(rewritten, source_alias, destination_alias)
  if rewritten == original:
    return False
  restore_path.write_text(rewritten)
  return True


def archive_trial(slug, roots=None):
  validate_slug(slug)
  values = roots if roots is not None else DEFAULT_ROOTS
  checked_roots = [root for root in (inspect_root(value) for value in values) if root is not None]
  sources = []
  destinations = []

  for root in checked_roots:
    source = root / slug
    archive_root = root / 'archive'
    destination = archive_root / slug

    if source.is_symlink():
      raise ValueError(f'symlink-source:{source}')
    if source.exists():
      if not source.is_dir():
        raise ValueError(f'invalid-source:{source}')
      sources.append((source, archive_root, destination))

    if archive_root.is_symlink():
      raise ValueError(f'symlink-archive-root:{archive_root}')
    if archive_root.exists() and not archive_root.is_dir():
      raise ValueError(f'invalid-archive-root:{archive_root}')
    if destination.exists() or destination.is_symlink():
      destinations.append(destination)

  if len(sources) > 1:
    raise ValueError('ambiguous-trial-source')
  if destinations:
    raise ValueError(f'destination-exists:{destinations[0]}')
  if not sources:
    return {
      'status': 'absent',
      'slug': slug,
      'roots_checked': [str(root) for root in checked_roots],
    }

  source, archive_root, destination = sources[0]
  restore_path = source / 'restore.sh'
  if restore_path.is_symlink():
    raise ValueError(f'symlink-restore:{restore_path}')
  restore_original = restore_path.read_bytes() if restore_path.is_file() else None
  archive_root.mkdir(mode=0o700, parents=False, exist_ok=True)
  source.rename(destination)

  try:
    restore_rewritten = rewrite_restore_path(destination / 'restore.sh', source, destination)
    if source.exists() or source.is_symlink() or not destination.is_dir() or destination.is_symlink():
      raise RuntimeError('archive-verification-failed')
  except (OSError, RuntimeError, ValueError):
    if destination.exists() and not source.exists():
      destination.rename(source)
    if restore_original is not None:
      (source / 'restore.sh').write_bytes(restore_original)
    raise

  return {
    'status': 'archived',
    'slug': slug,
    'source': str(source),
    'destination': str(destination),
    'restore_rewritten': restore_rewritten,
  }


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument('trial_slug')
  args = parser.parse_args()
  try:
    receipt = archive_trial(args.trial_slug)
  except (OSError, RuntimeError, ValueError) as error:
    print(json.dumps({
      'status': 'error',
      'slug': args.trial_slug,
      'error': str(error),
    }, ensure_ascii=False, sort_keys=True), file=sys.stderr)
    return 1
  print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
  return 0


if __name__ == '__main__':
  raise SystemExit(main())
