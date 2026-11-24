import fcntl
import json
import os
import resource
import selectors
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

MODE = Path(__file__).with_name("mode.py").resolve()
RECORDS = Path(__file__).with_name("records.py").resolve()
SESSION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OTHER_SESSION = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
NO_SAMPLE = "尚無可算樣本"


class RecordTests(unittest.TestCase):
  def setUp(self):
    temporary = tempfile.TemporaryDirectory()
    self.addCleanup(temporary.cleanup)
    self.home = Path(temporary.name)
    self.env = {**os.environ, "HOME": str(self.home)}
    for name in ("HC_TERMINAL_ID", "CLAUDE_SESSION_ID", "CLAUDE_AGENT_ID", "CLAUDE_CONFIG_DIR"):
      self.env.pop(name, None)
    self.record_file = self.home / ".claude/logs/auto-mode/records" / f"session-{SESSION}.json"

  def cli(self, *args, tool=RECORDS, session=SESSION, terminal=None, write_limit=None):
    env = dict(self.env)
    if terminal is not None:
      env["HC_TERMINAL_ID"] = terminal
    return subprocess.run(
      [sys.executable, "-IB", str(tool), *args, "--session", session],
      env=env, capture_output=True, text=True, timeout=5, preexec_fn=write_limit,
    )

  def output(self, *args, **kwargs):
    result = self.cli(*args, **kwargs)
    self.assertEqual(result.returncode, 0, result.stderr)
    return json.loads(result.stdout) if result.stdout else None

  def append(self, task="task-a", disposition="followed", **kwargs):
    adopted = "採用 A" if disposition == "followed" else "留在本機"
    args = ["append", "--task", task, "--stop", "發布", "--recommendation", "採用 A",
            "--adopted", adopted, "--disposition", disposition, "--reason", "變更可復原。"]
    if disposition == "followed":
      args += ["--undo", "還原選項"]
    return self.output(*args, **kwargs)

  def review(self, row, reply, value=None):
    args = ["review", "--id", row["id"], "--reply", reply]
    if value is not None:
      args += ["--changed-value", value]
    return self.output(*args)

  def test_closeout(self):
    key = {"terminal": "terminal/1"}
    self.assertIs(self.output("on", "--source", "button", tool=MODE, **key)["enabled"], True)
    followed = [self.append(**key) for _ in range(3)]
    self.append(task="task-b", **key)
    downweighted = self.append(disposition="downweighted", **key)
    self.assertEqual(followed[0], {
      "id": "D1", "task": "task-a", "stop": "發布", "recommendation": "採用 A",
      "adopted": "採用 A", "disposition": "followed", "reason": "變更可復原。",
      "undo": "還原選項", "reply": "unreviewed", "changed_value": None,
    })
    self.assertIsNone(downweighted["undo"])
    self.assertIs(self.output("off", "--source", "button", tool=MODE, **key)["enabled"], False)
    self.assertEqual(self.output("closeout", "--task", "task-a", session=OTHER_SESSION, **key),
                     [downweighted, *followed])
    self.assertEqual(self.output("closeout", "--task", "task-b", **key)[0]["id"], "D4")
    existing_files = {path.name for path in self.record_file.parent.iterdir()}
    for task, scope in (("task-c", key), ("task-a", {})):
      result = self.cli("closeout", "--task", task, **scope)
      self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)
    self.assertEqual({path.name for path in self.record_file.parent.iterdir()}, existing_files)

  def test_downweighted_reopened(self):
    kept = self.append()
    self.review(kept, "kept")
    baseline = self.output("stats")
    self.assertEqual(baseline["kept_rate"], {"numerator": 1, "denominator": 1, "display": "100.00%"})
    self.assertEqual(baseline["downweighted_reopened"], 0)
    reopened = self.append(disposition="downweighted")
    kept_closed = self.append(disposition="downweighted")
    self.review(reopened, "changed", "現在發布")
    self.review(kept_closed, "kept")
    rows = self.output("closeout", "--task", "task-a")
    self.assertEqual(rows[0], {**reopened, "reply": "changed", "changed_value": "現在發布"})
    self.assertEqual(rows[1], {**kept_closed, "reply": "kept"})
    self.assertEqual(self.output("stats"), {**baseline, "downweighted_reopened": 1})

  def test_followed_partition_and_rate(self):
    self.append()
    self.review(self.append(), "kept")
    self.review(self.append(), "changed", "選 B")
    revised = self.append()
    self.review(revised, "kept")
    self.review(revised, "changed", "選 C")
    self.review(self.append(disposition="downweighted"), "changed", "重新開啟")
    self.append(disposition="downweighted")
    counts = self.output("stats")
    self.assertEqual(counts, {
      "followed": 4, "unreviewed": 1, "kept": 1, "changed": 2,
      "kept_rate": {"numerator": 1, "denominator": 3, "display": "33.33%"},
      "reviewed_coverage": {"numerator": 3, "denominator": 4, "display": "75.00%"},
      "downweighted_reopened": 1,
    })
    self.assertEqual(counts["unreviewed"] + counts["kept"] + counts["changed"], counts["followed"])
    rate = counts["kept_rate"]
    self.assertLessEqual(rate["numerator"], rate["denominator"])
    self.assertEqual(rate["denominator"], counts["kept"] + counts["changed"])

  def test_latest_reply(self):
    row = self.append()
    self.assertEqual(self.review(row, "kept"), {**row, "reply": "kept"})
    self.assertEqual(self.output("stats")["kept_rate"],
                     {"numerator": 1, "denominator": 1, "display": "100.00%"})
    self.review(row, "changed", "選 B")
    self.assertEqual(self.output("closeout", "--task", "task-a"),
                     [{**row, "reply": "changed", "changed_value": "選 B"}])
    self.assertEqual(self.output("stats"), {
      "followed": 1, "unreviewed": 0, "kept": 0, "changed": 1,
      "kept_rate": {"numerator": 0, "denominator": 1, "display": "0.00%"},
      "reviewed_coverage": {"numerator": 1, "denominator": 1, "display": "100.00%"},
      "downweighted_reopened": 0,
    })
    self.review(row, "kept")
    self.assertEqual(self.output("closeout", "--task", "task-a"), [{**row, "reply": "kept"}])

  def test_no_sample(self):
    empty = self.output("stats")
    self.assertEqual(empty["kept_rate"], {"numerator": 0, "denominator": 0, "display": NO_SAMPLE})
    self.assertEqual(empty["reviewed_coverage"], empty["kept_rate"])
    self.append()
    unreviewed = self.output("stats")
    self.assertEqual(unreviewed["kept_rate"], empty["kept_rate"])
    self.assertEqual(unreviewed["unreviewed"], 1)
    self.assertEqual(unreviewed["reviewed_coverage"],
                     {"numerator": 0, "denominator": 1, "display": "0.00%"})

  def test_unreadable_records(self):
    row = self.append()
    self.assertEqual(self.output("closeout", "--task", "task-a"), [row])
    for broken in (b'[{"id":', b'[{"id":"D1"}]'):
      self.record_file.write_bytes(broken)
      for command in (("closeout", "--task", "task-a"), ("stats",),
                      ("review", "--id", "D1", "--reply", "kept")):
        with self.subTest(broken=broken, command=command[0]):
          result = self.cli(*command)
          self.assertNotEqual(result.returncode, 0)
          self.assertIn("讀不到自決紀錄", result.stderr)
          self.assertEqual(result.stdout, "")
      self.assertEqual(self.record_file.read_bytes(), broken)

  def test_all_commands_preserve_damaged_ledger_bytes(self):
    row = self.append()
    self.assertEqual(self.output("closeout", "--task", "task-a"), [row])
    append_args = ("append", "--task", "task-a", "--stop", "確認", "--recommendation", "選 A",
                   "--adopted", "選 A", "--disposition", "followed", "--reason", "安全。")
    for broken in (b"", b"\xff", b'[{"id":', json.dumps([{**row, "id": "D2"}]).encode("utf-8"),
                   json.dumps([{**row, "reply": "kept", "changed_value": "unexpected"}]).encode("utf-8")):
      for command in (append_args, ("review", "--id", "D1", "--reply", "kept"),
                      ("closeout", "--task", "task-a"), ("stats",)):
        with self.subTest(broken=broken, command=command[0]):
          self.record_file.write_bytes(broken)
          result = self.cli(*command)
          self.assertEqual((result.returncode, result.stdout), (1, ""), result.stderr)
          self.assertIn("檔案損毀或無法存取", result.stderr)
          self.assertEqual(self.record_file.read_bytes(), broken)

  def test_rejects_ledger_with_invalid_unicode_without_writing(self):
    row = self.append()
    broken = json.dumps([{**row, "reason": "\ud800"}]).encode("ascii")
    append_args = ("append", "--task", "task-a", "--stop", "確認", "--recommendation", "選 A",
                   "--adopted", "選 A", "--disposition", "followed", "--reason", "安全。")
    for command in (append_args, ("review", "--id", "D1", "--reply", "kept"),
                    ("closeout", "--task", "task-a"), ("stats",)):
      with self.subTest(command=command[0]):
        self.record_file.write_bytes(broken)
        result = self.cli(*command)
        self.assertEqual((result.returncode, result.stdout, self.record_file.read_bytes()), (1, "", broken),
                         result.stderr)
        self.assertIn("檔案損毀或無法存取", result.stderr)

  def test_closeout_waits_to_open_ledger_during_atomic_replacement(self):
    seed = self.append()
    updated = {**seed, "reply": "kept"}
    temporary = self.record_file.with_suffix(".next")
    temporary.write_text(json.dumps([updated]), encoding="utf-8")
    temporary.chmod(0o600)

    # Hold the writer lock and pause the reader at its first lock or ledger access.
    probe = """
import fcntl, os, runpy, sys
script, ledger, *args = sys.argv[1:]
real_open, real_flock = os.open, fcntl.flock

def open_file(path, *args, **kwargs):
  fd = real_open(path, *args, **kwargs)
  if path == ledger:
    print('ledger', file=sys.stderr, flush=True)
    sys.stdin.readline()
  return fd

def flock(fd, operation):
  print('lock', file=sys.stderr, flush=True)
  return real_flock(fd, operation)

os.open, fcntl.flock = open_file, flock
sys.argv = [script, *args]
runpy.run_path(script, run_name='__main__')
"""
    argv = [sys.executable, "-IB", "-c", probe, str(RECORDS), self.record_file.name,
            "closeout", "--task", "task-a", "--session", SESSION]
    with self.record_file.with_suffix(".lock").open("rb") as writer:
      fcntl.flock(writer, fcntl.LOCK_EX)
      with subprocess.Popen(argv, env=self.env, text=True, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE) as reader:
        try:
          with selectors.DefaultSelector() as ready:
            ready.register(reader.stderr, selectors.EVENT_READ)
            self.assertTrue(ready.select(timeout=5), "reader never reached the filesystem seam")
          first = reader.stderr.readline().strip()
          os.replace(temporary, self.record_file)
          fcntl.flock(writer, fcntl.LOCK_UN)
          output, error = reader.communicate("continue\n", timeout=5)
        finally:
          if reader.poll() is None:
            reader.kill()
        self.assertEqual(reader.returncode, 0, f"reader first accessed {first!r}: {error}")
        self.assertEqual(json.loads(output), [updated])

  def test_concurrent_appends_reviews_and_closeouts_keep_whole_records(self):
    seed = [self.append() for _ in range(4)]
    commands = [
      ("append", "--task", "task-a", "--stop", "確認", "--recommendation", f"選項 {index}",
       "--adopted", f"選項 {index}", "--disposition", "followed", "--reason", f"  說明 {index}  ")
      for index in range(6)
    ]
    commands += [("review", "--id", row["id"], "--reply", "changed", "--changed-value", f"更新 {row['id']}")
                 for row in seed]
    commands += [("closeout", "--task", "task-a")] * 4
    start = threading.Barrier(len(commands))

    def launch(args):
      start.wait(timeout=5)
      return self.output(*args)

    with ThreadPoolExecutor(max_workers=len(commands)) as pool:
      results = list(pool.map(launch, commands))
    appended, reviewed, snapshots = results[:6], results[6:10], results[10:]
    for index, row in enumerate(appended):
      self.assertEqual(row["recommendation"], f"選項 {index}")
      self.assertEqual(row["reason"], f"  說明 {index}  ")
    for old, new in zip(seed, reviewed):
      self.assertEqual(new, {**old, "reply": "changed", "changed_value": f"更新 {old['id']}"})
    final = self.output("closeout", "--task", "task-a")
    self.assertEqual([row["id"] for row in final], [f"D{i}" for i in range(1, 11)])
    self.assertEqual(final[:4], reviewed)
    self.assertCountEqual(final[4:], appended)
    for snapshot in snapshots:
      self.assertGreaterEqual(len(snapshot), len(seed))
      self.assertEqual([row["id"] for row in snapshot], [row["id"] for row in final[:len(snapshot)]])
      for index, row in enumerate(snapshot):
        self.assertIn(row, (seed[index], reviewed[index]) if index < len(seed) else (final[index],))

  def test_append_write_failure(self):
    row = self.append()
    original = self.record_file.read_bytes()
    files = set(self.record_file.parent.iterdir())

    def no_file_writes():
      resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))

    result = self.cli("append", "--task", "task-a", "--stop", "確認", "--recommendation", "選 A",
                      "--adopted", "選 A", "--disposition", "followed", "--reason", "安全。",
                      write_limit=no_file_writes)
    self.assertNotEqual(result.returncode, 0)
    self.assertIn("寫入自決紀錄失敗", result.stderr)
    self.assertEqual(result.stdout, "")
    self.assertEqual(self.record_file.read_bytes(), original)
    self.assertEqual(set(self.record_file.parent.iterdir()), files)
    self.assertEqual(self.output("closeout", "--task", "task-a"), [row])
    self.assertEqual(self.append()["id"], "D2")


if __name__ == "__main__":
  unittest.main(verbosity=2)
