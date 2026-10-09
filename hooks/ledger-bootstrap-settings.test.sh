#!/usr/bin/env bash
# 本檔在契約測試底下：bash ~/.claude/hooks/ledger-bootstrap-settings.test.sh
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SETTINGS="$ROOT/settings.json"
python3 - "$SETTINGS" <<'PY'
import json
import sys
from pathlib import Path

settings = json.loads(Path(sys.argv[1]).read_text())
assert settings["model"] == "fable"
assert settings["effortLevel"] == "medium"
entries = settings["hooks"]["SessionStart"][0]["hooks"]
commands = [entry["command"] for entry in entries]
assert commands.count("~/.claude/hooks/ledger-bootstrap.sh") == 1
assert "~/.claude/hooks/session-start-state.sh" in commands
assert commands.index("~/.claude/hooks/session-start-state.sh") < commands.index("~/.claude/hooks/ledger-bootstrap.sh")
print("PASS settings SessionStart bootstrap wiring and model preservation")
PY
