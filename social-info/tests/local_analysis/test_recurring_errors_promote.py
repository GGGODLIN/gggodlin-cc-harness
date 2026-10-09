import json
import subprocess
import sys
from pathlib import Path

DIR = Path(__file__).resolve().parent
ROOT = DIR.parents[1]
SCRIPT = ROOT / "scripts" / "local-analysis" / "recurring-errors-promote.py"
REPORT = DIR / "fixtures" / "2026-08-11-recurring-errors.md"
REPORT_0804 = DIR / "fixtures" / "2026-08-04-recurring-errors.md"
ALIASES = ROOT / "scripts" / "local-analysis" / "recurring-errors-pattern-aliases.json"
LEGACY_TITLE = "recurring-errors 3 個上升／新達門檻 pattern 對策（Workflow deferred tool 帶未知參數 5→9 session / Edit old_string 不匹配 9 / Read 大檔未帶 offset-limit 4）"
SOURCE_KEYS = [
  "recurring-errors:shell-eval-syntax",
  "recurring-errors:python-traceback-json",
  "recurring-errors:read-path-cwd",
  "recurring-errors:chrome-tab-session",
  "recurring-errors:git-operations",
  "recurring-errors:edit-replace-all",
]


def row(title, status, source_key=None, next_due=None):
  value = {
    "title": title,
    "first_seen": "2026-07-28",
    "last_seen": "2026-07-28",
    "count": 1,
    "status": status,
    "note": "fixture",
  }
  if source_key is not None:
    value["source_key"] = source_key
  if next_due is not None:
    value["next_due"] = next_due
  return value


def run_selector(tmp_path, rows, report=REPORT, date="2026-08-11"):
  ledger = tmp_path / "pending-actions.jsonl"
  ledger.write_text("".join(f"{json.dumps(value, ensure_ascii=False)}\n" for value in rows))
  result = subprocess.run(
    [
      sys.executable,
      str(SCRIPT),
      "--date",
      date,
      "--report",
      str(report),
      "--ledger",
      str(ledger),
      "--aliases",
      str(ALIASES),
    ],
    capture_output=True,
    text=True,
  )
  return result


def test_legacy_bundle_does_not_suppress_patterns_missing_from_its_title(tmp_path):
  result = run_selector(tmp_path, [row(LEGACY_TITLE, "killed")])

  assert result.returncode == 0, result.stderr
  packet = json.loads(result.stdout)
  assert packet["eligible_count"] == 6
  assert packet["candidate"]["source_key"] == "recurring-errors:shell-eval-syntax"
  assert packet["candidate"]["bucket"] == "high"
  assert packet["candidate"]["finding"] == {
    "title": "recurring-errors：shell eval 語法混淆",
    "match": None,
    "channel": "recurring-errors",
    "source_key": "recurring-errors:shell-eval-syntax",
    "note": "2026-08-11 recurring-errors 第 2 次以上：🚨 shell eval 語法混淆",
  }


def test_high_severity_wins_when_no_prior_decision_exists(tmp_path):
  result = run_selector(tmp_path, [])

  assert result.returncode == 0, result.stderr
  packet = json.loads(result.stdout)
  assert packet["candidate"]["source_key"] == "recurring-errors:shell-eval-syntax"
  assert packet["candidate"]["bucket"] == "high"


def test_future_defer_skips_to_the_next_unresolved_pattern(tmp_path):
  rows = [
    row(
      "recurring-errors：shell eval 語法混淆",
      "pending",
      source_key="recurring-errors:shell-eval-syntax",
      next_due="2026-08-18",
    ),
  ]
  result = run_selector(tmp_path, rows)

  assert result.returncode == 0, result.stderr
  packet = json.loads(result.stdout)
  assert packet["candidate"]["source_key"] == "recurring-errors:python-traceback-json"


def test_pending_without_future_due_is_promoted_again(tmp_path):
  title = "recurring-errors：shell eval 語法混淆"
  rows = [row(title, "pending", source_key="recurring-errors:shell-eval-syntax")]
  result = run_selector(tmp_path, rows)

  assert result.returncode == 0, result.stderr
  packet = json.loads(result.stdout)
  assert packet["candidate"]["source_key"] == "recurring-errors:shell-eval-syntax"
  assert packet["candidate"]["finding"]["match"] == title


