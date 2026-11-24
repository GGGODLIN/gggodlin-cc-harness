#!/usr/bin/env bash
# 本檔在契約測試底下：bash ~/.claude/hooks/contract-test-preflight-gate.test.sh
# Fixture 覆蓋 known-good、known-bad、邊界、生命週期與 helper 失效；輸入只走 hook stdin，觀察 stdout、stderr、exit code。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK="$ROOT/hooks/contract-test-preflight-gate.sh"
HELPER="$ROOT/scripts/contract-test-helper.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0
FAIL=0

make_payload() {
  local path=$1 session=$2 cwd=$3 tool=${4:-Edit}
  jq -nc --arg path "$path" --arg session "$session" --arg cwd "$cwd" --arg tool "$tool" \
    '{hook_event_name:"PreToolUse",session_id:$session,cwd:$cwd,tool_name:$tool,tool_input:{file_path:$path}}'
}

run_case() {
  local name=$1 path=$2 session=$3 state=$4 helper=${5:-$HELPER} tool=${6:-Edit} repo_root=${7:-}
  local -a extra=()
  [ -n "$repo_root" ] && extra=(CONTRACT_TEST_REPO_ROOT="$repo_root")
  make_payload "$path" "$session" "$(dirname "$path")" "$tool" \
    | env CONTRACT_TEST_STATE_DIR="$state" CONTRACT_TEST_HELPER="$helper" ${extra[@]+"${extra[@]}"} "$HOOK" \
      >"$TMP/$name.out" 2>"$TMP/$name.err"
  printf '%s' "$?" >"$TMP/$name.rc"
}

out() { cat "$TMP/$1.out"; }
err() { cat "$TMP/$1.err"; }
rc() { cat "$TMP/$1.rc"; }

check() {
  local label=$1 ok=$2 detail=${3:-}
  if [ "$ok" -eq 0 ]; then
    printf 'PASS %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf 'FAIL %s%s\n' "$label" "${detail:+ — $detail}"
    FAIL=$((FAIL + 1))
  fi
}

assert_rc() {
  local label=$1 name=$2 want=$3 actual
  actual=$(rc "$name")
  check "$label" "$([ "$actual" = "$want" ] && printf 0 || printf 1)" "actual exit=$actual want=$want"
}

assert_empty() {
  local label=$1 name=$2 stream=$3 value
  if [ "$stream" = stdout ]; then value=$(out "$name"); else value=$(err "$name"); fi
  check "$label" "$([ -z "$value" ] && printf 0 || printf 1)" "unexpected $stream: $value"
}

assert_contains() {
  local label=$1 name=$2 stream=$3 needle=$4 value
  if [ "$stream" = stdout ]; then value=$(out "$name"); else value=$(err "$name"); fi
  printf '%s' "$value" | grep -Fq -- "$needle"
  check "$label" "$?" "missing $needle in $stream: $value"
}

assert_deny_json() {
  local label=$1 name=$2 needle=${3:-} value
  value=$(out "$name")
  printf '%s' "$value" | jq -e --arg needle "$needle" '
    (. | type == "object")
    and ((has("decision") or has("reason")) | not)
    and (.hookSpecificOutput.hookEventName == "PreToolUse")
    and (.hookSpecificOutput.permissionDecision == "deny")
    and ((.hookSpecificOutput.permissionDecisionReason | type) == "string")
    and ((.hookSpecificOutput.permissionDecisionReason | length) > 0)
    and ($needle == "" or (.hookSpecificOutput.permissionDecisionReason | contains($needle)))
  ' >/dev/null 2>&1
  check "$label" "$?" "invalid PreToolUse deny JSON in stdout: $value"
}

clean_root="$TMP/clean/.claude"
mkdir -p "$clean_root/commands"
printf '%s\n' '# clean command' >"$clean_root/commands/clean.md"
run_case clean "$clean_root/commands/clean.md" clean-session "$TMP/state-clean"
assert_rc 'known-good: no exam allows edit' clean 0
assert_empty 'known-good: no exam is silent on stdout' clean stdout
assert_empty 'known-good: no exam is silent on stderr' clean stderr

