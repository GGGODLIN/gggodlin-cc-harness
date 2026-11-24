#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


HOOK = Path(__file__).with_name("herdr-worker-stop-gate.sh")


class HerdrWorkerStopGateTest(unittest.TestCase):
  def setUp(self):
    self.temp = tempfile.TemporaryDirectory()
    self.addCleanup(self.temp.cleanup)
    self.root = Path(self.temp.name)
    self.bin = self.root / "bin"
    self.bin.mkdir()
    self.state_dir = self.root / "state"
    self.state_dir.mkdir(mode=0o700)
    self.log_dir = self.root / "logs"
    self.log_dir.mkdir(mode=0o700)
    self.audit_log = self.log_dir / "herdr-worker-stop-gate.jsonl"
    self.lg_dir = self.state_dir / "herdr-worker-stop-loopguard"
    self.ps_file = self.root / "ps.txt"
    self.ps_file.write_text("", encoding="utf-8")
    self.ps_eww_file = self.root / "ps-eww.txt"
    self.ps_eww_file.write_text("", encoding="utf-8")
    self.hc_ls_file = self.root / "hc-ls.json"
    self.hc_status_file = self.root / "hc-status.json"
    self.hc_status_file.write_text(json.dumps({"running": True, "state": "running"}), encoding="utf-8")
    self.install_fake_hc()

  def install_fake_hc(self):
    hc = self.bin / "fake-hc"
    hc.write_text(
      """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
if args[:2] == ["server", "status"]:
  if os.environ.get("FAKE_HC_STATUS_FAIL") == "1":
    sys.exit(1)
  print(Path(os.environ["FAKE_HC_STATUS_FILE"]).read_text())
  sys.exit(0)
if args[:1] == ["ls"]:
  if os.environ.get("FAKE_HC_LS_FAIL") == "1":
    sys.exit(1)
  raw = Path(os.environ["FAKE_HC_LS_FILE"]).read_text()
  if "--label" in args:
    if os.environ.get("FAKE_HC_LABEL_LS_FAIL") == "1":
      sys.exit(1)
    idx = args.index("--label")
    wanted = args[idx + 1] if idx + 1 < len(args) else ""
    k, _, v = wanted.partition("=")
    try:
      data = json.loads(raw)
    except ValueError:
      print(raw)
      sys.exit(0)
    if isinstance(data, dict) and isinstance(data.get("terminals"), list):
      matched = [
        t for t in data["terminals"]
        if isinstance(t, dict) and isinstance(t.get("labels"), dict) and t["labels"].get(k) == v
      ]
      print(json.dumps({"terminals": matched}))
      sys.exit(0)
  print(raw)
  sys.exit(0)
sys.exit(2)
""",
      encoding="utf-8",
    )
    hc.chmod(0o755)
    self.hc = hc

  def write_terminals(self, terminals):
    self.hc_ls_file.write_text(json.dumps({"terminals": terminals}), encoding="utf-8")

  def run_gate(self, payload=None, *, parent="t10", ps_lines=None, ps_eww_lines=None, extra_env=None):
    if ps_lines is not None:
      self.ps_file.write_text("\n".join(ps_lines) + "\n", encoding="utf-8")
    if ps_eww_lines is not None:
      self.ps_eww_file.write_text("\n".join(ps_eww_lines) + "\n", encoding="utf-8")
    body = payload if payload is not None else {
      "hook_event_name": "Stop",
      "session_id": "sess-main-1",
      "last_assistant_message": "目前已整理完進度，稍後再繼續。",
    }
    env = {
      k: v for k, v in os.environ.items()
      if not k.startswith(("HERDR_", "HC_"))
    }
    env.update({
      "HC_BIN": str(self.hc),
      "FAKE_HC_LS_FILE": str(self.hc_ls_file),
      "FAKE_HC_STATUS_FILE": str(self.hc_status_file),
      "HERDR_STOP_GATE_STATE_DIR": str(self.state_dir),
      "HERDR_STOP_GATE_AUDIT_LOG": str(self.audit_log),
      "HERDR_STOP_GATE_LOOPGUARD_DIR": str(self.lg_dir),
      "HERDR_STOP_GATE_PS_FILE": str(self.ps_file),
      "HERDR_STOP_GATE_PS_EWW_FILE": str(self.ps_eww_file),
    })
    if parent is not None:
      env["HC_TERMINAL_ID"] = parent
    if extra_env:
      env.update(extra_env)
    return subprocess.run(
      ["bash", str(HOOK)],
      input=json.dumps(body, ensure_ascii=False),
      env=env,
      capture_output=True,
      text=True,
      timeout=5,
    )

  # --- 1. Known-good cases ---
  def test_known_good_non_herdr_fast_exits_zero(self):
    self.write_terminals([{"address": "t11", "parent": "t10", "state": "live", "agent": "claude-code", "status": "done", "turn": 1}])
    res = self.run_gate(parent=None)
    self.assertEqual(res.returncode, 0)
    self.assertEqual(res.stdout.strip(), "")

  def test_known_good_subagent_stop_is_exempt(self):
    self.write_terminals([{"address": "t11", "parent": "t10", "state": "live", "agent": "claude-code", "status": "done", "turn": 1}])
    res = self.run_gate({
      "hook_event_name": "Stop",
      "session_id": "sess-main-1",
      "agent_id": "subagent-123",
      "last_assistant_message": "完成子任務。",
    })
    self.assertEqual(res.returncode, 0)
    self.assertEqual(res.stdout.strip(), "")

  def test_known_good_working_child_with_live_watcher_allows_stop(self):
    self.write_terminals([
      {"address": "t149", "name": "worker-frontend", "parent": "t10", "state": "live", "agent": "claude-code", "status": "working", "turn": 3},
      {"address": "t78", "name": "dev-server", "parent": "t10", "state": "live", "agent": "npm", "turn": 0},
    ])
    res = self.run_gate(ps_lines=[
      "90001 bash ~/.claude/skills/agent-dispatch/scripts/agent-watch.sh herdr-core worker-frontend t10 /tmp/w.log uuid /tmp main-uuid t149"
    ])
    self.assertEqual(res.returncode, 0)
    self.assertEqual(res.stdout.strip(), "")

  def test_known_good_done_child_waiting_on_bg_test_with_live_watcher_allows_stop(self):
    self.write_terminals([
      {"address": "t149", "name": "worker-frontend", "parent": "t10", "state": "live", "agent": "claude-code", "status": "done", "turn": 2},
    ])
    res = self.run_gate(ps_lines=[
      "90002 bash ~/.claude/skills/agent-dispatch/scripts/agent-watch.sh herdr-core worker-frontend t10 /tmp/w.log uuid /tmp main-uuid t149"
    ])
    self.assertEqual(res.returncode, 0)
    self.assertEqual(res.stdout.strip(), "")

  def test_known_good_asking_human_question_allows_stop_without_deadlock(self):
    self.write_terminals([
      {"address": "t149", "name": "worker-frontend", "parent": "t10", "state": "live", "agent": "claude-code", "status": "idle", "turn": 1},
    ])
    for msg in (
      "小兵問了一個範圍問題。\n\n### 待拍板\n- 選項 A：保留\n- 選項 B：刪除",
      "請問你要選 A 還是 B？",
    ):
      res = self.run_gate({
        "hook_event_name": "Stop",
        "session_id": "sess-main-1",
        "last_assistant_message": msg,
      })
      self.assertEqual(res.returncode, 0)
      self.assertEqual(res.stdout.strip(), "")

  # --- 2. Known-bad cases ---
  def test_known_bad_working_child_without_watcher_blocks(self):
    self.write_terminals([
      {"address": "t149", "name": "worker-frontend", "parent": "t10", "state": "live", "agent": "claude-code", "status": "working", "turn": 3},
    ])
    res = self.run_gate(ps_lines=[])
    self.assertEqual(res.returncode, 0)
    out = json.loads(res.stdout)
    self.assertEqual(out["decision"], "block")
    self.assertIn("t149", out["reason"])
    self.assertIn("無活著的 agent-watch.sh", out["reason"])

  def test_known_bad_stopped_child_or_exited_shell_blocks(self):
    self.write_terminals([
      {"address": "t148", "name": "worker-backend", "parent": "t10", "state": "live", "agent": "codex", "status": "done", "turn": 4},
      {"address": "t150", "name": "crashed-worker", "parent": "t10", "state": "live", "agent": "zsh", "turn": 1},
    ])
    res = self.run_gate(ps_lines=[])
    out = json.loads(res.stdout)
    self.assertEqual(out["decision"], "block")
    self.assertIn("t148", out["reason"])
    self.assertIn("t150", out["reason"])
    self.assertIn("已退回 zsh", out["reason"])

  # --- 3. Boundary & sanitization cases ---
  def test_boundary_watcher_for_other_worker_does_not_cover_unwatched_worker_and_strips_bidi(self):
    self.write_terminals([
      {"address": "t148", "name": "saas", "parent": "t10", "state": "live", "agent": "codex", "status": "working", "turn": 2},
      {"address": "t149", "name": "dash‮\x1b[31m-evil", "parent": "t10", "state": "live", "agent": "claude-code", "status": "working", "turn": 2},
    ])
    res = self.run_gate(ps_lines=[
      "90010 bash /path/to/agent-watch.sh herdr-core saas t10 /tmp/s.log uuid /tmp main t148",
      # Code fence in last_assistant_message with a question mark must NOT trigger human-question exemption
    ], payload={
      "hook_event_name": "Stop",
      "session_id": "sess-main-1",
      "last_assistant_message": "進度更新：\n```\nwhy did it fail?\n```\n我先休息。",
    })
    out = json.loads(res.stdout)
    self.assertEqual(out["decision"], "block")
    self.assertNotIn("t148", out["reason"])
    self.assertIn("t149", out["reason"])
    self.assertNotIn("‮", out["reason"])
    self.assertNotIn("\x1b", out["reason"])

  def test_loop_guard_releases_after_same_state_limit_and_resets_when_clean(self):
    self.write_terminals([
      {"address": "t149", "name": "dash", "parent": "t10", "state": "live", "agent": "claude-code", "status": "done", "turn": 2},
    ])
    env = {"HERDR_STOP_GATE_LOOPGUARD_SAME": "2", "HERDR_STOP_GATE_LOOPGUARD_TOTAL": "5"}
    r1 = json.loads(self.run_gate(extra_env=env).stdout)
    r2 = json.loads(self.run_gate(extra_env=env).stdout)
    self.assertEqual(r1["decision"], "block")
    self.assertEqual(r2["decision"], "block")
    # 3rd identical state exceeds same=2 -> releases!
    r3 = self.run_gate(extra_env=env)
    self.assertEqual(r3.stdout.strip(), "")
    # Reset check: paired positive/negative — another session's guard file stays untouched while this session resets
    other_guard = self.lg_dir / "other-session.json"
    other_guard.write_text('{"state":"x","same":1,"total":1}', encoding="utf-8")
    _ = self.run_gate(extra_env=env)
    self.assertTrue((self.lg_dir / "sess-main-1.json").exists())
    self.write_terminals([])
    clean = self.run_gate(extra_env=env)
    self.assertEqual(clean.stdout.strip(), "")
    self.assertFalse((self.lg_dir / "sess-main-1.json").exists())
    self.assertEqual(other_guard.read_text(encoding="utf-8"), '{"state":"x","same":1,"total":1}')

  # --- 4. Self-lifecycle (bootstrap / update / recovery) + pathological write targets ---
  def test_lifecycle_bootstrap_recovery_sentinel_and_stopped_daemon(self):
    # Bootstrap with non-existent state/log subdirectories
    fresh_state = self.root / "fresh-state"
    fresh_log = self.root / "fresh-logs" / "audit.jsonl"
    self.write_terminals([
      {"address": "t149", "name": "dash", "parent": "t10", "state": "live", "agent": "claude-code", "status": "done", "turn": 1},
    ])
    boot = self.run_gate(extra_env={
      "HERDR_STOP_GATE_STATE_DIR": str(fresh_state),
      "HERDR_STOP_GATE_LOOPGUARD_DIR": str(fresh_state / "lg"),
      "HERDR_STOP_GATE_AUDIT_LOG": str(fresh_log),
    })
    self.assertEqual(json.loads(boot.stdout)["decision"], "block")
    self.assertTrue(fresh_log.is_file())

    # Recovery via disabled sentinel
    sentinel = self.state_dir / "herdr-worker-stop-gate.disabled"
    sentinel.write_text("manual disable\n", encoding="utf-8")
    rec = self.run_gate()
    self.assertEqual(rec.returncode, 0)
    self.assertEqual(rec.stdout.strip(), "")
    self.assertIn("disabled", rec.stderr)
    sentinel.unlink()

    # Stopped Herdr server never blocks Stop or starts daemon
    self.hc_status_file.write_text(json.dumps({"running": False, "state": "stopped"}), encoding="utf-8")
    down = self.run_gate()
    self.assertEqual(down.returncode, 0)
    self.assertEqual(down.stdout.strip(), "")

  def test_pathological_symlink_hardlink_and_fifo_targets_never_clobber_or_hang(self):
    bystander = self.root / "bystander.txt"
    bystander.write_text("DO_NOT_TOUCH", encoding="utf-8")
    self.write_terminals([
      {"address": "t149", "name": "dash", "parent": "t10", "state": "live", "agent": "claude-code", "status": "done", "turn": 1},
    ])

    # 1) Symlink audit log + symlink loopguard file
    self.lg_dir.mkdir(mode=0o700, exist_ok=True)
    sym_log = self.root / "sym.jsonl"
    sym_log.symlink_to(bystander)
    (self.lg_dir / "sess-main-1.json").symlink_to(bystander)
    r_sym = self.run_gate(extra_env={"HERDR_STOP_GATE_AUDIT_LOG": str(sym_log)})
    self.assertEqual(r_sym.returncode, 0)
    self.assertEqual(bystander.read_text(encoding="utf-8"), "DO_NOT_TOUCH")
    (self.lg_dir / "sess-main-1.json").unlink()

    # 2) Hardlink audit log + hardlink loopguard file
    hl_log = self.root / "hl.jsonl"
    os.link(bystander, hl_log)
    os.link(bystander, self.lg_dir / "sess-main-1.json")
    r_hl = self.run_gate(extra_env={"HERDR_STOP_GATE_AUDIT_LOG": str(hl_log)})
    self.assertEqual(r_hl.returncode, 0)
    self.assertEqual(bystander.read_text(encoding="utf-8"), "DO_NOT_TOUCH")
    (self.lg_dir / "sess-main-1.json").unlink()
    hl_log.unlink()

    # 3) FIFO (named pipe with zero readers) on audit log and loopguard file — must NOT block!
    fifo_log = self.root / "fifo.jsonl"
    os.mkfifo(fifo_log)
    os.mkfifo(self.lg_dir / "sess-main-1.json")
    r_fifo = self.run_gate(extra_env={"HERDR_STOP_GATE_AUDIT_LOG": str(fifo_log)})
    self.assertEqual(r_fifo.returncode, 0)
    self.assertEqual(bystander.read_text(encoding="utf-8"), "DO_NOT_TOUCH")

  def test_registered_once_in_settings_stop_hooks(self):
    settings = json.loads((HOOK.parents[1] / "settings.json").read_text(encoding="utf-8"))
    hooks = settings.get("hooks", {})
    stop_cmds = [h.get("command", "") for row in hooks.get("Stop", []) for h in row.get("hooks", [])]
    self.assertEqual(sum("herdr-worker-stop-gate.sh" in cmd for cmd in stop_cmds), 1)
    for event, rows in hooks.items():
      if event == "Stop":
        continue
      self.assertFalse(any("herdr-worker-stop-gate.sh" in h.get("command", "") for row in rows for h in row.get("hooks", [])))

  # --- 5. New-path seat_dispatch=v2 release conditions & wait attribution ---
  def v2_seat(self, addr="t201", name="task-verifier-abc", status="working", agent="pi", turn=1):
    return {
      "address": addr,
      "name": name,
      "parent": "t10",
      "state": "live",
      "agent": agent,
      "status": status,
      "turn": turn,
      "labels": {"seat_dispatch": "v2", "seat_id": "task-verifier"},
    }

  def test_v2_open_seat_without_wait_or_question_blocks_and_closed_seat_releases(self):
    self.write_terminals([self.v2_seat(status="working")])
    res = self.run_gate(ps_lines=[], ps_eww_lines=[])
    self.assertEqual(res.returncode, 0)
    out = json.loads(res.stdout)
    self.assertEqual(out["decision"], "block")
    self.assertIn("t201", out["reason"])
    self.assertNotIn("agent-watch.sh", out["reason"], "新路子席不應要求掛 agent-watch.sh")

    # 關掉後（不再是 live child）放行
    self.write_terminals([])
    closed = self.run_gate(ps_lines=[], ps_eww_lines=[])
    self.assertEqual(closed.returncode, 0)
    self.assertEqual(closed.stdout.strip(), "")

  def test_v2_asking_human_releases_keeping_seat_open(self):
    self.write_terminals([self.v2_seat(status="done")])
    res = self.run_gate(
      payload={
        "hook_event_name": "Stop",
        "session_id": "sess-main-1",
        "last_assistant_message": "子席回報需要決定方向，請問要選 A 還是 B？",
      },
      ps_lines=[],
      ps_eww_lines=[],
    )
    self.assertEqual(res.returncode, 0)
    self.assertEqual(res.stdout.strip(), "")

  def test_v2_attributable_single_seat_wait_releases_working_but_rejects_children_any_and_done(self):
    self.write_terminals([self.v2_seat(addr="t201", status="working")])
    # 歸屬成立：同 HC_TERMINAL_ID + 同 CLAUDE_CODE_SESSION_ID + argv 指定 t201
    ok = self.run_gate(
      ps_lines=["81001 hc wait t201 --timeout 300 --json"],
      ps_eww_lines=["81001 hc wait t201 --timeout 300 --json HC_TERMINAL_ID=t10 CLAUDE_CODE_SESSION_ID=sess-main-1"],
    )
    self.assertEqual(ok.returncode, 0)
    self.assertEqual(ok.stdout.strip(), "", "可歸屬的單席等待應放行 working 新路子席")

    # --children any 無法歸屬單席，不得放行
    any_wait = self.run_gate(
      ps_lines=["81002 hc wait --children any --timeout 300 --json"],
      ps_eww_lines=["81002 hc wait --children any --timeout 300 --json HC_TERMINAL_ID=t10 CLAUDE_CODE_SESSION_ID=sess-main-1"],
    )
    self.assertEqual(json.loads(any_wait.stdout)["decision"], "block")

    # 已停下（done）的新路子席即使有殘留 wait 也不放行，必須收件或關席
    self.write_terminals([self.v2_seat(addr="t201", status="done")])
    done_res = self.run_gate(
      ps_lines=["81001 hc wait t201 --timeout 300 --json"],
      ps_eww_lines=["81001 hc wait t201 --timeout 300 --json HC_TERMINAL_ID=t10 CLAUDE_CODE_SESSION_ID=sess-main-1"],
    )
    self.assertEqual(json.loads(done_res.stdout)["decision"], "block")

  def test_v2_wait_from_other_main_or_switched_session_on_same_terminal_never_releases(self):
    self.write_terminals([self.v2_seat(addr="t201", status="working")])
    cases = [
      ("other_main_terminal", "82001 hc wait t201 --timeout 300 --json HC_TERMINAL_ID=t99 CLAUDE_CODE_SESSION_ID=sess-other"),
      ("same_terminal_old_session", "82002 hc wait t201 --timeout 300 --json HC_TERMINAL_ID=t10 CLAUDE_CODE_SESSION_ID=sess-old"),
      ("missing_session_id_env", "82003 hc wait t201 --timeout 300 --json HC_TERMINAL_ID=t10"),
      ("other_seat_target", "82004 hc wait t202 --timeout 300 --json HC_TERMINAL_ID=t10 CLAUDE_CODE_SESSION_ID=sess-main-1"),
    ]
    for label, eww_line in cases:
      with self.subTest(case=label):
        pid_cmd = eww_line.split(" HC_TERMINAL_ID=")[0]
        res = self.run_gate(
          payload={
            "hook_event_name": "Stop",
            "session_id": f"sess-main-{label}",
            "last_assistant_message": "目前已整理完進度，稍後再繼續。",
          },
          ps_lines=[pid_cmd],
          ps_eww_lines=[eww_line.replace("sess-main-1", f"sess-main-{label}")],
        )
        out = json.loads(res.stdout)
        self.assertEqual(out["decision"], "block", f"{label} 不得放行")

  def test_v2_and_old_path_coexist_with_isolated_conditions(self):
    old_worker = {"address": "t149", "name": "old-dash", "parent": "t10", "state": "live", "agent": "claude-code", "status": "working", "turn": 2}
    new_seat = self.v2_seat(addr="t201", name="task-verifier-1", status="working")
    self.write_terminals([old_worker, new_seat])

    # 舊路有 agent-watch.sh、新路有可歸屬 hc wait → 兩席皆放行
    both_ok = self.run_gate(
      ps_lines=[
        "90001 bash /path/agent-watch.sh herdr-core old-dash t10 /tmp/w.log uuid /tmp main t149",
        "90002 hc wait t201 --timeout 300 --json",
      ],
      ps_eww_lines=[
        "90002 hc wait t201 --timeout 300 --json HC_TERMINAL_ID=t10 CLAUDE_CODE_SESSION_ID=sess-main-1",
      ],
    )
    self.assertEqual(both_ok.stdout.strip(), "")

    # 舊路只有 hc wait、沒有 agent-watch.sh → 舊路仍被攔（不混用新路條件）
    old_needs_watcher = self.run_gate(
      ps_lines=[
        "90003 hc wait t149 --timeout 300 --json",
        "90002 hc wait t201 --timeout 300 --json",
      ],
      ps_eww_lines=[
        "90003 hc wait t149 --timeout 300 --json HC_TERMINAL_ID=t10 CLAUDE_CODE_SESSION_ID=sess-main-1",
        "90002 hc wait t201 --timeout 300 --json HC_TERMINAL_ID=t10 CLAUDE_CODE_SESSION_ID=sess-main-1",
      ],
    )
    out = json.loads(old_needs_watcher.stdout)
    self.assertEqual(out["decision"], "block")
    self.assertIn("t149", out["reason"])
    self.assertNotIn("t201", out["reason"])

  def test_v2_malformed_hc_ls_or_label_query_failure_keeps_old_behavior(self):
    # 缺欄位或型別不對的 terminal 不崩潰、不多攔或多放
    self.write_terminals([
      {"address": None, "parent": "t10", "state": "live"},
      {"address": "t205", "parent": "t10", "state": "live", "agent": "pi", "status": {"state": 123}, "turn": "bad"},
      {"address": "t149", "name": "old-dash", "parent": "t10", "state": "live", "agent": "claude-code", "status": "done", "turn": 1},
    ])
    res = self.run_gate(extra_env={"FAKE_HC_LABEL_LS_FAIL": "1"}, ps_lines=[], ps_eww_lines=[])
    self.assertEqual(res.returncode, 0)
    out = json.loads(res.stdout)
    self.assertEqual(out["decision"], "block")
    self.assertIn("t149", out["reason"])
    self.assertNotIn("t205", out["reason"])

  def test_v2_review_hardening_unreported_status_blocks_and_non_hc_exe_rejected(self):
    # v2 子席剛開出 status=None 尚未回報，無可歸屬等待必攔；有可歸屬等待才放
    self.write_terminals([self.v2_seat(addr="t209", status=None)])
    blocked = self.run_gate(ps_lines=[], ps_eww_lines=[])
    self.assertEqual(json.loads(blocked.stdout)["decision"], "block")
    self.assertIn("t209", json.loads(blocked.stdout)["reason"])

    # 非 hc 執行檔（如 grep hc wait t209）或 eww 快照指令不符，一律不放行
    spoof = self.run_gate(
      payload={"hook_event_name": "Stop", "session_id": "sess-spoof", "last_assistant_message": "結束。"},
      ps_lines=[
        "83001 grep hc wait t209",
        "83002 hc wait t209 --timeout 300 --json",
      ],
      ps_eww_lines=[
        "83001 grep hc wait t209 HC_TERMINAL_ID=t10 CLAUDE_CODE_SESSION_ID=sess-spoof",
        "83002 sleep 300 HC_TERMINAL_ID=t10 CLAUDE_CODE_SESSION_ID=sess-spoof",
      ],
    )
    self.assertEqual(json.loads(spoof.stdout)["decision"], "block")

    # 合法 hc wait t209 且同快照重核通過 → 放行
    ok = self.run_gate(
      payload={"hook_event_name": "Stop", "session_id": "sess-ok", "last_assistant_message": "結束。"},
      ps_lines=["83003 ~/.local/bin/hc wait t209 --timeout 300 --json"],
      ps_eww_lines=["83003 ~/.local/bin/hc wait t209 --timeout 300 --json HC_TERMINAL_ID=t10 CLAUDE_CODE_SESSION_ID=sess-ok"],
    )
    self.assertEqual(ok.stdout.strip(), "")


if __name__ == "__main__":
  unittest.main()
