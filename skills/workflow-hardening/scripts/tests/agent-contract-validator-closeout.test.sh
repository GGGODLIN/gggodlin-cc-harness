#!/usr/bin/env bash
set -u

SKILL=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/SKILL.md
PASS=0
FAIL=0
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

check() {
  local name=$1
  local condition=$2
  if [ "$condition" -eq 0 ]; then
    PASS=$((PASS + 1))
    printf 'PASS: %s\n' "$name"
  else
    FAIL=$((FAIL + 1))
    printf 'FAIL: %s\n' "$name"
  fi
}

grep -qF '本檔在契約測試底下' "$SKILL"
check 'workflow-hardening marks its contract test' $?
grep -qF 'agent-contract-validator.mjs' "$SKILL"
check 'workflow-hardening names the validator CLI' $?
grep -qF '較貴的 smoke／測試前' "$SKILL"
check 'workflow-hardening places validator before expensive checks' $?
grep -qF '正常 Agent／Workflow 執行不呼叫 validator' "$SKILL"
check 'workflow-hardening keeps validator out of runtime' $?

python3 - "$SKILL" <<'PY'
from pathlib import Path
import sys
lines = Path(sys.argv[1]).read_text().splitlines()
validator = next((index for index, line in enumerate(lines) if 'node ' in line and 'agent-contract-validator.mjs' in line), -1)
pointer = next((index for index, line in enumerate(lines) if '接 §10.3 Agent contract validator closeout' in line), -1)
closeout = next((index for index, line in enumerate(lines) if line.startswith('### 10.3 Agent contract validator closeout')), -1)
pitfalls = next((index for index, line in enumerate(lines) if line.startswith('## 踩過的坑')), -1)
if validator < 0 or pointer < 0 or closeout < 0 or pitfalls < 0 or pointer >= closeout or closeout >= pitfalls:
    raise SystemExit(1)
PY
check 'workflow-hardening closeout is wired from the gate' $?

python3 - "$SKILL" "$TMP/closeout.sh" <<'PY'
from pathlib import Path
import sys
lines = Path(sys.argv[1]).read_text().splitlines()
anchor = next(index for index, line in enumerate(lines) if line.startswith('### 10.3 Agent contract validator closeout'))
start = next(index for index in range(anchor, len(lines)) if lines[index].strip() == '```bash')
end = next(index for index in range(start + 1, len(lines)) if lines[index].strip() == '```')
Path(sys.argv[2]).write_text('\n'.join(lines[start + 1:end]) + '\n')
PY
chmod +x "$TMP/closeout.sh"
WORKTREE_TMP=$(mktemp -d)
MAIN_ROOT="$WORKTREE_TMP/main"
ACTIVE_ROOT="$WORKTREE_TMP/active"
mkdir -p "$MAIN_ROOT/scripts"
printf '%s\n' 'import { writeFileSync } from "node:fs"' 'writeFileSync(process.env.MARKER, "main")' > "$MAIN_ROOT/scripts/agent-contract-validator.mjs"
printf '%s\n' 'initial' > "$MAIN_ROOT/README.md"
git -C "$MAIN_ROOT" init -q
git -C "$MAIN_ROOT" config user.email test@example.com
git -C "$MAIN_ROOT" config user.name test
git -C "$MAIN_ROOT" add .
git -C "$MAIN_ROOT" commit -qm initial
git -C "$MAIN_ROOT" worktree add -q "$ACTIVE_ROOT" -b closeout-worktree
printf '%s\n' 'import { writeFileSync } from "node:fs"' 'writeFileSync(process.env.MARKER, process.argv.includes(process.env.EXPECTED_ROOT) ? "active" : "wrong-root")' > "$ACTIVE_ROOT/scripts/agent-contract-validator.mjs"
EXPECTED_ROOT=$(git -C "$ACTIVE_ROOT" rev-parse --show-toplevel)
MARKER="$WORKTREE_TMP/used" EXPECTED_ROOT="$EXPECTED_ROOT" CLAUDE_CONFIG_DIR="$MAIN_ROOT" bash -c "cd \"$ACTIVE_ROOT\" && bash \"$TMP/closeout.sh\""
if [ -f "$WORKTREE_TMP/used" ] && [ "$(<"$WORKTREE_TMP/used")" = 'active' ]; then
  check 'workflow-hardening closeout uses active global worktree' 0
else
  check 'workflow-hardening closeout uses active global worktree' 1
fi
rm -rf "$WORKTREE_TMP"

printf 'PASS=%s FAIL=%s\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