def test_all_decided_patterns_produce_no_candidate(tmp_path):
  statuses = ["done", "killed", "kept", "observing", "done", "killed"]
  rows = [
    row(f"decided-{index}", statuses[index], source_key=source_key)
    for index, source_key in enumerate(SOURCE_KEYS)
  ]
  result = run_selector(tmp_path, rows)

  assert result.returncode == 0, result.stderr
  packet = json.loads(result.stdout)
  assert packet["candidate"] is None


def test_historical_title_variant_keeps_the_same_signature_identity(tmp_path):
  rows = [
    row("dcg known defense", "killed", source_key="recurring-errors:auto-e52601e900d6f3c7"),
    row(
      "recurring-errors：shell eval 語法混淆",
      "pending",
      source_key="recurring-errors:shell-eval-syntax",
      next_due="2026-08-18",
    ),
  ]
  result = run_selector(tmp_path, rows, report=REPORT_0804, date="2026-08-04")

  assert result.returncode == 0, result.stderr
  packet = json.loads(result.stdout)
  assert packet["candidate"]["source_key"] == "recurring-errors:python-traceback-json"
  assert packet["candidate"]["pattern"] == "Python 腳本 traceback / JSON decode 錯誤鏈"


def test_other_channel_source_key_does_not_break_recurring_selection(tmp_path):
  result = run_selector(tmp_path, [row("wiki item", "pending", source_key="wiki-lint:brand-new-item")])

  assert result.returncode == 0, result.stderr
  packet = json.loads(result.stdout)
  assert packet["candidate"]["source_key"] == "recurring-errors:shell-eval-syntax"


def test_observed_2026_09_01_heading_is_accepted(tmp_path):
  report = tmp_path / "2026-09-01-recurring-errors.md"
  report.write_text(
    "## 🔁 重複錯誤 pattern（按 escalation 優先，再按目前簽名次數）\n\n"
    "### 🚨 observed pattern（第 2 次）\n"
    "- 代表簽名：`stable observed signature`\n"
  )
  result = run_selector(tmp_path, [], report=report, date="2026-09-01")

  assert result.returncode == 0, result.stderr
  packet = json.loads(result.stdout)
  assert packet["eligible_count"] == 1
  assert packet["candidate"]["pattern"] == "observed pattern"


def test_similar_or_fenced_section_does_not_count_as_the_real_section(tmp_path):
  report = tmp_path / "2026-08-11-recurring-errors.md"
  report.write_text(
    "## 🔁 重複錯誤 pattern 寫作範例\n\n"
    "```markdown\n"
    "## 🔁 重複錯誤 pattern（按次數降冪）\n"
    "### 🚨 fake（第 2 次）\n"
    "- 代表簽名：`fake`\n"
    "```\n"
  )
  result = run_selector(tmp_path, [], report=report)

  assert result.returncode != 0
  assert "exactly one recurring pattern section" in result.stderr


def test_invalid_calendar_date_fails_closed(tmp_path):
  result = run_selector(tmp_path, [], date="2026-02-31")

  assert result.returncode != 0
  assert "valid calendar date" in result.stderr


def test_noncanonical_calendar_date_fails_closed(tmp_path):
  result = run_selector(tmp_path, [], date="20260811")

  assert result.returncode != 0
  assert "YYYY-MM-DD" in result.stderr


def test_invalid_next_due_fails_closed(tmp_path):
  rows = [
    row(
      "recurring-errors：shell eval 語法混淆",
      "pending",
      source_key="recurring-errors:shell-eval-syntax",
      next_due="2026-02-31",
    ),
  ]
  result = run_selector(tmp_path, rows)

  assert result.returncode != 0
  assert "valid calendar date" in result.stderr


def test_title_and_signature_alias_conflict_fails_closed(tmp_path):
  report = tmp_path / "2026-08-11-recurring-errors.md"
  report.write_text(
    "## 🔁 重複錯誤 pattern（按次數降冪）\n\n"
    "### 🚨 shell eval 語法混淆（第 2 次）\n"
    "- 代表簽名：`traceback (most recent call last):`\n"
  )
  result = run_selector(tmp_path, [], report=report)

  assert result.returncode != 0
  assert "title and signature aliases disagree" in result.stderr


