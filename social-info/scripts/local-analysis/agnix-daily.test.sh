#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP="$(mktemp -d)"
trap 'rc=$?; rm -rf "$TMP"; exit $rc' EXIT
BASELINE="$TMP/baseline"
INPUT="$TMP/input.json"
OUT="$TMP/out.md"
LOG="$TMP/run.log"

run_case() {
  AGNIX_BASELINE="$BASELINE" \
  AGNIX_JSON_INPUT="$INPUT" \
  AGNIX_OUT="$OUT" \
  AGNIX_LOG="$LOG" \
  LOCAL_ANALYSIS_DATE="2026-07-29" \
  bash "$DIR/agnix-daily.sh"
}

cat > "$BASELINE" <<'BASELINE'
warning|AS-013|vendor/sepia/skills/sepia/SKILL.md|File reference 'references/domains/dev-replies.md`' is deeper than one level
warning|AS-013|vendor/sepia/skills/sepia/SKILL.md|File reference 'references/domains/postmortems.md`' is deeper than one level
warning|AS-013|vendor/sepia/skills/sepia/SKILL.md|File reference 'references/domains/release-notes.md`' is deeper than one level
warning|AS-013|vendor/sepia/skills/sepia/SKILL.md|File reference 'references/domains/tech-articles.md`' is deeper than one level
warning|AS-013|vendor/sepia/skills/sepia/SKILL.md|File reference 'references/domains/tickets.md`' is deeper than one level
error|CC-HK-008|settings.json|Script file not found at 'SEMBLE_SCOPE_WRAPPER=~/.claude/scripts/semble-route3.sh' (resolved to '~/SEMBLE_SCOPE_WRAPPER=~/.claude/scripts/semble-route3.sh')
error|CC-HK-008|settings.json|Script file not found at 'SEMBLE_SCOPE_WRAPPER=~/.claude/scripts/semble-route3.sh' (resolved to '~/SEMBLE_SCOPE_WRAPPER=~/.claude/scripts/semble-route3.sh')
error|CC-HK-008|settings.json|Script file not found at 'SEMBLE_SCOPE_WRAPPER=~/.claude/scripts/semble-route3.sh' (resolved to '~/SEMBLE_SCOPE_WRAPPER=~/.claude/scripts/semble-route3.sh')
BASELINE
cat > "$INPUT" <<'JSON'
{"diagnostics":[
  {"file":"~/.claude/skills/a/SKILL.md","level":"warning","rule":"CC-SK-017","message":"Unknown frontmatter field 'upstream'"},
  {"file":"~/.claude/skills/a/SKILL.md","level":"warning","rule":"CC-SK-017","message":"Unknown frontmatter field 'upstream-path'"},
  {"file":"~/.claude/skills/a/SKILL.md","level":"warning","rule":"CC-SK-017","message":"Unknown frontmatter field 'upstream-pinned'"},
  {"file":"~/.claude/skills/a/SKILL.md","level":"warning","rule":"CC-SK-017","message":"Unknown frontmatter field 'upstream-status'"},
  {"file":"~/.claude/skills/a/SKILL.md","level":"warning","rule":"CC-SK-017","message":"Unknown frontmatter field 'upstreamm'"},
  {"file":"~/.claude/vendor/sepia/skills/sepia/SKILL.md","level":"warning","rule":"AS-013","message":"File reference 'references/domains/dev-replies.md`' is deeper than one level"},
  {"file":"~/.claude/vendor/sepia/skills/sepia/SKILL.md","level":"warning","rule":"AS-013","message":"File reference 'references/domains/postmortems.md`' is deeper than one level"},
  {"file":"~/.claude/vendor/sepia/skills/sepia/SKILL.md","level":"warning","rule":"AS-013","message":"File reference 'references/domains/release-notes.md`' is deeper than one level"},
  {"file":"~/.claude/vendor/sepia/skills/sepia/SKILL.md","level":"warning","rule":"AS-013","message":"File reference 'references/domains/tech-articles.md`' is deeper than one level"},
  {"file":"~/.claude/vendor/sepia/skills/sepia/SKILL.md","level":"warning","rule":"AS-013","message":"File reference 'references/domains/tickets.md`' is deeper than one level"},
  {"file":"~/.claude/settings.json","level":"error","rule":"CC-HK-008","message":"Script file not found at 'SEMBLE_SCOPE_WRAPPER=~/.claude/scripts/semble-route3.sh' (resolved to '~/SEMBLE_SCOPE_WRAPPER=~/.claude/scripts/semble-route3.sh')"},
  {"file":"~/.claude/settings.json","level":"error","rule":"CC-HK-008","message":"Script file not found at 'SEMBLE_SCOPE_WRAPPER=~/.claude/scripts/semble-route3.sh' (resolved to '~/SEMBLE_SCOPE_WRAPPER=~/.claude/scripts/semble-route3.sh')"},
  {"file":"~/.claude/settings.json","level":"error","rule":"CC-HK-008","message":"Script file not found at 'SEMBLE_SCOPE_WRAPPER=~/.claude/scripts/semble-route3.sh' (resolved to '~/SEMBLE_SCOPE_WRAPPER=~/.claude/scripts/semble-route3.sh')"},
  {"file":"~/.claude/settings.json","level":"error","rule":"CC-HK-008","message":"Script file not found at 'SEMBLE_SCOPE_WRAPPER=~/.claude/scripts/semble-route3.sh' (resolved to '~/SEMBLE_SCOPE_WRAPPER=~/.claude/scripts/missing-route3.sh')"},
  {"file":"~/.claude/settings.json","level":"error","rule":"CC-HK-008","message":"Script file not found at '~/.claude/hooks/missing.sh' (resolved to '~/.claude/hooks/missing.sh')"},
  {"file":"~/.claude/skills/workflow-hardening/SKILL.md","level":"warning","rule":"AS-013","message":"File reference 'references/archive/example.md`' is deeper than one level"},
  {"file":"~/.claude/skills/a/SKILL.md","level":"error","rule":"XML-002","message":"Expected closing tag"}
]}
JSON
run_case
grep -F "Unknown frontmatter field 'upstreamm'" "$OUT" >/dev/null
grep -F 'XML-002' "$OUT" >/dev/null
grep -F '~/.claude/hooks/missing.sh' "$OUT" >/dev/null
if [ "$(grep -Fc 'SEMBLE_SCOPE_WRAPPER=~/.claude/scripts/semble-route3.sh' "$OUT")" -ne 1 ]; then
  exit 1
