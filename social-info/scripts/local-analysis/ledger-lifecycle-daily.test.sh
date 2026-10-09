#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$DIR/ledger-lifecycle-daily.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
ROOT="$TMP/home"
REGISTRY="$TMP/registry.json"
OUT="$TMP/report.md"

mkdir -p "$ROOT/code/demo/docs/owner"
python3 - "$ROOT/code/demo/docs/owner/STATE.md" <<'PY'
import sys
from pathlib import Path
Path(sys.argv[1]).write_bytes(b'x' * 2048)
PY

python3 - "$REGISTRY" <<'PY'
import json
import sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
    "schema_version": 1,
    "scan_roots": ["~/Desktop/work/*", "~/Desktop/projects/*", "~/code/*"],
    "entries": [{
        "path": "~/code/*/docs/owner/STATE.md",
        "kind": "state",
        "threshold": [{"metric": "size", "unit": "KB", "operator": ">", "value": 1}],
        "action": "提醒",
    }],
}, ensure_ascii=False), encoding="utf-8")
PY

bash "$SCRIPT" --root "$ROOT" --registry "$REGISTRY" --date 2026-08-23 --out "$OUT"
grep -F 'ledger-lifecycle:code-demo-docs-owner-state-md-81354bab97cb' "$OUT" >/dev/null
grep -F '超過門檻' "$OUT" >/dev/null

OVERRIDE_REGISTRY="$TMP/override-registry.json"
OVERRIDE_OUT="$TMP/override-report.md"
python3 - "$OVERRIDE_REGISTRY" <<'PY'
import json
import sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
    "schema_version": 1,
    "scan_roots": ["~/Desktop/work/*", "~/Desktop/projects/*", "~/code/*"],
    "entries": [
        {
            "path": "~/code/*/docs/owner/STATE.md",
            "kind": "state",
            "threshold": [{"metric": "size", "unit": "KB", "operator": ">", "value": 1}],
            "action": "樣板提醒",
        },
        {
            "path": "~/code/demo/docs/owner/STATE.md",
            "kind": "state",
            "threshold": [{"metric": "size", "unit": "KB", "operator": ">", "value": 100}],
            "action": "具體提醒",
        },
    ],
}, ensure_ascii=False), encoding="utf-8")
PY
bash "$SCRIPT" --root "$ROOT" --registry "$OVERRIDE_REGISTRY" --date 2026-08-23 --out "$OVERRIDE_OUT"
test "$(<"$OVERRIDE_OUT")" = '__SILENT__'
printf '%s\n' 'ledger-lifecycle daily exact override slice: PASS'

APPEND="$ROOT/append.md"
python3 - "$APPEND" <<'PY'
import sys
from pathlib import Path
Path(sys.argv[1]).write_text('### Old entry (2026-05-01)\n\n### New entry (2026-08-01)\n', encoding='utf-8')
PY
APPEND_REGISTRY="$TMP/append-registry.json"
APPEND_OUT="$TMP/append-report.md"
python3 - "$APPEND_REGISTRY" <<'PY'
import json
import sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
    "schema_version": 1,
    "scan_roots": [],
    "entries": [{
        "path": "~/append.md",
        "kind": "append",
        "threshold": [
            {"metric": "main_size", "unit": "KB", "operator": ">", "value": 0},
            {"metric": "entry_age_months", "unit": "months", "operator": ">", "value": 2},
        ],
        "action": "追加紀錄提醒",
    }],
}, ensure_ascii=False), encoding="utf-8")
PY
bash "$SCRIPT" --root "$ROOT" --registry "$APPEND_REGISTRY" --date 2026-08-23 --out "$APPEND_OUT"
grep -F 'entry_age_months' "$APPEND_OUT" >/dev/null
printf '%s\n' 'ledger-lifecycle daily append metrics slice: PASS'