marked_root="$TMP/marked/.claude"
marked_tests="$marked_root/commands/tests"
mkdir -p "$marked_tests"
marked_test="$marked_tests/marked-contract.test.sh"
printf '%s\n' '#!/usr/bin/env bash' 'exit 0' >"$marked_test"
chmod +x "$marked_test"
printf '%s\n' "<!-- 本檔在契約測試底下：bash $marked_test -->" '# marked command' >"$marked_root/commands/marked.md"
mkdir -p "$marked_root/commands"
marked_state="$TMP/state-marked"
run_case marked "$marked_root/commands/marked.md" marked-session "$marked_state"
assert_rc 'known-bad: header-marked command denies first edit with exit 0' marked 0
assert_empty 'known-bad: header-marked deny keeps stderr empty' marked stderr
assert_deny_json 'known-bad: denial emits valid PreToolUse hookSpecificOutput JSON with test command' marked "$marked_test"
assert_contains 'known-bad: denial explains retry release' marked stdout '重試原本的 Edit／Write 即放行'
assert_contains 'known-bad: denial asks for missing marker' marked stdout '無標記者請補檔頭標記'
assert_contains 'known-bad: denial states the edit was not applied' marked stdout '這次修改未套用'
check 'known-bad: denial reason opens with unambiguous non-applied notice' "$(jq -e '.hookSpecificOutput.permissionDecisionReason | startswith("這次修改未套用")' "$TMP/marked.out" >/dev/null 2>&1 && printf 0 || printf 1)"
run_case marked-retry "$marked_root/commands/marked.md" marked-session "$marked_state"
assert_rc 'boundary: same session retry allows' marked-retry 0
assert_empty 'boundary: retry is silent on stdout' marked-retry stdout
assert_empty 'boundary: retry is silent on stderr' marked-retry stderr
run_case marked-write "$marked_root/commands/marked.md" marked-write-session "$TMP/state-marked-write" "$HELPER" Write
assert_rc 'known-bad: Write uses the same preflight gate with exit 0' marked-write 0
assert_empty 'known-bad: Write deny keeps stderr empty' marked-write stderr
assert_deny_json 'known-bad: Write denial emits valid PreToolUse JSON with test command' marked-write "$marked_test"

boundary_root="$TMP/boundary/.claude"
boundary_tests="$boundary_root/commands/tests"
mkdir -p "$boundary_tests" "$boundary_root/commands"
boundary_test="$boundary_tests/boundary-contract.test.sh"
printf '%s\n' "asserts boundary.md" >"$boundary_test"
printf '%s\n' '# no header marker' >"$boundary_root/commands/boundary.md"
run_case boundary "$boundary_root/commands/boundary.md" boundary-session "$TMP/state-boundary"
assert_rc 'boundary: grep-only reference denies first edit with exit 0' boundary 0
assert_empty 'boundary: grep-only deny keeps stderr empty' boundary stderr
assert_deny_json 'boundary: grep-only result emits valid PreToolUse JSON with test' boundary "$boundary_test"

canonical_root="$TMP/symlink/canonical/.claude"
mkdir -p "$canonical_root/commands/tests" "$canonical_root/commands"
symlink_test="$canonical_root/commands/tests/symlink-contract.test.sh"
printf '%s\n' 'checks symlink.md' >"$symlink_test"
printf '%s\n' '# target through alternate config link' >"$canonical_root/commands/symlink.md"
ln -s "$canonical_root" "$TMP/symlink/.claude-alt"
run_case symlink "$TMP/symlink/.claude-alt/commands/symlink.md" symlink-session "$TMP/state-symlink"
assert_rc 'boundary: alternate config symlink resolves before matching with exit 0' symlink 0
assert_empty 'boundary: symlink deny keeps stderr empty' symlink stderr
assert_deny_json 'boundary: resolved symlink result emits valid PreToolUse JSON with test' symlink "$symlink_test"

skill_root="$TMP/skill/.claude"
skill_tests="$skill_root/skills/own/scripts/tests"
mkdir -p "$skill_tests" "$skill_root/skills/own/evals"
skill_test="$skill_tests/own-contract.test.sh"
printf '%s\n' '# skill contract' >"$skill_test"
printf '%s\n' '# own skill' >"$skill_root/skills/own/SKILL.md"
run_case own-skill "$skill_root/skills/own/SKILL.md" own-session "$TMP/state-own"
assert_rc 'boundary: skill-owned tests or evals directory counts as exam with exit 0' own-skill 0
assert_empty 'boundary: skill-owned deny keeps stderr empty' own-skill stderr
assert_deny_json 'boundary: skill-owned directory emits valid PreToolUse JSON with test' own-skill "$skill_test"

