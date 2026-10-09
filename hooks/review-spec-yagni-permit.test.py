#!/usr/bin/env python3

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

HELPER = Path(__file__).with_name("review-spec-yagni-permit.py")
GATE = Path(__file__).with_name("T2-routing-gate.sh")
NOW = "2026-09-28T12:30:00Z"


class Suite:
  def __init__(self):
    self.passed = 0
    self.failed = 0

  def check(self, name, condition, detail=""):
    if condition:
      self.passed += 1
      print(f"PASS: {name}")
    else:
      self.failed += 1
      print(f"FAIL: {name}{': ' + detail if detail else ''}")


def write_jsonl(path, records):
  path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records))
  path.chmod(0o600)


def command_record(session, uuid="command"):
  return {
    "type": "user",
    "userType": "external",
    "sessionId": session,
    "uuid": uuid,
    "timestamp": "2026-09-28T12:20:00Z",
    "cwd": "/tmp",
    "message": {
      "role": "user",
      "content": (
        "<command-message>review-spec</command-message>\n"
        "<command-name>/review-spec</command-name>\n"
        "<command-args>yagni /tmp/spec.md</command-args>"
      ),
    },
  }


def menu_record(session, packet, uuid="menu"):
  return {
    "type": "assistant",
    "sessionId": session,
    "uuid": uuid,
    "timestamp": "2026-09-28T12:21:00Z",
    "message": {
      "role": "assistant",
      "content": [{
        "type": "text",
        "text": (
          "派工擇一：a. fable 級；b. opus 級。\n"
          f"<review-spec-yagni-model-menu:v1 packet={packet}>"
        ),
      }],
    },
  }


def selection_record(session, value="a", uuid="selection"):
  return {
    "type": "user",
    "userType": "external",
    "sessionId": session,
    "uuid": uuid,
    "timestamp": "2026-09-28T12:22:00Z",
    "message": {"role": "user", "content": value},
  }


def merged_menu_record(session, packet, uuid="menu"):
  return assistant_record(session, (
    "派工擇一（席位＋模型，回一個字母）：\n"
    "- a. c 席・fable 級 → claude-fable-5-1\n"
    "- b. c 席・opus 級 → claude-opus-5-5\n"
    "- c. c 席＋web GPT Pro 席・fable 級 → claude-fable-5-1\n"
    "- d. c 席＋web GPT Pro 席・opus 級 → claude-opus-5-5\n"
    f"<review-spec-yagni-model-menu:v1 packet={packet}>"
  ), uuid)


def entry_menu_record(session, uuid="entry-menu"):
  return assistant_record(session, (
    "a) T1 b) T2 c) T3 d) T4 e) 跳過 f) YAGNI 軸\n"
    "<review-spec-entry-menu:v1>"
  ), uuid)


def packet_for(env, session):
  project = Path(env["REVIEW_SPEC_YAGNI_TRANSCRIPT_ROOT"]) / f"project-{session}"
  project.mkdir(mode=0o700, parents=True)
  packet_dir = Path(env["HOME"]) / ".claude" / ".scratch"
  packet_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
  packet = packet_dir / f"review-spec-yagni-packet-{session}.md"
  packet.write_text(f"packet for {session}\n")
  packet.chmod(0o600)
  return packet, project / f"{session}.jsonl"


def assistant_record(session, value, uuid="assistant"):
  return {
    "type": "assistant",
    "sessionId": session,
    "uuid": uuid,
    "timestamp": "2026-09-28T12:23:00Z",
    "message": {"role": "assistant", "content": [{"type": "text", "text": value}]},
  }


def setup_session(root, env, session, selection="a"):
  project = Path(env["REVIEW_SPEC_YAGNI_TRANSCRIPT_ROOT"]) / f"project-{session}"
  project.mkdir(mode=0o700, parents=True)
  packet_dir = Path(env["HOME"]) / ".claude" / ".scratch"
  packet_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
  packet = packet_dir / f"review-spec-yagni-packet-{session}.md"
  packet.write_text(f"packet for {session}\n")
  packet.chmod(0o600)
  transcript = project / f"{session}.jsonl"
  records = [
    command_record(session),
    menu_record(session, packet),
    selection_record(session, selection),
  ]
  write_jsonl(transcript, records)
  return packet, transcript, records