mkdir -p "$ROOT/residue/old-copy"
RESIDUE_FILE="$ROOT/residue/completed.md"
python3 - "$RESIDUE_FILE" "$ROOT/residue/old-copy" <<'PY'
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
Path(sys.argv[1]).write_text('completed_at: 2026-07-01\n', encoding='utf-8')
old = datetime(2026, 8, 1, tzinfo=timezone.utc).timestamp()
os.utime(sys.argv[2], (old, old))
PY
RESIDUE_REGISTRY="$TMP/residue-registry.json"
RESIDUE_OUT="$TMP/residue-report.md"
python3 - "$RESIDUE_REGISTRY" <<'PY'
import json
import sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
    "schema_version": 1,
    "scan_roots": [],
    "entries": [
        {
            "path": "~/residue/old-copy",
            "kind": "residue",
            "threshold": [{"metric": "directory_age", "unit": "days", "operator": ">", "value": 10}],
            "action": "提醒整理",
        },
        {
            "path": "~/residue/completed.md",
            "kind": "residue",
            "threshold": [{"metric": "age_since_completion", "unit": "days", "operator": ">", "value": 30}],
            "action": "提醒整理",
        },
    ],
}, ensure_ascii=False), encoding="utf-8")
PY
bash "$SCRIPT" --root "$ROOT" --registry "$RESIDUE_REGISTRY" --date 2026-08-23 --out "$RESIDUE_OUT"
grep -F 'directory_age' "$RESIDUE_OUT" >/dev/null
grep -F 'age_since_completion' "$RESIDUE_OUT" >/dev/null
printf '%s\n' 'ledger-lifecycle daily residue metrics slice: PASS'

STATUS_FILE="$ROOT/residue/status.md"
printf '%s\n' 'status: active' > "$STATUS_FILE"
STATUS_REGISTRY="$TMP/status-registry.json"
STATUS_OUT="$TMP/status-report.md"
python3 - "$STATUS_REGISTRY" <<'PY'
import json
import sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
    "schema_version": 1,
    "scan_roots": [],
    "entries": [{
        "path": "~/residue/status.md",
        "kind": "residue",
        "threshold": [{"metric": "status", "unit": "state", "operator": "equals", "value": "active"}],
        "action": "保持不動",
    }],
}, ensure_ascii=False), encoding="utf-8")
PY
bash "$SCRIPT" --root "$ROOT" --registry "$STATUS_REGISTRY" --date 2026-08-23 --out "$STATUS_OUT"
grep -F 'status' "$STATUS_OUT" >/dev/null
printf '%s\n' 'ledger-lifecycle daily residue status slice: PASS'

JSON_STATUS_REGISTRY="$TMP/json-status-registry.json"
JSON_STATUS_OUT="$TMP/json-status-report.md"
python3 - "$ROOT" "$JSON_STATUS_REGISTRY" <<'PY'
import json
import sys
from pathlib import Path
root = Path(sys.argv[1]) / 'json-status'
root.mkdir()
for name, payload in {
  'array': [{'status': 'active'}],
  'null': None,
  'string': 'active',
  'number': 1,
  'boolean': True,
  'empty-object': {},
  'z-active': {'status': 'active'},
}.items():
  (root / f'{name}.json').write_text(json.dumps(payload), encoding='utf-8')
Path(sys.argv[2]).write_text(json.dumps({
  'schema_version': 1,
  'scan_roots': ['~/json-status/*'],
  'entries': [{
    'path': '~/json-status/*.json',
    'kind': 'residue',
    'threshold': [{'metric': 'status', 'unit': 'state', 'operator': 'equals', 'value': 'active'}],
    'action': '保持不動',
  }],
}, ensure_ascii=False), encoding='utf-8')
PY
bash "$SCRIPT" --root "$ROOT" --registry "$JSON_STATUS_REGISTRY" --date 2026-08-23 --out "$JSON_STATUS_OUT"
grep -F 'json-status/z-active.json' "$JSON_STATUS_OUT" >/dev/null
test "$(grep -c '| status |' "$JSON_STATUS_OUT")" = 1
printf '%s\n' 'ledger-lifecycle daily JSON status shapes slice: PASS'

COMPLETION_DIR="$ROOT/scratch/completed-work"
mkdir -p "$COMPLETION_DIR"
printf '%s\n' 'status: completed' 'completed_at: 2026-07-01' > "$COMPLETION_DIR/status.md"
COMPLETION_REGISTRY="$TMP/completion-registry.json"
COMPLETION_OUT="$TMP/completion-report.md"
python3 - "$COMPLETION_REGISTRY" <<'PY'
import json
import sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
    "schema_version": 1,
    "scan_roots": [],
    "entries": [{
        "path": "~/scratch/completed-work",
        "kind": "residue",
        "threshold": [{"metric": "age_since_completion", "unit": "days", "operator": ">", "value": 30}],
        "action": "提醒搬遷",
    }],
}, ensure_ascii=False), encoding="utf-8")
PY
bash "$SCRIPT" --root "$ROOT" --registry "$COMPLETION_REGISTRY" --date 2026-08-23 --out "$COMPLETION_OUT"
grep -F 'age_since_completion' "$COMPLETION_OUT" >/dev/null
printf '%s\n' 'ledger-lifecycle daily directory completion age slice: PASS'

