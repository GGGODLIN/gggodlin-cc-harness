#!/usr/bin/env bash
# Modified from the original work at https://github.com/anthropics/skills/tree/main/skills/skill-creator (Apache-2.0, copyright Anthropic, PBC). See THIRD_PARTY_NOTICES.md.
set -euo pipefail

SKILL="${HOME}/.claude/skills/skill-creator/SKILL.md"
PASS=0
FAIL=0

assert_grep() {
  local label="$1"
  local pattern="$2"
  if grep -qE "$pattern" "$SKILL"; then
    printf 'PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf 'FAIL: %s\n' "$label"
    FAIL=$((FAIL + 1))
  fi
}

assert_absent() {
  local label="$1"
  local pattern="$2"
  if grep -qE "$pattern" "$SKILL"; then
    printf 'FAIL: %s\n' "$label"
    FAIL=$((FAIL + 1))
  else
    printf 'PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  fi
}

assert_grep "skill marks its contract test" '本檔在契約測試底下.*skill-authoring-contract\.test\.sh'
assert_grep "red precedes skill edits" 'RED.*[Bb]efore changing skill text'
assert_grep "pre-red edits are discarded" '[Rr]estore the pre-change version and discard the untested wording'
assert_grep "baseline uses fresh context" 'fresh agent.*pre-change skill'
assert_grep "new file red closes both routes" 'Close both routes in the RED prompt.*Skill／slash-command invocation path'
assert_grep "red reading the tested file is invalid" 'trace shows the runner read the file under test as an 無效 baseline'
assert_grep "green reruns the same scenario" 'GREEN.*same scenario.*fresh agent'
assert_grep "refactor probes loopholes" 'REFACTOR.*pressure or loophole scenario'
assert_grep "loophole fixes rerun regressions" 'rerun the original scenario and every regression scenario'
assert_grep "retrofit candidate loophole is closed" 'Do not archive, consult, reapply, or adapt that candidate'
assert_grep "static checks do not replace behavior" 'Static validation.*does not replace behavioral evidence'
assert_grep "action scenarios require external evidence" '外部可觀察.*sentinel.*artifact'
assert_grep "zero tool action run is invalid" 'tool_uses=0.*invalid'
assert_grep "agent final is not behavior proof" 'agent final.*不算.*證據'
assert_grep "excerpt runners declare their evidence boundary" '節錄式 runner.*節錄邊界.*out-of-scope'
assert_grep "unreachable worker stops invalid reruns" 'worker 不可實例化.*行為驗證不可得.*caller.*產物'
assert_grep "behavior tests cannot bypass self-verify quota" '行為驗證.*Self-Verify.*一次 auditor.*不得.*例外'
# Item 15 (manual Collie palette sync through commands.toml) was retired 2026-10-14: the fork's
# bridge reads the skill and command files itself (Collie ADR 9009). It must not come back.
assert_absent "retired Collie palette sync stays out of closeout" '接第 15 項 Collie 面板清單'
assert_absent "retired Collie palette sync drops the config-dir step" 'herdr plugin config-dir herdr\.collie'
assert_grep "Collie palette needs no manual sync" 'Collie 手機面板不用手動同步.*ADR 9009'
assert_grep "mechanical edit takes deterministic checks" 'mechanical edit takes deterministic checks instead of the loop'
assert_grep "unclassifiable edit is not mechanical" 'an edit you cannot classify is not mechanical'
assert_grep "mechanical check: references exist" 'path, file and link on each changed line exists'
assert_grep "mechanical check: commands against help" 'changed command is checked against `--help`'
assert_grep "mechanical check: old name left behind" 'old name or path.*returns nothing left behind'
assert_grep "unreproduced RED stops the loop" 'stop the loop: do not run GREEN or REFACTOR'
assert_grep "unreproduced RED is reported to the user" '無法證明有問題.*let the user decide'
assert_grep "failure form selector exists" 'Failure form.*Guidance form'
assert_grep "frontmatter separates runtime requirements" 'runtime required'
assert_grep "frontmatter separates validator acceptance" 'local validator accepted'
assert_grep "frontmatter separates local convention" 'local convention'
assert_grep "validator allowlist is not platform support" 'allowlist.*platform support'
assert_grep "model invocation stays enabled by default" 'disable-model-invocation.*default.*不使用'
assert_grep "disabled invocation needs user-only reason" 'user-only.*理由'
assert_grep "disabled invocation needs inbound wiring" 'disable-model-invocation.*inbound wiring'
assert_grep "inbound inventory scans all wiring surfaces" 'skill.*command.*workflow.*registry.*frontmatter'
assert_grep "inbound inventory scans prose invocation" 'Skill.*slash.*prose'
assert_grep "inbound inventory records path and line" 'path:line'
assert_grep "unregistered dynamic wiring is unverified" 'dynamic.*planned.*unverified'
assert_grep "pipeline children stay model-callable" 'pipeline-gated child.*model-callable'
assert_grep "trigger conditions are authoring guidance" 'trigger condition.*authoring guidance'
assert_grep "trigger conditions are not hard gates" 'trigger condition.*not.*runtime hard gate'
assert_grep "context pointers use executable sentence form" '如果 X，就在 Y 前讀 Z'
assert_grep "context pointer predicate is observable" 'X.*可觀察'
assert_grep "context pointer names timing" 'Y.*時點'
assert_grep "context pointer names location" 'Z.*location'
assert_grep "pressure keeps active parent edges callable" 'hard flag.*suppress.*active parent edge'
assert_absent "retired Codex entry sync is not an authoring step" 'Codex 端入口盤點'
assert_absent "frontmatter does not ban classified optional fields" 'Do not include any other fields in YAML frontmatter'
assert_absent "no-op does not escalate vague adjectives" 'weak leading word.*relentless'
assert_grep "no-op rewrites vague adjectives as observable criteria" '模糊形容詞.*可觀察結果.*驗證條件.*不要只換成更強的形容詞'
assert_absent "superpowers writing dependency removed" 'superpowers:writing-skills'

printf 'PASS=%s FAIL=%s\n' "$PASS" "$FAIL"

if (( FAIL > 0 )); then
  exit 1
fi