worktree_repo="$TMP/worktree/.claude"
worktree_root="$worktree_repo/.claude/worktrees/nested"
worktree_tests="$worktree_root/skills/own/scripts/tests"
mkdir -p "$worktree_tests"
worktree_test="$worktree_tests/own-contract.test.sh"
printf '%s\n' '# worktree skill contract' >"$worktree_test"
printf '%s\n' '# worktree skill' >"$worktree_root/skills/own/SKILL.md"
run_case worktree-skill "$worktree_root/skills/own/SKILL.md" worktree-session "$TMP/state-worktree"
assert_rc 'boundary: nested worktree skill denies first edit with exit 0' worktree-skill 0
assert_empty 'boundary: nested worktree deny keeps stderr empty' worktree-skill stderr
assert_deny_json 'boundary: nested worktree emits valid PreToolUse JSON with owning test' worktree-skill "$worktree_test"

# 2026-09-16 third-round trial finding: a worktree of the config repo may live anywhere
# (`~/Desktop/projects/.worktrees/<branch>/`), not only under `<root>/.claude/worktrees/`.
# Authority is git's own worktree pointer file, not the directory name.
gitwt_config="$TMP/gitwt/.claude"
mkdir -p "$gitwt_config/.git/worktrees/anywhere"
gitwt_root="$TMP/gitwt-elsewhere/.worktrees/feat-branch"
gitwt_tests="$gitwt_root/skills/own/scripts/tests"
mkdir -p "$gitwt_tests" "$gitwt_root/commands/tests"
printf 'gitdir: %s\n' "$gitwt_config/.git/worktrees/anywhere" >"$gitwt_root/.git"
gitwt_test="$gitwt_tests/own-contract.test.sh"
printf '%s\n' '# detached worktree skill contract' >"$gitwt_test"
printf '%s\n' '# detached worktree skill' >"$gitwt_root/skills/own/SKILL.md"
run_case gitwt-skill "$gitwt_root/skills/own/SKILL.md" gitwt-session "$TMP/state-gitwt" "$HELPER" Edit \
  "$gitwt_config"
assert_rc 'boundary: git worktree outside .claude denies first edit with exit 0' gitwt-skill 0
assert_empty 'boundary: git worktree skill deny keeps stderr empty' gitwt-skill stderr
assert_deny_json 'boundary: git worktree outside .claude emits valid PreToolUse JSON with owning test' gitwt-skill "$gitwt_test"

gitwt_cmd_test="$gitwt_root/commands/tests/detached-contract.test.sh"
printf '%s\n' '# detached worktree command contract' >"$gitwt_cmd_test"
printf '%s\n' '# 本檔在契約測試底下：bash commands/tests/detached-contract.test.sh' >"$gitwt_root/commands/detached.md"
gitwt_cmd_test=$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$gitwt_cmd_test")
run_case gitwt-command "$gitwt_root/commands/detached.md" gitwt-cmd-session "$TMP/state-gitwt-cmd" "$HELPER" Edit \
  "$gitwt_config"
assert_rc 'boundary: git worktree command outside .claude denies first edit with exit 0' gitwt-command 0
assert_empty 'boundary: git worktree command deny keeps stderr empty' gitwt-command stderr
assert_deny_json 'boundary: git worktree command emits valid PreToolUse JSON with owning test' gitwt-command "$gitwt_cmd_test"

# Reverse assertion: a worktree belonging to some OTHER repository must never be treated
# as this config root, or the gate would start listing unrelated repos' tests.
foreign_root="$TMP/foreign/.worktrees/other"
foreign_tests="$foreign_root/skills/own/scripts/tests"
mkdir -p "$foreign_tests" "$TMP/foreign-origin/.git/worktrees/other"
printf 'gitdir: %s\n' "$TMP/foreign-origin/.git/worktrees/other" >"$foreign_root/.git"
printf '%s\n' '# foreign contract' >"$foreign_tests/own-contract.test.sh"
printf '%s\n' '# foreign skill' >"$foreign_root/skills/own/SKILL.md"
run_case foreign-wt "$foreign_root/skills/own/SKILL.md" foreign-session "$TMP/state-foreign" "$HELPER" Edit \
  "$gitwt_config"