INDEX_MAIN="$ROOT/archived.md"
INDEX_FILE="$ROOT/archived.index.md"
python3 - "$INDEX_MAIN" "$INDEX_FILE" <<'PY'
import sys
from pathlib import Path
Path(sys.argv[1]).write_text('### Trial A (2026-05-01)\n\n### Trial B (2026-06-01)\n', encoding='utf-8')
Path(sys.argv[2]).write_text('trial-a|KEEP|2026-05-01|reason|### Trial A (2026-05-01)\n', encoding='utf-8')
PY
INDEX_REGISTRY="$TMP/index-registry.json"
INDEX_OUT="$TMP/index-report.md"
python3 - "$INDEX_REGISTRY" <<'PY'
import json
import sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
    "schema_version": 1,
    "scan_roots": [],
    "entries": [{
        "path": "~/archived.md",
        "kind": "append",
        "index_path": "~/archived.index.md",
        "threshold": [{"metric": "main_size", "unit": "KB", "operator": ">", "value": 100}],
        "action": "建立索引",
    }],
}, ensure_ascii=False), encoding="utf-8")
PY
bash "$SCRIPT" --root "$ROOT" --registry "$INDEX_REGISTRY" --date 2026-08-23 --out "$INDEX_OUT"
grep -F 'ledger-lifecycle:index-drift:archived.md' "$INDEX_OUT" >/dev/null
grep -F '索引行數' "$INDEX_OUT" >/dev/null
printf '%s\n' 'ledger-lifecycle daily index drift slice: PASS'

NO_REL_MAIN="$ROOT/no-relation.md"
NO_REL_INDEX="$ROOT/no-relation.index.md"
printf '%s\n' '### One entry (2026-05-01)' > "$NO_REL_MAIN"
printf '%s\n' 'extra row' > "$NO_REL_INDEX"
NO_REL_REGISTRY="$TMP/no-relation-registry.json"
NO_REL_OUT="$TMP/no-relation-report.md"
python3 - "$NO_REL_REGISTRY" <<'PY'
import json
import sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
    "schema_version": 1,
    "scan_roots": [],
    "entries": [{
        "path": "~/no-relation.md",
        "kind": "append",
        "threshold": [{"metric": "main_size", "unit": "KB", "operator": ">", "value": 100}],
        "action": "建立索引",
    }],
}, ensure_ascii=False), encoding="utf-8")
PY
bash "$SCRIPT" --root "$ROOT" --registry "$NO_REL_REGISTRY" --date 2026-08-23 --out "$NO_REL_OUT"
test "$(<"$NO_REL_OUT")" = '__SILENT__'
printf '%s\n' 'ledger-lifecycle daily index relation guard slice: PASS'

SCOPE_ROOT="$TMP/scope-home"
mkdir -p "$SCOPE_ROOT/code/empty/docs/owner" "$SCOPE_ROOT/outside/docs/owner"
python3 - "$SCOPE_ROOT/outside/docs/owner/STATE.md" <<'PY'
import sys
from pathlib import Path
Path(sys.argv[1]).write_bytes(b'x' * 2048)
PY
SCOPE_REGISTRY="$TMP/scope-registry.json"
SCOPE_OUT="$TMP/scope-report.md"
python3 - "$SCOPE_REGISTRY" <<'PY'
import json
import sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
    "schema_version": 1,
    "scan_roots": ["~/Desktop/work/*", "~/Desktop/projects/*", "~/code/*"],
    "entries": [{
        "path": "~/code/*/docs/owner/STATE.md",
        "kind": "state",
        "threshold": [{"metric": "size", "unit": "KB", "operator": ">", "value": 1}],
        "action": "提醒",
    }],
}, ensure_ascii=False), encoding="utf-8")
PY
bash "$SCRIPT" --root "$SCOPE_ROOT" --registry "$SCOPE_REGISTRY" --date 2026-08-23 --out "$SCOPE_OUT"
test "$(<"$SCOPE_OUT")" = '__SILENT__'
printf '%s\n' 'ledger-lifecycle daily scan scope slice: PASS'

