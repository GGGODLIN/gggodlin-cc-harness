#!/usr/bin/env python3
"""skill-verify-once-gate.py 的 fixture 回歸。

涵蓋 gate-authoring 第 3 條四件（known-good / known-bad / 邊界 / 自身生命週期）、
寫檔型 gate 的兩件必測（旁路未受影響 / state 目標病態），以及 worker brief 列的
最小 fixture 清單。每個 uncovered branch 也各有一件，斷言的是「目前放行」這個
已知缺口，改行為就會紅。
"""

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

GATE = Path(__file__).with_name("skill-verify-once-gate.py")

HUMAN = "11111111-1111-4111-8111-111111111111"
HUMAN2 = "22222222-2222-4222-8222-222222222222"
SESSION = "sess-fixture-0001"


def human_event(prompt_id, text="請跑 self-verify", source="typed"):
  event = {
    "type": "user",
    "promptId": prompt_id,
    "isSidechain": False,
    "origin": {"kind": "human"},
    "turnOrigin": "human",
    "userType": "external",
    "message": {"role": "user", "content": text},
  }
  if source:
    event["promptSource"] = source
  return event


def slash_event(prompt_id, name="/pr-review"):
  return {
    "type": "user",
    "promptId": prompt_id,
    "isSidechain": False,
    "origin": {"kind": "human"},
    "turnOrigin": "human",
    "userType": "external",
    "message": {
      "role": "user",
      "content": f"<command-message>{name.lstrip('/')}</command-message>\n<command-name>{name}</command-name>",
    },
  }


def tool_result_event(prompt_id):
  return {
    "type": "user",
    "promptId": prompt_id,
    "isSidechain": False,
    "toolUseResult": {"ok": True},
    "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call_x", "content": "done"}]},
  }


def task_notification_event(prompt_id):
  return {
    "type": "user",
    "promptId": prompt_id,
    "isSidechain": False,
    "origin": {"kind": "task-notification"},
    "turnOrigin": "task_notification",
    "promptSource": "system",
    "message": {"role": "user", "content": "<task-notification>agent done</task-notification>"},
  }


def skill_expansion_event(prompt_id):
  return {
    "type": "user",
    "promptId": prompt_id,
    "isSidechain": False,
    "isMeta": True,
    "turnCompanion": True,
    "sourceToolUseID": "call_skill",
    "message": {"role": "user", "content": "Base directory for this skill: /Users/x/.claude/skills/pr-review"},
  }


def sdk_event(prompt_id, text="headless task"):
  """實測形狀：claude -p 的 turn 沒有 origin 欄位，只有 turnOrigin/promptSource=sdk。"""
  return {
    "type": "user",
    "promptId": prompt_id,
    "isSidechain": False,
    "turnOrigin": "sdk",
    "promptSource": "sdk",
    "entrypoint": "sdk-cli",
    "message": {"role": "user", "content": text},
  }


def unknown_origin_event(prompt_id):
  return {
    "type": "user",
    "promptId": prompt_id,
    "isSidechain": False,
    "origin": {"kind": "some-future-source"},
    "message": {"role": "user", "content": "?"},
  }


def peer_event(prompt_id):
  return {
    "type": "user",
    "promptId": prompt_id,
    "isSidechain": False,
    "isMeta": True,
    "origin": {"kind": "peer"},
    "promptSource": "system",
    "message": {"role": "user", "content": "peer says hi"},
  }


def agent_input(skill="pr-review", where="description", extra=""):
  description = f"Self-Verify skill-verify:{skill}" if where == "description" else "Self-Verify audit"
  prompt = f"skill-verify:{skill}\nrubric..." if where == "prompt" else "rubric..."
  return {
    "description": description + extra,
    "prompt": prompt,
    "subagent_type": "skill-verify-auditor",
    "model": "sonnet",
  }


LAUNCH_OK = (
  "Async agent launched successfully. (This tool result is internal metadata.)\n"
  "agentId: aa13b6a50643a5236 (internal ID - do not mention to user.)\n"
)