assert_rc 'security: foreign repo worktree is not treated as config root' foreign-wt 0
assert_empty 'security: foreign repo worktree stays silent' foreign-wt stdout

empty_root="$TMP/skill-empty/.claude"
mkdir -p "$empty_root/skills/empty/scripts/tests" "$empty_root/skills/empty/evals"
printf '%s\n' '# empty skill' >"$empty_root/skills/empty/SKILL.md"
run_case empty-skill "$empty_root/skills/empty/SKILL.md" empty-session "$TMP/state-empty"
assert_rc 'boundary: skill with only empty exam directories allows edit' empty-skill 0
assert_empty 'boundary: empty exam directories stay silent' empty-skill stdout
assert_empty 'boundary: empty exam directories emit no stderr' empty-skill stderr

pytest_root="$TMP/skill-pytest/.claude"
pytest_scripts="$pytest_root/skills/pytest-skill/scripts"
mkdir -p "$pytest_scripts/tests"
printf '%s\n' 'VALUE = 1' >"$pytest_scripts/helpers.py"
printf '%s\n' 'import helpers' '' 'def test_placeholder():' '    assert helpers.VALUE == 1' >"$pytest_scripts/tests/test_pytest_contract.py"
printf '%s\n' '# pytest skill' >"$pytest_root/skills/pytest-skill/SKILL.md"
pytest_scripts=$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$pytest_scripts")
run_case pytest-skill "$pytest_root/skills/pytest-skill/SKILL.md" pytest-session "$TMP/state-pytest"
assert_rc 'boundary: skill test_*.py denies first edit with exit 0' pytest-skill 0
assert_empty 'boundary: skill test_*.py deny keeps stderr empty' pytest-skill stderr
assert_deny_json 'boundary: skill test_*.py emits valid PreToolUse JSON with suite command' pytest-skill "cd $pytest_scripts && PYTHONPATH=$pytest_scripts uv run --no-project --with pytest --python 3.11 pytest tests/ -q"
check 'boundary: skill pytest files are not listed per file' "$(if grep -Eq 'pytest .+test_[A-Za-z_]+\.py' "$TMP/pytest-skill.out"; then printf 1; else printf 0; fi)"

# 2026-09-16 third-round trial finding: commands/tests/ accepted only the *.test.py suffix,
# so the six test_pr_review_*.py unittest exams were invisible and pr-review.md went unguarded
# twice (2026-09-11, 2026-09-15). These files are unittest, so they run per file, not as a suite.
cmdpy_root="$TMP/command-pytest/.claude"
mkdir -p "$cmdpy_root/commands/tests"
cmdpy_test="$cmdpy_root/commands/tests/test_cmdpy_contract.py"
printf '%s\n' '#!/usr/bin/env python3' 'import unittest' '' '# guards commands/cmdpy.md' >"$cmdpy_test"
printf '%s\n' '# cmdpy command' >"$cmdpy_root/commands/cmdpy.md"
cmdpy_test=$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$cmdpy_test")
run_case cmdpy "$cmdpy_root/commands/cmdpy.md" cmdpy-session "$TMP/state-cmdpy"
assert_rc 'security: pytest-named command test denies first edit with exit 0' cmdpy 0
assert_empty 'security: pytest-named command deny keeps stderr empty' cmdpy stderr
assert_deny_json 'security: pytest-named command test emits valid PreToolUse JSON per file' cmdpy "python3 $cmdpy_test"
check 'regression: commands/tests test_*.py is no longer silently dropped' "$(grep -Fq "$cmdpy_test" "$TMP/cmdpy.out" && printf 0 || printf 1)"

hardlink_root="$TMP/skill-hardlink/.claude"
hardlink_tests="$hardlink_root/skills/hard-skill/scripts/tests"
mkdir -p "$hardlink_tests"
printf '%s\n' 'def test_hard():' '    assert True' >"$TMP/hard-source.py"
ln "$TMP/hard-source.py" "$hardlink_tests/test_hard.py"
printf '%s\n' '# hard skill' >"$hardlink_root/skills/hard-skill/SKILL.md"
"$HELPER" "$hardlink_root/skills/hard-skill/SKILL.md" >"$TMP/hardlink.out"
check 'security: hardlinked pytest file is rejected' "$(grep -Fq 'pytest tests/' "$TMP/hardlink.out" && printf 1 || printf 0)"

