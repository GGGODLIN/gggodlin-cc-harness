import argparse
import fcntl
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import closing, redirect_stdout
from importlib.machinery import SourceFileLoader
import importlib.util
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).with_name("ccsi")


def db_path_for(home):
  if sys.platform == "darwin":
    return home / "Library/Caches/cc-session-index/index.sqlite"
  return home / ".cache/cc-session-index/index.sqlite"


LEGACY_SCRIPT = SCRIPT.parent / "testdata/ccsi-v2.py"


def ccsi_env(home, extra_env=None):
  env = os.environ.copy()
  env["HOME"] = str(home)
  for k in ("CCSI_DB_DIR", "CLAUDE_CONFIG_DIR", "CODEX_HOME", "PI_CODING_AGENT_DIR", "XDG_CACHE_HOME"):
    env.pop(k, None)
  if extra_env:
    env.update(extra_env)
  return env


def run_ccsi(home, *args, check=True, extra_env=None, script=SCRIPT, timeout=20, text=True):
  return subprocess.run(
    [sys.executable, str(script), *args],
    env=ccsi_env(home, extra_env),
    capture_output=True,
    text=text,
    check=check,
    timeout=timeout,
  )


def cc_session(home, name, text):
  path = home / ".claude/projects/probe" / f"{name}.jsonl"
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(json.dumps({
    "type": "user", "timestamp": "2026-10-19T00:00:00Z",
    "message": {"role": "user", "content": text},
  }) + "\n")
  return path


