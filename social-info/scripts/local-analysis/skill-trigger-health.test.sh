#!/bin/bash
# gate-authoring 三件 fixture 回歸：known-good（auto-only 純自動 → 不警報）/
# known-bad（auto-only 被手動 slash → 必警報）/ 邊界（dual 被手動 slash → 不警報）。
# 改 skill-trigger-health.py 後必跑本檔。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$SCRIPT_DIR/skill-trigger-health.py"

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
python3 "$SCRIPT" \
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
  python3 "$SCRIPT" \
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

python3 "$SCRIPT" \
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

# P2 & P6 regression: mtime-selected session file with >90d event must not inflate 90d window, and decided_by="agent" stays distinguishable
mkdir -p "$T/skills/mixed-window-skill" "$T/skills/agent-decided-skill"
printf -- '---\nname: mixed-window-skill\ndescription: Use when testing 90d window cutoff.\n---\n' > "$T/skills/mixed-window-skill/SKILL.md"
printf -- '---\nname: agent-decided-skill\ndescription: Use when testing agent-decided mode preservation.\n---\n' > "$T/skills/agent-decided-skill/SKILL.md"

ANCIENT_TS=$(python3 -c 'import datetime; print((datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=120)).isoformat())')
FUTURE_TS=$(python3 -c 'import datetime; print((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)).isoformat())')
cat >> "$T/projects/proj-a/s1.jsonl" <<EOF
{"uuid":"future-auto","timestamp":"$FUTURE_TS","message":{"role":"assistant","content":[{"type":"tool_use","id":"t_future","name":"Skill","input":{"skill":"mixed-window-skill"}}]}}
{"uuid":"future-manual","timestamp":"$FUTURE_TS","message":{"role":"user","content":"<command-name>/mixed-window-skill</command-name>"}}
{"uuid":"u6","timestamp":"$ANCIENT_TS","message":{"role":"assistant","content":[{"type":"tool_use","id":"t_old_120d","name":"Skill","input":{"skill":"mixed-window-skill"}}]}}
{"uuid":"u7","timestamp":"$TS","message":{"role":"assistant","content":[{"type":"tool_use","id":"t_now_0d","name":"Skill","input":{"skill":"mixed-window-skill"}}]}}
{"uuid":"u8","timestamp":"$TS","message":{"role":"assistant","content":[{"type":"tool_use","id":"t_agent_dec","name":"Skill","input":{"skill":"agent-decided-skill"}}]}}
EOF

python3 -c "
import json
r = json.load(open('$REG'))
r['agent-decided-skill'] = {'mode': 'dual', 'decided': True, 'decided_by': 'agent'}
json.dump(r, open('$REG', 'w'))
"

python3 "$SCRIPT" \
  --date 2026-11-11 --out "$T/report4.md" \
  --projects-dir "$T/projects" --skills-dir "$T/skills" --commands-dir "$T/commands" \
  --registry "$REG" --claude-git-dir "" \
  --deep-check-state-dir "$T/state" --repo-roots "$T/symlinks" > "$T/stdout4.txt"

check "P2: 90d 與近期計數排除 120 天前和未來事件，僅計入有效呼叫" grep -q '| `mixed-window-skill` | auto-only (未拍板) | 1 | 0 | 1 |' "$T/report4.md"
check "P6: decided_by=agent 保留 mode 不被覆寫且報告標註 (agent自決)" bash -c "
  python3 -c \"import json, sys; e = json.load(open('$REG'))['agent-decided-skill']; sys.exit(0 if e.get('mode') == 'dual' and e.get('decided') is True and e.get('decided_by') == 'agent' else 1)\" &&
  grep -q '| \`agent-decided-skill\` | dual (agent自決) | 1 | 0 | 1 |' '$T/report4.md'
"