SYMLINK_ROOT="$TMP/symlink-home"
SYMLINK_OUTSIDE="$TMP/symlink-outside"
mkdir -p "$SYMLINK_ROOT/code/linked" "$SYMLINK_OUTSIDE/docs/owner"
python3 - "$SYMLINK_OUTSIDE/docs/owner/STATE.md" <<'PY'
import sys
from pathlib import Path
Path(sys.argv[1]).write_bytes(b'x' * 2048)
PY
rm -rf "$SYMLINK_ROOT/code/linked"
ln -s "$SYMLINK_OUTSIDE" "$SYMLINK_ROOT/code/linked"
SYMLINK_REGISTRY="$TMP/symlink-registry.json"
SYMLINK_REPORT="$TMP/symlink-report.md"
python3 - "$SYMLINK_REGISTRY" <<'PY'
import json
import sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
    "schema_version": 1,
    "scan_roots": ["~/code/*"],
    "entries": [{
        "path": "~/code/*/docs/owner/STATE.md",
        "kind": "state",
        "threshold": [{"metric": "size", "unit": "KB", "operator": ">", "value": 1}],
        "action": "提醒",
    }],
}, ensure_ascii=False), encoding="utf-8")
PY
bash "$SCRIPT" --root "$SYMLINK_ROOT" --registry "$SYMLINK_REGISTRY" --date 2026-08-23 --out "$SYMLINK_REPORT"
if [ "$(<"$SYMLINK_REPORT")" = '__SILENT__' ]; then
  printf '%s\n' 'ledger-lifecycle daily symlink boundary slice: PASS'
else
  printf '%s\n' 'FAIL ledger-lifecycle daily symlink boundary slice'
  cat "$SYMLINK_REPORT"
  exit 1
fi

STABLE_OUT_A="$TMP/stable-a.md"
STABLE_OUT_B="$TMP/stable-b.md"
bash "$SCRIPT" --root "$ROOT" --registry "$REGISTRY" --date 2026-08-23 --out "$STABLE_OUT_A"
bash "$SCRIPT" --root "$ROOT" --registry "$REGISTRY" --date 2026-08-24 --out "$STABLE_OUT_B"
KEY_A="$(grep -o 'ledger-lifecycle:[a-z0-9-]*' "$STABLE_OUT_A" | head -1)"
KEY_B="$(grep -o 'ledger-lifecycle:[a-z0-9-]*' "$STABLE_OUT_B" | head -1)"
test "$KEY_A" = "$KEY_B"
! grep -F '超過門檻：2026-' "$STABLE_OUT_A" >/dev/null
printf '%s\n' 'ledger-lifecycle daily source key slice: PASS'

COLLISION_ROOT="$TMP/collision-home"
mkdir -p "$COLLISION_ROOT/Desktop/work/demo/docs/owner" "$COLLISION_ROOT/Desktop/projects/demo/docs/owner"
python3 - "$COLLISION_ROOT/Desktop/work/demo/docs/owner/STATE.md" "$COLLISION_ROOT/Desktop/projects/demo/docs/owner/STATE.md" <<'PY'
import sys
from pathlib import Path
for value in sys.argv[1:]:
    Path(value).write_bytes(b'x' * 2048)
PY
COLLISION_REGISTRY="$TMP/collision-registry.json"
COLLISION_OUT="$TMP/collision-report.md"
python3 - "$COLLISION_REGISTRY" <<'PY'
import json
import sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
    "schema_version": 1,
    "scan_roots": ["~/Desktop/work/*", "~/Desktop/projects/*", "~/code/*"],
    "entries": [
        {
            "path": "~/Desktop/work/*/docs/owner/STATE.md",
            "kind": "state",
            "threshold": [{"metric": "size", "unit": "KB", "operator": ">", "value": 1}],
            "action": "提醒",
        },
        {
            "path": "~/Desktop/projects/*/docs/owner/STATE.md",
            "kind": "state",
            "threshold": [{"metric": "size", "unit": "KB", "operator": ">", "value": 1}],
            "action": "提醒",
        },
    ],
}, ensure_ascii=False), encoding="utf-8")
PY
bash "$SCRIPT" --root "$COLLISION_ROOT" --registry "$COLLISION_REGISTRY" --date 2026-08-23 --out "$COLLISION_OUT"
WORK_KEY_COUNT="$(grep -o 'ledger-lifecycle:work-demo-docs-owner-state-md-4f9df5773652' "$COLLISION_OUT" | wc -l | tr -d ' ')"
PROJECTS_KEY_COUNT="$(grep -o 'ledger-lifecycle:projects-demo-docs-owner-state-md-6c55c15142af' "$COLLISION_OUT" | wc -l | tr -d ' ')"
test "$WORK_KEY_COUNT" = 1
test "$PROJECTS_KEY_COUNT" = 1
! grep -F 'ledger-lifecycle:demo-docs-owner-state-md' "$COLLISION_OUT" >/dev/null
printf '%s\n' 'ledger-lifecycle daily scan-root source key slice: PASS'