class GateCase(unittest.TestCase):
  def setUp(self):
    self.tmp = Path(tempfile.mkdtemp(prefix="svo-test-"))
    self.runtime = self.tmp / "runtime"
    self.audit = self.tmp / "audit.jsonl"
    self.sentinel = self.tmp / "disabled"
    self.transcript = self.tmp / "transcript.jsonl"
    self.dispatch_seq = 0
    self.write_transcript([human_event(HUMAN)])

  def tearDown(self):
    shutil.rmtree(self.tmp, ignore_errors=True)

  def write_transcript(self, events):
    with self.transcript.open("w", encoding="utf-8") as handle:
      for event in events:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")

  def run_gate(self, mode, payload, env=None):
    environment = dict(os.environ)
    environment.update(
      {
        "SKILL_VERIFY_ONCE_RUNTIME_DIR": str(self.runtime),
        "SKILL_VERIFY_ONCE_AUDIT": str(self.audit),
        "SKILL_VERIFY_ONCE_DISABLED": str(self.sentinel),
      }
    )
    if env:
      environment.update(env)
    proc = subprocess.run(
      [sys.executable, str(GATE), mode],
      input=json.dumps(payload),
      capture_output=True,
      text=True,
      env=environment,
    )
    return proc

  def verdict(self, proc):
    self.assertEqual(proc.returncode, 0, proc.stderr)
    body = json.loads(proc.stdout or "{}")
    specific = body.get("hookSpecificOutput") or {}
    return specific.get("permissionDecision"), specific.get("permissionDecisionReason") or ""

  def agent_payload(
    self, tool_input=None, session=SESSION, transcript=None, tool_name="Agent", tool_use_id=None, agent_id=None, agent_type=None
  ):
    self.dispatch_seq += 1
    payload = {
      "session_id": session,
      "transcript_path": str(transcript or self.transcript),
      "tool_name": tool_name,
      "tool_use_id": tool_use_id or f"toolu_fixture{self.dispatch_seq:08d}",
      "tool_input": tool_input if tool_input is not None else agent_input(),
    }
    if agent_id is not None:
      payload["agent_id"] = agent_id
    if agent_type is not None:
      payload["agent_type"] = agent_type
    return payload

  def send_payload(self, target, session=SESSION):
    return {
      "session_id": session,
      "transcript_path": str(self.transcript),
      "tool_name": "SendMessage",
      "tool_input": {"to": target, "recipient": target, "message": "再驗一次", "summary": "recheck", "type": "agent"},
    }

  def claim_files(self):
    directory = self.runtime / SESSION
    return sorted(p.name for p in directory.glob("claim-*.json")) if directory.is_dir() else []


