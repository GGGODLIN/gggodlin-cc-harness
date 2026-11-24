#!/usr/bin/env python3
"""failure-mode-daily.py 的行為測試：給 fixture 探針表，斷言 stdout／out 檔與探針表內容。"""
import importlib.util
import re
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

  def test_real_taxonomy_has_47_unique_probe_ids_and_parses_with_zero_bad_rows(self):
    real_text = self.mod.DEFAULT_TAXONOMY.read_text()
    probe_ids = re.findall(r"^\s*-\s*\[(F\d+\.\d+)\]", real_text, re.M)
    self.assertEqual(len(probe_ids), 47)
    self.assertEqual(len(set(probe_ids)), 47)
    self.assertFalse(any(pid.startswith("F7.") for pid in probe_ids))
    parsed = self.mod.parse(real_text)
    self.assertEqual(parsed.bad, [])
    self.assertGreater(len(parsed.rows), 500)
    self.tax.write_text(real_text)
    before_rows = [r.raw for r in self.mod.parse(self.tax.read_text()).rows]
    self.run_cli()
    after_first_bytes = self.tax.read_bytes()
    after_rows = [r.raw for r in self.mod.parse(self.tax.read_text()).rows]
    self.assertEqual(after_rows, before_rows)
    self.run_cli()
    self.assertEqual(self.tax.read_bytes(), after_first_bytes)

  def test_auto_archived_rows_keep_unreviewed_zero_while_surfacing_escalation_without_silence(self):
    head_with_dec = HEAD.replace("## 案例登記", "## 累犯決策紀錄（回流機制追加區）\n\n每行五欄：略\n\n---\n\n## 案例登記")
    unarchived = [
      f"{(TODAY - timedelta(days=i)).isoformat()} | Failure-miss | F5 | app | feat/0{i} | 雙處規則 → 漂移 | implement-review [reviewed {TODAY.isoformat()} 不改 probe=F5.2]\n"
      if i <= 2 else
      f"{(TODAY - timedelta(days=i)).isoformat()} | Failure-miss | F5 | app | feat/0{i} | 雙處規則 → 漂移 | implement-review\n"
      for i in range(1, 6)
    ]
    all_auto = [
      f"{(TODAY - timedelta(days=i)).isoformat()} | Failure-miss | F5 | app | feat/0{i} | 雙處規則 → 漂移 | implement-review [reviewed {TODAY.isoformat()} 自動結清 probe=F5.2 mode=auto-verified]\n"
      for i in range(1, 6)
    ]
    partial_parsed = self.mod.parse(head_with_dec + "".join(unarchived), TODAY)
    full_parsed = self.mod.parse(head_with_dec + "".join(all_auto), TODAY)
    _, partial_totals = self.mod.escalation_candidates(partial_parsed, TODAY)
    cands, full_totals = self.mod.escalation_candidates(full_parsed, TODAY)
    self.assertEqual(full_totals["F5.2"], 5)
    self.assertEqual(cands[0].probe, "F5.2")
    self.assertEqual(cands[0].unit_count, 5)
    self.assertGreater(full_totals["F5.2"], partial_totals["F5.2"])

    # 當 5 筆皆帶相同 probe=F5.2 時，半數已歸檔（另半數人工已標 probe）與全數 auto-verified 的累犯計數完全相等
    half_auto_same_probe = all_auto[:3] + [
      l.replace(" mode=auto-verified", "") for l in all_auto[3:]
    ]
    _, half_totals = self.mod.escalation_candidates(self.mod.parse(head_with_dec + "".join(half_auto_same_probe), TODAY), TODAY)
    self.assertEqual(half_totals["F5.2"], full_totals["F5.2"])

    self.tax.write_text(head_with_dec + "".join(all_auto))
    out = self.run_cli()
    self.assertNotEqual(out.strip(), "__SILENT__")
    self.assertIn("- F5.2：5 張獨立工作單（全窗 5 單", out)
    self.assertIn("app:feat/01", out)
    self.assertIn("## 門檻命中（三個門檻值暫定；只列不判斷）\n\n（無）", out)

  def test_work_unit_dedup_merges_same_pr_and_commit_keeps_subtickets_distinct_and_combines_tagged_am(self):
    d1 = (TODAY - timedelta(days=1)).isoformat()
    d2 = (TODAY - timedelta(days=2)).isoformat()
    rows = [
      # 同一個 PR #353 多種寫法 3 行 → 1 單，另驗 Bitbucket PR 與附註括號子票不誤併
      f"{d1} | Failure-miss | F5 | saas | PR #353 | 條件1 → 症狀1 | pr-review [reviewed {d1} 不改：[F5.2] 見 tests/t.py::test_a[0] probe=F5.2]\n",
      f"{d1} | Failure-miss | F5 | saas | github:github.com/acmeInc/saas#353 | 條件2 → 症狀2 | pr-review [reviewed {d1} 不改 probe=F5.2]\n",
      f"{d1} | Acceptance-miss | - | saas | #353 | 條件3 → 症狀3 | pr-review [reviewed {d1} 接受風險 probe=F5.2 mode=auto-accepted]\n",
      # 同一個本地 commit 拆兩檔 → 1 單
      f"{d2} | Failure-miss | F5 | ops | local:ops@adf5374 bg.py | 條件4 → 症狀4 | implement-review [reviewed {d2} 自動 probe=F5.2 mode=auto-verified]\n",
      f"{d2} | Failure-miss | F5 | ops | local:ops@adf5374 test_bg.py | 條件5 → 症狀5 | implement-review [reviewed {d2} 自動 probe=F5.2 mode=auto-verified]\n",
      # 同功能前綴下 3 個不同子票號（即使括號附註同一 github#10 也不得誤併成 1 單）→ 3 單（合計 1+1+3=5 單！）
      f"{d2} | Failure-miss | F5 | dash | ticket-fixture/01（github.com/org/dash#10） | 條件6 → 症狀6 | implement-review [reviewed {d2} 自動 probe=F5.2 mode=auto-verified]\n",
      f"{d2} | Failure-miss | F5 | dash | ticket-fixture/02（github.com/org/dash#10） | 條件7 → 症狀7 | implement-review [reviewed {d2} 自動 probe=F5.2 mode=auto-verified]\n",
      f"{d2} | Acceptance-miss | - | dash | ticket-fixture/03 | 票已列 → 初版漏做 | implement-review [reviewed {d2} 自動 probe=F5.2 mode=auto-verified]\n",
      # Bitbucket PR target_identity 與 PR #42 去重為 1 單
      f"{d1} | Failure-miss | F2 | bb-shop | bitbucket:bitbucket.org/acme/bb-shop#42 | b1 → s1 | pr-review [reviewed {d1} 不改 probe=F2.1]\n",
      f"{d1} | Failure-miss | F2 | bb-shop | PR #42 | b2 → s2 | pr-review [reviewed {d1} 不改 probe=F2.1]\n",
      # 無細項 Acceptance-miss 6 單與 F7 6 單：只進總量觀測，絕不進累犯升級候選
      *[f"{d2} | Acceptance-miss | - | dash | plain-am/0{k} | 漏做 → 補齊 | implement-review [reviewed {d2} 自動 probe=none mode=auto-verified]\n" for k in range(1, 7)],
      *[f"{d2} | Failure-miss | F7 | dash | logic-f7/0{k} | 算錯 → 修正 | implement-review [reviewed {d2} 不改 probe=none]\n" for k in range(1, 7)],
    ]
    self.tax.write_text(HEAD + "".join(rows))
    out_forward = self.run_cli()
    self.assertIn("- F5.2：5 張獨立工作單", out_forward)
    self.assertIn("- F2.1：1 張獨立工作單", out_forward)
    self.assertIn("無細項 Acceptance-miss 6 單、F7 6 單", out_forward)
    # 正向對照已證明 F5.2 出現在升級候選區；負向確認 F7 與無細項 Acceptance-miss 未混入升級候選區
    esc_section = out_forward.split("## 累犯升級候選")[1].split("## 門檻命中")[0]
    self.assertIn("F5.2：", esc_section)
    self.assertFalse("F7：" in esc_section)
    self.assertFalse("Acceptance-miss：" in esc_section)
    # 檔首 top-2 維持只計全窗 Failure-miss（F5 有 6 行 Failure-miss、F7 有 6 行 Failure-miss，Acceptance-miss 不計入）
    self.assertEqual(self.header_line(), f"> 近 30 天最常漏：F5（6）、F7（6）｜更新 {TODAY.isoformat()}")

    # 任意重排案例列後，去重計數與升級候選完全不變
    self.tax.write_text(HEAD + "".join(reversed(rows)))
    out_reversed = self.run_cli()
    self.assertIn("- F5.2：5 張獨立工作單", out_reversed)

  def test_top3_cap_with_ten_qualifying_subitems_and_decision_lifecycle_suppression(self):
    dec_block = "## 累犯決策紀錄（回流機制追加區）\n\n每行五欄：略\n\n"
    base_head = HEAD.replace("## 案例登記", dec_block + "---\n\n## 案例登記")
    d_old = (TODAY - timedelta(days=10)).isoformat()
    d_dec = (TODAY - timedelta(days=8)).isoformat()
    d_mid = (TODAY - timedelta(days=3)).isoformat()
    d_new = (TODAY - timedelta(days=1)).isoformat()

    # 建立 10 條無決策抑制且同時達 ≥5 單的細項，外加 1 條 open 抑制與 1 條 deferred 未滿新 5 單：
    # 10 條同時達標無抑制：F2.1(6 單, mid), F1.4(5 單, new), F4.2(5 單, new), F4.5(5 單, new),
    #   F1.1(5 單, mid), F1.2(5 單, mid), F2.2(5 單, mid), F3.1(5 單, mid), F3.2(5 單, mid), F5.1(5 單, mid)
    decisions = [
      f"{d_dec} | F5.2 | open | ref=fixture-obs-f5-2 | 已開立試用觀察中\n",
      f"{d_dec} | F6.1 | deferred | ref=N-A | 暫緩觀察決策日後新單\n",
    ]
    case_rows = []
    for k in range(1, 8):
      case_rows.append(f"{d_new} | Failure-miss | F5 | r | u{k} | c → s | implement-review [reviewed {d_new} 自動 probe=F5.2 mode=auto-verified]\n")
    for k in range(1, 7):
      case_rows.append(f"{d_mid} | Failure-miss | F2 | r | u{k} | c → s | implement-review [reviewed {d_mid} 自動 probe=F2.1 mode=auto-verified]\n")
    for p, day_str in (
      ("F1.4", d_new), ("F4.2", d_new), ("F4.5", d_new),
      ("F1.1", d_mid), ("F1.2", d_mid), ("F2.2", d_mid), ("F3.1", d_mid), ("F3.2", d_mid), ("F5.1", d_mid),
    ):
      cls = p.split(".")[0]
      for k in range(1, 6):
        case_rows.append(f"{day_str} | Failure-miss | {cls} | r | {p}-u{k} | c → s | implement-review [reviewed {day_str} 自動 probe={p} mode=auto-verified]\n")
    for k in range(1, 3):
      case_rows.append(f"{d_old} | Failure-miss | F6 | r | old{k} | c → s | implement-review [reviewed {d_old} 自動 probe=F6.1 mode=auto-verified]\n")
    for k in range(1, 5):
      case_rows.append(f"{d_new} | Failure-miss | F6 | r | new{k} | c → s | implement-review [reviewed {d_new} 自動 probe=F6.1 mode=auto-verified]\n")

    txt = base_head.replace("---\n\n## 案例登記", "".join(decisions) + "\n---\n\n## 案例登記") + "".join(case_rows)
    self.tax.write_text(txt)
    out = self.run_cli()
    self.assertIn("- F5.2：7 張獨立工作單", out)
    self.assertIn("- F6.1：6 張獨立工作單", out)
    esc_lines = [l for l in out.split("## 累犯升級候選")[1].split("## 門檻命中")[0].splitlines() if l.startswith("- ")]
    self.assertEqual(len(esc_lines), 3)
    self.assertTrue(esc_lines[0].startswith("- F2.1：6 張獨立工作單"))
    self.assertTrue(esc_lines[1].startswith("- F1.4：5 張獨立工作單"))
    self.assertTrue(esc_lines[2].startswith("- F4.2：5 張獨立工作單"))

    # 當 F6.1 改為 closed 且在決策日後補滿第 6 張新單（超越 5 單群），即排進前 3 名
    decisions_closed = [
      f"{d_dec} | F5.2 | open | ref=fixture-obs-f5-2 | 已開立試用觀察中\n",
      f"{d_dec} | F6.1 | closed | ref=fixture-obs-f6-1 | 前案結案後重算新單\n",
    ]
    case_rows.append(f"{d_new} | Failure-miss | F6 | r | new5 | c → s | implement-review [reviewed {d_new} 自動 probe=F6.1 mode=auto-verified]\n")
    case_rows.append(f"{d_new} | Failure-miss | F6 | r | new6 | c → s | implement-review [reviewed {d_new} 自動 probe=F6.1 mode=auto-verified]\n")
    txt2 = base_head.replace("---\n\n## 案例登記", "".join(decisions_closed) + "\n---\n\n## 案例登記") + "".join(case_rows)
    self.tax.write_text(txt2)
    out2 = self.run_cli()
    self.assertIn("- F6.1：6 張獨立工作單（全窗 8 單", out2)

  def test_decision_and_suffix_bad_rows_section_bounds_and_concurrent_decision_edit(self):
    d1 = (TODAY - timedelta(days=1)).isoformat()
    bad_dec_open_na = f"{d1} | F5.2 | open | ref=N-A | open 不得無引用\n"
    bad_dec_target = f"{d1} | Acceptance-miss | deferred | ref=N-A | 無細項不得當決策目標\n"
    bad_dec_dash_no_date = "- F5.2 | open | ref=trial-x | 誤加破折號且漏日期\n"
    good_dec = f"{d1} | F1.1 | deferred | ref=N-A | 合法暫緩列\n"
    bad_suffix_mode = f"{d1} | Failure-miss | F1 | r | t1 | c → s | implement-review [reviewed {d1} 人工 probe=F1.1 mode=human]\n"
    bad_suffix_probe = f"{d1} | Failure-miss | F1 | r | t2 | c → s | implement-review [reviewed {d1} 自動 probe=F9.1 mode=auto-verified]\n"
    bad_suffix_unclosed = f"{d1} | Failure-miss | F1 | r | t3 | c → s | implement-review [reviewed {d1} 截斷未閉合 probe=F1.1\n"
    bad_suffix_double = f"{d1} | Failure-miss | F1 | r | t4 | c → s | implement-review [reviewed {d1} A] [reviewed {d1} B]\n"
    bad_case_slash_date = "- 2026/11/18 | Failure-miss | F1 | r | t5 | 斜線日期 → 壞行 | pr-review\n"

    content = HEAD.replace(
      "## 案例登記",
      "## 累犯決策紀錄（回流機制追加區）\n\n每行五欄：略\n- 說明列含反引號 `open|deferred|closed` 不算壞行\n\n"
      + good_dec + bad_dec_open_na + bad_dec_target + bad_dec_dash_no_date + "\n---\n\n## 案例登記",
    ) + bad_suffix_mode + bad_suffix_probe + bad_suffix_unclosed + bad_suffix_double + bad_case_slash_date
    self.tax.write_text(content)
    out = self.run_cli()
    self.assertNotEqual(out.strip(), "__SILENT__")
    self.assertIn("## 無法解析", out)
    for b in (bad_dec_open_na, bad_dec_target, bad_dec_dash_no_date, bad_suffix_mode, bad_suffix_probe, bad_suffix_unclosed, bad_suffix_double, bad_case_slash_date):
      self.assertIn(b.strip(), out)
    self.assertNotIn("說明列含反引號", out)

    # 即使章節順序對調（案例登記在前、累犯決策紀錄在後），對稱切片也不會把合法五欄決策列誤判為壞行
    reversed_sections = HEAD + row(1, fn="F5") + "\n## 累犯決策紀錄\n\n" + good_dec
    parsed_rev = self.mod.parse(reversed_sections, TODAY)
    self.assertEqual(parsed_rev.bad, [])
    self.assertEqual(len(parsed_rev.decisions), 1)
    self.assertEqual(len(parsed_rev.rows), 1)

    # 在讀取與替換之間（before_write）模擬外部 Edit 原子替換插入新決策列，inode 變更觸發重讀重算，新決策列零遺失
    concurrent_new_dec = f"{d1} | F5.2 | open | ref=trial-concurrent | 並發 Edit 插入的新決策列\n"
    initial_doc = HEAD.replace("## 案例登記", "## 累犯決策紀錄（回流機制追加區）\n\n" + good_dec + "\n---\n\n## 案例登記") + row(1, fn="F5")
    self.tax.write_text(initial_doc)
    injected = {"done": False}
    def concurrent_edit(_):
      if not injected["done"]:
        injected["done"] = True
        updated = self.tax.read_text().replace(good_dec, good_dec + concurrent_new_dec)
        tmp_edit = self.tax.with_suffix(".edit-tmp")
        tmp_edit.write_text(updated)
        tmp_edit.replace(self.tax)
    rep, wrote = self.mod.run(self.tax, TODAY, before_write=concurrent_edit)
    self.assertTrue(wrote)
    self.assertIn("inode 已變，重讀後重算", rep)
    final_txt = self.tax.read_text()
    self.assertIn(good_dec, final_txt)
    self.assertIn(concurrent_new_dec, final_txt)

  def test_fmd_001_symlink_taxonomy_is_preserved_and_target_updated(self):
    real_dir = Path(self.tmp.name) / "real_dir"
    link_dir = Path(self.tmp.name) / "link_dir"
    real_dir.mkdir()
    link_dir.mkdir()
    real_tax = real_dir / "real-taxonomy.md"
    link_tax = link_dir / "link-taxonomy.md"
    real_tax.write_text(HEAD + row(1) + row(2, fn="F2"))
    link_tax.symlink_to(real_tax)

    report, wrote = self.mod.run(link_tax, TODAY)
    self.assertTrue(wrote, report)
    self.assertTrue(link_tax.is_symlink())
    self.assertEqual(link_tax.resolve(), real_tax.resolve())
    expected_hdr = f"> 近 30 天最常漏：F1（1）、F2（1）｜更新 {TODAY.isoformat()}"
    self.assertIn(expected_hdr, real_tax.read_text())

  def test_fmd_002_crlf_taxonomy_inserts_updates_and_skips_without_false_conflict(self):
    crlf_content = (HEAD + row(1) + row(2, fn="F2")).replace("\n", "\r\n")
    self.tax.write_bytes(crlf_content.encode("utf-8"))

    report, wrote = self.mod.run(self.tax, TODAY)
    self.assertTrue(wrote, report)
    self.assertNotIn("放棄本日檔首改寫", report)
    raw_after_first = self.tax.read_bytes()
    text_after_first = raw_after_first.decode("utf-8")
    self.assertNotIn("\n", text_after_first.replace("\r\n", ""))
    lines = text_after_first.splitlines()
    hdr = f"> 近 30 天最常漏：F1（1）、F2（1）｜更新 {TODAY.isoformat()}"
    self.assertIn(hdr, lines)
    self.assertLess(lines.index(hdr), lines.index("---"))

    # 第二次無變更重跑：應判斷未變且不重寫、維持 CRLF
    report2, wrote2 = self.mod.run(self.tax, TODAY)
    self.assertFalse(wrote2, report2)
    self.assertIn("檔首行內容未變，未寫入", report2)
    self.assertEqual(self.tax.read_bytes(), raw_after_first)

    # 追加新案例改變 top-2 后重跑：應原地更新檔首並維持 CRLF
    self.tax.write_bytes((text_after_first + row(0, fn="F5").replace("\n", "\r\n") + row(0, fn="F5").replace("\n", "\r\n")).encode("utf-8"))
    report3, wrote3 = self.mod.run(self.tax, TODAY)
    self.assertTrue(wrote3, report3)
    text_after_third = self.tax.read_bytes().decode("utf-8")
    self.assertNotIn("\n", text_after_third.replace("\r\n", ""))
    self.assertIn(f"> 近 30 天最常漏：F5（2）、F1（1）｜更新 {TODAY.isoformat()}", text_after_third.splitlines())

  def test_fmd_003_atomic_write_exception_cleans_up_temp_file(self):
    self.tax.write_text(HEAD + row(1))
    with self.assertRaises(FileNotFoundError):
      self.mod.run(self.tax, TODAY, before_write=lambda _: self.tax.unlink())
    self.assertEqual(list(self.tax.parent.glob(".fmd-*")), [])

  def test_fmd_004_reviewed_text_inside_symptom_column_not_misclassified(self):
    d1 = (TODAY - timedelta(days=1)).isoformat()
    line_unreviewed = f"{d1} | Failure-miss | F1 | shop | t1 | 檢查 [reviewed ...] 漏判 → 失敗 | implement-review\n"
    line_reviewed = f"{d1} | Failure-miss | F2 | shop | t2 | 檢查 [reviewed ...] 漏判 → 失敗 | implement-review [reviewed {d1} 不改 probe=F2.1]\n"
    line_extra_cols = f"{d1} | Failure-miss | F1 | shop | t3 | c → s | implement-review | extra-col\n"
    parsed = self.mod.parse(HEAD + line_unreviewed + line_reviewed + line_extra_cols, TODAY)
    self.assertEqual(parsed.bad, [line_extra_cols.strip()])
    self.assertEqual(len(parsed.rows), 2)
    self.assertFalse(parsed.rows[0].reviewed)
    self.assertTrue(parsed.rows[1].reviewed)
    self.assertEqual(parsed.rows[1].probe, "F2.1")

  def test_fmd_005_no_rule_and_no_trailing_newline_inserts_clean_header_once(self):
    d1 = (TODAY - timedelta(days=1)).isoformat()
    no_rule_doc = f"## 案例登記\n{d1} | Failure-miss | F1 | shop | t1 | c → s | implement-review"
    self.tax.write_text(no_rule_doc)

    report1, wrote1 = self.mod.run(self.tax, TODAY)
    self.assertTrue(wrote1, report1)
    text1 = self.tax.read_text()
    parsed1 = self.mod.parse(text1, TODAY)
    self.assertEqual(parsed1.bad, [])
    self.assertEqual(len(parsed1.rows), 1)
    self.assertEqual(parsed1.rows[0].found_at, "implement-review")
    self.assertEqual(sum(1 for l in text1.splitlines() if l.startswith("> 近 30 天最常漏")), 1)

    report2, wrote2 = self.mod.run(self.tax, TODAY)
    self.assertFalse(wrote2, report2)
    self.assertEqual(self.tax.read_text(), text1)

  def test_fmd_006_empty_repo_ref_symptom_or_found_at_goes_to_bad(self):
    d1 = (TODAY - timedelta(days=1)).isoformat()
    empty_repo = f"{d1} | Failure-miss | F1 |  | t1 | c → s | implement-review\n"
    empty_ref = f"{d1} | Failure-miss | F1 | shop |  | c → s | implement-review\n"
    empty_symptom = f"{d1} | Failure-miss | F1 | shop | t1 |  | implement-review\n"
    empty_found_at = f"{d1} | Failure-miss | F1 | shop | t1 | c → s |  [reviewed {d1} 不改]\n"
    parsed = self.mod.parse(HEAD + empty_repo + empty_ref + empty_symptom + empty_found_at, TODAY)
    self.assertEqual(parsed.rows, [])
    self.assertEqual(parsed.bad, [empty_repo.strip(), empty_ref.strip(), empty_symptom.strip(), empty_found_at.strip()])

  def test_fmd_007_hash_pr_missing_date_goes_to_bad_while_atx_heading_skipped(self):
    bad_hash_pr = "#353 | Failure-miss | F1 | saas | PR #353 | 條件 → 症狀 | pr-review\n"
    heading_with_pipe = "### 小節 | 說明\n"
    parsed = self.mod.parse(HEAD + heading_with_pipe + bad_hash_pr, TODAY)
    self.assertEqual(parsed.rows, [])
    self.assertEqual(parsed.bad, [bad_hash_pr.strip()])

  def test_fmd_add_001_and_mut_09_cli_backfill_yesterday_allows_later_valid_rows_and_never_writes_header(self):
    yesterday = TODAY - timedelta(days=1)
    d_old = (TODAY - timedelta(days=2)).isoformat()
    d_today = TODAY.isoformat()
    d_future = (TODAY + timedelta(days=10)).isoformat()
    doc = (
      HEAD.replace("## 案例登記", "## 累犯決策紀錄\n\n" + f"{d_today} | F1.1 | open | ref=trial-today | 今日決策\n" + "\n---\n\n## 案例登記")
      + f"{d_old} | Failure-miss | F1 | shop | t-old | c → s | implement-review [reviewed {d_old} 不改]\n"
      + f"{d_today} | Failure-miss | F2 | shop | t-today | c → s | implement-review [reviewed {d_today} 不改]\n"
      + f"{d_future} | Failure-miss | F3 | shop | t-future | 未來錯字 → 應入壞行 | implement-review\n"
    )
    self.tax.write_text(doc)
    before_bytes = self.tax.read_bytes()

    p = subprocess.run(
      [sys.executable, str(SCRIPT), "--taxonomy", str(self.tax), "--date", yesterday.isoformat(), "--out", str(self.out)],
      capture_output=True,
      text=True,
    )
    self.assertEqual(p.returncode, 0, p.stderr)
    self.assertEqual(self.tax.read_bytes(), before_bytes)
    self.assertIsNone(self.header_line())

    out = self.out.read_text()
    self.assertIn("--date 早於今天，只算不改檔首", out)
    self.assertIn("| F1 | 1 | 0 |", out)
    self.assertNotIn("| F2 |", out)
    self.assertNotIn("t-today", out)
    self.assertNotIn("今日決策", out)
    self.assertIn("t-future", out)

    # 若拿掉未來錯字列，昨日之前皆已審時應回傳 __SILENT__（且仍不改寫檔首）
    doc_clean = doc.replace(f"{d_future} | Failure-miss | F3 | shop | t-future | 未來錯字 → 應入壞行 | implement-review\n", "")
    self.tax.write_text(doc_clean)
    before_clean_bytes = self.tax.read_bytes()
    p2 = subprocess.run(
      [sys.executable, str(SCRIPT), "--taxonomy", str(self.tax), "--date", yesterday.isoformat(), "--out", str(self.out)],
      capture_output=True,
      text=True,
    )
    self.assertEqual(p2.returncode, 0, p2.stderr)
    self.assertEqual(self.tax.read_bytes(), before_clean_bytes)
    self.assertEqual(self.out.read_text().strip(), "__SILENT__")

  def test_fmd_add_002_empty_probe_or_mode_kv_goes_to_bad(self):
    d1 = (TODAY - timedelta(days=1)).isoformat()
    empty_probe = f"{d1} | Failure-miss | F1 | shop | t1 | c → s | implement-review [reviewed {d1} 自動 probe= mode=auto-verified]\n"
    empty_mode = f"{d1} | Failure-miss | F1 | shop | t2 | c → s | implement-review [reviewed {d1} 自動 probe=F1.1 mode=]\n"
    parsed = self.mod.parse(HEAD + empty_probe + empty_mode, TODAY)
    self.assertEqual(parsed.rows, [])
    self.assertEqual(parsed.bad, [empty_probe.strip(), empty_mode.strip()])

  def test_mut_03_06_10_same_day_decision_boundary_none_probe_and_unbalanced_brackets(self):
    # MUT-03: lo == dec.day 的工作單不計入新單（1 單同日 + 4 單決策日後 => 4 單 < 5 不升級）
    dec_day = TODAY - timedelta(days=5)
    after_day = TODAY - timedelta(days=2)
    dec_doc = (
      HEAD.replace("## 案例登記", f"## 累犯決策紀錄\n\n{dec_day.isoformat()} | F2.1 | deferred | ref=N-A | 暫緩觀察\n\n---\n\n## 案例登記")
      + f"{dec_day.isoformat()} | Failure-miss | F2 | shop | same-day-1 | c → s | implement-review [reviewed {dec_day.isoformat()} 自動 probe=F2.1 mode=auto-verified]\n"
      + "".join(
        f"{after_day.isoformat()} | Failure-miss | F2 | shop | after-{k} | c → s | implement-review [reviewed {after_day.isoformat()} 自動 probe=F2.1 mode=auto-verified]\n"
        for k in range(1, 5)
      )
    )
    cands, totals = self.mod.escalation_candidates(self.mod.parse(dec_doc, TODAY), TODAY)
    self.assertEqual(totals["F2.1"], 5)
    self.assertEqual(cands, [])

    # MUT-06: probe=none 絕不進全窗細項統計或升級候選
    none_rows = "".join(
      f"{after_day.isoformat()} | Failure-miss | F1 | shop | none-{k} | c → s | implement-review [reviewed {after_day.isoformat()} 自動 probe=none mode=auto-verified]\n"
      for k in range(1, 7)
    )
    self.tax.write_text(HEAD + none_rows)
    out_none = self.run_cli()
    self.assertEqual(out_none.strip(), "__SILENT__")
    none_cands, none_totals = self.mod.escalation_candidates(self.mod.parse(HEAD + none_rows, TODAY), TODAY)
    self.assertEqual(none_cands, [])
    self.assertNotIn("none", none_totals)

    # MUT-10: 結尾為 ] 但內部方括號不平衡的壞尾碼必須進 parsed.bad
    d1 = (TODAY - timedelta(days=1)).isoformat()
    unbalanced_open = f"{d1} | Failure-miss | F1 | shop | b1 | c → s | implement-review [reviewed {d1} [unclosed]\n"
    unbalanced_close_first = f"{d1} | Failure-miss | F1 | shop | b2 | c → s | implement-review [reviewed {d1} A] junk [B]\n"
    parsed_brackets = self.mod.parse(HEAD + unbalanced_open + unbalanced_close_first, TODAY)
    self.assertEqual(parsed_brackets.rows, [])
    self.assertEqual(parsed_brackets.bad, [unbalanced_open.strip(), unbalanced_close_first.strip()])



if __name__ == "__main__":
  unittest.main()
