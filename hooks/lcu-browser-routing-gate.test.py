#!/usr/bin/env python3
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / 'hooks/lcu-browser-routing-gate.py'


class LcuBrowserRoutingGateTest(unittest.TestCase):
  def setUp(self):
    self.temp_root = Path(tempfile.mkdtemp(prefix='lcu-gate-test.'))
    self.audit = self.temp_root / 'audit.jsonl'
    self.untouched = self.temp_root / 'untouched.txt'
    self.untouched.write_text('keep-me', encoding='utf-8')

  def tearDown(self):
    shutil.rmtree(self.temp_root, ignore_errors=True)

  def run_hook(self, code, tool_name='mcp__lcu__js', extra_env=None):
    env = {
      'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
      'HOME': os.environ.get('HOME', str(self.temp_root)),
      'LCU_ROUTING_GATE_AUDIT': str(self.audit),
    }
    if extra_env:
      env.update(extra_env)
    payload = {
      'hook_event_name': 'PreToolUse',
      'session_id': 'lcu-test-session',
      'tool_name': tool_name,
      'tool_input': {'code': code} if code is not None else {'completion_summary': 'Checked page'},
    }
    res = subprocess.run(
      [sys.executable, '-I', str(HOOK)],
      input=json.dumps(payload),
      capture_output=True,
      text=True,
      env=env,
      timeout=3,
      check=False,
    )
    self.assertEqual(res.returncode, 0, res.stderr)
    self.assertEqual(self.untouched.read_text(encoding='utf-8'), 'keep-me')
    return res.stdout.strip()

  def test_known_bad_unsupported_playwright_and_chained_clicks_deny(self):
    bad_cases = [
      ('playwright-evaluate', 'return await tab.playwright.evaluate(() => document.title);'),
      ('tab-evaluate', 'const links = await tab.evaluate(() => location.href);'),
      ('tab-page-locator', 'let text = await tab.page().locator("body").innerText();'),
      ('wait-for-load-state', 'await tab.waitForLoadState("networkidle");'),
      ('set-input-files', 'await tab.setInputFiles(12, "/tmp/a.png");'),
      ('scroll-into-view-if-needed', 'await renderTab.playwright.getByLabel("Key").scrollIntoViewIfNeeded();'),
      ('tab-wait-for-event', 'const chooserPromise = ghTab.waitForEvent("filechooser");'),
      ('tab-wait', 'await ghTab.wait(1000);'),
      ('tab-get-state', 'nodeRepl.write(await civ.getState());'),
      ('tab-snapshot', 'const snap = await tab.snapshot();'),
      ('locator-input-value', 'const val = await tab.playwright.locator("input").inputValue();'),
      ('chained-clicks', 'await tab.click(56);\nawait tab.click(65);'),
      ('chained-clicks-with-fake-refresh', 'await tab.click(56);\nawait tab.getAXState();\nawait tab.click(65);'),
    ]
    for label, code in bad_cases:
      with self.subTest(label=label):
        out = self.run_hook(code)
        self.assertTrue(bool(out), f'{label} should deny')
        data = json.loads(out)['hookSpecificOutput']
        self.assertEqual(data['permissionDecision'], 'deny')

  def test_known_good_and_boundary_cases_allow(self):
    good_cases = [
      ('single-click-plus-ax', 'await tab.click(56);\nawait tab.getAXState();'),
      ('single-click-plus-screenshot', 'await tab.click(56);\nawait tab.getAXStateAndScreenshot();'),
      ('multi-setvalue-single-click', 'await tab.setValue(24, "a@b.com");\nawait tab.setValue(27, "pw");\nawait tab.click(30);\nawait tab.getAXState();'),
      ('playwright-locator-upload-exception', 'await tab.playwright.locator("input[type=file]").click();'),
      ('playwright-wait-for-event-filechooser', 'const chooserPromise = tab.playwright.waitForEvent("filechooser", { timeoutMs: 10000 });'),
      ('cua-get-state-allowed', 'const st = await cua.getState();'),
      ('comment-mentions-only', '// do not call tab.evaluate(x) or click(1) then click(2)\nawait tab.getAXState();'),
      ('completion-summary-only', None),
    ]
    for label, code in good_cases:
      with self.subTest(label=label):
        self.assertEqual(self.run_hook(code), '')

  def test_self_lifecycle_and_pathological_audit_targets(self):
    # Recovery env disables gate
    self.assertEqual(
      self.run_hook('await tab.click(1); await tab.click(2);', extra_env={'LCU_ROUTING_GATE_DISABLE': '1'}),
      '',
    )
    # Non-LCU tool is ignored (update path)
    self.assertEqual(self.run_hook('await tab.click(1); await tab.click(2);', tool_name='Bash'), '')

    # Symlink audit target is refused without touching target
    symlink_audit = self.temp_root / 'symlink-audit.jsonl'
    symlink_audit.symlink_to(self.untouched)
    out = self.run_hook('await tab.click(1); await tab.click(2);', extra_env={'LCU_ROUTING_GATE_AUDIT': str(symlink_audit)})
    self.assertTrue(bool(out))
    self.assertEqual(self.untouched.read_text(encoding='utf-8'), 'keep-me')

    # FIFO audit target does not hang
    fifo_audit = self.temp_root / 'fifo-audit.jsonl'
    os.mkfifo(fifo_audit)
    out_fifo = self.run_hook('await tab.click(1); await tab.click(2);', extra_env={'LCU_ROUTING_GATE_AUDIT': str(fifo_audit)})
    self.assertTrue(bool(out_fifo))


if __name__ == '__main__':
  unittest.main()
