#!/bin/bash
set -u

SCRIPT="$(dirname "$0")/model-routing.sh"
RUNTIME="$(dirname "$0")/../hooks/memory-ripple-runtime.py"
TMP=$(mktemp -d)
MARKER="$TMP/pwn-marker"
PASS=0
FAIL=0
trap 'rm -r "$TMP"' EXIT

python_value() {
  CLAUDE_MODEL_ROUTING_FILE="$1" MEMORY_RIPPLE_TEST_MODE=1 /usr/bin/python3 - "$RUNTIME" <<'PY'
import importlib.util
import sys

spec = importlib.util.spec_from_file_location("model_routing_runtime", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print(module.gemini_flash_model())
PY
}

check_case() {
  local name="$1" expected="$2" content="$3" shell_value shell_status python_result
  local file="$TMP/$name.env"
  printf '%s\n' "$content" > "$file"
  shell_value=$(bash "$SCRIPT" GEMINI_FLASH_MODEL "$file" 2>/dev/null)
  shell_status=$?
  python_result=$(python_value "$file")
  if [[ -n "$expected" && "$shell_status" -eq 0 && "$shell_value" == "$expected" && "$python_result" == "$expected" ]]; then
    PASS=$((PASS + 1)); printf 'PASS %s\n' "$name"; return
  fi
  if [[ -z "$expected" && "$shell_status" -ne 0 && -z "$shell_value" && -z "$python_result" ]]; then
    PASS=$((PASS + 1)); printf 'PASS %s\n' "$name"; return
  fi
  FAIL=$((FAIL + 1)); printf 'FAIL %s shell_status=%s shell=%s python=%s\n' "$name" "$shell_status" "$shell_value" "$python_result"
}

check_case unquoted gemini-3.8-flash-high 'GEMINI_FLASH_MODEL=gemini-3.8-flash-high'
check_case quoted gemini-3.8-flash-medium 'GEMINI_FLASH_MODEL="gemini-3.8-flash-medium"'
check_case whitespace gemini-3.8-flash-low 'GEMINI_FLASH_MODEL=  gemini-3.8-flash-low  '
check_case duplicate '' $'GEMINI_FLASH_MODEL=gemini-3.8-flash-high\nGEMINI_FLASH_MODEL=gemini-3.7-flash-high'
check_case inline-comment '' 'GEMINI_FLASH_MODEL=gemini-3.8-flash-high # current'
check_case wrong-provider '' 'GEMINI_FLASH_MODEL=groq-qwen-3.8-27b'
check_case command-substitution '' 'GEMINI_FLASH_MODEL=$(touch '"$MARKER"')'

if [ ! -e "$MARKER" ]; then
  PASS=$((PASS + 1)); printf 'PASS command-substitution-not-executed\n'
else
  FAIL=$((FAIL + 1)); printf 'FAIL command-substitution-executed\n'
fi

UNKNOWN=$(bash "$SCRIPT" UNKNOWN_MODEL "$TMP/unquoted.env" 2>/dev/null)
UNKNOWN_STATUS=$?
if [ "$UNKNOWN_STATUS" -ne 0 ] && [ -z "$UNKNOWN" ]; then
  PASS=$((PASS + 1)); printf 'PASS unknown-key\n'
else
  FAIL=$((FAIL + 1)); printf 'FAIL unknown-key\n'
fi

printf '%s pass, %s fail\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] && printf 'MODEL_ROUTING_TEST_OK\n'
[ "$FAIL" -eq 0 ]