class QuotaLifecycle(GateCase):
  def test_first_attempt_claims_and_second_is_denied(self):
    first, _ = self.verdict(self.run_gate("pre-agent", self.agent_payload()))
    self.assertIsNone(first, "首次派工要走正常權限流程、不強制 allow")
    self.assertEqual(len(self.claim_files()), 1)

    second, reason = self.verdict(self.run_gate("pre-agent", self.agent_payload()))
    self.assertEqual(second, "deny")
    self.assertIn("額度已使用", reason)
    self.assertEqual(len(self.claim_files()), 1, "被拒的第二次不得覆寫或新增 claim")

  def test_same_tool_event_replay_is_idempotent(self):
    payload = self.agent_payload(tool_use_id="toolu_01SameEventReplay")
    self.assertIsNone(self.verdict(self.run_gate("pre-agent", payload))[0])
    replay, _ = self.verdict(self.run_gate("pre-agent", payload))
    self.assertIsNone(replay, "同一個 tool event 重放要冪等放行")
    self.assertEqual(len(self.claim_files()), 1)

  def test_identical_input_with_new_tool_use_id_is_still_denied(self):
    """第二次派工可以長得跟第一次一模一樣；分辨點只有 tool_use_id。"""
    self.assertIsNone(self.verdict(self.run_gate("pre-agent", self.agent_payload(tool_use_id="toolu_01First")))[0])
    verdict, _ = self.verdict(self.run_gate("pre-agent", self.agent_payload(tool_use_id="toolu_01Second")))
    self.assertEqual(verdict, "deny")

  def test_edited_draft_or_description_suffix_does_not_refund(self):
    self.assertIsNone(self.verdict(self.run_gate("pre-agent", self.agent_payload()))[0])
    for extra in (" (retry)", " — 已修正 draft", " v2"):
      verdict, _ = self.verdict(self.run_gate("pre-agent", self.agent_payload(agent_input(extra=extra))))
      self.assertEqual(verdict, "deny", f"改後綴 {extra!r} 不得重置額度")

  def test_concurrent_first_attempts_yield_exactly_one_claim(self):
    payloads = [self.agent_payload(agent_input(extra=f" #{i}")) for i in range(8)]
    with ThreadPoolExecutor(max_workers=8) as pool:
      results = list(pool.map(lambda p: self.verdict(self.run_gate("pre-agent", p))[0], payloads))
    self.assertEqual(results.count(None), 1, f"併發只能有一個 claim，實得 {results}")
    self.assertEqual(len(self.claim_files()), 1)

  def test_different_skill_in_same_turn_gets_its_own_quota(self):
    self.assertIsNone(self.verdict(self.run_gate("pre-agent", self.agent_payload(agent_input("pr-review"))))[0])
    other, _ = self.verdict(self.run_gate("pre-agent", self.agent_payload(agent_input("safe-trial"))))
    self.assertIsNone(other, "同一回合不同 skill 各有一次額度")
    self.assertEqual(len(self.claim_files()), 2)

  def test_new_human_turn_resets_quota(self):
    self.assertIsNone(self.verdict(self.run_gate("pre-agent", self.agent_payload()))[0])
    self.write_transcript([human_event(HUMAN), tool_result_event(HUMAN), human_event(HUMAN2, "再來一輪")])
    fresh, _ = self.verdict(self.run_gate("pre-agent", self.agent_payload()))
    self.assertIsNone(fresh, "新的真人回合要 reset 額度")
    self.assertEqual(len(self.claim_files()), 2)

  def test_human_slash_command_counts_as_a_turn(self):
    self.write_transcript([human_event(HUMAN), slash_event(HUMAN2)])
    self.assertIsNone(self.verdict(self.run_gate("pre-agent", self.agent_payload()))[0])
    self.assertEqual(self.verdict(self.run_gate("pre-agent", self.agent_payload()))[0], "deny")

  def test_headless_sdk_turn_gets_one_quota(self):
    """claude -p 沒有真人 turn；只認 human 會讓所有 headless 流程的 Self-Verify 全被 deny。"""
    self.write_transcript([sdk_event("aaaa1111-1111-4111-8111-111111111111")])
    self.assertIsNone(self.verdict(self.run_gate("pre-agent", self.agent_payload()))[0])
    self.assertEqual(self.verdict(self.run_gate("pre-agent", self.agent_payload()))[0], "deny")

  def test_new_sdk_turn_resets_quota(self):
    self.write_transcript([sdk_event("aaaa1111-1111-4111-8111-111111111111")])
    self.assertIsNone(self.verdict(self.run_gate("pre-agent", self.agent_payload()))[0])
    self.write_transcript(
      [sdk_event("aaaa1111-1111-4111-8111-111111111111"), sdk_event("bbbb2222-2222-4222-8222-222222222222")]
    )
    self.assertIsNone(self.verdict(self.run_gate("pre-agent", self.agent_payload()))[0])

  def test_unknown_origin_kind_is_not_a_turn_boundary(self):
    self.write_transcript([human_event(HUMAN), unknown_origin_event("cccc3333-3333-4333-8333-333333333333")])
    self.assertIsNone(self.verdict(self.run_gate("pre-agent", self.agent_payload()))[0])
    self.assertEqual(
      self.verdict(self.run_gate("pre-agent", self.agent_payload()))[0],
      "deny",
      "沒見過的 origin 種類不得被當成新回合",
    )

  def test_non_human_events_never_reset_quota(self):
    base = [human_event(HUMAN)]
    self.assertIsNone(self.verdict(self.run_gate("pre-agent", self.agent_payload()))[0])
    for label, event in (
      ("task notification", task_notification_event("99999999-9999-4999-8999-999999999999")),
      ("tool result", tool_result_event("88888888-8888-4888-8888-888888888888")),
      ("skill 展開", skill_expansion_event("77777777-7777-4777-8777-777777777777")),
      ("peer 訊息", peer_event("66666666-6666-4666-8666-666666666666")),
    ):
      base.append(event)
      self.write_transcript(base)
      verdict, _ = self.verdict(self.run_gate("pre-agent", self.agent_payload()))
      self.assertEqual(verdict, "deny", f"{label} 不得 reset 額度")

  def test_quota_is_spent_before_outcome_is_known(self):
    """PASS／FAIL／API error 都不退費：gate 在 PreToolUse 就消耗，之後不看結果。"""
    self.assertIsNone(self.verdict(self.run_gate("pre-agent", self.agent_payload()))[0])
    for response in (
      "VERDICT: COMPLIANT",
      "R1 FAIL\nVERDICT: VIOLATIONS: R1",
      "API Error: 500 internal",
    ):
      post = self.agent_payload()
      post["tool_response"] = response
      self.assertEqual(self.run_gate("post-agent", post).returncode, 0)
      self.assertEqual(self.verdict(self.run_gate("pre-agent", self.agent_payload()))[0], "deny")


SUB_A = "a17b1110ae87b4b51"
SUB_B = "a6865e3fb69a4f86a"


