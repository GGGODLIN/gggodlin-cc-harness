#!/bin/bash
set -uo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
AUDIT="${AUDIT_FILE:-$ROOT/commands/memory-audit.md}"
L_CHECK="${L_CHECK_FILE:-$ROOT/scripts/memory-index-audit.sh}"
TMP=$(mktemp -d)
trap 'rm -r "$TMP"' EXIT
PASS=0
FAIL=0

check_text() {
  local name="$1"
  local expected="$2"
  if grep -qF -- "$expected" "$AUDIT"; then
    PASS=$((PASS + 1))
    printf '  ok   %s\n' "$name"
  else
    FAIL=$((FAIL + 1))
    printf '  FAIL %s\n' "$name"
  fi
}

check_file_text() {
  local name="$1"
  local path="$2"
  local expected="$3"
  if grep -qF -- "$expected" "$path"; then
    PASS=$((PASS + 1))
    printf '  ok   %s\n' "$name"
  else
    FAIL=$((FAIL + 1))
    printf '  FAIL %s\n' "$name"
  fi
}

check_absent() {
  local name="$1"
  local unexpected="$2"
  if grep -qF -- "$unexpected" "$AUDIT"; then
    FAIL=$((FAIL + 1))
    printf '  FAIL %s\n' "$name"
  else
    PASS=$((PASS + 1))
    printf '  ok   %s\n' "$name"
  fi
}

check_eq() {
  local name="$1"
  local expected="$2"
  local actual="$3"
  if [ "$expected" = "$actual" ]; then
    PASS=$((PASS + 1))
    printf '  ok   %s\n' "$name"
  else
    FAIL=$((FAIL + 1))
    printf '  FAIL %s expect=%s actual=%s\n' "$name" "$expected" "$actual"
  fi
}

coverage_hits() {
  local pointer="$1"
  local wiki_dir="$2"
  local tail="${pointer#*→}"
  while IFS= read -r raw; do
    local slug="${raw#\[\[}"
    slug="${slug%\]\]}"
    slug="${slug%%#*}"
    [ -f "$wiki_dir/$slug.md" ] && printf '%s\n' "$slug"
  done < <(printf '%s' "$tail" | grep -oE '\[\[[^][]+\]\]')
}

path_state() {
  local path="$1"
  local expanded="${path/#\~/$HOME}"
  if [[ "$expanded" == *[\*\?]* ]]; then
    compgen -G "$expanded" >/dev/null && printf 'VALID\n' || printf 'DEAD\n'
  elif [ -e "$expanded" ]; then
    printf 'VALID\n'
  else
    printf 'DEAD\n'
  fi
}

path_segment() {
  local line="$1"
  local path="$2"
  local pattern="$3"
  printf '%s\n' "$line" | python3 -c 'import re, sys; p, pattern=sys.argv[1:]; line=sys.stdin.read(); matches=list(re.finditer(pattern, line)); current=next((m for m in matches if m.group(0) == p), None); start=max((line.rfind(sep, 0, current.start()) for sep in ",，;；:：。！？"), default=-1)+1 if current else 0; following=next((m.start() for m in matches if current and m.start() > current.start()), len(line)); print(line[start:following] if current else "")' "$path" "$pattern"
}

status_for() {
  local path="$1"
  local output="$2"
  grep -F "$path" "$output" | awk '{print $1}' | sort -u | tr '\n' ','
}

mkdir -p "$TMP/wiki"
: > "$TMP/wiki/a.md"
: > "$TMP/wiki/b.md"
: > "$TMP/wiki/c.md"
: > "$TMP/wiki/cheap-coding-agent-subscription-landscape.md"

multi_hits=$(coverage_hits 'pointer → [[a]] + [[b]] wiki' "$TMP/wiki" | sort | tr '\n' ',')
merged_hits=$(coverage_hits 'pointer → 已併入 [[c]]（2026-07-17）' "$TMP/wiki")
path_regex_line=$(grep -F "PATH_RE='" "$AUDIT")
path_regex=$(printf '%s\n' "$path_regex_line" | sed -E "s/^PATH_RE='([^']+)'$/\\1/")
marker_line=$(grep -F "/usr/bin/grep -qE '" "$AUDIT")
marker_regex=$(printf '%s\n' "$marker_line" | sed -E "s/.*grep -qE '([^']+)'.*/\\1/")
existing_glob='~/Desktop/projects/hook-llm-bench/scripts/bench_*.py'
missing_glob='~/Desktop/projects/hook-llm-bench/scripts/no-such-bench_*.py'
extracted_existing=$(printf 'source: %s\n' "$existing_glob" | grep -oE "$path_regex")
extracted_missing=$(printf 'source: %s\n' "$missing_glob" | grep -oE "$path_regex")
unmarked_retired=$(grep -RInE '/grill-me-one-shot|/memory-checkpoint' "$ROOT/memory" --include='*.md' --exclude-dir=archive \
  | grep -vE '歷史|退役|曾試圖|當時' || true)