# Wave 19 regression tests: missing id/uuid same-second collision, cross-file fork >90d resurrection,
# >90d remind_after_days scan_cut, corrupt registry preservation, non-dict JSON/settings resilience,
# frontmatter BOM/multiline/comment-true, ASCII locale, and CLI validation.
T2="$T/w19"
mkdir -p "$T2/skills/no-id-skill" "$T2/skills/fork-old-skill" "$T2/skills/long-remind-skill" "$T2/skills/multiline-skill" "$T2/commands" "$T2/projects/proj-b"
printf -- '---\nname: no-id-skill\ndescription: Auto skill without tool ids.\n---\n' > "$T2/skills/no-id-skill/SKILL.md"
printf -- '---\nname: fork-old-skill\ndescription: Old skill forked without ts.\n---\n' > "$T2/skills/fork-old-skill/SKILL.md"
printf -- '---\nname: long-remind-skill\ndescription: Long cadence skill.\n---\n' > "$T2/skills/long-remind-skill/SKILL.md"
# UTF-8 BOM + YAML multiline description + comment containing 'true' on false disable-model-invocation
python3 - "$T2/skills/multiline-skill/SKILL.md" <<'PY'
import sys
text = "﻿---\nname: multiline-skill\ndescription: |\n  Use when manually triggered.\n  可手動呼叫 /multiline-skill。\ndisable-model-invocation: false # not true\n---\n"
open(sys.argv[1], "w", encoding="utf-8").write(text)
PY

TS_100D="$(python3 -c 'import datetime; print((datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=100)).isoformat())')"
TS_120D="$(python3 -c 'import datetime; print((datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=120)).isoformat())')"
EPOCH_NOW="$(python3 -c 'import time; print(int(time.time()))')"

# Same-turn / same-second Skill & Workflow without id + identical user lines without uuid + malformed lines
cat > "$T2/projects/proj-b/a_calls.jsonl" <<EOF
["Skill", "skill"]
{"timestamp":"$TS","message":"not-a-dict","Skill":"skill"}
{"timestamp":$EPOCH_NOW,"message":{"role":"assistant","content":[{"type":"tool_use","name":"Skill","input":{"skill":"no-id-skill"}},{"type":"tool_use","name":"Skill","input":{"skill":"no-id-skill"}},{"type":"tool_use","id":["bad"],"name":"Skill","input":{"skill":["bad"]}}]}}
{"timestamp":"$TS","message":{"role":"user","content":"<command-name>/no-id-skill</command-name>"}}
{"timestamp":"$TS","message":{"role":"user","content":"<command-name>/no-id-skill</command-name>"}}
{"timestamp":"$TS_120D","message":{"role":"assistant","content":[{"type":"tool_use","id":"fork-dup-1","name":"Skill","input":{"skill":"fork-old-skill"}}]}}
EOF

# Fork file missing timestamp (would fall back to recent mtime) must NOT resurrect >90d event
cat > "$T2/projects/proj-b/b_fork.jsonl" <<EOF
{"message":{"role":"assistant","content":[{"type":"tool_use","id":"fork-dup-1","name":"Skill","input":{"skill":"fork-old-skill"}}]}}
EOF

# File with mtime 100d ago (older than 90d dead window) containing invoke for skill with remind_after_days=120
cat > "$T2/projects/proj-b/c_long.jsonl" <<EOF
{"timestamp":"$TS_100D","message":{"role":"assistant","content":[{"type":"tool_use","id":"long-1","name":"Skill","input":{"skill":"long-remind-skill"}}]}}
EOF
python3 - "$T2/projects/proj-b/c_long.jsonl" <<'PY'
import os, sys, time
t = time.time() - 100 * 86400
os.utime(sys.argv[1], (t, t))
PY

# Registry with valid entry, non-dict entry, and string "false" decided
REG2="$T2/sub/reg.json"
mkdir -p "$(dirname "$REG2")"
cat > "$REG2" <<'EOF'
{
  "long-remind-skill": {"mode": "dual", "decided": true, "remind_after_days": 120},
  "no-id-skill": {"mode": "auto-only", "decided": "false", "remind_after_days": 30},
  "fork-old-skill": "broken-non-dict-entry"
}
EOF

# Fake HOME with malformed settings.json (skillOverrides: null) under ASCII locale
FAKE_HOME2="$T2/fake-home"
mkdir -p "$FAKE_HOME2/.claude"
printf '{"skillOverrides": null}\n' > "$FAKE_HOME2/.claude/settings.json"