fi
if grep -F "Unknown frontmatter field 'upstream-path'" "$OUT" >/dev/null; then
  exit 1
fi
grep -F 'skills/workflow-hardening/SKILL.md' "$OUT" >/dev/null
if grep -F 'vendor/sepia/skills/sepia/SKILL.md' "$OUT" >/dev/null; then
  exit 1
fi
if grep -F '## ✅ 已解除' "$OUT" >/dev/null; then
  exit 1
fi
if grep -F 'vendor/sepia/skills/sepia/SKILL.md' "$BASELINE" >/dev/null; then
  exit 1
fi
if [ "$(grep -Fc 'SEMBLE_SCOPE_WRAPPER=~/.claude/scripts/semble-route3.sh' "$BASELINE")" -ne 1 ]; then
  exit 1
fi

cp "$BASELINE" "$TMP/baseline.before"
run_case
test "$(cat "$OUT")" = '__SILENT__'
cmp -s "$TMP/baseline.before" "$BASELINE"

python3 - "$INPUT" <<'PY'
import json, sys
path = sys.argv[1]
data = json.load(open(path))
data['diagnostics'] = [item for item in data['diagnostics'] if 'missing-route3.sh' not in item['message']]
with open(path, 'w') as output:
    json.dump(data, output)
PY
run_case
grep -F '## ✅ 已解除' "$OUT" >/dev/null
grep -F 'CC-HK-008' "$OUT" >/dev/null

python3 - "$BASELINE" "$INPUT" <<'PY'
import json, sys
baseline_path, input_path = sys.argv[1:]
prefix = 'x' * 160
with open(baseline_path, 'w') as baseline:
    baseline.write(f'error|CC-HK-008|settings.json|{prefix}\n')
with open(input_path, 'w') as output:
    json.dump({'diagnostics': [{
        'file': '~/.claude/settings.json',
        'level': 'error',
        'rule': 'CC-HK-008',
        'message': prefix + '-longer',
    }]}, output)
PY
run_case
grep -F '## ⚠️ 新 finding' "$OUT" >/dev/null
grep -F '## ✅ 已解除' "$OUT" >/dev/null
PREFIX="$(python3 -c "print('x' * 160)")"
test "$(grep -Fc "$PREFIX" "$OUT")" -eq 1
test "$(grep -Fc 'CC-HK-008' "$OUT")" -eq 2

cp "$BASELINE" "$TMP/baseline.before"
printf '{invalid' > "$INPUT"
run_case
grep -F '## 🚨 掃描器輸出不是合法 JSON' "$OUT" >/dev/null
cmp -s "$TMP/baseline.before" "$BASELINE"

printf '' > "$BASELINE"
cat > "$INPUT" <<'JSON'
{"diagnostics":[
  {"file":"~/.claude/vendor/sepia/skills/sepia/SKILL.md","level":"warning","rule":"AS-013","message":"File reference 'references/languages/zh.md`' is deeper than one level"},
  {"file":"~/.claude/vendor/sepia/skills/sepia/SKILL.md","level":"warning","rule":"AS-013","message":"File reference 'references/languages/en.md`' is deeper than one level"},
  {"file":"~/.claude/skills/other/SKILL.md","level":"warning","rule":"AS-013","message":"File reference 'references/languages/zh.md`' is deeper than one level"}
]}
JSON
run_case
test "$(grep -Fc 'references/languages/zh.md' "$OUT")" -eq 1
grep -F 'skills/other/SKILL.md' "$OUT" >/dev/null
grep -F 'references/languages/en.md' "$OUT" >/dev/null

printf '6/6 passed\n'