class ContentlessUpgradeTest(unittest.TestCase):
  def test_v2_upgrade_keeps_searchable_old_db_until_replace(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      cc_session(home, "old-session", "legacyneedle")
      run_ccsi(home, "index", script=LEGACY_SCRIPT)
      database = db_path_for(home)
      old_bytes = database.read_bytes()
      old_hit = run_ccsi(home, "search", "legacyneedle", script=LEGACY_SCRIPT).stdout
      self.assertIn("old-session.jsonl", old_hit)
      cc_session(home, "new-session", "rebuiltneedle")

      scoped = run_ccsi(home, "index", "--vendor", "cc", check=False)
      self.assertNotEqual(scoped.returncode, 0)
      self.assertIn("ccsi index", scoped.stderr)
      self.assertEqual(database.read_bytes(), old_bytes)
      self.assertEqual(run_ccsi(home, "search", "legacyneedle").stdout, old_hit)
      self.assertEqual(run_ccsi(home, "search", "rebuiltneedle").stdout, "(no hits)\n")

      run_ccsi(home, "index")
      self.assertNotEqual(database.read_bytes(), old_bytes)
      self.assertEqual(run_ccsi(home, "search", "legacyneedle").stdout, old_hit)
      self.assertIn(">>>rebuiltneedle<<<", run_ccsi(home, "search", "rebuiltneedle", "--vendor", "cc").stdout)
      self.assertEqual(run_ccsi(home, "search", "rebuiltneedle", "--exclude-session", "new-session").stdout,
                       "(no hits)\n")

  def test_interrupted_rebuild_preserves_old_db_and_discards_staging_on_retry(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      session = cc_session(home, "before", "interruptneedle")
      run_ccsi(home, "index", script=LEGACY_SCRIPT)
      database = db_path_for(home)
      staging = database.with_suffix(".sqlite.rebuild")
      old_bytes = database.read_bytes()
      old_hit = run_ccsi(home, "search", "interruptneedle", script=LEGACY_SCRIPT).stdout
      fifo = session.with_name("pause.jsonl")
      os.mkfifo(fifo)
      with subprocess.Popen([sys.executable, str(SCRIPT), "index"], env=ccsi_env(home),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE) as rebuild:
        try:
          deadline = time.monotonic() + 5
          while not staging.is_file() and rebuild.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
          self.assertTrue(staging.is_file(), "rebuild did not create a separate index")
          self.assertIsNone(rebuild.poll())
          self.assertEqual(database.read_bytes(), old_bytes)
          self.assertEqual(run_ccsi(home, "search", "interruptneedle").stdout, old_hit)
        finally:
          rebuild.kill()
          rebuild.communicate(timeout=5)
      self.assertEqual(database.read_bytes(), old_bytes)
      self.assertEqual(run_ccsi(home, "search", "interruptneedle").stdout, old_hit)
      self.assertTrue(staging.is_file())
      fifo.unlink()
      cc_session(home, "after", "recoverneedle")
      run_ccsi(home, "index")
      self.assertFalse(staging.exists())
      self.assertIn("after.jsonl", run_ccsi(home, "search", "recoverneedle").stdout)

  def test_missing_indexed_source_blocks_rebuild_until_restored(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      cc_session(home, "legacy", "preserveneedle")
      write_codex_rollout(home / ".codex/sessions/probe/rollout.jsonl")
      run_ccsi(home, "index", script=LEGACY_SCRIPT)
      initial = run_ccsi(home, "search", "codexneedle").stdout
      self.assertIn("rollout.jsonl", initial)
      db = db_path_for(home)
      old = db.read_bytes()
      codex = home / ".codex"
      moved = codex.rename(home / "codex-away")
      try:
        result = run_ccsi(home, "index", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("existing index", result.stderr)
        self.assertEqual(db.read_bytes(), old)
      finally:
        moved.rename(codex)
      run_ccsi(home, "index")
      self.assertEqual(run_ccsi(home, "search", "codexneedle").stdout, initial)

  def test_rebuild_skips_unreadable_file_only_if_it_was_never_indexed(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      indexed = cc_session(home, "indexed", "keptneedle")
      run_ccsi(home, "index", script=LEGACY_SCRIPT)
      new = cc_session(home, "unindexed", "deferredneedle")
      indexed.chmod(0)
      new.chmod(0)
      try:
        blocked = run_ccsi(home, "index", check=False)
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("kept the existing index", blocked.stderr)
        self.assertIn(">>>keptneedle<<<", run_ccsi(home, "search", "keptneedle").stdout)
        indexed.chmod(0o600)
        rebuilt = run_ccsi(home, "index")
        self.assertIn("updated=1 failed=1 rows=1 ", rebuilt.stdout)
        self.assertIn(str(new), rebuilt.stderr)
        self.assertIn(">>>keptneedle<<<", run_ccsi(home, "search", "keptneedle").stdout)
        self.assertEqual(run_ccsi(home, "search", "deferredneedle").stdout, "(no hits)\n")
      finally:
        indexed.chmod(0o600)
        new.chmod(0o600)
      self.assertIn("updated=1 failed=0 rows=2 ", run_ccsi(home, "index").stdout)
      self.assertIn(">>>deferredneedle<<<", run_ccsi(home, "search", "deferredneedle").stdout)

  def test_search_uses_the_indexed_extractor_during_version_rebuild(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      cc_session(home, "version", "indexedversionneedle")
      run_ccsi(home, "index")
      old = run_ccsi(home, "search", "indexedversionneedle").stdout
      self.assertIn(">>>indexedversionneedle<<<", old)
      future = home / "ccsi-next.py"
      script = SCRIPT.read_text().replace("EXTRACTOR_VERSION = 1", "EXTRACTOR_VERSION = 2", 1)
      old_mapping = "EXTRACTORS = {1: extract_rows}"
      next_mapping = """def next_extract_rows(path, vendor=None, records=None):
  return [(text + ' nextversion', source, ts, role)
          for text, source, ts, role in extract_rows(path, vendor, records)]


EXTRACTORS = {1: extract_rows, 2: next_extract_rows}"""
      future.write_text(script.replace(old_mapping, next_mapping, 1))
      self.assertEqual(run_ccsi(home, "search", "indexedversionneedle", script=future).stdout, old)
      rebuild = run_ccsi(home, "index", script=future)
      self.assertIn("updated=1 failed=0 rows=1 ", rebuild.stdout)
      rebuilt = run_ccsi(home, "search", "indexedversionneedle", script=future).stdout
      self.assertEqual(rebuilt, old.replace("<<<\n", "<<< nextversion\n"))
      self.assertIn("updated=0 failed=0 rows=1 ", run_ccsi(home, "index", script=future).stdout)


class ChangedSearchSourceTest(unittest.TestCase):
  def test_missing_source_does_not_take_a_result_slot(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      paths = [cc_session(home, name, "sharedneedle") for name in ("first", "second")]
      run_ccsi(home, "index")
      before = run_ccsi(home, "search", "sharedneedle", "-k", "1").stdout
      first, second = sorted(paths, key=lambda path: path.name not in before)
      self.assertIn(first.name, before)
      first.unlink()
      after = run_ccsi(home, "search", "sharedneedle", "-k", "1").stdout
      self.assertIn(second.name, after)
      self.assertNotIn(first.name, after)

  def test_shrunk_or_replaced_source_is_skipped_even_if_the_term_still_matches(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      shrunk = cc_session(home, "shrunk", "shrinkneedle extra words removed later")
      replaced = cc_session(home, "replaced", "replaceneedle initial")
      run_ccsi(home, "index")
      self.assertIn(shrunk.name, run_ccsi(home, "search", "shrinkneedle").stdout)
      self.assertIn(replaced.name, run_ccsi(home, "search", "replaceneedle").stdout)
      cc_session(home, "shrunk", "shrinkneedle")
      replacement = cc_session(home, "replacement", "replaceneedle updated with more words")
      replacement.replace(replaced)
      self.assertEqual(run_ccsi(home, "search", "shrinkneedle").stdout, "(no hits)\n")
      self.assertEqual(run_ccsi(home, "search", "replaceneedle").stdout, "(no hits)\n")

  def test_rewritten_row_does_not_mix_new_text_and_old_timestamp(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      path = cc_session(home, "rewritten", "sameneedle old")
      run_ccsi(home, "index")
      self.assertIn(">>>sameneedle<<< old", run_ccsi(home, "search", "sameneedle").stdout)
      raw = path.read_text().replace("sameneedle old", "sameneedle new").replace("00:00:00Z", "00:00:01Z")
      self.assertEqual(len(raw.encode()), path.stat().st_size)
      path.write_text(raw)
      self.assertEqual(run_ccsi(home, "search", "sameneedle").stdout, "(no hits)\n")

  def test_replaced_pipe_does_not_block_search(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      replaced = cc_session(home, "replaced", "pipeneedle")
      available = cc_session(home, "available", "pipeneedle")
      run_ccsi(home, "index")
      self.assertIn(replaced.name, run_ccsi(home, "search", "pipeneedle").stdout)
      fifo = replaced.with_name("replacement.pipe")
      os.mkfifo(fifo)
      fifo.replace(replaced)
      result = run_ccsi(home, "search", "pipeneedle", timeout=3)
      self.assertIn(available.name, result.stdout)
      self.assertNotIn(replaced.name, result.stdout)

  def test_codex_hit_uses_parser_recorded_when_indexed(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      codex = home / "custom-codex"
      write_codex_rollout(codex / "sessions/probe/rollout.jsonl")
      extra = {"CODEX_HOME": str(codex)}
      run_ccsi(home, "index", script=LEGACY_SCRIPT, extra_env={**extra, "CCSI_DB_DIR": str(home / "legacy")})
      run_ccsi(home, "index", extra_env=extra)
      old = run_ccsi(home, "search", "codexneedle", script=LEGACY_SCRIPT,
                     extra_env={"CCSI_DB_DIR": str(home / "legacy")}).stdout
      self.assertIn(">>>codexneedle<<<", old)
      self.assertEqual(run_ccsi(home, "search", "codexneedle").stdout, old)

  def test_short_term_filter_continues_beyond_the_first_candidates(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      for i in range(70):
        cc_session(home, f"filler-{i}", "batchneedle")
      cc_session(home, "matching-a", "batchneedle extra words ZX at end")
      cc_session(home, "matching-b", "batchneedle extra words zx at end")
      run_ccsi(home, "index")
      self.assertIn("filler-", run_ccsi(home, "search", "batchneedle", "-k", "1").stdout)
      first = run_ccsi(home, "search", "batchneedle", "zx", "-k", "1").stdout
      self.assertEqual(first.count("--- [cc]"), 1)
      self.assertIn("matching-", first)
      exhausted = run_ccsi(home, "search", "batchneedle", "zx", "-k", "3").stdout
      self.assertIn("matching-a.jsonl", exhausted)
      self.assertIn("matching-b.jsonl", exhausted)
      self.assertEqual(exhausted.count("--- [cc]"), 2)


class PruneDeletedSessionsTest(unittest.TestCase):
  def test_deleted_session_is_removed_from_index(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      path = cc_session(home, "deleted", "deletedneedle")
      cc_session(home, "retained", "retainedneedle")
      self.assertIn("rows=2 ", run_ccsi(home, "index").stdout)
      self.assertIn(path.name, run_ccsi(home, "search", "deletedneedle").stdout)
      path.unlink()
      self.assertIn("rows=1 ", run_ccsi(home, "index").stdout)
      self.assertEqual(run_ccsi(home, "search", "deletedneedle").stdout, "(no hits)\n")
      self.assertIn("retained.jsonl", run_ccsi(home, "search", "retainedneedle").stdout)

  def test_vendor_scoped_prune_retains_other_vendors(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      cc = cc_session(home, "deleted", "deletedneedle")
      codex = home / ".codex/sessions/probe/rollout.jsonl"
      write_codex_rollout(codex)
      pi = home / ".pi/agent/sessions/probe/pi.jsonl"
      pi.parent.mkdir(parents=True)
      pi.write_text(json.dumps({"type": "message", "message": {"role": "user", "content": "pineedle"}}) + "\n")
      initial = run_ccsi(home, "index").stdout
      total = int(initial.split("rows=")[1].split()[0])
      self.assertIn("rollout.jsonl", run_ccsi(home, "search", "codexneedle").stdout)
      self.assertIn("pi.jsonl", run_ccsi(home, "search", "pineedle").stdout)
      for path in (cc, codex, pi):
        path.rename(path.with_suffix(".backup"))
      self.assertIn(f"rows={total - 1} ", run_ccsi(home, "index", "--vendor", "cc").stdout)
      for path in (codex, pi):
        path.with_suffix(".backup").rename(path)
      self.assertIn("rollout.jsonl", run_ccsi(home, "search", "codexneedle").stdout)
      self.assertIn("pi.jsonl", run_ccsi(home, "search", "pineedle").stdout)
      self.assertEqual(run_ccsi(home, "search", "deletedneedle").stdout, "(no hits)\n")

  def test_missing_root_preserves_index_entries(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      path = cc_session(home, "restore", "restoreneedle")
      self.assertIn("rows=1 ", run_ccsi(home, "index").stdout)
      initial = run_ccsi(home, "search", "restoreneedle").stdout
      self.assertIn(path.name, initial)
      root = home / ".claude/projects"
      relocated = root.rename(root.with_name("projects-away"))
      try:
        self.assertIn("rows=1 ", run_ccsi(home, "index").stdout)
      finally:
        relocated.rename(root)
      self.assertEqual(run_ccsi(home, "search", "restoreneedle").stdout, initial)


class SearchEquivalenceTest(unittest.TestCase):
  def test_same_corpus_has_identical_legacy_and_contentless_stdout(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      cc = cc_session(home, "equivalence", "共用索引 queryneedle 0% Git settings.json\nsecond line")
      with cc.open("a") as file:
        for content in (
          "<command-name>/review-spec</command-name><command-args>fixed packet</command-args>",
          "<task-notification><summary>oracle task finished</summary><result>expected evidence</result></task-notification>",
          [{"type": "tool_use", "name": "Bash", "input": {"command": "git-closeout"}}],
          [{"type": "tool_use", "name": "Widget", "input": {"options": {"token": "structuredneedle"}}}],
        ):
          file.write(json.dumps({"type": "assistant", "timestamp": "2026-10-19T00:00:01Z",
                                 "message": {"role": "assistant", "content": content}}) + "\n")
      write_codex_rollout(home / ".codex/sessions/probe/rollout.jsonl")
      pi = home / ".pi/agent/sessions/probe/pi.jsonl"
      pi.parent.mkdir(parents=True)
      pi.write_text(json.dumps({"type": "message", "message": {"role": "user", "content": "pineedle 共用索引"}}) + "\n")
      cc_session(home, "tied-one", "rankneedle")
      cc_session(home, "tied-two", "rankneedle")
      old_env = {"CCSI_DB_DIR": str(home / "old-index")}
      run_ccsi(home, "index", script=LEGACY_SCRIPT, extra_env=old_env)
      run_ccsi(home, "index")
      cases = (
        (("共用索引", "-C", "2"), ">>>共用索引<<<"),
        (("settings.json",), ">>>settings.json<<<"),
        (("queryneedle", "0%"), "0%"),
        (("queryneedle", "pi"), "(no hits)\n"),
        (("共用索引", "--vendor", "pi"), "--- [pi]"),
        (("共用索引", "--exclude-session", "equivalence"), "--- [pi]"),
        (("oracle task finished", "-C", "1"), "expected evidence"),
        (("review-spec",), "fixed packet"),
        (("git-closeout",), ">>>git-closeout<<<"),
        (("structuredneedle",), "[Widget]"),
        (("spawn_agent", "--vendor", "codex"), "--- [codex]"),
        (("rankneedle", "-k", "1"), ">>>rankneedle<<<"),
        (("never-indexed",), "(no hits)\n"),
      )
      compared = 0
      for args, expected in cases:
        with self.subTest(args=args):
          old = run_ccsi(home, "search", *args, script=LEGACY_SCRIPT, extra_env=old_env, text=False).stdout
          new = run_ccsi(home, "search", *args, text=False).stdout
          self.assertIn(expected.encode(), old)
          self.assertEqual(new, old)
          if "-C" in args:
            self.assertEqual(run_ccsi(home, "search", *args, extra_env=old_env, text=False).stdout, old)
          compared += 1
      self.assertGreater(compared, 0)
      print(f"\n{compared}/{len(cases)} CLI queries have identical stdout", flush=True)

  def test_only_approved_fixture_changes_differ_between_versions(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      deleted = cc_session(home, "delete", "gonefromdisk")
      appended = cc_session(home, "append", "anchorneedle old text")
      old_env = {"CCSI_DB_DIR": str(home / "old-index")}
      run_ccsi(home, "index", script=LEGACY_SCRIPT, extra_env=old_env)
      run_ccsi(home, "index")

      def old_search(*args):
        return run_ccsi(home, "search", *args, script=LEGACY_SCRIPT, extra_env=old_env).stdout

      original_context = old_search("anchorneedle", "-C", "1")
      self.assertIn(">>>anchorneedle<<< old text", original_context)
      self.assertIn("  > [user 2026-10-19T00:00:00Z] anchorneedle old text\n", original_context)
      self.assertEqual(run_ccsi(home, "search", "anchorneedle", "-C", "1").stdout, original_context)
      self.assertIn(deleted.name, old_search("gonefromdisk"))
      self.assertIn(deleted.name, run_ccsi(home, "search", "gonefromdisk").stdout)
      deleted.unlink()
      with appended.open("a") as file:
        file.write(json.dumps({"type": "assistant", "timestamp": "2026-10-19T00:00:01Z",
                               "message": {"role": "assistant", "content": "new adjacent row"}}) + "\n")
      self.assertEqual(old_search("anchorneedle", "-C", "1"), original_context)
      self.assertEqual(run_ccsi(home, "search", "anchorneedle", "-C", "1").stdout,
                       original_context + "  + [assistant 2026-10-19T00:00:01Z] new adjacent row\n")
      run_ccsi(home, "index", script=LEGACY_SCRIPT, extra_env=old_env)
      run_ccsi(home, "index")
      self.assertIn(deleted.name, old_search("gonefromdisk"))
      self.assertEqual(run_ccsi(home, "search", "gonefromdisk").stdout, "(no hits)\n")


class IndexSafetyTest(unittest.TestCase):
  def test_unreadable_file_is_skipped_without_losing_index_entries(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      blocked = cc_session(home, "blocked", "sharedreadneedle old text")
      available = cc_session(home, "available", "sharedreadneedle other text")
      self.assertIn("rows=2 ", run_ccsi(home, "index").stdout)
      before = run_ccsi(home, "search", "sharedreadneedle").stdout
      self.assertIn(blocked.name, before)
      self.assertIn(available.name, before)

      changed_mtime = blocked.stat().st_mtime + 10
      os.utime(blocked, (changed_mtime, changed_mtime))
      blocked.chmod(0)
      try:
        self.assertIn("updated=0 failed=1 rows=2 ", run_ccsi(home, "index").stdout)
        result = run_ccsi(home, "search", "sharedreadneedle")
        self.assertIn(available.name, result.stdout)
        self.assertNotIn(blocked.name, result.stdout)
        self.assertEqual(result.stderr, "")
      finally:
        blocked.chmod(0o600)

      self.assertEqual(run_ccsi(home, "search", "sharedreadneedle").stdout, before)
      self.assertIn("updated=1 failed=0 rows=2 ", run_ccsi(home, "index").stdout)

  def test_changed_file_replaces_existing_messages(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      session = home / ".claude/projects/probe/session.jsonl"
      session.parent.mkdir(parents=True)
      session.write_text(json.dumps({
        "timestamp": "2026-09-02T00:00:00Z",
        "message": {"role": "user", "content": "oldneedle"},
      }) + "\n")
      run_ccsi(home, "index")

      session.write_text(json.dumps({
        "timestamp": "2026-09-02T00:01:00Z",
        "message": {"role": "user", "content": "newneedle"},
      }) + "\n")
      changed_mtime = session.stat().st_mtime + 10
      os.utime(session, (changed_mtime, changed_mtime))
      run_ccsi(home, "index")

      db_path = db_path_for(home)
      with closing(sqlite3.connect(db_path)) as db:
        old_count = db.execute(
          "SELECT count(*) FROM messages WHERE messages MATCH 'oldneedle'",
        ).fetchone()[0]
        new_count = db.execute(
          "SELECT count(*) FROM messages WHERE messages MATCH 'newneedle'",
        ).fetchone()[0]

      self.assertEqual(old_count, 0)
      self.assertEqual(new_count, 1)


def write_codex_rollout(path, session_id="01a0aaaa-0000-7000-8000-000000000001"):
  path.parent.mkdir(parents=True, exist_ok=True)
  rows = [
    {"timestamp": "2026-09-13T00:00:00Z", "type": "session_meta", "payload": {"id": session_id, "cwd": "/tmp/proj", "originator": "Codex Desktop", "source": {"subagent": {"thread_spawn": {"agent_role": "cc_judge"}}}}},
    {"timestamp": "2026-09-13T00:00:01Z", "type": "turn_context", "payload": {"cwd": "/tmp/proj", "model": "gpt-5.6-luna", "effort": "max"}},
    {"timestamp": "2026-09-13T00:00:02Z", "type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "codexneedle please"}]}},
    {"timestamp": "2026-09-13T00:00:03Z", "type": "response_item", "payload": {"type": "function_call", "name": "spawn_agent", "arguments": json.dumps({"agent_type": "cc_impl", "message": "do it"})}},
    {"timestamp": "2026-09-13T00:00:04Z", "type": "response_item", "payload": {"type": "function_call_output", "output": "spawned"}},
    {"timestamp": "2026-09-13T00:00:05Z", "type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "done codexreply"}]}},
  ]
  path.write_text("".join(json.dumps(r) + "\n" for r in rows))


class DualVendorTest(unittest.TestCase):
  def test_codex_rollouts_are_indexed_and_tagged(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      cc = home / ".claude/projects/probe/session.jsonl"
      cc.parent.mkdir(parents=True)
      cc.write_text(json.dumps({"type": "user", "timestamp": "2026-09-13T00:00:00Z", "message": {"role": "user", "content": "ccneedle here"}}) + "\n")
      write_codex_rollout(home / ".codex/sessions/2026/09/13/rollout-2026-09-13T00-00-00-01a0aaaa.jsonl")
      write_codex_rollout(home / ".codex/archived_sessions/rollout-2026-09-01T00-00-00-01a0bbbb.jsonl", "01a0bbbb-0000-7000-8000-000000000002")
      out = run_ccsi(home, "index").stdout
      self.assertIn("scanned=3 updated=3", out)

      hits = run_ccsi(home, "search", "codexneedle").stdout
      self.assertEqual(hits.count("--- [codex]"), 2)
      self.assertIn("rollout-2026-09-01T00-00-00-01a0bbbb.jsonl", hits)
      self.assertIn("--- [cc] probe/session.jsonl", run_ccsi(home, "search", "ccneedle").stdout)
      self.assertIn("[>>>spawn_agent<<<] {", run_ccsi(home, "search", "spawn_agent").stdout)
      self.assertIn("--- [codex]", run_ccsi(home, "search", "codexneedle", "--vendor", "codex").stdout)
      self.assertIn("--- [cc]", run_ccsi(home, "search", "ccneedle", "--vendor", "cc").stdout)
      self.assertEqual(run_ccsi(home, "search", "codexneedle", "--vendor", "cc").stdout.strip(), "(no hits)")
      self.assertEqual(run_ccsi(home, "search", "ccneedle", "--vendor", "codex").stdout.strip(), "(no hits)")

  def test_events_stream_normalizes_both_formats(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      cc = home / ".claude/projects/probe/abc.jsonl"
      cc.parent.mkdir(parents=True)
      cc.write_text(
        json.dumps({"type": "user", "sessionId": "abc", "cwd": "/tmp/proj", "timestamp": "2026-09-13T00:00:00Z", "message": {"role": "user", "content": "hello"}}) + "\n"
        + json.dumps({"type": "assistant", "sessionId": "abc", "timestamp": "2026-09-13T00:00:01Z", "message": {"role": "assistant", "model": "claude-fable-5-1", "content": [{"type": "text", "text": "hi"}, {"type": "tool_use", "id": "t1", "name": "Agent", "input": {"subagent_type": "routed-judge", "model": "opus", "prompt": "judge"}}]}}) + "\n"
      )
      write_codex_rollout(home / ".codex/sessions/2026/09/13/rollout-x.jsonl")
      events = [json.loads(l) for l in run_ccsi(home, "events").stdout.splitlines()]
      vendors = {e["vendor"] for e in events}
      self.assertEqual(vendors, {"cc", "codex"})
      cc_agent = [e for e in events if e["vendor"] == "cc" and e["kind"] == "tool_call"][0]
      self.assertEqual((cc_agent["tool"], cc_agent["agent_type"], cc_agent["agent_model"], cc_agent["model"]), ("Agent", "routed-judge", "opus", "claude-fable-5-1"))
      spawn = [e for e in events if e["vendor"] == "codex" and e["kind"] == "tool_call"][0]
      self.assertEqual((spawn["tool"], spawn["agent_type"], spawn["model"], spawn["effort"], spawn["agent_role"], spawn["cwd"]), ("spawn_agent", "cc_impl", "gpt-5.6-luna", "max", "cc_judge", "/tmp/proj"))
      only_tool = run_ccsi(home, "events", "--vendor", "codex", "--kind", "tool_call", "--tool", "spawn_agent").stdout.splitlines()
      self.assertEqual(len(only_tool), 1)
      self.assertEqual(run_ccsi(home, "events", "--since", "2027-01-01").stdout, "")


class StructuredToolInputTest(unittest.TestCase):
  def test_object_valued_tool_arguments_are_indexed_without_crashing(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      session = home / ".claude/projects/probe/structured.jsonl"
      session.parent.mkdir(parents=True)
      session.write_text(
        json.dumps({
          "type": "assistant",
          "sessionId": "structured",
          "timestamp": "2026-09-19T00:00:00Z",
          "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "mcp__mongodb__count", "input": {"query": {"endDate": None, "tag": "objectneedle"}}},
            {"type": "tool_use", "id": "t2", "name": "Artifact", "input": {"query": {"limit": 5, "cursor": "cursorneedle"}}},
          ]},
        }) + "\n"
        + json.dumps({
          "type": "assistant",
          "sessionId": "structured",
          "timestamp": "2026-09-19T00:00:01Z",
          "message": {"role": "assistant", "content": [
            {"type": "text", "text": {"unexpected": "textneedle"}},
          ]},
        }) + "\n"
      )

      run_ccsi(home, "index")

      for needle in ("objectneedle", "cursorneedle", "textneedle"):
        self.assertIn("structured.jsonl", run_ccsi(home, "search", needle).stdout, needle)


class SearchQueryTest(unittest.TestCase):
  def test_empty_index_still_validates_query_syntax(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      old_env = {"CCSI_DB_DIR": str(home / "legacy")}
      for query, code in (("missingneedle OR", 1), ("git-closeout", 0)):
        with self.subTest(query=query):
          expected = run_ccsi(home, "search", query, check=False, script=LEGACY_SCRIPT, extra_env=old_env)
          result = run_ccsi(home, "search", query, check=False)
          self.assertEqual(expected.returncode, code)
          self.assertEqual((result.returncode, result.stdout, result.stderr),
                           (expected.returncode, expected.stdout, expected.stderr))
  def test_queries_with_fts_punctuation_match_literally(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      session = home / ".claude/projects/probe/punct.jsonl"
      session.parent.mkdir(parents=True)
      session.write_text(json.dumps({
        "type": "user",
        "sessionId": "punct",
        "timestamp": "2026-09-24T00:00:00Z",
        "message": {"role": "user", "content": "check config.yaml under ~/.cli-proxy-api/logs today"},
      }) + "\n")

      run_ccsi(home, "index")

      for query in ("config.yaml", "~/.cli-proxy-api/logs", "cli-proxy-api"):
        self.assertIn("punct.jsonl", run_ccsi(home, "search", query).stdout, query)


class IndexPerformanceTest(unittest.TestCase):
  def test_initial_build_avoids_quadratic_fts_scans(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      root = home / ".claude/projects/probe"
      root.mkdir(parents=True)
      line = json.dumps({
        "timestamp": "2026-09-02T00:00:00Z",
        "message": {"role": "user", "content": "benchmark needle"},
      }) + "\n"
      for index in range(15_000):
        (root / f"{index:05d}.jsonl").write_text(line)

      started = time.monotonic()
      run_ccsi(home, "index")
      elapsed = time.monotonic() - started

      db_path = db_path_for(home)
      with closing(sqlite3.connect(db_path)) as db:
        file_count = db.execute("SELECT count(*) FROM files").fetchone()[0]
        message_count = db.execute("SELECT count(*) FROM messages").fetchone()[0]

      self.assertEqual(file_count, 15_000)
      self.assertEqual(message_count, 15_000)
      self.assertLess(elapsed, 10, f"initial index took {elapsed:.1f}s")


class ObeliskEnhancementsTest(unittest.TestCase):
  def test_append_only_cursor_and_half_line_recovery(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      session = home / ".claude/projects/probe/append.jsonl"
      session.parent.mkdir(parents=True)
      first = json.dumps({"type": "user", "timestamp": "2026-10-19T00:00:00Z", "message": {"role": "user", "content": "firstlinealpha"}}) + "\n"
      half = '{"type": "assistant", "timestamp": "2026-10-19T00:00:01Z", "message": {"role": "assistant", "content": "secondline'
      session.write_text(first + half)
      run_ccsi(home, "index")

      self.assertIn("firstlinealpha", run_ccsi(home, "search", "firstlinealpha").stdout)
      self.assertEqual(run_ccsi(home, "search", "secondlinebeta").stdout.strip(), "(no hits)")

      with open(session, "a") as f:
        f.write('beta"}}\n')
      t = session.stat().st_mtime + 5
      os.utime(session, (t, t))
      run_ccsi(home, "index")

      self.assertIn("firstlinealpha", run_ccsi(home, "search", "firstlinealpha").stdout)
      self.assertIn("secondlinebeta", run_ccsi(home, "search", "secondlinebeta").stdout)
      db_path = db_path_for(home)
      with closing(sqlite3.connect(db_path)) as db:
        total = db.execute("SELECT count(*) FROM messages").fetchone()[0]
      self.assertEqual(total, 2)

  def test_interleaved_context_and_exclude_session(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      s_a = home / ".claude/projects/probe/sess-alpha.jsonl"
      s_b = home / ".claude/projects/probe/sess-bravo.jsonl"
      s_a.parent.mkdir(parents=True)
      s_a.write_text(
        json.dumps({"type": "user", "timestamp": "2026-10-19T00:00:01Z", "message": {"role": "user", "content": "alpha step one"}}) + "\n"
        + json.dumps({"type": "assistant", "timestamp": "2026-10-19T00:00:02Z", "message": {"role": "assistant", "content": "alpha step two"}}) + "\n"
      )
      s_b.write_text(
        "".join(
          json.dumps({"type": "user", "timestamp": f"2026-10-19T00:01:{i:02d}Z", "message": {"role": "user", "content": f"bravo filler {i} sharedkeyword"}}) + "\n"
          for i in range(10)
        )
      )
      run_ccsi(home, "index")

      with open(s_a, "a") as f:
        f.write(json.dumps({"type": "user", "timestamp": "2026-10-19T00:02:00Z", "message": {"role": "user", "content": "alpha targetneedle sharedkeyword"}}) + "\n")
        f.write(json.dumps({"type": "assistant", "timestamp": "2026-10-19T00:02:01Z", "message": {"role": "assistant", "content": "alpha step four"}}) + "\n")
      t = s_a.stat().st_mtime + 5
      os.utime(s_a, (t, t))
      run_ccsi(home, "index")

      ctx_out = run_ccsi(home, "search", "targetneedle", "-C", "2").stdout
      self.assertIn("alpha step one", ctx_out)
      self.assertIn("alpha step two", ctx_out)
      self.assertIn("alpha step four", ctx_out)
      self.assertNotIn("bravo filler", ctx_out)

      excl_out = run_ccsi(home, "search", "sharedkeyword", "--exclude-session", "sess-bravo").stdout
      self.assertIn("sess-alpha.jsonl", excl_out)
      self.assertNotIn("sess-bravo.jsonl", excl_out)

  def test_tool_summary_and_envelope_normalization(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      s = home / ".claude/projects/probe/tools.jsonl"
      mirror = home / ".claude/projects/codex/mirrored.jsonl"
      s.parent.mkdir(parents=True)
      mirror.parent.mkdir(parents=True)
      mirror.write_text(json.dumps({"type": "user", "timestamp": "2026-10-19T00:00:00Z", "message": {"role": "user", "content": "mirrorneedle"}}) + "\n")
      s.write_text(
        json.dumps({"type": "user", "timestamp": "2026-10-19T00:00:01Z", "message": {"role": "user", "content": "<command-message>github-repo-research</command-message>\n<command-name>/github-repo-research</command-name>\n<command-args>https://github.com/tommy0103/obelisk</command-args>\nBase directory for this skill: /tmp\n# Huge Skill Body shouldbefiltered"}}) + "\n"
        + json.dumps({"type": "user", "timestamp": "2026-10-19T00:00:02Z", "message": {"role": "user", "content": "Base directory for this skill: /tmp\npure skill dump noiseshouldnotmatch"}}) + "\n"
        + json.dumps({"type": "user", "timestamp": "2026-10-19T00:00:03Z", "message": {"role": "user", "content": "<task-notification><task-id>a1</task-id><summary>Agent finished</summary><result>verdictpassneedle</result></task-notification>"}}) + "\n"
        + json.dumps({"type": "assistant", "timestamp": "2026-10-19T00:00:04Z", "message": {"role": "assistant", "content": [
          {"type": "tool_use", "id": "u1", "name": "Edit", "input": {"file_path": "/Users/test/advisor.md"}},
          {"type": "tool_use", "id": "u2", "name": "Skill", "input": {"skill": "check-my-stack", "args": "obelisk"}},
          {"type": "tool_use", "id": "u3", "name": "StructuredOutput", "input": {"verdict": "structuredverdictneedle"}},
          {"type": "tool_use", "id": "u4", "name": "TaskList", "input": {}},
        ]}}) + "\n"
      )
      run_ccsi(home, "index")

      self.assertIn("tools.jsonl", run_ccsi(home, "search", "github-repo-research").stdout)
      self.assertIn("tools.jsonl", run_ccsi(home, "search", "tommy0103/obelisk").stdout)
      self.assertEqual(run_ccsi(home, "search", "noiseshouldnotmatch").stdout.strip(), "(no hits)")
      self.assertIn("tools.jsonl", run_ccsi(home, "search", "verdictpassneedle").stdout)
      self.assertIn("tools.jsonl", run_ccsi(home, "search", "advisor.md").stdout)
      self.assertIn("tools.jsonl", run_ccsi(home, "search", "check-my-stack").stdout)
      self.assertIn("tools.jsonl", run_ccsi(home, "search", "structuredverdictneedle").stdout)
      self.assertEqual(run_ccsi(home, "search", "TaskList").stdout.strip(), "(no hits)")
      self.assertEqual(run_ccsi(home, "search", "mirrorneedle").stdout.strip(), "(no hits)")

  def test_pi_vendor_indexing_and_events(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      pi_file = home / ".pi/agent/sessions/--tmp--/2026-10-19_pi1.jsonl"
      pi_file.parent.mkdir(parents=True)
      pi_file.write_text(
        json.dumps({"type": "session", "version": 3, "id": "pi-sess-1", "timestamp": "2026-10-19T01:00:00.000Z", "cwd": "/tmp/piwork"}) + "\n"
        + json.dumps({"type": "model_change", "id": "m1", "timestamp": "2026-10-19T01:00:01.000Z", "provider": "openai", "modelId": "gpt-5.6-luna"}) + "\n"
        + json.dumps({"type": "message", "id": "m2", "timestamp": "2026-10-19T01:00:02.000Z", "message": {"role": "user", "content": [{"type": "text", "text": "pineedle question"}], "timestamp": 1760000002000}}) + "\n"
        + json.dumps({"type": "message", "id": "m3", "timestamp": "2026-10-19T01:00:03.000Z", "message": {"role": "assistant", "content": [{"type": "toolCall", "id": "c1", "name": "read", "arguments": {"file_path": "/tmp/pifile.ts"}}], "timestamp": 1760000003000}}) + "\n"
        + json.dumps({"type": "message", "id": "m4", "timestamp": "2026-10-19T01:00:04.000Z", "message": {"role": "toolResult", "toolName": "read", "content": [{"type": "text", "text": "piresultnotindexed"}], "timestamp": 1760000004000}}) + "\n"
      )
      run_ccsi(home, "index")

      self.assertIn("--- [pi]", run_ccsi(home, "search", "pineedle", "--vendor", "pi").stdout)
      self.assertIn("pifile.ts", run_ccsi(home, "search", "pifile.ts", "--vendor", "pi").stdout)
      self.assertEqual(run_ccsi(home, "search", "piresultnotindexed").stdout.strip(), "(no hits)")
      evs = [json.loads(l) for l in run_ccsi(home, "events", "--vendor", "pi", "--since", "2026-10-19").stdout.splitlines()]
      self.assertEqual([e["kind"] for e in evs], ["session_meta", "text", "tool_call", "tool_result"])
      self.assertEqual(evs[1]["model"], "openai/gpt-5.6-luna")

  def test_short_token_guard_mixed_like_and_context_central_row(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      s = home / ".claude/projects/probe/short-and-ctx.jsonl"
      s.parent.mkdir(parents=True)
      long_tail = "尾端關鍵結論九八七六五"
      filler = "中段填充文字" * 20
      s.write_text(
        json.dumps({"type": "user", "timestamp": "2026-10-19T02:00:01Z", "message": {"role": "user", "content": f"Herdr 左下角 狀態 100% 測試 假綠 {filler} {long_tail}"}}) + "\n"
        + json.dumps({"type": "user", "timestamp": "2026-10-19T02:00:02Z", "message": {"role": "user", "content": "Herdr 左下角 1000 無關內容"}}) + "\n"
        + json.dumps({"type": "user", "timestamp": "2026-10-19T02:00:03Z", "message": {"role": "user", "content": "betaneedle standalone row"}}) + "\n"
      )
      run_ccsi(home, "index")

      pure_short = run_ccsi(home, "search", "白話", check=False)
      self.assertEqual(pure_short.returncode, 2)
      self.assertIn("trigram index requires >=3-char terms", pure_short.stderr)

      two_shorts = run_ccsi(home, "search", "測試", "假綠", check=False)
      self.assertEqual(two_shorts.returncode, 2)

      bool_short = run_ccsi(home, "search", "Herdr AND 狀態", check=False)
      self.assertEqual(bool_short.returncode, 2)

      quoted_short = run_ccsi(home, "search", 'Herdr "狀態"', check=False)
      self.assertEqual(quoted_short.returncode, 2)

      quoted_phrase = run_ccsi(home, "search", '"測試 假綠"')
      self.assertIn("short-and-ctx.jsonl", quoted_phrase.stdout)

      mixed_hit = run_ccsi(home, "search", "Herdr", "左下角", "狀態")
      self.assertEqual(mixed_hit.stdout.count("--- [cc]"), 1)

      mixed_miss = run_ccsi(home, "search", "Herdr", "左下角", "亂講")
      self.assertEqual(mixed_miss.stdout.strip(), "(no hits)")

      escaped_pct = run_ccsi(home, "search", "Herdr", "左下角", "0%")
      self.assertEqual(escaped_pct.stdout.count("--- [cc]"), 1)

      or_query = run_ccsi(home, "search", "左下角 OR betaneedle")
      self.assertEqual(or_query.stdout.count("--- [cc]"), 3)

      punct_or = run_ccsi(home, "search", "100% OR betaneedle")
      self.assertEqual(punct_or.stdout.count("--- [cc]"), 2)

      ctx_out = run_ccsi(home, "search", "Herdr 左下角 狀態", "-C", "1").stdout
      self.assertIn(long_tail, ctx_out)

      db_path = db_path_for(home)
      self.assertEqual(db_path.stat().st_mode & 0o777, 0o600)
      self.assertEqual(db_path.parent.stat().st_mode & 0o777, 0o700)

  def test_custom_env_vars_override_roots_and_db_dir(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      custom_cc = home / "custom-claude"
      custom_db = home / "custom-cache/ccsi-db"
      s = custom_cc / "projects/probe/envtest.jsonl"
      s.parent.mkdir(parents=True)
      s.write_text(
        json.dumps({"type": "user", "timestamp": "2026-10-19T03:00:00Z", "message": {"role": "user", "content": "customenvneedle"}}) + "\n"
      )
      extra = {"CLAUDE_CONFIG_DIR": str(custom_cc), "CCSI_DB_DIR": str(custom_db)}
      run_ccsi(home, "index", extra_env=extra)
      self.assertTrue((custom_db / "index.sqlite").exists())
      out = run_ccsi(home, "search", "customenvneedle", extra_env=extra).stdout
      self.assertIn("envtest.jsonl", out)

  def test_symlinked_config_dirs_share_one_copy_of_each_transcript(self):
    # Several account config dirs link their projects/ to the same transcripts; indexing from each
    # used to store every file once per config dir.
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      real = home / ".claude"
      s = real / "projects/probe/shared.jsonl"
      s.parent.mkdir(parents=True)
      s.write_text(
        json.dumps({"type": "user", "timestamp": "2026-11-19T07:00:00Z", "message": {"role": "user", "content": "symlinkneedle"}}) + "\n"
      )
      team = home / ".claude-team"
      team.mkdir()
      (team / "projects").symlink_to(real / "projects")
      first = run_ccsi(home, "index").stdout
      second = run_ccsi(home, "index", extra_env={"CLAUDE_CONFIG_DIR": str(team)}).stdout
      self.assertIn("rows=1", first)
      self.assertIn("updated=0", second)
      self.assertIn("rows=1", second)
      out = run_ccsi(home, "search", "symlinkneedle", extra_env={"CLAUDE_CONFIG_DIR": str(team)}).stdout
      self.assertEqual(out.count("--- [cc]"), 1)


def load_ccsi_module():
  loader = SourceFileLoader("ccsi_module", str(SCRIPT))
  spec = importlib.util.spec_from_loader(loader.name, loader)
  module = importlib.util.module_from_spec(spec)
  loader.exec_module(module)
  return module


def compact_cc_line(ts, content, role="user"):
  return json.dumps(
    {"type": role, "timestamp": ts, "message": {"role": role, "content": content}},
    separators=(",", ":"),
  ) + "\n"


class LargeFilePrefilterTest(unittest.TestCase):
  def test_compact_json_large_file_uses_binary_seek_and_matches_legacy(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      session = home / ".claude/projects/probe/compact-large.jsonl"
      session.parent.mkdir(parents=True)
      padding = "p" * 350
      lines = []
      for i in range(120):
        ts = f"2026-11-20T00:{i // 60:02d}:{i % 60:02d}Z"
        if i == 55:
          content = f"compactneedle wrong only {padding}"
        elif i == 58:
          content = f"ctx before two {padding}"
        elif i == 59:
          content = f"ctx before one {padding}"
        elif i == 60:
          content = f"compactneedle zx target {padding}"
        elif i == 61:
          content = f"ctx after one {padding}"
        elif i == 62:
          content = f"ctx after two {padding}"
        else:
          content = f"filler row {i} {padding}"
        lines.append(compact_cc_line(ts, content))
      session.write_text("".join(lines))
      self.assertGreater(session.stat().st_size, 32768)

      ccsi_mod = load_ccsi_module()
      fd = os.open(session, os.O_RDONLY)
      try:
        spans = ccsi_mod.seek_ts_spans_pread(fd, session.stat().st_size, b"2026-11-20T00:01:00Z")
      finally:
        os.close(fd)
      self.assertIsNotNone(spans)
      self.assertEqual(len(spans), 1)
      self.assertIn(b"compactneedle zx target", spans[0][2])

      old_env = {"CCSI_DB_DIR": str(home / "legacy")}
      run_ccsi(home, "index", script=LEGACY_SCRIPT, extra_env=old_env)
      run_ccsi(home, "index")

      legacy_out = run_ccsi(home, "search", "compactneedle", "zx", "-C", "2", script=LEGACY_SCRIPT, extra_env=old_env).stdout
      new_out = run_ccsi(home, "search", "compactneedle", "zx", "-C", "2").stdout
      self.assertEqual(new_out, legacy_out)
      self.assertEqual(new_out.count("--- [cc]"), 1)
      self.assertIn("  - [user 2026-11-20T00:00:58Z] ctx before two", new_out)
      self.assertIn("  - [user 2026-11-20T00:00:59Z] ctx before one", new_out)
      self.assertIn("  > [user 2026-11-20T00:01:00Z] compactneedle zx target", new_out)
      self.assertIn("  + [user 2026-11-20T00:01:01Z] ctx after one", new_out)
      self.assertIn("  + [user 2026-11-20T00:01:02Z] ctx after two", new_out)

  def test_scientific_notation_timestamp_in_large_file_does_not_false_reject(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      session = home / ".claude/projects/probe/sci-ts.jsonl"
      session.parent.mkdir(parents=True)
      padding = "s" * 400
      lines = [
        compact_cc_line(f"2026-11-20T00:{i // 60:02d}:{i % 60:02d}Z", f"filler {i} {padding}")
        for i in range(90)
      ]
      lines.insert(40, f'{{"type":"user","timestamp":1000000000000.0,"message":{{"role":"user","content":"scinotationneedle canonical miss {padding}"}}}}\n')
      lines.insert(41, f'{{"type":"user","timestamp":1e12,"message":{{"role":"user","content":"scinotationneedle zx matched {padding}"}}}}\n')
      lines.insert(46, f'{{"type":"user","timestamp":2e12,"message":{{"role":"user","content":"scinotationneedle unmatched {padding}"}}}}\n')
      session.write_text("".join(lines))
      self.assertGreater(session.stat().st_size, 32768)

      run_ccsi(home, "index")
      long_hits = run_ccsi(home, "search", "scinotationneedle").stdout
      self.assertEqual(long_hits.count("--- [cc]"), 3)

      short_hits = run_ccsi(home, "search", "scinotationneedle", "zx").stdout
      self.assertEqual(short_hits.count("--- [cc]"), 1)
      self.assertIn("1000000000000.0", short_hits)
      self.assertIn(">>>scinotationneedle<<<", short_hits)

      with session.open("a") as f:
        f.write(compact_cc_line("2026-11-20T01:00:00Z", "appended active tail"))
      self.assertEqual(run_ccsi(home, "search", "scinotationneedle", "zx").stdout, short_hits)

  def test_unicode_escape_and_clock_rollback_in_large_file_fallback(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      session = home / ".claude/projects/probe/rollback-escape.jsonl"
      session.parent.mkdir(parents=True)
      padding = "u" * 400
      lines = [
        compact_cc_line(f"2026-11-20T01:{i // 60:02d}:{i % 60:02d}Z", f"before {i} {padding}")
        for i in range(180)
      ]
      lines.append(compact_cc_line("2026-11-20T00:04:59Z", f"rollback ctx prev {padding}"))
      lines.append(compact_cc_line("2026-11-20T00:05:00Z", f"rollbackneedle zx hit {padding}"))
      lines.append(compact_cc_line("2026-11-20T00:05:01Z", f"rollback ctx next {padding}"))
      lines.append(
        f'{{"type":"user","timestamp":"2026-11-20T00:06:00\\u005a","message":{{"role":"user","content":"escapeneedle \\u007a\\u0078 hit {padding}"}}}}\n'
      )
      for i in range(60):
        lines.append(compact_cc_line(f"2026-11-20T02:{i // 60:02d}:{i % 60:02d}Z", f"after {i} {padding}"))
      session.write_text("".join(lines))
      self.assertGreater(session.stat().st_size, 96_000)

      ccsi_mod = load_ccsi_module()
      fd = os.open(session, os.O_RDONLY)
      try:
        self.assertIsNone(ccsi_mod.seek_ts_spans_pread(fd, session.stat().st_size, b"2026-11-20T00:05:00Z"))
      finally:
        os.close(fd)

      old_env = {"CCSI_DB_DIR": str(home / "legacy")}
      run_ccsi(home, "index", script=LEGACY_SCRIPT, extra_env=old_env)
      run_ccsi(home, "index")

      for args in (("rollbackneedle", "zx", "-C", "1"), ("escapeneedle", "zx")):
        legacy_out = run_ccsi(home, "search", *args, script=LEGACY_SCRIPT, extra_env=old_env).stdout
        new_out = run_ccsi(home, "search", *args).stdout
        self.assertEqual(new_out, legacy_out)
        self.assertEqual(new_out.count("--- [cc]"), 1)

  def test_local_context_window_across_multichunk_lines(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      session = home / ".claude/projects/probe/multichunk-ctx.jsonl"
      session.parent.mkdir(parents=True)
      huge_before = "B" * 200_000 + " before-one-tail"
      huge_after = "A" * 200_000 + " after-one-tail"
      lines = [
        compact_cc_line("2026-11-20T00:00:01Z", "before-two-marker"),
        compact_cc_line("2026-11-20T00:00:02Z", huge_before),
        compact_cc_line("2026-11-20T00:00:03Z", "bigctxneedle zx center"),
        compact_cc_line("2026-11-20T00:00:04Z", huge_after),
        compact_cc_line("2026-11-20T00:00:05Z", "after-two-marker"),
      ]
      session.write_text("".join(lines))

      old_env = {"CCSI_DB_DIR": str(home / "legacy")}
      run_ccsi(home, "index", script=LEGACY_SCRIPT, extra_env=old_env)
      run_ccsi(home, "index")

      legacy_out = run_ccsi(home, "search", "bigctxneedle", "zx", "-C", "2", script=LEGACY_SCRIPT, extra_env=old_env).stdout
      new_out = run_ccsi(home, "search", "bigctxneedle", "zx", "-C", "2").stdout
      self.assertEqual(new_out, legacy_out)
      self.assertIn("  - [user 2026-11-20T00:00:01Z] before-two-marker\n", new_out)
      self.assertIn("  - [user 2026-11-20T00:00:02Z] BBBBB", new_out)
      self.assertIn("  > [user 2026-11-20T00:00:03Z] bigctxneedle zx center\n", new_out)
      self.assertIn("  + [user 2026-11-20T00:00:04Z] AAAAA", new_out)
      self.assertIn("  + [user 2026-11-20T00:00:05Z] after-two-marker\n", new_out)

      ccsi_mod = load_ccsi_module()
      fd = os.open(session, os.O_RDONLY)
      try:
        size = session.stat().st_size
        spans = ccsi_mod.seek_ts_spans_pread(fd, size, b"2026-11-20T00:00:03Z")
        self.assertIsNotNone(spans)
        ls, le, _ = spans[0]
        cb, ca = ccsi_mod.collect_local_context_pread(fd, size, str(session), "cc", ls, le, (), (), 2, 2)
      finally:
        os.close(fd)
      self.assertEqual([r[0] for r in cb], ["before-two-marker", huge_before[:8000]])
      self.assertEqual([r[0] for r in ca], [huge_after[:8000], "after-two-marker"])

  def test_growing_large_file_avoids_repeated_full_pread_across_candidates(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      session = home / ".claude/projects/probe/growing-large.jsonl"
      session.parent.mkdir(parents=True)
      padding = "g" * 1800
      lines = [
        compact_cc_line(
          f"2026-11-20T00:00:{i:02d}Z",
          f"activedupneedle activedupneedle activedupneedle filler {i} {padding}",
        )
        for i in range(20)
      ]
      lines.append(compact_cc_line("2026-11-20T00:00:50Z", f"activedupneedle zx winner {padding}"))
      session.write_text("".join(lines))
      self.assertGreater(session.stat().st_size, 32768)

      run_ccsi(home, "index")
      with session.open("a") as f:
        f.write(compact_cc_line("2026-11-20T00:01:00Z", "live appended line"))

      cli_out = run_ccsi(home, "search", "activedupneedle", "zx").stdout
      self.assertEqual(cli_out.count("--- [cc]"), 1)
      self.assertIn("2026-11-20T00:00:50Z", cli_out)

      ccsi_mod = load_ccsi_module()
      db_path = db_path_for(home)
      full_pread_calls = []
      orig_pread_exact = ccsi_mod.pread_exact

      def counting_pread_exact(fd, count, offset):
        if offset == 0 and count >= 32768:
          full_pread_calls.append(count)
        return orig_pread_exact(fd, count, offset)

      args = argparse.Namespace(k=10, vendor=None, exclude_session=[], context=0)
      buf = io.StringIO()
      with (
        mock.patch.object(ccsi_mod, "ROOTS", (("cc", str(home / ".claude/projects")),)),
        mock.patch.object(ccsi_mod, "ROOT", str(home / ".claude/projects")),
        mock.patch.object(ccsi_mod, "pread_exact", side_effect=counting_pread_exact),
        closing(sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)) as db,
        redirect_stdout(buf),
      ):
        found = ccsi_mod.search_contentless(db, ccsi_mod.extract_rows, args, "activedupneedle", ["zx"])

      self.assertEqual(found, 1)
      self.assertEqual(buf.getvalue(), cli_out)
      self.assertLessEqual(len(full_pread_calls), 1)

  def test_short_scan_2char_cjk_recency_context_and_escapes(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      older = home / ".claude/projects/probe/older-cjk.jsonl"
      newer = home / ".claude/projects/probe/newer-cjk.jsonl"
      escaped = home / ".claude/projects/probe/escaped-cjk.jsonl"
      older.parent.mkdir(parents=True)
      older.write_text(
        json.dumps({"type": "user", "timestamp": "2026-11-10T01:00:00Z", "message": {"role": "user", "content": "舊版記憶 衝突 紀錄"}}, ensure_ascii=False) + "\n"
      )
      newer.write_text(
        json.dumps({"type": "user", "timestamp": "2026-11-20T01:00:00Z", "message": {"role": "user", "content": "前文背景"}}, ensure_ascii=False) + "\n"
        + json.dumps({"type": "user", "timestamp": "2026-11-20T01:00:05Z", "message": {"role": "user", "content": "最新記憶與衝突的處理方式 V2"}}, ensure_ascii=False) + "\n"
        + json.dumps({"type": "user", "timestamp": "2026-11-20T01:00:10Z", "message": {"role": "user", "content": "後續結語"}}, ensure_ascii=False) + "\n"
      )
      # Write escaped \uXXXX JSON so raw UTF-8 bytes are absent on disk
      escaped.write_text(
        json.dumps({"type": "user", "timestamp": "2026-11-15T01:00:00Z", "message": {"role": "user", "content": "記憶 衝突 逸出測試"}}, ensure_ascii=True) + "\n"
      )
      os.utime(older, (1700000100, 1700000100))
      os.utime(escaped, (1700000200, 1700000200))
      os.utime(newer, (1700000300, 1700000300))
      run_ccsi(home, "index")

      # Default without --short-scan keeps exit 2 contract
      no_flag = run_ccsi(home, "search", "記憶", "衝突", check=False)
      self.assertEqual(no_flag.returncode, 2)
      self.assertIn("--short-scan", no_flag.stderr)

      # With --short-scan: newest file hits first, highlights tokens, supports -C context
      hit = run_ccsi(home, "search", "--short-scan", "-C", "1", "記憶", "衝突")
      self.assertEqual(hit.stdout.count("--- [cc]"), 3)
      lines = [l for l in hit.stdout.splitlines() if l.startswith("--- [cc]")]
      self.assertIn("newer-cjk.jsonl", lines[0])
      self.assertIn("escaped-cjk.jsonl", lines[1])
      self.assertIn("older-cjk.jsonl", lines[2])
      self.assertIn(">>>記憶<<<", hit.stdout)
      self.assertIn(">>>衝突<<<", hit.stdout)
      self.assertIn("  - [user 2026-11-20T01:00:00Z] 前文背景", hit.stdout)
      self.assertIn("  + [user 2026-11-20T01:00:10Z] 後續結語", hit.stdout)

      # Mixed ASCII case folding + CJK
      mixed = run_ccsi(home, "search", "--short-scan", "記憶", "v2")
      self.assertEqual(mixed.stdout.count("--- [cc]"), 1)
      self.assertIn("newer-cjk.jsonl", mixed.stdout)

      # Bounded --scan-limit respects newest files first
      bounded = run_ccsi(home, "search", "--short-scan", "--scan-limit", "1", "記憶", "衝突")
      self.assertEqual(bounded.stdout.count("--- [cc]"), 1)
      self.assertIn("newer-cjk.jsonl", bounded.stdout)

      # --exclude-session filters out excluded paths
      excluded = run_ccsi(home, "search", "--short-scan", "--exclude-session", "newer-cjk", "記憶", "衝突")
      self.assertNotIn("newer-cjk.jsonl", excluded.stdout)
      self.assertEqual(excluded.stdout.count("--- [cc]"), 2)

  def test_short_scan_rejects_boolean_syntax_single_char_and_negative_limit(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      cc_session(home, "s1", "白話 測試")
      run_ccsi(home, "index")

      bool_err = run_ccsi(home, "search", "--short-scan", "白話 AND 測試", check=False)
      self.assertEqual(bool_err.returncode, 2)

      single_char = run_ccsi(home, "search", "--short-scan", "a", check=False)
      self.assertEqual(single_char.returncode, 2)

      neg_limit = run_ccsi(home, "search", "--short-scan", "--scan-limit", "-1", "白話", check=False)
      self.assertNotEqual(neg_limit.returncode, 0)


class HardeningChaosTest(unittest.TestCase):
  def test_inplace_rewrite_larger_same_inode_replaces_old_rows(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      session = home / ".claude/projects/probe/rewrite-larger.jsonl"
      session.parent.mkdir(parents=True)
      session.write_text(json.dumps({
        "type": "user",
        "timestamp": "2026-10-19T00:00:00Z",
        "message": {"role": "user", "content": "oldshortneedle"},
      }) + "\n")
      orig_ino = session.stat().st_ino
      run_ccsi(home, "index")
      self.assertIn("oldshortneedle", run_ccsi(home, "search", "oldshortneedle").stdout)

      session.write_text(json.dumps({
        "type": "user",
        "timestamp": "2026-10-19T00:01:00Z",
        "message": {"role": "user", "content": "newmuchlongerneedle_after_inplace_rewrite"},
      }) + "\n")
      self.assertEqual(session.stat().st_ino, orig_ino)
      t = session.stat().st_mtime + 10
      os.utime(session, (t, t))
      run_ccsi(home, "index")

      self.assertIn(">>>newmuchlongerneedle<<<_after_inplace_rewrite", run_ccsi(home, "search", "newmuchlongerneedle").stdout)
      self.assertEqual(run_ccsi(home, "search", "oldshortneedle").stdout, "(no hits)\n")
      with closing(sqlite3.connect(db_path_for(home))) as db:
        old_cnt = db.execute("SELECT count(*) FROM messages WHERE messages MATCH 'oldshortneedle'").fetchone()[0]
        new_cnt = db.execute("SELECT count(*) FROM messages WHERE messages MATCH 'newmuchlongerneedle'").fetchone()[0]
      self.assertEqual(old_cnt, 0)
      self.assertEqual(new_cnt, 1)

  def test_inplace_rewrite_same_line_len_plus_append_reindexes(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      session = home / ".claude/projects/probe/rewrite-boundary.jsonl"
      session.parent.mkdir(parents=True)
      line1_old = json.dumps({
        "type": "user",
        "timestamp": "2026-10-19T00:00:00Z",
        "message": {"role": "user", "content": "firstold01"},
      }) + "\n"
      session.write_text(line1_old)
      run_ccsi(home, "index")

      line1_new = json.dumps({
        "type": "user",
        "timestamp": "2026-10-19T00:00:01Z",
        "message": {"role": "user", "content": "firstnew01"},
      }) + "\n"
      line2_new = json.dumps({
        "type": "assistant",
        "timestamp": "2026-10-19T00:00:02Z",
        "message": {"role": "assistant", "content": "secondappend02"},
      }) + "\n"
      self.assertEqual(len(line1_old.encode()), len(line1_new.encode()))
      session.write_text(line1_new + line2_new)
      t = session.stat().st_mtime + 10
      os.utime(session, (t, t))
      run_ccsi(home, "index")

      self.assertEqual(run_ccsi(home, "search", "firstold01").stdout, "(no hits)\n")
      self.assertIn("firstnew01", run_ccsi(home, "search", "firstnew01").stdout)
      self.assertIn("secondappend02", run_ccsi(home, "search", "secondappend02").stdout)
      with closing(sqlite3.connect(db_path_for(home))) as db:
        old_cnt = db.execute("SELECT count(*) FROM messages WHERE messages MATCH 'firstold01'").fetchone()[0]
      self.assertEqual(old_cnt, 0)

  def test_mtime_rollback_with_larger_size_forces_full_reindex(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      session = home / ".claude/projects/probe/mtime-rollback.jsonl"
      session.parent.mkdir(parents=True)
      session.write_text(json.dumps({
        "type": "user",
        "timestamp": "2026-10-19T00:00:00Z",
        "message": {"role": "user", "content": "rollbackoldneedle"},
      }) + "\n")
      future_ts = time.time() + 200
      os.utime(session, (future_ts, future_ts))
      run_ccsi(home, "index")

      session.write_text(json.dumps({
        "type": "user",
        "timestamp": "2026-10-19T00:00:00Z",
        "message": {"role": "user", "content": "rollbacknewneedle_extra_content"},
      }) + "\n")
      older_ts = future_ts - 150
      os.utime(session, (older_ts, older_ts))
      run_ccsi(home, "index")

      self.assertEqual(run_ccsi(home, "search", "rollbackoldneedle").stdout, "(no hits)\n")
      self.assertIn(">>>rollbacknewneedle<<<_extra_content", run_ccsi(home, "search", "rollbacknewneedle").stdout)

  def test_corrupt_deep_nested_and_partial_jsonl_do_not_crash(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      session = home / ".claude/projects/probe/corrupt.jsonl"
      session.parent.mkdir(parents=True)
      deep = ("[" * 3000) + ("]" * 3000) + "\n"
      raw = (
        (json.dumps({"type": "user", "timestamp": "2026-10-19T00:00:00Z", "message": {"role": "user", "content": "validbeforecorrupt"}}) + "\n").encode()
        + b"\xff\xfe{not valid json\n"
        + deep.encode()
        + b"123\n\"scalar\"\n[1,2]\nnull\n"
        + (json.dumps({"type": "assistant", "timestamp": "2026-10-19T00:00:01Z", "message": {"role": "assistant", "content": "validaftercorrupt"}}) + "\n").encode()
        + b'{"type":"user","timestamp":"2026-10-19T00:00:02Z","message":{"role":"user","content":"trailinghalf'
      )
      session.write_bytes(raw)

      idx = run_ccsi(home, "index")
      self.assertIn("failed=0 rows=2 ", idx.stdout)
      self.assertIn("validbeforecorrupt", run_ccsi(home, "search", "validbeforecorrupt").stdout)
      self.assertIn("validaftercorrupt", run_ccsi(home, "search", "validaftercorrupt").stdout)
      evs = run_ccsi(home, "events").stdout
      self.assertIn("validaftercorrupt", evs)

      with session.open("ab") as f:
        f.write(b'completed"}}\n')
      t = session.stat().st_mtime + 5
      os.utime(session, (t, t))
      idx2 = run_ccsi(home, "index")
      self.assertIn("failed=0 rows=3 ", idx2.stdout)
      self.assertIn("trailinghalfcompleted", run_ccsi(home, "search", "trailinghalfcompleted").stdout)

  def test_file_deleted_between_stat_and_open_is_pruned_without_failing(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      doomed = cc_session(home, "doomed", "doomedraceneedle")
      keeper = cc_session(home, "keeper", "keeperraceneedle")
      run_ccsi(home, "index")
      t = doomed.stat().st_mtime + 10
      os.utime(doomed, (t, t))

      ccsi_mod = load_ccsi_module()
      orig_read = ccsi_mod.read_jsonl_records

      def unlink_then_read(path, *a, **kw):
        if Path(path) == doomed and doomed.exists():
          doomed.unlink()
        return orig_read(path, *a, **kw)

      with (
        mock.patch.object(ccsi_mod, "ROOTS", (("cc", str(home / ".claude/projects")),)),
        mock.patch.object(ccsi_mod, "ROOT", str(home / ".claude/projects")),
        mock.patch.object(ccsi_mod, "read_jsonl_records", side_effect=unlink_then_read),
        closing(sqlite3.connect(db_path_for(home))) as db,
      ):
        scanned, updated, failed, total = ccsi_mod.update_index(db, {"cc"})

      self.assertEqual(failed, 0)
      self.assertEqual(total, 1)
      self.assertEqual(run_ccsi(home, "search", "doomedraceneedle").stdout, "(no hits)\n")
      self.assertIn(keeper.name, run_ccsi(home, "search", "keeperraceneedle").stdout)

  def test_corrupted_and_empty_sqlite_db_recovery_and_clean_search_errors(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      cc_session(home, "recover", "recoverdbneedle 記憶")
      run_ccsi(home, "index")
      db_path = db_path_for(home)

      db_path.write_bytes(b"NOT_A_VALID_SQLITE_HEADER_AT_ALL")
      search_bad = run_ccsi(home, "search", "recoverdbneedle", check=False)
      self.assertNotEqual(search_bad.returncode, 0)
      self.assertNotIn("Traceback", search_bad.stderr)

      partial_idx = run_ccsi(home, "index", "--vendor", "cc", check=False)
      self.assertNotEqual(partial_idx.returncode, 0)
      self.assertNotIn("Traceback", partial_idx.stderr)

      rebuilt = run_ccsi(home, "index")
      self.assertIn("rows=1 ", rebuilt.stdout)
      self.assertIn("recoverdbneedle", run_ccsi(home, "search", "recoverdbneedle").stdout)

      db_path.write_bytes(b"")
      empty_short = run_ccsi(home, "search", "--short-scan", "記憶", check=False)
      self.assertNotEqual(empty_short.returncode, 0)
      self.assertNotIn("Traceback", empty_short.stderr)

      with closing(sqlite3.connect(db_path)) as db:
        db.execute("PRAGMA user_version = 3")
        db.commit()
      broken_v3 = run_ccsi(home, "search", "recoverdbneedle", check=False)
      self.assertNotEqual(broken_v3.returncode, 0)
      self.assertNotIn("Traceback", broken_v3.stderr)

      run_ccsi(home, "index")
      self.assertIn("recoverdbneedle", run_ccsi(home, "search", "recoverdbneedle").stdout)

  def test_wal_upgrade_preserves_old_index_until_reader_closes(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      cc_session(home, "wal-old", "oldwalneedle")
      run_ccsi(home, "index", script=LEGACY_SCRIPT)
      db_path = db_path_for(home)
      before = db_path.stat().st_ino
      wal_path = db_path.with_name(db_path.name + "-wal")
      shm_path = db_path.with_name(db_path.name + "-shm")
      cc_session(home, "wal-new", "freshwalneedle")

      with closing(sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)) as reader:
        with closing(sqlite3.connect(db_path)) as writer:
          self.assertEqual(writer.execute("PRAGMA journal_mode=WAL").fetchone(), ("wal",))
          writer.execute("UPDATE files SET rows = 999")
          writer.commit()
          reader.execute("BEGIN")
          self.assertEqual(reader.execute("SELECT rows FROM files").fetchone(), (999,))

        self.assertTrue(wal_path.exists())
        self.assertTrue(shm_path.exists())
        blocked = run_ccsi(home, "index", check=False)
        self.assertNotEqual(blocked.returncode, 0, blocked.stdout)
        self.assertIn("kept the existing WAL index", blocked.stderr)
        self.assertEqual(db_path.stat().st_ino, before)
        self.assertTrue(wal_path.exists())
        self.assertTrue(shm_path.exists())
        self.assertEqual(reader.execute("SELECT rows FROM files").fetchone(), (999,))
        self.assertIn("oldwalneedle", run_ccsi(home, "search", "oldwalneedle").stdout)
        self.assertEqual(run_ccsi(home, "search", "freshwalneedle").stdout, "(no hits)\n")

      run_ccsi(home, "index")
      self.assertNotEqual(db_path.stat().st_ino, before)
      self.assertFalse(wal_path.exists())
      self.assertFalse(shm_path.exists())
      self.assertFalse(db_path.with_name(db_path.name + "-journal").exists())
      with closing(sqlite3.connect(db_path)) as db:
        self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 3)
      self.assertIn("oldwalneedle", run_ccsi(home, "search", "oldwalneedle").stdout)
      self.assertIn("freshwalneedle", run_ccsi(home, "search", "freshwalneedle").stdout)

  def test_cross_process_lock_timeout_and_recovery_after_release(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      cc_session(home, "locked", "locktestneedle")
      db_dir = db_path_for(home).parent
      db_dir.mkdir(parents=True, exist_ok=True)
      lock_path = db_dir / "index.lock"
      fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
      try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode("ascii"))
        blocked = run_ccsi(
          home,
          "index",
          check=False,
          extra_env={"CCSI_LOCK_TIMEOUT": "0.2"},
          timeout=5,
        )
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("timed out", blocked.stderr)
      finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

      recovered = run_ccsi(home, "index", extra_env={"CCSI_LOCK_TIMEOUT": "2"})
      self.assertIn("rows=1 ", recovered.stdout)
      self.assertIn("locktestneedle", run_ccsi(home, "search", "locktestneedle").stdout)

  def test_negative_k_context_and_scan_limit_rejected(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      cc_session(home, "bounds-a", "boundsneedle alpha 白話")
      cc_session(home, "bounds-b", "boundsneedle beta 白話")

      pre_neg_scan = run_ccsi(home, "search", "--short-scan", "--scan-limit", "-1", "白話", check=False)
      self.assertNotEqual(pre_neg_scan.returncode, 0)

      run_ccsi(home, "index")
      for args in (
        ("boundsneedle", "-k", "-1"),
        ("boundsneedle", "-C", "-1"),
        ("--short-scan", "-k", "-1", "白話"),
        ("--short-scan", "-C", "-1", "白話"),
      ):
        with self.subTest(args=args):
          res = run_ccsi(home, "search", *args, check=False)
          self.assertNotEqual(res.returncode, 0)

      zero_k = run_ccsi(home, "search", "boundsneedle", "-k", "0")
      self.assertEqual(zero_k.stdout, "(no hits)\n")

  def test_vendor_filter_escapes_like_wildcards_in_root_path(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      cc_root = home / "cc_root"
      codex_root = home / "ccXroot"
      cc_file = cc_root / "projects/p/a.jsonl"
      cc_file.parent.mkdir(parents=True)
      cc_file.write_text(json.dumps({
        "type": "user",
        "timestamp": "2026-10-19T00:00:00Z",
        "message": {"role": "user", "content": "wildcardrootneedle"},
      }) + "\n")
      fake_codex = codex_root / "projects/p/b.jsonl"
      fake_codex.parent.mkdir(parents=True)
      fake_codex.write_text(json.dumps({
        "type": "user",
        "timestamp": "2026-10-19T00:00:00Z",
        "message": {"role": "user", "content": "wildcardrootneedle"},
      }) + "\n")

      run_ccsi(home, "index", extra_env={"CLAUDE_CONFIG_DIR": str(codex_root)})
      run_ccsi(home, "index", extra_env={"CLAUDE_CONFIG_DIR": str(cc_root)})

      out = run_ccsi(home, "search", "wildcardrootneedle", "--vendor", "cc", extra_env={"CLAUDE_CONFIG_DIR": str(cc_root)}).stdout
      self.assertEqual(out.count("--- [cc]"), 1)
      self.assertIn("a.jsonl", out)
      self.assertNotIn("b.jsonl", out)

  def test_short_scan_matches_json_escaped_chars_and_synthesized_tool_tags(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      s_slash = home / ".claude/projects/probe/slash.jsonl"
      s_bs = home / ".claude/projects/probe/backslash.jsonl"
      s_tool = home / ".claude/projects/probe/tool.jsonl"
      s_slash.parent.mkdir(parents=True)
      s_slash.write_text('{"type":"user","timestamp":"2026-10-19T00:00:00Z","message":{"role":"user","content":"api\\/v2"}}\n')
      s_bs.write_text('{"type":"user","timestamp":"2026-10-19T00:00:01Z","message":{"role":"user","content":"c:\\\\go"}}\n')
      s_tool.write_text(json.dumps({
        "type": "assistant",
        "timestamp": "2026-10-19T00:00:02Z",
        "message": {"role": "assistant", "content": [
          {"type": "tool_use", "id": "t1", "name": "jq", "input": {"command": "run"}},
        ]},
      }) + "\n")
      run_ccsi(home, "index")

      self.assertIn("slash.jsonl", run_ccsi(home, "search", "--short-scan", "i/").stdout)
      self.assertIn("backslash.jsonl", run_ccsi(home, "search", "--short-scan", "\\g").stdout)
      self.assertIn("tool.jsonl", run_ccsi(home, "search", "--short-scan", "[j").stdout)

  def test_parallel_scan_large_change_batch_does_not_deadlock(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      projects = home / ".claude" / "projects"
      # Create >2,000 files across 16 top-level project dirs so _parallel_scan_diff activates,
      # with long paths so bulk deletion easily exceeds a 64 KB pipe buffer per worker.
      payload = json.dumps({
        "type": "user",
        "timestamp": "2026-11-24T00:00:00Z",
        "message": {"role": "user", "content": "parallelbatchneedle"},
      }) + "\n"
      keep_payload = json.dumps({
        "type": "user",
        "timestamp": "2026-11-24T00:01:00Z",
        "message": {"role": "user", "content": "parallelkeepneedle"},
      }) + "\n"
      created = []
      for d in range(16):
        pdir = projects / f"long-project-directory-name-padding-segment-{d:02d}"
        pdir.mkdir(parents=True)
        for j in range(140):
          fpath = pdir / f"session-transcript-long-filename-padding-{d:02d}-{j:03d}.jsonl"
          fpath.write_text(keep_payload if j == 0 else payload)
          created.append((j, fpath))

      init = run_ccsi(home, "index", timeout=30)
      self.assertIn("scanned=2240 ", init.stdout)

      # Delete 1,920 files (120 per dir) so each worker returns >64 KB of unseen paths
      for j, fpath in created:
        if j >= 20:
          fpath.unlink()

      inc = run_ccsi(home, "index", timeout=30)
      self.assertIn("scanned=320 ", inc.stdout)
      self.assertIn("rows=320 ", inc.stdout)
      self.assertIn("parallelkeepneedle", run_ccsi(home, "search", "parallelkeepneedle").stdout)

  def test_fts5_escaped_quote_phrase_and_punctuation_queries(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      cc_session(home, "special", 'literal a"b token foo:bar fn(x) err-code')
      run_ccsi(home, "index")

      for query in ('"a""b"', "foo:bar", "fn(x)", "err-code"):
        with self.subTest(query=query):
          res = run_ccsi(home, "search", query)
          self.assertIn("special.jsonl", res.stdout)

  def test_fifo_jsonl_does_not_hang_events_or_short_scan(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      cc_session(home, "healthy", "healthyfifoneedle 測試")
      run_ccsi(home, "index")
      fifo_path = home / ".claude/projects/probe/pipe.jsonl"
      os.mkfifo(fifo_path)

      evs = run_ccsi(home, "events", timeout=5)
      self.assertIn("healthyfifoneedle", evs.stdout)

      replaced = home / ".claude/projects/probe/healthy.jsonl"
      fifo2 = home / ".claude/projects/probe/swap.pipe"
      os.mkfifo(fifo2)
      fifo2.replace(replaced)
      short_res = run_ccsi(home, "search", "--short-scan", "測試", timeout=5)
      self.assertEqual(short_res.stdout, "(no hits)\n")

  def test_inplace_rewrite_non_message_same_length_plus_append_reindexes(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      session = home / ".claude/projects/probe/rewrite-nonmsg.jsonl"
      session.parent.mkdir(parents=True)
      line1_old = json.dumps({
        "type": "user",
        "timestamp": "2026-10-19T00:00:00Z",
        "message": {"role": "user", "content": "oldsecretneedle"},
      }) + "\n"
      session.write_text(line1_old)
      run_ccsi(home, "index")

      prefix = '{"type":"progress","p":"'
      suffix = '"}\n'
      pad_len = len(line1_old.encode()) - len((prefix + suffix).encode())
      line1_new = prefix + ("x" * pad_len) + suffix
      self.assertEqual(len(line1_old.encode()), len(line1_new.encode()))
      line2_new = json.dumps({
        "type": "user",
        "timestamp": "2026-10-19T00:01:00Z",
        "message": {"role": "user", "content": "newsecretneedle"},
      }) + "\n"
      session.write_text(line1_new + line2_new)
      t = session.stat().st_mtime + 10
      os.utime(session, (t, t))
      run_ccsi(home, "index")

      self.assertEqual(run_ccsi(home, "search", "oldsecretneedle").stdout, "(no hits)\n")
      self.assertIn("newsecretneedle", run_ccsi(home, "search", "newsecretneedle").stdout)
      with closing(sqlite3.connect(db_path_for(home))) as db:
        old_cnt = db.execute("SELECT count(*) FROM messages WHERE messages MATCH 'oldsecretneedle'").fetchone()[0]
        new_cnt = db.execute("SELECT count(*) FROM messages WHERE messages MATCH 'newsecretneedle'").fetchone()[0]
      self.assertEqual(old_cnt, 0)
      self.assertEqual(new_cnt, 1)

  def test_corrupted_v3_wrong_columns_and_broken_fts_auto_recovers(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      cc_session(home, "schema-heal", "schemahealneedle")
      db_path = db_path_for(home)
      db_path.parent.mkdir(parents=True, exist_ok=True)
      with closing(sqlite3.connect(db_path)) as db:
        db.executescript("""
          CREATE TABLE paths (id INTEGER);
          CREATE TABLE files (id INTEGER);
          CREATE TABLE message_refs (id INTEGER);
          CREATE TABLE metadata (wrong_col TEXT);
          CREATE TABLE messages (id INTEGER);
          PRAGMA user_version = 3;
        """)

      bad_search = run_ccsi(home, "search", "schemahealneedle", check=False)
      self.assertNotEqual(bad_search.returncode, 0)
      self.assertNotIn("Traceback", bad_search.stderr)

      bad_vendor = run_ccsi(home, "index", "--vendor", "cc", check=False)
      self.assertNotEqual(bad_vendor.returncode, 0)
      self.assertNotIn("Traceback", bad_vendor.stderr)

      healed = run_ccsi(home, "index")
      self.assertIn("rows=1 ", healed.stdout)
      self.assertIn("schemahealneedle", run_ccsi(home, "search", "schemahealneedle").stdout)

  def test_large_file_context_search_survives_mid_search_truncation_and_bad_utf8(self):
    with tempfile.TemporaryDirectory() as tmp:
      home = Path(tmp)
      session = home / ".claude/projects/probe/large-race.jsonl"
      session.parent.mkdir(parents=True)
      filler = "z" * 400
      lines = []
      for i in range(90):
        content = f"msg-{i} {filler}" if i != 45 else f"targetlargeraceneedle {filler}"
        lines.append((json.dumps({
          "type": "user",
          "timestamp": f"2026-10-19T00:{i // 60:02d}:{i % 60:02d}Z",
          "message": {"role": "user", "content": content},
        }) + "\n").encode("utf-8"))
      lines.insert(44, b"\xff\xfe{bad utf8 line\n")
      session.write_bytes(b"".join(lines))
      run_ccsi(home, "index")

      ok_ctx = run_ccsi(home, "search", "targetlargeraceneedle", "-C", "2")
      self.assertIn("targetlargeraceneedle", ok_ctx.stdout)
      self.assertIn("msg-44", ok_ctx.stdout)
      self.assertIn("msg-46", ok_ctx.stdout)

      ccsi_mod = load_ccsi_module()
      orig_collect = ccsi_mod.collect_local_context_pread

      def truncate_during_context(*a, **kw):
        session.write_bytes(b"")
        return orig_collect(*a, **kw)

      with (
        mock.patch.object(ccsi_mod, "DB_PATH", db_path_for(home)),
        mock.patch.object(ccsi_mod, "ROOTS", (("cc", str(home / ".claude/projects")),)),
        mock.patch.object(ccsi_mod, "ROOT", str(home / ".claude/projects")),
        mock.patch.object(ccsi_mod, "collect_local_context_pread", side_effect=truncate_during_context),
        closing(sqlite3.connect(db_path_for(home).resolve().as_uri() + "?mode=ro", uri=True)) as db,
      ):
        args = argparse.Namespace(k=5, vendor=None, exclude_session=[], context=2)
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
          found = ccsi_mod.search_contentless(db, ccsi_mod.extract_rows, args, "targetlargeraceneedle", [])
      self.assertEqual(found, 0)


if __name__ == "__main__":
  unittest.main()
