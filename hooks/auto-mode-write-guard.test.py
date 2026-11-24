import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).with_name("auto-mode-write-guard.py")
SESSION = "2471cbbc-31f0-4be6-9d60-5140d9f4aa0e"


class GuardTests(unittest.TestCase):
  def setUp(self):
    tmp = tempfile.TemporaryDirectory()
    self.addCleanup(tmp.cleanup)
    self.home = Path(tmp.name).resolve()
    self.root = self.home / ".claude/logs/auto-mode/modes"
    self.root.mkdir(parents=True)
    self.state = self.root / f"session-{SESSION}.json"
    self.state.write_text('{"enabled":false,"applied_events":[]}\n')
    self.ordinary = self.home / "ordinary.json"
    self.ordinary.write_bytes(self.state.read_bytes())
    self.mode = self.home / ".claude/scripts/auto-mode/mode.py"
    self.mode.parent.mkdir(parents=True)
    self.mode.touch()

  def check(self, deny, payload, reason="自動模式"):
    result = subprocess.run([sys.executable, "-IB", str(HOOK)], input=json.dumps(payload),
                            capture_output=True, text=True, timeout=5,
                            env={**os.environ, "HOME": str(self.home)})
    self.assertEqual(result.returncode, 0, result.stderr)
    if deny:
      self.assertTrue(result.stdout, "expected deny decision, got no decision")
      body = json.loads(result.stdout)["hookSpecificOutput"]
      self.assertEqual(body["hookEventName"], "PreToolUse")
      self.assertEqual(body["permissionDecision"], "deny")
      self.assertIn(reason, body["permissionDecisionReason"])
    else:
      self.assertEqual(result.stdout, "")

  def payload(self, tool, **tool_input):
    return {"hook_event_name": "PreToolUse", "session_id": SESSION, "cwd": str(self.home),
            "tool_name": tool, "tool_input": tool_input}

  def write_payload(self, tool, path):
    if tool == "Write":
      return self.payload(tool, file_path=str(path), content="{}")
    return self.payload(tool, file_path=str(path), old_string="false", new_string="true")

  def test_state_write_destinations(self):
    alias = self.home / "state link.json"
    alias.symlink_to(self.state)
    parent = self.home / "state dir"
    parent.symlink_to(self.root, target_is_directory=True)
    unborn = parent / "future.json"
    for tool in ("Edit", "Write"):
      self.check(False, self.write_payload(tool, self.ordinary))
      for path in (self.state, alias, unborn):
        with self.subTest(tool=tool, path=path):
          self.check(True, self.write_payload(tool, path))
    for form in ("printf '{{}}'>{}", "printf '{{}}' | tee {}", "mv source {}", "rm {}", "sed -i '' s/a/b/ {}"):
      self.check(False, self.payload("Bash", command=form.format(shlex.quote(str(self.ordinary)))))
      for path in (self.state, alias, unborn):
        with self.subTest(form=form, path=path):
          self.check(True, self.payload("Bash", command=form.format(shlex.quote(str(path.relative_to(self.home))))))
    self.check(True, self.payload("Bash", command="cd 'state dir' && printf x > future.json"))

  def test_button_block_sync_and_normal_allow(self):
    tool = shlex.quote(str(self.mode))
    for action in ("on", "off"):
      for option in ("--source button", "--source=button"):
        with self.subTest(action=action, option=option):
          command = f"HC_TERMINAL_ID=t python3 -I {tool} {action} {option}"
          self.check(True, self.payload("Bash", command=command), reason="按鈕來源只供 Herdr")
    for cmd in (f"python3 -I {tool} sync --session {SESSION}", f"python3 {tool} status --session {SESSION}",
                f"cat {shlex.quote(str(self.state))}", "git status", "echo x > ordinary.json",
                f"python3 ~/.claude/scripts/pi-subtask/mode.py sync --session {SESSION}"):
      self.check(False, self.payload("Bash", command=cmd))
    for name in ("Edit", "Write"):
      self.check(False, self.write_payload(name, self.ordinary))
    self.assertEqual(self.state.read_bytes(), self.ordinary.read_bytes())

  def test_inline_python_literal_write(self):
    for template in ("from pathlib import Path; Path({!r}).write_text('x')", "open({!r}, 'w').close()"):
      for path, deny in ((self.ordinary, False), (self.state, True)):
        self.check(deny, self.payload("Bash", command=f"python3 -c {shlex.quote(template.format(str(path)))}"))
    read = f"open({str(self.state)!r}, 'r').read()"
    self.check(False, self.payload("Bash", command=f"python3 -c {shlex.quote(read)}"))

  def test_plain_text_heredoc_keeps_destination_check(self):
    command = "cat <<'DOC' > {}\nIt's normal text.\nDOC\n"
    self.check(True, self.payload("Bash", command=command.format(shlex.quote(str(self.state)))))
    self.check(False, self.payload("Bash", command=command.format(shlex.quote(str(self.ordinary)))))

  def test_commit_heredoc_keeps_message_as_literal_data(self):
    def bash(command):
      return {**self.payload("Bash", command=command), "permission_mode": "default",
              "transcript_path": str(self.home / f"{SESSION}.jsonl")}

    for message in ("the tool's sync", "feat: add skills"):
      with self.subTest(message=message):
        self.check(False, bash(f"cd ~/.claude && git commit -q -F - <<'EOF'\n{message}\nEOF"))
    for opener, tab in (("<<'END'", ""), ('<<"END"', ""), ("<<-'END'", "\t")):
      with self.subTest(opener=opener):
        state = shlex.quote(str(self.state))
        body = f"{tab}printf 'x' > {state}\n{tab}the tool's sync\n{tab}END\n"
        self.check(False, bash(f"git commit -q -F - {opener}\n{body}"))
        self.check(True, bash(f"cat > {state} {opener}\n{body}"), reason="不可直接寫入")

  def test_shell_parse_failure_checks_protected_text(self):
    for destination, reason in ((self.ordinary, None), (self.state, "不可直接寫入")):
      self.check(reason is not None, self.payload("Bash", command=f"printf 'oops > {destination}"), reason)
    for option in ("--source button", "--source=button"):
      self.check(True, self.payload("Bash", command=f"python3 '{self.mode} on {option}"),
                 reason="按鈕來源只供 Herdr")
    self.check(False, self.payload("Bash", command=f"python3 '{self.mode} sync"))

  def test_malformed_input_is_denied(self):
    self.check(False, self.write_payload("Write", self.ordinary))
    self.check(False, self.payload("Bash", command="git status"))
    for payload in (None, [], {}, {**self.payload("Bash", command="git status"), "cwd": 9},
                    {**self.payload("Bash", command="git status"), "tool_input": None},
                    {**self.payload("Bash", command="git status"), "tool_name": None},
                    self.payload("Bash"), self.payload("Bash", command=None), self.payload("Bash", command=4),
                    self.payload("Edit"), self.payload("Edit", file_path=None),
                    self.payload("Write", file_path={"path": str(self.ordinary)})):
      with self.subTest(payload=payload):
        self.check(True, payload)


if __name__ == "__main__":
  if not unittest.main(verbosity=2, exit=False).result.wasSuccessful():
    sys.exit(1)
  print("AUTO_MODE_WRITE_GUARD_CONTRACT_OK")