class CallerQuota(GateCase):
  """額度按 caller 分：main 一份、每個 subagent 各一份（2026-09-29 trial review 修正）。"""

  def verdict_for(self, **kwargs):
    return self.verdict(self.run_gate("pre-agent", self.agent_payload(**kwargs)))[0]

  def write_legacy_claim(self, attempt_id, prompt_id=HUMAN, skill="pr-review"):
    digest = hashlib.sha256("\x00".join((SESSION, prompt_id, skill)).encode()).hexdigest()
    directory = self.runtime / SESSION
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(self.runtime, 0o700)
    path = directory / f"claim-{digest}.json"
    record = {"version": 1, "session_id": SESSION, "prompt_id": prompt_id, "skill": skill, "attempt_id": attempt_id}
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as handle:
      json.dump(record, handle)
    return path

  def test_two_subagents_in_same_turn_each_get_one_quota(self):
    self.assertIsNone(self.verdict_for(agent_id=SUB_A, agent_type="routed-impl"))
    self.assertIsNone(self.verdict_for(agent_id=SUB_B, agent_type="routed-impl"), "另一個 subagent 的首次稽查不得被擋")
    self.assertEqual(len(self.claim_files()), 2)

  def test_same_subagent_second_attempt_is_denied(self):
    self.assertIsNone(self.verdict_for(agent_id=SUB_A))
    self.assertEqual(self.verdict_for(agent_id=SUB_A), "deny")

  def test_main_and_subagent_independent_in_both_orders(self):
    self.assertIsNone(self.verdict_for())
    self.assertIsNone(self.verdict_for(agent_id=SUB_A), "main 先用過不得擋 subagent")
    self.write_transcript([human_event(HUMAN), human_event(HUMAN2, "下一輪")])
    self.assertIsNone(self.verdict_for(agent_id=SUB_B))
    self.assertIsNone(self.verdict_for(), "subagent 先用過不得擋 main")
    self.assertEqual(self.verdict_for(), "deny", "main 自己的第二次仍要擋")

  def test_agent_type_only_main_shares_main_quota(self):
    self.assertIsNone(self.verdict_for())
    self.assertEqual(self.verdict_for(agent_type="advisor-seat"), "deny", "`--agent` 開的 main 只帶 agent_type，仍算 main")

  def test_empty_agent_id_counts_as_main(self):
    self.assertIsNone(self.verdict_for())
    self.assertEqual(self.verdict_for(agent_id=""), "deny")

  def test_malformed_agent_id_fails_closed_without_claiming(self):
    for bad in ("../etc", 12345, ["x"], "a" * 200):
      verdict = self.verdict(self.run_gate("pre-agent", self.agent_payload(agent_id=bad)))[0]
      self.assertEqual(verdict, "deny", f"壞掉的 agent_id {bad!r} 不得退回 main")
    self.assertEqual(self.claim_files(), [])
    self.assertIsNone(self.verdict_for(), "壞值被擋後，main 的額度仍完整")

  def test_new_claim_records_caller(self):
    self.assertIsNone(self.verdict_for(agent_id=SUB_A))
    [name] = self.claim_files()
    record = json.loads((self.runtime / SESSION / name).read_text())
    self.assertEqual(record["caller"], f"agent:{SUB_A}")
    audit = [json.loads(line) for line in self.audit.read_text().splitlines()]
    self.assertEqual(audit[-1]["caller"], f"agent:{SUB_A}")

  def test_legacy_claim_keeps_whole_turn_sharing_for_every_caller(self):
    self.write_legacy_claim("tool_use_id:toolu_legacy0001")
    self.assertEqual(self.verdict_for(), "deny", "部署前 main 已用過，升級不得重發額度")
    self.assertEqual(self.verdict_for(agent_id=SUB_A), "deny", "舊 claim 不知是誰建的，同回合一律照舊共用")

  def test_legacy_claim_same_attempt_is_replay(self):
    self.write_legacy_claim("tool_use_id:toolu_legacyReplay")
    self.assertIsNone(self.verdict_for(tool_use_id="toolu_legacyReplay"))

  def test_legacy_claim_does_not_affect_new_turn(self):
    self.write_legacy_claim("tool_use_id:toolu_legacy0002")
    self.write_transcript([human_event(HUMAN), human_event(HUMAN2, "新回合")])
    self.assertIsNone(self.verdict_for())
    self.assertIsNone(self.verdict_for(agent_id=SUB_A))

  def test_symlinked_legacy_claim_fails_closed(self):
    target = self.tmp / "elsewhere.json"
    target.write_text("{}")
    digest = hashlib.sha256("\x00".join((SESSION, HUMAN, "pr-review")).encode()).hexdigest()
    directory = self.runtime / SESSION
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(self.runtime, 0o700)
    (directory / f"claim-{digest}.json").symlink_to(target)
    self.assertEqual(self.verdict_for(), "deny")
    self.assertEqual(target.read_text(), "{}")


