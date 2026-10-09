#!/usr/bin/env python3

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS = Path(__file__).resolve().parent
PROJECTION = SCRIPTS / "pr-review-report-projection.py"
GROUP = SCRIPTS / "pr-review-group-report.py"
SAAS_11 = "github:github.com/acme/saas#11"
DASH_707 = "github:github.com/acme/dashboard#707"
DEFAULT_TARGETS = [
  {"target_identity": SAAS_11, "head": "b" * 40, "base": "c" * 40, "version_state": "current"},
  {"target_identity": DASH_707, "head": "d" * 40, "base": "e" * 40, "version_state": "current"},
]


def canonical_set_identity(targets):
  import hashlib
  joined = "\n".join(sorted(target["target_identity"] for target in targets))
  return "sha256:" + hashlib.sha256(joined.encode("utf-8")).hexdigest()


SET_IDENTITY = canonical_set_identity(DEFAULT_TARGETS)


def load_module():
  spec = importlib.util.spec_from_file_location("pr_review_report_projection", PROJECTION)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def run_group(mode, payload):
  proc = subprocess.run(
    [sys.executable, str(GROUP), mode],
    input=json.dumps(payload),
    capture_output=True,
    text=True,
  )
  if mode == "render":
    if not proc.stdout.strip():
      raise AssertionError(f"render produced no stdout; stderr={proc.stderr}")
    return proc.stdout
  return json.loads(proc.stdout)


def group_payload(findings=None, targets=None):
  resolved_targets = targets if targets is not None else DEFAULT_TARGETS
  return {
    "set_identity": canonical_set_identity(resolved_targets),
    "targets": resolved_targets,
    "findings": findings if findings is not None else [
      {"target_identity": SAAS_11, "file": "src/a.ts", "line": 12, "anchor": "return value",
       "root_cause": "missing guard", "source": "cc", "suggestion": "Must Fix",
       "action": "auto-fix", "action_reason": "修法明確", "title": "少了 guard",
       "comment": "這邊少了 guard，會回傳 null。", "failure_chain_id": "chain-baseline"},
      {"target_identity": DASH_707, "file": "src/a.ts", "line": 12, "anchor": "return value",
       "root_cause": "missing   guard", "source": "codex", "suggestion": "Must Fix",
       "action": "auto-fix", "action_reason": "修法明確", "failure_chain_id": "chain-baseline"},
    ],
  }


