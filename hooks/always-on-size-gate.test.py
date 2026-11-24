#!/usr/bin/env python3
"""always-on-size-gate.py 自動化測試套件（全數隔離於 TemporaryDirectory）。"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


HOOK = Path(__file__).with_name("always-on-size-gate.py")
BIDI_CONTROL_RE = re.compile(
  r"[\x00-\x09\x0b-\x1f\x7f-\x9f؜‎‏‪-‮⁦-⁩﻿]"
)


class AlwaysOnSizeGateTest(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.base = Path(self.tmp.name)
    self.claude_home = self.base / "claude-home"
    self.claude_home.mkdir()
    (self.claude_home / "rules" / "common").mkdir(parents=True)
    (self.claude_home / "rules" / "external").mkdir(parents=True)
    (self.claude_home / "hooks" / "state").mkdir(parents=True)
    (self.claude_home / "logs").mkdir(parents=True)
    self.project = self.base / "project"
    self.project.mkdir()
    self.session_id = f"test-session-{os.getpid()}-{id(self)}"

  def tearDown(self):
    self.tmp.cleanup()

  def log_path(self) -> Path:
    return self.claude_home / "logs" / "always-on-size-gate.jsonl"

  def read_logs(self) -> list[dict]:
    p = self.log_path()
    if not p.exists():
      return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line]

  def run_hook(
    self,
    payload: dict,
    *,
    env_overrides: dict[str, str] | None = None,
    claude_home: Path | None = None,
    timeout: float = 5.0,
  ) -> dict:
    env = os.environ.copy()
    for key in list(env):
      if key.startswith("ALWAYS_ON_SIZE_GATE_"):
        del env[key]
    env["ALWAYS_ON_SIZE_GATE_CLAUDE_HOME"] = str(claude_home or self.claude_home)
    if env_overrides:
      env.update(env_overrides)
    result = subprocess.run(
      [sys.executable, str(HOOK)],
      input=json.dumps(payload, ensure_ascii=False),
      capture_output=True,
      text=True,
      env=env,
      timeout=timeout,
      check=False,
    )
    self.assertEqual(0, result.returncode, f"stderr={result.stderr!r}")
    return json.loads(result.stdout or "{}")

  def run_write(self, file_path: Path | str, content: str, **kwargs) -> dict:
    return self.run_hook(
      {
        "session_id": self.session_id,
        "cwd": str(self.base),
        "tool_name": "Write",
        "tool_input": {"file_path": str(file_path), "content": content},
      },
      **kwargs,
    )

  def run_edit(
    self,
    file_path: Path | str,
    old_string: str,
    new_string: str,
    *,
    replace_all: bool = False,
    **kwargs,
  ) -> dict:
    return self.run_hook(
      {
        "session_id": self.session_id,
        "cwd": str(self.base),
        "tool_name": "Edit",
        "tool_input": {
          "file_path": str(file_path),
          "old_string": old_string,
          "new_string": new_string,
          "replace_all": replace_all,
        },
      },
      **kwargs,
    )

  def run_multiedit(
    self, file_path: Path | str, edits: list[dict], **kwargs
  ) -> dict:
    return self.run_hook(
      {
        "session_id": self.session_id,
        "cwd": str(self.base),
        "tool_name": "MultiEdit",
        "tool_input": {"file_path": str(file_path), "edits": edits},
      },
      **kwargs,
    )

  def assert_denied(self, output: dict) -> str:
    self.assertIn("hookSpecificOutput", output, output)
    specific = output["hookSpecificOutput"]
    self.assertEqual("PreToolUse", specific["hookEventName"])
    self.assertEqual("deny", specific["permissionDecision"])
    reason = specific["permissionDecisionReason"]
    self.assertIn("[always-on-size-gate]", reason)
    return reason

  # --- known-good ---

  def test_non_scope_files_and_other_tools_allowed(self):
    (self.claude_home / "rules" / "typescript").mkdir(parents=True)
    (self.claude_home / "references").mkdir(parents=True)
    (self.claude_home / "memory").mkdir(parents=True)
    (self.claude_home / "rules" / "common" / "nested").mkdir(parents=True)

    non_scope = [
      self.project / "README.md",
      self.claude_home / "rules" / "typescript" / "ts.md",
      self.claude_home / "references" / "big.md",
      self.claude_home / "memory" / "MEMORY.md",
      self.claude_home / "rules" / "common" / "notes.txt",
      self.claude_home / "rules" / "common" / "nested" / "sub.md",
    ]
    huge = "x" * 60000
    for path in non_scope:
      with self.subTest(path=path):
        self.assertEqual({}, self.run_write(path, huge))

    read_payload = {
      "session_id": self.session_id,
      "tool_name": "Read",
      "tool_input": {"file_path": str(self.claude_home / "CLAUDE.md")},
    }
    self.assertEqual({}, self.run_hook(read_payload))
    self.assertEqual([], self.read_logs())

  def test_within_cap_net_increase_allowed(self):
    claude_md = self.claude_home / "CLAUDE.md"
    claude_md.write_bytes(b"a" * 1000)
    self.assertEqual({}, self.run_edit(claude_md, "a" * 10, "b" * 110))

    common_rule = self.claude_home / "rules" / "common" / "r.md"
    self.assertEqual({}, self.run_write(common_rule, "c" * 5000))

    ext_rule = self.claude_home / "rules" / "external" / "e.md"
    self.assertEqual({}, self.run_write(ext_rule, "d" * 5000))

  def test_over_cap_but_negative_delta_allowed(self):
    claude_md = self.claude_home / "CLAUDE.md"
    claude_md.write_bytes(b"a" * 15000)
    self.assertEqual({}, self.run_write(claude_md, "a" * 14900))
    self.assertEqual({}, self.run_edit(claude_md, "a" * 50, "b" * 10))
    self.assertEqual(
      {},
      self.run_multiedit(
        claude_md,
        [
          {"old_string": "a" * 100, "new_string": "b" * 20},
          {"old_string": "b" * 20, "new_string": "c" * 10},
        ],
      ),
    )

    # 總量超 46080 但單檔減肥 → 仍應放行
    for i in range(5):
      (self.claude_home / "rules" / "common" / f"r{i}.md").write_bytes(b"z" * 9000)
    target = self.claude_home / "rules" / "common" / "r0.md"
    self.assertEqual({}, self.run_edit(target, "z" * 100, "y" * 99))

  def test_over_cap_but_zero_delta_allowed(self):
    claude_md = self.claude_home / "CLAUDE.md"
    claude_md.write_bytes(b"abcd" + b"x" * 14996)
    self.assertEqual({}, self.run_write(claude_md, "efgh" + "x" * 14996))
    self.assertEqual({}, self.run_edit(claude_md, "abcd", "efgh"))
    # UTF-8 等 byte 替換：3 個 ASCII (3B) 換 1 個中文字 (3B)
    self.assertEqual({}, self.run_edit(claude_md, "abc", "一"))
    # MultiEdit 先 +20 再 -20，淨增 = 0
    self.assertEqual(
      {},
      self.run_multiedit(
        claude_md,
        [
          {"old_string": "abcd", "new_string": "abcd" + "y" * 20},
          {"old_string": "x" * 20, "new_string": ""},
        ],
      ),
    )

  def test_valid_suppress_allows_and_audits(self):
    claude_md = self.claude_home / "CLAUDE.md"
    claude_md.write_bytes(b"base\n" + b"x" * 13990)

    out_write = self.run_write(
      claude_md, "<!-- size-gate-suppress: 緊急補上規則 -->\n" + "x" * 14500
    )
    self.assertEqual({}, out_write)

    out_edit = self.run_edit(
      claude_md,
      "base",
      "<!-- size-gate-suppress: hotfix -->\n" + "y" * 500,
    )
    self.assertEqual({}, out_edit)

    out_multi = self.run_multiedit(
      claude_md,
      [
        {"old_string": "base", "new_string": "base2"},
        {"old_string": "xxxx", "new_string": "<!-- size-gate-suppress: 緊急修補 -->" + "z" * 400},
      ],
    )
    self.assertEqual({}, out_multi)

    logs = self.read_logs()
    self.assertEqual(3, len(logs))
    for row in logs:
      self.assertEqual("suppressed", row["status"])
      self.assertTrue(len(row["reason"]) >= 4)

  # --- known-bad ---

  def test_claude_md_over_cap_denied_with_cache_friendly_message(self):
    claude_md = self.claude_home / "CLAUDE.md"
    claude_md.write_bytes(b"hello " + b"x" * 13900)

    reason = self.assert_denied(self.run_write(claude_md, "x" * 14001))
    self.assertIn("~/.claude/references/", reason)
    self.assertIn("size-gate-suppress:", reason)
    # 穩定說明文字在前、動態 bytes 與路徑在尾（prompt cache 擺位）
    self.assertLess(reason.index("兩條正路"), reason.index("詳情："))
    self.assertLess(reason.index("size-gate-suppress:"), reason.index("post=14001B"))

    reason_edit = self.assert_denied(self.run_edit(claude_md, "hello", "hello" + "z" * 200))
    self.assertIn("file_cap(14106>14000)", reason_edit)

    logs = self.read_logs()
    self.assertEqual(2, len(logs))
    self.assertEqual("deny", logs[0]["status"])

  def test_rules_common_and_external_over_cap_denied(self):
    common_rule = self.claude_home / "rules" / "common" / "c.md"
    common_rule.write_bytes(b"a" * 9700)
    reason_c = self.assert_denied(self.run_write(common_rule, "a" * 9729))
    self.assertIn("rules/common", reason_c)
    self.assertIn("9729>9728", reason_c)

    ext_rule = self.claude_home / "rules" / "external" / "e.md"
    ext_rule.write_bytes(b"b" * 9700)
    reason_e = self.assert_denied(self.run_write(ext_rule, "b" * 9729))
    self.assertIn("rules/external", reason_e)
    self.assertIn("9729>9728", reason_e)

  def test_total_cap_over_denied_even_when_file_within_cap(self):
    (self.claude_home / "CLAUDE.md").write_bytes(b"a" * 12000)
    for i in range(3):
      (self.claude_home / "rules" / "common" / f"r{i}.md").write_bytes(b"b" * 9000)
    # 12000 + 27000 = 39000；寫入 external/ext.md 8000 (< 9728) → 總量 47000 > 46080
    ext = self.claude_home / "rules" / "external" / "ext.md"
    reason = self.assert_denied(self.run_write(ext, "c" * 8000))
    self.assertIn("total_cap(47000>46080)", reason)
    self.assertNotIn("file_cap(", reason)

  def test_multiedit_cumulative_over_cap_denied(self):
    rule = self.claude_home / "rules" / "common" / "m.md"
    rule.write_bytes(b"part1\npart2\n" + b"x" * 9600)
    # 每筆單看只加 65 bytes，合計 +130 bytes → 9742 > 9728
    output = self.run_multiedit(
      rule,
      [
        {"old_string": "part1", "new_string": "part1" + "a" * 65},
        {"old_string": "part2", "new_string": "part2" + "b" * 65},
      ],
    )
    reason = self.assert_denied(output)
    self.assertIn("post=9742B", reason)

  def test_blank_short_symbol_control_suppress_still_denied(self):
    claude_md = self.claude_home / "CLAUDE.md"
    claude_md.write_bytes(b"x" * 13900)
    bad_suppresses = [
      "<!-- size-gate-suppress: -->",
      "<!-- size-gate-suppress:    -->",
      "<!-- size-gate-suppress: abc -->",
      "<!-- size-gate-suppress: 理由三 -->",
      "<!-- size-gate-suppress: !@#$%^&* -->",
      "<!-- size-gate-suppress: \x1b[31m‮   -->",
      "size-gate-suppress: \nnext line has many words",
    ]
    for marker in bad_suppresses:
      with self.subTest(marker=marker):
        content = marker + "\n" + ("y" * 14500)
        self.assert_denied(self.run_write(claude_md, content))

  def test_symlink_bypass_paths_still_caught(self):
    claude_md = self.claude_home / "CLAUDE.md"
    claude_md.write_bytes(b"x" * 13990)

    # 1) 外部 symlink 指向 CLAUDE.md
    alias = self.project / "innocent-notes.md"
    alias.symlink_to(claude_md)
    self.assert_denied(self.run_write(alias, "y" * 14050))

    # 2) CLAUDE_HOME 本身為 symlink farm
    farm = self.base / "claude-farm"
    farm.symlink_to(self.claude_home)
    self.assert_denied(
      self.run_write(farm / "CLAUDE.md", "z" * 14050, claude_home=farm)
    )

    # 3) rules/common 內 symlink 指向外部檔
    outside = self.project / "outside-rule.md"
    outside.write_bytes(b"o" * 9700)
    inside_link = self.claude_home / "rules" / "common" / "linked.md"
    inside_link.symlink_to(outside)
    self.assert_denied(self.run_write(inside_link, "o" * 9729))

  def test_in_scope_fail_closed_on_malformed_input_or_bad_cap(self):
    claude_md = self.claude_home / "CLAUDE.md"
    claude_md.write_bytes(b"ok")

    # 缺 content
    self.assert_denied(
      self.run_hook(
        {
          "session_id": self.session_id,
          "tool_name": "Write",
          "tool_input": {"file_path": str(claude_md)},
        }
      )
    )
    # Edit 不存在於 scope 內的檔案
    self.assert_denied(
      self.run_edit(self.claude_home / "rules" / "common" / "missing.md", "a", "b")
    )
    # cap env 損毀：scope 內 fail-closed deny，非 scope 仍秒放行
    self.assert_denied(
      self.run_write(
        claude_md,
        "small",
        env_overrides={"ALWAYS_ON_SIZE_GATE_TOTAL_CAP": "broken"},
      )
    )
    self.assertEqual(
      {},
      self.run_write(
        self.project / "other.md",
        "small",
        env_overrides={"ALWAYS_ON_SIZE_GATE_TOTAL_CAP": "broken"},
      ),
    )

  # --- 邊界案例 ---

  def test_exact_cap_allowed_and_plus_one_denied(self):
    claude_md = self.claude_home / "CLAUDE.md"
    self.assertEqual({}, self.run_write(claude_md, "a" * 14000))
    self.assert_denied(self.run_write(claude_md, "a" * 14001))

    common_rule = self.claude_home / "rules" / "common" / "edge.md"
    self.assertEqual({}, self.run_write(common_rule, "b" * 9728))
    self.assert_denied(self.run_write(common_rule, "b" * 9729))

    ext_rule = self.claude_home / "rules" / "external" / "edge.md"
    self.assertEqual({}, self.run_write(ext_rule, "c" * 9728))
    self.assert_denied(self.run_write(ext_rule, "c" * 9729))

    # Total 邊界：46080 放行，46081 攔截
    claude_md.write_bytes(b"a" * 10000)
    for i in range(4):
      (self.claude_home / "rules" / "common" / f"t{i}.md").write_bytes(b"b" * 9000)
    # 現有 10000 + 36000 = 46000
    tail = self.claude_home / "rules" / "external" / "tail.md"
    self.assertEqual({}, self.run_write(tail, "c" * 80))
    self.assert_denied(self.run_write(tail, "c" * 81))

  def test_edit_replace_all_true_and_false(self):
    rule = self.claude_home / "rules" / "common" / "rep.md"
    # 5 個 "TOKEN"（25B）+ 9695B = 9720B
    rule.write_bytes(b"TOKEN" * 5 + b"x" * 9695)
    # replace_all=False: 只換 1 個 (+2B -> 9722B <= 9728B) → 放行
    self.assertEqual(
      {}, self.run_edit(rule, "TOKEN", "TOKEN12", replace_all=False)
    )
    # replace_all=True: 換 5 個 (+10B -> 9730B > 9728B) → 攔截
    reason = self.assert_denied(
      self.run_edit(rule, "TOKEN", "TOKEN12", replace_all=True)
    )
    self.assertIn("post=9730B", reason)

  def test_edit_old_string_not_found_allows_and_logs(self):
    claude_md = self.claude_home / "CLAUDE.md"
    claude_md.write_bytes(b"a" * 14500)
    self.assertEqual({}, self.run_edit(claude_md, "NOT_IN_FILE", "longer" * 100))
    logs = self.read_logs()
    self.assertEqual(1, len(logs))
    self.assertEqual("edit_noop_allow", logs[0]["status"])

  def test_new_rule_file_over_total_cap_denied(self):
    (self.claude_home / "CLAUDE.md").write_bytes(b"a" * 10080)
    for i in range(4):
      (self.claude_home / "rules" / "common" / f"n{i}.md").write_bytes(b"b" * 9000)
    # 現有總量 = 46080，新建 1 byte 規則檔即超總量
    new_rule = self.claude_home / "rules" / "common" / "brand-new.md"
    reason = self.assert_denied(self.run_write(new_rule, "x"))
    self.assertIn("total_cap(46081>46080)", reason)

  def test_utf8_multibyte_count(self):
    rule = self.claude_home / "rules" / "common" / "utf8.md"
    # 10 chars / 10 bytes + 9718 bytes = 9728 bytes
    rule.write_bytes(b"abcdefghij" + b"x" * 9718)
    # 10 chars -> 4 個中文字（字元數變少，但 UTF-8 為 12 bytes，總量變成 9730 > 9728）
    reason = self.assert_denied(self.run_edit(rule, "abcdefghij", "一二三四"))
    self.assertIn("post=9730B", reason)

  # --- 自身生命週期 ---

  def test_self_lifecycle_gate_and_test_edits_allowed(self):
    gate_copy = self.claude_home / "hooks" / "always-on-size-gate.py"
    test_copy = self.claude_home / "hooks" / "always-on-size-gate.test.py"
    huge = "# " + ("a" * 50000)
    self.assertEqual({}, self.run_write(gate_copy, huge))
    self.assertEqual({}, self.run_write(test_copy, huge))

  def test_disabled_sentinel_file_and_symlink_bypass(self):
    claude_md = self.claude_home / "CLAUDE.md"
    claude_md.write_bytes(b"x" * 13990)
    sentinel = self.claude_home / "hooks" / "state" / "always-on-size-gate.disabled"

    # 1) 一般 sentinel 檔
    sentinel.write_text("manual pause", encoding="utf-8")
    self.assertEqual({}, self.run_write(claude_md, "y" * 20000))
    sentinel.unlink()

    # 2) broken symlink sentinel
    sentinel.symlink_to(self.base / "nonexistent-target")
    self.assertEqual({}, self.run_write(claude_md, "y" * 20000))

    logs = self.read_logs()
    self.assertEqual(2, len(logs))
    self.assertEqual(["disabled_bypass", "disabled_bypass"], [r["status"] for r in logs])

  def test_disabled_env_var_bypass(self):
    claude_md = self.claude_home / "CLAUDE.md"
    claude_md.write_bytes(b"x" * 13990)
    out = self.run_write(
      claude_md,
      "y" * 20000,
      env_overrides={"ALWAYS_ON_SIZE_GATE_DISABLE": "1"},
    )
    self.assertEqual({}, out)
    logs = self.read_logs()
    self.assertEqual(1, len(logs))
    self.assertEqual("disabled_bypass", logs[0]["status"])

  # --- 旁路與安全強制 ---

  def test_side_files_untouched_by_hook_runs(self):
    claude_md = self.claude_home / "CLAUDE.md"
    common_a = self.claude_home / "rules" / "common" / "a.md"
    other = self.project / "unrelated.md"
    claude_md.write_bytes(b"CLAUDE_ORIG_" + b"x" * 13900)
    common_a.write_bytes(b"COMMON_ORIG_" + b"y" * 9000)
    other.write_bytes(b"PROJECT_ORIG")

    before = {
      claude_md: claude_md.read_bytes(),
      common_a: common_a.read_bytes(),
      other: other.read_bytes(),
    }

    self.assert_denied(self.run_write(claude_md, "z" * 20000))
    self.assertEqual({}, self.run_edit(claude_md, "CLAUDE_ORIG_", "CLAUDE_NEW__"))
    self.assertEqual(
      {},
      self.run_write(
        common_a, "<!-- size-gate-suppress: test bypass -->\n" + ("w" * 12000)
      ),
    )

    for path, expected in before.items():
      self.assertEqual(expected, path.read_bytes(), f"mutated {path}")

  def test_log_target_pathological_symlink_hardlink_fifo(self):
    claude_md = self.claude_home / "CLAUDE.md"
    claude_md.write_bytes(b"x" * 13900)

    victim = self.base / "victim.txt"
    victim.write_text("UNCHANGED", encoding="utf-8")
    log_file = self.log_path()

    # 1) symlink 到既有目標
    log_file.symlink_to(victim)
    self.assert_denied(self.run_write(claude_md, "y" * 15000))
    self.assertEqual("UNCHANGED", victim.read_text(encoding="utf-8"))
    log_file.unlink()

    # 2) dangling symlink
    dangling = self.base / "never-created.jsonl"
    log_file.symlink_to(dangling)
    self.assert_denied(self.run_write(claude_md, "y" * 15000))
    self.assertFalse(dangling.exists())
    log_file.unlink()

    # 3) hard link 到既有目標 (st_nlink == 2)
    os.link(victim, log_file)
    self.assert_denied(self.run_write(claude_md, "y" * 15000))
    self.assertEqual("UNCHANGED", victim.read_text(encoding="utf-8"))
    log_file.unlink()

    # 4) 無 reader 的 FIFO：不可卡死（timeout 內結束且仍正常回傳 deny）
    os.mkfifo(log_file)
    self.assert_denied(self.run_write(claude_md, "y" * 15000, timeout=2.0))

  def test_control_and_bidi_sanitization(self):
    claude_md = self.claude_home / "CLAUDE.md"
    claude_md.write_bytes(b"x" * 13900)

    # 先取得乾淨基線長度
    clean_reason = self.assert_denied(self.run_write(claude_md, "y" * 15000))

    # 透過含控制碼與 bidi 的 symlink 名稱與 session_id 觸發 deny
    evil_link = self.project / "evil-\x1b[31m-‮-⁦-\x07.md"
    evil_link.symlink_to(claude_md)
    dirty_reason = self.assert_denied(
      self.run_hook(
        {
          "session_id": "sess-\x1b[31m-‮-123",
          "tool_name": "Write",
          "tool_input": {"file_path": str(evil_link), "content": "y" * 15000},
        }
      )
    )
    self.assertIsNone(BIDI_CONTROL_RE.search(dirty_reason), dirty_reason)
    self.assertNotIn("\x1b", dirty_reason)
    self.assertNotIn("[31m", dirty_reason)
    self.assertGreaterEqual(len(dirty_reason), int(len(clean_reason) * 0.9))

    # 含控制碼/bidi 的有效 suppress 寫入 audit log 也必須被淨化且非空
    self.assertEqual(
      {},
      self.run_hook(
        {
          "session_id": "sess-‮\x1b[32m-abc",
          "tool_name": "Write",
          "tool_input": {
            "file_path": str(claude_md),
            "content": "<!-- size-gate-suppress: \x1b[31m‮緊急修補⁩ -->\n" + ("y" * 15000),
          },
        }
      ),
    )
    logs = self.read_logs()
    suppressed = [row for row in logs if row["status"] == "suppressed"]
    self.assertEqual(1, len(suppressed))
    self.assertNotIn("\x1b", suppressed[0]["reason"])
    self.assertNotIn("[31m", suppressed[0]["reason"])
    self.assertIsNone(BIDI_CONTROL_RE.search(suppressed[0]["reason"]))
    self.assertIn("緊急修補", suppressed[0]["reason"])
    self.assertIsNone(BIDI_CONTROL_RE.search(suppressed[0]["session_id"]))

  # --- 發現 9 & 發現 10 補強測試 ---

  def test_write_cannot_reuse_existing_suppress_reason(self):
    claude_md = self.claude_home / "CLAUDE.md"
    old_marker = "<!-- size-gate-suppress: 舊理由四字以上 -->"
    claude_md.write_text(old_marker + "\n" + ("x" * 13900), encoding="utf-8")

    # 1) 整檔 Write 淨增超標且沿用同一個舊理由（含空白微調）→ 必須 DENY
    self.assert_denied(
      self.run_write(
        claude_md,
        "<!-- size-gate-suppress:   舊理由四字以上   -->\n" + ("x" * 14500),
      )
    )

    # 2) 保留舊理由並新增一個新理由 → 放行且 log 記新理由
    self.assertEqual(
      {},
      self.run_write(
        claude_md,
        old_marker
        + "\n<!-- size-gate-suppress: 本次新增的緊急理由 -->\n"
        + ("x" * 14500),
      ),
    )

    # 3) 將舊理由改寫成新理由 → 放行且 log 記 suppressed
    self.assertEqual(
      {},
      self.run_write(
        claude_md,
        "<!-- size-gate-suppress: 改寫後的新緊急理由 -->\n" + ("x" * 14500),
      ),
    )

    # 4) 同一個舊理由出現次數從 1 次增加到 2 次 → 認列為新增次數並放行
    self.assertEqual(
      {},
      self.run_write(
        claude_md,
        old_marker + "\n" + old_marker + "\n" + ("x" * 14500),
      ),
    )

    logs = self.read_logs()
    self.assertEqual(
      ["deny", "suppressed", "suppressed", "suppressed"],
      [row["status"] for row in logs],
    )
    self.assertEqual("本次新增的緊急理由", logs[1]["reason"])
    self.assertEqual("改寫後的新緊急理由", logs[2]["reason"])
    self.assertEqual("舊理由四字以上", logs[3]["reason"])

  def test_shrink_and_same_bypass_total_scan_failure(self):
    claude_md = self.claude_home / "CLAUDE.md"
    claude_md.write_bytes(b"a" * 100)
    common_dir = self.claude_home / "rules" / "common"
    (common_dir / "other.md").write_bytes(b"b" * 50)

    os.chmod(common_dir, 0o000)
    try:
      # 對照：淨增 > 0 在掃描失敗時仍會 fail-closed error_deny
      self.assert_denied(self.run_write(claude_md, "a" * 101))

      # 減量 1 byte → 提前放行 {} 且不依賴總量掃描
      self.assertEqual({}, self.run_write(claude_md, "a" * 99))
      # 等長修改 → 提前放行 {} 且不依賴總量掃描
      self.assertEqual({}, self.run_write(claude_md, "b" * 100))
      # cap env 損毀下減量依然放行
      self.assertEqual(
        {},
        self.run_write(
          claude_md,
          "a" * 90,
          env_overrides={"ALWAYS_ON_SIZE_GATE_TOTAL_CAP": "broken"},
        ),
      )
    finally:
      os.chmod(common_dir, 0o755)

    logs = self.read_logs()
    self.assertEqual(
      ["error_deny", "allow_shrink", "allow_same", "allow_shrink"],
      [row["status"] for row in logs],
    )
    self.assertEqual(100, logs[1]["pre_bytes"])
    self.assertEqual(99, logs[1]["post_bytes"])
    self.assertEqual(-1, logs[1]["net_delta"])
    self.assertEqual(str(claude_md.resolve()), logs[1]["path"])
    self.assertIsNone(logs[1]["post_total"])

  def test_in_scope_allows_log_shrink_same_and_within_cap(self):
    claude_md = self.claude_home / "CLAUDE.md"
    claude_md.write_bytes(b"a" * 200)

    # 1) 減量
    self.assertEqual({}, self.run_write(claude_md, "a" * 180))
    # 2) 等長
    self.assertEqual({}, self.run_write(claude_md, "b" * 200))
    # 3) 未超標淨增
    self.assertEqual({}, self.run_write(claude_md, "c" * 250))
    # 4) 非受控檔案不留 log
    self.assertEqual({}, self.run_write(self.project / "outside.md", "z" * 100))

    logs = self.read_logs()
    self.assertEqual(3, len(logs))
    self.assertEqual(
      ["allow_shrink", "allow_same", "allow_within_cap"],
      [row["status"] for row in logs],
    )
    self.assertEqual(-20, logs[0]["net_delta"])
    self.assertEqual(0, logs[1]["net_delta"])
    self.assertEqual(50, logs[2]["net_delta"])
    self.assertEqual(250, logs[2]["post_total"])


if __name__ == "__main__":
  unittest.main()
