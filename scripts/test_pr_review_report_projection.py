#!/usr/bin/env python3

import importlib.util
import os
import re
import statistics
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from markdown_it import MarkdownIt


MODULE_PATH = Path(__file__).with_name("pr-review-report-projection.py")


def load_module():
  spec = importlib.util.spec_from_file_location("pr_review_report_projection", MODULE_PATH)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


REPORT_ROOT = MODULE_PATH.parent.parent / "pr-review-reports"
REPORT_ROOTS = [
  REPORT_ROOT / "oldco-api",
  REPORT_ROOT / "oldco-shop",
]


def report_paths(root, number=1):
  return (
    Path(root, f"pr-{number}-review.audit.draft.md"),
    Path(root, f"pr-{number}-review.audit.md"),
    Path(root, f"pr-{number}-review.md"),
  )


def report_date(path):
  match = re.search(r"(?m)^\*\*審查日期\*\*:\s*(\d{4}-\d{2}-\d{2})", path.read_text())
  return match.group(1) if match else "0000-00-00"


def replayable_report(path):
  text = path.read_text()
  return bool(
    re.search(r"(?m)^## 發現總覽$", text)
    and re.search(r"(?m)^\| # .*問題.*最終建議.*Action.*Action 理由", text)
    and "### Inline Comments per Finding" in text
  )


def recent_reports(limit=10):
  selected = {}
  for root in REPORT_ROOTS:
    for path in root.glob("pr-*-review*.md"):
      if path.name.endswith(".audit.draft.md"):
        continue
      key = path.name.replace(".audit.md", ".md")
      current = selected.get((root, key))
      if current is None or path.name.endswith(".audit.md"):
        selected[(root, key)] = path
  reports = [path for path in selected.values() if replayable_report(path)]
  return sorted(reports, key=lambda path: (report_date(path), path.stat().st_mtime), reverse=True)[:limit]


def comment_payloads(text):
  lines = text.splitlines(keepends=True)
  result = []
  index = 0
  while index < len(lines):
    if not lines[index].startswith("**Comment**:"):
      index += 1
      continue
    index += 1
    while index < len(lines) and not re.match(r" {0,3}(`{3,}|~{3,})", lines[index]):
      index += 1
    if index >= len(lines):
      break
    marker = re.match(r" {0,3}(`{3,}|~{3,})", lines[index]).group(1)
    index += 1
    payload = []
    while index < len(lines):
      closing = re.match(r" {0,3}(`{3,}|~{3,})\s*$", lines[index])
      if closing and closing.group(1)[0] == marker[0] and len(closing.group(1)) >= len(marker):
        break
      payload.append(lines[index])
      index += 1
    value = "".join(payload)
    if value.endswith("\r\n"):
      value = value[:-2]
    elif value.endswith(("\n", "\r")):
      value = value[:-1]
    result.append(value)
    index += 1
  return result


