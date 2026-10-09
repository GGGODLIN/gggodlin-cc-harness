#!/usr/bin/env python3
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("friction-outcome-packet.py")
SESSION = "123e4567-e89b-12d3-a456-426614174000"
SKILL = "payment-debugger"


class FrictionOutcomePacketTest(unittest.TestCase):
  def setUp(self):
    self.temporary = tempfile.TemporaryDirectory()
    self.home = Path(self.temporary.name) / "home"
    self.project = self.home / ".claude" / "projects" / "project-a"
    self.output_dir = self.home / ".claude" / ".scratch" / "packets"
    self.project.mkdir(parents=True)
    self.output_dir.mkdir(parents=True)
    for path in (
      self.home / ".claude" / "projects",
      self.project,
      self.home / ".claude" / ".scratch",
      self.output_dir,
    ):
      path.chmod(0o700)

  def tearDown(self):
    self.temporary.cleanup()

  def write_transcript(self, records, project=None, session=SESSION):
    target_project = project or self.project
    target_project.mkdir(parents=True, exist_ok=True)
    target_project.chmod(0o700)
    path = target_project / f"{session}.jsonl"
    path.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records))
    path.chmod(0o600)
    return path

  def run_helper(self, session=SESSION, skill=SKILL, output=None):
    target = output or self.output_dir / "packet.json"
    environment = os.environ.copy()
    environment["HOME"] = str(self.home)
    result = subprocess.run(
      [
        "python3",
        str(SCRIPT),
        "--session",
        session,
        "--skill",
        skill,
        "--output",
        str(target),
      ],
      env=environment,
      capture_output=True,
      text=True,
    )
    return result, target

  def test_outputs_distinct_skill_invokes_and_bounded_context(self):
    self.write_transcript(
      [
        {
          "type": "user",
          "userType": "external",
          "timestamp": "2026-08-30T01:02:03Z",
          "message": {"role": "user", "content": "Please inspect src/payments.py at commit abc1234."},
        },
        {
          "type": "assistant",
          "message": {
            "role": "assistant",
            "content": [
              {
                "type": "tool_use",
                "id": "skill-1",
                "name": "Skill",
                "input": {"skill": SKILL},
              }
            ],
          },
        },
        {
          "type": "assistant",
          "message": {
            "role": "assistant",
            "content": [
              {
                "type": "tool_use",
                "id": "skill-1",
                "name": "Skill",
                "input": {"skill": SKILL},
              },
              {
                "type": "tool_use",
                "id": "skill-2",
                "name": "Skill",
                "input": {"skill": "research-before-answer"},
              },
            ],
          },
        },
        {
          "type": "user",
          "userType": "external",
          "timestamp": "2026-08-30T01:02:04Z OPENAI_API_KEY=timestamp-secret",
          "message": {
            "role": "user",
            "content": "不對，AUTH_TOKEN=sk_live_example OPENAI_API_KEY=openai-secret AWS_SECRET_ACCESS_KEY=aws-secret github_pat_12345678901234567890 sk-ant-1234567890abcdef sk-proj-1234567890abcdef AIza12345678901234567890 Basic YWxhZGRpbjpvcGVuc2VzYW1l for alice@example.com；請重講「必要短句」，保留 src/payments.py 與 abc1234。\n-----BEGIN PRIVATE KEY-----\nprivate-material\n-----END PRIVATE KEY-----",
          },
        },
        {
          "type": "user",
          "userType": "external",
          "message": {"role": "user", "content": "最後只要可採取的結論。"},
        },
      ]
    )

    result, output = self.run_helper()

    self.assertEqual(result.returncode, 0, result.stderr)
    packet = json.loads(output.read_text())
    self.assertEqual(packet["schema_version"], 1)
    self.assertEqual(packet["source_session"], SESSION)
    self.assertEqual(packet["owning_skill"], SKILL)
    self.assertTrue(packet["skill_invoked"])
    self.assertEqual([item["tool_use_id"] for item in packet["skill_invokes"]], ["skill-1", "skill-2"])
    self.assertEqual(packet["distinct_skills"], [SKILL, "research-before-answer"])
    self.assertLessEqual(len(packet["context"]), 5)
    self.assertTrue(all(len(item["text"]) <= 600 for item in packet["context"]))
    context = " ".join(item["text"] for item in packet["context"])
    self.assertIn("src/payments.py", context)
    self.assertIn("abc1234", context)
    self.assertIn("必要短句", context)
    for secret in (
      "sk_live_example",
      "openai-secret",
      "aws-secret",
      "github_pat_12345678901234567890",
      "sk-ant-1234567890abcdef",
      "sk-proj-1234567890abcdef",
      "AIza12345678901234567890",
      "YWxhZGRpbjpvcGVuc2VzYW1l",
      "alice@example.com",
      "private-material",
      "timestamp-secret",
    ):
      self.assertNotIn(secret, json.dumps(packet, ensure_ascii=False))
    source = next(item for item in packet["context"] if item["kind"] == "source")
    self.assertEqual(source["timestamp"], "2026-08-30T01:02:03Z")
    correction = next(item for item in packet["context"] if item["kind"] == "correction")
    self.assertNotIn("timestamp", correction)
    self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)

  def test_rejects_session_traversal_without_output(self):
    result, output = self.run_helper(session="../../outside")

    self.assertEqual(result.returncode, 2)
    self.assertIn("ERROR invalid-session-id", result.stderr)
    self.assertFalse(output.exists())

  def test_rejects_skill_traversal_without_output(self):
    result, output = self.run_helper(skill="../../skill")

    self.assertEqual(result.returncode, 2)
    self.assertIn("ERROR invalid-skill-id", result.stderr)
    self.assertFalse(output.exists())

  def test_rejects_duplicate_top_level_transcripts(self):
    records = [
      {
        "type": "assistant",
        "message": {
          "role": "assistant",
          "content": [
            {
              "type": "tool_use",
              "id": "skill-1",
              "name": "Skill",
              "input": {"skill": SKILL},
            }
          ],
        },
      }
    ]
    self.write_transcript(records)
    self.write_transcript(records, project=self.project.parent / "project-b")

    result, output = self.run_helper()

    self.assertEqual(result.returncode, 2)
    self.assertIn("ERROR transcript-not-unique", result.stderr)
    self.assertFalse(output.exists())

  def test_rejects_symlink_transcript(self):
    external = self.home / "external.jsonl"
    external.write_text("{}\n")
    external.chmod(0o600)
    (self.project / f"{SESSION}.jsonl").symlink_to(external)

    result, output = self.run_helper()

    self.assertEqual(result.returncode, 2)
    self.assertIn("ERROR untrusted-transcript", result.stderr)
    self.assertFalse(output.exists())

  def test_rejects_output_outside_scratch(self):
    self.write_transcript([])
    output = self.home / "packet.json"

    result, _ = self.run_helper(output=output)

    self.assertEqual(result.returncode, 2)
    self.assertIn("ERROR output-outside-allowed-root", result.stderr)
    self.assertFalse(output.exists())

  def test_rejects_symlink_output_without_touching_target(self):
    self.write_transcript([])
    external = self.home / "external-output.json"
    external.write_text("sentinel\n")
    external.chmod(0o600)
    output = self.output_dir / "packet.json"
    output.symlink_to(external)

    result, _ = self.run_helper(output=output)

    self.assertEqual(result.returncode, 2)
    self.assertIn("ERROR untrusted-output-file", result.stderr)
    self.assertEqual(external.read_text(), "sentinel\n")

  def test_rejects_mixed_trust_duplicate_transcript(self):
    self.write_transcript([])
    untrusted_project = self.project.parent / "project-b"
    self.write_transcript([], project=untrusted_project)
    untrusted_project.chmod(0o777)

    result, output = self.run_helper()

    untrusted_project.chmod(0o700)
    self.assertEqual(result.returncode, 2)
    self.assertIn("ERROR untrusted-transcript", result.stderr)
    self.assertFalse(output.exists())

  def test_accepts_dot_prefixed_skill_identifier(self):
    skill = ".sdd/proj-pr-evidence-home:debugging"
    self.write_transcript(
      [
        {
          "type": "assistant",
          "message": {
            "role": "assistant",
            "content": [
              {
                "type": "tool_use",
                "id": "skill-dot",
                "name": "Skill",
                "input": {"skill": skill},
              }
            ],
          },
        }
      ]
    )

    result, output = self.run_helper(skill=skill)

    self.assertEqual(result.returncode, 0, result.stderr)
    packet = json.loads(output.read_text())
    self.assertTrue(packet["skill_invoked"])
    self.assertEqual(packet["distinct_skills"], [skill])

  def test_excludes_generated_envelopes_and_cleans_before_correction_detection(self):
    self.write_transcript(
      [
        {
          "type": "assistant",
          "message": {
            "role": "assistant",
            "content": [
              {
                "type": "tool_use",
                "id": "skill-1",
                "name": "Skill",
                "input": {"skill": SKILL},
              }
            ],
          },
        },
        {
          "type": "user",
          "userType": "external",
          "message": {"role": "user", "content": "<bash-input>echo did not run</bash-input>"},
        },
        {
          "type": "user",
          "userType": "external",
          "message": {"role": "user", "content": "<bash-stdout>wrong output</bash-stdout>"},
        },
        {
          "type": "user",
          "userType": "external",
          "message": {"role": "user", "content": "<local-command-stdout>incorrect</local-command-stdout>"},
        },
        {
          "type": "user",
          "userType": "external",
          "message": {
            "role": "user",
            "content": "<system-reminder>wrong and did not</system-reminder>Proceed normally.",
          },
        },
        {
          "type": "user",
          "userType": "external",
          "message": {"role": "user", "content": "Final human request."},
        },
      ]
    )

    result, output = self.run_helper()

    self.assertEqual(result.returncode, 0, result.stderr)
    packet = json.loads(output.read_text())
    context = " ".join(item["text"] for item in packet["context"])
    self.assertNotIn("bash-input", context)
    self.assertNotIn("wrong output", context)
    self.assertNotIn("local-command-stdout", context)
    cleaned = next(item for item in packet["context"] if item["text"] == "Proceed normally.")
    self.assertFalse(cleaned["correction_candidate"])

  def test_context_priority_preserves_latest_tail(self):
    records = [
      {
        "type": "user",
        "userType": "external",
        "message": {"role": "user", "content": "source request"},
      },
      {
        "type": "assistant",
        "message": {
          "role": "assistant",
          "content": [
            {
              "type": "tool_use",
              "id": "skill-1",
              "name": "Skill",
              "input": {"skill": SKILL},
            }
          ],
        },
      },
    ]
    records.extend(
      {
        "type": "user",
        "userType": "external",
        "message": {"role": "user", "content": f"不對 correction-{index}"},
      }
      for index in range(3)
    )
    records.extend(
      [
        {
          "type": "user",
          "userType": "external",
          "message": {"role": "user", "content": "tail-one"},
        },
        {
          "type": "user",
          "userType": "external",
          "message": {"role": "user", "content": "tail-two"},
        },
      ]
    )
    self.write_transcript(records)

    result, output = self.run_helper()

    self.assertEqual(result.returncode, 0, result.stderr)
    packet = json.loads(output.read_text())
    texts = [item["text"] for item in packet["context"]]
    self.assertEqual(len(texts), 5)
    self.assertIn("tail-one", texts)
    self.assertIn("tail-two", texts)
    self.assertIn("source request", texts)
    self.assertNotIn("不對 correction-2", texts)

  def test_io_failures_return_stable_errors_without_tracebacks(self):
    transcript = self.write_transcript([])
    transcript.chmod(0o000)

    read_result, read_output = self.run_helper()

    transcript.chmod(0o600)
    self.assertEqual(read_result.returncode, 2)
    self.assertIn("ERROR transcript-read-failed", read_result.stderr)
    self.assertNotIn("Traceback", read_result.stderr)
    self.assertFalse(read_output.exists())

    self.output_dir.chmod(0o500)
    write_result, write_output = self.run_helper()
    self.output_dir.chmod(0o700)

    self.assertEqual(write_result.returncode, 2)
    self.assertIn("ERROR output-write-failed", write_result.stderr)
    self.assertNotIn("Traceback", write_result.stderr)
    self.assertFalse(write_output.exists())

  def test_excludes_sdk_prompt_from_human_context(self):
    self.write_transcript(
      [
        {
          "type": "assistant",
          "message": {
            "role": "assistant",
            "content": [
              {
                "type": "tool_use",
                "id": "skill-1",
                "name": "Skill",
                "input": {"skill": SKILL},
              }
            ],
          },
        },
        {
          "type": "user",
          "userType": "external",
          "promptSource": "sdk",
          "message": {"role": "user", "content": "wrong: evaluator-generated instructions"},
        },
        {
          "type": "user",
          "userType": "external",
          "promptSource": "typed",
          "origin": {"kind": "human"},
          "message": {"role": "user", "content": "wrong: typed human correction"},
        },
      ]
    )

    result, output = self.run_helper()

    self.assertEqual(result.returncode, 0, result.stderr)
    packet = json.loads(output.read_text())
    context = " ".join(item["text"] for item in packet["context"])
    self.assertNotIn("evaluator-generated", context)
    self.assertIn("typed human correction", context)

  def test_redacts_structured_credentials_jwt_and_phone(self):
    self.write_transcript(
      [
        {
          "type": "assistant",
          "message": {
            "role": "assistant",
            "content": [
              {
                "type": "tool_use",
                "id": "skill-1",
                "name": "Skill",
                "input": {"skill": SKILL},
              }
            ],
          },
        },
        {
          "type": "user",
          "userType": "external",
          "message": {
            "role": "user",
            "content": "wrong in src/db.py: {\"password\":\"hunter2\",\"apiKey\":\"opaque-key-123\"}\nCookie: sessionid=session-secret\nAuthorization: Digest auth-secret\nDATABASE_URL=postgres://alice:dbpass@db.example/test\nJWT eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature12345\nphone +886912345678",
          },
        },
      ]
    )

    result, output = self.run_helper()

    self.assertEqual(result.returncode, 0, result.stderr)
    serialized = output.read_text()
    for secret in (
      "hunter2",
      "opaque-key-123",
      "session-secret",
      "auth-secret",
      "alice",
      "dbpass",
      "eyJhbGciOiJIUzI1NiJ9",
      "+886912345678",
    ):
      self.assertNotIn(secret, serialized)
    self.assertIn("src/db.py", serialized)

  def test_rejects_non_executable_project_directory(self):
    self.write_transcript([])
    hidden_project = self.project.parent / "project-hidden"
    self.write_transcript([], project=hidden_project)
    hidden_project.chmod(0o000)

    result, output = self.run_helper()

    hidden_project.chmod(0o700)
    self.assertEqual(result.returncode, 2)
    self.assertIn("ERROR untrusted-transcript-directory", result.stderr)
    self.assertFalse(output.exists())

  def test_large_json_integer_returns_stable_error(self):
    path = self.project / f"{SESSION}.jsonl"
    path.write_text('{"value":' + '9' * 5000 + '}\n')
    path.chmod(0o600)

    result, output = self.run_helper()

    self.assertEqual(result.returncode, 2)
    self.assertIn("ERROR transcript-invalid", result.stderr)
    self.assertNotIn("Traceback", result.stderr)
    self.assertFalse(output.exists())

  def test_lone_surrogate_returns_stable_error(self):
    path = self.project / f"{SESSION}.jsonl"
    path.write_text('{"type":"user","userType":"external","message":{"role":"user","content":"bad\\ud800text"}}\n')
    path.chmod(0o600)

    result, output = self.run_helper()

    self.assertEqual(result.returncode, 2)
    self.assertIn("ERROR transcript-invalid-unicode", result.stderr)
    self.assertNotIn("Traceback", result.stderr)
    self.assertFalse(output.exists())

  def test_unknown_user_output_path_returns_stable_error(self):
    result, _ = self.run_helper(output="~definitely-no-such-user-task10/packet.json")

    self.assertEqual(result.returncode, 2)
    self.assertIn("ERROR output-path-invalid", result.stderr)
    self.assertNotIn("Traceback", result.stderr)

  def test_bounds_context_and_excludes_non_user_records(self):
    records = [
      {
        "type": "assistant",
        "message": {
          "role": "assistant",
          "content": [
            {
              "type": "tool_use",
              "id": "skill-1",
              "name": "Skill",
              "input": {"skill": SKILL},
            }
          ],
        },
      },
      {
        "type": "user",
        "userType": "external",
        "origin": {"kind": "task-notification"},
        "message": {"role": "user", "content": "不對，這是背景通知。"},
      },
      {
        "type": "user",
        "userType": "external",
        "promptSource": "system",
        "message": {"role": "user", "content": "不對，這是 system。"},
      },
    ]
    records.extend(
      {
        "type": "user",
        "userType": "external",
        "message": {"role": "user", "content": f"不對，請重講 case-{index} " + "x" * 700},
      }
      for index in range(8)
    )
    self.write_transcript(records)

    result, output = self.run_helper()

    self.assertEqual(result.returncode, 0, result.stderr)
    packet = json.loads(output.read_text())
    self.assertEqual(len(packet["context"]), 5)
    self.assertTrue(all(len(item["text"]) <= 600 for item in packet["context"]))
    context = " ".join(item["text"] for item in packet["context"])
    self.assertIn("case-6", context)
    self.assertIn("case-7", context)
    self.assertNotIn("背景通知", context)
    self.assertNotIn("這是 system", context)


if __name__ == "__main__":
  unittest.main()
