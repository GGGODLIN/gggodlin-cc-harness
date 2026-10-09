import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

RUNNER = Path(__file__).with_name('ticket-yagni-runner.py')


class TicketFileTests(unittest.TestCase):
  def test_explicit_ticket_wins_over_newer_same_number(self):
    with tempfile.TemporaryDirectory() as temporary:
      root = Path(temporary)
      repo = root / 'repo'
      repo.mkdir()
      subprocess.run(['git', '-C', str(repo), 'init', '-q'], check=True)
      base = subprocess.run(['git', '-C', str(repo), 'hash-object', '-w', '-t', 'tree', '--stdin'], input='', text=True, capture_output=True, check=True).stdout.strip()
      correct = repo / '.scratch/experiment/issues/01-environment.md'
      wrong = repo / '.scratch/old-task/issues/01-material.md'
      for path, text in [(correct, '# Environment ticket\n'), (wrong, '# Material ticket\n')]:
        path.parent.mkdir(parents=True)
        path.write_text(text)
      os.utime(correct, (1, 1))
      os.utime(wrong, (2, 2))
      original = {path: path.read_bytes() for path in (correct, wrong)}
      output = root / 'output'
      result = subprocess.run([sys.executable, str(RUNNER), '--session', 'fixture', '--run', 'fixture-run', '--ticket', '01', '--ticket-file', str(correct), '--worktree', str(repo), '--base', base, '--out', str(output), '--dry-run'], capture_output=True, text=True)
      self.assertEqual(result.returncode, 0, result.stderr)
      packet = (output / 'packet.md').read_text().split('## 待審 item 清單')[0]
      self.assertIn('# Environment ticket', packet)
      self.assertNotIn('# Material ticket', packet)
      self.assertEqual(json.loads(result.stdout)['ticket_file'], str(correct.resolve()))
      for path, content in original.items():
        self.assertEqual(path.read_bytes(), content)

  def test_invalid_explicit_path_does_not_fall_back(self):
    with tempfile.TemporaryDirectory() as temporary:
      root = Path(temporary)
      issues = root / '.scratch/feature/issues'
      issues.mkdir(parents=True)
      valid = issues / '01-valid.md'
      valid.write_text('# Valid fallback must not be selected\n')
      wrong = issues / '02-other.md'
      wrong.write_text('# Wrong ticket\n')
      fifo = issues / '01-pipe.md'
      os.mkfifo(fifo)
      misplaced = root / '01-not-an-issue.md'
      misplaced.write_text('# Wrong directory\n')
      for index, path in enumerate([wrong, issues / '01-missing.md', fifo, misplaced]):
        with self.subTest(path=path.name):
          output = root / str(index)
          result = subprocess.run([sys.executable, str(RUNNER), '--session', 'fixture', '--run', 'fixture-run', '--ticket', '01', '--ticket-file', str(path), '--worktree', str(root), '--base', 'HEAD', '--out', str(output), '--dry-run'], capture_output=True, text=True, timeout=5)
          self.assertEqual(result.returncode, 1, result.stderr)
          self.assertIn('explicit ticket file', json.loads((output / 'error.json').read_text())['error'])
          self.assertFalse((output / 'packet.md').exists())
      self.assertEqual(valid.read_text(), '# Valid fallback must not be selected\n')
      self.assertEqual(wrong.read_text(), '# Wrong ticket\n')


if __name__ == '__main__':
  unittest.main()
