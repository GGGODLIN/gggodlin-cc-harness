import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class SembleAdoptionTest(unittest.TestCase):
    def test_distinguishes_all_adoption_paths(self):
        scripts_dir = Path(__file__).parent
        fixture_home = scripts_dir / "fixtures" / "semble-adoption" / "home"
        env = os.environ.copy()
        env["HOME"] = str(fixture_home)

        result = subprocess.run(
            [
                sys.executable,
                str(scripts_dir / "semble-adoption.py"),
                "1",
                "--as-of",
                "2026-08-15",
                "--root",
                str(fixture_home / ".claude" / "projects"),
            ],
            capture_output=True,
            check=False,
            env=env,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("MCP-code", result.stdout)
        self.assertIn("MCP-docs", result.stdout)
        self.assertRegex(result.stdout, r"2026-08-15\s+1\s+1\s+1\s+1\s+1\s+1")
        self.assertRegex(result.stdout, r"合計\s+1\s+1\s+1\s+1\s+1")
        self.assertIn(
            "三路呼叫數: MCP 2 (code 1 / docs 1) / CLI 1 / subagent 1",
            result.stdout,
        )

    def test_counts_only_real_cli_and_exact_semble_search_subagent(self):
        scripts_dir = Path(__file__).parent
        tool_uses = [
            {
                "type": "tool_use",
                "id": "agent-review",
                "name": "Agent",
                "input": {
                    "subagent_type": "reviewer",
                    "prompt": "Review assemble and semble-search filenames",
                },
            },
            {
                "type": "tool_use",
                "id": "agent-semble",
                "name": "Agent",
                "input": {"subagent_type": "semble-search", "prompt": "Find code"},
            },
            {
                "type": "tool_use",
                "id": "bash-rg",
                "name": "Bash",
                "input": {"command": "rg 'semble search' review-semble-search.md"},
            },
            {
                "type": "tool_use",
                "id": "bash-printf",
                "name": "Bash",
                "input": {"command": "printf '%s\\n' 'semble search literal'"},
            },
            {
                "type": "tool_use",
                "id": "bash-assemble",
                "name": "Bash",
                "input": {"command": "assemble search repository"},
            },
            {
                "type": "tool_use",
                "id": "bash-absolute",
                "name": "Bash",
                "input": {
                    "command": "/Users/test/.local/bin/semble search authentication /repo"
                },
            },
            {
                "type": "tool_use",
                "id": "bash-uvx",
                "name": "Bash",
                "input": {
                    "command": "uvx --from 'semble[mcp]' semble find-related src/a.py 4 /repo"
                },
            },
            {
                "type": "tool_use",
                "id": "bash-newline",
                "name": "Bash",
                "input": {"command": "pwd\nsemble search newline /repo"},
            },
        ]
        record = {
            "timestamp": "2026-08-15T01:00:00Z",
            "message": {"content": tool_uses},
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture_home = Path(temp_dir)
            project_dir = fixture_home / ".claude" / "projects" / "fixture-project"
            project_dir.mkdir(parents=True)
            (project_dir / "session.jsonl").write_text(f"{json.dumps(record)}\n")
            env = os.environ.copy()
            env["HOME"] = str(fixture_home)
            result = subprocess.run(
                [
                    sys.executable,
                    str(scripts_dir / "semble-adoption.py"),
                    "1",
                    "--as-of",
                    "2026-08-15",
                    "--root",
                    str(fixture_home / ".claude" / "projects"),
                ],
                capture_output=True,
                check=False,
                env=env,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r"2026-08-15\s+0\s+0\s+3\s+0\s+1\s+1")
        self.assertRegex(result.stdout, r"合計\s+0\s+0\s+3\s+0\s+1")

    def test_counts_time_wrapped_semble_commands(self):
        scripts_dir = Path(__file__).parent
        commands = [
            "time semble search query /repo --content docs",
            "cd /repo && time semble find-related src/a.py 4",
            "/usr/bin/time -p -f '%e' -o /tmp/time.log semble search query /repo --content docs",
            "/usr/bin/time --verbose --format '%e' --output /tmp/time.log semble find-related src/a.py 4 --content docs",
        ]
        record = {
            "timestamp": "2026-08-15T01:00:00Z",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": f"time-{index}",
                        "name": "Bash",
                        "input": {"command": command},
                    }
                    for index, command in enumerate(commands)
                ]
            },
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            projects_root = Path(temp_dir) / "projects"
            project_dir = projects_root / "fixture-project"
            project_dir.mkdir(parents=True)
            (project_dir / "session.jsonl").write_text(f"{json.dumps(record)}\n")
            result = subprocess.run(
                [
                    sys.executable,
                    str(scripts_dir / "semble-adoption.py"),
                    "1",
                    "--as-of",
                    "2026-08-15",
                    "--root",
                    str(projects_root),
                ],
                capture_output=True,
                check=False,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r"2026-08-15\s+0\s+0\s+4\s+3\s+0\s+1")
        self.assertRegex(result.stdout, r"合計\s+0\s+0\s+4\s+3\s+0")

    def test_detects_all_docs_content_forms(self):
        scripts_dir = Path(__file__).parent
        commands = [
            "semble search query /repo --content=docs",
            "semble search query /repo --content code docs",
            "semble search query /repo --content all",
        ]
        record = {
            "timestamp": "2026-08-15T01:00:00Z",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": f"bash-{index}",
                        "name": "Bash",
                        "input": {"command": command},
                    }
                    for index, command in enumerate(commands)
                ]
            },
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture_home = Path(temp_dir)
            project_dir = fixture_home / ".claude" / "projects" / "fixture-project"
            project_dir.mkdir(parents=True)
            (project_dir / "session.jsonl").write_text(f"{json.dumps(record)}\n")
            env = os.environ.copy()
            env["HOME"] = str(fixture_home)
            result = subprocess.run(
                [
                    sys.executable,
                    str(scripts_dir / "semble-adoption.py"),
                    "1",
                    "--as-of",
                    "2026-08-15",
                    "--root",
                    str(fixture_home / ".claude" / "projects"),
                ],
                capture_output=True,
                check=False,
                env=env,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r"2026-08-15\s+0\s+0\s+3\s+3\s+0\s+1")
        self.assertRegex(result.stdout, r"合計\s+0\s+0\s+3\s+3\s+0")

    def test_uses_calendar_window_and_emits_zero_adoption_days(self):
        scripts_dir = Path(__file__).parent
        records = [
            {
                "timestamp": "2026-08-12T01:00:00Z",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "old-code",
                            "name": "mcp__semble__search",
                            "input": {"query": "old", "repo": "/repo"},
                        }
                    ]
                },
            },
            {
                "timestamp": "2026-08-13T01:00:00Z",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "recent-code",
                            "name": "mcp__semble__search",
                            "input": {"query": "recent", "repo": "/repo"},
                        }
                    ]
                },
            },
            {
                "timestamp": "2026-08-14T01:00:00Z",
                "message": {
                    "content": [{"type": "text", "text": "semble documentation"}]
                },
            },
            {
                "timestamp": "2026-08-15T01:00:00Z",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "unrelated-bash",
                            "name": "Bash",
                            "input": {"command": "pwd"},
                        }
                    ]
                },
            },
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            projects_root = Path(temp_dir) / "projects"
            project_dir = projects_root / "fixture-project"
            project_dir.mkdir(parents=True)
            (project_dir / "session.jsonl").write_text(
                "".join(f"{json.dumps(record)}\n" for record in records)
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(scripts_dir / "semble-adoption.py"),
                    "3",
                    "--as-of",
                    "2026-08-15",
                    "--root",
                    str(projects_root),
                ],
                capture_output=True,
                check=False,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("2026-08-12", result.stdout)
        self.assertRegex(result.stdout, r"2026-08-13\s+1\s+0\s+0\s+0\s+0\s+1")
        self.assertRegex(result.stdout, r"2026-08-14\s+0\s+0\s+0\s+0\s+0\s+0")
        self.assertRegex(result.stdout, r"2026-08-15\s+0\s+0\s+0\s+0\s+0\s+1")
        self.assertRegex(result.stdout, r"合計\s+1\s+0\s+0\s+0\s+0")
        self.assertIn(
            "三路呼叫數: MCP 1 (code 1 / docs 0) / CLI 0 / subagent 0",
            result.stdout,
        )

    def test_deduplicates_main_tool_uses_and_ignores_nested_children(self):
        scripts_dir = Path(__file__).parent
        duplicate = {
            "timestamp": "2026-08-15T01:00:00Z",
            "sessionId": "session-shared",
            "uuid": "message-duplicate",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool-duplicate",
                        "name": "mcp__semble__search",
                        "input": {"query": "code", "repo": "/repo"},
                    }
                ]
            },
        }
        distinct = {
            "timestamp": "2026-08-15T01:01:00Z",
            "sessionId": "session-shared",
            "uuid": "message-cli",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool-cli",
                        "name": "Bash",
                        "input": {"command": "semble search code /repo"},
                    }
                ]
            },
        }
        nested = {
            "timestamp": "2026-08-15T01:02:00Z",
            "uuid": "message-nested",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool-nested",
                        "name": "mcp__semble-docs__search",
                        "input": {"query": "docs", "repo": "/repo"},
                    }
                ]
            },
        }
        workflow = {
            "timestamp": "2026-08-15T01:03:00Z",
            "uuid": "message-workflow",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool-workflow",
                        "name": "mcp__semble-docs__search",
                        "input": {"query": "workflow", "repo": "/repo"},
                    }
                ]
            },
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            projects_root = Path(temp_dir) / "projects"
            first_project = projects_root / "project-a"
            second_project = projects_root / "project-b"
            first_project.mkdir(parents=True)
            second_project.mkdir(parents=True)
            (first_project / "same-session.jsonl").write_text(
                f"{json.dumps(duplicate)}\n{json.dumps(duplicate)}\n{json.dumps(distinct)}\n"
            )
            (second_project / "copied-session.jsonl").write_text(
                f"{json.dumps(duplicate)}\n"
            )
            nested_dir = first_project / "same-session" / "subagents"
            nested_dir.mkdir(parents=True)
            (nested_dir / "child.jsonl").write_text(f"{json.dumps(nested)}\n")
            workflow_dir = first_project / "workflow-journal"
            workflow_dir.mkdir()
            (workflow_dir / "journal.jsonl").write_text(f"{json.dumps(workflow)}\n")
            result = subprocess.run(
                [
                    sys.executable,
                    str(scripts_dir / "semble-adoption.py"),
                    "1",
                    "--as-of",
                    "2026-08-15",
                    "--root",
                    str(projects_root),
                ],
                capture_output=True,
                check=False,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r"2026-08-15\s+1\s+0\s+1\s+0\s+0\s+1")
        self.assertRegex(result.stdout, r"合計\s+1\s+0\s+1\s+0\s+0")

    def test_rejects_non_positive_and_non_numeric_days_cleanly(self):
        scripts_dir = Path(__file__).parent
        with tempfile.TemporaryDirectory() as temp_dir:
            projects_root = Path(temp_dir) / "projects"
            projects_root.mkdir()
            for invalid in ("0", "-1", "abc"):
                with self.subTest(invalid=invalid):
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(scripts_dir / "semble-adoption.py"),
                            invalid,
                            "--as-of",
                            "2026-08-15",
                            "--root",
                            str(projects_root),
                        ],
                        capture_output=True,
                        check=False,
                        text=True,
                    )
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("usage:", result.stderr)
                    self.assertIn("DAYS must be a positive integer", result.stderr)
                    self.assertNotIn("Traceback", result.stderr)

    def test_rejects_calendar_overflow_cleanly(self):
        scripts_dir = Path(__file__).parent
        cases = (("1000000", "2026-08-15"), ("2", "0001-01-01"))
        with tempfile.TemporaryDirectory() as temp_dir:
            projects_root = Path(temp_dir) / "projects"
            projects_root.mkdir()
            for days, as_of in cases:
                with self.subTest(days=days, as_of=as_of):
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(scripts_dir / "semble-adoption.py"),
                            days,
                            "--as-of",
                            as_of,
                            "--root",
                            str(projects_root),
                        ],
                        capture_output=True,
                        check=False,
                        text=True,
                    )
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("usage:", result.stderr)
                    self.assertIn("requested date range is outside supported calendar", result.stderr)
                    self.assertNotIn("Traceback", result.stderr)

    def test_bad_shapes_do_not_discard_later_valid_record(self):
        scripts_dir = Path(__file__).parent
        records = [
            {
                "timestamp": 123,
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Bash",
                            "input": {"command": "pwd"},
                        }
                    ]
                },
            },
            ["semble"],
            {"timestamp": "2026-08-15T01:00:00Z", "message": "semble"},
            {"timestamp": "2026-08-15T01:01:00Z", "message": {"content": "semble"}},
            {"timestamp": "2026-08-15T01:02:00Z", "message": {"content": ["semble"]}},
            {
                "timestamp": "2026-08-15T01:03:00Z",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "shared-malformed",
                            "name": "Bash",
                            "input": "bad",
                        }
                    ]
                },
            },
            {
                "timestamp": "2026-08-15T01:04:00Z",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "shared-malformed",
                            "name": "mcp__semble__search",
                            "input": {"query": "valid code path", "repo": "/repo"},
                        }
                    ]
                },
            },
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture_home = Path(temp_dir)
            project_dir = fixture_home / ".claude" / "projects" / "fixture-project"
            project_dir.mkdir(parents=True)
            session = project_dir / "session.jsonl"
            session.write_text("".join(f"{json.dumps(record)}\n" for record in records))
            env = os.environ.copy()
            env["HOME"] = str(fixture_home)
            result = subprocess.run(
                [
                    sys.executable,
                    str(scripts_dir / "semble-adoption.py"),
                    "30",
                    "--as-of",
                    "2026-08-15",
                    "--root",
                    str(fixture_home / ".claude" / "projects"),
                ],
                capture_output=True,
                check=False,
                env=env,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r"2026-08-15\s+1\s+0\s+0\s+0\s+0\s+1")
        self.assertRegex(result.stdout, r"合計\s+1\s+0\s+0\s+0\s+0")


if __name__ == "__main__":
    unittest.main()