HOME="$FAKE_HOME2" LC_ALL=C LANG=C PYTHONCOERCECLOCALE=0 PYTHONUTF8=0 \
  python3 "$SCRIPT" \
  --date 2026-11-24 --out "$T2/nested/report.md" \
  --projects-dir "$T2/projects" --skills-dir "$T2/skills" --commands-dir "$T2/commands" \
  --registry "$REG2" --claude-git-dir "" > "$T2/run.out" 2>"$T2/run.err"

check "缺 id 同秒雙 Skill 與缺 uuid 重複手動呼叫不被誤併（auto=2, manual=2）" grep -q '| `no-id-skill` | auto-only (未拍板) | 2 | 2 | 4 |' "$T2/nested/report.md"
check "跨檔 fork 缺 timestamp 不復活 >90d 舊事件（fork-old-skill 不進活躍表）" bash -c "! grep -q '| \`fork-old-skill\` |' '$T2/nested/report.md'"
check "remind_after_days=120 掃到 100d 前舊檔不誤觸久未執行提醒" bash -c "! grep -q '\`long-remind-skill\`' '$T2/nested/report.md'"
check "BOM＋YAML 多行中文描述正確判為 dual 且 comment true 不誤設 disable" python3 -c "
import json, sys
r = json.load(open('$REG2', encoding='utf-8'))
ok = r['multiline-skill']['mode'] == 'dual' and r['no-id-skill']['decided'] is False and r['no-id-skill']['remind_after_days'] == 30 and r['long-remind-skill']['decided'] is True
sys.exit(0 if ok else 1)
"
check "原子寫入無殘留 .tmp 檔" bash -c "[ -z \"\$(find '$T2/nested' '$(dirname "$REG2")' -name '*.tmp')\" ]"

# Corrupt registry JSON must NOT crash and must NOT overwrite/destroy the file on disk
CORRUPT_REG="$T2/corrupt-reg.json"
printf '{"keep-me": {"mode": "dual", "decided": true,},}\n' > "$CORRUPT_REG"
cp "$CORRUPT_REG" "$T2/corrupt-reg.orig"
HOME="$FAKE_HOME2" python3 "$SCRIPT" \
  --date 2026-11-24 --out "$T2/report-corrupt.md" \
  --projects-dir "$T2/projects" --skills-dir "$T2/skills" --commands-dir "$T2/commands" \
  --registry "$CORRUPT_REG" --claude-git-dir "" > "$T2/corrupt.out" 2>"$T2/corrupt.err"

check "壞 JSON registry 容錯不崩潰且原檔不被覆寫破壞" cmp -s "$T2/corrupt-reg.orig" "$CORRUPT_REG"
check "壞 JSON registry 在 stderr 輸出警告" grep -q "WARNING:" "$T2/corrupt.err"

# CLI flag & missing directory validation (exit 2)
rc_cap=0
HOME="$FAKE_HOME2" python3 "$SCRIPT" \
  --date 2026-11-24 --out "$T2/bad-cap.md" \
  --projects-dir "$T2/projects" --skills-dir "$T2/skills" --commands-dir "$T2/commands" \
  --registry "$REG2" --claude-git-dir "" --dead-cap -1 >/dev/null 2>&1 || rc_cap=$?
check "--dead-cap -1 回傳 exit 2" test "$rc_cap" -eq 2

rc_win=0
HOME="$FAKE_HOME2" python3 "$SCRIPT" \
  --date 2026-11-24 --out "$T2/bad-win.md" \
  --projects-dir "$T2/projects" --skills-dir "$T2/skills" --commands-dir "$T2/commands" \
  --registry "$REG2" --claude-git-dir "" --dead-window-days 0 >/dev/null 2>&1 || rc_win=$?
check "--dead-window-days 0 回傳 exit 2" test "$rc_win" -eq 2

rc_miss=0
HOME="$FAKE_HOME2" python3 "$SCRIPT" \
  --date 2026-11-24 --out "$T2/bad-miss.md" \
  --projects-dir "$T2/does-not-exist" --skills-dir "$T2/skills" --commands-dir "$T2/commands" \
  --registry "$REG2" --claude-git-dir "" >/dev/null 2>&1 || rc_miss=$?
check "缺 --projects-dir 回傳 exit 2" test "$rc_miss" -eq 2

echo "$pass/$((pass+fail)) passed"
[ "$fail" -eq 0 ]
