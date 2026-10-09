#!/usr/bin/env bash
# 本檔在契約測試底下：bash ~/.claude/commands/tests/init-project-docs-contract.test.sh
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMMAND="$ROOT/commands/init-project-docs.md"
HELPER="$ROOT/scripts/ledger-bootstrap.py"
PASS=0
FAIL=0

check_file() {
  local name=$1
  local path=$2
  local expected=$3
  if grep -qF -- "$expected" "$path" 2>/dev/null; then
    PASS=$((PASS + 1))
    printf 'PASS %s\n' "$name"
  else
    FAIL=$((FAIL + 1))
    printf 'FAIL %s\n' "$name"
  fi
}

check_file "command exists" "$COMMAND" "# Init Project Docs"
check_file "contract marker" "$COMMAND" "init-project-docs-contract.test.sh"
check_file "shared helper is used" "$COMMAND" "ledger-bootstrap.py init-project-docs"
check_file "git info exclude is explicit" "$COMMAND" ".git/info/exclude"
check_file "CLAUDE pointer is explicit" "$COMMAND" "ledger-lifecycle.md"
check_file "existing files are preserved" "$COMMAND" "不要覆蓋"

FIX="$(mktemp -d)"
trap 'rm -R "$FIX"' EXIT
HOME_FIX="$FIX/home"
REPO="$HOME_FIX/Desktop/work/demo"
mkdir -p "$REPO"
git -C "$REPO" init -q

if HOME="$HOME_FIX" python3 "$HELPER" init-project-docs "$REPO" >/dev/null 2>&1; then
  check_file "behavior creates STATE.md" "$REPO/docs/owner/STATE.md" "current_change: none"
  check_file "behavior creates factcheck log header" "$REPO/docs/owner/factcheck-log.md" "# Factcheck Log"
  check_file "behavior creates proofread log header" "$REPO/docs/owner/proofread-log.md" "# Proofread Log"
  check_file "behavior creates syndication log header" "$REPO/docs/owner/syndication-log.md" "# Syndication Log"
  check_file "behavior creates friction log header" "$REPO/docs/owner/friction-log.md" "# Friction Log"
  check_file "behavior excludes docs directory locally" "$REPO/.git/info/exclude" "docs/owner/"
  check_file "behavior appends CLAUDE pointer" "$REPO/CLAUDE.md" "帳本生命週期"
else
  FAIL=$((FAIL + 1))
  printf 'FAIL behavior helper init-project-docs\n'
fi

PRESERVE="$HOME_FIX/Desktop/work/preserve"
mkdir -p "$PRESERVE/docs/owner"
git -C "$PRESERVE" init -q
printf '%s\n' '# Existing factcheck data' > "$PRESERVE/docs/owner/factcheck-log.md"
printf '%s\n' '# Existing project instructions' > "$PRESERVE/CLAUDE.md"
if HOME="$HOME_FIX" python3 "$HELPER" init-project-docs "$PRESERVE" >/dev/null 2>&1; then
  check_file "behavior preserves existing log" "$PRESERVE/docs/owner/factcheck-log.md" "# Existing factcheck data"
  check_file "behavior preserves existing CLAUDE" "$PRESERVE/CLAUDE.md" "# Existing project instructions"
  if [ ! -e "$PRESERVE/.gitignore" ]; then
    PASS=$((PASS + 1))
    printf 'PASS behavior does not create gitignore\n'
  else
    FAIL=$((FAIL + 1))
    printf 'FAIL behavior does not create gitignore\n'
  fi
  if HOME="$HOME_FIX" python3 "$HELPER" init-project-docs "$PRESERVE" >/dev/null 2>&1; then
    FAIL=$((FAIL + 1))
    printf 'FAIL second init overwrote existing STATE\n'
  else
    PASS=$((PASS + 1))
    printf 'PASS second init refuses existing STATE\n'
  fi
else
  FAIL=$((FAIL + 1))
  printf 'FAIL behavior helper preserves existing files\n'
fi

printf '%s PASS / %s FAIL\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
