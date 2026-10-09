#!/usr/bin/env python3

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).with_name("pr-review-c4.py")
SPEC = importlib.util.spec_from_file_location("pr_review_c4", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def line_number(text, quote):
  return text[:text.index(quote)].count("\n") + 1


def clause(path="openspec/specs/orders/spec.md"):
  return {
    "clause_id": "C4-001",
    "contract_type": "ERROR_CONTRACT",
    "spec_path": path,
    "line_start": 5,
    "line_end": 5,
    "exact_quote": "cancelOrder MUST return 409 when state is PENDING",
    "source_excerpt": "cancelOrder MUST return 409 when state is PENDING",
    "changed_flow_hint": {
      "actor_or_entity": "order",
      "operation_or_event": "cancelOrder",
      "precondition": "state=PENDING",
      "observable_result": "HTTP 409",
    },
  }


def accounting(finding_id="SPEC-001"):
  return {
    "clause_id": "C4-001",
    "contract_type": "ERROR_CONTRACT",
    "classification": "mismatch",
    "reason_code": "OBSERVABLE_BEHAVIOR_DIFFERS",
    "normative_quote": "cancelOrder MUST return 409 when state is PENDING",
    "spec_anchor": {
      "path": "openspec/specs/orders/spec.md",
      "line_start": 5,
      "line_end": 5,
    },
    "finding_id": finding_id,
  }


def finding(identifier="SPEC-001", title="PENDING order cancellation returns the wrong status"):
  trace_quote = "if (order.state === \"PENDING\") {\n  return response.status(200).json(order)\n}"
  return {
    "id": identifier,
    "reviewer": "spec-compliance-reviewer",
    "severity": "HIGH",
    "classification": "mismatch",
    "contract_type": "ERROR_CONTRACT",
    "title": title,
    "normative_quote": "cancelOrder MUST return 409 when state is PENDING",
    "spec_anchor": {
      "path": "openspec/specs/orders/spec.md",
      "line_start": 5,
      "line_end": 5,
    },
    "same_flow": {
      "actor_or_entity": "order",
      "operation_or_event": "cancelOrder",
      "precondition": "state=PENDING",
      "observable_result": "HTTP 409",
      "mapping_evidence": "The clause and changed handler govern the same flow.",
    },
    "file": "src/orders/cancel.ts",
    "line_start": 89,
    "line_end": 89,
    "anchor": "return response.status(200).json(order)",
    "trace_anchors": [
      {
        "binding_id": "C4-BIND-001",
        "side": "head",
        "path": "src/orders/cancel.ts",
        "line_start": 88,
        "line_end": 90,
        "quote": trace_quote,
      }
    ],
    "behavioral_evidence": {
      "kind": "static_trace",
      "given": "order state is PENDING",
      "when": "cancelOrder is called",
      "actual": "the changed branch returns HTTP 200",
      "required": "the clause requires HTTP 409",
      "observable_delta": "the caller treats a rejected cancellation as successful",
    },
    "problem": "The implementation contradicts the same-flow error contract.",
    "impact": "The caller can persist an incorrect success state.",
    "suggested_fix": "Return the specified status from the PENDING branch.",
  }


def reviewer_output(findings=None):
  values = findings if findings is not None else [finding()]
  return {
    "reviewer": "spec-compliance-reviewer",
    "dispatch_id": "c4-dispatch-001",
    "status": "COMPLETE",
    "contract_accounting": [accounting(values[0]["id"] if values else None)],
    "findings": values,
    "spec_file_accounting": [
      {
        "path": "openspec/specs/orders/spec.md",
        "status": "SPEC_REVIEWED",
      }
    ],
    "summary": {
      "candidates": 1,
      "findings": len(values),
      "full_match": 0,
      "partial_match": 0,
      "mismatch": 1,
      "missing_in_code": 0,
      "code_stronger_than_spec": 0,
      "code_weaker_than_spec": 0,
      "undocumented_behavior": 0,
      "AMBIGUOUS": 0,
    },
    "errors": [],
  }


def packet():
  trace_quote = "if (order.state === \"PENDING\") {\n  return response.status(200).json(order)\n}"
  return {
    "dispatch_id": "c4-dispatch-001",
    "clauses": [clause()],
    "spec_files": [{"path": "openspec/specs/orders/spec.md"}],
    "changed_files": [{"path": "src/orders/cancel.ts", "provenance": "authored"}],
    "evidence_bindings": [
      {
        "binding_id": "C4-BIND-001",
        "side": "head",
        "path": "src/orders/cancel.ts",
        "line_start": 88,
        "line_end": 90,
        "quote": trace_quote,
      }
    ],
    "trace_context": {
      "authored_diff_binding_ids": ["C4-BIND-001"],
      "connected_guard_binding_ids": [],
      "connected_guard_status": "NONE_REQUIRED",
      "clause_traces": [
        {
          "clause_id": "C4-001",
          "authored_binding_ids": ["C4-BIND-001"],
          "connected_guard_binding_ids": [],
        }
      ],
    },
    "predispatch_verification": {
      "canonical_spec_bound": True,
      "head_bindings_verified": True,
      "base_bindings_status": "NOT_APPLICABLE",
      "hunk_provenance_verified": True,
    },
  }


class ResolveAuthorityTest(unittest.TestCase):
  def test_resolves_archive_alias_to_unique_live_requirement(self):
    quote = "The widget MUST use the canonical login URL."
    block = f"### Requirement: Login redirect\n\n{quote}\n\n#### Scenario: Logged out\n\n- **THEN** redirect\n"
    archived = f"# Change\n\n## MODIFIED Requirements\n\n{block}"
    live = f"# Point redemption\n\n## Requirements\n\n{block}"
    with tempfile.TemporaryDirectory() as root:
      archive_path = Path(root, "openspec/changes/archive/old/specs/redirect/spec.md")
      live_path = Path(root, "openspec/specs/cart-point-redemption/spec.md")
      archive_path.parent.mkdir(parents=True)
      live_path.parent.mkdir(parents=True)
      archive_path.write_text(archived)
      live_path.write_text(live)
      candidate = {
        **clause(str(archive_path.relative_to(root))),
        "exact_quote": quote,
        "line_start": line_number(archived, quote),
        "line_end": line_number(archived, quote),
      }
      result = MODULE.resolve_authority(root, candidate)
    self.assertEqual("RESOLVED", result["status"])
    self.assertEqual("C4_LIVE_CANONICAL_RESOLVED", result["reason_code"])
    self.assertEqual("openspec/specs/cart-point-redemption/spec.md", result["clause"]["spec_path"])
    self.assertEqual(line_number(live, quote), result["clause"]["line_start"])
    self.assertNotIn("changes/archive", result["clause"]["source_excerpt"])

  def test_rejects_archive_without_live_canonical(self):
    quote = "The widget MUST use the canonical login URL."
    archived = f"### Requirement: Login redirect\n\n{quote}\n"
    with tempfile.TemporaryDirectory() as root:
      path = Path(root, "openspec/changes/archive/old/spec.md")
      path.parent.mkdir(parents=True)
      path.write_text(archived)
      candidate = {
        **clause(str(path.relative_to(root))),
        "exact_quote": quote,
        "line_start": 3,
        "line_end": 3,
      }
      result = MODULE.resolve_authority(root, candidate)
    self.assertEqual("SKIPPED", result["status"])
    self.assertEqual("C4_ARCHIVED_ONLY_NO_LIVE_CANONICAL", result["reason_code"])

  def test_rejects_multiple_live_canonical_matches(self):
    quote = "The widget MUST use the canonical login URL."
    block = f"### Requirement: Login redirect\n\n{quote}\n"
    with tempfile.TemporaryDirectory() as root:
      archive_path = Path(root, "openspec/changes/archive/old/spec.md")
      archive_path.parent.mkdir(parents=True)
      archive_path.write_text(block)
      for name in ("one", "two"):
        live_path = Path(root, f"openspec/specs/{name}/spec.md")
        live_path.parent.mkdir(parents=True)
        live_path.write_text(block)
      candidate = {
        **clause(str(archive_path.relative_to(root))),
        "exact_quote": quote,
        "line_start": 3,
        "line_end": 3,
      }
      result = MODULE.resolve_authority(root, candidate)
    self.assertEqual("SKIPPED", result["status"])
    self.assertEqual("C4_LIVE_CANONICAL_AMBIGUOUS", result["reason_code"])

  def test_rejects_non_unique_quote_in_current_spec(self):
    quote = "The order MUST remain pending."
    content = f"### Requirement: One\n\n{quote}\n\n### Requirement: Two\n\n{quote}\n"
    with tempfile.TemporaryDirectory() as root:
      path = Path(root, "openspec/specs/orders/spec.md")
      path.parent.mkdir(parents=True)
      path.write_text(content)
      candidate = {
        **clause(str(path.relative_to(root))),
        "exact_quote": quote,
        "line_start": 3,
        "line_end": 3,
      }
      result = MODULE.resolve_authority(root, candidate)
    self.assertEqual("SKIPPED", result["status"])
    self.assertEqual("C4_CANONICAL_QUOTE_NOT_UNIQUE", result["reason_code"])

  def test_rejects_invalid_authority_input_shape(self):
    result = MODULE.resolve_authority("/tmp", {**clause(), "spec_path": None})
    self.assertEqual("SKIPPED", result["status"])
    self.assertEqual("C4_AUTHORITY_INPUT_INVALID", result["reason_code"])

  def test_does_not_treat_crlf_and_lf_blocks_as_byte_identical(self):
    quote = "The widget MUST use the canonical login URL."
    archived = f"### Requirement: Login redirect\r\n\r\n{quote}\r\n"
    live = f"### Requirement: Login redirect\n\n{quote}\n"
    with tempfile.TemporaryDirectory() as root:
      archive_path = Path(root, "openspec/changes/archive/old/spec.md")
      live_path = Path(root, "openspec/specs/live/spec.md")
      archive_path.parent.mkdir(parents=True)
      live_path.parent.mkdir(parents=True)
      archive_path.write_bytes(archived.encode())
      live_path.write_bytes(live.encode())
      candidate = {
        **clause(str(archive_path.relative_to(root))),
        "exact_quote": quote,
        "line_start": 3,
        "line_end": 3,
      }
      result = MODULE.resolve_authority(root, candidate)
    self.assertEqual("SKIPPED", result["status"])
    self.assertEqual("C4_ARCHIVED_ONLY_NO_LIVE_CANONICAL", result["reason_code"])

  def test_rejects_live_path_symlinked_to_archive(self):
    quote = "The widget MUST use the canonical login URL."
    content = f"### Requirement: Login redirect\n\n{quote}\n"
    with tempfile.TemporaryDirectory() as root:
      archive_path = Path(root, "openspec/changes/archive/old/spec.md")
      live_path = Path(root, "openspec/specs/live/spec.md")
      archive_path.parent.mkdir(parents=True)
      live_path.parent.mkdir(parents=True)
      archive_path.write_text(content)
      live_path.symlink_to(archive_path)
      candidate = {
        **clause(str(live_path.relative_to(root))),
        "exact_quote": quote,
        "line_start": 3,
        "line_end": 3,
      }
      result = MODULE.resolve_authority(root, candidate)
    self.assertEqual("SKIPPED", result["status"])
    self.assertEqual("C4_AUTHORITY_SYMLINK_NOT_ALLOWED", result["reason_code"])

  def test_rejects_archive_path_with_symlinked_directory(self):
    quote = "The widget MUST use the canonical login URL."
    block = f"### Requirement: Login redirect\n\n{quote}\n"
    with tempfile.TemporaryDirectory() as root:
      archive_real = Path(root, "openspec/changes/archive/real")
      archive_link = Path(root, "openspec/changes/archive/link")
      live_path = Path(root, "openspec/specs/live/spec.md")
      archive_real.mkdir(parents=True)
      live_path.parent.mkdir(parents=True)
      Path(archive_real, "spec.md").write_text(block)
      archive_link.symlink_to(archive_real, target_is_directory=True)
      live_path.write_text(block)
      candidate = {
        **clause("openspec/changes/archive/link/spec.md"),
        "exact_quote": quote,
        "line_start": 3,
        "line_end": 3,
      }
      result = MODULE.resolve_authority(root, candidate)
    self.assertEqual("SKIPPED", result["status"])
    self.assertEqual("C4_AUTHORITY_SYMLINK_NOT_ALLOWED", result["reason_code"])

  def test_rejects_archive_prefix_with_parent_traversal(self):
    with tempfile.TemporaryDirectory() as root:
      live_path = Path(root, "openspec/specs/orders/spec.md")
      live_path.parent.mkdir(parents=True)
      live_path.write_text("# Orders\n\n\n\n" + clause()["exact_quote"])
      candidate = {
        **clause("openspec/changes/archive/../../../openspec/specs/orders/spec.md"),
      }
      result = MODULE.resolve_authority(root, candidate)
    self.assertEqual("SKIPPED", result["status"])
    self.assertEqual("C4_AUTHORITY_PATH_NOT_ALLOWED", result["reason_code"])


  def test_resolves_unpromoted_change_delta_spec(self):
    quote = "cancelOrder MUST return 409 when state is PENDING"
    content = f"# Delta\n\n## ADDED Requirements\n\n### Requirement: Pending cancellation\n\n{quote}\n"
    with tempfile.TemporaryDirectory() as root:
      spec_path = "openspec/changes/add-cancel/specs/orders/spec.md"
      target = Path(root, spec_path)
      target.parent.mkdir(parents=True)
      target.write_text(content)
      candidate = {
        **clause(spec_path),
        "exact_quote": quote,
        "line_start": line_number(content, quote),
        "line_end": line_number(content, quote),
      }
      result = MODULE.resolve_authority(root, candidate)
    self.assertEqual("RESOLVED", result["status"])
    self.assertEqual("C4_CHANGE_DELTA_AUTHORITY_RESOLVED", result["reason_code"])
    self.assertEqual(spec_path, result["clause"]["spec_path"])
    self.assertNotIn("authority_alias_path", result["clause"])

  def test_rejects_change_dir_path_outside_specs_segment(self):
    quote = "cancelOrder MUST return 409 when state is PENDING"
    content = f"# Notes\n\n\n\n{quote}\n"
    with tempfile.TemporaryDirectory() as root:
      target = Path(root, "openspec/changes/add-cancel/README.md")
      target.parent.mkdir(parents=True)
      target.write_text(content)
      candidate = {
        **clause("openspec/changes/add-cancel/README.md"),
        "exact_quote": quote,
        "line_start": line_number(content, quote),
        "line_end": line_number(content, quote),
      }
      result = MODULE.resolve_authority(root, candidate)
    self.assertEqual("SKIPPED", result["status"])
    self.assertEqual("C4_AUTHORITY_PATH_NOT_ALLOWED", result["reason_code"])

  def test_rejects_change_delta_path_with_symlinked_specs_directory(self):
    quote = "cancelOrder MUST return 409 when state is PENDING"
    content = f"# Delta\n\n### Requirement: Pending cancellation\n\n{quote}\n"
    with tempfile.TemporaryDirectory() as root:
      archive_specs = Path(root, "openspec/changes/archive/old/specs")
      Path(archive_specs, "orders").mkdir(parents=True)
      Path(archive_specs, "orders/spec.md").write_text(content)
      change_dir = Path(root, "openspec/changes/add-cancel")
      change_dir.mkdir(parents=True)
      Path(change_dir, "specs").symlink_to(archive_specs, target_is_directory=True)
      candidate = {
        **clause("openspec/changes/add-cancel/specs/orders/spec.md"),
        "exact_quote": quote,
        "line_start": line_number(content, quote),
        "line_end": line_number(content, quote),
      }
      result = MODULE.resolve_authority(root, candidate)
    self.assertEqual("SKIPPED", result["status"])
    self.assertEqual("C4_AUTHORITY_SYMLINK_NOT_ALLOWED", result["reason_code"])


QUOTE = "cancelOrder MUST return 409 when state is PENDING"
DOC = f"# Orders\n\n{QUOTE}\n"
OTHER_ORIGIN = "https://github.com/acme/widgets.git"
PROFILE_YAML = """\
acme/widgets:
  trunk: main
  authority:
    live: docs/pages/*.md
    change:
      - docs/specs/*.md
"""


def git(root, *args):
  return subprocess.run(
    ["git", "-C", str(root), *args],
    check=True,
    capture_output=True,
    text=True,
  ).stdout.strip()


def make_repo(root, base_files, head_files, origin=OTHER_ORIGIN):
  git(root, "init", "-q")
  git(root, "config", "user.email", "test@example.com")
  git(root, "config", "user.name", "Test")
  if origin is not None:
    git(root, "remote", "add", "origin", origin)
  commits = []
  for files in (base_files, head_files):
    for relative, content in files.items():
      target = Path(root, relative)
      target.parent.mkdir(parents=True, exist_ok=True)
      target.write_text(content)
    git(root, "add", ".")
    git(root, "commit", "-qm", "step", "--allow-empty")
    commits.append(git(root, "rev-parse", "HEAD"))
  return commits[0], commits[1]


def write_profile(home, yaml_text):
  target = Path(home, ".claude/pr-review/repos.yaml")
  target.parent.mkdir(parents=True, exist_ok=True)
  target.write_text(yaml_text)


def resolve_cli(root, home, candidate, **extra):
  payload = {"review_root": str(root), "candidate": candidate, **extra}
  result = subprocess.run(
    [sys.executable, str(MODULE_PATH), "resolve-authority"],
    input=json.dumps(payload),
    capture_output=True,
    text=True,
    check=False,
    env={**os.environ, "HOME": str(home)},
  )
  return json.loads(result.stdout)


def doc_candidate(path, content=DOC):
  line = line_number(content, QUOTE)
  return {
    **clause(path),
    "exact_quote": QUOTE,
    "line_start": line,
    "line_end": line,
  }


class DeclaredAuthorityTest(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp.cleanup)
    self.root = Path(self.tmp.name, "repo")
    self.root.mkdir()
    self.home = Path(self.tmp.name, "home")
    write_profile(self.home, PROFILE_YAML)

  def resolve(self, path, base, head, content=DOC, **extra):
    return resolve_cli(
      self.root,
      self.home,
      doc_candidate(path, content),
      authored_diff_base=base,
      review_head=head,
      **extra,
    )

  def test_live_document_resolves_without_being_touched_by_the_pull_request(self):
    base, head = make_repo(
      self.root,
      {"docs/pages/orders.md": DOC, "src/app.ts": "a\n"},
      {"src/app.ts": "b\n"},
    )
    result = self.resolve("docs/pages/orders.md", base, head)
    self.assertEqual("RESOLVED", result["status"])
    self.assertEqual("C4_CURRENT_AUTHORITY_RESOLVED", result["reason_code"])
    self.assertEqual("docs/pages/orders.md", result["clause"]["spec_path"])

  def test_change_document_touched_by_the_pull_request_resolves(self):
    base, head = make_repo(
      self.root,
      {"docs/specs/orders.md": "# Orders\n"},
      {"docs/specs/orders.md": DOC},
    )
    result = self.resolve("docs/specs/orders.md", base, head)
    self.assertEqual("RESOLVED", result["status"])
    self.assertEqual("C4_CHANGE_DELTA_AUTHORITY_RESOLVED", result["reason_code"])

  def test_change_document_not_touched_by_the_pull_request_is_rejected(self):
    base, head = make_repo(
      self.root,
      {"docs/specs/orders.md": DOC, "src/app.ts": "a\n"},
      {"src/app.ts": "b\n"},
    )
    result = self.resolve("docs/specs/orders.md", base, head)
    self.assertEqual("SKIPPED", result["status"])
    self.assertEqual("C4_AUTHORITY_PATH_NOT_ALLOWED", result["reason_code"])

  def test_paths_outside_the_declared_locations_are_rejected(self):
    delta = "openspec/changes/add-cancel/specs/orders/spec.md"
    base, head = make_repo(
      self.root,
      {"README.md": DOC, "openspec/specs/orders/spec.md": DOC, delta: DOC},
      {"README.md": DOC + "\n", delta: DOC + "\n"},
    )
    for path in ("README.md", "openspec/specs/orders/spec.md", delta):
      with self.subTest(path=path):
        result = self.resolve(path, base, head, content=DOC)
        self.assertEqual("SKIPPED", result["status"])
        self.assertEqual("C4_AUTHORITY_PATH_NOT_ALLOWED", result["reason_code"])

  def test_glob_fields_in_the_input_are_rejected_and_never_widen_the_result(self):
    base, head = make_repo(self.root, {"README.md": DOC}, {"README.md": DOC + "\n"})
    for name in ("authority", "live", "change", "spec_globs", "profile_path"):
      with self.subTest(name=name):
        result = self.resolve("README.md", base, head, **{name: {"live": ["README.md"]}})
        self.assertEqual("FAILED", result["status"])
        self.assertEqual("C4_CLI_INPUT_INVALID", result["reason_code"])
    smuggled = {**doc_candidate("README.md"), "authority": {"live": ["README.md"]}}
    result = resolve_cli(
      self.root, self.home, smuggled, authored_diff_base=base, review_head=head
    )
    self.assertEqual("SKIPPED", result["status"])
    self.assertEqual("C4_AUTHORITY_INPUT_INVALID", result["reason_code"])
    plain = self.resolve("README.md", base, head)
    self.assertEqual("C4_AUTHORITY_PATH_NOT_ALLOWED", plain["reason_code"])

  def test_unreadable_or_mistyped_profile_falls_back_to_openspec(self):
    # 使用者 2026-10-08 裁決：設定檔壞掉時沒宣告的 openspec repo 不能跟著停擺，所以照「沒宣告」處理
    live = "openspec/specs/orders/spec.md"
    base, head = make_repo(
      self.root,
      {"docs/pages/orders.md": DOC, live: f"### Requirement: Pending\n\n{QUOTE}\n"},
      {"src/app.ts": "b\n"},
    )
    broken = {
      "malformed yaml": "acme/widgets: [unclosed\n  trunk: x\n",
      "numeric live": "acme/widgets:\n  trunk: main\n  authority:\n    live: 5\n",
      "authority not a mapping": "acme/widgets:\n  trunk: main\n  authority: 5\n",
      "top level not a mapping": "- acme/widgets\n",
    }
    for label, yaml_text in broken.items():
      write_profile(self.home, yaml_text)
      with self.subTest(label=label, path=live):
        result = resolve_cli(
          self.root,
          self.home,
          {**doc_candidate(live), "line_start": 3, "line_end": 3},
          authored_diff_base=base,
          review_head=head,
        )
        self.assertEqual("RESOLVED", result["status"])
        self.assertEqual("C4_CURRENT_AUTHORITY_RESOLVED", result["reason_code"])
      with self.subTest(label=label, path="docs/pages/orders.md"):
        result = self.resolve("docs/pages/orders.md", base, head)
        self.assertEqual("SKIPPED", result["status"])

  def test_git_diff_failure_rejects_instead_of_assuming_no_changed_files(self):
    _, head = make_repo(
      self.root,
      {"docs/specs/orders.md": DOC},
      {"docs/specs/orders.md": DOC},
    )
    result = self.resolve("docs/specs/orders.md", "a" * 40, head)
    self.assertEqual("SKIPPED", result["status"])
    self.assertEqual("C4_AUTHORITY_INPUT_INVALID", result["reason_code"])

  def test_live_document_needs_no_diff_range(self):
    make_repo(self.root, {"docs/pages/orders.md": DOC}, {"src/app.ts": "b\n"})
    result = resolve_cli(self.root, self.home, doc_candidate("docs/pages/orders.md"))
    self.assertEqual("RESOLVED", result["status"])
    self.assertEqual("C4_CURRENT_AUTHORITY_RESOLVED", result["reason_code"])

  def test_change_document_without_diff_range_is_rejected(self):
    make_repo(self.root, {"docs/specs/orders.md": "# Orders\n"}, {"docs/specs/orders.md": DOC})
    result = resolve_cli(self.root, self.home, doc_candidate("docs/specs/orders.md"))
    self.assertEqual("SKIPPED", result["status"])
    self.assertEqual("C4_AUTHORITY_INPUT_INVALID", result["reason_code"])

  def test_single_level_glob_does_not_match_nested_paths(self):
    base, head = make_repo(
      self.root,
      {"docs/pages/sub/x.md": DOC},
      {"docs/pages/sub/x.md": DOC + "\n"},
    )
    result = self.resolve("docs/pages/sub/x.md", base, head)
    self.assertEqual("SKIPPED", result["status"])
    self.assertEqual("C4_AUTHORITY_PATH_NOT_ALLOWED", result["reason_code"])

  def test_declared_sources_keep_the_existing_path_and_quote_checks(self):
    base, head = make_repo(
      self.root,
      {
        "docs/pages/orders.md": DOC,
        "docs/pages/twice.md": f"{DOC}\n{QUOTE}\n",
        "docs/pages/latin1.md": "x",
        "outside.md": DOC,
        "src/app.ts": "a\n",
      },
      {"src/app.ts": "b\n"},
    )
    Path(self.root, "docs/pages/latin1.md").write_bytes(b"\xff\xfe" + QUOTE.encode())
    Path(self.root, "docs/pages/inside-link.md").symlink_to("orders.md")
    Path(self.root, "docs/pages/escape-link.md").symlink_to(Path(self.tmp.name, "elsewhere.md"))
    Path(self.tmp.name, "elsewhere.md").write_text(DOC)
    cases = {
      "docs/pages/inside-link.md": "C4_AUTHORITY_SYMLINK_NOT_ALLOWED",
      "docs/pages/escape-link.md": "C4_SPEC_PATH_OUTSIDE_REVIEW_ROOT",
      "docs/pages/twice.md": "C4_CANONICAL_QUOTE_NOT_UNIQUE",
      "docs/pages/latin1.md": "C4_SPEC_CONTENT_INVALID",
      "docs/pages/missing.md": "C4_SPEC_PATH_NOT_FOUND",
    }
    for path, reason in cases.items():
      with self.subTest(path=path):
        result = self.resolve(path, base, head)
        self.assertEqual("SKIPPED", result["status"])
        self.assertEqual(reason, result["reason_code"])
    wrong_line = doc_candidate("docs/pages/orders.md")
    wrong_line["line_start"] = wrong_line["line_end"] = 1
    result = resolve_cli(
      self.root, self.home, wrong_line, authored_diff_base=base, review_head=head
    )
    self.assertEqual("C4_SPEC_ANCHOR_MISMATCH", result["reason_code"])

  def test_repo_without_a_profile_entry_keeps_the_openspec_behavior(self):
    live = "openspec/specs/orders/spec.md"
    base, head = make_repo(
      self.root,
      {live: f"### Requirement: Pending\n\n{QUOTE}\n"},
      {"src/app.ts": "b\n"},
      origin="https://github.com/acme/other.git",
    )
    result = resolve_cli(
      self.root,
      self.home,
      {**doc_candidate(live), "line_start": 3, "line_end": 3},
    )
    self.assertEqual("RESOLVED", result["status"])
    self.assertEqual("C4_CURRENT_AUTHORITY_RESOLVED", result["reason_code"])
    self.assertEqual("SKIPPED", resolve_cli(
      self.root, self.home, doc_candidate("docs/pages/orders.md")
    )["status"])

  def test_repo_without_origin_keeps_the_openspec_behavior(self):
    live = "openspec/specs/orders/spec.md"
    make_repo(
      self.root,
      {live: f"### Requirement: Pending\n\n{QUOTE}\n"},
      {"src/app.ts": "b\n"},
      origin=None,
    )
    result = resolve_cli(
      self.root,
      self.home,
      {**doc_candidate(live), "line_start": 3, "line_end": 3},
    )
    self.assertEqual("RESOLVED", result["status"])
    self.assertEqual("C4_CURRENT_AUTHORITY_RESOLVED", result["reason_code"])


class PacketAuthorityValidTest(unittest.TestCase):
  def test_accepts_change_delta_clause_present_in_review_head(self):
    quote = "cancelOrder MUST return 409 when state is PENDING"
    content = f"# Delta\n\n## ADDED Requirements\n\n### Requirement: Pending cancellation\n\n{quote}\n"
    with tempfile.TemporaryDirectory() as root:
      spec_path = "openspec/changes/add-cancel/specs/orders/spec.md"
      target = Path(root, spec_path)
      target.parent.mkdir(parents=True)
      target.write_text(content)
      subprocess.run(["git", "-C", root, "init", "-q"], check=True)
      subprocess.run(["git", "-C", root, "config", "user.email", "test@example.com"], check=True)
      subprocess.run(["git", "-C", root, "config", "user.name", "Test"], check=True)
      subprocess.run(["git", "-C", root, "add", "."], check=True)
      subprocess.run(["git", "-C", root, "commit", "-qm", "delta"], check=True)
      head = subprocess.run(
        ["git", "-C", root, "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
      ).stdout.strip()
      resolved = MODULE.resolve_authority(
        root,
        {
          **clause(spec_path),
          "exact_quote": quote,
          "line_start": line_number(content, quote),
          "line_end": line_number(content, quote),
        },
      )
      self.assertEqual("RESOLVED", resolved["status"])
      binding_context = {
        "review_root": root,
        "authored_diff_base": head,
        "review_head": head,
      }
      self.assertTrue(
        MODULE.packet_authority_valid(binding_context, {"clauses": [resolved["clause"]]})
      )
      rejected = {**resolved["clause"], "spec_path": "openspec/changes/add-cancel/README.md"}
      self.assertFalse(
        MODULE.packet_authority_valid(binding_context, {"clauses": [rejected]})
      )


class ValidateOutputTest(unittest.TestCase):
  def setUp(self):
    self.root = tempfile.TemporaryDirectory()
    self.addCleanup(self.root.cleanup)
    review_root = Path(self.root.name, "review")
    source = review_root / "src/orders/cancel.ts"
    source.parent.mkdir(parents=True)
    base_lines = ["const stable = true"] + [""] * 86 + [
      "if (order.state === \"PENDING\") {",
      "  return response.status(409).json(order)",
      "}",
    ]
    source.write_text("\n".join(base_lines))
    spec = review_root / "openspec/specs/orders/spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("# Orders\n\n### Requirement: Pending cancellation\n\n" + clause()["exact_quote"])
    subprocess.run(["git", "-C", review_root, "init", "-q"], check=True)
    subprocess.run(["git", "-C", review_root, "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", review_root, "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", review_root, "add", "."], check=True)
    subprocess.run(["git", "-C", review_root, "commit", "-qm", "base"], check=True)
    base = subprocess.run(
      ["git", "-C", review_root, "rev-parse", "HEAD"],
      check=True,
      capture_output=True,
      text=True,
    ).stdout.strip()
    head_lines = [*base_lines]
    head_lines[88] = "  return response.status(200).json(order)"
    source.write_text("\n".join(head_lines))
    subprocess.run(["git", "-C", review_root, "add", "."], check=True)
    subprocess.run(["git", "-C", review_root, "commit", "-qm", "head"], check=True)
    head = subprocess.run(
      ["git", "-C", review_root, "rev-parse", "HEAD"],
      check=True,
      capture_output=True,
      text=True,
    ).stdout.strip()
    self.transcript = Path(self.root.name, "agent.jsonl")
    self.runtime_input = {
      "transcript_path": str(self.transcript),
      "dispatch_id": "c4-dispatch-001",
      "expected_agent_id": "agent-smoke-001",
      "requested_model": "opus",
      "requested_effort": "high",
    }
    self.binding_context = {
      "review_root": str(review_root),
      "authored_diff_base": base,
      "review_head": head,
    }

  def write_runtime_output(self, raw, packet_value=None):
    data = packet() if packet_value is None else packet_value
    packet_json = json.dumps(
      data,
      ensure_ascii=False,
      sort_keys=True,
      separators=(",", ":"),
    )
    prompt = MODULE.render_dispatch_prompt(data)
    self.runtime_input["packet"] = data
    text = raw if isinstance(raw, str) else json.dumps(raw)
    rows = [
      {
        "type": "user",
        "agentId": "agent-smoke-001",
        "message": {
          "role": "user",
          "content": prompt,
        },
      },
      {
        "type": "assistant",
        "agentId": "agent-smoke-001",
        "attributionAgent": "spec-compliance-reviewer",
        "effort": "high",
        "message": {
          "role": "assistant",
          "model": "claude-opus-5",
          "content": [{"type": "text", "text": text}],
        },
      },
    ]
    self.transcript.write_text("".join(json.dumps(row) + "\n" for row in rows))

  def validate(self, raw, packet_value=None, **kwargs):
    data = packet() if packet_value is None else packet_value
    if isinstance(raw, dict):
      raw["dispatch_id"] = data.get("dispatch_id")
    self.write_runtime_output(raw, data)
    return MODULE.validate_output(
      data,
      raw,
      runtime_input=self.runtime_input,
      binding_context=self.binding_context,
      **kwargs,
    )

  def test_admits_valid_findings_and_projects_rejected_ids_without_semantics(self):
    secret_title = "SPEC-001 concern must not appear in human projection"
    raw = reviewer_output([finding("SPEC-001", secret_title), finding("SPEC-002", "Valid second finding")])
    raw["contract_accounting"] = [accounting("SPEC-001"), {**accounting("SPEC-002"), "clause_id": "C4-002"}]
    raw["contract_accounting"][1]["normative_quote"] = "refundOrder MUST return 409 when state is PENDING"
    raw["contract_accounting"][1]["spec_anchor"] = {
      "path": "openspec/specs/orders/spec.md",
      "line_start": 6,
      "line_end": 6,
    }
    raw["findings"][1]["normative_quote"] = raw["contract_accounting"][1]["normative_quote"]
    raw["findings"][1]["spec_anchor"] = raw["contract_accounting"][1]["spec_anchor"]
    raw["summary"]["candidates"] = 2
    raw["summary"]["findings"] = 2
    raw["summary"]["mismatch"] = 2
    data = packet()
    data["clauses"].append({
      **clause(),
      "clause_id": "C4-002",
      "exact_quote": raw["contract_accounting"][1]["normative_quote"],
      "line_start": 6,
      "line_end": 6,
      "source_excerpt": raw["contract_accounting"][1]["normative_quote"],
    })
    invalid_quote = "if (order.state === \"PENDING\") {\n  return response.status(201).json(order)\n}"
    raw["findings"][0]["anchor"] = "return response.status(201).json(order)"
    raw["findings"][0]["trace_anchors"][0]["quote"] = invalid_quote
    raw["findings"][1]["trace_anchors"][0]["binding_id"] = "C4-BIND-002"
    data["evidence_bindings"][0]["quote"] = invalid_quote
    data["evidence_bindings"].append({
      **packet()["evidence_bindings"][0],
      "binding_id": "C4-BIND-002",
    })
    data["trace_context"]["authored_diff_binding_ids"].append("C4-BIND-002")
    data["trace_context"]["clause_traces"].append({
      "clause_id": "C4-002",
      "authored_binding_ids": ["C4-BIND-002"],
      "connected_guard_binding_ids": [],
    })
    review_root = self.binding_context["review_root"]
    spec = Path(review_root, "openspec/specs/orders/spec.md")
    spec.write_text(spec.read_text() + "\n" + raw["contract_accounting"][1]["normative_quote"])
    subprocess.run(["git", "-C", review_root, "add", "."], check=True)
    subprocess.run(["git", "-C", review_root, "commit", "-qm", "second clause"], check=True)
    self.binding_context["review_head"] = subprocess.run(
      ["git", "-C", review_root, "rev-parse", "HEAD"],
      check=True,
      capture_output=True,
      text=True,
    ).stdout.strip()
    result = self.validate(raw, data)
    projection = json.dumps(result["human_projection"], sort_keys=True)
    self.assertEqual("COMPLETE", result["status"])
    self.assertEqual(["SPEC-002"], [item["id"] for item in result["admitted_findings"]])
    self.assertEqual(1, result["human_projection"]["invalidated_count"])
    self.assertEqual(1, result["human_projection"]["classification_counts"]["mismatch"])
    self.assertEqual("C4_TRACE_HASH_MISMATCH", result["invalidated"][0]["reason_code"])
    self.assertNotIn(secret_title, projection)
    self.assertNotIn("SPEC-001", projection)

  def test_fails_closed_on_unknown_output_key(self):
    raw = reviewer_output()
    raw["unexpected"] = True
    result = self.validate(raw)
    self.assertEqual("FAILED", result["status"])
    self.assertEqual("C4_OUTPUT_SCHEMA_INVALID", result["reason_code"])
    self.assertEqual([], result["admitted_findings"])
    self.assertEqual({
      "classification_counts": {name: 0 for name in MODULE.CLASSIFICATIONS},
      "clause_accounting": [],
      "invalidated_count": 1,
      "invalidated_reason_codes": ["C4_OUTPUT_SCHEMA_INVALID"],
      "findings": [],
      "observations": [],
    }, result["human_projection"])

  def test_fails_closed_on_clause_accounting_mismatch(self):
    raw = reviewer_output()
    raw["contract_accounting"][0]["normative_quote"] = "different quote"
    result = self.validate(raw)
    self.assertEqual("FAILED", result["status"])
    self.assertEqual("C4_CLAUSE_BINDING_MISMATCH", result["reason_code"])
    self.assertEqual([], result["admitted_findings"])

  def test_requires_bound_runtime_receipt(self):
    result = MODULE.validate_output(
      packet(),
      reviewer_output(),
      binding_context=self.binding_context,
    )
    self.assertEqual("FAILED", result["status"])
    self.assertEqual("C4_RUNTIME_RECEIPT_INVALID", result["reason_code"])

  def test_rejects_duplicate_finding_id_across_clauses(self):
    raw = reviewer_output()
    second = {**accounting("SPEC-001"), "clause_id": "C4-002"}
    raw["contract_accounting"].append(second)
    raw["summary"]["candidates"] = 2
    raw["summary"]["mismatch"] = 2
    data = packet()
    data["clauses"].append({
      **clause(),
      "clause_id": "C4-002",
    })
    data["trace_context"]["clause_traces"].append({
      "clause_id": "C4-002",
      "authored_binding_ids": ["C4-BIND-001"],
      "connected_guard_binding_ids": [],
    })
    result = self.validate(raw, data)
    self.assertEqual("FAILED", result["status"])
    self.assertEqual("C4_FINDING_ACCOUNTING_MISMATCH", result["reason_code"])

  def test_rejects_finding_outside_packet_evidence_bindings(self):
    raw = reviewer_output()
    raw["findings"][0]["file"] = "src/orders/unbound.ts"
    result = self.validate(raw)
    self.assertEqual("FAILED", result["status"])
    self.assertEqual("C4_CODE_BINDING_MISMATCH", result["reason_code"])

  def test_rejects_reverse_line_ranges(self):
    raw = reviewer_output()
    raw["findings"][0]["line_start"] = 90
    raw["findings"][0]["line_end"] = 88
    result = self.validate(raw)
    self.assertEqual("FAILED", result["status"])
    self.assertEqual("C4_LINE_RANGE_INVALID", result["reason_code"])

  def test_rejects_anchor_line_that_does_not_match_quote_offset(self):
    raw = reviewer_output()
    raw["findings"][0]["line_start"] = 88
    raw["findings"][0]["line_end"] = 88
    result = self.validate(raw)
    self.assertEqual("FAILED", result["status"])
    self.assertEqual("C4_CODE_BINDING_MISMATCH", result["reason_code"])

  def test_rejects_finding_bound_only_to_connected_guard(self):
    raw = reviewer_output()
    data = packet()
    authored = {**data["evidence_bindings"][0], "binding_id": "C4-BIND-002"}
    data["evidence_bindings"].append(authored)
    data["trace_context"] = {
      "authored_diff_binding_ids": ["C4-BIND-002"],
      "connected_guard_binding_ids": ["C4-BIND-001"],
      "connected_guard_status": "SUPPLIED",
      "clause_traces": [
        {
          "clause_id": "C4-001",
          "authored_binding_ids": ["C4-BIND-002"],
          "connected_guard_binding_ids": ["C4-BIND-001"],
        }
      ],
    }
    result = self.validate(raw, data)
    self.assertEqual("FAILED", result["status"])
    self.assertEqual("C4_CODE_BINDING_MISMATCH", result["reason_code"])

  def test_rejects_same_flow_that_differs_from_packet(self):
    raw = reviewer_output()
    raw["findings"][0]["same_flow"]["precondition"] = "state=COMPLETE"
    result = self.validate(raw)
    self.assertEqual("FAILED", result["status"])
    self.assertEqual("C4_SAME_FLOW_MISMATCH", result["reason_code"])

  def test_rejects_runtime_output_from_a_different_candidate(self):
    self.write_runtime_output(reviewer_output([]))
    result = MODULE.validate_output(
      packet(),
      reviewer_output(),
      runtime_input=self.runtime_input,
      binding_context=self.binding_context,
    )
    self.assertEqual("FAILED", result["status"])
    self.assertEqual("C4_RUNTIME_OUTPUT_MISMATCH", result["reason_code"])

  def test_rejects_direct_archive_packet(self):
    data = packet()
    data["clauses"][0]["spec_path"] = "openspec/changes/archive/old/spec.md"
    data["spec_files"][0]["path"] = data["clauses"][0]["spec_path"]
    result = self.validate(reviewer_output(), data)
    self.assertEqual("FAILED", result["status"])
    self.assertEqual("C4_PACKET_SCHEMA_INVALID", result["reason_code"])

  def test_rejects_archive_alias_with_parent_traversal(self):
    data = packet()
    data["clauses"][0]["authority_alias_path"] = (
      "openspec/changes/archive/../../../openspec/specs/orders/spec.md"
    )
    result = self.validate(reviewer_output(), data)
    self.assertEqual("FAILED", result["status"])
    self.assertEqual("C4_PACKET_SCHEMA_INVALID", result["reason_code"])

  def test_rejects_finding_that_omits_required_guard_binding(self):
    raw = reviewer_output()
    data = packet()
    guard = {**data["evidence_bindings"][0], "binding_id": "C4-BIND-002"}
    data["evidence_bindings"].append(guard)
    data["trace_context"]["connected_guard_binding_ids"] = ["C4-BIND-002"]
    data["trace_context"]["connected_guard_status"] = "SUPPLIED"
    data["trace_context"]["clause_traces"][0]["connected_guard_binding_ids"] = [
      "C4-BIND-002"
    ]
    result = self.validate(raw, data)
    self.assertEqual("FAILED", result["status"])
    self.assertEqual("C4_CODE_BINDING_MISMATCH", result["reason_code"])

  def test_invalidates_finding_when_required_guard_is_stale(self):
    raw = reviewer_output()
    data = packet()
    stale_quote = "if (order.state === \"COMPLETE\") {"
    guard = {
      **data["evidence_bindings"][0],
      "binding_id": "C4-BIND-002",
      "line_start": 91,
      "line_end": 91,
      "quote": stale_quote,
    }
    data["evidence_bindings"].append(guard)
    data["trace_context"]["connected_guard_binding_ids"] = ["C4-BIND-002"]
    data["trace_context"]["connected_guard_status"] = "SUPPLIED"
    data["trace_context"]["clause_traces"][0]["connected_guard_binding_ids"] = [
      "C4-BIND-002"
    ]
    raw["findings"][0]["trace_anchors"].append({
      key: guard[key]
      for key in (
        "binding_id",
        "side",
        "path",
        "line_start",
        "line_end",
        "quote",
      )
    })
    result = self.validate(raw, data)
    self.assertEqual("COMPLETE", result["status"])
    self.assertEqual([], result["admitted_findings"])
    self.assertEqual(1, result["human_projection"]["invalidated_count"])
    self.assertEqual(
      ["C4_TRACE_HASH_MISMATCH"],
      result["human_projection"]["invalidated_reason_codes"],
    )

  def test_rejects_base_binding_with_unrelated_report_path(self):
    review_root = self.binding_context["review_root"]
    base = self.binding_context["authored_diff_base"]
    old_path = "src/orders/cancel.ts"
    report_path = "src/orders/nonexistent.ts"
    blob = subprocess.run(
      ["git", "-C", review_root, "rev-parse", f"{base}:{old_path}"],
      check=True,
      capture_output=True,
      text=True,
    ).stdout.strip()
    size = int(subprocess.run(
      ["git", "-C", review_root, "cat-file", "-s", blob],
      check=True,
      capture_output=True,
      text=True,
    ).stdout.strip())
    data = packet()
    base_quote = data["evidence_bindings"][0]["quote"].replace("status(200)", "status(409)")
    data["changed_files"][0]["path"] = report_path
    data["evidence_bindings"][0] = {
      "binding_id": "C4-BIND-001",
      "side": "base",
      "path": report_path,
      "line_start": 88,
      "line_end": 90,
      "quote": base_quote,
      "provenance_base_tree": base,
      "old_path": old_path,
      "blob_oid": blob,
      "blob_size_bytes": size,
    }
    data["predispatch_verification"]["base_bindings_status"] = "VERIFIED"
    raw = reviewer_output()
    raw["findings"][0]["file"] = report_path
    raw["findings"][0]["anchor"] = "return response.status(409).json(order)"
    raw["findings"][0]["trace_anchors"][0] = {
      key: data["evidence_bindings"][0][key]
      for key in (
        "binding_id",
        "side",
        "path",
        "line_start",
        "line_end",
        "quote",
      )
    }
    result = self.validate(raw, data)
    self.assertEqual("FAILED", result["status"])
    self.assertEqual("C4_PACKET_SCHEMA_INVALID", result["reason_code"])

  def test_rejects_authored_binding_without_git_provenance(self):
    raw = reviewer_output()
    with tempfile.TemporaryDirectory() as root:
      source = Path(root, "src/orders/cancel.ts")
      source.parent.mkdir(parents=True)
      source.write_text(
        "\n".join([""] * 87 + [
          "if (order.state === \"PENDING\") {",
          "  return response.status(200).json(order)",
          "}",
        ])
      )
      spec = Path(root, "openspec/specs/orders/spec.md")
      spec.parent.mkdir(parents=True)
      spec.write_text("# Orders\n\n### Requirement: Pending cancellation\n\n" + clause()["exact_quote"])
      self.write_runtime_output(raw)
      result = MODULE.validate_output(
        packet(),
        raw,
        runtime_input=self.runtime_input,
        binding_context={
          "review_root": root,
          "authored_diff_base": "a" * 40,
          "review_head": "b" * 40,
        },
      )
    self.assertEqual("FAILED", result["status"])
    self.assertEqual("C4_AUTHORITY_BINDING_INVALID", result["reason_code"])

  def test_rejects_path_with_control_character(self):
    data = packet()
    invalid_path = "src/orders/cancel.ts\x00other"
    data["changed_files"][0]["path"] = invalid_path
    data["evidence_bindings"][0]["path"] = invalid_path
    raw = reviewer_output()
    raw["findings"][0]["file"] = invalid_path
    raw["findings"][0]["trace_anchors"][0]["path"] = invalid_path
    result = self.validate(raw, data)
    self.assertEqual("FAILED", result["status"])
    self.assertEqual("C4_PACKET_SCHEMA_INVALID", result["reason_code"])

  def test_rejects_packet_over_clause_limit(self):
    data = packet()
    data["clauses"] = [
      {**data["clauses"][0], "clause_id": f"C4-{index:03d}"}
      for index in range(1, 52)
    ]
    result = self.validate(reviewer_output(), data)
    self.assertEqual("FAILED", result["status"])
    self.assertEqual("C4_PACKET_SCHEMA_INVALID", result["reason_code"])

  def test_rejects_packet_over_byte_limit(self):
    data = packet()
    data["clauses"][0]["changed_flow_hint"]["observable_result"] = "x" * 120001
    result = self.validate(reviewer_output(), data)
    self.assertEqual("FAILED", result["status"])
    self.assertEqual("C4_PACKET_SCHEMA_INVALID", result["reason_code"])

  def test_handles_malformed_findings_container_without_crashing(self):
    raw = reviewer_output()
    raw["findings"] = None
    result = self.validate(raw)
    self.assertEqual("FAILED", result["status"])
    self.assertEqual("C4_OUTPUT_SCHEMA_INVALID", result["reason_code"])

  def test_invalidates_uncommitted_head_evidence(self):
    source = Path(self.binding_context["review_root"], "src/orders/cancel.ts")
    source.write_text(source.read_text().replace("status(200)", "status(201)"))
    data = packet()
    raw = reviewer_output()
    changed_quote = data["evidence_bindings"][0]["quote"].replace(
      "status(200)",
      "status(201)",
    )
    data["evidence_bindings"][0]["quote"] = changed_quote
    raw["findings"][0]["anchor"] = "return response.status(201).json(order)"
    raw["findings"][0]["trace_anchors"][0]["quote"] = changed_quote
    result = self.validate(raw, data)
    self.assertEqual("COMPLETE", result["status"])
    self.assertEqual([], result["admitted_findings"])
    self.assertEqual(1, result["human_projection"]["invalidated_count"])

  def test_rejects_changed_canonical_spec_after_packet_creation(self):
    review_root = self.binding_context["review_root"]
    spec = Path(review_root, "openspec/specs/orders/spec.md")
    spec.write_text(spec.read_text().replace("MUST return 409", "MUST return 410"))
    subprocess.run(["git", "-C", review_root, "add", "."], check=True)
    subprocess.run(["git", "-C", review_root, "commit", "-qm", "change spec"], check=True)
    self.binding_context["review_head"] = subprocess.run(
      ["git", "-C", review_root, "rev-parse", "HEAD"],
      check=True,
      capture_output=True,
      text=True,
    ).stdout.strip()
    result = self.validate(reviewer_output())
    self.assertEqual("FAILED", result["status"])
    self.assertEqual("C4_AUTHORITY_BINDING_INVALID", result["reason_code"])

  def test_rejects_canonical_packet_path_that_is_a_symlink(self):
    root = Path(self.binding_context["review_root"])
    original = root / "openspec/specs/orders/spec.md"
    target = root / "openspec/specs/orders/real.md"
    original.rename(target)
    original.symlink_to(target)
    subprocess.run(["git", "-C", root, "add", "."], check=True)
    subprocess.run(["git", "-C", root, "commit", "-qm", "symlink spec"], check=True)
    self.binding_context["review_head"] = subprocess.run(
      ["git", "-C", root, "rev-parse", "HEAD"],
      check=True,
      capture_output=True,
      text=True,
    ).stdout.strip()
    result = self.validate(reviewer_output())
    self.assertEqual("FAILED", result["status"])
    self.assertEqual("C4_AUTHORITY_BINDING_INVALID", result["reason_code"])

  def test_keeps_nonharmful_mismatch_as_observation(self):
    raw = reviewer_output([])
    result = self.validate(raw)
    self.assertEqual("COMPLETE", result["status"])
    self.assertEqual([], result["admitted_findings"])
    self.assertEqual(1, len(result["observations"]))
    self.assertEqual(1, result["human_projection"]["classification_counts"]["mismatch"])

  def test_accepts_one_exact_json_code_fence(self):
    raw = reviewer_output()
    fenced = f"```json\n{json.dumps(raw)}\n```"
    result = self.validate(fenced)
    self.assertEqual("COMPLETE", result["status"])
    self.assertEqual(["C4-001"], [item["clause_id"] for item in result["human_projection"]["clause_accounting"]])
    self.assertEqual(1, result["human_projection"]["classification_counts"]["mismatch"])

  def test_requires_authoritative_binding_context(self):
    self.write_runtime_output(reviewer_output())
    result = MODULE.validate_output(
      packet(),
      reviewer_output(),
      runtime_input=self.runtime_input,
    )
    self.assertEqual("FAILED", result["status"])
    self.assertEqual("C4_BINDING_CONTEXT_INVALID", result["reason_code"])


class RuntimeReceiptTest(unittest.TestCase):
  def write_transcript(self, path, model, tool_names, effort="high", packet_value=None, prompt=None):
    data = packet() if packet_value is None else packet_value
    dispatched_prompt = MODULE.render_dispatch_prompt(data) if prompt is None else prompt
    rows = [
      {
        "type": "user",
        "agentId": "agent-smoke-001",
        "message": {
          "role": "user",
          "content": dispatched_prompt,
        },
      },
      {
        "type": "assistant",
        "agentId": "agent-smoke-001",
        "attributionAgent": "spec-compliance-reviewer",
        "effort": effort,
        "message": {
          "role": "assistant",
          "model": model,
          "content": [
            {"type": "thinking", "thinking": "hidden"},
            {"type": "text", "text": json.dumps(reviewer_output())},
          ],
        },
      },
    ]
    rows.extend({
      "type": "assistant",
      "agentId": "agent-smoke-001",
      "attributionAgent": "spec-compliance-reviewer",
      "effort": effort,
      "message": {
        "role": "assistant",
        "model": model,
        "content": [{"type": "tool_use", "name": name, "input": {}}],
      },
    } for name in tool_names)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))

  def receipt(self, path):
    return MODULE.runtime_receipt(
      path,
      dispatch_id="c4-dispatch-001",
      expected_agent_id="agent-smoke-001",
      packet_value=packet(),
      requested_model="opus",
      requested_effort="high",
    )

  def test_extracts_opus_48_zero_tool_receipt(self):
    with tempfile.TemporaryDirectory() as root:
      path = Path(root, "agent.jsonl")
      self.write_transcript(path, "claude-opus-4-8", [])
      result = self.receipt(path)
    self.assertEqual("COMPLETE", result["status"])
    self.assertEqual("BOUND", result["binding_status"])
    self.assertEqual("claude-opus-4-8", result["observed_model"])
    self.assertEqual("high", result["effort"])
    self.assertEqual([], [key for key in result if "sha256" in key or "hash" in key])
    self.assertEqual(0, result["tool_call_count"])
    self.assertEqual([], result["tool_calls"])

  def test_flags_opus_5_bash_and_read_calls(self):
    with tempfile.TemporaryDirectory() as root:
      path = Path(root, "agent.jsonl")
      self.write_transcript(path, "claude-opus-5", ["Bash"] * 13 + ["Read"])
      result = self.receipt(path)
    self.assertEqual("FAILED", result["status"])
    self.assertEqual("C4_TOOL_SURFACE_VIOLATION", result["reason_code"])
    self.assertEqual(14, result["tool_call_count"])
    self.assertEqual({"Bash": 13, "Read": 1}, result["tool_calls_by_name"])

  def test_rejects_wrong_or_missing_runtime_identity(self):
    with tempfile.TemporaryDirectory() as root:
      wrong_path = Path(root, "wrong.jsonl")
      missing_path = Path(root, "missing.jsonl")
      self.write_transcript(wrong_path, "claude-sonnet-5", [], effort="medium")
      self.write_transcript(missing_path, None, [], effort=None)
      wrong = self.receipt(wrong_path)
      missing = self.receipt(missing_path)
    self.assertEqual("C4_RUNTIME_MODEL_MISMATCH", wrong["reason_code"])
    self.assertEqual("C4_RUNTIME_MODEL_UNAVAILABLE", missing["reason_code"])

  def test_rejects_dispatch_prompt_appended_after_output(self):
    with tempfile.TemporaryDirectory() as root:
      path = Path(root, "agent.jsonl")
      self.write_transcript(path, "claude-opus-5", [])
      rows = [json.loads(line) for line in path.read_text().splitlines()]
      path.write_text(json.dumps(rows[1]) + "\n" + json.dumps(rows[0]) + "\n")
      result = self.receipt(path)
    self.assertEqual("FAILED", result["status"])
    self.assertEqual("C4_RUNTIME_DISPATCH_MISMATCH", result["reason_code"])

  def test_rejects_any_complete_prompt_mutation(self):
    data = packet()
    prompt = MODULE.render_dispatch_prompt(data)
    for label, mutated in (
      ("prefix", "Extra instruction\n" + prompt),
      ("suffix", prompt + "\nExtra instruction"),
      ("middle", prompt.replace("Use no tools.", "Use absolutely no tools.", 1)),
    ):
      with self.subTest(label=label), tempfile.TemporaryDirectory() as root:
        path = Path(root, "agent.jsonl")
        self.write_transcript(path, "claude-opus-5", [], prompt=mutated)
        result = MODULE.runtime_receipt(
          path,
          dispatch_id=data["dispatch_id"],
          expected_agent_id="agent-smoke-001",
          packet_value=data,
          requested_model="opus",
          requested_effort="high",
        )
      self.assertEqual("FAILED", result["status"])
      self.assertEqual("C4_RUNTIME_DISPATCH_MISMATCH", result["reason_code"])

  def test_rejects_packet_differing_from_the_dispatched_prompt(self):
    other = packet()
    other["clauses"][0]["changed_flow_hint"]["observable_result"] = "HTTP 410"
    with tempfile.TemporaryDirectory() as root:
      path = Path(root, "agent.jsonl")
      self.write_transcript(path, "claude-opus-5", [])
      result = MODULE.runtime_receipt(
        path,
        dispatch_id="c4-dispatch-001",
        expected_agent_id="agent-smoke-001",
        packet_value=other,
        requested_model="opus",
        requested_effort="high",
      )
    self.assertEqual("FAILED", result["status"])
    self.assertEqual("C4_RUNTIME_DISPATCH_MISMATCH", result["reason_code"])

  def test_rejects_binding_marker_with_suffixes(self):
    with tempfile.TemporaryDirectory() as root:
      path = Path(root, "agent.jsonl")
      self.write_transcript(path, "claude-opus-5", [])
      rows = [json.loads(line) for line in path.read_text().splitlines()]
      rows[0]["message"]["content"] = rows[0]["message"]["content"].replace(
        "\nC4_PACKET_JSON=",
        "x\nC4_PACKET_JSON=",
      ) + "x"
      path.write_text("".join(json.dumps(row) + "\n" for row in rows))
      result = self.receipt(path)
    self.assertEqual("FAILED", result["status"])
    self.assertEqual("C4_RUNTIME_DISPATCH_MISMATCH", result["reason_code"])

  def test_accepts_packet_marker_with_unicode_line_separator(self):
    with tempfile.TemporaryDirectory() as root:
      path = Path(root, "agent.jsonl")
      data = packet()
      data["clauses"][0]["changed_flow_hint"]["observable_result"] = "HTTP 409"
      self.write_transcript(path, "claude-opus-5", [], packet_value=data)
      result = MODULE.runtime_receipt(
        path,
        dispatch_id=data["dispatch_id"],
        expected_agent_id="agent-smoke-001",
        packet_value=data,
        requested_model="opus",
        requested_effort="high",
      )
    self.assertEqual("COMPLETE", result["status"])
    self.assertEqual("C4_RUNTIME_RECEIPT_OK", result["reason_code"])

  def test_rejects_partial_runtime_metadata(self):
    with tempfile.TemporaryDirectory() as root:
      path = Path(root, "agent.jsonl")
      self.write_transcript(path, "claude-opus-5", [])
      row = {
        "type": "assistant",
        "agentId": "agent-smoke-001",
        "attributionAgent": "spec-compliance-reviewer",
        "effort": "high",
        "message": {
          "role": "assistant",
          "content": [{"type": "thinking", "thinking": "hidden"}],
        },
      }
      with path.open("a") as handle:
        handle.write(json.dumps(row) + "\n")
      result = self.receipt(path)
    self.assertEqual("FAILED", result["status"])
    self.assertEqual("C4_RUNTIME_MODEL_UNAVAILABLE", result["reason_code"])

  def test_rejects_multiple_reviewer_outputs(self):
    with tempfile.TemporaryDirectory() as root:
      path = Path(root, "agent.jsonl")
      self.write_transcript(path, "claude-opus-5", [])
      row = {
        "type": "assistant",
        "agentId": "agent-smoke-001",
        "attributionAgent": "spec-compliance-reviewer",
        "effort": "high",
        "message": {
          "role": "assistant",
          "model": "claude-opus-5",
          "content": [{"type": "text", "text": json.dumps(reviewer_output([]))}],
        },
      }
      with path.open("a") as handle:
        handle.write(json.dumps(row) + "\n")
      result = self.receipt(path)
    self.assertEqual("FAILED", result["status"])
    self.assertEqual("C4_RUNTIME_OUTPUT_AMBIGUOUS", result["reason_code"])

  def test_rejects_malformed_jsonl_row(self):
    with tempfile.TemporaryDirectory() as root:
      path = Path(root, "agent.jsonl")
      path.write_text("[]\n")
      result = self.receipt(path)
    self.assertEqual("FAILED", result["status"])
    self.assertEqual("C4_RUNTIME_RECEIPT_INVALID", result["reason_code"])

  def test_cli_returns_json_for_missing_and_malformed_inputs(self):
    for mode, payload in (("validate", "{}"), ("resolve-authority", "{")):
      with self.subTest(mode=mode, payload=payload):
        result = subprocess.run(
          [sys.executable, str(MODULE_PATH), mode],
          input=payload,
          capture_output=True,
          text=True,
          check=False,
        )
        self.assertEqual(1, result.returncode)
        self.assertEqual("FAILED", json.loads(result.stdout)["status"])

  def test_validate_cli_returns_json_for_unpaired_surrogate(self):
    data = packet()
    data["clauses"][0]["changed_flow_hint"]["observable_result"] = "\ud800"
    payload = {
      "packet": data,
      "reviewer_output": reviewer_output(),
      "runtime_input": {
        "transcript_path": "/tmp/missing.jsonl",
        "dispatch_id": data["dispatch_id"],
        "expected_agent_id": "agent-smoke-001",
        "packet": data,
        "requested_model": "opus",
        "requested_effort": "high",
      },
      "binding_context": {
        "review_root": "/tmp",
        "authored_diff_base": "a" * 40,
        "review_head": "b" * 40,
      },
    }
    result = subprocess.run(
      [sys.executable, str(MODULE_PATH), "validate"],
      input=json.dumps(payload, ensure_ascii=True),
      capture_output=True,
      text=True,
      check=False,
    )
    self.assertEqual(1, result.returncode)
    self.assertEqual("FAILED", json.loads(result.stdout)["status"])

  def test_runtime_cli_rejects_missing_model_and_effort(self):
    result = subprocess.run(
      [sys.executable, str(MODULE_PATH), "runtime-receipt"],
      input=json.dumps({
        "transcript_path": "/tmp/missing.jsonl",
        "dispatch_id": "c4-dispatch-001",
        "expected_agent_id": "agent-smoke-001",
        "packet": packet(),
      }),
      capture_output=True,
      text=True,
      check=False,
    )
    self.assertEqual(1, result.returncode)
    self.assertEqual(
      "C4_RUNTIME_RECEIPT_INVALID",
      json.loads(result.stdout)["reason_code"],
    )


