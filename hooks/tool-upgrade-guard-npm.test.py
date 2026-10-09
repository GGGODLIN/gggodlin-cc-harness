import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


HOOK = Path(__file__).with_name('tool-upgrade-guard.py')


class NpmPinTests(unittest.TestCase):
  def setUp(self):
    self.temp = tempfile.TemporaryDirectory()
    self.addCleanup(self.temp.cleanup)
    self.root = Path(self.temp.name)
    self.configs = [self.root / 'default.json', self.root / 'account.json']
    for path in self.configs:
      path.write_text(json.dumps({'mcpServers': {'chrome-devtools': {
        'command': 'npx', 'args': ['chrome-devtools-mcp@1.8.0', '--autoConnect']
      }}}))
    self.registry = self.root / 'notes.json'
    self.tool = {
      'aliases': ['chrome-devtools', 'chrome-devtools-mcp'],
      'mode': 'pinned',
      'pin_type': 'npm',
      'package': 'chrome-devtools-mcp',
      'server': 'chrome-devtools',
      'pin_files': [str(path) for path in self.configs],
      'report_note': '保留兩份 MCP 設定釘版'
    }

  def run_gate(self, command):
    self.registry.write_text(json.dumps({'schema_version': 1, 'tools': {
      'chrome-devtools': self.tool
    }}))
    before = {path: path.read_bytes() for path in self.configs if path.exists()}
    result = subprocess.run(
      ['python3', str(HOOK)],
      input=json.dumps({'tool_input': {'command': command}}),
      text=True, capture_output=True,
      env={**os.environ, 'TOOL_UPGRADE_NOTES': str(self.registry),
        'TOOL_UPGRADE_GUARD_OFF': str(self.root / 'off')},
      timeout=10
    )
    self.assertEqual(result.returncode, 0, result.stderr)
    for path, data in before.items():
      self.assertEqual(path.read_bytes(), data)
    return json.loads(result.stdout)['hookSpecificOutput'] if result.stdout else {}

  def test_unrelated_upgrade_with_npm_pin_is_allowed(self):
    output = self.run_gate('uv tool upgrade graphifyy')
    self.assertNotEqual(output.get('permissionDecision'), 'deny', output)

  def test_matching_npm_version_is_allowed(self):
    output = self.run_gate('npm install -g chrome-devtools-mcp@1.8.0')
    self.assertNotEqual(output.get('permissionDecision'), 'deny', output)
    self.assertIn('保留兩份', output.get('additionalContext', ''))

  def test_hold_blocks_even_matching_version(self):
    self.tool['hold_until'] = '9999-12-31'
    output = self.run_gate('npm install -g chrome-devtools-mcp@1.8.0')
    self.assertEqual(output.get('permissionDecision'), 'deny', output)
    self.assertIn('9999-12-31', output.get('permissionDecisionReason', ''))

  def test_wrong_or_unspecified_npm_version_is_denied(self):
    for target in ['chrome-devtools-mcp@1.9.0', 'chrome-devtools-mcp',
      'chrome-devtools-mcp@latest', 'chrome-devtools-mcp@^1.8.0']:
      with self.subTest(target=target):
        output = self.run_gate('npm install -g ' + target)
        self.assertEqual(output.get('permissionDecision'), 'deny', output)

  def test_disagreeing_config_versions_are_denied(self):
    self.configs[1].write_text(self.configs[1].read_text().replace('@1.8.0', '@1.9.0'))
    output = self.run_gate('npm install -g chrome-devtools-mcp@1.8.0')
    self.assertEqual(output.get('permissionDecision'), 'deny', output)
    self.assertIn('不一致', output.get('permissionDecisionReason', ''))

  def test_missing_config_is_denied(self):
    self.configs[1].unlink()
    output = self.run_gate('npm install -g chrome-devtools-mcp@1.8.0')
    self.assertEqual(output.get('permissionDecision'), 'deny', output)

  def test_pin_update_uses_both_current_configs(self):
    for path in self.configs:
      path.write_text(path.read_text().replace('@1.8.0', '@1.9.0'))
    output = self.run_gate('npm install -g chrome-devtools-mcp@1.9.0')
    self.assertNotEqual(output.get('permissionDecision'), 'deny', output)
    output = self.run_gate('npm install -g chrome-devtools-mcp@1.8.0')
    self.assertEqual(output.get('permissionDecision'), 'deny', output)

  def test_hold_includes_today_and_expired_hold_allows_pin(self):
    from datetime import date
    self.tool['hold_until'] = date.today().isoformat()
    output = self.run_gate('npm install -g chrome-devtools-mcp@1.8.0')
    self.assertEqual(output.get('permissionDecision'), 'deny', output)
    self.tool['hold_until'] = '2000-01-01'
    output = self.run_gate('npm install -g chrome-devtools-mcp@1.8.0')
    self.assertNotEqual(output.get('permissionDecision'), 'deny', output)

  def test_invalid_hold_fails_closed(self):
    for hold in ['tomorrow', '2026-02-30', None, 123]:
      with self.subTest(hold=hold):
        self.tool['hold_until'] = hold
        output = self.run_gate('npm install -g chrome-devtools-mcp@1.8.0')
        self.assertEqual(output.get('permissionDecision'), 'deny', output)

  def test_invalid_npm_schema_fails_closed(self):
    for field in ['package', 'server', 'pin_files']:
      with self.subTest(field=field):
        value = self.tool.pop(field)
        output = self.run_gate('uv tool upgrade graphifyy')
        self.assertEqual(output.get('permissionDecision'), 'deny', output)
        self.tool[field] = value
    self.tool['pin_type'] = 'unknown'
    output = self.run_gate('uv tool upgrade graphifyy')
    self.assertEqual(output.get('permissionDecision'), 'deny', output)

  def test_pin_source_symlink_is_denied(self):
    target = self.root / 'actual.json'
    self.configs[1].rename(target)
    self.configs[1].symlink_to(target)
    output = self.run_gate('npm install -g chrome-devtools-mcp@1.8.0')
    self.assertEqual(output.get('permissionDecision'), 'deny', output)

  def test_recovery_is_only_fixture_local(self):
    self.tool['hold_until'] = '9999-12-31'
    (self.root / 'off').touch()
    output = self.run_gate('npm install -g chrome-devtools-mcp@1.9.0')
    self.assertEqual(output, {})


if __name__ == '__main__':
  unittest.main()