eval_link_root="$TMP/skill-eval-link/.claude"
mkdir -p "$eval_link_root/skills/eval-link-symlink/evals" "$eval_link_root/skills/eval-link-hard/evals"
printf '%s\n' 'version: 1' >"$TMP/eval-source.yaml"
ln -s "$TMP/eval-source.yaml" "$eval_link_root/skills/eval-link-symlink/evals/eval.yaml"
ln "$TMP/eval-source.yaml" "$eval_link_root/skills/eval-link-hard/evals/eval.yaml"
printf '%s\n' '# eval link skill' >"$eval_link_root/skills/eval-link-symlink/SKILL.md"
printf '%s\n' '# eval hard skill' >"$eval_link_root/skills/eval-link-hard/SKILL.md"
"$HELPER" "$eval_link_root/skills/eval-link-symlink/SKILL.md" >"$TMP/eval-symlink.out"
"$HELPER" "$eval_link_root/skills/eval-link-hard/SKILL.md" >"$TMP/eval-hardlink.out"
check 'security: symlinked eval.yaml is rejected' "$(grep -Fq 'skill-up run' "$TMP/eval-symlink.out" && printf 1 || printf 0)"
check 'security: hardlinked eval.yaml is rejected' "$(grep -Fq 'skill-up run' "$TMP/eval-hardlink.out" && printf 1 || printf 0)"

eval_root="$TMP/skill-eval/.claude"
eval_dir="$eval_root/skills/eval-skill/evals"
mkdir -p "$eval_dir"
printf '%s\n' 'version: 1' >"$eval_dir/eval.yaml"
printf '%s\n' '# eval skill' >"$eval_root/skills/eval-skill/SKILL.md"
eval_skill_dir=$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$eval_root/skills/eval-skill")
run_case eval-skill "$eval_root/skills/eval-skill/SKILL.md" eval-session "$TMP/state-eval"
assert_rc 'boundary: skill eval.yaml denies first edit with exit 0' eval-skill 0
assert_empty 'boundary: skill eval.yaml deny keeps stderr empty' eval-skill stderr
assert_deny_json 'boundary: skill eval.yaml emits valid PreToolUse JSON with skill-up command' eval-skill 'skill-up run evals/eval.yaml --output-dir ~/Desktop/projects/.claude/trials/skill-up-cli/eval-runs'
assert_contains 'boundary: skill eval.yaml command cd into skill dir' eval-skill stdout "cd $eval_skill_dir"

disabled_state="$TMP/state-disabled"
mkdir -p "$disabled_state"
: >"$disabled_state/contract-test-gate.disabled"
run_case disabled "$marked_root/commands/marked.md" disabled-session "$disabled_state"
assert_rc 'lifecycle: disabled sentinel allows edit' disabled 0
assert_empty 'lifecycle: disabled sentinel keeps stdout empty' disabled stdout
assert_contains 'lifecycle: disabled sentinel leaves recovery trace' disabled stderr 'disabled'

run_case self-test "$HOOK" self-test-session "$TMP/state-self-test"
assert_rc 'lifecycle: gate test target does not recurse' self-test 0
assert_empty 'lifecycle: gate test target remains silent' self-test stdout

run_case helper-failure "$marked_root/commands/marked.md" helper-failure-session "$TMP/state-helper-failure" "$TMP/missing-helper"
assert_rc 'failure mode: missing helper fails open' helper-failure 0
assert_empty 'failure mode: missing helper emits no hook JSON' helper-failure stdout
assert_contains 'failure mode: missing helper reports one-line fallback' helper-failure stderr 'helper failed; allowing edit'
helper_error_lines=$(wc -l <"$TMP/helper-failure.err" | tr -d ' ')
check 'failure mode: missing helper stderr has exactly one line' "$([ "$helper_error_lines" = 1 ] && printf 0 || printf 1)" "actual lines=$helper_error_lines"

