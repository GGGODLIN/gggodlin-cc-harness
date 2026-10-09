#!/usr/bin/env bash
set -u

SCRIPT="$HOME/.claude/scripts/skill-inventory-paths.sh"
INVENTORY="$HOME/.claude/skills/INVENTORY.md"
WRAPPER="$HOME/code/social-info/scripts/local-analysis/skill-desc-quality-daily.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
pass=0
fail=0

if [ -x "$SCRIPT" ]; then
  fixture_home="$TMP/home"
  fixture_project="$TMP/project"
  mkdir -p "$fixture_home/.claude/skills/alpha" "$fixture_home/.claude/skills/beta" "$fixture_project/.claude/skills/gamma"
  touch "$fixture_home/.claude/skills/alpha/SKILL.md" "$fixture_home/.claude/skills/beta/SKILL.md" "$fixture_project/.claude/skills/gamma/SKILL.md"
  cat > "$TMP/INVENTORY.md" <<EOF
## Global skills (\`~/.claude/skills/\`)

| Skill | Origin | Audit |
|---|---|---|
| alpha | self | yes |
| beta | upstream | no |
| malformed | self | no |

## Project: fixture (\`$fixture_project/.claude/skills/\`)

| Skill | Origin | Audit |
|---|---|---|
| gamma | self | yes (patched) |
| sample (command) | self | yes |

## Notes

| Skill | Origin | Audit |
|---|---|---|
| phantom | self | yes |

## Excluded paths
EOF
  HOME="$fixture_home" bash "$SCRIPT" --paths "$TMP/INVENTORY.md" > "$TMP/paths"
  HOME="$fixture_home" bash "$SCRIPT" --counts "$TMP/INVENTORY.md" > "$TMP/counts"
  expected_paths=$(printf '%s\n%s\n' "$fixture_home/.claude/skills/alpha/SKILL.md" "$fixture_project/.claude/skills/gamma/SKILL.md")
  actual_paths=$(<"$TMP/paths")
  if [ "$actual_paths" = "$expected_paths" ]; then
    echo "PASS paths"
    ((pass++))
  else
    echo "FAIL paths: $actual_paths"
    ((fail++))
  fi
  if grep -q '"global":1,"project":1,"total":2' "$TMP/counts"; then
    echo "PASS counts"
    ((pass++))
  else
    echo "FAIL counts: $(<"$TMP/counts")"
    ((fail++))
  fi

  cat > "$TMP/invalid-audit.md" <<EOF
## Global skills (\`~/.claude/skills/\`)

| Skill | Origin | Audit |
|---|---|---|
| alpha | self | yes-ish |
EOF
  if HOME="$fixture_home" bash "$SCRIPT" --paths "$TMP/invalid-audit.md" > "$TMP/invalid-audit.paths" 2> "$TMP/invalid-audit.err"; then
    echo "FAIL invalid Audit accepted"
    ((fail++))
  elif grep -Fq 'invalid Audit value: yes-ish' "$TMP/invalid-audit.err"; then
    echo "PASS invalid Audit rejected"
    ((pass++))
  else
    echo "FAIL invalid Audit message: $(<"$TMP/invalid-audit.err")"
    ((fail++))
  fi

  cat > "$TMP/invalid-traversal.md" <<EOF
## Global skills (\`~/.claude/skills/\`)

| Skill | Origin | Audit |
|---|---|---|
| ../../outside | self | yes |
EOF
  if HOME="$fixture_home" bash "$SCRIPT" --paths "$TMP/invalid-traversal.md" > "$TMP/invalid-traversal.paths" 2> "$TMP/invalid-traversal.err"; then
    echo "FAIL traversal skill accepted"
    ((fail++))
  elif grep -Fq 'invalid skill name: ../../outside' "$TMP/invalid-traversal.err"; then
    echo "PASS traversal skill rejected"
    ((pass++))
  else
    echo "FAIL traversal message: $(<"$TMP/invalid-traversal.err")"
    ((fail++))
  fi

  cat > "$TMP/invalid-name.md" <<EOF
## Global skills (\`~/.claude/skills/\`)

| Skill | Origin | Audit |
|---|---|---|
| bad_name | self | yes |
EOF
  if HOME="$fixture_home" bash "$SCRIPT" --paths "$TMP/invalid-name.md" > "$TMP/invalid-name.paths" 2> "$TMP/invalid-name.err"; then
    echo "FAIL invalid skill name accepted"
    ((fail++))
  elif grep -Fq 'invalid skill name: bad_name' "$TMP/invalid-name.err"; then
    echo "PASS invalid skill name rejected"
    ((pass++))
  else
    echo "FAIL invalid name message: $(<"$TMP/invalid-name.err")"
    ((fail++))
  fi
else
  echo "FAIL missing parser: $SCRIPT"
  ((fail++))
fi

if [ ! -f "$INVENTORY" ]; then
  echo "FAIL missing INVENTORY: $INVENTORY"
  ((fail++))
elif grep -qE '^\*\*(Global Audit-eligible 統計|Project-scoped Audit-eligible 統計|全體 audit 範圍)\*\*.*[0-9]+' "$INVENTORY"; then
  echo "FAIL hand-maintained INVENTORY totals remain"
  ((fail++))