class FailClosed(GateCase):
  def test_missing_marker_is_denied(self):
    tool_input = {"description": "audit the draft", "prompt": "rubric", "subagent_type": "skill-verify-auditor"}
    verdict, reason = self.verdict(self.run_gate("pre-agent", self.agent_payload(tool_input)))
    self.assertEqual(verdict, "deny")
    self.assertIn("marker", reason)

  def test_ambiguous_marker_is_denied(self):
    tool_input = agent_input("pr-review")
    tool_input["prompt"] = "skill-verify:pr-review and skill-verify:safe-trial"
    self.assertEqual(self.verdict(self.run_gate("pre-agent", self.agent_payload(tool_input)))[0], "deny")

  def test_transcript_without_human_turn_is_denied(self):
    self.write_transcript([task_notification_event(HUMAN), tool_result_event(HUMAN)])
    verdict, reason = self.verdict(self.run_gate("pre-agent", self.agent_payload()))
    self.assertEqual(verdict, "deny")
    self.assertIn("回合邊界", reason)

  def test_missing_transcript_is_denied(self):
    payload = self.agent_payload(transcript=self.tmp / "nope.jsonl")
    self.assertEqual(self.verdict(self.run_gate("pre-agent", payload))[0], "deny")

  def test_unsafe_session_id_is_denied(self):
    self.assertEqual(self.verdict(self.run_gate("pre-agent", self.agent_payload(session="../escape")))[0], "deny")

  def test_invalid_json_input_is_denied(self):
    proc = subprocess.run(
      [sys.executable, str(GATE), "pre-agent"],
      input="not json",
      capture_output=True,
      text=True,
      env={**os.environ, "SKILL_VERIFY_ONCE_RUNTIME_DIR": str(self.runtime), "SKILL_VERIFY_ONCE_DISABLED": str(self.sentinel)},
    )
    self.assertEqual(self.verdict(proc)[0], "deny")

  def test_world_writable_runtime_root_is_denied(self):
    self.runtime.mkdir(parents=True)
    self.runtime.chmod(0o777)
    self.assertEqual(self.verdict(self.run_gate("pre-agent", self.agent_payload()))[0], "deny")


class StatePathology(GateCase):
  def test_symlinked_runtime_root_is_denied(self):
    real = self.tmp / "elsewhere"
    real.mkdir(mode=0o700)
    self.runtime.symlink_to(real)
    self.assertEqual(self.verdict(self.run_gate("pre-agent", self.agent_payload()))[0], "deny")
    self.assertEqual(list(real.iterdir()), [], "被拒時不得寫進 symlink 指向的目錄")

  def test_symlinked_claim_file_is_denied_and_target_untouched(self):
    self.assertIsNone(self.verdict(self.run_gate("pre-agent", self.agent_payload()))[0])
    name = self.claim_files()[0]
    path = self.runtime / SESSION / name
    bait = self.tmp / "bait.json"
    bait.write_text('{"version": 1, "keep": "me"}\n', encoding="utf-8")
    path.unlink()
    path.symlink_to(bait)
    self.assertEqual(self.verdict(self.run_gate("pre-agent", self.agent_payload()))[0], "deny")
    self.assertEqual(bait.read_text(encoding="utf-8"), '{"version": 1, "keep": "me"}\n', "旁路檔案不得被改寫")

  def test_hard_linked_claim_file_is_denied(self):
    self.assertIsNone(self.verdict(self.run_gate("pre-agent", self.agent_payload()))[0])
    path = self.runtime / SESSION / self.claim_files()[0]
    os.link(path, self.tmp / "hardlink.json")
    self.assertEqual(self.verdict(self.run_gate("pre-agent", self.agent_payload()))[0], "deny")

  def test_fifo_claim_file_does_not_hang(self):
    self.assertIsNone(self.verdict(self.run_gate("pre-agent", self.agent_payload()))[0])
    directory = self.runtime / SESSION
    path = directory / self.claim_files()[0]
    path.unlink()
    os.mkfifo(path, 0o600)
    proc = subprocess.run(
      [sys.executable, str(GATE), "pre-agent"],
      input=json.dumps(self.agent_payload()),
      capture_output=True,
      text=True,
      timeout=20,
      env={
        **os.environ,
        "SKILL_VERIFY_ONCE_RUNTIME_DIR": str(self.runtime),
        "SKILL_VERIFY_ONCE_AUDIT": str(self.audit),
        "SKILL_VERIFY_ONCE_DISABLED": str(self.sentinel),
      },
    )
    self.assertEqual(self.verdict(proc)[0], "deny")

  def test_fifo_audit_log_does_not_hang_or_block(self):
    os.mkfifo(self.audit, 0o600)
    proc = subprocess.run(
      [sys.executable, str(GATE), "pre-agent"],
      input=json.dumps(self.agent_payload()),
      capture_output=True,
      text=True,
      timeout=20,
      env={
        **os.environ,
        "SKILL_VERIFY_ONCE_RUNTIME_DIR": str(self.runtime),
        "SKILL_VERIFY_ONCE_AUDIT": str(self.audit),
        "SKILL_VERIFY_ONCE_DISABLED": str(self.sentinel),
      },
    )
    self.assertIsNone(self.verdict(proc)[0], "audit log 是 FIFO 時要靜默跳過、不阻斷判定")

  def test_symlinked_audit_log_leaves_target_untouched(self):
    bait = self.tmp / "audit-bait.txt"
    bait.write_text("original\n", encoding="utf-8")
    self.audit.symlink_to(bait)
    self.assertIsNone(self.verdict(self.run_gate("pre-agent", self.agent_payload()))[0])
    self.assertEqual(bait.read_text(encoding="utf-8"), "original\n")