def no_op_ordinals(text):
  result = set()
  action_column = None
  in_finding_table = False
  for line in text.splitlines():
    if line.startswith("|"):
      cells = [cell.strip().strip("`") for cell in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
      if cells and cells[0].lower() == "#":
        in_finding_table = True
        action_column = next(
          (index for index, cell in enumerate(cells) if cell.lower() == "action"),
          None,
        )
        continue
      if in_finding_table and action_column is not None and action_column < len(cells):
        ordinal = re.fullmatch(r"(?:F-)?(\d+)", cells[0])
        if ordinal and cells[action_column].lower() == "no-op":
          result.add(int(ordinal.group(1)))
      continue
    in_finding_table = False
    action_column = None
    match = re.search(r"\bF-(\d+)\b.*\baction\s*=\s*no-op\b", line, re.IGNORECASE)
    if match:
      result.add(int(match.group(1)))
  return result


def actionable_comment_payloads(text):
  no_ops = no_op_ordinals(text)
  headings = list(re.finditer(r"(?m)^#### #?(?:F-)?(\d+)[a-z]?\b[^\n]*\n", text))
  result = []
  for index, heading in enumerate(headings):
    end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
    if int(heading.group(1)) in no_ops:
      continue
    result.extend(comment_payloads(text[heading.start():end]))
  return result


def expected_finding_uids(text):
  summary = re.search(r"(?m)^## 發現總覽[^\n]*\n", text)
  if not summary:
    return []
  remainder = text[summary.end():]
  boundary = re.search(r"(?m)^#{2,3} Inline Comments per Finding[^\n]*\n", remainder)
  scope = remainder[:boundary.start()] if boundary else remainder
  result = []
  for line in scope.splitlines():
    if not re.search(r"\bF-\d+\b|finding_uid|內部 uid|內部結構", line, re.IGNORECASE):
      continue
    result.extend(re.findall(r"(?<![0-9a-f])([0-9a-f]{20})(?![0-9a-f])", line))
  return list(dict.fromkeys(result))


def state_lines(text):
  prefixes = (
    "**Prior review continuity**:",
    "**審查工具**:",
    "**Reviewer models**:",
    "**覆蓋 (ENH-A)**:",
    "**定位 (ENH-B)**:",
    "**Formal spec traceability (2.65)**:",
  )
  preamble = re.split(r"(?m)^## ", text, maxsplit=1)[0]
  return [line for line in preamble.splitlines() if line.startswith(prefixes)]


def minimal_report():
  return """# PR #1 Code Review

**Report projection schema**: 1
**Review input basis**: input_binding: verified
**覆蓋 (ENH-A)**: missed 0
**React-doctor (2.97)**: 未引入新問題
**Formal spec traceability (2.65)**: SKIPPED

## 發現總覽

| # | 問題 | 最終建議 | Action | Action 理由 |
|---|---|---|---|---|
| F-01 | 問題 | Should Fix | auto-fix | 修法明確 |

F-01 finding_uid: 0123456789abcdef0123 action=auto-fix

### Inline Comments per Finding

#### F-01 問題

**File**: `src/a.ts`
**Line**: 1

**Comment**:
```
ACTIONABLE_PAYLOAD
```
"""


def schema2_report():
  source = minimal_report().replace(
    "**Report projection schema**: 1",
    "**Report projection schema**: 2",
  ).replace(
    "**Formal spec traceability (2.65)**: SKIPPED",
    "**Prior review continuity**: N-A (no prior audit)\n**Formal spec traceability (2.65)**: SKIPPED",
  )
  return source.replace(
    "## 發現總覽",
    "## 上一輪 findings 對帳\n\nN-A — no prior audit\n\n## 發現總覽",
  )


class ProjectionTest(unittest.TestCase):
  def test_projection_helper_exists(self):
    self.assertTrue(MODULE_PATH.is_file())

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_rejects_unclosed_markdown_fence(self):
    module = load_module()
    source = """# PR #1 Code Review

```text
unterminated

## 發現總覽

F-01 0123456789abcdef0123
"""
    with self.assertRaisesRegex(ValueError, "unclosed Markdown fence"):
      module.project_report(source, "pr-1-review.audit.md")

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_indented_or_wrong_container_fence_does_not_close_root_fence(self):
    module = load_module()
    variants = (
      "```\npayload\n    ```\nAFTER\n",
      "> ```\n> payload\n```\nAFTER\n",
    )
    for source in variants:
      with self.subTest(source=source):
        with self.assertRaisesRegex(ValueError, "unclosed Markdown fence"):
          module.assert_balanced_fences(source)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_balanced_fence_inside_markdown_container_is_allowed(self):
    module = load_module()
    variants = (
      "> ```\n> payload\n> ```\n",
      "- item\n\n  ~~~\n  payload\n  ~~~\n",
    )
    for source in variants:
      with self.subTest(source=source):
        module.assert_balanced_fences(source)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_backtick_in_info_string_is_not_a_fence(self):
    module = load_module()
    source = minimal_report() + "\n## 本輪限制\n\n```foo`bar\n"
    main = module.project_report(source, "pr-1-review.audit.md")
    self.assertIn("```foo`bar", main)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_rejects_source_missing_uid_or_comment_block(self):
    malformed = (
      minimal_report().replace("F-01 finding_uid: 0123456789abcdef0123 action=auto-fix\n", ""),
      minimal_report().replace("**Comment**:\n```\nACTIONABLE_PAYLOAD\n```\n", ""),
    )
    for source in malformed:
      with self.subTest(source=source):
        module = load_module()
        with self.assertRaisesRegex(ValueError, "source report contract mismatch"):
          module.project_report(source, "pr-1-review.audit.md")

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_action_column_controls_noop_filtering(self):
    module = load_module()
    source = minimal_report().replace(
      "| F-01 | 問題 | Should Fix | auto-fix | 修法明確 |",
      "| F-01 | no-op | Should Fix | auto-fix | 修法明確 |",
    )
    main = module.project_report(source, "pr-1-review.audit.md")
    self.assertIn("ACTIONABLE_PAYLOAD", main)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_prior_review_continuity_section_is_preserved(self):
    module = load_module()
    source = schema2_report().replace(
      "**Prior review continuity**: N-A (no prior audit)",
      "**Prior review continuity**: CHECKED (fixed 0 / still-open 1 / stale 0)",
    ).replace(
      "N-A — no prior audit",
      """| 前輪 finding_uid | 問題 | 狀態 | 本輪證據 |
|---|---|---|---|
| `fedcba9876543210fedc` | 舊問題 | `STILL_OPEN` | `src/old.ts:8` |""",
    )
    main = module.project_report(source, "pr-1-review.audit.md", require_schema=True)
    state = "**Prior review continuity**: CHECKED (fixed 0 / still-open 1 / stale 0)"
    self.assertIn(state, module.extract_state_lines(source))
    self.assertIn(state, main)
    self.assertIn("## 上一輪 findings 對帳", main)
    self.assertIn("fedcba9876543210fedc", main)
    self.assertIn("STILL_OPEN", main)
    self.assertNotIn("[fedcba9876543210fedc](pr-1-review.audit.md#發現總覽)", main)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_schema_two_requires_exact_prior_continuity_contract(self):
    module = load_module()
    variants = (
      schema2_report().replace("**Prior review continuity**: N-A (no prior audit)\n", ""),
      schema2_report().replace("## 上一輪 findings 對帳", "## 上一輪 findings 對帳（Step 4.7）"),
      schema2_report().replace("## 上一輪 findings 對帳\n\nN-A — no prior audit\n\n", ""),
    )
    for source in variants:
      with self.subTest(source=source):
        with self.assertRaisesRegex(ValueError, "required-state|prior-review-continuity"):
          module.project_report(source, "pr-1-review.audit.md", require_schema=True)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_schema_two_enforces_prior_status_tally_and_unique_uids(self):
    module = load_module()
    valid = schema2_report().replace(
      "**Prior review continuity**: N-A (no prior audit)",
      "**Prior review continuity**: CHECKED (fixed 0 / still-open 1 / stale 0)",
    ).replace(
      "N-A — no prior audit",
      """| 前輪 finding_uid | 問題 | 狀態 | 本輪證據 |
|---|---|---|---|
| `fedcba9876543210fedc` | 舊問題 | `STILL_OPEN` | `src/old.ts:8` |""",
    )
    invalid = (
      valid.replace("still-open 1", "still-open 2"),
      valid.replace(
        "| `fedcba9876543210fedc` | 舊問題 | `STILL_OPEN` | `src/old.ts:8` |",
        """| `fedcba9876543210fedc` | 舊問題 | `STILL_OPEN` | `src/old.ts:8` |
| `fedcba9876543210fedc` | 重複 | `STILL_OPEN` | `src/old.ts:9` |""",
      ),
    )
    for source in invalid:
      with self.subTest(source=source):
        with self.assertRaisesRegex(ValueError, "prior-review-continuity"):
          module.project_report(source, "pr-1-review.audit.md", require_schema=True)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_schema_one_remains_legacy_compatible(self):
    module = load_module()
    main = module.project_report(minimal_report(), "pr-1-review.audit.md", require_schema=True)
    self.assertNotIn("Prior review continuity", main)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_inline_title_collision_in_limitation_is_preserved(self):
    module = load_module()
    source = minimal_report() + """

## 沒做的部分

### Inline Comments per Finding

#### F-01 這是限制，不是留言

LIMITATION_MUST_SURVIVE

### 其他限制

TAIL_MUST_SURVIVE
"""
    main = module.project_report(source, "pr-1-review.audit.md", require_schema=True)
    self.assertIn("LIMITATION_MUST_SURVIVE", main)
    self.assertIn("TAIL_MUST_SURVIVE", main)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_noop_filter_does_not_remove_limitation_h4(self):
    module = load_module()
    source = minimal_report().replace(
      "| F-01 | 問題 | Should Fix | auto-fix | 修法明確 |",
      "| F-01 | 問題 | 參考用 | no-op | 非本 PR 缺陷 |",
    ).replace(
      "action=auto-fix",
      "action=no-op",
    ) + "\n## 本輪限制\n\n#### F-01 限制說明\n\nLIMITATION_CONTENT\n"
    main = module.project_report(source, "pr-1-review.audit.md", require_schema=True)
    self.assertNotIn("ACTIONABLE_PAYLOAD", main)
    self.assertIn("LIMITATION_CONTENT", main)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_finding_table_handles_escaped_pipe_and_first_cell_ordinal(self):
    module = load_module()
    escaped_pipe = minimal_report().replace(
      "| F-01 | 問題 | Should Fix | auto-fix | 修法明確 |",
      r"| F-01 | `(left \| right)` 會走錯分支 | Should Fix | auto-fix | 修法明確 |",
    )
    numeric_ordinal = minimal_report().replace(
      "| F-01 | 問題 | Should Fix | auto-fix | 修法明確 |",
      "| 1 | 問題引用 F-02 | Should Fix | auto-fix | 修法明確 |",
    )
    for source in (escaped_pipe, numeric_ordinal):
      with self.subTest(source=source):
        main = module.project_report(source, "pr-1-review.audit.md", require_schema=True)
        self.assertIn("ACTIONABLE_PAYLOAD", main)
        tokens = MarkdownIt("commonmark").enable("table").parse(main)
        self.assertIn("table_open", [token.type for token in tokens])
        cells = [tokens[index + 1].content for index, token in enumerate(tokens) if token.type == "td_open"]
        self.assertIn("auto-fix", cells)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_finding_data_cell_named_action_is_not_a_header(self):
    module = load_module()
    source = minimal_report().replace(
      "| F-01 | 問題 | Should Fix | auto-fix | 修法明確 |",
      "| F-01 | Action | Should Fix | auto-fix | 修法明確 |",
    )
    main = module.project_report(source, "pr-1-review.audit.md", require_schema=True)
    self.assertIn("ACTIONABLE_PAYLOAD", main)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_finding_table_rejects_unescaped_pipe_inside_code_span(self):
    module = load_module()
    source = minimal_report().replace(
      "| F-01 | 問題 | Should Fix | auto-fix | 修法明確 |",
      "| F-01 | `left | right` 會失效 | Should Fix | auto-fix |",
    )
    with self.assertRaisesRegex(ValueError, "source report contract mismatch"):
      module.project_report(source, "pr-1-review.audit.md", require_schema=True)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_finding_table_requires_one_canonical_header(self):
    module = load_module()
    missing_header = minimal_report().replace(
      "| # | 問題 | 最終建議 | Action | Action 理由 |",
      "| 編號 | 問題 | 最終建議 | Action |",
    ).replace(
      "F-01 finding_uid: 0123456789abcdef0123 action=auto-fix\n",
      "",
    ).replace(
      "#### F-01 問題\n\n**File**: `src/a.ts`\n**Line**: 1\n\n**Comment**:\n```\nACTIONABLE_PAYLOAD\n```\n",
      "",
    )
    duplicate_header = minimal_report().replace(
      "### Inline Comments per Finding",
      "| # | 問題 | 最終建議 | Action | Action 理由 |\n|---|---|---|---|---|\n\n### Inline Comments per Finding",
    )
    missing_separator = minimal_report().replace("|---|---|---|---|---|\n", "")
    for source in (missing_header, duplicate_header, missing_separator):
      with self.subTest(source=source):
        with self.assertRaisesRegex(ValueError, "source report contract mismatch"):
          module.project_report(source, "pr-1-review.audit.md", require_schema=True)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_finding_table_inside_fence_is_not_canonical(self):
    module = load_module()
    table = "| # | 問題 | 最終建議 | Action | Action 理由 |\n|---|---|---|---|---|\n| F-01 | 問題 | Should Fix | auto-fix | 修法明確 |"
    source = minimal_report().replace(table, f"```markdown\n{table}\n```")
    with self.assertRaisesRegex(ValueError, "source report contract mismatch"):
      module.project_report(source, "pr-1-review.audit.md", require_schema=True)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_html_blocks_cannot_supply_canonical_table_or_uid(self):
    module = load_module()
    table = "| # | 問題 | 最終建議 | Action | Action 理由 |\n|---|---|---|---|---|\n| F-01 | 問題 | Should Fix | auto-fix | 修法明確 |"
    canonical_uid = "F-01 finding_uid: 0123456789abcdef0123 action=auto-fix"
    html_table = minimal_report().replace(table, f"<pre>\n{table}\n</pre>")
    html_uid = minimal_report().replace(canonical_uid, f"<pre>\n{canonical_uid}\n</pre>")
    for source in (html_table, html_uid):
      with self.subTest(source=source):
        with self.assertRaisesRegex(ValueError, "source report contract mismatch"):
          module.project_report(source, "pr-1-review.audit.md", require_schema=True)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_finding_table_requires_matching_width_and_one_action_column(self):
    module = load_module()
    short_separator = minimal_report().replace("|---|---|---|---|---|", "|---|---|---|")
    duplicate_action = minimal_report().replace(
      "| # | 問題 | 最終建議 | Action | Action 理由 |",
      "| # | 問題 | Action | Action |",
    ).replace(
      "| F-01 | 問題 | Should Fix | auto-fix | 修法明確 |",
      "| F-01 | 問題 | auto-fix | no-op |",
    )
    short_row = minimal_report().replace(
      "| F-01 | 問題 | Should Fix | auto-fix | 修法明確 |",
      "| F-01 | 問題 | auto-fix |",
    )
    duplicate_ordinal_column = minimal_report().replace(
      "| # | 問題 | 最終建議 | Action | Action 理由 |",
      "| # | # | 最終建議 | Action |",
    )
    for source in (short_separator, duplicate_action, short_row, duplicate_ordinal_column):
      with self.subTest(source=source):
        with self.assertRaisesRegex(ValueError, "source report contract mismatch"):
          module.project_report(source, "pr-1-review.audit.md", require_schema=True)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_finding_table_rejects_malformed_ordinal_row(self):
    module = load_module()
    source = minimal_report().replace(
      "| F-01 | 問題 | Should Fix | auto-fix | 修法明確 |",
      "| F-01 | 問題 | Should Fix | auto-fix | 修法明確 |\n| F-O2 | silently unbound | Should Fix | ask-user |",
    )
    with self.assertRaisesRegex(ValueError, "source report contract mismatch"):
      module.project_report(source, "pr-1-review.audit.md", require_schema=True)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_required_header_lines_inside_comment_do_not_satisfy_source_contract(self):
    module = load_module()
    required = (
      "**Report projection schema**: 1",
      "**覆蓋 (ENH-A)**: missed 0",
      "**Formal spec traceability (2.65)**: SKIPPED",
    )
    source = minimal_report()
    for line in required:
      source = source.replace(f"{line}\n", "")
    source = source.replace("ACTIONABLE_PAYLOAD", "ACTIONABLE_PAYLOAD\n" + "\n".join(required))
    with self.assertRaisesRegex(ValueError, "source report contract mismatch"):
      module.project_report(source, "pr-1-review.audit.md", require_schema=True)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_unrelated_h2_containing_keep_title_does_not_leak(self):
    module = load_module()
    source = minimal_report() + "\n## CC 原始發現總覽備份\n\nRAW_PRIVATE_EVIDENCE\n"
    main = module.project_report(source, "pr-1-review.audit.md")
    self.assertNotIn("RAW_PRIVATE_EVIDENCE", main)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_strict_uid_mapping_ignores_hashes_in_finding_text(self):
    module = load_module()
    hash_value = "aaaaaaaaaaaaaaaaaaaa"
    missing_uid = minimal_report().replace(
      "| F-01 | 問題 | Should Fix | auto-fix | 修法明確 |",
      f"| F-01 | `{hash_value}` 被硬編碼 | Should Fix | auto-fix | 修法明確 |",
    ).replace("F-01 finding_uid: 0123456789abcdef0123 action=auto-fix\n", "")
    with self.assertRaisesRegex(ValueError, "source report contract mismatch"):
      module.project_report(missing_uid, "pr-1-review.audit.md", require_schema=True)
    explicit_uid = minimal_report().replace(
      "| F-01 | 問題 | Should Fix | auto-fix | 修法明確 |",
      f"| F-01 | `{hash_value}` 被硬編碼 | Should Fix | auto-fix | 修法明確 |",
    )
    main = module.project_report(explicit_uid, "pr-1-review.audit.md", require_schema=True)
    self.assertIn("[0123456789abcdef0123](pr-1-review.audit.md#發現總覽)", main)
    self.assertNotIn(f"[{hash_value}](pr-1-review.audit.md#發現總覽)", main)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_strict_uid_line_requires_outside_fence_matching_action(self):
    module = load_module()
    canonical = "F-01 finding_uid: 0123456789abcdef0123 action=auto-fix"
    fenced = minimal_report().replace(canonical, f"```text\n{canonical}\n```")
    conflicting = minimal_report().replace("action=auto-fix\n\n### Inline", "action=no-op\n\n### Inline")
    missing_action = minimal_report().replace(" action=auto-fix\n\n### Inline", "\n\n### Inline")
    for source in (fenced, conflicting, missing_action):
      with self.subTest(source=source):
        with self.assertRaisesRegex(ValueError, "source report contract mismatch"):
          module.project_report(source, "pr-1-review.audit.md", require_schema=True)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_schema_one_rejects_noncanonical_uid_record_spelling(self):
    module = load_module()
    canonical = "F-01 finding_uid: 0123456789abcdef0123 action=auto-fix"
    invalid_records = (
      "F-1 finding_uid: 0123456789abcdef0123 action=auto-fix",
      "F-01 finding_uid=0123456789abcdef0123 action=auto-fix",
      "F-01 finding_uid: 0123456789ABCDEF0123 action=auto-fix",
      "F-01 finding_uid: 0123456789abcdef0123 action = auto-fix",
      " F-01 finding_uid: 0123456789abcdef0123 action = auto-fix",
      "  F-01 finding_uid: 0123456789abcdef0123 action = auto-fix",
      "   F-01 finding_uid: 0123456789abcdef0123 action = auto-fix",
    )
    for invalid in invalid_records:
      with self.subTest(record=invalid):
        source = minimal_report().replace(canonical, invalid)
        with self.assertRaisesRegex(ValueError, "source report contract mismatch"):
          module.project_report(source, "pr-1-review.audit.md", require_schema=True)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_schema_one_requires_contiguous_ordinals_and_rejects_reserved_near_miss(self):
    module = load_module()
    non_contiguous = minimal_report().replace("F-01", "F-02")
    near_miss = minimal_report().replace(
      "F-01 finding_uid: 0123456789abcdef0123 action=auto-fix",
      "F-01 finding_uid: 0123456789abcdef0123 action=auto-fix\nF-01 finding_uid: fedcba9876543210fedc action = no-op",
    )
    padded_prefixed = minimal_report().replace("| F-01 |", "| F-001 |").replace(
      "#### F-01 問題",
      "#### F-001 問題",
    )
    padded_plain = minimal_report().replace("| F-01 |", "| 0001 |").replace(
      "#### F-01 問題",
      "#### #0001 問題",
    )
    for source in (non_contiguous, near_miss, padded_prefixed, padded_plain):
      with self.subTest(source=source):
        with self.assertRaisesRegex(ValueError, "source report contract mismatch"):
          module.project_report(source, "pr-1-review.audit.md", require_schema=True)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_indented_code_cannot_supply_canonical_uid(self):
    module = load_module()
    canonical = "F-01 finding_uid: 0123456789abcdef0123 action=auto-fix"
    summary_indented = minimal_report().replace(canonical, f"    {canonical}")
    block_indented = minimal_report().replace(f"{canonical}\n\n", "").replace(
      "**File**: `src/a.ts`",
      "    finding_uid: 0123456789abcdef0123\n\n**File**: `src/a.ts`",
    )
    for source in (summary_indented, block_indented):
      with self.subTest(source=source):
        with self.assertRaisesRegex(ValueError, "source report contract mismatch"):
          module.project_report(source, "pr-1-review.audit.md", require_schema=True)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_schema_one_rejects_uid_only_in_finding_block(self):
    module = load_module()
    uid = "0123456789abcdef0123"
    source = f"""# PR #1 Code Review

**Report projection schema**: 1
**覆蓋 (ENH-A)**: missed 0
**Formal spec traceability (2.65)**: SKIPPED

## 發現總覽

| # | 問題 | Action |
|---|---|---|
| F-01 | 參考項 | no-op |

### Inline Comments per Finding

#### F-01 參考項

finding_uid: {uid}

**File**: `src/a.ts`
**Line**: 1

**Comment**:
```
不是 PR 缺陷。
```
"""
    with self.assertRaisesRegex(ValueError, "source report contract mismatch"):
      module.project_report(source, "pr-1-review.audit.md", require_schema=True)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_architecture_finding_can_declare_no_inline_comment(self):
    module = load_module()
    uid = "0123456789abcdef0123"
    source = f"""# PR #1 Code Review

**Report projection schema**: 1
**覆蓋 (ENH-A)**: missed 0
**Formal spec traceability (2.65)**: SKIPPED

## 發現總覽

| # | 問題 | 最終建議 | Action | Action 理由 |
|---|---|---|---|---|
| F-01 | 純架構觀察 | 參考用 | no-op | 無可定位位置 |

F-01 finding_uid: {uid} action=no-op inline=none

### Inline Comments per Finding
"""
    main = module.project_report(source, "pr-1-review.audit.md", require_schema=True)
    self.assertIn(f"[{uid}](pr-1-review.audit.md#發現總覽)", main)
    self.assertNotIn("**Comment**:", main)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_inline_comment_section_rejects_orphan_payload(self):
    module = load_module()
    source = """# PR #1 Code Review

**Report projection schema**: 1
**覆蓋 (ENH-A)**: missed 0
**Formal spec traceability (2.65)**: SKIPPED

## 發現總覽

| # | 問題 | 最終建議 | Action | Action 理由 |
|---|---|---|---|---|
| F-01 | 純架構觀察 | 參考用 | no-op | 無可定位位置 |

F-01 finding_uid: 0123456789abcdef0123 action=no-op inline=none

### Inline Comments per Finding

**Comment**:
```
ORPHAN_PAYLOAD
```
"""
    with self.assertRaisesRegex(ValueError, "source report contract mismatch"):
      module.project_report(source, "pr-1-review.audit.md", require_schema=True)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_inline_comment_heading_rejects_arbitrary_suffix(self):
    module = load_module()
    source = minimal_report().replace(
      "### Inline Comments per Finding",
      "### Inline Comments per Finding RAW",
    )
    with self.assertRaisesRegex(ValueError, "source report contract mismatch"):
      module.project_report(source, "pr-1-review.audit.md", require_schema=True)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_actionable_finding_cannot_use_no_inline_marker(self):
    module = load_module()
    comment_block = """#### F-01 問題

**File**: `src/a.ts`
**Line**: 1

**Comment**:
```
ACTIONABLE_PAYLOAD
```
"""
    for action in ("auto-fix", "ask-user"):
      source = minimal_report().replace(
        "| F-01 | 問題 | Should Fix | auto-fix | 修法明確 |",
        f"| F-01 | 問題 | Should Fix | {action} |",
      ).replace(
        "action=auto-fix",
        f"action={action} inline=none",
      ).replace(comment_block, "")
      with self.subTest(action=action):
        with self.assertRaisesRegex(ValueError, "source report contract mismatch"):
          module.project_report(source, "pr-1-review.audit.md", require_schema=True)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_rejects_finding_row_missing_all_bound_fields_or_duplicate_ordinal(self):
    missing = minimal_report().replace(
      "| F-01 | 問題 | Should Fix | auto-fix | 修法明確 |",
      "| F-01 | 問題 | Should Fix | |",
    ).replace(
      "F-01 finding_uid: 0123456789abcdef0123 action=auto-fix\n",
      "",
    ).replace(
      "#### F-01 問題\n\n**File**: `src/a.ts`\n**Line**: 1\n\n**Comment**:\n```\nACTIONABLE_PAYLOAD\n```\n",
      "",
    )
    duplicate = minimal_report().replace(
      "| F-01 | 問題 | Should Fix | auto-fix | 修法明確 |",
      "| F-01 | 問題 | Should Fix | auto-fix | 修法明確 |\n| F-01 | 重複 | Should Fix | auto-fix |",
    )
    for source in (missing, duplicate):
      with self.subTest(source=source):
        module = load_module()
        with self.assertRaisesRegex(ValueError, "source report contract mismatch"):
          module.project_report(source, "pr-1-review.audit.md", require_schema=True)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_projection_preserves_html_and_thematic_break_boundaries(self):
    module = load_module()
    source = minimal_report().replace(
      "**Formal spec traceability (2.65)**: SKIPPED\n\n## 發現總覽",
      "**Formal spec traceability (2.65)**: SKIPPED\n\n---\n\n## 發現總覽",
    ) + "\n## 本輪限制\n\n<details>\n<summary>補充</summary>\n\n內容\n</details>\n"
    main = module.project_report(source, "pr-1-review.audit.md")
    tokens = MarkdownIt("commonmark").parse(main)
    headings = [tokens[index + 1].content for index, token in enumerate(tokens) if token.type == "heading_open"]
    self.assertIn("Inline Comments per Finding", headings)
    self.assertIn("hr", [token.type for token in tokens])

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_unmatched_backticks_inside_html_are_not_markdown_fences(self):
    module = load_module()
    for html in ("<pre>\n```\nliteral\n</pre>", "<!--\n```\nliteral\n-->"):
      with self.subTest(html=html):
        source = minimal_report() + f"\n## 本輪限制\n\n{html}\n"
        main = module.project_report(source, "pr-1-review.audit.md")
        self.assertIn(html, main)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_projection_preserves_multiline_html_terminator(self):
    module = load_module()
    source = minimal_report() + "\n## 本輪限制\n\n<div>\nraw html content\n\n### Limitation tail\n"
    main = module.project_report(source, "pr-1-review.audit.md")
    tokens = MarkdownIt("commonmark").parse(main)
    headings = [tokens[index + 1].content for index, token in enumerate(tokens) if token.type == "heading_open"]
    self.assertIn("Inline Comments per Finding", headings)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_invalid_fence_info_string_keeps_paragraph_boundaries(self):
    module = load_module()
    source = minimal_report() + "\n## 本輪限制\n\nparagraph one\n\n```foo`bar\n\nparagraph two\n"
    main = module.project_report(source, "pr-1-review.audit.md")
    tokens = MarkdownIt("commonmark").parse(main)
    paragraphs = [
      tokens[index + 1].content
      for index, token in enumerate(tokens)
      if token.type == "paragraph_open" and index + 1 < len(tokens) and tokens[index + 1].type == "inline"
    ]
    self.assertIn("paragraph one", paragraphs)
    self.assertIn("```foo`bar", paragraphs)
    self.assertIn("paragraph two", paragraphs)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_html_block_cannot_supply_comment_payload(self):
    module = load_module()
    comment = "**Comment**:\n```\nACTIONABLE_PAYLOAD\n```"
    source = minimal_report().replace(comment, f"<pre>\n{comment}\n</pre>")
    with self.assertRaisesRegex(ValueError, "source report contract mismatch"):
      module.project_report(source, "pr-1-review.audit.md", require_schema=True)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_incomplete_custom_tag_cannot_hide_raw_h2(self):
    module = load_module()
    tags = (
      "<broken attr",
      "<broken attr=>",
      "<broken =x>",
      "<broken \"x\">",
      "<broken / x>",
    )
    for tag in tags:
      source = minimal_report() + f"\n## 本輪限制\n\n{tag}\n## CC raw evidence\nRAW_PRIVATE_EVIDENCE\n"
      with self.subTest(tag=tag):
        try:
          main = module.project_report(source, "pr-1-review.audit.md", require_schema=True)
        except ValueError:
          continue
        self.assertNotIn("RAW_PRIVATE_EVIDENCE", main)
        self.assertNotIn("## CC raw evidence", main)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_unclosed_html_cannot_hide_raw_h2_in_kept_section(self):
    module = load_module()
    for opening in ("<div>", "<pre>"):
      source = minimal_report() + f"\n## 本輪限制\n\n{opening}\n## CC 原始 findings\nRAW_PRIVATE_EVIDENCE\n"
      with self.subTest(opening=opening):
        with self.assertRaisesRegex(ValueError, "source report contract mismatch"):
          module.project_report(source, "pr-1-review.audit.md", require_schema=True)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_html_block_cannot_hide_atx_or_setext_h2_variants(self):
    module = load_module()
    hidden_headings = (
      "##\nRAW_PRIVATE_EVIDENCE",
      "CC 原始 findings\n---\nRAW_PRIVATE_EVIDENCE",
      "<span>CC 原始 findings</span>\n---\nRAW_PRIVATE_EVIDENCE",
    )
    for opening in ("<div>", "<pre>"):
      for hidden in hidden_headings:
        source = minimal_report() + f"\n## 本輪限制\n\n{opening}\n{hidden}\n"
        with self.subTest(opening=opening, hidden=hidden):
          with self.assertRaisesRegex(ValueError, "source report contract mismatch"):
            module.project_report(source, "pr-1-review.audit.md", require_schema=True)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_h2_allowlist_rejects_arbitrary_suffix(self):
    module = load_module()
    source = minimal_report() + "\n## 本輪限制 - CC raw evidence\n\nRAW_PRIVATE_EVIDENCE\n"
    main = module.project_report(source, "pr-1-review.audit.md", require_schema=True)
    self.assertNotIn("RAW_PRIVATE_EVIDENCE", main)
    self.assertNotIn("本輪限制 - CC raw evidence", main)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_nested_h2_does_not_create_kept_top_level_section(self):
    module = load_module()
    variants = (
      minimal_report() + "\n## 其他區段\n\n> ## 本輪限制\n> RAW_PRIVATE_EVIDENCE\n",
      minimal_report() + "\n## 其他區段\n\n- item\n\n  ## 本輪限制\n  RAW_PRIVATE_EVIDENCE\n",
    )
    for source in variants:
      with self.subTest(source=source):
        main = module.project_report(source, "pr-1-review.audit.md", require_schema=True)
        self.assertNotIn("RAW_PRIVATE_EVIDENCE", main)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_duplicate_finding_block_identity_is_rejected(self):
    module = load_module()
    second_block = "\n\n#### {heading} 第二個位置\n\n**File**: `src/b.ts`\n**Line**: 2\n\n**Comment**:\n```\nSECOND_PAYLOAD\n```"
    unsuffixed = minimal_report().replace(
      "```\nACTIONABLE_PAYLOAD\n```",
      "```\nACTIONABLE_PAYLOAD\n```" + second_block.format(heading="F-01"),
    )
    duplicate_suffix = minimal_report().replace("#### F-01 問題", "#### F-01a 問題").replace(
      "```\nACTIONABLE_PAYLOAD\n```",
      "```\nACTIONABLE_PAYLOAD\n```" + second_block.format(heading="F-01a"),
    )
    for source in (unsuffixed, duplicate_suffix):
      with self.subTest(source=source):
        with self.assertRaisesRegex(ValueError, "source report contract mismatch"):
          module.project_report(source, "pr-1-review.audit.md", require_schema=True)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_distinct_finding_block_suffixes_are_allowed(self):
    module = load_module()
    source = minimal_report().replace("#### F-01 問題", "#### F-01a 問題").replace(
      "```\nACTIONABLE_PAYLOAD\n```",
      "```\nACTIONABLE_PAYLOAD\n```\n\n#### F-01b 第二個位置\n\n**File**: `src/b.ts`\n**Line**: 2\n\n**Comment**:\n```\nSECOND_PAYLOAD\n```",
    )
    main = module.project_report(source, "pr-1-review.audit.md", require_schema=True)
    self.assertIn("ACTIONABLE_PAYLOAD", main)
    self.assertIn("SECOND_PAYLOAD", main)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_noncanonical_summary_headings_and_orphan_noop_comment_are_rejected(self):
    module = load_module()
    variants = (
      minimal_report().replace(
        "### Inline Comments per Finding",
        "#### CC 原始 findings\n\nRAW_PRIVATE_EVIDENCE\n\n### Inline Comments per Finding",
      ),
      minimal_report().replace(
        "### Inline Comments per Finding",
        "##### CC 原始 findings\n\nRAW_PRIVATE_EVIDENCE\n\n### Inline Comments per Finding",
      ),
      minimal_report().replace(
        "### Inline Comments per Finding",
        "**Comment**:\n```\nORPHAN_NOOP_PAYLOAD\n```\n\n### Inline Comments per Finding",
      ),
    )
    for source in variants:
      with self.subTest(source=source):
        with self.assertRaisesRegex(ValueError, "source report contract mismatch"):
          module.project_report(source, "pr-1-review.audit.md", require_schema=True)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_arbitrary_preamble_or_summary_content_is_rejected(self):
    module = load_module()
    variants = (
      minimal_report().replace("## 發現總覽", "RAW_PRIVATE_EVIDENCE\n\n## 發現總覽"),
      minimal_report().replace("## 發現總覽", "> ## Raw evidence\n> RAW_PRIVATE_EVIDENCE\n\n## 發現總覽"),
      minimal_report().replace("## 發現總覽", "###### Raw evidence\n\nRAW_PRIVATE_EVIDENCE\n\n## 發現總覽"),
      minimal_report().replace("### Inline Comments per Finding", "RAW_PRIVATE_EVIDENCE\n\n### Inline Comments per Finding"),
      minimal_report().replace("### Inline Comments per Finding", "> ## Raw evidence\n> RAW_PRIVATE_EVIDENCE\n\n### Inline Comments per Finding"),
      minimal_report().replace("### Inline Comments per Finding", "###### Raw evidence\n\nRAW_PRIVATE_EVIDENCE\n\n### Inline Comments per Finding"),
    )
    for source in variants:
      with self.subTest(source=source):
        with self.assertRaisesRegex(ValueError, "source report contract mismatch"):
          module.project_report(source, "pr-1-review.audit.md", require_schema=True)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_nested_raw_h3_in_preamble_or_summary_is_rejected(self):
    module = load_module()
    variants = (
      minimal_report().replace(
        "## 發現總覽",
        "> ### CC 原始 findings\n> RAW_PRIVATE_EVIDENCE\n\n## 發現總覽",
      ),
      minimal_report().replace(
        "## 發現總覽",
        "- item\n\n  ### CC 原始 findings\n  RAW_PRIVATE_EVIDENCE\n\n## 發現總覽",
      ),
      minimal_report().replace(
        "### Inline Comments per Finding",
        "> ### CC 原始 findings\n> RAW_PRIVATE_EVIDENCE\n\n### Inline Comments per Finding",
      ),
      minimal_report().replace(
        "### Inline Comments per Finding",
        "- item\n\n  ### CC 原始 findings\n  RAW_PRIVATE_EVIDENCE\n\n### Inline Comments per Finding",
      ),
    )
    for source in variants:
      with self.subTest(source=source):
        with self.assertRaisesRegex(ValueError, "source report contract mismatch"):
          module.project_report(source, "pr-1-review.audit.md", require_schema=True)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_raw_h3_in_preamble_is_rejected(self):
    module = load_module()
    source = minimal_report().replace(
      "## 發現總覽",
      "### CC 原始 findings\n\nRAW_PRIVATE_EVIDENCE\n\n## 發現總覽",
    )
    with self.assertRaisesRegex(ValueError, "source report contract mismatch"):
      module.project_report(source, "pr-1-review.audit.md", require_schema=True)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_raw_h3_before_inline_comments_is_rejected(self):
    module = load_module()
    source = minimal_report().replace(
      "### Inline Comments per Finding",
      "### CC 原始 findings\n\nRAW_PRIVATE_EVIDENCE\n\n### Inline Comments per Finding",
    )
    with self.assertRaisesRegex(ValueError, "source report contract mismatch"):
      module.project_report(source, "pr-1-review.audit.md", require_schema=True)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_finding_priority_order_is_monotonic(self):
    module = load_module()
    source = minimal_report().replace(
      "| F-01 | 問題 | Should Fix | auto-fix | 修法明確 |",
      "| F-01 | 第一條 | Nice to Have | auto-fix | 第一條理由 |\n| F-02 | 第二條 | Must Fix | auto-fix | 第二條理由 |",
    ).replace(
      "F-01 finding_uid: 0123456789abcdef0123 action=auto-fix",
      "F-01 finding_uid: 0123456789abcdef0123 action=auto-fix\nF-02 finding_uid: fedcba9876543210fedc action=auto-fix",
    ).replace(
      "```\nACTIONABLE_PAYLOAD\n```",
      "```\nACTIONABLE_PAYLOAD\n```\n\n#### F-02 第二條\n\n**File**: `src/b.ts`\n**Line**: 2\n\n**Comment**:\n```\nSECOND_PAYLOAD\n```",
    )
    with self.assertRaisesRegex(ValueError, "source report contract mismatch"):
      module.project_report(source, "pr-1-review.audit.md", require_schema=True)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_finding_blocks_follow_inventory_order(self):
    module = load_module()
    source = """# PR #1 Code Review

**Report projection schema**: 1
**覆蓋 (ENH-A)**: missed 0
**Formal spec traceability (2.65)**: SKIPPED

## 發現總覽

| # | 問題 | 最終建議 | Action | Action 理由 |
|---|---|---|---|---|
| F-01 | 第一條 | Should Fix | auto-fix | 第一條理由 |
| F-02 | 第二條 | Should Fix | auto-fix | 第二條理由 |

F-01 finding_uid: 0123456789abcdef0123 action=auto-fix
F-02 finding_uid: fedcba9876543210fedc action=auto-fix

### Inline Comments per Finding

#### F-02 第二條

**File**: `src/b.ts`
**Line**: 2

**Comment**:
```
SECOND_PAYLOAD
```

#### F-01 第一條

**File**: `src/a.ts`
**Line**: 1

**Comment**:
```
FIRST_PAYLOAD
```
"""
    with self.assertRaisesRegex(ValueError, "source report contract mismatch"):
      module.project_report(source, "pr-1-review.audit.md", require_schema=True)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_multi_location_suffixes_are_contiguous(self):
    module = load_module()
    source = minimal_report().replace("#### F-01 問題", "#### F-01a 問題").replace(
      "```\nACTIONABLE_PAYLOAD\n```",
      "```\nACTIONABLE_PAYLOAD\n```\n\n#### F-01c 第三個位置\n\n**File**: `src/c.ts`\n**Line**: 3\n\n**Comment**:\n```\nTHIRD_PAYLOAD\n```",
    )
    with self.assertRaisesRegex(ValueError, "source report contract mismatch"):
      module.project_report(source, "pr-1-review.audit.md", require_schema=True)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_malformed_finding_heading_is_not_merged_into_previous_block(self):
    module = load_module()
    source = minimal_report().replace(
      "```\nACTIONABLE_PAYLOAD\n```",
      "```\nACTIONABLE_PAYLOAD\n```\n\n#### F-O2 orphan finding\n\n**File**: `src/orphan.ts`\n**Line**: 2",
    )
    with self.assertRaisesRegex(ValueError, "source report contract mismatch"):
      module.project_report(source, "pr-1-review.audit.md", require_schema=True)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_commonmark_indented_finding_heading_is_recognized(self):
    module = load_module()
    for spaces in (1, 2, 3):
      source = minimal_report().replace("#### F-01 問題", f"{' ' * spaces}#### F-01 問題")
      with self.subTest(spaces=spaces):
        main = module.project_report(source, "pr-1-review.audit.md", require_schema=True)
        self.assertIn("ACTIONABLE_PAYLOAD", main)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_unbound_tail_after_finding_block_is_rejected(self):
    module = load_module()
    tails = (
      " #### F-O2 orphan",
      "  #### F-O2 orphan",
      "   #### F-O2 orphan",
      "##### F-02 orphan",
      "####F-02 orphan",
      "UNBOUND_TRAILER",
    )
    for tail in tails:
      source = minimal_report().rstrip() + f"\n\n{tail}\n\n**File**: `src/orphan.ts`\n"
      with self.subTest(tail=tail):
        with self.assertRaisesRegex(ValueError, "source report contract mismatch"):
          module.project_report(source, "pr-1-review.audit.md", require_schema=True)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_each_finding_block_requires_one_nonempty_comment(self):
    module = load_module()
    empty = minimal_report().replace("ACTIONABLE_PAYLOAD", "")
    missing_subblock = minimal_report().replace(
      "#### F-01 問題",
      "#### F-01a 問題",
    ).replace(
      "```\nACTIONABLE_PAYLOAD\n```",
      "```\nACTIONABLE_PAYLOAD\n```\n\n#### F-01b 第二個位置\n\n**File**: `src/b.ts`\n**Line**: 2",
    )
    for source in (empty, missing_subblock):
      with self.subTest(source=source):
        with self.assertRaisesRegex(ValueError, "source report contract mismatch"):
          module.project_report(source, "pr-1-review.audit.md", require_schema=True)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_finding_block_requires_canonical_location_and_comment_label(self):
    variants = (
      minimal_report().replace("**File**: `src/a.ts`\n", ""),
      minimal_report().replace("**Line**: 1\n", ""),
      minimal_report().replace("**Comment**:\n", "**Comment**: trailing text\n"),
      minimal_report().replace("**File**: `src/a.ts`", "**File**:   "),
      minimal_report().replace("**Line**: 1", "**Line**: 10-2"),
      minimal_report().replace("**File**: `src/a.ts`\n**Line**: 1", "**Line**: 1\n**File**: `src/a.ts`"),
      minimal_report().replace("**File**: `src/a.ts`", "ORPHAN_PREFIX\n\n**File**: `src/a.ts`"),
    )
    for source in variants:
      with self.subTest(source=source):
        module = load_module()
        with self.assertRaisesRegex(ValueError, "source report contract mismatch"):
          module.project_report(source, "pr-1-review.audit.md", require_schema=True)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_failed_anchor_line_sentinel_is_allowed(self):
    module = load_module()
    source = minimal_report().replace(
      "**Line**: 1",
      "**Line**: 需人工確認（anchor 未在綁定來源中比中或證據 binding 失效）",
    )
    main = module.project_report(source, "pr-1-review.audit.md", require_schema=True)
    self.assertIn("需人工確認", main)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_finding_block_rejects_opaque_or_noncanonical_content(self):
    variants = (
      minimal_report().replace(
        "**File**: `src/a.ts`",
        "<broken attr=>\nRAW_PRIVATE_EVIDENCE\n\n**File**: `src/a.ts`",
      ),
      minimal_report().replace(
        "**File**: `src/a.ts`",
        "    RAW_PRIVATE_EVIDENCE\n\n**File**: `src/a.ts`",
      ),
      minimal_report().replace("#### F-01 問題", "#### F-01-extra 問題"),
    )
    for source in variants:
      with self.subTest(source=source):
        module = load_module()
        with self.assertRaisesRegex(ValueError, "source report contract mismatch"):
          module.project_report(source, "pr-1-review.audit.md", require_schema=True)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_react_doctor_new_findings_are_preserved(self):
    module = load_module()
    source = minimal_report().replace(
      "**React-doctor (2.97)**: 未引入新問題",
      "**React-doctor (2.97)**: 新引入 1 條",
    ) + "\n## React-doctor 機械掃描\n\n- rule-id · `src/App.tsx:7` · 改用穩定 key · Should Fix\n"
    main = module.project_report(source, "pr-1-review.audit.md", require_schema=True)
    self.assertIn("## React-doctor 機械掃描", main)
    self.assertIn("rule-id · `src/App.tsx:7` · 改用穩定 key · Should Fix", main)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_non_finding_comment_label_does_not_enter_payload_validation(self):
    module = load_module()
    source = minimal_report() + "\n## 本輪限制（沒做的部分）\n\n**Comment**: 欄位格式未驗證。\n"
    main = module.project_report(source, "pr-1-review.audit.md", require_schema=True)
    self.assertIn("**Comment**: 欄位格式未驗證。", main)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_zero_finding_report_projects_successfully(self):
    module = load_module()
    source = """# PR #1 Code Review

**Report projection schema**: 1
**Review input basis**: input_binding: verified
**覆蓋 (ENH-A)**: missed 0
**Formal spec traceability (2.65)**: SKIPPED

## 發現總覽

| # | 問題 | 最終建議 | Action | Action 理由 |
|---|---|---|---|---|

### Inline Comments per Finding
"""
    main = module.project_report(source, "pr-1-review.audit.md", require_schema=True)
    self.assertIn("## 發現總覽", main)
    self.assertNotIn("finding_uid:", main)
    self.assertNotIn("**Comment**:", main)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_publish_rejects_project_or_arbitrary_paths(self):
    module = load_module()
    for parent_name in ("project", "arbitrary"):
      with self.subTest(parent_name=parent_name):
        with tempfile.TemporaryDirectory() as root:
          parent = Path(root, parent_name)
          parent.mkdir()
          draft, audit, main = report_paths(parent)
          draft.write_text(minimal_report())
          with self.assertRaises(ValueError):
            module.publish_report_pair(draft, audit, main)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_publish_accepts_canonical_root_and_names(self):
    module = load_module()
    with tempfile.TemporaryDirectory(dir=REPORT_ROOT) as root:
      draft, audit, main = report_paths(root)
      draft.write_text(minimal_report())
      module.publish_report_pair(draft, audit, main)
      self.assertFalse(draft.exists())
      self.assertTrue(audit.exists())
      self.assertTrue(main.exists())

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_publish_accepts_equivalent_relative_and_absolute_paths(self):
    module = load_module()
    with tempfile.TemporaryDirectory(dir=REPORT_ROOT) as root:
      absolute_draft, absolute_audit, absolute_main = report_paths(root)
      relative_root = Path(os.path.relpath(root, Path.cwd()))
      draft = absolute_draft
      audit = relative_root / absolute_audit.name
      main = absolute_main
      draft.write_text(minimal_report())
      module.publish_report_pair(draft, audit, main)
      self.assertTrue(absolute_audit.exists())
      self.assertTrue(absolute_main.exists())

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_publish_rejects_mismatched_pr_numbers_and_names(self):
    module = load_module()
    cases = ((2, 1, 1), (1, 2, 1), (1, 1, 2))
    for draft_number, audit_number, main_number in cases:
      with self.subTest(
        draft_number=draft_number,
        audit_number=audit_number,
        main_number=main_number,
      ):
        with tempfile.TemporaryDirectory(dir=REPORT_ROOT) as root:
          draft = Path(root, f"pr-{draft_number}-review.audit.draft.md")
          audit = Path(root, f"pr-{audit_number}-review.audit.md")
          main = Path(root, f"pr-{main_number}-review.md")
          draft.write_text(minimal_report())
          with self.assertRaises(ValueError):
            module.publish_report_pair(draft, audit, main)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_invalid_source_does_not_overwrite_existing_main_report(self):
    with tempfile.TemporaryDirectory(dir=REPORT_ROOT) as root:
      draft = Path(root, "pr-1-review.audit.draft.md")
      audit = Path(root, "pr-1-review.audit.md")
      main = Path(root, "pr-1-review.md")
      draft.write_text("# invalid\n\n```text\nunterminated\n")
      audit.write_text("existing-audit")
      main.write_text("existing-main")
      result = subprocess.run(
        [sys.executable, str(MODULE_PATH), str(draft), str(audit), str(main)],
        capture_output=True,
        text=True,
      )
      self.assertNotEqual(0, result.returncode)
      self.assertEqual("existing-audit", audit.read_text())
      self.assertEqual("existing-main", main.read_text())

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_draft_cannot_supply_generation_binding(self):
    module = load_module()
    with tempfile.TemporaryDirectory(dir=REPORT_ROOT) as root:
      draft = Path(root, "pr-1-review.audit.draft.md")
      audit = Path(root, "pr-1-review.audit.md")
      main = Path(root, "pr-1-review.md")
      draft.write_text(minimal_report() + "\n## 本輪限制\n\n**Report generation**: 2026-01-01T00:00:00Z\n")
      with self.assertRaisesRegex(ValueError, "source report contract mismatch"):
        module.publish_report_pair(draft, audit, main)
      self.assertFalse(audit.exists())
      self.assertFalse(main.exists())

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_published_pair_has_matching_generation_binding(self):
    module = load_module()
    with tempfile.TemporaryDirectory(dir=REPORT_ROOT) as root:
      draft = Path(root, "pr-1-review.audit.draft.md")
      audit = Path(root, "pr-1-review.audit.md")
      main = Path(root, "pr-1-review.md")
      draft.write_text(minimal_report())
      module.publish_report_pair(draft, audit, main)
      pattern = re.compile(r"(?m)^\*\*Report generation\*\*: (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)$")
      audit_generation = pattern.findall(audit.read_text())
      main_generation = pattern.findall(main.read_text())
      self.assertEqual(1, len(audit_generation))
      self.assertEqual(audit_generation, main_generation)
      self.assertNotIn("sha256", audit.read_text().split("## ", 1)[0] + main.read_text().split("## ", 1)[0])

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_concurrent_publish_keeps_audit_and_main_on_same_source(self):
    with tempfile.TemporaryDirectory(dir=REPORT_ROOT) as root:
      draft, audit, main = report_paths(root)
      draft.write_text(minimal_report().replace("ACTIONABLE_PAYLOAD", "PAYLOAD"))
      processes = [
        subprocess.Popen(
          [sys.executable, str(MODULE_PATH), str(draft), str(audit), str(main)],
          stdout=subprocess.PIPE,
          stderr=subprocess.PIPE,
          text=True,
        )
        for _ in range(2)
      ]
      results = [process.communicate() + (process.returncode,) for process in processes]
      self.assertEqual([0, 1], sorted(returncode for _, _, returncode in results), results)
      self.assertIn("PAYLOAD", audit.read_text())
      self.assertIn("PAYLOAD", main.read_text())

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_publish_rejects_draft_aliasing_lock_path(self):
    for alias_kind in ("symlink", "hardlink"):
      with self.subTest(alias_kind=alias_kind):
        with tempfile.TemporaryDirectory(dir=REPORT_ROOT) as root:
          draft, audit, main = report_paths(root)
          lock = main.with_name(f".{main.name}.lock")
          lock.write_text(minimal_report())
          if alias_kind == "symlink":
            draft.symlink_to(lock)
          else:
            draft.hardlink_to(lock)
          result = subprocess.run(
            [sys.executable, str(MODULE_PATH), str(draft), str(audit), str(main)],
            capture_output=True,
            text=True,
          )
          self.assertNotEqual(0, result.returncode)
          self.assertFalse(audit.exists())
          self.assertFalse(main.exists())

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_publish_rejects_symlink_or_hardlink_interrupted_claim(self):
    module = load_module()
    for alias_kind in ("symlink", "hardlink", "directory-symlink"):
      with self.subTest(alias_kind=alias_kind):
        with tempfile.TemporaryDirectory(dir=REPORT_ROOT) as root:
          with tempfile.TemporaryDirectory() as outside_root:
            draft, audit, main = report_paths(root)
            outside = Path(outside_root, "outside-report.md")
            outside.write_text(minimal_report())
            claim_directory = Path(tempfile.mkdtemp(
              dir=Path(root),
              prefix=f".{draft.name}.claim.",
            ))
            claimed = claim_directory / "draft.md"
            if alias_kind == "symlink":
              claimed.symlink_to(outside)
            elif alias_kind == "hardlink":
              claimed.hardlink_to(outside)
            else:
              claim_directory.rmdir()
              outside_claim_directory = Path(outside_root, "claim")
              outside_claim_directory.mkdir()
              (outside_claim_directory / "draft.md").write_text(minimal_report())
              claim_directory.symlink_to(outside_claim_directory, target_is_directory=True)
            with self.assertRaises(ValueError):
              module.publish_report_pair(draft, audit, main)
            self.assertFalse(audit.exists())
            self.assertFalse(main.exists())
            self.assertEqual(minimal_report(), outside.read_text())

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_publish_does_not_delete_replacement_at_original_draft_path(self):
    module = load_module()
    with tempfile.TemporaryDirectory(dir=REPORT_ROOT) as root:
      draft = Path(root, "pr-1-review.audit.draft.md")
      audit = Path(root, "pr-1-review.audit.md")
      main = Path(root, "pr-1-review.md")
      draft.write_text(minimal_report())
      original_write = module.write_main_report

      def write_and_replace_draft(path, content, before_replace=None):
        original_write(path, content, before_replace=before_replace)
        if path == main:
          draft.write_text("replacement-draft")

      with mock.patch.object(module, "write_main_report", side_effect=write_and_replace_draft):
        module.publish_report_pair(draft, audit, main)
      self.assertEqual("replacement-draft", draft.read_text())

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_publish_rejects_same_or_aliased_audit_and_main_paths(self):
    with tempfile.TemporaryDirectory(dir=REPORT_ROOT) as root:
      draft = Path(root, "pr-1-review.audit.draft.md")
      draft.write_text(minimal_report())
      audit = Path(root, "pr-1-review.audit.md")
      audit.write_text("existing-audit")
      for main in (audit, Path(root, "other-main.md")):
        with self.subTest(main=main):
          result = subprocess.run(
            [sys.executable, str(MODULE_PATH), str(draft), str(audit), str(main)],
            capture_output=True,
            text=True,
          )
          self.assertNotEqual(0, result.returncode)
      self.assertEqual("existing-audit", audit.read_text())
    for alias_kind in ("symlink", "hardlink"):
      with self.subTest(alias_kind=alias_kind):
        with tempfile.TemporaryDirectory(dir=REPORT_ROOT) as root:
          draft, audit, main = report_paths(root)
          draft.write_text(minimal_report())
          audit.write_text("existing-audit")
          if alias_kind == "symlink":
            main.symlink_to(audit)
          else:
            main.hardlink_to(audit)
          result = subprocess.run(
            [sys.executable, str(MODULE_PATH), str(draft), str(audit), str(main)],
            capture_output=True,
            text=True,
          )
          self.assertNotEqual(0, result.returncode)
          self.assertEqual("existing-audit", audit.read_text())

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_cli_preserves_crlf_inside_comment_payload(self):
    with tempfile.TemporaryDirectory(dir=REPORT_ROOT) as root:
      draft = Path(root, "pr-1-review.audit.draft.md")
      audit = Path(root, "pr-1-review.audit.md")
      main = Path(root, "pr-1-review.md")
      draft.write_bytes(minimal_report().replace("\n", "\r\n").encode())
      result = subprocess.run(
        [sys.executable, str(MODULE_PATH), str(draft), str(audit), str(main)],
        capture_output=True,
        text=True,
      )
      self.assertEqual(0, result.returncode, result.stderr)
      self.assertIn(b"```\r\nACTIONABLE_PAYLOAD\r\n```", audit.read_bytes())
      self.assertIn(b"```\r\nACTIONABLE_PAYLOAD\r\n```", main.read_bytes())

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_atomic_write_does_not_follow_predictable_temp_symlink(self):
    module = load_module()
    with tempfile.TemporaryDirectory() as root:
      main = Path(root, "pr-1-review.md")
      victim = Path(root, "victim.txt")
      predictable_temp = Path(root, ".pr-1-review.md.tmp")
      victim.write_text("victim-original")
      predictable_temp.symlink_to(victim)
      module.write_main_report(main, "projected-main")
      self.assertEqual("victim-original", victim.read_text())
      self.assertEqual("projected-main", main.read_text())
      self.assertFalse(main.is_symlink())

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_atomic_write_failure_preserves_existing_main_report(self):
    module = load_module()
    with tempfile.TemporaryDirectory(dir=REPORT_ROOT) as root:
      draft = Path(root, "pr-1-review.audit.draft.md")
      audit = Path(root, "pr-1-review.audit.md")
      main = Path(root, "pr-1-review.md")
      draft.write_text(minimal_report())
      audit.write_text("existing-audit")
      main.write_text("existing-main")
      original_fdopen = module.os.fdopen

      class FailingTempFile:
        def __init__(self, descriptor, *args, **kwargs):
          self.file = original_fdopen(descriptor, *args, **kwargs)

        def __enter__(self):
          return self

        def __exit__(self, *args):
          self.file.close()

        def write(self, data):
          self.file.write("PARTIAL")
          self.file.flush()
          raise OSError("injected write failure")

      def fail_temp_only(descriptor, mode, *args, **kwargs):
        if mode == "a":
          return original_fdopen(descriptor, mode, *args, **kwargs)
        return FailingTempFile(descriptor, mode, *args, **kwargs)

      with mock.patch("sys.argv", [str(MODULE_PATH), str(draft), str(audit), str(main)]):
        with mock.patch.object(module.os, "fdopen", side_effect=fail_temp_only):
          with self.assertRaisesRegex(OSError, "injected write failure"):
            module.main()
      self.assertEqual("existing-audit", audit.read_text())
      self.assertEqual("existing-main", main.read_text())
      self.assertEqual([], list(Path(root).glob(".*.tmp")))

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_interrupted_publish_recovers_claim_on_next_run(self):
    module = load_module()
    with tempfile.TemporaryDirectory(dir=REPORT_ROOT) as root:
      draft = Path(root, "pr-1-review.audit.draft.md")
      audit = Path(root, "pr-1-review.audit.md")
      main = Path(root, "pr-1-review.md")
      draft.write_text(minimal_report())
      claim_directory, claimed = module.claim_draft(draft)
      self.assertFalse(draft.exists())
      module.recover_claimed_draft(draft)
      self.assertTrue(draft.exists())
      self.assertFalse(claimed.exists())
      self.assertFalse(claim_directory.exists())
      module.publish_report_pair(draft, audit, main)
      self.assertTrue(audit.exists())
      self.assertTrue(main.exists())

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_pair_rollback_preserves_existing_audit_mode_and_content(self):
    module = load_module()
    with tempfile.TemporaryDirectory(dir=REPORT_ROOT) as root:
      draft = Path(root, "pr-1-review.audit.draft.md")
      audit = Path(root, "pr-1-review.audit.md")
      main = Path(root, "pr-1-review.md")
      draft.write_text(minimal_report())
      audit.write_text("existing-audit")
      audit.chmod(0o640)
      main.write_text("existing-main")
      original_write = module.write_main_report

      def fail_main(path, content, before_replace=None):
        if path == main:
          raise OSError("injected main publish failure")
        return original_write(path, content, before_replace=before_replace)

      with mock.patch.object(module, "write_main_report", side_effect=fail_main):
        with self.assertRaisesRegex(OSError, "injected main publish failure"):
          module.publish_report_pair(draft, audit, main)
      self.assertEqual("existing-audit", audit.read_text())
      self.assertEqual(0o640, audit.stat().st_mode & 0o777)
      self.assertEqual("existing-main", main.read_text())
      self.assertTrue(draft.exists())

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_post_projection_validation_rejects_lost_decision_content(self):
    for lost in (
      "0123456789abcdef0123",
      "ACTIONABLE_PAYLOAD",
      "Should Fix",
      "**Review input basis**: input_binding: verified",
      "**覆蓋 (ENH-A)**: missed 0",
      "**React-doctor (2.97)**: 未引入新問題",
    ):
      with self.subTest(lost=lost):
        module = load_module()
        original = module.remove_external_blank_lines
        module.remove_external_blank_lines = lambda text: original(text).replace(lost, "")
        with self.assertRaisesRegex(ValueError, "projection integrity mismatch"):
          module.project_report(minimal_report(), "pr-1-review.audit.md")

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_keeps_decision_content_and_links_each_finding_uid_to_audit(self):
    module = load_module()
    source = """# PR #42 Code Review 比較報告 · SHA 12345678

**審查工具**: CC + Codex
**Reviewer models**: orchestrator=claude-fable-5
**覆蓋 (ENH-A)**: |F|=2 → missed 0
**定位 (ENH-B)**: anchored exact 2 / ambiguous 0 / FAILED 0
**Formal spec traceability (2.65)**: DISPATCHED（clauses 1 / findings 1）

## Spec 依據

- C4 receipt 完整。

## 變更概要

這段不進主報告。

## 發現總覽

| # | 問題 | 最終建議 | Action | Action 理由 |
|---|---|---|---|---|
| 1 | 第一條 | Must Fix | `auto-fix` | 修法明確 |
| 2 | 第二條 | 參考用 | `no-op` | 非本 PR 缺陷 |

F-01 `0123456789abcdef0123`
F-02 `fedcba9876543210fedc`

### Inline Comments per Finding

#### #1 第一條

**File**: `src/a.ts`
**Line**: 10

**Comment**:
```
第一條完整留言。
```

#### #2 第二條

**File**: `src/b.ts`
**Line**: 20

**Comment**:
```
不是 PR 缺陷，第二條完整留言。
```

### CC 原始 findings

RAW_OPUS_EVIDENCE 不進主報告。

### Codex 原始 findings

RAW_CODEX_EVIDENCE 不進主報告。

### Codex 對 CC 的複查結果

RAW_CROSS_VERIFICATION 不進主報告。

## Action Items

不進主報告。

## 本輪限制（沒做的部分）

- CI 未驗證。
"""
    main = module.project_report(source, "pr-42-review.audit.md")
    self.assertNotIn("## Spec 依據", main)
    self.assertIn("## 發現總覽", main)
    self.assertIn("第一條完整留言。", main)
    self.assertNotIn("不是 PR 缺陷，第二條完整留言。", main)
    self.assertIn("## 本輪限制（沒做的部分）", main)
    self.assertNotIn("## 變更概要", main)
    self.assertNotIn("RAW_OPUS_EVIDENCE", main)
    self.assertNotIn("RAW_CODEX_EVIDENCE", main)
    self.assertNotIn("RAW_CROSS_VERIFICATION", main)
    self.assertNotIn("## Action Items", main)
    self.assertIn("[0123456789abcdef0123](pr-42-review.audit.md#發現總覽)", main)
    self.assertIn("[fedcba9876543210fedc](pr-42-review.audit.md#發現總覽)", main)
    self.assertEqual(actionable_comment_payloads(source), comment_payloads(main))
    self.assertEqual(state_lines(source), state_lines(main))

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_fenced_structured_uid_block_still_links_to_audit(self):
    module = load_module()
    source = """# PR #9 Code Review

**覆蓋 (ENH-A)**: missed 0
**Formal spec traceability (2.65)**: SKIPPED

## 發現總覽

```text
F-01 0123456789abcdef0123 action=auto-fix
F-02 fedcba9876543210fedc action=no-op
```

### Inline Comments per Finding

#### F-01 問題

**File**: `src/a.ts`
**Line**: 1

**Comment**:
```
ACTIONABLE_PAYLOAD
```
"""
    main = module.project_report(source, "pr-9-review.audit.md")
    self.assertIn("[0123456789abcdef0123](pr-9-review.audit.md#發現總覽)", main)
    self.assertIn("[fedcba9876543210fedc](pr-9-review.audit.md#發現總覽)", main)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_markdown_headings_and_metadata_inside_comment_payload_are_opaque(self):
    module = load_module()
    payload = """留言內的 Markdown 範例：
```json
{"kind":"literal fence with info string"}
## 新標題仍是留言內容
#### #99 不是 finding
**File**: `example.ts`

**Line**: 9

這些空行與標題都必須逐字保留。"""
    source = f"""# PR #8 Code Review

**覆蓋 (ENH-A)**: missed 0
**Formal spec traceability (2.65)**: SKIPPED

## 發現總覽

| # | 問題 | Action |
|---|---|---|
| F-01 | 問題 | auto-fix |

### Inline Comments per Finding

#### F-01 問題

**File**: `src/a.ts`
**Line**: 1

**Comment**:
```
{payload}
```

### CC 原始 findings

RAW_OPUS_EVIDENCE
"""
    main = module.project_report(source, "pr-8-review.audit.md")
    self.assertEqual([payload], comment_payloads(main))
    self.assertNotIn("RAW_OPUS_EVIDENCE", main)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_four_space_indented_fence_is_comment_payload_text(self):
    module = load_module()
    source = minimal_report().replace(
      "ACTIONABLE_PAYLOAD",
      "before literal fence\n    ```\nafter literal fence",
    )
    main = module.project_report(source, "pr-1-review.audit.md")
    self.assertEqual(
      ["before literal fence\n    ```\nafter literal fence"],
      comment_payloads(main),
    )

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_canonical_h3_raw_sections_do_not_leak_after_inline_comments(self):
    module = load_module()
    source = """# PR #7 Code Review

**覆蓋 (ENH-A)**: missed 0
**Formal spec traceability (2.65)**: SKIPPED

## 發現總覽

| # | 問題 | Action |
|---|---|---|
| F-01 | 問題 | auto-fix |

### Inline Comments per Finding

#### F-01 問題

**File**: `src/a.ts`
**Line**: 1

**Comment**:
```
ACTIONABLE_PAYLOAD
```

### CC 原始 findings

RAW_OPUS_EVIDENCE

### Codex 原始 findings

RAW_CODEX_EVIDENCE

### Codex 對 CC 的複查結果

RAW_CROSS_VERIFICATION
"""
    main = module.project_report(source, "pr-7-review.audit.md")
    self.assertIn("ACTIONABLE_PAYLOAD", main)
    self.assertNotIn("RAW_OPUS_EVIDENCE", main)
    self.assertNotIn("RAW_CODEX_EVIDENCE", main)
    self.assertNotIn("RAW_CROSS_VERIFICATION", main)

  @unittest.skipUnless(MODULE_PATH.is_file(), "projection helper not implemented")
  def test_replays_ten_reports_without_losing_state_or_comment_payloads(self):
    module = load_module()
    reports = recent_reports()
    self.assertEqual(10, len(reports))
    ratios = []
    for path in reports:
      source = path.read_text()
      main = module.project_report(source, path.name.replace(".md", ".audit.md"))
      self.assertEqual(actionable_comment_payloads(source), comment_payloads(main), str(path))
      self.assertEqual(state_lines(source), state_lines(main), str(path))
      for uid in expected_finding_uids(source):
        link = f"[{uid}]({path.name.replace('.md', '.audit.md')}#發現總覽)"
        self.assertIn(link, main, str(path))
      ratios.append(len(main.splitlines()) / len(source.splitlines()))
    self.assertLessEqual(statistics.median(ratios), 0.51)


if __name__ == "__main__":
  unittest.main()
