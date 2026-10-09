from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / 'check-decisions'


def write_decision(directory: Path, name: str, content: str) -> Path:
  path = directory / name
  path.write_text(content, encoding='utf-8')
  return path


def decision_bytes(directory: Path) -> dict[str, bytes]:
  return {
    path.name: path.read_bytes()
    for path in sorted(directory.iterdir())
    if path.is_file()
  }


def run_checker(*args: str) -> subprocess.CompletedProcess[str]:
  return subprocess.run(
    [str(SCRIPT), *args],
    capture_output=True,
    text=True,
    check=False,
  )


class CheckDecisionsTests(unittest.TestCase):
  def test_missing_supersedes_target_returns_exit_one_with_diagnostic(self):
    with tempfile.TemporaryDirectory() as root:
      decisions = Path(root)
      write_decision(
        decisions,
        '0001-source.md',
        '---\nsupersedes: [0002]\n---\n# Source\n',
      )
      result = run_checker(str(decisions))

    self.assertEqual(result.returncode, 1)
    self.assertEqual(
      result.stdout,
      '0001-source.md:supersedes:0002: missing numbered ADR\n',
    )
    self.assertEqual(result.stderr, '')

  def test_missing_superseded_by_and_status_targets_return_exit_one(self):
    with tempfile.TemporaryDirectory() as root:
      decisions = Path(root)
      write_decision(
        decisions,
        '0003-structured.md',
        '---\nsuperseded_by: 0009\n---\n# Structured\n',
      )
      write_decision(
        decisions,
        '0002-status.md',
        '---\nstatus: superseded by ADR-0008\n---\n# Status\n',
      )
      result = run_checker(str(decisions))

    self.assertEqual(result.returncode, 1)
    self.assertEqual(
      result.stdout,
      '0002-status.md:status:ADR-0008: missing numbered ADR\n'
      '0003-structured.md:superseded_by:0009: missing numbered ADR\n',
    )
    self.assertEqual(result.stderr, '')

  def test_non_numeric_structured_and_status_targets_are_invalid(self):
    with tempfile.TemporaryDirectory() as root:
      decisions = Path(root)
      write_decision(
        decisions,
        '0001-invalid-targets.md',
        '---\nsupersedes: [change-slug]\n'
        'status: superseded by ADR-change-slug\n---\n# Invalid targets\n',
      )
      result = run_checker(str(decisions))

    self.assertEqual(result.returncode, 1)
    self.assertEqual(
      result.stdout,
      '0001-invalid-targets.md:status:ADR-change-slug: missing numbered ADR\n'
      '0001-invalid-targets.md:supersedes:change-slug: missing numbered ADR\n',
    )
    self.assertEqual(result.stderr, '')

  def test_invocation_io_and_malformed_frontmatter_return_exit_two(self):
    with tempfile.TemporaryDirectory() as root:
      directory = Path(root)
      missing = run_checker(str(directory / 'missing'))
      write_decision(
        directory,
        '0001-malformed.md',
        '---\nsupersedes: [0002]\n# Missing closing delimiter\n',
      )
      malformed = run_checker(str(directory))
      missing_source = run_checker(
        str(directory),
        str(directory / '9999-missing.md'),
      )
      nested = directory / 'nested'
      nested.mkdir()
      nested_source = write_decision(nested, '0002-nested.md', '# Nested\n')
      outside_source = run_checker(str(directory), str(nested_source))
      invocation = run_checker()

    for result in (
      missing,
      malformed,
      missing_source,
      outside_source,
      invocation,
    ):
      with self.subTest(args=result.args):
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, '')
        self.assertNotEqual(result.stderr, '')
        self.assertNotIn('Traceback', result.stderr)

  def test_valid_and_plain_sources_pass_and_explicit_sources_are_isolated(self):
    with tempfile.TemporaryDirectory() as root:
      decisions = Path(root)
      write_decision(decisions, '0001-plain.md', '# Plain\n')
      write_decision(
        decisions,
        '0002-unrelated.md',
        '---\nowner: architecture\n---\n# Unrelated\n',
      )
      write_decision(decisions, '0003-target.md', '# Target\n')
      structured = write_decision(
        decisions,
        '0004-valid-structured.md',
        '---\nsupersedes: [0003]\nsuperseded_by: null\n---\n# Valid\n',
      )
      write_decision(
        decisions,
        '0005-valid-status.md',
        '---\nstatus: superseded by ADR-0003\n---\n# Valid status\n',
      )
      write_decision(
        decisions,
        '0006-status-only.md',
        '---\nstatus: superseded\n---\n# No target required\n',
      )
      orientation = write_decision(
        decisions,
        'README.md',
        '---\nsuperseded_by: 9998\n---\n# Orientation\n',
      )
      all_valid = run_checker(str(decisions))
      write_decision(
        decisions,
        '0007-legacy-broken.md',
        '---\nsuperseded_by: 9999\n---\n# Legacy violation\n',
      )
      selected = run_checker(str(decisions), str(structured))
      selected_orientation = run_checker(str(decisions), str(orientation))

    for result in (all_valid, selected, selected_orientation):
      with self.subTest(args=result.args):
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertEqual(result.stderr, '')

  def test_supersedes_accepts_block_sequence(self):
    with tempfile.TemporaryDirectory() as root:
      decisions = Path(root)
      write_decision(decisions, '0001-target.md', '# Target\n')
      write_decision(
        decisions,
        '0002-block-list.md',
        '---\nsupersedes:\n  - 0001\n---\n# Valid grammar\n',
      )
      result = run_checker(str(decisions))

    self.assertEqual(result.returncode, 0)
    self.assertEqual(result.stdout, '')
    self.assertEqual(result.stderr, '')

  def test_orientation_fences_change_slug_and_diagnostics_are_deterministic(self):
    with tempfile.TemporaryDirectory() as root:
      decisions = Path(root)
      write_decision(
        decisions,
        'README.md',
        '---\nsuperseded_by: 9999\n---\n```md\nsupersedes: [9998]\n```\n',
      )
      write_decision(
        decisions,
        '0001-fenced.md',
        '# Example\n```md\n---\nsuperseded_by: 9997\n---\n```\n',
      )
      write_decision(decisions, '0002.md', '# Not a numbered ADR target\n')
      write_decision(
        decisions,
        '0003-change-slug.md',
        '---\nsuperseded_by: replace-order-discounts\n---\n# Broken successor\n',
      )
      write_decision(
        decisions,
        '0004-order.md',
        '---\nsupersedes: [0009, 0002, 0008]\n'
        'status: superseded by ADR-0006\n---\n# Ordering\n',
      )
      result = run_checker(str(decisions))

    self.assertEqual(result.returncode, 1)
    self.assertEqual(
      result.stdout,
      '0003-change-slug.md:superseded_by:replace-order-discounts: missing numbered ADR\n'
      '0004-order.md:status:ADR-0006: missing numbered ADR\n'
      '0004-order.md:supersedes:0002: missing numbered ADR\n'
      '0004-order.md:supersedes:0008: missing numbered ADR\n'
      '0004-order.md:supersedes:0009: missing numbered ADR\n',
    )
    self.assertEqual(result.stderr, '')

  def test_checker_is_read_only_and_leaves_non_v1_invariants_unchecked(self):
    with tempfile.TemporaryDirectory() as root:
      decisions = Path(root)
      unchecked = write_decision(
        decisions,
        '0001-unchecked-invariants.md',
        '---\nsupersedes: [0001, 0002, 0002]\n'
        'superseded_by: 0002\nstatus: accepted\n---\n# Unchecked\n',
      )
      write_decision(decisions, '0002-target-without-reciprocity.md', '# Target\n')
      broken = write_decision(
        decisions,
        '0003-broken.md',
        '---\nsuperseded_by: 9999\n---\n# Broken\n',
      )
      before = decision_bytes(decisions)
      unchecked_result = run_checker(str(decisions), str(unchecked))
      broken_result = run_checker(str(decisions), str(broken))
      after = decision_bytes(decisions)

    self.assertEqual(unchecked_result.returncode, 0)
    self.assertEqual(unchecked_result.stdout, '')
    self.assertEqual(unchecked_result.stderr, '')
    self.assertEqual(broken_result.returncode, 1)
    self.assertIn('0003-broken.md:superseded_by:9999', broken_result.stdout)
    self.assertEqual(before, after)

  def test_symlinked_numbered_target_outside_directory_is_not_accepted(self):
    with tempfile.TemporaryDirectory() as root:
      base = Path(root)
      decisions = base / 'decisions'
      decisions.mkdir()
      outside = write_decision(base, 'outside.md', '# Outside\n')
      write_decision(
        decisions,
        '0001-source.md',
        '---\nsupersedes: [0002]\n---\n# Source\n',
      )
      (decisions / '0002-target.md').symlink_to(outside)
      result = run_checker(str(decisions))

    self.assertEqual(result.returncode, 1)
    self.assertEqual(
      result.stdout,
      '0001-source.md:supersedes:0002: missing numbered ADR\n',
    )
    self.assertEqual(result.stderr, '')

  def test_deep_yaml_recursion_returns_exit_two_without_traceback(self):
    with tempfile.TemporaryDirectory() as root:
      decisions = Path(root)
      nested = ''.join(f'{"  " * depth}level:\n' for depth in range(500))
      nested += f'{"  " * 500}value: true\n'
      write_decision(
        decisions,
        '0001-deep.md',
        f'---\n{nested}---\n# Deep\n',
      )
      result = run_checker(str(decisions))

    self.assertEqual(result.returncode, 2)
    self.assertEqual(result.stdout, '')
    self.assertNotIn('Traceback', result.stderr)

  def test_duplicate_lifecycle_key_returns_exit_two(self):
    with tempfile.TemporaryDirectory() as root:
      decisions = Path(root)
      write_decision(decisions, '0001-target.md', '# Target\n')
      write_decision(
        decisions,
        '0002-duplicate.md',
        '---\nsupersedes: [0001]\nsupersedes: [9999]\n---\n# Duplicate\n',
      )
      result = run_checker(str(decisions))

    self.assertEqual(result.returncode, 2)
    self.assertEqual(result.stdout, '')
    self.assertIn('duplicate lifecycle key: supersedes', result.stderr)
    self.assertNotIn('Traceback', result.stderr)


if __name__ == '__main__':
  unittest.main()
