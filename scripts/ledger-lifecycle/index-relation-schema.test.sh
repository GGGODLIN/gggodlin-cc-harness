#!/bin/bash
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLI="$DIR/validate-registry.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

python3 - "$TMP/valid.json" "$TMP/invalid.json" <<'PY'
import json
import sys
from pathlib import Path
base = {
    "schema_version": 1,
    "scan_roots": ["~/Desktop/projects/*"],
    "entries": [{
        "path": "~/source.md",
        "kind": "append",
        "index_path": "~/source.index.md",
        "index_relation": {
            "entry_pattern": r"^### .*\([^)]*\d{4}-\d{2}-\d{2}[^)]*\)$",
            "format": "slug｜verdict｜結案日｜一句理由｜標題原文",
            "anchor_field": 5,
        },
        "threshold": [{"metric": "main_size", "unit": "KB", "operator": ">", "value": 256}],
        "action": "建立索引",
    }],
}
Path(sys.argv[1]).write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")
bad = json.loads(json.dumps(base))
bad["entries"][0]["index_path"] = 7
bad["entries"][0]["index_relation"]["entry_pattern"] = 7
Path(sys.argv[2]).write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
regex_bad = json.loads(json.dumps(base))
regex_bad["entries"][0]["index_relation"]["entry_pattern"] = "["
Path(Path(sys.argv[2]).with_name("invalid-pattern.json")).write_text(json.dumps(regex_bad, ensure_ascii=False), encoding="utf-8")
PY

if ! python3 "$CLI" validate "$TMP/valid.json" >/dev/null; then
  printf '%s\n' 'FAIL valid index relation rejected'
  exit 1
fi
if python3 "$CLI" validate "$TMP/invalid.json" >/dev/null 2>&1; then
  printf '%s\n' 'FAIL invalid index relation accepted'
  exit 1
fi
if python3 "$CLI" validate "$TMP/invalid-pattern.json" >/dev/null 2>&1; then
  printf '%s\n' 'FAIL invalid index regex accepted'
  exit 1
fi
printf '%s\n' 'index relation schema: PASS'
