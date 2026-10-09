#!/bin/sh
set -eu
python3 - "$(dirname "$0")/better-rm-env.sh" <<'PY'
import os
from pathlib import Path
import subprocess
import sys
import tempfile

hook = str(Path(sys.argv[1]).resolve())
with tempfile.TemporaryDirectory(prefix='better-rm-env-test-') as directory:
  root = Path(directory)
  home = root / 'home with spaces'
  prefix = home / '.local/share/better-rm/bin'
  prefix.mkdir(parents=True)
  shim = prefix / 'rm'
  shim.write_text('#!/bin/sh\nexit 77\n')
  shim.chmod(0o755)
  base = dict(os.environ, HOME=str(home), PATH='/usr/bin:/bin')
  base.pop('CLAUDE_ENV_FILE', None)
  def invoke(target=None):
    env = dict(base)
    if target is not None:
      env['CLAUDE_ENV_FILE'] = str(target)
    return subprocess.run(['/bin/sh', hook], env=env, capture_output=True, text=True, timeout=3)
  assert invoke().returncode == 0
  envfile = root / 'env'
  assert invoke(envfile).returncode == 0
  command = '. "$1"; . "$1"; command -v rm; printf "%s\n" "$PATH"'
  result = subprocess.run(['/bin/sh', '-c', command, 'probe', str(envfile)], env=base, capture_output=True, text=True, check=True)
  lines = result.stdout.splitlines()
  assert lines[0] == str(shim)
  assert lines[1].split(':').count(str(prefix)) == 1
  envfile.write_text('export PRESERVE_ME=yes\n')
  assert invoke(envfile).returncode == 0
  assert envfile.read_text().startswith('export PRESERVE_ME=yes\n')
  protected = root / 'protected'
  protected.write_text('untouched\n')
  symlink = root / 'symlink'
  symlink.symlink_to(protected)
  assert invoke(symlink).returncode != 0
  hardlink = root / 'hardlink'
  os.link(protected, hardlink)
  assert invoke(hardlink).returncode != 0
  fifo = root / 'fifo'
  os.mkfifo(fifo)
  assert invoke(fifo).returncode != 0
  assert protected.read_text() == 'untouched\n'
  ordinary = subprocess.run(['/bin/sh', '-c', 'command -v rm'], env=base, capture_output=True, text=True, check=True)
  assert ordinary.stdout.strip() != str(shim)
  print('BETTER_RM_ENV_TESTS_PASS: unset, bootstrap, repeated-source, preserve-existing, symlink, hardlink, fifo, non-agent')
PY
