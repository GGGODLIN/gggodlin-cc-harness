#!/usr/bin/env bash
# sem-pr-blast-radius.sh <repo> <base-ref> [<review-diff>]
# 對 PR diff（base..HEAD）中 modified 的既有 entity 算彙總 blast radius，給 /pr-review
# Step 2.9 注入 CC reviewer context。graceful: 無 sem / 非 git / parse 失敗 → 靜默 exit 0。
# 補強而非依賴。對應工具: sem (Ataraxy-Labs/sem)。trial — review 2026-06-22。
set -euo pipefail
export SEM_CACHE_DIR="${SEM_CACHE_DIR:-$HOME/.cache/sem}"
repo="${1:-.}"; base="${2:-}"; review_diff="${3:-}"
command -v sem >/dev/null 2>&1 || exit 0
git -C "$repo" rev-parse 2>/dev/null >/dev/null || exit 0
[ -n "$base" ] || exit 0
if [ -z "$review_diff" ]; then
  mb="$(git -C "$repo" merge-base "$base" HEAD 2>/dev/null || true)"
  [ -n "$mb" ] && base="$mb"
fi

SEM_REPO="$repo" SEM_BASE="$base" SEM_REVIEW_DIFF="$review_diff" python3 <<'PY' 2>/dev/null || true
import os, re, subprocess, json
repo = os.environ["SEM_REPO"]; base = os.environ["SEM_BASE"]
review_diff = os.environ.get("SEM_REVIEW_DIFF", "")
CAP = 60
KINDS = {"function", "class", "method", "struct", "enum"}

def sem(args):
    try:
        o = subprocess.run(["sem", *args], cwd=repo, capture_output=True, text=True, timeout=30)
        if o.returncode != 0 or not o.stdout.strip():
            return None
        return json.loads(o.stdout)
    except Exception:
        return None

d = sem(["diff", "--from", base, "--to", "HEAD", "--format", "json"])
if not isinstance(d, dict):
    raise SystemExit(0)

def review_diff_files(path):
    try:
        text = open(path, encoding="utf-8").read()
    except Exception:
        return set()
    return {m.group(1) for m in re.finditer(r"^diff --git a/.* b/(.*)$", text, re.M)}

if review_diff:
    diff_files = review_diff_files(review_diff)
else:
    try:
        diff_files = set(subprocess.run(
            ["git", "diff", "--name-only", f"{base}..HEAD"],
            cwd=repo, capture_output=True, text=True, timeout=15,
        ).stdout.split())
    except Exception:
        diff_files = set()
if not diff_files:
    raise SystemExit(0)

seen, rows, calls = set(), [], 0
for c in d.get("changes", []):
    if c.get("changeType") != "modified" or c.get("entityType") not in KINDS:
        continue
    if c.get("filePath") not in diff_files:
        continue
    eid = c.get("entityId")
    if not eid or eid in seen:
        continue
    seen.add(eid)
    if calls >= CAP:
        break
    calls += 1
    imp = sem(["impact", "--entity-id", eid, "--json"])
    if not isinstance(imp, dict):
        continue
    deps = [x for x in imp.get("dependents", []) if x.get("type") != "test"]
    if deps:
        rows.append((len(deps), len(imp.get("tests", [])), c.get("entityName"), c.get("filePath")))

if not rows:
    raise SystemExit(0)

rows.sort(reverse=True)
print("### sem blast radius（本 PR 改動的既有 entity 影響面）\n")
for deps, tests, name, f in rows[:12]:
    warn = " ⚠️ 0 tests" if tests == 0 else f" / {tests} tests"
    print(f"- `{name}` ({f}): {deps} dependents{warn}")
PY
exit 0
