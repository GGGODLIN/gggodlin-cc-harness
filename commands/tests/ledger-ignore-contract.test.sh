#!/usr/bin/env bash
# 本檔在契約測試底下：bash ~/.claude/commands/tests/ledger-ignore-contract.test.sh
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMMAND="$ROOT/commands/ledger-ignore.md"
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

check_file "command exists" "$COMMAND" "# Ledger Ignore"
check_file "contract marker" "$COMMAND" "ledger-ignore-contract.test.sh"
check_file "shared helper is used" "$COMMAND" "ledger-bootstrap.py add-ignore"
check_file "canonical repo root is required" "$COMMAND" "canonical"
check_file "one path per line is stated" "$COMMAND" "一行一個絕對路徑"

FIX="$(mktemp -d)"
trap 'rm -R "$FIX"' EXIT
HOME_FIX="$FIX/home"
REPO="$HOME_FIX/Desktop/projects/demo"
IGNORE="$HOME_FIX/.claude/state/ledger-bootstrap-ignore.txt"
mkdir -p "$REPO"
git -C "$REPO" init -q

if HOME="$HOME_FIX" python3 "$HELPER" add-ignore "$REPO" --ignore-file "$IGNORE" >/dev/null 2>&1; then
  check_file "behavior writes canonical ignore path" "$IGNORE" "$REPO"
  HOME="$HOME_FIX" python3 "$HELPER" add-ignore "$REPO" --ignore-file "$IGNORE" >/dev/null 2>&1
  COUNT=$(grep -cF -- "$REPO" "$IGNORE" || true)
  if [ "$COUNT" -eq 1 ]; then
    PASS=$((PASS + 1))
    printf 'PASS behavior is idempotent\n'
  else
    FAIL=$((FAIL + 1))
    printf 'FAIL behavior is idempotent\n'
  fi
else
  FAIL=$((FAIL + 1))
  printf 'FAIL behavior helper add-ignore\n'
fi

printf '%s PASS / %s FAIL\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