pressure_live='~/code/social-info/scripts/live-missing.sh'
pressure_retired='~/code/social-info/scripts/retired-missing.sh'
pressure_line="現行 ${pressure_live}；舊版 ${pressure_retired} 已於 2026-08-18 退役"
pressure_live_segment=$(path_segment "$pressure_line" "$pressure_live" "$path_regex")
pressure_retired_segment=$(path_segment "$pressure_line" "$pressure_retired" "$path_regex")
trailing_retired='~/code/social-info/scripts/trailing-retired-missing.sh'
trailing_line="同 session 內升級當時的 ${trailing_retired} Constraints 段；該 command 已於 2026-08-18 退役"
trailing_retired_segment=$(path_segment "$trailing_line" "$trailing_retired" "$path_regex")
h_script="$TMP/h-pipeline.zsh"
h_memory="$TMP/h-memory"
h_home="$TMP/h-home"
h_output="$TMP/h-output.txt"
python3 - "$AUDIT" "$h_script" <<'PY'
from pathlib import Path
import sys
lines = Path(sys.argv[1]).read_text().splitlines()
start = lines.index('/bin/bash -s -- "$MEMORY_DIR" <<\'BASH\'')
end = next(i for i in range(start + 1, len(lines)) if lines[i] == 'BASH')
Path(sys.argv[2]).write_text('\n'.join(lines[start:end + 1]) + '\n')
PY
mkdir -p "$h_memory/general" "$h_memory/work" "$h_memory/projects" "$h_home/.claude/scripts/fixtures"
: > "$h_home/.claude/scripts/fixtures/existing.sh"
h_existing='~/.claude/scripts/fixtures/*.sh'
h_retired='~/.claude/scripts/retired-missing.sh'
h_active='~/.claude/scripts/active-missing.sh'
h_reverse_retired='~/.claude/scripts/reverse-retired.sh'
h_reverse_active='~/.claude/scripts/reverse-active.sh'
h_library_retired='~/.claude/scripts/library-retired.sh'
h_trailing_slash='~/Desktop/projects/retired-dir'
h_brace_base='~/Desktop/projects/reports/historical-report'
printf '現行 %s\n' "$h_existing" > "$h_memory/glob.md"
printf '舊版 %s 已於 2026-08-18 退役\n' "$h_retired" > "$h_memory/retired.md"
printf '現行 %s\n' "$h_active" > "$h_memory/general/含 空格.md"
printf '舊版 %s 已於 2026-08-18 退役；現行 %s\n' "$h_reverse_retired" "$h_reverse_active" > "$h_memory/pressure.md"
printf '歷史 %s；參照 ~/Library/Application Support；該 command 已於 2026-08-18 退役\n' "$h_library_retired" > "$h_memory/library.md"
printf '歷史紀錄 %s/ 已於 2026-08-18 刪除\n' "$h_trailing_slash" > "$h_memory/trailing-slash.md"
printf '報告 %s.{md,json}（歷史紀錄；兩個副檔名檔案仍存在）\n' "$h_brace_base" > "$h_memory/brace.md"
HOME="$h_home" MEMORY_DIR="$h_memory" /bin/zsh "$h_script" > "$h_output"

l_memory="$TMP/l-memory"
l_output="$TMP/l-output.txt"
mkdir -p "$l_memory/general" "$l_memory/work/sample" "$l_memory/projects"
printf '# General\n' > "$l_memory/general/_INDEX.md"
printf '# Work\n- [sample](sample/_INDEX.md)\n' > "$l_memory/work/_INDEX.md"
printf '# Projects\n' > "$l_memory/projects/_INDEX.md"
printf '%s\n' \
  '- [actual](actual.md)' \
  '- [owner](owner.md) — [[cheap-coding-agent-subscription-landscape]]' \
  '- [[bitbucket-api]]' \
  '- [[filename-only]]' \
  '- [cross](../shared.md)' \
  '- [[wiki-owner#section]]' \
  '- [broken](missing.md)' > "$l_memory/work/sample/_INDEX.md"
printf '%s\n' 'actual' > "$l_memory/work/sample/actual.md"
printf '%s\n' 'owner' > "$l_memory/work/sample/owner.md"
printf '%s\n' '---' 'name: bitbucket-api' '---' 'named' > "$l_memory/work/sample/named.md"
printf '%s\n' 'filename route' > "$l_memory/work/sample/filename-only.md"
"$L_CHECK" "$l_memory" > "$l_output"
if "$L_CHECK" "$TMP/missing-memory" > "$TMP/l-invalid.out" 2> "$TMP/l-invalid.err"; then
  l_invalid_rc=0
else
  l_invalid_rc=$?
fi

