import re
import tempfile
import unittest
from pathlib import Path


ACTIVE_DIRECTORIES = (
    "agents",
    "skills",
    "commands",
    "rules",
    "hooks",
    "workflows",
    "mcp",
    "mcp-configs",
    ".cursor",
    ".codex",
)
ROOT_HARNESS_FILES = ("CLAUDE.md", "AGENTS.md", "GEMINI.md")
EXCLUDED_PARTS = {
    ".git",
    ".scratch",
    "__pycache__",
    "archive",
    "archived",
    "build",
    "dist",
    "memory",
    "node_modules",
    "out",
    "scratch",
    "trials",
    "tests",
    "evals",
}
RETIRED_TOOL = re.compile(r"mcp__semble-docs__[\w-]*")
RETIRED_SERVER_KEY = re.compile(r'["\']semble-docs["\']\s*:')
RETIRED_TOML_SERVER = re.compile(r"\[\s*mcp_servers\.semble-docs\s*\]")
AVAILABLE_DOCS_MCP = re.compile(
    r"docs(?: 搜尋| search)? MCP|對應 docs 搜尋 MCP|MCP for docs|documentation MCP",
    re.IGNORECASE,
)


def walked_files(base, root):
    files = []
    seen_directories = set()
    stack = [base]
    while stack:
        path = stack.pop()
        try:
            relative = path.relative_to(root)
            if EXCLUDED_PARTS.intersection(relative.parts):
                continue
            stat = path.stat()
            if path.is_dir():
                identity = stat.st_dev, stat.st_ino
                if identity in seen_directories:
                    continue
                seen_directories.add(identity)
                stack.extend(path.iterdir())
            elif path.is_file() and ".test." not in path.name and not path.name.startswith("test_"):
                files.append(path)
        except OSError:
            continue
    return files


def active_files(root):
    paths = []
    for directory in ACTIVE_DIRECTORIES:
        base = root / directory
        if base.exists():
            paths.extend(walked_files(base, root))
    for filename in ROOT_HARNESS_FILES:
        path = root / filename
        if path.is_file():
            paths.append(path)
    paths.extend(path for path in root.glob("settings*.json") if path.is_file())
    return sorted(set(paths))


def retired_references(root):
    findings = []
    for path in active_files(root):
        for line_number, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
            for pattern in (
                RETIRED_TOOL,
                RETIRED_SERVER_KEY,
                RETIRED_TOML_SERVER,
                AVAILABLE_DOCS_MCP,
            ):
                for match in pattern.finditer(line):
                    findings.append(
                        f"{path.relative_to(root)}:{line_number}:{match.group(0)}"
                    )
    return findings


class SembleDocsRetirementTest(unittest.TestCase):
    def test_prose_search_policy_is_consistent_across_active_guidance(self):
        root = Path(__file__).resolve().parent.parent
        documents = {
            "CLAUDE.md": root / "CLAUDE.md",
            "agents/semble-search.md": root / "agents" / "semble-search.md",
            "skills/agent-authoring/SKILL.md": (
                root / "skills" / "agent-authoring" / "SKILL.md"
            ),
        }
        required = {
            "CLAUDE.md": (
                "本機",
                "技術上接受 `content`",
                "可回 Markdown",
                "docs index",
                "cache",
                "多語模型",
                "常駐",
            ),
            "agents/semble-search.md": (
                "Local policy",
                "technically accepts `content`",
                "return Markdown",
                "docs index",
                "cache",
                "multilingual model",
                "resident",
            ),
            "skills/agent-authoring/SKILL.md": (
                "本機散文搜尋政策",
                "技術上可接受 `content`",
                "回傳 Markdown",
                "docs index",
                "cache",
                "多語模型",
                "常駐",
            ),
        }
        forbidden = (
            "takes only `query`",
            "code-only",
            "prose is unreachable",
            "md 不在索引裡",
            "查散文會靜靜回",
            "Markdown 不可達",
        )

        for name, path in documents.items():
            with self.subTest(document=name):
                text = path.read_text()
                for phrase in required[name]:
                    self.assertIn(phrase, text)
                for phrase in forbidden:
                    self.assertNotIn(phrase, text)

    def test_active_harness_has_no_retired_docs_mcp_references(self):
        root = Path(__file__).resolve().parent.parent
        self.assertEqual(retired_references(root), [])

    def test_detects_all_active_surfaces_and_retired_reference_forms(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "harness"
            root.mkdir()
            (root / "CLAUDE.md").write_text("mcp__semble-docs__arbitrary_suffix\n")
            (root / "AGENTS.md").write_text("mcp__semble-docs__agents_suffix\n")
            (root / "GEMINI.md").write_text(
                "not retired: use mcp__semble-docs__search\n"
            )
            (root / "settings.json").write_text(
                '{"mcpServers":{"semble-docs":{"command":"server"}}}\n'
            )
            hooks = root / "hooks"
            hooks.mkdir()
            (hooks / "check.sh").write_text("mcp__semble-docs__hook_suffix\n")
            workflows = root / "workflows"
            workflows.mkdir()
            (workflows / "flow.json").write_text(
                '{"tool":"mcp__semble-docs__workflow_suffix"}\n'
            )
            mcp = root / "mcp"
            mcp.mkdir()
            (mcp / "config.toml").write_text("[mcp_servers.semble-docs]\n")
            mcp_configs = root / "mcp-configs"
            mcp_configs.mkdir()
            (mcp_configs / "docs.txt").write_text("MCP for docs is available\n")
            (mcp_configs / "documentation.txt").write_text(
                "documentation MCP is available\n"
            )
            external = root / "external-skill"
            external.mkdir()
            (external / "SKILL.md").write_text("mcp__semble-docs__linked_suffix\n")
            skills = root / "skills"
            skills.mkdir()
            (skills / "linked").symlink_to(external, target_is_directory=True)
            (external / "cycle").symlink_to(skills, target_is_directory=True)

            findings = retired_references(root)

        self.assertTrue(any(finding.startswith("CLAUDE.md:") for finding in findings))
        self.assertTrue(any(finding.startswith("AGENTS.md:") for finding in findings))
        self.assertTrue(any(finding.startswith("GEMINI.md:") for finding in findings))
        self.assertTrue(any(finding.startswith("settings.json:") for finding in findings))
        self.assertTrue(any(finding.startswith("hooks/check.sh:") for finding in findings))
        self.assertTrue(any(finding.startswith("workflows/flow.json:") for finding in findings))
        self.assertTrue(any(finding.startswith("mcp/config.toml:") for finding in findings))
        self.assertTrue(
            any(finding.startswith("mcp-configs/docs.txt:") for finding in findings)
        )
        self.assertTrue(
            any(
                finding.startswith("mcp-configs/documentation.txt:")
                for finding in findings
            )
        )
        self.assertTrue(
            any(finding.startswith("skills/linked/SKILL.md:") for finding in findings)
        )


if __name__ == "__main__":
    unittest.main()