class BindingVerificationTest(unittest.TestCase):
  def test_reads_regular_blob_with_unicode_path(self):
    with tempfile.TemporaryDirectory() as root:
      source = Path(root, "src/訂單.py")
      source.parent.mkdir(parents=True)
      source.write_text("status = 409\n")
      subprocess.run(["git", "-C", root, "init", "-q"], check=True)
      subprocess.run(["git", "-C", root, "config", "user.email", "test@example.com"], check=True)
      subprocess.run(["git", "-C", root, "config", "user.name", "Test"], check=True)
      subprocess.run(["git", "-C", root, "add", "."], check=True)
      subprocess.run(["git", "-C", root, "commit", "-qm", "unicode"], check=True)
      head = subprocess.run(
        ["git", "-C", root, "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
      ).stdout.strip()
      entry = MODULE.git_tree_entry(root, head, "src/訂單.py")
    self.assertIsNotNone(entry)
    self.assertEqual("status = 409\n", entry["text"])

  def test_checks_base_blob_size_before_reading_content(self):
    root = "/tmp/review"
    oid = "a" * 40
    binding = {
      "binding_id": "C4-BIND-001",
      "side": "base",
      "path": "src/orders/cancel.ts",
      "line_start": 2,
      "line_end": 2,
      "quote": "return response.status(409).json(order)",
      "provenance_base_tree": "b" * 40,
      "old_path": "src/orders/cancel.ts",
      "blob_oid": oid,
      "blob_size_bytes": 120000,
    }

    def fake_run(args, **kwargs):
      if args[3] == "ls-tree":
        return subprocess.CompletedProcess(
          args,
          0,
          stdout=f"100644 blob {oid}\tsrc/orders/cancel.ts\0".encode(),
          stderr=b"",
        )
      if args[3:5] == ["cat-file", "-s"]:
        return subprocess.CompletedProcess(args, 0, stdout=b"200000\n", stderr=b"")
      raise AssertionError("blob content must not be read before size validation")

    with mock.patch.object(MODULE.subprocess, "run", side_effect=fake_run):
      self.assertIsNone(MODULE.git_blob_text(root, binding))

  def test_rejects_base_binding_from_different_tree(self):
    with tempfile.TemporaryDirectory() as root:
      source = Path(root, "src/orders/cancel.ts")
      source.parent.mkdir(parents=True)
      subprocess.run(["git", "-C", root, "init", "-q"], check=True)
      subprocess.run(["git", "-C", root, "config", "user.email", "test@example.com"], check=True)
      subprocess.run(["git", "-C", root, "config", "user.name", "Test"], check=True)
      source.write_text("return response.status(409).json(order)\n")
      subprocess.run(["git", "-C", root, "add", "."], check=True)
      subprocess.run(["git", "-C", root, "commit", "-qm", "base"], check=True)
      base = subprocess.run(
        ["git", "-C", root, "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
      ).stdout.strip()
      source.write_text("return response.status(418).json(order)\n")
      subprocess.run(["git", "-C", root, "add", "."], check=True)
      subprocess.run(["git", "-C", root, "commit", "-qm", "other"], check=True)
      other = subprocess.run(
        ["git", "-C", root, "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
      ).stdout.strip()
      binding = {"provenance_base_tree": other}
      self.assertFalse(MODULE.base_binding_tree_matches(root, base, binding))

  def test_reads_base_binding_from_bound_git_object(self):
    with tempfile.TemporaryDirectory() as root:
      source = Path(root, "src/orders/cancel.ts")
      source.parent.mkdir(parents=True)
      text = "before\nreturn response.status(409).json(order)\nafter\n"
      source.write_text(text)
      subprocess.run(["git", "-C", root, "init", "-q"], check=True)
      subprocess.run(["git", "-C", root, "config", "user.email", "test@example.com"], check=True)
      subprocess.run(["git", "-C", root, "config", "user.name", "Test"], check=True)
      subprocess.run(["git", "-C", root, "add", "src/orders/cancel.ts"], check=True)
      subprocess.run(["git", "-C", root, "commit", "-qm", "test"], check=True)
      tree = subprocess.run(
        ["git", "-C", root, "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
      ).stdout.strip()
      blob = subprocess.run(
        ["git", "-C", root, "rev-parse", "HEAD:src/orders/cancel.ts"],
        check=True,
        capture_output=True,
        text=True,
      ).stdout.strip()
      quote = "return response.status(409).json(order)"
      binding = {
        "binding_id": "C4-BIND-001",
        "side": "base",
        "path": "src/orders/cancel.ts",
        "line_start": 2,
        "line_end": 2,
        "quote": quote,
        "provenance_base_tree": tree,
        "old_path": "src/orders/cancel.ts",
        "blob_oid": blob,
        "blob_size_bytes": len(text.encode()),
      }
      context = {
        "review_root": root,
        "authored_diff_base": tree,
        "review_head": tree,
      }
      self.assertIsNone(MODULE.binding_failure_reason(context, binding))
      invalid = {**binding, "blob_oid": "0" * len(blob)}
      self.assertEqual(
        "C4_TRACE_PROVENANCE_MISMATCH",
        MODULE.binding_failure_reason(context, invalid),
      )


class EmitPromptTest(unittest.TestCase):
  def run_emit(self, payload):
    stdout = io.StringIO()
    stdin = io.StringIO(json.dumps(payload, ensure_ascii=False))
    with mock.patch.object(sys, "stdin", stdin), mock.patch.object(sys, "stdout", stdout):
      code = MODULE.main(["emit-prompt"])
    return code, stdout.getvalue()

  def test_emits_packet_line_matching_dispatch_prompt(self):
    value = packet()
    code, out = self.run_emit({"packet": value})
    self.assertEqual(0, code)
    lines = out.splitlines()
    self.assertEqual(1, len(lines))
    packet_json = json.dumps(
      value,
      ensure_ascii=False,
      sort_keys=True,
      separators=(",", ":"),
    )
    self.assertEqual(f"C4_PACKET_JSON={packet_json}", lines[0])
    self.assertEqual(json.loads(lines[0].split("=", 1)[1]), value)
    self.assertIn(lines[0], MODULE.render_dispatch_prompt(value).splitlines())

  def test_fails_closed_on_schema_invalid_packet(self):
    broken = packet()
    del broken["dispatch_id"]
    code, out = self.run_emit({"packet": broken})
    self.assertEqual(1, code)
    self.assertIn("C4_CLI_INPUT_INVALID", out)
    self.assertNotIn("C4_PACKET_JSON=", out)

  def test_fails_closed_on_missing_packet_key(self):
    code, out = self.run_emit({"payload": {}})
    self.assertEqual(1, code)
    self.assertIn("C4_CLI_INPUT_INVALID", out)

  def test_fails_closed_on_legacy_digest_field_in_packet(self):
    broken = packet()
    broken["clauses"][0]["source_hash"] = "0" * 64
    code, out = self.run_emit({"packet": broken})
    self.assertEqual(1, code)
    self.assertIn("C4_CLI_INPUT_INVALID", out)


class DispatchEnvelopeTest(unittest.TestCase):
  def run_cli(self, payload):
    env = {key: value for key, value in os.environ.items() if key != "CLAUDE_CODE_SESSION_ID"}
    return subprocess.run(
      [sys.executable, str(MODULE_PATH), "dispatch-envelope"],
      input=json.dumps(payload, ensure_ascii=False),
      capture_output=True,
      text=True,
      check=False,
      env=env,
    )

  def test_emits_complete_fixed_agent_contract_and_packet(self):
    result = self.run_cli({"packet": packet()})
    self.assertEqual(0, result.returncode)
    envelope = json.loads(result.stdout)
    self.assertEqual("COMPLETE", envelope["status"])
    self.assertEqual("C4_DISPATCH_ENVELOPE_READY", envelope["reason_code"])
    self.assertEqual("spec-compliance-reviewer", envelope["agent"]["subagent_type"])
    self.assertEqual("opus", envelope["agent"]["model"])
    self.assertEqual("C4 spec compliance review", envelope["agent"]["description"])
    prompt = envelope["agent"]["prompt"]
    packet_json = json.dumps(packet(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    self.assertIn(f"C4_PACKET_JSON={packet_json}", prompt)
    self.assertIn("Return exactly one JSON object matching the agent output contract", prompt)
    self.assertIn("Copy dispatch_id from C4_PACKET_JSON.", prompt)
    self.assertNotIn("observations key", prompt)
    self.assertEqual(packet(), envelope["runtime_input"]["packet"])
    self.assertEqual(
      {"transcript_path", "expected_agent_id"},
      set(MODULE.RUNTIME_INPUT_SCHEMA["required"]) - set(envelope["runtime_input"]),
    )

  def test_envelope_prompt_and_runtime_input_carry_no_digest(self):
    envelope = MODULE.dispatch_envelope(packet())
    self.assertEqual({"status", "reason_code", "agent", "runtime_input"}, set(envelope))
    self.assertEqual(
      {"dispatch_id", "packet", "requested_model", "requested_effort"},
      set(envelope["runtime_input"]),
    )
    prompt = envelope["agent"]["prompt"]
    self.assertNotIn("sha256", prompt.lower())
    self.assertNotIn("_hash", prompt)
    self.assertEqual(
      ["C4_PACKET_JSON"],
      [line.split("=", 1)[0] for line in prompt.splitlines() if line.startswith("C4_PACKET")],
    )

  def test_fails_closed_on_invalid_packet(self):
    broken = packet()
    broken["trace_context"]["clause_traces"][0]["connected_guard_binding_ids"] = ["C4-BIND-999"]
    result = self.run_cli({"packet": broken})
    self.assertEqual(1, result.returncode)
    self.assertEqual("C4_CLI_INPUT_INVALID", json.loads(result.stdout)["reason_code"])


TARGET_A = "github:github.com/acme/orders#11"
TARGET_B = "github:github.com/acme/dashboard#707"


class MultiTargetBindingTest(unittest.TestCase):
  def build_git_root(self, root, spec_quote, code_lines, commit_message):
    source = Path(root, "src/orders/cancel.ts")
    source.parent.mkdir(parents=True)
    source.write_text("\n".join(code_lines))
    spec = Path(root, "openspec/specs/orders/spec.md")
    spec.parent.mkdir(parents=True)
    spec.write_text("# Orders\n\n### Requirement: Pending cancellation\n\n" + spec_quote)
    subprocess.run(["git", "-C", root, "init", "-q"], check=True)
    subprocess.run(["git", "-C", root, "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", root, "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", root, "add", "."], check=True)
    subprocess.run(["git", "-C", root, "commit", "-qm", commit_message], check=True)
    return source

  def setUp(self):
    self.root = tempfile.TemporaryDirectory()
    self.addCleanup(self.root.cleanup)
    self.quote_a = "cancelOrder MUST return 409 when state is PENDING"
    trace_quote = "if (order.state === \"PENDING\") {\n  return response.status(200).json(order)\n}"
    self.trace_quote = trace_quote
    self.root_a = str(Path(self.root.name, "repo-orders"))
    self.root_b = str(Path(self.root.name, "repo-dashboard"))
    Path(self.root_a).mkdir()
    Path(self.root_b).mkdir()
    base_lines = ["const stable = true"] + [""] * 86 + [
      "if (order.state === \"PENDING\") {",
      "  return response.status(409).json(order)",
      "}",
    ]
    self.build_git_root(self.root_a, self.quote_a, base_lines, "base a")
    self.build_git_root(self.root_b, self.quote_a, base_lines, "base b")
    base_a = subprocess.run(
      ["git", "-C", self.root_a, "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    base_b = subprocess.run(
      ["git", "-C", self.root_b, "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    for repo_root in (self.root_a, self.root_b):
      source = Path(repo_root, "src/orders/cancel.ts")
      head_lines = [*base_lines]
      head_lines[88] = "  return response.status(200).json(order)"
      source.write_text("\n".join(head_lines))
      subprocess.run(["git", "-C", repo_root, "add", "."], check=True)
      subprocess.run(["git", "-C", repo_root, "commit", "-qm", "head"], check=True)
    self.head_a = subprocess.run(
      ["git", "-C", self.root_a, "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    self.head_b = subprocess.run(
      ["git", "-C", self.root_b, "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    self.base_a = base_a
    self.base_b = base_b

  def multi_packet(self):
    clause_value = {
      "clause_id": "C4-001",
      "contract_type": "ERROR_CONTRACT",
      "spec_path": "openspec/specs/orders/spec.md",
      "line_start": 5,
      "line_end": 5,
      "exact_quote": self.quote_a,
      "source_excerpt": self.quote_a,
      "changed_flow_hint": {
        "actor_or_entity": "order",
        "operation_or_event": "cancelOrder",
        "precondition": "state=PENDING",
        "observable_result": "HTTP 409",
      },
      "target_identity": TARGET_A,
    }
    binding = {
      "binding_id": "C4-BIND-001",
      "side": "head",
      "path": "src/orders/cancel.ts",
      "line_start": 88,
      "line_end": 90,
      "quote": self.trace_quote,
      "target_identity": TARGET_B,
    }
    return {
      "dispatch_id": "c4-dispatch-001",
      "clauses": [clause_value],
      "spec_files": [{"path": "openspec/specs/orders/spec.md", "target_identity": TARGET_A}],
      "changed_files": [
        {"path": "src/orders/cancel.ts", "provenance": "authored", "target_identity": TARGET_B}
      ],
      "evidence_bindings": [binding],
      "trace_context": {
        "authored_diff_binding_ids": ["C4-BIND-001"],
        "connected_guard_binding_ids": [],
        "connected_guard_status": "NONE_REQUIRED",
        "clause_traces": [
          {
            "clause_id": "C4-001",
            "authored_binding_ids": ["C4-BIND-001"],
            "connected_guard_binding_ids": [],
          }
        ],
      },
      "predispatch_verification": {
        "canonical_spec_bound": True,
        "head_bindings_verified": True,
        "base_bindings_status": "NOT_APPLICABLE",
        "hunk_provenance_verified": True,
      },
    }

  def targets_context(self, **overrides):
    entries = {
      TARGET_A: {
        "review_root": self.root_a,
        "authored_diff_base": self.base_a,
        "review_head": self.head_a,
      },
      TARGET_B: {
        "review_root": self.root_b,
        "authored_diff_base": self.base_b,
        "review_head": self.head_b,
      },
    }
    entries.update(overrides)
    return {
      "review_root": self.root_a,
      "authored_diff_base": self.base_a,
      "review_head": self.head_a,
      "targets": entries,
    }

  def single_finding(self):
    return finding()

  def multi_reviewer_output(self, packet_value, findings=None):
    values = findings if findings is not None else [finding()]
    return {
      "reviewer": "spec-compliance-reviewer",
      "dispatch_id": packet_value["dispatch_id"],
      "status": "COMPLETE",
      "contract_accounting": [accounting(values[0]["id"] if values else None)],
      "findings": values,
      "spec_file_accounting": [
        {"path": "openspec/specs/orders/spec.md", "status": "SPEC_REVIEWED"}
      ],
      "summary": {
        "candidates": 1,
        "findings": len(values),
        "full_match": 0,
        "partial_match": 0,
        "mismatch": 1,
        "missing_in_code": 0,
        "code_stronger_than_spec": 0,
        "code_weaker_than_spec": 0,
        "undocumented_behavior": 0,
        "AMBIGUOUS": 0,
      },
      "errors": [],
    }

  def validate_multi(self, packet_value, binding_context, output=None):
    raw = output if output is not None else self.multi_reviewer_output(packet_value)
    transcript = Path(self.root.name, "agent-multi.jsonl")
    prompt = MODULE.render_dispatch_prompt(packet_value)
    runtime_input = {
      "transcript_path": str(transcript),
      "dispatch_id": packet_value["dispatch_id"],
      "expected_agent_id": "agent-smoke-001",
      "packet": packet_value,
      "requested_model": "opus",
      "requested_effort": "high",
    }
    text = json.dumps(raw if output is None else output)
    rows = [
      {
        "type": "user",
        "agentId": "agent-smoke-001",
        "message": {"role": "user", "content": prompt},
      },
      {
        "type": "assistant",
        "agentId": "agent-smoke-001",
        "attributionAgent": "spec-compliance-reviewer",
        "effort": "high",
        "message": {
          "role": "assistant",
          "model": "claude-opus-5",
          "content": [{"type": "text", "text": text}],
        },
      },
    ]
    transcript.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return MODULE.validate_output(
      packet_value,
      raw,
      runtime_input=runtime_input,
      binding_context=binding_context,
    )

  def test_accepts_cross_target_spec_and_code_bindings_when_all_targets_verified(self):
    data = self.multi_packet()
    result = self.validate_multi(data, self.targets_context())
    self.assertEqual("COMPLETE", result["status"])
    self.assertEqual("C4_VALIDATED", result["reason_code"])
    self.assertEqual(["SPEC-001"], [item["id"] for item in result["admitted_findings"]])

  def test_validated_cross_target_finding_routes_to_the_code_target(self):
    data = self.multi_packet()
    result = self.validate_multi(data, self.targets_context())
    self.assertEqual(TARGET_B, result["group_findings"][0]["target_identity"])
    group_path = Path(__file__).with_name("pr-review-group-report.py")
    spec = importlib.util.spec_from_file_location("pr_review_group_report", group_path)
    group = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(group)
    routed = group.route_findings(result["group_findings"], [TARGET_A, TARGET_B])
    self.assertEqual([], routed["refused"])
    self.assertEqual(1, len(routed["groups"]))

  def test_rejects_finding_with_ambiguous_code_target(self):
    data = self.multi_packet()
    second = {
      **data["evidence_bindings"][0],
      "binding_id": "C4-BIND-002",
      "target_identity": TARGET_A,
    }
    data["evidence_bindings"].append(second)
    data["trace_context"]["authored_diff_binding_ids"].append("C4-BIND-002")
    data["trace_context"]["clause_traces"][0]["authored_binding_ids"].append("C4-BIND-002")
    raw = self.multi_reviewer_output(data)
    raw["findings"][0]["trace_anchors"].append({
      key: second[key]
      for key in (
        "binding_id",
        "side",
        "path",
        "line_start",
        "line_end",
        "quote",
      )
    })
    result = self.validate_multi(data, self.targets_context(), output=raw)
    self.assertEqual("FAILED", result["status"])
    self.assertEqual("C4_CODE_TARGET_AMBIGUOUS", result["reason_code"])

  def test_rejects_binding_target_not_among_declared_targets(self):
    data = self.multi_packet()
    data["evidence_bindings"][0]["target_identity"] = "github:github.com/acme/other#1"
    result = self.validate_multi(data, self.targets_context())
    self.assertEqual("FAILED", result["status"])
    self.assertEqual("C4_BINDING_TARGET_INVALID", result["reason_code"])

  def test_rejects_clause_target_not_among_declared_targets(self):
    data = self.multi_packet()
    data["clauses"][0]["target_identity"] = "github:github.com/acme/other#1"
    result = self.validate_multi(data, self.targets_context())
    self.assertEqual("FAILED", result["status"])
    self.assertEqual("C4_BINDING_TARGET_INVALID", result["reason_code"])

  def test_rejects_multi_target_packet_when_authority_root_misses_declared_target(self):
    data = self.multi_packet()
    context = self.targets_context()
    context["targets"][TARGET_A] = {
      "review_root": "/nonexistent-root",
      "authored_diff_base": self.base_a,
      "review_head": self.head_a,
    }
    result = self.validate_multi(data, context)
    self.assertEqual("FAILED", result["status"])
    self.assertEqual("C4_AUTHORITY_BINDING_INVALID", result["reason_code"])

  def test_rejects_multi_target_packet_when_hunk_root_misses_declared_target(self):
    data = self.multi_packet()
    context = self.targets_context()
    context["targets"][TARGET_B] = {
      "review_root": self.root_b,
      "authored_diff_base": "a" * 40,
      "review_head": self.head_b,
    }
    result = self.validate_multi(data, context)
    self.assertEqual("FAILED", result["status"])
    self.assertEqual("C4_HUNK_CONTEXT_INVALID", result["reason_code"])

  def test_invalidates_all_findings_depending_on_failed_target_evidence(self):
    data = self.multi_packet()
    second = {
      **data["evidence_bindings"][0],
      "binding_id": "C4-BIND-002",
      "target_identity": TARGET_A,
    }
    data["evidence_bindings"].append(second)
    data["trace_context"]["authored_diff_binding_ids"].append("C4-BIND-002")
    data["trace_context"]["clause_traces"][0]["authored_binding_ids"].append("C4-BIND-002")
    broken = self.trace_quote.replace("status(200)", "status(201)")
    data["evidence_bindings"][0]["quote"] = broken
    raw = self.multi_reviewer_output(data)
    raw["findings"][0]["trace_anchors"][0]["quote"] = broken
    raw["findings"][0]["trace_anchors"].append({
      key: second[key]
      for key in (
        "binding_id",
        "side",
        "path",
        "line_start",
        "line_end",
        "quote",
      )
    })
    result = self.validate_multi(data, self.targets_context(), output=raw)
    self.assertEqual("COMPLETE", result["status"])
    self.assertEqual([], result["admitted_findings"])
    self.assertEqual(1, result["human_projection"]["invalidated_count"])
    self.assertEqual(
      ["C4_TRACE_HASH_MISMATCH"],
      result["human_projection"]["invalidated_reason_codes"],
    )

  def test_multi_target_packet_keeps_single_clause_and_byte_budget(self):
    data = self.multi_packet()
    data["clauses"] = [
      {**data["clauses"][0], "clause_id": f"C4-{index:03d}"}
      for index in range(1, 52)
    ]
    result = self.validate_multi(data, self.targets_context())
    self.assertEqual("FAILED", result["status"])
    self.assertEqual("C4_PACKET_SCHEMA_INVALID", result["reason_code"])
    over = self.multi_packet()
    over["clauses"][0]["changed_flow_hint"]["observable_result"] = "x" * 120001
    result = self.validate_multi(over, self.targets_context())
    self.assertEqual("FAILED", result["status"])
    self.assertEqual("C4_PACKET_SCHEMA_INVALID", result["reason_code"])

  def test_single_target_packet_with_targets_map_fails_closed(self):
    legacy = self.multi_packet()
    for item in legacy["clauses"] + legacy["spec_files"] + legacy["changed_files"] + legacy["evidence_bindings"]:
      del item["target_identity"]
    result = self.validate_multi(
      legacy,
      {
        "review_root": self.root_b,
        "authored_diff_base": self.base_b,
        "review_head": self.head_b,
      },
    )
    self.assertEqual("COMPLETE", result["status"])
    self.assertEqual("C4_VALIDATED", result["reason_code"])
    with_targets = self.multi_packet()
    with_targets["clauses"][0]["target_identity"] = TARGET_A
    result = self.validate_multi(
      with_targets,
      {
        "review_root": self.root_b,
        "authored_diff_base": self.base_b,
        "review_head": self.head_b,
      },
    )
    self.assertEqual("FAILED", result["status"])
    self.assertEqual("C4_BINDING_TARGET_INVALID", result["reason_code"])

  def test_packet_targets_helper_reports_identities(self):
    data = self.multi_packet()
    self.assertEqual({TARGET_A, TARGET_B}, MODULE.packet_targets(data))
    self.assertTrue(MODULE.packet_is_multi_target(data))


SPEC_DOC = "# Orders\n\n### Requirement: Pending cancellation\n\n" + QUOTE
ORDERS_ORIGIN = "https://github.com/acme/orders.git"
DASHBOARD_ORIGIN = "https://github.com/acme/dashboard.git"
DECLARED_PROFILES = """\
acme/dashboard:
  trunk: main
  authority:
    live: docs/pages/*.md
    change: .scratch/*/spec.md
acme/orders:
  trunk: main
  authority:
    change: docs/specs/*.md
"""
CODE_BASE_LINES = ["const stable = true"] + [""] * 86 + [
  "if (order.state === \"PENDING\") {",
  "  return response.status(409).json(order)",
  "}",
]
CODE_HEAD_LINES = [*CODE_BASE_LINES]
CODE_HEAD_LINES[88] = "  return response.status(200).json(order)"
CODE_PATH = "src/orders/cancel.ts"


class DeclaredPacketAuthorityTest(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp.cleanup)
    self.home = Path(self.tmp.name, "home")
    write_profile(self.home, DECLARED_PROFILES)
    patcher = mock.patch.dict(os.environ, {"HOME": str(self.home)})
    patcher.start()
    self.addCleanup(patcher.stop)

  def make_target(self, name, origin, base_docs, head_docs):
    root = Path(self.tmp.name, name)
    root.mkdir()
    base, head = make_repo(
      root,
      {CODE_PATH: "\n".join(CODE_BASE_LINES), **base_docs},
      {CODE_PATH: "\n".join(CODE_HEAD_LINES), **head_docs},
      origin=origin,
    )
    return {"review_root": str(root), "authored_diff_base": base, "review_head": head}

  def resolved_clause(self, context, spec_path):
    result = resolve_cli(
      context["review_root"],
      self.home,
      {**doc_candidate(spec_path, SPEC_DOC), "line_start": 5, "line_end": 5},
      authored_diff_base=context["authored_diff_base"],
      review_head=context["review_head"],
    )
    self.assertEqual("RESOLVED", result["status"])
    return result["clause"]

  def packet_for(self, clause_value, code_target=None):
    spec_path = clause_value["spec_path"]
    value = json.loads(json.dumps(packet()))
    value["clauses"] = [clause_value]
    value["spec_files"] = [{"path": spec_path}]
    clause_target = clause_value.get("target_identity")
    if clause_target is not None:
      value["spec_files"][0]["target_identity"] = clause_target
      value["changed_files"][0]["target_identity"] = code_target
      value["evidence_bindings"][0]["target_identity"] = code_target
    return value

  def output_for(self, spec_path):
    raw = json.dumps(reviewer_output()).replace("openspec/specs/orders/spec.md", spec_path)
    return json.loads(raw)

  def validate(self, packet_value, binding_context):
    spec_path = packet_value["clauses"][0]["spec_path"]
    raw = self.output_for(spec_path)
    transcript = Path(self.tmp.name, "agent.jsonl")
    rows = [
      {
        "type": "user",
        "agentId": "agent-smoke-001",
        "message": {"role": "user", "content": MODULE.render_dispatch_prompt(packet_value)},
      },
      {
        "type": "assistant",
        "agentId": "agent-smoke-001",
        "attributionAgent": "spec-compliance-reviewer",
        "effort": "high",
        "message": {
          "role": "assistant",
          "model": "claude-opus-5",
          "content": [{"type": "text", "text": json.dumps(raw)}],
        },
      },
    ]
    transcript.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return MODULE.validate_output(
      packet_value,
      raw,
      runtime_input={
        "transcript_path": str(transcript),
        "dispatch_id": packet_value["dispatch_id"],
        "expected_agent_id": "agent-smoke-001",
        "packet": packet_value,
        "requested_model": "opus",
        "requested_effort": "high",
      },
      binding_context=binding_context,
    )

  def assert_accepted(self, result):
    self.assertEqual("COMPLETE", result["status"], result)
    self.assertEqual("C4_VALIDATED", result["reason_code"])

  def assert_rejected(self, result):
    self.assertEqual("FAILED", result["status"], result)
    self.assertEqual("C4_AUTHORITY_BINDING_INVALID", result["reason_code"])

  def test_live_clause_resolved_by_stage_one_is_accepted_unchanged_by_stage_two(self):
    context = self.make_target(
      "dashboard", DASHBOARD_ORIGIN, {"docs/pages/orders.md": SPEC_DOC}, {}
    )
    clause_value = self.resolved_clause(context, "docs/pages/orders.md")
    self.assert_accepted(self.validate(self.packet_for(clause_value), context))

  def test_change_clause_touched_by_the_pull_request_is_accepted(self):
    context = self.make_target(
      "dashboard",
      DASHBOARD_ORIGIN,
      {},
      {".scratch/view-b/spec.md": SPEC_DOC},
    )
    clause_value = self.resolved_clause(context, ".scratch/view-b/spec.md")
    self.assert_accepted(self.validate(self.packet_for(clause_value), context))

  def test_spec_path_rewritten_to_an_undeclared_location_is_rejected(self):
    context = self.make_target(
      "dashboard",
      DASHBOARD_ORIGIN,
      {"docs/pages/orders.md": SPEC_DOC},
      {"openspec/specs/orders/spec.md": SPEC_DOC, "README.md": SPEC_DOC},
    )
    clause_value = self.resolved_clause(context, "docs/pages/orders.md")
    for rewritten in ("openspec/specs/orders/spec.md", "README.md"):
      with self.subTest(spec_path=rewritten):
        forged = {**clause_value, "spec_path": rewritten}
        self.assert_rejected(self.validate(self.packet_for(forged), context))

  def test_change_document_the_pull_request_did_not_touch_is_rejected(self):
    context = self.make_target(
      "dashboard",
      DASHBOARD_ORIGIN,
      {".scratch/view-b/spec.md": SPEC_DOC},
      {},
    )
    clause_value = {
      **doc_candidate(".scratch/view-b/spec.md", SPEC_DOC),
      "line_start": 5,
      "line_end": 5,
      "source_excerpt": SPEC_DOC,
    }
    self.assert_rejected(self.validate(self.packet_for(clause_value), context))

  def test_unreadable_profile_falls_back_to_openspec(self):
    context = self.make_target(
      "dashboard",
      DASHBOARD_ORIGIN,
      {"docs/pages/orders.md": SPEC_DOC, "openspec/specs/orders/spec.md": SPEC_DOC},
      {},
    )
    clause_value = self.resolved_clause(context, "docs/pages/orders.md")
    # 要帶 trunk：缺 trunk 的條目被視為沒有 profile，根本不會走到型別檢查
    write_profile(self.home, "acme/dashboard:\n  trunk: main\n  authority:\n    live: 5\n")
    openspec_clause = {**clause_value, "spec_path": "openspec/specs/orders/spec.md"}
    self.assertTrue(
      MODULE.packet_authority_valid(context, {"clauses": [openspec_clause]})
    )
    self.assertFalse(
      MODULE.packet_authority_valid(context, {"clauses": [clause_value]})
    )

  def test_declared_repo_rejects_an_archive_alias(self):
    context = self.make_target(
      "dashboard",
      DASHBOARD_ORIGIN,
      {"docs/pages/orders.md": SPEC_DOC, "openspec/changes/archive/old/spec.md": SPEC_DOC},
      {},
    )
    clause_value = self.resolved_clause(context, "docs/pages/orders.md")
    aliased = {**clause_value, "authority_alias_path": "openspec/changes/archive/old/spec.md"}
    self.assertFalse(MODULE.packet_authority_valid(context, {"clauses": [aliased]}))

  def multi_context(self):
    docs = {"docs/pages/orders.md": SPEC_DOC}
    orders = self.make_target("orders", ORDERS_ORIGIN, docs, {"docs/specs/orders.md": SPEC_DOC})
    dashboard = self.make_target(
      "dashboard",
      DASHBOARD_ORIGIN,
      docs,
      {},
    )
    return {
      **orders,
      "targets": {TARGET_A: orders, TARGET_B: dashboard},
    }

  def multi_clause(self, context, target, spec_path):
    entry = context["targets"][target]
    return {**self.resolved_clause(entry, spec_path), "target_identity": target}

  def test_each_clause_is_judged_by_the_profile_of_its_own_target(self):
    context = self.multi_context()
    cases = (
      (TARGET_A, "docs/specs/orders.md"),
      (TARGET_B, "docs/pages/orders.md"),
    )
    for target, spec_path in cases:
      with self.subTest(target=target, spec_path=spec_path):
        clause_value = self.multi_clause(context, target, spec_path)
        result = self.validate(self.packet_for(clause_value, code_target=TARGET_B), context)
        self.assert_accepted(result)

  def test_dashboard_page_clause_labelled_as_the_saas_target_is_rejected(self):
    context = self.multi_context()
    clause_value = self.multi_clause(context, TARGET_B, "docs/pages/orders.md")
    mislabelled = {**clause_value, "target_identity": TARGET_A}
    self.assert_rejected(
      self.validate(self.packet_for(mislabelled, code_target=TARGET_B), context)
    )


if __name__ == "__main__":
  unittest.main()