check_file_text "brainstorm third-party authority route" "$ROOT/skills/brainstorm/SKILL.md" "In a third party's head (PM, designer, coworker) | \`to-questionnaire\`"
check_file_text "grill-me third-party authority route" "$ROOT/skills/grill-me/SKILL.md" 'If a decision belongs to a third party (such as a PM, designer, or coworker), propose `to-questionnaire`'
check_text "標示契約測試跑法" "memory-audit-contract.test.sh"
check_text "F 支援多 wiki link" "不要假設只有一個 link"
check_text "F 支援已併入形狀" '→ 已併入 [[c]]'
check_text "F completion criterion" "pointer wiki hits=0"
check_text "H extractor 保留 glob" '[A-Za-z0-9._/+*?-]+'
check_text "H 固定 bash runtime" '/bin/bash -s -- "$MEMORY_DIR"'
check_text "H 使用 compgen 驗 glob" 'compgen -G "$exp"'
check_text "H 保留來源行號" 'grep -HnoE'
check_text "H 自我註記在 pipeline 內 suppress" 'SELF_NOTE'
check_text "H disposition 限定 path 範圍" 'source_segment='
check_text "H 自我註記涵蓋歷史" "歷史(記錄|紀錄|實例)"
check_text "local chain skill examples" '[[brainstorm]]` / `[[to-spec]]` / `[[to-tickets]]` / `[[implement]]'
check_text "local completion skill example" '[[dispatch-and-verify]]'
check_absent "retired plugin skill example removed" '[[superpowers:'
check_eq "多 link coverage" "a,b," "$multi_hits"
check_eq "已併入 coverage" "c" "$merged_hits"
check_eq "existing glob 完整抽取" "$existing_glob" "$extracted_existing"
check_eq "existing glob 判有效" "VALID" "$(path_state "$extracted_existing")"
check_eq "missing glob 完整抽取" "$missing_glob" "$extracted_missing"
check_eq "missing glob 判死路徑" "DEAD" "$(path_state "$extracted_missing")"
check_eq "已於日期後退役 marker 命中" "1" "$(printf '%s\n' '該 command 已於 2026-08-18 退役' | grep -cE "$marker_regex")"
check_eq "未註記 active path 不命中" "0" "$(printf '%s\n' '現行 hook 路徑仍需存在' | grep -cE "$marker_regex" || true)"
check_eq "同列 active path 範圍不命中" "0" "$(printf '%s\n' "$pressure_live_segment" | grep -cE "$marker_regex" || true)"
check_eq "同列 retired path 範圍命中" "1" "$(printf '%s\n' "$pressure_retired_segment" | grep -cE "$marker_regex")"
check_eq "下一 clause 退役 marker 命中" "1" "$(printf '%s\n' "$trailing_retired_segment" | grep -cE "$marker_regex")"
check_eq "完整 pipeline 排除有效 glob" "" "$(status_for "$h_existing" "$h_output")"
check_eq "完整 pipeline retired 判 SELF_NOTE" "SELF_NOTE," "$(status_for "$h_retired" "$h_output")"
check_eq "完整 pipeline active 判 DEAD" "DEAD," "$(status_for "$h_active" "$h_output")"
check_eq "完整 pipeline 反向 retired 判 SELF_NOTE" "SELF_NOTE," "$(status_for "$h_reverse_retired" "$h_output")"
check_eq "完整 pipeline 反向 active 判 DEAD" "DEAD," "$(status_for "$h_reverse_active" "$h_output")"
check_eq "完整 pipeline 不受非候選 ~/Library 截斷" "SELF_NOTE," "$(status_for "$h_library_retired" "$h_output")"
check_eq "完整 pipeline trailing slash 判 SELF_NOTE" "SELF_NOTE," "$(status_for "$h_trailing_slash" "$h_output")"
check_eq "完整 pipeline brace base 判 SELF_NOTE" "SELF_NOTE," "$(status_for "$h_brace_base" "$h_output")"
check_eq "退役 slash reference 全有 disposition" "" "$unmarked_retired"
check_text "L 使用 deterministic helper" '$HOME/.claude/scripts/memory-index-audit.sh'
check_text "L 禁止重新實作" "不得改寫成 Python"
check_eq "L 只回報真 relative broken link" "LISTED-BUT-MISSING: work/sample/missing.md" "$(cat "$l_output")"
check_eq "L 不把 wiki entity 當 local missing" "0" "$(grep -c 'cheap-coding-agent-subscription-landscape' "$l_output" || true)"
check_eq "L frontmatter route 註冊實際檔名" "0" "$(grep -c 'named.md' "$l_output" || true)"
check_eq "L filename route 註冊實際檔名" "0" "$(grep -c 'filename-only.md' "$l_output" || true)"
check_eq "L 無效 memory dir fail closed" "2" "$l_invalid_rc"
check_file_text "L 無效 memory dir 有錯誤證據" "$TMP/l-invalid.err" "memory dir not found"
check_eq "L 不把跨目錄 target 當 local missing" "0" "$(grep -c 'shared.md' "$l_output" || true)"
check_eq "L 不把 anchor wikilink 當 local missing" "0" "$(grep -c 'wiki-owner' "$l_output" || true)"

printf '\n%s PASS / %s FAIL\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