def run(env, *args, stdin=None, timeout=5):
  result = subprocess.run(
    ["python3", str(HELPER), *args],
    input=stdin,
    text=True,
    capture_output=True,
    env=env,
    timeout=timeout,
  )
  try:
    payload = json.loads(result.stdout)
  except json.JSONDecodeError:
    payload = {"invalid": result.stdout, "stderr": result.stderr}
  return result.returncode, payload


def run_gate(env, payload, root, helper=HELPER):
  audit = root / "t2-audit.jsonl"
  trace = root / "t2-trace.log"
  agent_dir = root / "agents"
  agent_dir.mkdir(mode=0o700, exist_ok=True)
  (agent_dir / "routed-judge.md").write_text("---\nname: routed-judge\n---\n")
  gate_env = env.copy()
  gate_env.update({
    "T2_ROUTED_SENTINEL": str(root / "sentinel-off"),
    "T2_AUDIT_LOG": str(audit),
    "T2_TRACE_LOG": str(trace),
    "T2_AGENT_DIR": str(agent_dir),
    "REVIEW_SPEC_YAGNI_PERMIT_HELPER": str(helper),
  })
  result = subprocess.run(
    ["bash", str(GATE)],
    input=payload,
    text=True,
    capture_output=True,
    env=gate_env,
    timeout=5,
  )
  rows = []
  if audit.exists():
    rows = [json.loads(line) for line in audit.read_text().splitlines() if line.strip()]
  return result, rows


def hook_payload(session, marker, snapshot, batch, tool_id="tool-1", extra_description=""):
  home = Path(os.environ["TEST_HOME"])
  sentinel = home / ".claude" / ".scratch" / f"yagni-c-{batch}-{session}.started"
  report = home / ".claude" / ".scratch" / f"yagni-c-{batch}-{session}.report.md"
  return json.dumps({
    "tool_name": "Agent",
    "session_id": session,
    "tool_use_id": tool_id,
    "tool_input": {
      "subagent_type": "routed-judge",
      "model": "fable",
      "description": f"{marker}{extra_description}",
      "prompt": f"Read {snapshot} then Write {sentinel} and {report}",
    },
  })


