#!/usr/bin/env bash
set -uo pipefail

SKILL="${IMPLEMENT_SKILL_PATH:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/SKILL.md}"
PASS=0
FAIL=0

check() {
  local label=$1 pattern=$2
  if grep -qE "$pattern" "$SKILL"; then
    printf 'PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf 'FAIL: %s\n' "$label"
    FAIL=$((FAIL + 1))
  fi
}

check_absent() {
  local label=$1 pattern=$2
  if grep -qE "$pattern" "$SKILL"; then
    printf 'FAIL: %s\n' "$label"
    FAIL=$((FAIL + 1))
  else
    printf 'PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  fi
}

check_order() {
  local label=$1 first=$2 second=$3 third=$4
  local a b c
  a=$(grep -nE "$first" "$SKILL" | cut -d: -f1 | head -1)
  b=$(grep -nE "$second" "$SKILL" | cut -d: -f1 | head -1)
  c=$(grep -nE "$third" "$SKILL" | cut -d: -f1 | head -1)
  if [ -n "$a" ] && [ -n "$b" ] && [ -n "$c" ] && [ "$a" -lt "$b" ] && [ "$b" -lt "$c" ]; then
    printf 'PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf 'FAIL: %s\n' "$label"
    FAIL=$((FAIL + 1))
  fi
}

check 'header marks architecture visual contract' 'architecture-visual-gate-contract\.test\.sh'
check 'base SHA captured before feature commits' 'feature_base_sha.*第一筆 feature commit'
check 'detector uses boundary and cross-boundary edge' '邊界.*跨邊界連線'
check 'candidate asks before generation' 'a\. 產生 actual delta.*b\. 這次不用'
check 'no answer blocks without generation' 'no response.*0 次 Archify invoke.*BLOCKED'
check 'waiver binds human decision and head SHA' 'waived.*人類決策.*head_sha'
check 'generation uses safe wrapper' 'archify-safe\.mjs actual-delta'
check 'diagram labels follow user language' 'title.*component label.*connection label.*使用者語言'
check 'local profile uses plain Traditional Chinese' '本機 profile.*繁體中文白話'
check 'technical terms keep names with short annotations' '保留.*hook.*skill.*API.*括號註釋'
check 'connection labels explain handoff plainly' 'connection label.*誰把什麼交給誰'
check 'bare technical labels are forbidden' '不得只留下.*embedding.*receipt.*permit.*runner'
check 'opaque product names also need annotations' '產品名.*不能.*免註釋.*label.*看不出用途'
check_order 'safe wrapper receipt/path/head validation precedes actual-delta adapter' 'archify-safe\.mjs actual-delta' 'wrapper receipt.*artifact path／存在.*base/head SHA.*最終.*head_sha' 'plannotator-review\.mjs actual-delta'
check_absent 'wrapper receipt validation names no artifact hash' 'artifact path/hash|artifact hash drift|綁 path/hash'
check_order 'generation choice precedes Archify and Plannotator' 'a\. 產生 actual delta.*b\. 這次不用' 'archify-safe\.mjs actual-delta' 'plannotator-review\.mjs actual-delta'
check_order 'adapter approval precedes accepted release' 'plannotator-review\.mjs actual-delta' 'Adapter exit 0.*decision.*approved.*transition.*accepted' 'visual decision.*accepted.*允許 shipping'
check 'no response also blocks Plannotator' 'no response.*0 次 Archify invoke.*0 次 Plannotator invoke.*BLOCKED'
check 'waiver preserves both SHA bindings' 'b.*waived.*feature_base_sha.*最終.*head_sha'
check 'waiver does not start Plannotator' 'b.*不啟動 Plannotator'
check 'actual-delta adapter command is exact' 'node ~/\.claude/scripts/plannotator-review\.mjs actual-delta <wrapper-receipt> <head_sha>'
check 'actual-delta adapter launches as one background task' 'Bash\(run_in_background=true\).*plannotator-review\.mjs actual-delta'
check 'actual-delta task binds receipt and head identity' 'adapterTaskId.*wrapper receipt identity.*head_sha'
check 'background handoff is not an adapter timeout' 'moved to background.*仍在執行.*不是.*adapter timeout'
check 'live actual-delta task is never relaunched' 'adapter task.*live.*不得啟動第二支'
check 'actual-delta waits for harness completion' 'task-notification.*completed.*failed'
check 'actual-delta reads one completed output and receipt' 'Read.*output file.*一次.*唯一.*receipt'
check 'actual-delta does not ask for manual relaunch' '不得要求.*user shell.*重跑'
check_order 'background task completes before accepted release' 'Bash\(run_in_background=true\).*plannotator-review\.mjs actual-delta' 'task-notification' 'Adapter exit 0.*decision.*approved.*transition.*accepted'
check 'adapter receipt path feedback and head are handed off' 'adapter receipt path.*feedback.*最終.*head_sha.*closeout handoff'
check 'approved outcome requires matching head' 'approved.*transition.*accepted.*同一最終.*head_sha'
check 'Approve with Notes remains accepted' 'Approve with Notes.*accepted'
check 'Approve with Notes persists notes' '保存 notes 不阻擋'
check 'annotated maps to classification required' 'annotated.*transition.*classification-required'
check 'annotated feedback blocks closeout' '保存 feedback.*closeout.*BLOCKED'
check 'classification belongs to top-level human' 'top-level human.*分類.*artifact-inaccurate.*architecture-rejected'
check 'classification agent never guesses' 'agent 不得猜測'
check 'classification no-answer blocks' 'classification no-answer.*BLOCKED'
check 'artifact-inaccurate keeps the same SHA pair' 'artifact-inaccurate.*同一組.*feature_base_sha.*head_sha'
check 'artifact-inaccurate does not change code or commit' 'artifact-inaccurate.*不修改 code.*不建立新 commit'
check 'architecture rejection returns to implement' 'architecture-rejected.*回到 implement'
check 'architecture rejection creates a new commit' 'architecture-rejected.*新 commit'
check 'architecture rejection reruns both gates' 'architecture-rejected.*兩道 gate 都重跑'
check 'dismissed remains blocked' 'dismissed.*BLOCKED'
check 'timeout remains blocked' 'timeout.*BLOCKED'
check 'gate-error remains blocked' 'gate-error.*BLOCKED'
check 'invalid or missing result remains blocked' '無效或缺少 result.*BLOCKED'
check 'result artifact receipt and head drift remain blocked' 'result／artifact／source-receipt／head drift.*BLOCKED'
check 'blocked outcomes cannot become waiver or accepted' '不會變成 waiver 或.*accepted'
check 'shipping binds latest review and adapter receipt' '最新.*review-implement.*terminal outcome.*最新 adapter visual decision receipt.*同一最終.*head_sha'
check 'rollback removes adapter runtime and receipts' 'rollback.*移除 Plannotator adapter.*runtime 變更.*receipts'
check 'rollback preserves Archify evidence' '保留既有 Archify trial evidence'
check 'rollback scripts belong to Ticket 05' 'rollback script 與 fixture.*Ticket 05'
check 'artifact and architecture rejection are separate' 'artifact-inaccurate.*architecture-rejected'
check 'code change invalidates both receipts' 'review-implement.*visual.*同時失效'
check 'ship requires matching final SHA' '同一最終 `head_sha`'
check 'review implement axes stay canonical' '不得修改.*review-implement.*scope.*YAGNI'
check_order 'visual gate is between review and repo closeout' '^7\. After the local commit' '^8\. Architecture visual candidate gate' '^9\. Follow the repo'

printf '%s\n' '----'
printf 'PASS=%s FAIL=%s\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
