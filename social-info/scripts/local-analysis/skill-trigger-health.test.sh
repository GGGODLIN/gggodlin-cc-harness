#!/bin/bash
# gate-authoring 三件 fixture 回歸：known-good（auto-only 純自動 → 不警報）/
# known-bad（auto-only 被手動 slash → 必警報）/ 邊界（dual 被手動 slash → 不警報）。
# 改 skill-trigger-health.py 後必跑本檔。
set -euo pipefail

T=$(mktemp -d)
trap 'rc=$?; rm -rf "$T"; exit $rc' EXIT
mkdir -p "$T/skills/good-skill" "$T/skills/bad-skill" "$T/skills/dual-skill" "$T/skills/hook-skill" "$T/commands" "$T/projects/proj-a"
printf -- '---\nname: hook-skill\ndescription: Triggered by hook injection only.\n---\n' > "$T/skills/hook-skill/SKILL.md"

printf -- '---\nname: good-skill\ndescription: Use when testing good.\n---\n' > "$T/skills/good-skill/SKILL.md"
printf -- '---\nname: bad-skill\ndescription: Use when testing bad.\n---\n' > "$T/skills/bad-skill/SKILL.md"
printf -- '---\nname: dual-skill\ndescription: Use when testing dual. Also invokable manually via /dual-skill.\n---\n' > "$T/skills/dual-skill/SKILL.md"

TS=$(python3 -c 'import datetime; print(datetime.datetime.now(datetime.timezone.utc).isoformat())')
cat > "$T/projects/proj-a/s1.jsonl" <<EOF
{"uuid":"u1","timestamp":"$TS","message":{"role":"assistant","content":[{"type":"tool_use","id":"t1","name":"Skill","input":{"skill":"good-skill"}}]}}
{"uuid":"u2","timestamp":"$TS","message":{"role":"user","content":"<command-name>/bad-skill</command-name> please"}}
{"uuid":"u3","timestamp":"$TS","message":{"role":"user","content":"<command-name>/dual-skill</command-name> go"}}
{"uuid":"u2","timestamp":"$TS","message":{"role":"user","content":"<command-name>/bad-skill</command-name> duplicated-resume-copy-same-uuid"}}
EOF

REG="$T/registry.json"
printf '{"hook-skill": {"mode": "hook-driven", "decided": true}}\n' > "$REG"
python3 ~/code/social-info/scripts/local-analysis/skill-trigger-health.py \
  --date 2026-07-31 --out "$T/report.md" \
  --projects-dir "$T/projects" --skills-dir "$T/skills" --commands-dir "$T/commands" \
  --registry "$REG" --claude-git-dir "" > "$T/stdout.txt"

pass=0; fail=0
check() {
  local desc="$1"; shift
  if "$@"; then pass=$((pass+1)); echo "  ok   $desc"; else fail=$((fail+1)); echo "  FAIL $desc"; fi
}

check "known-bad: auto-only 手動 slash 有警報" grep -q '⚠️ `bad-skill`' "$T/report.md"
check "known-bad: 同 uuid 複製訊息去重為 1 次" grep -q '手動 slash \*\*1 次\*\*' "$T/report.md"
check "known-good: 純自動不警報" bash -c "! grep -q '⚠️ \`good-skill\`' '$T/report.md'"
check "邊界: dual 手動 slash 不警報" bash -c "! grep -q '⚠️ \`dual-skill\`' '$T/report.md'"
check "dual 自動分類生效" python3 -c "import json,sys; r=json.load(open('$REG')); sys.exit(0 if r['dual-skill']['mode']=='dual' else 1)"
check "hook-driven 零 invoke 不進死庫存、標題計數 1" grep -q '排除 hook-driven 1 個' "$T/report.md"
check "hook-driven 不列為死庫存候選" bash -c "! grep -q 'hook-skill.*留/殺候選' '$T/report.md'"
check "registry decided=true 不被覆寫" bash -c "
  python3 -c \"import json; r=json.load(open('$REG')); r['bad-skill']={'mode':'dual','decided':True}; json.dump(r,open('$REG','w'))\"
  python3 ~/code/social-info/scripts/local-analysis/skill-trigger-health.py \
    --date 2026-07-31 --out '$T/report2.md' \
    --projects-dir '$T/projects' --skills-dir '$T/skills' --commands-dir '$T/commands' \
    --registry '$REG' --claude-git-dir '' >/dev/null
  ! grep -q '⚠️ \`bad-skill\`' '$T/report2.md'
"

echo "$pass/$((pass+fail)) passed"
[ "$fail" -eq 0 ]