def main():
  suite = Suite()
  with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    home = root / "home"
    projects = home / ".claude" / "projects"
    projects.mkdir(mode=0o700, parents=True)
    runtime = root / "runtime"
    issued = root / "issued"
    env = os.environ.copy()
    env.update({
      "HOME": str(home),
      "TEST_HOME": str(home),
      "REVIEW_SPEC_YAGNI_TRANSCRIPT_ROOT": str(projects),
      "REVIEW_SPEC_YAGNI_RUNTIME_DIR": str(runtime),
      "REVIEW_SPEC_YAGNI_ISSUED_DIR": str(issued),
      "REVIEW_SPEC_YAGNI_NOW": NOW,
      "CC_VENDOR": "",
      "ANTHROPIC_DEFAULT_FABLE_MODEL": "",
    })
    os.environ["TEST_HOME"] = str(home)

    packet, transcript, records = setup_session(root, env, "s1")
    code, issued_payload = run(env, "issue", "--session", "s1", "--packet", str(packet))
    suite.check("known-good selection issues permit", code == 0 and issued_payload.get("allowed") is True)
    permit = issued_payload.get("permit_id", "")

    code, marker_payload = run(env, "marker", "--session", "s1", "--permit-id", permit, "--batch", "stories")
    marker = marker_payload.get("marker", "")
    snapshot = marker_payload.get("snapshot_path", "")
    suite.check("marker binds stories batch and packet", code == 0 and "batch=stories" in marker and snapshot)

    fixed = marker.replace(permit, "0" * 32)
    code, payload = run(env, "consume", stdin=hook_payload("s1", fixed, snapshot, "stories"))
    suite.check("fixed marker without matching state is denied", code == 3 and payload.get("reason") == "permit-marker-mismatch")

    code, payload = run(env, "consume", stdin=hook_payload("other", marker, snapshot, "stories"))
    suite.check("cross-session permit use is denied", code == 3 and payload.get("reason") == "permit-missing")

    code, payload = run(env, "consume", stdin=hook_payload("s1", marker, snapshot, "stories", extra_description=" <fable-ok>"))
    suite.check("generic fable marker cannot substitute for permit", code == 3 and payload.get("reason") == "generic-fable-marker-forbidden")

    code, payload = run(env, "consume", stdin=hook_payload("s1", marker, snapshot, "stories"))
    suite.check("known-good stories dispatch consumes permit", code == 0 and payload.get("batch") == "stories")

    code, payload = run(env, "consume", stdin=hook_payload("s1", marker, snapshot, "stories", tool_id="tool-2"))
    suite.check("same batch cannot replay", code == 3 and payload.get("reason") == "batch-already-consumed")

    code, decisions_marker = run(env, "marker", "--session", "s1", "--permit-id", permit, "--batch", "decisions")
    decisions = decisions_marker.get("marker", "")
    code, payload = run(env, "consume", stdin=hook_payload("s1", decisions, snapshot, "decisions", tool_id="tool-3"))
    suite.check("decisions batch consumes independently", code == 0 and payload.get("batch") == "decisions")

    code, payload = run(env, "close", "--session", "s1", "--permit-id", permit)
    suite.check("permit closes only after both batches", code == 0 and payload.get("reason") == "permit-closed")

    code, payload = run(env, "issue", "--session", "s1", "--packet", str(packet))
    suite.check("same human selection cannot reissue", code == 3 and payload.get("reason") == "selection-already-issued")

    suite.check(
      "issue response and marker carry no digest field",
      "packet_sha256" not in issued_payload and "packet_sha256" not in marker_payload,
    )
    suite.check(
      "marker binds only permit_id and batch",
      marker == f"<review-spec-yagni:v1 permit_id={permit} batch=stories>",
      marker,
    )

    # Acceptance batch: identity binding at the hook seam.
    packet_a, _, _ = setup_session(root, env, "a1")
    code, issued_a = run(env, "issue", "--session", "a1", "--packet", str(packet_a))
    permit_a = issued_a.get("permit_id", "")
    suite.check("menu marker without digest yields a permit after a valid reply", code == 0 and issued_a.get("allowed") is True, json.dumps(issued_a))
    state_a = json.loads((runtime / "a1.json").read_text()) if (runtime / "a1.json").exists() else {}
    suite.check(
      "state records identity fields and no digest field",
      bool(state_a)
      and not {"packet_sha256", "menu_sha256", "selection_sha256"} & set(state_a)
      and all(state_a.get(key) for key in ("session_id", "command_uuid", "menu_uuid", "selection_uuid", "packet_path", "snapshot_path", "expires_at")),
      json.dumps(sorted(state_a)),
    )
    snapshot_a = Path(state_a.get("snapshot_path", "/nonexistent"))
    suite.check(
      "snapshot copy exists, owner-only and readable by the reviewer",
      snapshot_a.is_file()
      and snapshot_a.stat().st_mode & 0o077 == 0
      and os.access(snapshot_a, os.R_OK)
      and snapshot_a.read_bytes() == packet_a.read_bytes(),
    )
    code, marker_a_stories = run(env, "marker", "--session", "a1", "--permit-id", permit_a, "--batch", "stories")
    code, marker_a_decisions = run(env, "marker", "--session", "a1", "--permit-id", permit_a, "--batch", "decisions")
    stories_payload = hook_payload("a1", marker_a_stories.get("marker", ""), str(snapshot_a), "stories", tool_id="a-stories")
    decisions_payload = hook_payload("a1", marker_a_decisions.get("marker", ""), str(snapshot_a), "decisions", tool_id="a-decisions")
    gate_result, audit_rows = run_gate(env, stories_payload, root)
    suite.check(
      "gate allows stories once",
      gate_result.returncode == 0 and gate_result.stdout == "" and audit_rows and audit_rows[-1].get("reason") == "review_spec_yagni_permit:stories",
    )
    gate_result, audit_rows = run_gate(env, stories_payload, root)
    suite.check(
      "gate denies the second stories use of the same permit",
      '"permissionDecision": "deny"' in gate_result.stdout and "batch-already-consumed" in audit_rows[-1].get("reason", ""),
    )
    gate_result, audit_rows = run_gate(env, decisions_payload, root)
    suite.check(
      "gate allows decisions once after stories was spent",
      gate_result.returncode == 0 and gate_result.stdout == "" and audit_rows[-1].get("reason") == "review_spec_yagni_permit:decisions",
    )
    gate_result, audit_rows = run_gate(env, decisions_payload, root)
    suite.check(
      "gate denies the second decisions use of the same permit",
      '"permissionDecision": "deny"' in gate_result.stdout and "batch-already-consumed" in audit_rows[-1].get("reason", ""),
    )

    packet_b, _, _ = setup_session(root, env, "b1")
    code, issued_b = run(env, "issue", "--session", "b1", "--packet", str(packet_b))
    permit_b = issued_b.get("permit_id", "")
    code, marker_b = run(env, "marker", "--session", "b1", "--permit-id", permit_b, "--batch", "stories")
    payload_b = hook_payload("b1", marker_b.get("marker", ""), marker_b.get("snapshot_path", ""), "stories", tool_id="b-expiry")
    late_env = env.copy()
    late_env["REVIEW_SPEC_YAGNI_NOW"] = "2026-09-28T13:31:00Z"
    code, payload = run(late_env, "consume", stdin=payload_b)
    suite.check("expired permit is denied", code == 3 and payload.get("reason") == "permit-expired", json.dumps(payload))
    gate_result, audit_rows = run_gate(late_env, payload_b, root)
    suite.check(
      "gate denies an expired permit",
      '"permissionDecision": "deny"' in gate_result.stdout and "permit-expired" in audit_rows[-1].get("reason", ""),
    )

    state_path_b = runtime / "b1.json"
    original_b = state_path_b.read_text()
    foreign = json.loads(original_b)
    foreign["session_id"] = "someone-else"
    state_path_b.write_text(json.dumps(foreign))
    code, payload = run(env, "consume", stdin=payload_b)
    suite.check("state recording another session is denied", code == 3 and payload.get("reason") == "permit-session-mismatch", json.dumps(payload))
    state_path_b.write_text(original_b)

    for field in ("session_id", "command_uuid", "menu_uuid", "selection_uuid", "packet_path", "snapshot_path", "expires_at", "permit_id"):
      broken = json.loads(original_b)
      del broken[field]
      state_path_b.write_text(json.dumps(broken))
      code, payload = run(env, "consume", stdin=payload_b)
      suite.check(f"state missing {field} is denied", code == 3 and payload.get("reason") == "invalid-permit-state", json.dumps(payload))
    state_path_b.write_text(original_b)

    packet_c, transcript_c, records_c = setup_session(root, env, "c1")
    other_menu = menu_record("c1", "/somewhere/else.md", "menu")
    write_jsonl(transcript_c, [records_c[0], other_menu, records_c[2]])
    code, payload = run(env, "issue", "--session", "c1", "--packet", str(packet_c))
    suite.check("menu marker naming another packet path is invalid", code == 3 and payload.get("reason") == "model-menu-invalid", json.dumps(payload))

    packet_d, transcript_d, records_d = setup_session(root, env, "d1")
    second_menu = menu_record("d1", str(packet_d), "menu-2")
    second_menu["timestamp"] = "2026-09-28T12:21:30Z"
    early_reply = selection_record("d1", "a", "early-reply")
    early_reply["timestamp"] = "2026-09-28T12:21:15Z"
    write_jsonl(transcript_d, [records_d[0], records_d[1], early_reply, second_menu])
    code, payload = run(env, "issue", "--session", "d1", "--packet", str(packet_d))
    suite.check("a reply before the latest menu does not count", code == 3 and payload.get("reason") == "model-selection-missing", json.dumps(payload))

    packet7, _, _ = setup_session(root, env, "s7")
    code, issued7 = run(env, "issue", "--session", "s7", "--packet", str(packet7))
    permit7 = issued7.get("permit_id", "")
    code, marker7 = run(env, "marker", "--session", "s7", "--permit-id", permit7, "--batch", "stories")
    gate_payload = hook_payload("s7", marker7.get("marker", ""), marker7.get("snapshot_path", ""), "stories", tool_id="gate-good")
    gate_result, audit_rows = run_gate(env, gate_payload, root)
    suite.check(
      "T2 known-good consumes trusted permit with sentinel off",
      gate_result.returncode == 0
      and gate_result.stdout == ""
      and audit_rows
      and audit_rows[-1].get("reason") == "review_spec_yagni_permit:stories",
    )
    gate_result, audit_rows = run_gate(env, gate_payload, root)
    suite.check(
      "T2 boundary replay is denied",
      '"permissionDecision": "deny"' in gate_result.stdout
      and audit_rows
      and "batch-already-consumed" in audit_rows[-1].get("reason", ""),
    )

    missing_marker = "<review-spec-yagni:v1 permit_id=" + "f" * 32 + " batch=stories>"
    missing_payload = hook_payload("s8", missing_marker, "/missing/snapshot", "stories", tool_id="gate-bad")
    gate_result, audit_rows = run_gate(env, missing_payload, root)
    suite.check(
      "T2 known-bad fixed marker without state is denied",
      '"permissionDecision": "deny"' in gate_result.stdout
      and audit_rows
      and "permit-missing" in audit_rows[-1].get("reason", ""),
    )

    gate_result, audit_rows = run_gate(env, missing_payload, root, helper=root / "missing-helper.py")
    suite.check(
      "T2 lifecycle missing helper fails closed",
      '"permissionDecision": "deny"' in gate_result.stdout
      and audit_rows
      and "helper-error" in audit_rows[-1].get("reason", ""),
    )

    packet2, transcript2, records2 = setup_session(root, env, "s2")
    code, issued2 = run(env, "issue", "--session", "s2", "--packet", str(packet2))
    with transcript2.open("a") as handle:
      later = selection_record("s2", "continue", "later")
      later["timestamp"] = "2026-09-28T12:23:00Z"
      handle.write(json.dumps(later) + "\n")
    code, payload = run(env, "marker", "--session", "s2", "--permit-id", issued2.get("permit_id", ""), "--batch", "stories")
    suite.check("later user message supersedes selection", code == 3 and payload.get("reason") == "model-selection-superseded")

    vendor_env = env.copy()
    vendor_env.update({"CC_VENDOR": "gpt", "ANTHROPIC_DEFAULT_FABLE_MODEL": "gpt-fable-a"})
    packet3, _, _ = setup_session(root, vendor_env, "s3")
    code, issued3 = run(vendor_env, "issue", "--session", "s3", "--packet", str(packet3))
    drift_env = vendor_env.copy()
    drift_env["ANTHROPIC_DEFAULT_FABLE_MODEL"] = "gpt-fable-b"
    code, payload = run(drift_env, "marker", "--session", "s3", "--permit-id", issued3.get("permit_id", ""), "--batch", "stories")
    suite.check("model mapping drift invalidates permit", code == 3 and payload.get("reason") == "fable-model-binding-mismatch")

    bad_root = root / "bad-runtime"
    target = root / "runtime-target"
    target.mkdir(mode=0o700)
    bad_root.symlink_to(target, target_is_directory=True)
    symlink_env = env.copy()
    symlink_env["REVIEW_SPEC_YAGNI_RUNTIME_DIR"] = str(bad_root)
    packet4, _, _ = setup_session(root, symlink_env, "s4")
    code, payload = run(symlink_env, "issue", "--session", "s4", "--packet", str(packet4))
    suite.check("symlink runtime directory is rejected", code == 3 and payload.get("reason") == "untrusted-runtime")

    packet5, _, _ = setup_session(root, env, "s5")
    code, issued5 = run(env, "issue", "--session", "s5", "--packet", str(packet5))
    state5 = runtime / "s5.json"
    hardlink = root / "state-hardlink"
    os.link(state5, hardlink)
    code, payload = run(env, "marker", "--session", "s5", "--permit-id", issued5.get("permit_id", ""), "--batch", "stories")
    suite.check("hard-linked state is rejected", code == 3 and payload.get("reason") == "invalid-permit-state")
    hardlink.unlink()

    packet6, _, _ = setup_session(root, env, "s6")
    code, issued6 = run(env, "issue", "--session", "s6", "--packet", str(packet6))
    state6 = runtime / "s6.json"
    state6.unlink()
    os.mkfifo(state6, 0o600)
    code, payload = run(env, "marker", "--session", "s6", "--permit-id", issued6.get("permit_id", ""), "--batch", "stories", timeout=2)
    suite.check("FIFO state is rejected without blocking", code == 3 and payload.get("reason") == "invalid-permit-state")

    packet9, transcript9, _ = setup_session(root, env, "s9", selection="b")
    with transcript9.open("a") as handle:
      later_question = assistant_record("s9", "另一題：a. 繼續；b. 停止", "later-question")
      later_selection = selection_record("s9", "a", "later-selection")
      later_selection["timestamp"] = "2026-09-28T12:24:00Z"
      handle.write(json.dumps(later_question, ensure_ascii=False) + "\n")
      handle.write(json.dumps(later_selection, ensure_ascii=False) + "\n")
    code, payload = run(env, "issue", "--session", "s9", "--packet", str(packet9))
    suite.check("later unrelated a cannot override Opus selection", code == 3 and payload.get("reason") == "fable-not-selected")

    packet10, transcript10, records10 = setup_session(root, env, "s10")
    intervening = assistant_record("s10", "先回答另一題：a. 是；b. 否", "intervening-question")
    write_jsonl(transcript10, [records10[0], records10[1], intervening, records10[2]])
    code, payload = run(env, "issue", "--session", "s10", "--packet", str(packet10))
    suite.check("intervening assistant question invalidates model selection", code == 3 and payload.get("reason") == "model-selection-not-adjacent")

    packet11, _, _ = setup_session(root, env, "s11")
    code, issued11 = run(env, "issue", "--session", "s11", "--packet", str(packet11))
    code, marker11 = run(env, "marker", "--session", "s11", "--permit-id", issued11.get("permit_id", ""), "--batch", "stories")
    path_payload = json.loads(hook_payload("s11", marker11.get("marker", ""), marker11.get("snapshot_path", ""), "stories", tool_id="path-prefix"))
    path_payload["tool_input"]["prompt"] = path_payload["tool_input"]["prompt"].replace(
      marker11.get("snapshot_path", ""),
      marker11.get("snapshot_path", "") + ".evil",
    )
    code, payload = run(env, "consume", stdin=json.dumps(path_payload))
    suite.check("prompt path prefix extension is denied", code == 3 and payload.get("reason") == "prompt-binding-mismatch")

    packet12, _, _ = setup_session(root, env, "s12")
    code, issued12 = run(env, "issue", "--session", "s12", "--packet", str(packet12))
    code, marker12 = run(env, "marker", "--session", "s12", "--permit-id", issued12.get("permit_id", ""), "--batch", "stories")
    stacked_payload = hook_payload(
      "s12",
      marker12.get("marker", ""),
      marker12.get("snapshot_path", ""),
      "stories",
      tool_id="stacked-markers",
      extra_description=" <fable-ok> <review-implement-fable:v1 axis=yagni>",
    )
    gate_result, audit_rows = run_gate(env, stacked_payload, root)
    code, reissued12 = run(env, "marker", "--session", "s12", "--permit-id", issued12.get("permit_id", ""), "--batch", "stories")
    suite.check(
      "T2 marker stacking cannot bypass YAGNI permit validation",
      '"permissionDecision": "deny"' in gate_result.stdout
      and audit_rows
      and "generic-fable-marker-forbidden" in audit_rows[-1].get("reason", "")
      and code == 0
      and reissued12.get("allowed") is True,
    )

    for session, reply, allowed in (("m1", "c", True), ("m2", "b", False), ("m3", "d", False)):
      packet_m, transcript_m = packet_for(env, session)
      write_jsonl(transcript_m, [command_record(session), merged_menu_record(session, packet_m), selection_record(session, reply)])
      code, payload = run(env, "issue", "--session", session, "--packet", str(packet_m))
      if allowed:
        suite.check(f"merged menu letter {reply} maps to Fable", code == 0 and payload.get("allowed") is True, json.dumps(payload))
      else:
        suite.check(f"merged menu letter {reply} is not Fable", code == 3 and payload.get("reason") == "fable-not-selected", json.dumps(payload))

    packet_e, transcript_e = packet_for(env, "e1")
    entry_reply = selection_record("e1", "f", "entry-reply")
    entry_reply["timestamp"] = "2026-09-28T12:20:00Z"
    write_jsonl(transcript_e, [entry_menu_record("e1"), entry_reply, merged_menu_record("e1", packet_e), selection_record("e1", "a")])
    code, payload = run(env, "issue", "--session", "e1", "--packet", str(packet_e))
    suite.check("to-spec entry menu followed by human f counts as the command", code == 0 and payload.get("allowed") is True, json.dumps(payload))

    packet_e2, transcript_e2 = packet_for(env, "e2")
    write_jsonl(transcript_e2, [entry_menu_record("e2"), assistant_record("e2", "插一句", "between"), selection_record("e2", "f", "entry-reply"), merged_menu_record("e2", packet_e2), selection_record("e2", "a")])
    code, payload = run(env, "issue", "--session", "e2", "--packet", str(packet_e2))
    suite.check("entry reply must be adjacent to the entry menu", code == 3 and payload.get("reason") == "review-spec-yagni-command-missing", json.dumps(payload))

    packet_e3, transcript_e3 = packet_for(env, "e3")
    write_jsonl(transcript_e3, [assistant_record("e3", "a) T1 … f) YAGNI 軸", "no-marker"), selection_record("e3", "f", "entry-reply"), merged_menu_record("e3", packet_e3), selection_record("e3", "a")])
    code, payload = run(env, "issue", "--session", "e3", "--packet", str(packet_e3))
    suite.check("f without the entry marker is not a command", code == 3 and payload.get("reason") == "review-spec-yagni-command-missing", json.dumps(payload))

    packet_e4, transcript_e4 = packet_for(env, "e4")
    write_jsonl(transcript_e4, [entry_menu_record("e4"), selection_record("e4", "e", "entry-reply"), merged_menu_record("e4", packet_e4), selection_record("e4", "a")])
    code, payload = run(env, "issue", "--session", "e4", "--packet", str(packet_e4))
    suite.check("entry menu answered with another option is not a command", code == 3 and payload.get("reason") == "review-spec-yagni-command-missing", json.dumps(payload))

    packet_x, transcript_x = packet_for(env, "x1")
    ambiguous = assistant_record("x1", f"a. fable 級\na. opus 級\n<review-spec-yagni-model-menu:v1 packet={packet_x}>", "menu")
    write_jsonl(transcript_x, [command_record("x1"), ambiguous, selection_record("x1", "a")])
    code, payload = run(env, "issue", "--session", "x1", "--packet", str(packet_x))
    suite.check("a letter mapped to both Fable and Opus invalidates the menu", code == 3 and payload.get("reason") == "model-menu-invalid", json.dumps(payload))

    malformed = runtime / "foreign.json"
    malformed.write_text("{broken\n")
    malformed.chmod(0o600)
    packet13, _, _ = setup_session(root, env, "s13")
    code, payload = run(env, "issue", "--session", "s13", "--packet", str(packet13))
    suite.check("malformed foreign state cannot pollute issue JSON", code == 0 and payload.get("allowed") is True)
    malformed.unlink(missing_ok=True)

  print(f"RESULT: {suite.passed} passed, {suite.failed} failed")
  raise SystemExit(1 if suite.failed else 0)


if __name__ == "__main__":
  main()