def test_unknown_pattern_reuses_existing_title_identity_when_signatures_change(tmp_path):
  report = tmp_path / "2026-08-11-recurring-errors.md"
  report.write_text(
    "## 🔁 重複錯誤 pattern（按次數降冪）\n\n"
    "### ⚠️ unknown pattern（第 2 次）\n"
    "- 代表簽名：`stable primary`\n"
  )
  first = run_selector(tmp_path, [], report=report)

  assert first.returncode == 0, first.stderr
  first_packet = json.loads(first.stdout)
  assert first_packet["candidate"]["source_key"] == "recurring-errors:auto-27ceeb4db760d055"

  report.write_text(
    "## 🔁 重複錯誤 pattern（按次數降冪）\n\n"
    "### ⚠️ unknown pattern（第 3 次）\n"
    "- 代表簽名：`different primary`；`new secondary`\n"
  )
  rows = [
    row(
      "recurring-errors：unknown pattern",
      "pending",
      source_key="recurring-errors:auto-27ceeb4db760d055",
    ),
  ]
  second = run_selector(tmp_path, rows, report=report)

  assert second.returncode == 0, second.stderr
  candidate = json.loads(second.stdout)["candidate"]
  assert candidate["finding"]["source_key"] == "recurring-errors:auto-27ceeb4db760d055"
  assert candidate["finding"]["match"] == "recurring-errors：unknown pattern"

  findings = tmp_path / "findings.json"
  findings.write_text(json.dumps([candidate["finding"]], ensure_ascii=False))
  applied = subprocess.run(
    [
      sys.executable,
      str(ROOT / "scripts" / "local-analysis" / "ledger-reconcile.py"),
      "--date",
      "2026-08-11",
      "--ledger",
      str(tmp_path / "pending-actions.jsonl"),
      "--findings",
      str(findings),
      "--apply",
      "--no-health",
      "--json",
    ],
    capture_output=True,
    text=True,
  )
  assert applied.returncode == 0, applied.stderr
  applied_rows = [json.loads(line) for line in (tmp_path / "pending-actions.jsonl").read_text().splitlines()]
  assert applied_rows[0]["source_key"] == "recurring-errors:auto-27ceeb4db760d055"


def test_unknown_pattern_keeps_identity_when_secondary_signatures_change(tmp_path):
  report = tmp_path / "2026-08-11-recurring-errors.md"
  report.write_text(
    "## 🔁 重複錯誤 pattern（按次數降冪）\n\n"
    "### ⚠️ first title（第 2 次）\n"
    "- 代表簽名：`stable primary`\n"
  )
  first = run_selector(tmp_path, [], report=report)

  assert first.returncode == 0, first.stderr
  source_key = json.loads(first.stdout)["candidate"]["source_key"]

  report.write_text(
    "## 🔁 重複錯誤 pattern（按次數降冪）\n\n"
    "### ⚠️ renamed title（第 3 次）\n"
    "- 代表簽名：`stable primary`；`new secondary`\n"
  )
  second = run_selector(
    tmp_path,
    [row("recurring-errors：first title", "killed", source_key=source_key)],
    report=report,
  )

  assert second.returncode == 0, second.stderr
  assert json.loads(second.stdout)["candidate"] is None


def test_longer_fence_is_not_closed_by_shorter_nested_fence(tmp_path):
  report = tmp_path / "2026-08-11-recurring-errors.md"
  report.write_text(
    "````markdown\n"
    "```\n"
    "## 🔁 重複錯誤 pattern（按次數降冪）\n"
    "### 🚨 fake（第 2 次）\n"
    "- 代表簽名：`fake`\n"
    "```\n"
    "````python\n"
    "## 🔁 重複錯誤 pattern（按次數降冪）\n"
    "### 🚨 also fake（第 2 次）\n"
    "- 代表簽名：`also fake`\n"
    "````\n\n"
    "## 🔁 重複錯誤 pattern（按次數降冪）\n\n"
    "### ⚠️ real（第 2 次）\n"
    "- 代表簽名：`real signature`\n"
  )
  result = run_selector(tmp_path, [], report=report)

  assert result.returncode == 0, result.stderr
  packet = json.loads(result.stdout)
  assert packet["eligible_count"] == 1
  assert packet["candidate"]["pattern"] == "real"


def test_duplicate_source_keys_fail_closed(tmp_path):
  rows = [
    row("duplicate-a", "pending", source_key="recurring-errors:read-path-cwd"),
    row("duplicate-b", "pending", source_key="recurring-errors:read-path-cwd"),
  ]
  result = run_selector(tmp_path, rows)

  assert result.returncode != 0
  assert "duplicate source_key" in result.stderr
