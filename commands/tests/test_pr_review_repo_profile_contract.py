#!/usr/bin/env python3

import os
import re
import unittest
from pathlib import Path


COMMAND_PATH = Path(os.environ.get("PR_REVIEW_COMMAND_PATH", Path.home() / ".claude/commands/pr-review.md"))


class PrReviewRepoProfileContractTest(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    cls.command = COMMAND_PATH.read_text()

  def section(self, start_marker, end_marker):
    start = self.command.index(start_marker)
    end = self.command.index(end_marker, start)
    return self.command[start:end]

  def test_poll_word_splits_rollout_paths_in_bash_and_zsh(self):
    self.assertIn('printf \'%s\\n\' "$ROLLOUTS" | xargs ~/.claude/scripts/poll-liveness.sh poll', self.command)
    self.assertNotIn("${=ROLLOUTS}", self.command)
    self.assertNotRegex(self.command, r"--deadline \d+ \$ROLLOUTS\b")
    self.assertNotIn("ls -S $ROLLOUTS", self.command)

  def test_zsh_companion_plugin_dir_joins_with_slash(self):
    self.assertIn("${CODEX_PLUGIN_DIR%/}/scripts/codex-companion.mjs", self.command)
    self.assertNotIn("${CODEX_PLUGIN_DIR}scripts/", self.command)
    self.assertNotIn("${CODEX_PLUGIN_DIR}schemas/", self.command)
    self.assertIn("ls -d */", self.command)
    self.assertIn("結尾斜線", self.command)

  def test_cwd_persistence_claim_and_codex_launch_use_git_dash_c(self):
    lock = self.section("### 2.5.3", "### 2.5.4")
    self.assertNotIn("不會持久", lock)
    self.assertIn("可能跨 call 殘留", lock)
    self.assertNotRegex(self.command, r'(?m)^cd "\$REVIEW_ROOT" &&')
    self.assertNotIn('`cd "$REVIEW_ROOT" &&` prefix', self.command)
    self.assertIn("git -C \"$REVIEW_ROOT\" merge-base", self.command)
    self.assertRegex(self.command, r"\(cd \"\$REVIEW_ROOT\" && nohup codex review")
    self.assertRegex(self.command, r"\(cd \"\$REVIEW_ROOT\" && env -u CODEX_COMPANION_SESSION_ID")

  def test_github_file_list_is_paginated_in_step2_and_step295(self):
    step2 = self.section("## Step 2: Fetch PR Data", "## Step 2.1")
    inventory = self.section("## Step 2.95", "### Chunking decision")
    for name, block in (("step2", step2), ("inventory", inventory)):
      with self.subTest(block=name):
        self.assertIn("gh api --paginate", block)
        self.assertIn("pulls/<number>/files?per_page=100", block)
        self.assertIn(".[].filename", block)
    self.assertIn("100 檔", step2)
    self.assertNotIn("gh pr view <number> --json files", inventory)

  def test_c4_scans_live_normative_sources_before_skipping(self):
    gate = self.section("## Step 2.65", "## Step 2.7")
    scan = gate.index("### 2.65.1")
    reducer = gate.index("resolve-authority")
    self.assertLess(scan, reducer)
    self.assertIn("git -C \"$REVIEW_ROOT\" ls-files", gate)
    self.assertIn("openspec/specs/**/spec.md", gate)
    self.assertNotIn("openspec/changes/archive/**/spec.md", gate[scan:reducer])
    self.assertIn("MUST|SHALL|NEVER", gate)
    self.assertIn("NORMATIVE_SCAN=", gate)
    self.assertIn("AUTHORED_FILES=$(git -C \"$REVIEW_ROOT\" diff --name-only", gate)
    self.assertIn('[ -z "$AUTHORED_IDS" ]', gate)
    self.assertIn("先跑 2.65.1", gate[reducer:])
    self.assertIn("2.65.1", self.section("**Dispatch checklist", " Review (Multi-Agent Routing)"))

  def test_c4_skipped_reason_has_three_states(self):
    for state in (
      "SKIPPED (no normative source)",
      "SKIPPED (normative sources scanned, none intersect)",
      "SKIPPED (scan not run: <原因>)",
    ):
      with self.subTest(state=state):
        self.assertIn(state, self.section("## Step 2.65", "## Step 2.7"))
        self.assertIn(state, self.section("**Formal spec traceability (2.65)**", "**Quota"))
        self.assertIn(state, self.section("## Spec 依據", "## 變更概要"))

  def test_c4_authority_source_comes_only_from_declared_authority(self):
    gate = self.section("## Step 2.65", "## Step 2.7")
    # 現行 openspec 來源與 archive 別名規則原封不動（未宣告的 repo 照舊）
    self.assertIn("unpromoted `openspec/changes/<name>/specs/**` delta specs are also accepted as authority", gate)
    self.assertIn("`openspec/changes/archive/**` is an alias only", gate)
    # 新來源只經 profile 的 authority 進來，不經 spec_globs / conventions_docs 推導
    self.assertNotIn("spec_globs", gate)
    self.assertNotIn("conventions_docs", gate)
    self.assertIn("pr-review-profile.py", gate)
    self.assertIn(".authority.live", gate)
    self.assertIn(".authority.change", gate)
    # 宣告位置以外整份不算來源
    self.assertIn("outside the declared authority locations", gate)
    self.assertIn("supplies no clause", gate)
    self.assertIn("matches neither list", gate)

  def test_c4_scan_reads_declared_globs_and_falls_back_to_openspec(self):
    gate = self.section("## Step 2.65", "## Step 2.7")
    scan = gate[gate.index("### 2.65.1"):gate.index("resolve-authority")]
    self.assertIn("jq -r '.authority.live[]?'", scan)
    self.assertIn("jq -r '.authority.change[]?'", scan)
    # git pathspec 的 * 預設跨 /，核驗器只認單層 *；掃描端必須與核驗器一致
    self.assertIn(':(glob)', scan)
    self.assertIn("segment count", scan)
    declared = scan.index(".authority.live")
    fallback = scan.index("openspec/specs/**/spec.md")
    self.assertLess(declared, fallback)
    self.assertIn("openspec/changes/*/specs/**/spec.md", scan)
    # 2026-10-08 使用者裁決：profile 讀不到時照「沒宣告」處理，掃描退回 openspec，與核驗器一致
    self.assertNotIn("repo profile unreadable", scan)
    self.assertIn("an unreadable profile counts as no declaration", scan)

  def test_c4_scan_change_files_only_when_pr_touched_them(self):
    gate = self.section("## Step 2.65", "## Step 2.7")
    scan = gate[gate.index("### 2.65.1"):gate.index("resolve-authority")]
    self.assertIn("CHANGE_FILES", scan)
    self.assertIn('command grep -qxF -- "$f"', scan)
    self.assertLess(scan.index("AUTHORED_FILES=$(git -C"), scan.index("CHANGE_FILES"))
    self.assertIn("untouched change documents are never scanned", scan)

  def test_c4_scan_normative_words_include_chinese_set(self):
    gate = self.section("## Step 2.65", "## Step 2.7")
    scan = gate[gate.index("### 2.65.1"):gate.index("resolve-authority")]
    self.assertIn("MUST|SHALL|NEVER|必須|不得|一律|只能|不可|禁止|不准", scan)
    # 識別字交集與停用字清單不變
    self.assertIn("index|types|utils|constants|module|service|controller|schema|README|spec|test", scan)
    self.assertIn("command grep -F -w -f", scan)

  def test_c4_clause_qualification_has_two_layers(self):
    gate = self.section("## Step 2.65", "## Step 2.7")
    head = gate[:gate.index("### 2.65.1")]
    self.assertIn("outside the declared authority locations", head)
    self.assertIn("judge each sentence on its own", head)
    for excluded in ("rationale", "goals", "history", "examples", "quoted speech", "`[user: …]`", "`[evidence: …]`"):
      with self.subTest(excluded=excluded):
        self.assertIn(excluded, head)
    self.assertNotIn("informal plan/design prose, and a bare uppercase keyword", head)

  def test_c4_scan_and_reducer_share_one_authored_diff_base(self):
    gate = self.section("## Step 2.65", "## Step 2.7")
    scan = gate[gate.index("### 2.65.1"):gate.index("resolve-authority")]
    # 單輸入不跑 Step 2.05，authored_diff_base 沒有來源；掃描若另用 session trunk，多目標時會跟核驗器判不同的「PR 改到」
    self.assertIn('AUTHORED_DIFF_BASE="${AUTHORED_DIFF_BASE:-$(git -C "$REVIEW_ROOT" merge-base "origin/$TRUNK_BRANCH" HEAD', scan)
    self.assertIn('diff --name-only "$AUTHORED_DIFF_BASE...HEAD"', scan)
    self.assertNotIn('"origin/$TRUNK_BRANCH...HEAD"', scan)
    self.assertIn("`authored_diff_base` = `$AUTHORED_DIFF_BASE`", gate)

  def test_step25_profile_field_list_names_authority(self):
    sync = self.section("## Step 2.5:", "### 2.5.1")
    self.assertIn("authority", sync)
    self.assertNotIn("欄位只有 `trunk`、`spec_globs`、`conventions_docs`；", sync)

  def test_step25_resolves_trunk_from_profile_then_origin_head_then_master(self):
    sync = self.section("## Step 2.5:", "### 2.5.1")
    self.assertIn("pr-review-profile.py", sync)
    self.assertIn("REPO_PROFILE=", sync)
    self.assertIn("TRUNK=<x> (source: profile <path> | origin/HEAD | default master)", sync)
    self.assertIn("**Trunk**: `TRUNK=", self.command)

  def test_provenance_triggers_on_base_not_equal_trunk(self):
    head = self.section("## Step 2.55", "```bash")
    self.assertIn("TRUNK_BRANCH", head)
    self.assertNotRegex(head, r"master ?/ ?main")
    self.assertNotIn("base = master", head)
    self.assertNotIn("base ≠ master", head)
    self.assertIn("base = trunk", head)
    self.assertNotIn("≠ master", self.command)
    self.assertNotIn("base = master", self.command)

  def test_spec_detection_appends_profile_globs(self):
    detect = self.section("### Detection heuristic", "### What to do with detected specs")
    self.assertIn("spec_globs", detect)
    self.assertIn("不是 C4 權威來源", detect)

  def test_conventions_docs_only_reach_cc_shared_prompt(self):
    shared = self.section("#### Shared prompt", "### Codex Review")
    self.assertIn("conventions_docs", shared)
    self.assertIn("沒做的部分", shared)
    for name, block in (
      ("codex", self.section("### Codex Review", "### Gemini Pro / Flash Review")),
      ("gemini", self.section("### Gemini Pro / Flash Review", "## Step 4")),
      ("c4", self.section("## Step 2.65", "## Step 2.7")),
      ("c4-packet", self.section("spec-compliance-reviewer` dispatch", "#### Shared prompt")),
    ):
      with self.subTest(block=name):
        self.assertNotIn("conventions_docs", block)

  def test_private_files_live_under_home_pr_review_dir(self):
    self.assertIn("~/.claude/pr-review/calibration/<author-slug>.md", self.command)
    self.assertIn("~/.claude/pr-review/friction.md", self.command)
    self.assertNotIn("docs/owner/", self.command)
    for word in ("acme", "acme-saas", "acme-dashboard"):
      with self.subTest(word=word):
        self.assertNotIn(word, self.command)


if __name__ == "__main__":
  unittest.main()