else
  echo "PASS INVENTORY totals are derived"
  ((pass++))
fi

if [ ! -f "$WRAPPER" ]; then
  echo "FAIL missing wrapper: $WRAPPER"
  ((fail++))
else
  if grep -qE '含 global .* [0-9]+ 個|預期 output ~[0-9]+ 條 path' "$WRAPPER"; then
    echo "FAIL hand-maintained wrapper totals remain"
    ((fail++))
  else
    echo "PASS wrapper totals are derived"
    ((pass++))
  fi
  if grep -qF 'bash ~/.claude/scripts/skill-inventory-paths.sh --paths' "$WRAPPER" && grep -qF 'bash ~/.claude/scripts/skill-inventory-paths.sh --counts' "$WRAPPER"; then
    echo "PASS wrapper calls canonical parser"
    ((pass++))
  else
    echo "FAIL wrapper does not call both parser modes"
    ((fail++))
  fi
fi

if [ ! -f "$WRAPPER" ] || ! grep -qF 'skill-desc-quality.paths' "$WRAPPER" || ! grep -qF 'SELECTION_FIXTURE_BEGIN' "$WRAPPER" || ! grep -qF 'mv -f' "$WRAPPER"; then
  echo "FAIL incremental selection contract is missing"
  ((fail++))
else
  python3 - "$WRAPPER" "$TMP/selection.sh" <<'PY'
from pathlib import Path
import sys
source = Path(sys.argv[1]).read_text()
start = source.index('SELECTION_FIXTURE_BEGIN') + len('SELECTION_FIXTURE_BEGIN')
end = source.index('SELECTION_FIXTURE_END')
Path(sys.argv[2]).write_text(source[start:end].strip() + '\n')
PY
  fixture_root="$TMP/incremental"
  mkdir -p "$fixture_root"
  printf '%s\n' "$fixture_root/delegate-browser-e2e/SKILL.md" "$fixture_root/old/SKILL.md" > "$fixture_root/paths"
  mkdir -p "$fixture_root/delegate-browser-e2e" "$fixture_root/old" "$fixture_root/state"
  touch "$fixture_root/delegate-browser-e2e/SKILL.md" "$fixture_root/old/SKILL.md"
  printf '%s\n' "$fixture_root/old/SKILL.md" > "$fixture_root/state/seen"
  python3 - "$fixture_root/last_run" "$fixture_root/delegate-browser-e2e/SKILL.md" "$fixture_root/old/SKILL.md" <<'PY'
from pathlib import Path
import os
import sys
last_run, delegate, old = map(Path, sys.argv[1:])
last_run.touch()
os.utime(last_run, (100, 100))
os.utime(delegate, (90, 90))
os.utime(old, (90, 90))
PY
  PATHS_FILE="$fixture_root/paths" SEEN_PATHS="$fixture_root/state/seen" LAST_RUN="$fixture_root/last_run" CHANGED_FILE="$fixture_root/changed" bash "$TMP/selection.sh"
  if grep -Fxq "$fixture_root/delegate-browser-e2e/SKILL.md" "$fixture_root/changed" && ! grep -Fxq "$fixture_root/old/SKILL.md" "$fixture_root/changed"; then
    printf '%s\n' "$fixture_root/delegate-browser-e2e/SKILL.md" >> "$fixture_root/state/seen"
    PATHS_FILE="$fixture_root/paths" SEEN_PATHS="$fixture_root/state/seen" LAST_RUN="$fixture_root/last_run" CHANGED_FILE="$fixture_root/changed-again" bash "$TMP/selection.sh"
    if [ ! -s "$fixture_root/changed-again" ]; then
      echo "PASS incremental selection handles unseen then old seen path"
      ((pass++))
    else
      echo "FAIL incremental selection retained old seen path: $(<"$fixture_root/changed-again")"
      ((fail++))
    fi
  else
    echo "FAIL incremental selection did not include unseen delegate"
    ((fail++))
  fi
fi

cat > "$TMP/MALFORMED.md" <<'EOF'
### Global skills (~/.claude/skills/)

Skill / Origin / Audit
alpha / self / yes
beta / upstream / yes

### Project: fixture (~/proj/.claude/skills/)

Skill / Origin / Audit
gamma / self / yes (patched)
EOF
malformed_total=$(bash "$SCRIPT" --counts "$TMP/MALFORMED.md" | sed 's/.*"total"://; s/}//')
if [ ! -f "$INVENTORY" ]; then
  real_total=0
else
  real_total=$(bash "$SCRIPT" --counts "$INVENTORY" | sed 's/.*"total"://; s/}//')
fi
if [ -s "$TMP/MALFORMED.md" ] && [ "$malformed_total" -eq 0 ] && [ "$real_total" -gt 0 ]; then
  echo "PASS zero-hit guard fires on non-empty input parsed to 0"
  ((pass++))
else
  echo "FAIL zero-hit guard: malformed_total=$malformed_total real_total=$real_total"
  ((fail++))
fi

echo "---- $pass pass / $fail fail ----"
exit "$fail"