PUNCT_ROOT="$TMP/punctuation-home"
mkdir -p "$PUNCT_ROOT/code/foo-bar/docs/owner" "$PUNCT_ROOT/code/foo_bar/docs/owner"
python3 - "$PUNCT_ROOT/code/foo-bar/docs/owner/STATE.md" "$PUNCT_ROOT/code/foo_bar/docs/owner/STATE.md" <<'PY'
import sys
from pathlib import Path
for value in sys.argv[1:]:
    Path(value).write_bytes(b'x' * 2048)
PY
PUNCT_REGISTRY="$TMP/punctuation-registry.json"
PUNCT_OUT_A="$TMP/punctuation-a.md"
PUNCT_OUT_B="$TMP/punctuation-b.md"
python3 - "$PUNCT_REGISTRY" <<'PY'
import json
import sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
    "schema_version": 1,
    "scan_roots": ["~/code/*"],
    "entries": [{
        "path": "~/code/*/docs/owner/STATE.md",
        "kind": "state",
        "threshold": [{"metric": "size", "unit": "KB", "operator": ">", "value": 1}],
        "action": "提醒",
    }],
}, ensure_ascii=False), encoding="utf-8")
PY
bash "$SCRIPT" --root "$PUNCT_ROOT" --registry "$PUNCT_REGISTRY" --date 2026-08-23 --out "$PUNCT_OUT_A"
bash "$SCRIPT" --root "$PUNCT_ROOT" --registry "$PUNCT_REGISTRY" --date 2026-08-24 --out "$PUNCT_OUT_B"
PUNCT_PATTERN='ledger-lifecycle:code-foo-bar-docs-owner-state-md-[a-f0-9]\{12\}'
PUNCT_COUNT="$(grep -o "$PUNCT_PATTERN" "$PUNCT_OUT_A" | sort -u | wc -l | tr -d ' ')"
PUNCT_KEYS_A="$(grep -o "$PUNCT_PATTERN" "$PUNCT_OUT_A" | sort -u)"
PUNCT_KEYS_B="$(grep -o "$PUNCT_PATTERN" "$PUNCT_OUT_B" | sort -u)"
if [ "$PUNCT_COUNT" = 2 ] && [ "$PUNCT_KEYS_A" = "$PUNCT_KEYS_B" ]; then
  printf '%s\n' 'ledger-lifecycle daily punctuation source key slice: PASS'
else
  printf '%s\n' 'FAIL ledger-lifecycle daily punctuation source key slice'
  printf 'day1=%s\nday2=%s\n' "$PUNCT_KEYS_A" "$PUNCT_KEYS_B"
  exit 1
fi

ENV_REGISTRY="$TMP/env-registry.json"
ENV_OUT="$TMP/env-report.md"
python3 - "$ENV_REGISTRY" <<'PY'
import json
import sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
    "schema_version": 1,
    "scan_roots": ["~/code/*"],
    "entries": [{
        "path": "~/code/*/docs/owner/STATE.md",
        "kind": "state",
        "threshold": [{"metric": "size", "unit": "KB", "operator": ">", "value": 100}],
        "action": "提醒",
    }],
}, ensure_ascii=False), encoding="utf-8")
PY
LOCAL_ANALYSIS_DATE=2026-08-23 LEDGER_LIFECYCLE_STATE_SIZE_KB_CAP=1 bash "$SCRIPT" --root "$ROOT" --registry "$ENV_REGISTRY" --out "$ENV_OUT"
grep -F '# Ledger lifecycle — 2026-08-23' "$ENV_OUT" >/dev/null
grep -F '> 1 KB |' "$ENV_OUT" >/dev/null
printf '%s\n' 'ledger-lifecycle daily env contract slice: PASS'

