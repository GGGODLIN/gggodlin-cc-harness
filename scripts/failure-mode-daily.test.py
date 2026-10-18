#!/usr/bin/env python3
"""failure-mode-daily.py 的行為測試：給 fixture 探針表，斷言 stdout／out 檔與探針表內容。"""
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

SCRIPT = Path(__file__).with_name("failure-mode-daily.py")
TODAY = date.today()

HEAD = """<!-- 契約測試 -->

# 失敗模式探針表

**誰在哪一步讀**：略

---

## F1 時序

問句略

---

## 案例登記（回流機制追加區）

每行七欄：`YYYY-MM-DD | <Failure-miss|Acceptance-miss> | Fn | <repo> | <ticket 或 PR> | 條件 → 症狀 | 發現於（implement-review／pr-review）`

- `Acceptance-miss` 的 Fn 可填 `-`。
"""


def row(days_ago, tag="Failure-miss", fn="F1", cond="切換 → 舊資料", suffix=""):
  d = (TODAY - timedelta(days=days_ago)).isoformat()
  return f"{d} | {tag} | {fn} | shop | ticket-07 | {cond} | implement-review{suffix}\n"


def load():
  spec = importlib.util.spec_from_file_location("fmd", SCRIPT)
  mod = importlib.util.module_from_spec(spec)
  sys.modules["fmd"] = mod
  spec.loader.exec_module(mod)
  return mod