def large_assistant_event():
  return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "x" * (4 * 1024 * 1024 + 8192)}]}}


def auditor_dispatch_events(agent_id, subagent_type="skill-verify-auditor", tool_use_id="toolu_dispatch01"):
  """transcript 裡一次 auditor 派工的 tool_use + tool_result 配對（實測形狀）。"""
  return [
    {
      "type": "assistant",
      "message": {
        "role": "assistant",
        "content": [
          {
            "type": "tool_use",
            "id": tool_use_id,
            "name": "Agent",
            "input": {"description": "skill-verify:pr-review", "prompt": "rubric", "subagent_type": subagent_type},
          }
        ],
      },
    },
    {
      "type": "user",
      "promptId": HUMAN,
      "message": {
        "role": "user",
        "content": [
          {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": [
              {
                "type": "text",
                "text": f"Async agent launched successfully.\nagentId: {agent_id} (internal ID)",
              }
            ],
          }
        ],
      },
    },
  ]


class SendMessageGate(GateCase):
  def register_auditor(self, response=LAUNCH_OK):
    payload = self.agent_payload()
    payload["tool_response"] = response
    self.assertEqual(self.run_gate("post-agent", payload).returncode, 0)

  def spend_quota(self):
    self.assertIsNone(self.verdict(self.run_gate("pre-agent", self.agent_payload()))[0])

  def test_recorded_auditor_id_is_denied(self):
    self.register_auditor()
    verdict, reason = self.verdict(self.run_gate("pre-sendmessage", self.send_payload("aa13b6a50643a5236")))
    self.assertEqual(verdict, "deny")
    self.assertIn("額度已使用", reason)

  def test_auditor_type_name_target_is_denied(self):
    verdict, _ = self.verdict(self.run_gate("pre-sendmessage", self.send_payload("skill-verify-auditor")))
    self.assertEqual(verdict, "deny", "用型別名當 target 也要擋，不需事先登記")

  def test_other_agent_traffic_is_allowed(self):
    self.register_auditor()
    for target in ("a99999999999999ff", "uds:/tmp/cc-socks/33208.sock", "routed-impl"):
      verdict, _ = self.verdict(self.run_gate("pre-sendmessage", self.send_payload(target)))
      self.assertIsNone(verdict, f"{target} 不是已登記 auditor，不得封鎖")

  def test_recipient_field_alone_is_still_checked(self):
    self.register_auditor()
    payload = self.send_payload("x")
    payload["tool_input"] = {"recipient": "aa13b6a50643a5236", "message": "再驗"}
    self.assertEqual(self.verdict(self.run_gate("pre-sendmessage", payload))[0], "deny")

  def test_new_human_turn_does_not_unblock_old_auditor(self):
    self.register_auditor()
    self.write_transcript([human_event(HUMAN), human_event(HUMAN2, "換個題目")])
    verdict, _ = self.verdict(self.run_gate("pre-sendmessage", self.send_payload("aa13b6a50643a5236")))
    self.assertEqual(verdict, "deny", "新回合可以派新 auditor，但不得續問舊的")

  def test_failed_launch_is_not_recorded(self):
    self.register_auditor("Error: agent failed to start\nagentId: aa13b6a50643a5236")
    self.assertIsNone(self.verdict(self.run_gate("pre-sendmessage", self.send_payload("aa13b6a50643a5236")))[0])

  def test_state_failure_fails_closed(self):
    self.runtime.mkdir(parents=True)
    self.runtime.chmod(0o777)
    verdict, reason = self.verdict(self.run_gate("pre-sendmessage", self.send_payload("a99999999999999ff")))
    self.assertEqual(verdict, "deny")
    self.assertIn("fail closed", reason)

  def test_transcript_launch_record_blocks_even_without_post_agent(self):
    """live known-bad 抓到的回歸：async 派工沒有 PostToolUse 登記時，仍要靠 transcript 擋。"""
    self.spend_quota()
    self.write_transcript([human_event(HUMAN)] + auditor_dispatch_events("ae95a7785bba53bf2"))
    verdict, _ = self.verdict(self.run_gate("pre-sendmessage", self.send_payload("ae95a7785bba53bf2")))
    self.assertEqual(verdict, "deny")

  def test_transcript_record_for_other_agent_type_is_not_blocked(self):
    self.spend_quota()
    self.write_transcript([human_event(HUMAN)] + auditor_dispatch_events("a1111111111111111", "deep-explore"))
    self.assertIsNone(self.verdict(self.run_gate("pre-sendmessage", self.send_payload("a1111111111111111")))[0])

  def test_session_without_any_verify_activity_never_blocks_sendmessage(self):
    """沒派過 Self-Verify 就沒有要保護的對象；transcript 壞掉也不得牽連其他 SendMessage。"""
    payload = self.send_payload("a99999999999999ff")
    payload["transcript_path"] = str(self.tmp / "gone.jsonl")
    self.assertIsNone(self.verdict(self.run_gate("pre-sendmessage", payload))[0])

  def test_unreadable_transcript_fails_closed_once_quota_was_spent(self):
    self.spend_quota()
    payload = self.send_payload("a99999999999999ff")
    payload["transcript_path"] = str(self.tmp / "gone.jsonl")
    verdict, reason = self.verdict(self.run_gate("pre-sendmessage", payload))
    self.assertEqual(verdict, "deny")
    self.assertIn("fail closed", reason)