LINE_FILE="$ROOT/line-count.md"
printf '%s\n' 'first' 'second' > "$LINE_FILE"
LINE_REGISTRY="$TMP/line-registry.json"
LINE_OUT="$TMP/line-report.md"
python3 - "$LINE_REGISTRY" <<'PY'
import json
import sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
    "schema_version": 1,
    "scan_roots": [],
    "entries": [{
        "path": "~/line-count.md",
        "kind": "state",
        "threshold": [{"metric": "line_count", "unit": "lines", "operator": ">", "value": 1}],
        "action": "提醒",
    }],
}, ensure_ascii=False), encoding="utf-8")
PY
bash "$SCRIPT" --root "$ROOT" --registry "$LINE_REGISTRY" --date 2026-08-23 --out "$LINE_OUT"
grep -F 'line_count' "$LINE_OUT" >/dev/null
printf '%s\n' 'ledger-lifecycle daily line count slice: PASS'

HARD_ROOT="$TMP/hard-home"
mkdir -p "$HARD_ROOT/code/hard/docs/owner"
python3 - "$HARD_ROOT/code/hard/docs/owner/STATE.md" <<'PY'
import sys
from pathlib import Path
Path(sys.argv[1]).write_bytes(b'x' * (257 * 1024))
PY
HARD_REGISTRY="$TMP/hard-registry.json"
HARD_OUT="$TMP/hard-report.md"
python3 - "$HARD_REGISTRY" <<'PY'
import json
import sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
    "schema_version": 1,
    "scan_roots": ["~/code/*"],
    "entries": [{
        "path": "~/code/*/docs/owner/STATE.md",
        "kind": "state",
        "threshold": [{"metric": "size", "unit": "KB", "operator": ">", "value": 1}],
        "action": "提醒",
    }],
}, ensure_ascii=False), encoding="utf-8")
PY
bash "$SCRIPT" --root "$HARD_ROOT" --registry "$HARD_REGISTRY" --date 2026-08-23 --out "$HARD_OUT"
grep -F '已故障' "$HARD_OUT" >/dev/null
printf '%s\n' 'ledger-lifecycle daily hard failure slice: PASS'

UNIT_ROOT="$TMP/unit-home"
mkdir -p "$UNIT_ROOT"
python3 - "$UNIT_ROOT/small.md" "$UNIT_ROOT/medium.md" <<'PY'
import sys
from pathlib import Path
Path(sys.argv[1]).write_bytes(b'x' * 300)
Path(sys.argv[2]).write_bytes(b'x' * (257 * 1024))
PY
SMALL_REGISTRY="$TMP/small-registry.json"
SMALL_OUT="$TMP/small-report.md"
python3 - "$SMALL_REGISTRY" <<'PY'
import json
import sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
    "schema_version": 1,
    "scan_roots": [],
    "entries": [{
        "path": "~/small.md",
        "kind": "state",
        "threshold": [{"metric": "size_bytes", "unit": "bytes", "operator": ">", "value": 100}],
        "action": "提醒",
    }],
}, ensure_ascii=False), encoding="utf-8")
PY
bash "$SCRIPT" --root "$UNIT_ROOT" --registry "$SMALL_REGISTRY" --date 2026-08-23 --out "$SMALL_OUT"
grep -F 'small.md' "$SMALL_OUT" >/dev/null
! grep -F '已故障' "$SMALL_OUT" >/dev/null
MB_REGISTRY="$TMP/mb-registry.json"
MB_OUT="$TMP/mb-report.md"
python3 - "$MB_REGISTRY" <<'PY'
import json
import sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
    "schema_version": 1,
    "scan_roots": [],
    "entries": [{
        "path": "~/medium.md",
        "kind": "state",
        "threshold": [{"metric": "size", "unit": "MB", "operator": ">", "value": 0.1}],
        "action": "提醒",
    }],
}, ensure_ascii=False), encoding="utf-8")
PY
bash "$SCRIPT" --root "$UNIT_ROOT" --registry "$MB_REGISTRY" --date 2026-08-23 --out "$MB_OUT"
grep -F '已故障' "$MB_OUT" >/dev/null
printf '%s\n' 'ledger-lifecycle daily hard failure units slice: PASS'

