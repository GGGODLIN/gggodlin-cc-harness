#!/bin/bash
set -u

ROOT="${REVIEWER_AGENT_ROOT:-$HOME/.claude/agents}"
CODE="$ROOT/code-reviewer.md"
PYTHON="$ROOT/python-reviewer.md"
TYPESCRIPT="$ROOT/typescript-reviewer.md"
PASS=0
FAIL=0

contains() {
  local file="$1"
  local pattern="$2"
  local label="$3"
  if grep -Fq "$pattern" "$file"; then
    printf 'PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf 'FAIL: %s\n' "$label"
    FAIL=$((FAIL + 1))
  fi
}

description_equals() {
  local file="$1"
  local expected="$2"
  local label="$3"
  local actual
  actual=$(grep '^description:' "$file")
  if [ "$actual" = "description: $expected" ]; then
    printf 'PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf 'FAIL: %s\n' "$label"
    FAIL=$((FAIL + 1))
  fi
}

description_equals "$CODE" 'Expert cross-boundary code reviewer for quality, security, and maintainability. Use for cross-repository, cross-language, cross-module, public-contract, integration-wiring changes, or when no language reviewer exists. Do not use redundantly for a local single-language diff already covered by python-reviewer or typescript-reviewer.' 'generic description exactly matches approved routing contract'
description_equals "$PYTHON" 'Expert Python reviewer specializing in Pythonic correctness, typing, security, and performance. Use as the primary reviewer for local Python diffs. Pair with code-reviewer only for cross-boundary changes involving repositories, languages, module responsibilities, public contracts, or integration wiring.' 'Python description exactly matches approved routing contract'
description_equals "$TYPESCRIPT" 'Expert TypeScript/JavaScript reviewer specializing in type safety, async correctness, Node/web security, and idiomatic patterns. Use as the primary reviewer for local TypeScript/JavaScript diffs. Pair with code-reviewer only for cross-boundary changes involving repositories, languages, module responsibilities, public contracts, or integration wiring.' 'TypeScript description exactly matches approved routing contract'

contains "$CODE" 'model: opus' 'generic model remains pinned'
contains "$PYTHON" 'model: opus' 'Python model remains pinned'
contains "$TYPESCRIPT" 'model: opus' 'TypeScript model remains pinned'

printf '%s\n' '----'
printf 'PASS=%s FAIL=%s\n' "$PASS" "$FAIL"
test "$FAIL" -eq 0