external_root="$TMP/external-marker/.claude"
mkdir -p "$external_root/commands"
external_target="$external_root/commands/external.md"
external_test="$TMP/outside/external-contract.test.sh"
mkdir -p "$(dirname "$external_test")"
printf '%s\n' '#!/usr/bin/env bash' 'exit 0' >"$external_test"
chmod +x "$external_test"
printf '%s\n' "<!-- 本檔在契約測試底下：bash $external_test -->" '# external' >"$external_target"
run_case external-marker "$external_target" external-marker-session "$TMP/state-external-marker"
assert_rc 'security: external marker is rejected' external-marker 0
assert_empty 'security: external marker does not emit a command' external-marker stdout

identity_root="$TMP/skill-identity/.claude"
mkdir -p "$identity_root/skills/research-before-answer/scripts/tests" "$identity_root/skills/other/scripts/tests" "$identity_root/commands/tests"
identity_target="$identity_root/skills/research-before-answer/SKILL.md"
identity_cross="$identity_root/commands/tests/cross-skill-contract.test.sh"
identity_test="$identity_root/skills/research-before-answer/scripts/tests/identity-contract.test.sh"
unrelated_test_a="$identity_root/skills/other/scripts/tests/unrelated-a-contract.test.sh"
unrelated_test_b="$identity_root/skills/other/scripts/tests/unrelated-b-contract.test.sh"
printf '%s\n' '#!/usr/bin/env bash' 'exit 0' >"$identity_test"
printf '%s\n' '#!/usr/bin/env bash' 'skills/research-before-answer/SKILL.md' >"$identity_cross"
printf '%s\n' '#!/usr/bin/env bash' 'SKILL.md' >"$unrelated_test_a"
printf '%s\n' '#!/usr/bin/env bash' 'SKILL.md' >"$unrelated_test_b"
chmod +x "$identity_test" "$identity_cross" "$unrelated_test_a" "$unrelated_test_b"
printf '%s\n' '# research-before-answer' >"$identity_target"
"$HELPER" "$identity_target" >"$TMP/skill-identity.out"
check 'security: skill discovery keeps the owning skill test' "$(grep -Fq "$identity_test" "$TMP/skill-identity.out" && printf 0 || printf 1)"
check 'security: skill discovery keeps exact cross-file references' "$(grep -Fq "$identity_cross" "$TMP/skill-identity.out" && printf 0 || printf 1)"
check 'security: skill discovery drops basename-only references' "$(if grep -Fq "$unrelated_test_a" "$TMP/skill-identity.out" || grep -Fq "$unrelated_test_b" "$TMP/skill-identity.out"; then printf 1; else printf 0; fi)"

relative_root="$TMP/relative-marker/.claude"
mkdir -p "$relative_root/commands/tests" "$relative_root/commands"
relative_target="$relative_root/commands/relative.md"
relative_test="$relative_root/commands/tests/relative-contract.test.sh"
printf '%s\n' '#!/usr/bin/env bash' 'exit 0' >"$relative_test"
chmod +x "$relative_test"
printf '%s\n' '<!-- 本檔在契約測試底下：bash commands/tests/relative-contract.test.sh -->' '# relative' >"$relative_target"
( cd "$TMP" && "$HELPER" "$relative_target" ) >"$TMP/relative-marker.out"
check 'security: relative marker resolves from target root' "$(grep -Fq "$relative_test" "$TMP/relative-marker.out" && printf 0 || printf 1)"

typed_root="$TMP/typed-marker/.claude"
mkdir -p "$typed_root/commands/tests" "$typed_root/commands"
typed_target="$typed_root/commands/typed.md"
typed_python="$typed_root/commands/tests/typed-contract.test.py"
typed_mjs="$typed_root/commands/tests/typed-contract.test.mjs"
typed_js="$typed_root/commands/tests/typed-contract.test.js"
printf '%s\n' 'print("typed")' >"$typed_python"
printf '%s\n' 'test("typed", () => {})' >"$typed_mjs"
printf '%s\n' 'test("typed", () => {})' >"$typed_js"
printf '%s\n' '<!-- 本檔在契約測試底下：python3 commands/tests/typed-contract.test.py && node --test commands/tests/typed-contract.test.mjs -->' '<!-- 本檔在契約測試底下：node commands/tests/typed-contract.test.js -->' '# typed' >"$typed_target"
"$HELPER" "$typed_target" >"$TMP/typed-marker.out"
check 'security: python marker is discovered' "$(grep -Fq "$typed_python" "$TMP/typed-marker.out" && printf 0 || printf 1)"
check 'security: node test marker is discovered' "$(grep -Fq "$typed_mjs" "$TMP/typed-marker.out" && grep -Fq 'node --test' "$TMP/typed-marker.out" && printf 0 || printf 1)"
check 'security: node javascript marker is discovered' "$(grep -Fq "$typed_js" "$TMP/typed-marker.out" && grep -Fq 'node ' "$TMP/typed-marker.out" && printf 0 || printf 1)"