class FailureModeDailyTest(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp.cleanup)
    self.tax = Path(self.tmp.name) / "taxonomy.md"
    self.out = Path(self.tmp.name) / "out.md"
    self.mod = load()

  def run_cli(self):
    p = subprocess.run([sys.executable, str(SCRIPT), "--taxonomy", str(self.tax), "--date", TODAY.isoformat(), "--out", str(self.out)],
                       capture_output=True, text=True)
    self.assertEqual(p.returncode, 0, p.stderr)
    return self.out.read_text()

  def header_line(self):
    return next((l for l in self.tax.read_text().splitlines() if l.startswith("> 近 30 天最常漏")), None)

  def test_counts_only_thirty_day_window_and_splits_tags(self):
    rows = [row(1), row(2), row(3, fn="F2"), row(4, tag="Acceptance-miss", fn="-"), row(29, fn="F2"),
            row(31), row(40, fn="F2"), row(60, tag="Acceptance-miss", fn="F3")]
    self.tax.write_text(HEAD + "".join(rows))
    out = self.run_cli()
    self.assertIn("| F1 | 2 | 0 |", out)
    self.assertIn("| F2 | 2 | 0 |", out)
    self.assertIn("| - | 0 | 1 |", out)
    self.assertNotIn("| F3 |", out)
    self.assertIn("Failure-miss 4", out)
    self.assertIn("Acceptance-miss 1", out)

  def test_thresholds_are_listed_not_judged(self):
    rows = [row(1), row(2), row(3, fn="F7"), row(4, fn="F7"), row(5, fn="F7"), row(6, tag="Acceptance-miss", fn="-", cond="空字串 → 空白")]
    self.tax.write_text(HEAD + "".join(rows))
    out = self.run_cli()
    self.assertIn("F1 同類第 2 筆", out)
    self.assertIn("F7／未分類累積 3 筆", out)
    self.assertNotIn("F7 同類第 2 筆", out)
    self.assertIn("Acceptance-miss：空字串 → 空白", out)
    self.assertIn("暫定", out)

  def test_silent_when_no_rows_in_window_but_header_still_maintained(self):
    self.tax.write_text(HEAD + row(31) + row(45, fn="F2"))
    out = self.run_cli()
    self.assertEqual(out.strip(), "__SILENT__")
    self.assertEqual(self.header_line(), f"> 近 30 天最常漏：（尚無登記）｜更新 {TODAY.isoformat()}")

  def test_header_inserted_before_first_rule_then_rewritten_in_place_and_stable_bytes(self):
    self.tax.write_text(HEAD + row(1) + row(2, fn="F2") + row(3, fn="F2"))
    self.run_cli()
    lines = self.tax.read_text().splitlines()
    idx = lines.index(f"> 近 30 天最常漏：F2（2）、F1（1）｜更新 {TODAY.isoformat()}")
    self.assertLess(idx, lines.index("---"))
    self.assertEqual(lines.count("---"), 2)
    before = self.tax.read_bytes()
    self.run_cli()
    self.assertEqual(self.tax.read_bytes(), before)
    self.tax.write_text(self.tax.read_text() + row(0, fn="F5") + row(0, fn="F5") + row(0, fn="F5"))
    self.run_cli()
    lines = self.tax.read_text().splitlines()
    self.assertEqual(sum(1 for l in lines if l.startswith("> 近 30 天最常漏")), 1)
    self.assertEqual(lines[idx], f"> 近 30 天最常漏：F5（3）、F2（2）｜更新 {TODAY.isoformat()}")

  def test_concurrent_append_between_read_and_write_is_preserved(self):
    self.tax.write_text(HEAD + row(1))
    appended = row(0, fn="F4", cond="第三方 5xx → 白畫面")
    calls = {"n": 0}

    def after_read(_):
      calls["n"] += 1
      if calls["n"] == 1:
        with self.tax.open("a") as f:
          f.write(appended)

    report, wrote = self.mod.run(self.tax, TODAY, after_read=after_read)
    self.assertTrue(wrote)
    text = self.tax.read_text()
    self.assertIn(appended, text)
    self.assertEqual(self.header_line(), f"> 近 30 天最常漏：F1（1）、F4（1）｜更新 {TODAY.isoformat()}")
    self.assertEqual(len(self.mod.parse(text).rows), 2)
    self.assertIn("重讀後重算", report)

  def test_gives_up_after_three_conflicts_and_says_so(self):
    self.tax.write_text(HEAD + row(1))

    def after_read(_):
      with self.tax.open("a") as f:
        f.write(row(0, fn="F6"))

    report, wrote = self.mod.run(self.tax, TODAY, after_read=after_read)
    self.assertFalse(wrote)
    self.assertIn("放棄本日檔首改寫", report)
    self.assertNotIn("__SILENT__", report)
    self.assertIsNone(self.header_line())
    self.tax.write_text(HEAD + row(40))
    report, wrote = self.mod.run(self.tax, TODAY, after_read=after_read)
    self.assertFalse(wrote)
    self.assertIn("放棄本日檔首改寫", report)
    self.assertNotIn("__SILENT__", report)

  def test_bad_rows_are_listed_and_not_counted(self):
    bad1 = "2026-09-24 | Failure-miss | F1 | shop | 缺兩欄\n"
    bad2 = "2026-13-40 | Failure-miss | F1 | shop | t | c → s | pr-review\n"
    bad3 = "2026-09-24 | Failure-miss | F9 | shop | t | c → s | pr-review\n"
    bad4 = "- 2026-09-24 | Failure-miss | F1 | shop | t | 模仿條列 → 前面多了 - | pr-review\n"
    bad5 = "2026-09-24|Failure-miss|F1|shop|t|沒空格 → 分不開|pr-review\n"
    bad6 = f"{(TODAY + timedelta(days=29)).isoformat()} | Failure-miss | F1 | shop | t | 未來日期 → 打錯 | pr-review\n"
    self.tax.write_text(HEAD + row(1) + bad1 + bad2 + bad3 + bad4 + bad5 + bad6)
    out = self.run_cli()
    self.assertIn("## 無法解析", out)
    for b in (bad1, bad2, bad3, bad4, bad5, bad6):
      self.assertIn(b.strip(), out)
    self.assertIn("| F1 | 1 | 0 |", out)
    self.assertNotRegex(out, r"(?m)^\| F9 \| \d")

  def test_boundary_day_empty_registry_and_missing_file(self):
    self.tax.write_text(HEAD + row(30) + row(31, fn="F2"))
    out = self.run_cli()
    self.assertIn("| F1 | 1 | 0 |", out)
    self.assertNotIn("| F2 |", out)
    self.tax.write_text(HEAD)
    out = self.run_cli()
    self.assertEqual(out.strip(), "__SILENT__")
    self.assertEqual(self.header_line(), f"> 近 30 天最常漏：（尚無登記）｜更新 {TODAY.isoformat()}")
    self.tax.unlink()
    p = subprocess.run([sys.executable, str(SCRIPT), "--taxonomy", str(self.tax), "--date", TODAY.isoformat(), "--out", str(self.out)],
                       capture_output=True, text=True)
    self.assertEqual(p.returncode, 0, p.stderr)
    self.assertIn("探針表不存在", self.out.read_text())
    self.assertFalse(self.tax.exists())

  def test_reviewed_suffix_rows_count_but_do_not_trigger_thresholds_or_silence(self):
    self.tax.write_text(HEAD + row(1, suffix=" [reviewed 2026-09-20 改 F1 問句：`useEffect` 未 cleanup]") + row(2, cond="`variants` 放錯層級 → 422"))
    out = self.run_cli()
    self.assertIn("| F1 | 2 | 0 |", out)
    self.assertNotIn("F1 同類第 2 筆", out)
    self.assertNotIn("## 無法解析", out)
    self.tax.write_text(HEAD + row(1, suffix=" [reviewed 2026-09-24 不改]") + row(2, tag="Acceptance-miss", fn="-", suffix=" [reviewed 2026-09-24 記摩擦]"))
    out = self.run_cli()
    self.assertEqual(out.strip(), "__SILENT__")
    self.assertEqual(self.header_line(), f"> 近 30 天最常漏：F1（1）｜更新 {TODAY.isoformat()}")

  def test_acceptance_miss_never_drives_thresholds_or_header(self):
    self.tax.write_text(HEAD + row(1, fn="F6") + row(2, tag="Acceptance-miss", fn="F6") + row(3, tag="Acceptance-miss", fn="-"))
    out = self.run_cli()
    self.assertNotIn("F6 同類第 2 筆", out)
    self.assertEqual(sum(1 for l in out.splitlines() if l.startswith("- Acceptance-miss：")), 2)
    self.assertEqual(self.header_line(), f"> 近 30 天最常漏：F6（1）｜更新 {TODAY.isoformat()}")

  def test_acceptance_miss_em_dash_counts_without_rewriting_history(self):
    original = row(2, tag="Acceptance-miss", fn="—")
    self.tax.write_text(HEAD + row(1, fn="F6") + original)
    out = self.run_cli()
    self.assertIn("Acceptance-miss 1", out)
    self.assertIn("| - | 0 | 1 |", out)
    self.assertNotIn("## 無法解析", out)
    self.assertIn(original, self.tax.read_text())
    self.assertNotIn("F6 同類第 2 筆", out)

  def test_failure_miss_em_dash_still_requires_a_class(self):
    invalid = row(1, fn="—")
    self.tax.write_text(HEAD + invalid)
    out = self.run_cli()
    self.assertIn("## 無法解析", out)
    self.assertIn(invalid.strip(), out)
    self.assertIn("Failure-miss 0", out)

  def test_append_between_reread_and_replace_is_copied_over(self):
    self.tax.write_text(HEAD + row(1))
    self.tax.chmod(0o644)
    appended = row(0, fn="F3", cond="第三方改欄位 → 解析失敗")

    def before_write(_):
      with self.tax.open("a") as f:
        f.write(appended)

    report, wrote = self.mod.run(self.tax, TODAY, before_write=before_write)
    self.assertTrue(wrote)
    text = self.tax.read_text()
    self.assertIn(appended, text)
    self.assertEqual(len(self.mod.parse(text).rows), 2)
    self.assertIn("補回 1 行並發 append", report)
    self.assertEqual(self.tax.stat().st_mode & 0o777, 0o644)

  def test_backfill_date_does_not_rewrite_header(self):
    self.tax.write_text(HEAD + row(1))
    report, wrote = self.mod.run(self.tax, TODAY, allow_write=False)
    self.assertFalse(wrote)
    self.assertIsNone(self.header_line())
    self.assertIn("只算不改檔首", report)


if __name__ == "__main__":
  unittest.main()