TRIAL_ROOT="$TMP/trial-home"
ARCHIVED_TRIAL_DIR="$TRIAL_ROOT/Desktop/projects/.claude/trials/archive/closed/snapshot/before/dirs"
ARCHIVED_OTHER_DIR="$TRIAL_ROOT/Desktop/projects/.claude/trials/archive/closed/other-residue"
TRIAL_DIR="$TRIAL_ROOT/Desktop/projects/.claude/trials/closed/snapshot/before/dirs"
mkdir -p "$ARCHIVED_TRIAL_DIR/old-copy" "$ARCHIVED_OTHER_DIR" "$TRIAL_DIR/old-copy"
printf '%s\n' 'archived file' > "$ARCHIVED_TRIAL_DIR/old-copy/file.txt"
printf '%s\n' 'nested file' > "$TRIAL_DIR/old-copy/file.txt"
TRIAL_REGISTRY="$TMP/trial-registry.json"
TRIAL_OUT="$TMP/trial-report.md"
python3 - "$TRIAL_REGISTRY" <<'PY'
import json
import sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
    "schema_version": 1,
    "scan_roots": ["~/Desktop/work/*", "~/Desktop/projects/*", "~/code/*"],
    "entries": [
        {
            "path": "~/Desktop/projects/.claude/trials/**/snapshot/before/dirs",
            "kind": "residue",
            "threshold": [{"metric": "legacy_dirs_present", "unit": "boolean", "operator": "equals", "value": True}],
            "action": "提醒縮形",
        },
        {
            "path": "~/Desktop/projects/.claude/trials/archive/**/other-residue",
            "kind": "residue",
            "threshold": [{"metric": "exists", "unit": "boolean", "operator": "equals", "value": True}],
            "action": "提醒其他殘留",
        },
    ],
}, ensure_ascii=False), encoding="utf-8")
PY
bash "$SCRIPT" --root "$TRIAL_ROOT" --registry "$TRIAL_REGISTRY" --date 2026-08-23 --out "$TRIAL_OUT"
grep -F 'trials/closed/snapshot/before/dirs' "$TRIAL_OUT" >/dev/null
! grep -F 'trials/archive/closed/snapshot/before/dirs' "$TRIAL_OUT" >/dev/null
grep -F 'trials/archive/closed/other-residue' "$TRIAL_OUT" >/dev/null
! grep -F 'file.txt' "$TRIAL_OUT" >/dev/null
test "$(grep -c '| legacy_dirs_present |' "$TRIAL_OUT")" = 1
mkdir -p "$TRIAL_ROOT/Desktop/projects/.claude/trials/active-trial/snapshot/before/dirs/old-copy"
printf '%s\n' '## active-trial (2026-08-01)' > "$TRIAL_ROOT/Desktop/projects/.claude/trials/active.md"
bash "$SCRIPT" --root "$TRIAL_ROOT" --registry "$TRIAL_REGISTRY" --date 2026-08-23 --out "$TRIAL_OUT"
grep -F 'trials/closed/snapshot/before/dirs' "$TRIAL_OUT" >/dev/null
! grep -F 'trials/archive/closed/snapshot/before/dirs' "$TRIAL_OUT" >/dev/null
grep -F 'trials/archive/closed/other-residue' "$TRIAL_OUT" >/dev/null
! grep -F 'active-trial' "$TRIAL_OUT" >/dev/null
rm -rf "$TRIAL_DIR"
bash "$SCRIPT" --root "$TRIAL_ROOT" --registry "$TRIAL_REGISTRY" --date 2026-08-23 --out "$TRIAL_OUT"
! grep -F 'trials/archive/closed/snapshot/before/dirs' "$TRIAL_OUT" >/dev/null
grep -F 'trials/archive/closed/other-residue' "$TRIAL_OUT" >/dev/null
printf '%s\n' 'ledger-lifecycle daily residue archive slice: PASS'

UNKNOWN_ROOT="$TMP/unknown-metric-home"
mkdir -p "$UNKNOWN_ROOT"
printf '%s\n' 'unknown metric fixture' > "$UNKNOWN_ROOT/unknown.md"
UNKNOWN_REGISTRY="$TMP/unknown-metric-registry.json"
UNKNOWN_OUT="$TMP/unknown-metric-report.md"
python3 - "$UNKNOWN_REGISTRY" <<'PY'
import json
import sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
    "schema_version": 1,
    "scan_roots": [],
    "entries": [{
        "path": "~/unknown.md",
        "kind": "state",
        "threshold": [{"metric": "unknown_metric", "unit": "units", "operator": ">", "value": 1}],
        "action": "提醒",
    }],
}, ensure_ascii=False), encoding="utf-8")
PY
if bash "$SCRIPT" --root "$UNKNOWN_ROOT" --registry "$UNKNOWN_REGISTRY" --date 2026-08-23 --out "$UNKNOWN_OUT"; then
  printf '%s\n' 'FAIL ledger-lifecycle daily unknown metric was accepted'
  cat "$UNKNOWN_OUT"
  exit 1