# Regression (Medium #7): HEADER_LINES > 12 (up to 25) and python3 test_*.py in header markers.
deep_root="$TMP/deep-header/.claude"
mkdir -p "$deep_root/commands/tests" "$deep_root/skills/deep-skill/scripts/tests"
deep_sh="$deep_root/commands/tests/deep-first.test.sh"
deep_py="$deep_root/commands/tests/test_deep_header_contract.py"
deep_non_test="$deep_root/commands/tests/helper.py"
deep_skill_py="$deep_root/skills/deep-skill/scripts/tests/test_skill_pytest_only.py"
deep_skill="$deep_root/skills/deep-skill/SKILL.md"
printf '%s\n' '#!/usr/bin/env bash' 'exit 0' >"$deep_sh"
printf '%s\n' '#!/usr/bin/env python3' 'print("ok")' >"$deep_py"
printf '%s\n' 'VALUE = 1' >"$deep_non_test"
printf '%s\n' 'def test_ok(): pass' >"$deep_skill_py"
chmod +x "$deep_sh"
{
  printf '%s\n' '---' 'name: deep-skill' '---'
  for i in $(seq 1 13); do printf '<!-- filler line %s -->\n' "$i"; done
  printf '<!-- 本檔在契約測試底下：bash commands/tests/deep-first.test.sh && python3 commands/tests/test_deep_header_contract.py -->\n'
  printf '<!-- 本檔在契約測試底下：python3 commands/tests/helper.py -->\n'
  printf '<!-- 本檔在契約測試底下：python3 skills/deep-skill/scripts/tests/test_skill_pytest_only.py -->\n'
  printf '%s\n' '# deep skill'
} >"$deep_skill"
deep_py_real=$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$deep_py")
deep_sh_real=$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$deep_sh")
"$HELPER" "$deep_skill" >"$TMP/deep-header.out"
check 'regression: header marker after line 12 (line 17) is discovered' "$(grep -Fq "$deep_sh_real" "$TMP/deep-header.out" && printf 0 || printf 1)"
check 'regression: python3 test_*.py header marker in && chain is discovered' "$(grep -Fq "python3 $deep_py_real" "$TMP/deep-header.out" && printf 0 || printf 1)"
check 'reverse: non-test python helper.py header marker is rejected' "$(if grep -Fq 'helper.py' "$TMP/deep-header.out"; then printf 1; else printf 0; fi)"
check 'reverse: skills/*/scripts/tests/test_*.py header marker is not listed per file' "$(if grep -Fq 'test_skill_pytest_only.py' "$TMP/deep-header.out"; then printf 1; else printf 0; fi)"
run_case deep-header "$deep_skill" deep-header-session "$TMP/state-deep-header"
assert_rc 'regression: deep-header skill denies first edit with exit 0' deep-header 0
assert_empty 'regression: deep-header deny keeps stderr empty' deep-header stderr
assert_deny_json 'regression: deep-header emits valid PreToolUse JSON with test_*.py command' deep-header "python3 $deep_py_real"

if python3 - "$ROOT/settings.json" <<'PY'
import json
import sys
from pathlib import Path

settings = json.loads(Path(sys.argv[1]).read_text())
commands = [
  hook.get("command", "")
  for group in settings.get("hooks", {}).get("PreToolUse", [])
  for hook in group.get("hooks", [])
]
assert commands.count("~/.claude/hooks/contract-test-preflight-gate.sh") == 1
print("PASS settings.json wires contract-test-preflight-gate once")
PY
then
  PASS=$((PASS + 1))
else
  printf 'FAIL settings.json wires contract-test-preflight-gate once\n'
  FAIL=$((FAIL + 1))
fi

printf '%s\n' '----'
printf 'pass=%s fail=%s\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
