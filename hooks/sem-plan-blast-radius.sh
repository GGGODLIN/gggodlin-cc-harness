#!/usr/bin/env bash
# PostToolUse(Write|Edit): openspec tasks 落檔 → 對 tasks 要 Modify 的既有檔算 sem
# blast radius，注入 execute 前提醒。盯輸出路徑、graceful skip（無 sem / 非 git /
# parse 失敗一律 exit 0 不擋流程），與 review-spec-tier1-nudge.sh 同 pattern。
# 補強而非依賴：sem 不在照樣跑。對應工具: sem (Ataraxy-Labs/sem)。trial — review 2026-06-22。
set -euo pipefail
export SEM_CACHE_DIR="${SEM_CACHE_DIR:-$HOME/.cache/sem}"

input=$(cat)
file_path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // ""' 2>/dev/null || echo "")

case "$file_path" in
  *openspec/changes/*/tasks.md) ;;
  *) exit 0 ;;
esac

command -v sem >/dev/null 2>&1 || exit 0
[ -f "$file_path" ] || exit 0
repo=$(git -C "$(dirname "$file_path")" rev-parse --show-toplevel 2>/dev/null) || exit 0

summary=$(SEM_PLAN_FILE="$file_path" SEM_REPO="$repo" python3 <<'PY' 2>/dev/null || true
import os, re, subprocess, json

plan = os.environ["SEM_PLAN_FILE"]
repo = os.environ["SEM_REPO"]
CALL_CAP = 50
KINDS = {"function", "class", "struct", "enum"}

def sem(args):
    try:
        out = subprocess.run(["sem", *args], cwd=repo, capture_output=True, text=True, timeout=20)
        if out.returncode != 0 or not out.stdout.strip():
            return None
        return json.loads(out.stdout)
    except Exception:
        return None

text = open(plan, encoding="utf-8", errors="ignore").read()
files = []
for m in re.finditer(r'Modify:\s*`?([^`\s:]+)', text):
    f = m.group(1)
    if f not in files:
        files.append(f)
files = files[:15]

rows, calls = [], 0
for f in files:
    ents = sem(["entities", f, "--json"])
    if not isinstance(ents, list):
        continue
    tops = [e for e in ents if e.get("parent_id") is None and e.get("type") in KINDS][:10]
    for e in tops:
        if calls >= CALL_CAP:
            break
        calls += 1
        imp = sem(["impact", "--entity-id", f"{f}::{e['type']}::{e['name']}", "--json"])
        if not isinstance(imp, dict):
            continue
        deps = [d for d in imp.get("dependents", []) if d.get("type") != "test"]
        if deps:
            rows.append((len(deps), len(imp.get("tests", [])), e["name"], f))

if not rows:
    raise SystemExit(0)

rows.sort(reverse=True)
lines = []
for deps, tests, name, f in rows[:10]:
    warn = " ⚠️ 0 tests" if tests == 0 else f" / {tests} tests"
    lines.append(f"- `{name}` ({f}): {deps} dependents{warn}")
print("\n".join(lines))
PY
)

[ -z "$summary" ] && exit 0

ctx="📐 sem blast radius — 這份 plan 要改的既有 entity（execute 前確認高影響面有沒有漏 test / 漏改 dependent；標 ⚠️ 0 tests 的改動沒有測試守護）:
$summary"

jq -n --arg c "$ctx" '{hookSpecificOutput:{hookEventName:"PostToolUse",additionalContext:$c}}'
exit 0