else
  printf '%s\n' 'ledger-lifecycle daily unknown metric failure slice: PASS'
fi

FRICTION_ROOT="$TMP/friction-home"
FRICTION_FILE="$FRICTION_ROOT/friction-ledger.md"
mkdir -p "$FRICTION_ROOT"
printf '%s\n' \
  '# fixture' \
  '' \
  '## 待折' \
  '' \
  '- 2026-08-22 pending' \
  '' \
  '## 已折 / 已否決' \
  '' \
  '- 2026-05-24 older one' \
  '- 2026-05-24 older two' \
  '### entry detail' \
  '' \
  '## 後續同層' \
  '' \
  '- 2020-01-01 sibling must not count' \
  > "$FRICTION_FILE"
test "$(wc -c < "$FRICTION_FILE" | tr -d ' ')" -lt 65536
FRICTION_REGISTRY="$TMP/friction-registry.json"
FRICTION_OUT_A="$TMP/friction-a.md"
FRICTION_OUT_B="$TMP/friction-b.md"
python3 - "$FRICTION_REGISTRY" <<'PY'
import json
import sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
    "schema_version": 1,
    "scan_roots": [],
    "entries": [{
        "path": "~/friction-ledger.md",
        "kind": "state",
        "threshold": [{"metric": "friction_age_days", "unit": "days", "operator": ">", "value": 90}],
        "action": "提醒退場",
    }],
}, ensure_ascii=False), encoding="utf-8")
PY
bash "$SCRIPT" --root "$FRICTION_ROOT" --registry "$FRICTION_REGISTRY" --date 2026-08-23 --out "$FRICTION_OUT_A"
bash "$SCRIPT" --root "$FRICTION_ROOT" --registry "$FRICTION_REGISTRY" --date 2026-08-24 --out "$FRICTION_OUT_B"
FRICTION_KEY_A="$(grep -o 'ledger-lifecycle:[a-z0-9-]*' "$FRICTION_OUT_A" | sort -u)"
FRICTION_KEY_B="$(grep -o 'ledger-lifecycle:[a-z0-9-]*' "$FRICTION_OUT_B" | sort -u)"
if [ "$(grep -c '| friction_age_days |' "$FRICTION_OUT_A")" = 1 ] && grep -F '候選 2 筆' "$FRICTION_OUT_A" >/dev/null && [ "$FRICTION_KEY_A" = "$FRICTION_KEY_B" ]; then
  printf '%s\n' 'ledger-lifecycle daily friction retirement slice: PASS'
else
  printf '%s\n' 'FAIL ledger-lifecycle daily friction retirement slice'
  cat "$FRICTION_OUT_A"
  exit 1
fi

FRICTION_BOUNDARY_FILE="$FRICTION_ROOT/friction-boundary.md"
FRICTION_BOUNDARY_OUT="$TMP/friction-boundary.md"
printf '%s\n' \
  '# fixture' \
  '' \
  '## 待折' \
  '' \
  '## 已折／已否決' \
  '' \
  '- 2026-05-25 exactly 90 days' \
  > "$FRICTION_BOUNDARY_FILE"
FRICTION_BOUNDARY_REGISTRY="$TMP/friction-boundary-registry.json"
python3 - "$FRICTION_BOUNDARY_REGISTRY" <<'PY'
import json
import sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
    "schema_version": 1,
    "scan_roots": [],
    "entries": [{
        "path": "~/friction-boundary.md",
        "kind": "state",
        "threshold": [{"metric": "friction_age_days", "unit": "days", "operator": ">", "value": 90}],
        "action": "提醒退場",
    }],
}, ensure_ascii=False), encoding="utf-8")
PY
bash "$SCRIPT" --root "$FRICTION_ROOT" --registry "$FRICTION_BOUNDARY_REGISTRY" --date 2026-08-23 --out "$FRICTION_BOUNDARY_OUT"
test "$(<"$FRICTION_BOUNDARY_OUT")" = '__SILENT__'
printf '%s\n' 'ledger-lifecycle daily friction 90-day boundary slice: PASS'
