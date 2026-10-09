#!/bin/bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP="$(mktemp -d)"
trap 'rc=$?; rm -rf "$TMP"; exit $rc' EXIT

touch "$TMP/_schema.md" "$TMP/index.md" "$TMP/log.md" "$TMP/alpha.md" "$TMP/beta.md"
actual="$(WIKI_DIR="$TMP" bash "$DIR/wiki-entity-paths.sh")"
expected="$(printf '%s\n' "$TMP/alpha.md" "$TMP/beta.md")"
test "$actual" = "$expected"

prompt="$(bash "$DIR/wiki-graduation-daily.sh")"
grep -F "$DIR/wiki-entity-paths.sh" <<< "$prompt" >/dev/null
grep -F '所有 entity 計數、分桶與候選掃描只能使用這份輸出' <<< "$prompt" >/dev/null
grep -F 'C1/C2 匯總數字每日必重算' <<< "$prompt" >/dev/null
grep -F '禁止沿用前日報告字面數字' <<< "$prompt" >/dev/null
grep -F '統計一律當日實跑 `grep -c` 對 frontmatter 重算' <<< "$prompt" >/dev/null

printf '%s\n' '---' 'confidence: high' 'lifecycle: verified' '---' > "$TMP/alpha.md"
printf '%s\n' '---' 'confidence: medium' 'lifecycle: reviewed' '---' > "$TMP/beta.md"
paths="$(WIKI_DIR="$TMP" bash "$DIR/wiki-entity-paths.sh")"
high="$(xargs grep -l '^confidence: high$' <<< "$paths" | wc -l | tr -d ' ')"
medium="$(xargs grep -l '^confidence: medium$' <<< "$paths" | wc -l | tr -d ' ')"
verified="$(xargs grep -l '^lifecycle: verified$' <<< "$paths" | wc -l | tr -d ' ')"
reviewed="$(xargs grep -l '^lifecycle: reviewed$' <<< "$paths" | wc -l | tr -d ' ')"
test "$high" = 1
test "$medium" = 1
test "$verified" = 1
test "$reviewed" = 1

printf 'wiki graduation entity scope: PASS\n'