class LongTranscript(GateCase):
  def test_first_audit_after_large_turn_is_allowed_but_second_is_denied(self):
    self.write_transcript([human_event(HUMAN), large_assistant_event(), task_notification_event(HUMAN2)])
    self.assertIsNone(self.verdict(self.run_gate("pre-agent", self.agent_payload()))[0])
    self.assertEqual(self.verdict(self.run_gate("pre-agent", self.agent_payload()))[0], "deny")
    self.assertEqual(len(self.claim_files()), 1)

  def test_old_auditor_is_still_protected_after_new_turn_and_large_output(self):
    self.assertIsNone(self.verdict(self.run_gate("pre-agent", self.agent_payload()))[0])
    self.write_transcript([human_event(HUMAN)] + auditor_dispatch_events("ae95a7785bba53bf2") + [human_event(HUMAN2), large_assistant_event()])
    self.assertEqual(self.verdict(self.run_gate("pre-sendmessage", self.send_payload("ae95a7785bba53bf2")))[0], "deny")
    self.assertIsNone(self.verdict(self.run_gate("pre-sendmessage", self.send_payload("a99999999999999ff")))[0])

  def test_auditor_pair_across_large_event_stays_protected(self):
    self.assertIsNone(self.verdict(self.run_gate("pre-agent", self.agent_payload()))[0])
    dispatch, result = auditor_dispatch_events("ae95a7785bba53bf2")
    self.write_transcript([human_event(HUMAN), dispatch, large_assistant_event(), result, human_event(HUMAN2)])
    self.assertEqual(self.verdict(self.run_gate("pre-sendmessage", self.send_payload("ae95a7785bba53bf2")))[0], "deny")

  def test_malformed_transcript_cannot_clear_old_auditor_identity(self):
    self.assertIsNone(self.verdict(self.run_gate("pre-agent", self.agent_payload()))[0])
    with self.transcript.open("a", encoding="utf-8") as handle:
      handle.write("{broken\n")
    self.assertEqual(self.verdict(self.run_gate("pre-sendmessage", self.send_payload("a99999999999999ff")))[0], "deny")


class UncoveredBranches(GateCase):
  """已知缺口。斷言的是現行行為，行為一改這裡就紅，不讓缺口靜默變動。"""

  def test_marker_on_other_subagent_type_is_not_gated(self):
    self.assertIsNone(self.verdict(self.run_gate("pre-agent", self.agent_payload()))[0])
    reroute = agent_input()
    reroute["subagent_type"] = "routed-judge"
    verdict, _ = self.verdict(self.run_gate("pre-agent", self.agent_payload(reroute)))
    self.assertIsNone(verdict, "已知缺口：改派其他 subagent_type 不在字串比對型 gate 的保證範圍")

  def test_unknown_sendmessage_target_is_not_blocked(self):
    self.assertIsNone(self.verdict(self.run_gate("pre-sendmessage", self.send_payload("a0000000000000000")))[0])

  def test_marker_in_prompt_only_still_works(self):
    """向後相容：舊 caller 把 marker 放 prompt，gate 仍認得。"""
    self.assertIsNone(self.verdict(self.run_gate("pre-agent", self.agent_payload(agent_input(where="prompt"))))[0])
    self.assertEqual(self.verdict(self.run_gate("pre-agent", self.agent_payload(agent_input(where="prompt"))))[0], "deny")

  def test_non_auditor_agent_dispatch_passes_through(self):
    payload = self.agent_payload({"description": "explore", "prompt": "x", "subagent_type": "deep-explore"})
    self.assertIsNone(self.verdict(self.run_gate("pre-agent", payload))[0])

  def test_task_tool_name_is_handled_like_agent(self):
    self.assertIsNone(self.verdict(self.run_gate("pre-agent", self.agent_payload(tool_name="Task")))[0])
    self.assertEqual(self.verdict(self.run_gate("pre-agent", self.agent_payload(tool_name="Task")))[0], "deny")


