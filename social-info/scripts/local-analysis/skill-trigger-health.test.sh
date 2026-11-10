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

# Ticket 01: cadence reminder (remind_after_days), decided=false field preservation, Workflow scriptPath last_ts, deep-check repo nomination
mkdir -p "$T/skills/hillclimb" "$T/skills/deep-check" "$T/skills/wf-skill" "$T/state" "$T/work/repo-alpha" "$T/work/repo-beta" "$T/symlinks"
ln -s "$T/work/repo-alpha" "$T/symlinks/repo-alpha"
ln -s "$T/work/repo-beta" "$T/symlinks/repo-beta"
printf -- '---\nname: hillclimb\ndescription: Hillclimb metric.\n---\n' > "$T/skills/hillclimb/SKILL.md"
printf -- '---\nname: deep-check\ndescription: Deep check repo.\n---\n' > "$T/skills/deep-check/SKILL.md"
printf -- '---\nname: wf-skill\ndescription: Workflow skill.\n---\n' > "$T/skills/wf-skill/SKILL.md"

# Setup two git repos under $T/work: repo-alpha has 22 new commits after head_sha (and skipped_at 25d ago); repo-beta has 5 commits
git -C "$T/work/repo-alpha" init -q
git -C "$T/work/repo-alpha" config user.email "test@example.com"
git -C "$T/work/repo-alpha" config user.name "Test"
git -C "$T/work/repo-alpha" commit --allow-empty -m "base" -q
BASE_SHA=$(git -C "$T/work/repo-alpha" rev-parse HEAD)
for i in $(seq 1 22); do
  git -C "$T/work/repo-alpha" commit --allow-empty -m "c$i" -q
done

git -C "$T/work/repo-beta" init -q
git -C "$T/work/repo-beta" config user.email "test@example.com"
git -C "$T/work/repo-beta" config user.name "Test"
for i in $(seq 1 5); do
  git -C "$T/work/repo-beta" commit --allow-empty -m "b$i" -q
done

OLD_DATE=$(python3 -c 'import datetime; print((datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=25)).strftime("%Y-%m-%d"))')
RECENT_DATE=$(python3 -c 'import datetime; print((datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=5)).strftime("%Y-%m-%d"))')
OLD_TS=$(python3 -c 'import datetime; print((datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=35)).isoformat())')

cat > "$T/state/repo-alpha.json" <<EOF
{
  "repo_path": "$T/work/repo-alpha",
  "checked_at": "$OLD_DATE",
  "skipped_at": "$OLD_DATE",
  "head_sha": "$BASE_SHA",
  "items_judged": {},
  "wontfix": []
}
EOF

# Add a recent Workflow tool_use with only scriptPath for wf-skill, and an old Skill call (35d ago) for hillclimb
cat >> "$T/projects/proj-a/s1.jsonl" <<EOF
{"uuid":"u4","timestamp":"$TS","message":{"role":"assistant","content":[{"type":"tool_use","id":"t2","name":"Workflow","input":{"scriptPath":"~/.claude/workflows/wf-skill.js"}}]}}
{"uuid":"u5","timestamp":"$OLD_TS","message":{"role":"assistant","content":[{"type":"tool_use","id":"t3","name":"Skill","input":{"skill":"hillclimb"}}]}}
EOF

cat > "$REG" <<EOF
{
  "hook-skill": {"mode": "hook-driven", "decided": true},
  "hillclimb": {"mode": "dual", "decided": false, "remind_after_days": 21, "remind_hint": "單一指標多輪調優", "last_skipped_at": "$OLD_DATE"},
  "deep-check": {"mode": "dual", "decided": true, "remind_after_days": 21, "remind_hint": "全庫深度健檢"},
  "wf-skill": {"mode": "dual", "decided": true, "remind_after_days": 21, "remind_hint": "工作流技能"}
}
EOF

cat > "$T/state/empty-path.json" <<EOF
{
  "repo_path": "",
  "checked_at": "$RECENT_DATE"
}
EOF

python3 ~/code/social-info/scripts/local-analysis/skill-trigger-health.py \
  --date 2026-11-04 --out "$T/report3.md" \
  --projects-dir "$T/projects" --skills-dir "$T/skills" --commands-dir "$T/commands" \
  --registry "$REG" --claude-git-dir "" \
  --deep-check-state-dir "$T/state" --repo-roots "$T/symlinks" > "$T/stdout3.txt"

check "decided=false 條目保留 remind_after_days 與 last_skipped_at" python3 -c "
import json, sys
r = json.load(open('$REG'))
h = r.get('hillclimb', {})
sys.exit(0 if h.get('remind_after_days') == 21 and h.get('last_skipped_at') == '$OLD_DATE' and h.get('remind_hint') == '單一指標多輪調優' else 1)
"
check "久未執行提醒段落出現且含 hillclimb 與 deep-check（wf-skill 因 Workflow scriptPath 剛跑過不列）" bash -c "
  grep -q '^## 🔔 久未執行提醒（2）' '$T/report3.md' &&
  grep -q '\`hillclimb\`' '$T/report3.md' &&
  grep -q '\`deep-check\`.*repo-alpha（+22 commits）' '$T/report3.md' &&
  ! grep -q '\`wf-skill\`.*久未執行' '$T/report3.md'
"
check "設有 remind_after_days 的零呼叫工具排除於死庫存候選並註記排除數" grep -q '排除 remind_after_days 1 個' "$T/report3.md"

echo "$pass/$((pass+fail)) passed"
[ "$fail" -eq 0 ]