class GroupProjectionTest(unittest.TestCase):
  def setUp(self):
    self.module = load_module()
    self.root = tempfile.TemporaryDirectory()
    self.addCleanup(self.root.cleanup)
    self.module.REPORT_ROOT = (Path(self.root.name) / "pr-review-reports").resolve()
    self.module.REPORT_ROOT.joinpath(self.module.GROUP_ROOT_NAME).mkdir(parents=True)
    self.stable = "abc123def456"
    self.addCleanup(self._cleanup)

  def _cleanup(self):
    for path in self.module.REPORT_ROOT.joinpath(self.module.GROUP_ROOT_NAME).glob(f"set-{self.stable}*"):
      path.unlink()

  def set_paths(self, stable_id=None, schemas=None):
    self.stable = stable_id or self.stable
    names = (
      f"set-{self.stable}-review.audit.draft.md",
      f"set-{self.stable}-review.audit.md",
      f"set-{self.stable}-review.md",
    )
    base = self.module.REPORT_ROOT / self.module.GROUP_ROOT_NAME
    return tuple(base / name for name in names)

  def published_pair(self, draft_text, stable_id=None):
    if stable_id is None:
      stable_id = re.match(r"# Review set ([0-9a-f]{12}) Code Review", draft_text).group(1)
    draft, audit, main = self.set_paths(stable_id)
    draft.write_text(draft_text)
    self.module.publish_report_pair(draft, audit, main)
    return audit, main

  def test_group_report_publishes_schema_three_pair_under_canonical_set_paths(self):
    payload = group_payload()
    rendered = run_group("render", payload)
    self.assertEqual(rendered.count("**Report projection schema**: 3"), 1)
    self.assertNotIn('{"set_identity"', rendered)
    self.assertTrue(rendered.startswith("# Review set "))

    title_id = re.match(r"# Review set ([0-9a-f]{12}) Code Review", rendered).group(1)
    self.assertEqual(title_id, canonical_set_identity(payload["targets"])[7:19])
    self.assertEqual(
      "**Review set identity**: " + canonical_set_identity(payload["targets"]),
      re.search(r"(?m)^\*\*Review set identity\*\*: sha256:[0-9a-f]{64}$", rendered).group(0),
    )
    targets_line = re.search(r"(?m)^\*\*Review set targets\*\*: (.+)$", rendered).group(1)
    versions_line = re.search(r"(?m)^\*\*Target versions\*\*: (.+)$", rendered).group(1)
    self.assertEqual(
      set(part.strip() for part in targets_line.split(" · ")),
      {target["target_identity"] for target in payload["targets"]},
    )
    self.assertEqual(
      set(entry.strip().split("=", 1)[0] for entry in versions_line.split(";")),
      {target["target_identity"] for target in payload["targets"]},
    )

    audit, main = self.published_pair(rendered)
    audit_text = audit.read_text()
    main_text = main.read_text()
    self.assertIn("**Report projection schema**: 3", audit_text)
    self.assertIn("**Review set identity**: " + canonical_set_identity(payload["targets"]), audit_text)
    self.assertIn("**Target versions**: ", audit_text)
    self.assertIn(SAAS_11, audit_text)
    self.assertIn(DASH_707, audit_text)
    generation = re.search(r"\*\*Report generation\*\*: (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)", audit_text)
    self.assertIsNotNone(generation)
    self.assertEqual(generation.group(1), re.search(
      r"\*\*Report generation\*\*: (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)", main_text).group(1))
    self.assertIn("## " + self.module.SET_LOCATIONS_TITLE, main_text)
    self.assertIn("## 發現總覽", main_text)
    self.assertIn(f"## [完整證據副檔]({audit.name})", main_text)
    self.assertNotIn(self.module.LOCATIONS_TITLE if hasattr(self.module, "LOCATIONS_TITLE") else "___", main_text)
    self.assertEqual(
      self.module.extract_finding_uids(rendered),
      self.module.extract_finding_uids(main_text),
    )
    self.assertEqual(1, len(self.module.extract_finding_uids(rendered)))
    self.assertNotIn("**Report projection schema**: 2", main_text)
    self.assertEqual(
      run_group("reconcile", group_payload())["groups"][0]["group_id"],
      self.module.extract_finding_uids(main_text)[0],
    )
    path_ids = {self.module.canonical_report_identity(path)[2] for path in (audit, main)}
    derived_stable = canonical_set_identity(payload["targets"])[7:19]
    self.assertEqual(path_ids, {derived_stable})
    self.assertEqual(title_id, derived_stable)

  def test_distinct_same_location_findings_keep_unique_group_ids_and_publish(self):
    findings = [
      {"target_identity": SAAS_11, "file": "src/a.ts", "line": 5,
       "anchor": "return value", "root_cause": "missing guard", "source": "cc",
       "suggestion": "Must Fix", "action": "auto-fix", "action_reason": "修法明確"},
      {"target_identity": SAAS_11, "file": "src/a.ts", "line": 5,
       "anchor": "guard dropped", "root_cause": "missing guard", "source": "cc",
       "suggestion": "Should Fix", "action": "ask-user", "action_reason": "需人工判斷"},
    ]
    rendered = run_group("render", group_payload(findings=findings))
    group_uids = self.module.extract_finding_uids(rendered)
    self.assertEqual(len(group_uids), 2)
    self.assertEqual(len(set(group_uids)), 2)
    audit, main = self.published_pair(rendered)
    self.assertTrue(audit.is_file())
    self.assertTrue(main.is_file())

  def test_no_op_group_declares_inline_exemption_and_publishes(self):
    rendered = run_group("render", group_payload(findings=[
      {"target_identity": SAAS_11, "file": "src/a.ts", "line": 12,
       "anchor": "return value", "root_cause": "informational observation", "source": "cc",
       "suggestion": "參考用", "action": "no-op", "action_reason": "不需處理"},
    ]))
    self.assertRegex(
      rendered,
      r"(?m)^F-01 finding_uid: [0-9a-f]{20} action=no-op inline=none$",
    )
    audit, main = self.published_pair(rendered)
    self.assertTrue(audit.is_file())
    self.assertTrue(main.is_file())

  def test_zero_finding_group_uses_marker_and_publishes(self):
    marker = "本輪零 finding：跨目標位置表沒有資料列，這是正常結果，不是表格損壞。"
    rendered = run_group("render", group_payload(findings=[]))
    self.assertIn(marker, rendered)
    self.assertFalse(self.module.set_locations_is_valid(rendered.replace(marker, "    " + marker)))
    audit, main = self.published_pair(rendered)
    self.assertTrue(audit.is_file())
    self.assertTrue(main.is_file())

  def test_populated_locations_reject_fenced_or_trailing_garbage(self):
    rendered = run_group("render", group_payload())
    fenced = rendered.replace(
      "## 跨目標位置\n\n| group_id",
      "## 跨目標位置\n\n```text\n| bad | row |\n```\n\n| group_id",
      1,
    )
    trailing = rendered.replace(
      "\n## 上一輪 findings 對帳",
      "\ntrailing garbage\n\n## 上一輪 findings 對帳",
      1,
    )
    self.assertFalse(self.module.set_locations_is_valid(fenced))
    self.assertFalse(self.module.set_locations_is_valid(trailing))

  def test_group_contract_allows_version_drift_but_rejects_other_mismatches(self):
    payload = group_payload()
    rendered = run_group("render", payload)
    stable = canonical_set_identity(payload["targets"])[7:19]
    draft, audit, main = self.set_paths(stable)

    draft.write_text(rendered)
    self.module.publish_report_pair(draft, audit, main)
    self.assertTrue(audit.exists())
    self.assertTrue(main.exists())

    original_audit = audit.read_text()
    original_main = main.read_text()
    updated = rendered.replace(
      f"{DASH_707}=head:{'d' * 40}",
      f"{DASH_707}=head:{'f' * 40}",
    )
    draft.write_text(updated)
    self.module.publish_report_pair(draft, audit, main)
    self.assertFalse(draft.exists())
    self.assertIn(f"{DASH_707}=head:{'f' * 40}", audit.read_text())

    audit_backups = list(audit.parent.glob(f"{audit.name}.*.bak.md"))
    main_backups = list(main.parent.glob(f"{main.name}.*.bak.md"))
    self.assertEqual(len(audit_backups), 1)
    self.assertEqual(len(main_backups), 1)
    self.assertEqual(audit_backups[0].read_text(), original_audit)
    self.assertEqual(main_backups[0].read_text(), original_main)

    cases = {
      "schema-two": updated.replace("**Report projection schema**: 3", "**Report projection schema**: 2"),
      "schema-vanish": updated.replace("**Report projection schema**: 3\n", ""),
      "target-dropped": re.sub(
        r"\*\*Target versions\*\*: [^\n]*",
        f"**Target versions**: {SAAS_11}=head:{'b' * 40}|base:{'c' * 40}|state:current",
        updated,
      ),
      "identity-rewritten": updated.replace(
        "**Review set identity**: " + SET_IDENTITY,
        "**Review set identity**: sha256:" + "b2" * 32,
      ),
      "continuity-dropped": updated.replace("**Prior review continuity**: N-A (no prior audit)\n", ""),
      "locations-dropped": re.sub(r"(?ms)^## 跨目標位置\n.*?(?=^## )", "", updated),
      "location-uid-foreign": updated.replace(
        self.module.extract_finding_uids(updated)[0],
        "0" * 20,
        1,
      ),
    }
    audit_before = audit.read_text()
    main_before = main.read_text()
    for name, candidate in cases.items():
      with self.subTest(case=name):
        draft.write_text(candidate)
        with self.assertRaises(ValueError):
          self.module.publish_report_pair(draft, audit, main)
        self.assertTrue(draft.exists())
      self.assertEqual(audit.read_text(), audit_before)
      self.assertEqual(main.read_text(), main_before)

  def test_same_second_group_republish_uses_collision_free_backup_names(self):
    rendered = run_group("render", group_payload())
    audit, main = self.published_pair(rendered)
    draft, _, _ = self.set_paths()
    real_datetime = self.module.datetime.datetime

    class FixedDateTime(real_datetime):
      @classmethod
      def now(cls, tz=None):
        return real_datetime(2026, 9, 18, 14, 0, 0, tzinfo=tz)

    first_update = rendered.replace(
      f"{DASH_707}=head:{'d' * 40}",
      f"{DASH_707}=head:{'f' * 40}",
    )
    second_update = rendered.replace(
      f"{DASH_707}=head:{'d' * 40}",
      f"{DASH_707}=head:{'a' * 40}",
    )
    with mock.patch.object(self.module.datetime, "datetime", FixedDateTime):
      draft.write_text(first_update)
      self.module.publish_report_pair(draft, audit, main)
      draft.write_text(second_update)
      self.module.publish_report_pair(draft, audit, main)

    audit_backups = sorted(audit.parent.glob(f"{audit.name}.*.bak.md"))
    main_backups = sorted(main.parent.glob(f"{main.name}.*.bak.md"))
    self.assertEqual(len(audit_backups), 2)
    self.assertEqual(len(main_backups), 2)
    self.assertTrue(any(".1.bak.md" in path.name for path in audit_backups))
    self.assertTrue(any(".1.bak.md" in path.name for path in main_backups))

  def test_group_publish_restores_archived_pair_when_main_write_fails(self):
    rendered = run_group("render", group_payload())
    audit, main = self.published_pair(rendered)
    original_audit = audit.read_text()
    original_main = main.read_text()

    updated = rendered.replace(
      f"{DASH_707}=head:{'d' * 40}",
      f"{DASH_707}=head:{'f' * 40}",
    )
    draft, _, _ = self.set_paths()
    draft.write_text(updated)
    original_write = self.module.write_main_report
    write_count = 0

    def fail_on_main(path, text):
      nonlocal write_count
      write_count += 1
      if write_count == 2:
        raise OSError("simulated main write failure")
      return original_write(path, text)

    with mock.patch.object(self.module, "write_main_report", side_effect=fail_on_main):
      with self.assertRaisesRegex(OSError, "simulated main write failure"):
        self.module.publish_report_pair(draft, audit, main)

    self.assertTrue(draft.exists())
    self.assertEqual(audit.read_text(), original_audit)
    self.assertEqual(main.read_text(), original_main)
    self.assertEqual(list(audit.parent.glob(f"{audit.name}.*.bak.md")), [])
    self.assertEqual(list(main.parent.glob(f"{main.name}.*.bak.md")), [])

  def test_publish_rejects_forged_identity_title_or_path_without_prior_audit(self):
    payload = group_payload()
    rendered = run_group("render", payload)
    derived_stable = canonical_set_identity(payload["targets"])[7:19]

    cases = {
      "identity-and-title-and-path": rendered
        .replace("**Review set identity**: " + SET_IDENTITY, "**Review set identity**: sha256:" + "b2" * 32)
        .replace(derived_stable, "fedcba987654"),
      "path-only": rendered,
      "title-only": rendered.replace(f"# Review set {derived_stable} Code Review", "# Review set 000000000000 Code Review"),
      "title-and-path": rendered.replace(
        f"# Review set {derived_stable} Code Review",
        "# Review set fedcba987654 Code Review",
      ),
    }
    for name, candidate in cases.items():
      with self.subTest(case=name):
        draft, audit, main = self.set_paths(
          "fedcba987654" if name in ("identity-and-title-and-path", "path-only", "title-and-path") else derived_stable,
        )
        draft.write_text(candidate)
        with self.assertRaises(ValueError):
          self.module.publish_report_pair(draft, audit, main)
        self.assertTrue(draft.exists())
        self.assertFalse(audit.exists())
        self.assertFalse(main.exists())

  def test_group_publish_refuses_mixed_pair_and_heals_from_valid_draft(self):
    rendered = run_group("render", group_payload())
    audit, main = self.published_pair(rendered)
    generation_pattern = re.compile(r"\*\*Report generation\*\*: (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)")

    tampered = main.read_text().replace(
      generation_pattern.findall(main.read_text())[0], "1970-01-01T00:00:00Z",
    )
    main.write_text(tampered)
    self.assertNotEqual(
      generation_pattern.findall(audit.read_text()),
      generation_pattern.findall(main.read_text()),
    )

    draft, _, _ = self.set_paths()
    draft.write_text(rendered)
    self.module.publish_report_pair(draft, audit, main)
    self.assertEqual(
      generation_pattern.findall(audit.read_text()),
      generation_pattern.findall(main.read_text()),
    )
    self.assertIn("**Report projection schema**: 3", main.read_text())

    mixed = rendered.replace("**Report projection schema**: 3", "**Report projection schema**: 2")
    draft, _, _ = self.set_paths()
    draft.write_text(mixed)
    with self.assertRaisesRegex(ValueError, "source report contract mismatch"):
      self.module.publish_report_pair(draft, audit, main)
    self.assertTrue(draft.exists())
    self.assertEqual(
      generation_pattern.findall(audit.read_text()),
      generation_pattern.findall(main.read_text()),
    )

    self.assertEqual(
      ("single", "main", 7),
      self.module.canonical_report_identity(self.module.REPORT_ROOT / "some-repo" / "pr-7-review.md"),
    )
    self.assertEqual(
      ("group", "main", canonical_set_identity(DEFAULT_TARGETS)[7:19]),
      self.module.canonical_report_identity(main),
    )

  def test_group_report_reads_markdown_and_rejects_json_blobs(self):
    prior = {
      "set_identity": SET_IDENTITY,
      "findings": [
        {"target_identity": SAAS_11, "file": "src/a.ts", "anchor": "return value",
         "root_cause": "missing guard", "action": "auto-fix", "finding_uid": "0123456789abcdef0123"},
      ],
    }
    rendered = run_group("render", {**group_payload(), "prior_report": prior})
    self.assertRegex(rendered, r"(?m)^# Review set [0-9a-f]{12} Code Review 比較報告$")
    self.assertIn("| group_id | finding_uid | target_identity | file | line | source |", rendered)
    self.assertIn("| 前輪 finding_uid | 問題 | 狀態 | 本輪證據 |", rendered)
    self.assertIn("**Prior review continuity**: CHECKED", rendered)
    draft, audit, main = self.set_paths("abcdefabcdef")
    draft.write_text(json.dumps(run_group("reconcile", {**group_payload(), "prior_report": prior}), ensure_ascii=False))
    with self.assertRaises(ValueError):
      self.module.publish_report_pair(draft, audit, main)
    self.assertTrue(draft.exists())

  def test_single_pr_report_paths_and_names_stay_unchanged(self):
    relative = "some-repo"
    cells = (
      ("pr-9-review.audit.draft.md", ("single", "draft", 9)),
      ("pr-9-review.audit.md", ("single", "audit", 9)),
      ("pr-9-review.md", ("single", "main", 9)),
    )
    for name, expected in cells:
      with self.subTest(name=name):
        self.assertEqual(
          expected,
          self.module.canonical_report_identity(self.module.REPORT_ROOT / relative / name),
        )
    for name in ("set-abc123def456-review.md", "pr-9-review.md"):
      with self.subTest(rejected=name):
        with self.assertRaises(ValueError):
          self.module.canonical_report_identity(self.module.REPORT_ROOT / "too" / "deep" / name)
    self.assertEqual(
      ("group", "audit", "abc123def456"),
      self.module.canonical_report_identity(self.module.REPORT_ROOT / "sets" / "set-abc123def456-review.audit.md"),
    )
    self.assertEqual("**Report projection schema**: 2" in self.module.SCHEMA_LINES, True)
    self.assertEqual(2, self.module.SCHEMA_LINES["**Report projection schema**: 2"])

  def test_range_group_main_report_keeps_attribution_section(self):
    spec = importlib.util.spec_from_file_location(
      "test_pr_review_group_report", SCRIPTS / "test_pr_review_group_report.py")
    report_test = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(report_test)
    payload = report_test.range_payload(findings=[
      report_test.finding(
        report_test.SAAS_RANGE, "src/a.ts", "return value", "guard runs after the write", line=40,
        suggestion="Must Fix", action="auto-fix", action_reason="修法明確",
        code_source=[{"commit": report_test.COMMIT_A, "prs": [{"pr": 11, "author": "alice", "base_ref": "stage"}]}],
      ),
    ])
    rendered = run_group("render", payload)
    self.assertIn("**Report projection schema**: 3", rendered)
    self.assertIn("## 歸因三欄", rendered)
    audit, main = self.published_pair(rendered)
    main_text = main.read_text()
    self.assertIn("## 歸因三欄", main_text)
    self.assertIn("#11 @alice", main_text.split("## 歸因三欄")[1].split("\n## ")[0])


if __name__ == "__main__":
  unittest.main()