class SelfLifecycle(GateCase):
  """gate-authoring 第 3 條第四件：這支 gate 裝得上去、改得動、關得掉。"""

  def test_bootstrap_creates_runtime_root_with_owner_only_mode(self):
    self.assertFalse(self.runtime.exists())
    self.assertIsNone(self.verdict(self.run_gate("pre-agent", self.agent_payload()))[0])
    mode = stat.S_IMODE(self.runtime.lstat().st_mode)
    self.assertEqual(mode & 0o077, 0, f"runtime root 權限 {oct(mode)} 對外開放")

  def test_update_path_editing_the_gate_itself_is_not_blocked(self):
    payload = {
      "session_id": SESSION,
      "transcript_path": str(self.transcript),
      "tool_name": "Edit",
      "tool_input": {"file_path": str(GATE), "old_string": "a", "new_string": "b"},
    }
    for mode in ("pre-agent", "post-agent", "pre-sendmessage"):
      self.assertIsNone(self.verdict(self.run_gate(mode, payload))[0], f"{mode} 不得攔改 gate 自身")

  def test_recovery_sentinel_opens_every_mode_without_clearing_claims(self):
    self.assertIsNone(self.verdict(self.run_gate("pre-agent", self.agent_payload()))[0])
    self.assertEqual(self.verdict(self.run_gate("pre-agent", self.agent_payload()))[0], "deny")
    before = self.claim_files()

    self.sentinel.write_text("停用理由：gate 誤攔\n", encoding="utf-8")
    self.assertIsNone(self.verdict(self.run_gate("pre-agent", self.agent_payload()))[0], "sentinel 在就要放行")
    self.assertIsNone(self.verdict(self.run_gate("pre-sendmessage", self.send_payload("skill-verify-auditor")))[0])
    self.assertEqual(self.claim_files(), before, "recovery 不得清空既有 claim")

    self.sentinel.unlink()
    self.assertEqual(self.verdict(self.run_gate("pre-agent", self.agent_payload()))[0], "deny", "移除 sentinel 後恢復攔截")

  def test_sentinel_also_rescues_malformed_hook_input(self):
    """逃生門要能救回每一條 deny，包含輸入壞掉那條。"""
    self.sentinel.write_text("停用\n", encoding="utf-8")
    proc = subprocess.run(
      [sys.executable, str(GATE), "pre-agent"],
      input="not json",
      capture_output=True,
      text=True,
      env={**os.environ, "SKILL_VERIFY_ONCE_RUNTIME_DIR": str(self.runtime), "SKILL_VERIFY_ONCE_DISABLED": str(self.sentinel)},
    )
    self.assertIsNone(self.verdict(proc)[0])

  def test_symlinked_sentinel_does_not_disable_the_gate(self):
    real = self.tmp / "real-sentinel"
    real.write_text("x\n", encoding="utf-8")
    self.sentinel.symlink_to(real)
    self.assertIsNone(self.verdict(self.run_gate("pre-agent", self.agent_payload()))[0])
    self.assertEqual(self.verdict(self.run_gate("pre-agent", self.agent_payload()))[0], "deny")

  def test_post_agent_never_blocks(self):
    for payload in ({"tool_name": "Agent"}, {"garbage": True}, self.agent_payload()):
      proc = self.run_gate("post-agent", payload)
      self.assertEqual(proc.returncode, 0)
      self.assertIsNone(self.verdict(proc)[0])

  def test_post_agent_survives_invalid_json(self):
    proc = subprocess.run(
      [sys.executable, str(GATE), "post-agent"],
      input="{{{",
      capture_output=True,
      text=True,
      env={**os.environ, "SKILL_VERIFY_ONCE_RUNTIME_DIR": str(self.runtime), "SKILL_VERIFY_ONCE_DISABLED": str(self.sentinel)},
    )
    self.assertEqual(proc.returncode, 0)
    self.assertIsNone(self.verdict(proc)[0])

  def test_unknown_mode_exits_nonzero(self):
    proc = subprocess.run([sys.executable, str(GATE), "bogus"], input="{}", capture_output=True, text=True)
    self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
  unittest.main(verbosity=2)
