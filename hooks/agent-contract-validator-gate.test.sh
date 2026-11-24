#!/usr/bin/env bash
set -u

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
GATE="$ROOT/hooks/agent-contract-validator-gate.sh"
PERMIT_HELPER="$ROOT/hooks/agent-contract-gate-permit.sh"
# fixture 改 HOME，不應改變測試使用的已下載相依與編譯快取。
export GOMODCACHE="${GOMODCACHE:-$(go env GOMODCACHE)}"
export GOCACHE="${GOCACHE:-$(go env GOCACHE)}"
TMP_ROOT=$(mktemp -d)
trap 'rm -r "$TMP_ROOT"' EXIT
PASS=0
FAIL=0

check() {
  local name=$1
  local condition=$2
  if [ "$condition" -eq 0 ]; then
    PASS=$((PASS + 1))
    printf 'PASS: %s\n' "$name"
  else
    FAIL=$((FAIL + 1))
    printf 'FAIL: %s\n' "$name"
  fi
}

new_fixture() {
  FIXTURE=$(mktemp -d "$TMP_ROOT/fixture.XXXXXX")
  HOME_ROOT="$FIXTURE/home"
  REPO="$FIXTURE/repo"
  GLOBAL_ROOT_OVERRIDE="$REPO"
  SENTINEL_OVERRIDE=
  PERMIT_OVERRIDE=
  SESSION_OVERRIDE=
  LOCK_ROOT_OVERRIDE=
  mkdir -p "$HOME_ROOT" "$REPO/agents" "$REPO/.claude/agents" "$REPO/.claude/skills/demo"
  printf '%s\n' '{}' > "$HOME_ROOT/.claude.json"
  printf '%s\n' '{"permissions":{"allow":["Agent(removed)"]},"hooks":{"PreToolUse":[{"matcher":"Bash","hooks":[{"type":"command","command":"~/.claude/hooks/agent-contract-validator-gate.sh"}]}]}}' > "$REPO/settings.json"
  printf '%s\n' '---' 'name: good' 'tools: [Read]' '---' > "$REPO/agents/good.md"
  printf '%s\n' '---' 'name: removed' 'tools: [Read]' '---' > "$REPO/agents/removed.md"
  printf '%s\n' '---' 'name: local-helper' 'tools: [Read]' '---' > "$REPO/.claude/agents/local-helper.md"
  printf '%s\n' '---' 'name: demo' '---' 'subagent_type: local-helper' > "$REPO/.claude/skills/demo/SKILL.md"
  printf '%s\n' 'initial' > "$REPO/README.md"
  git -C "$REPO" init -q
  git -C "$REPO" config user.email test@example.com
  git -C "$REPO" config user.name test
  git -C "$REPO" add .
  git -C "$REPO" commit -qm initial
}

new_global_worktree_fixture() {
  FIXTURE=$(mktemp -d "$TMP_ROOT/global-worktree.XXXXXX")
  HOME_ROOT="$FIXTURE/home"
  GLOBAL_ROOT_OVERRIDE="$FIXTURE/global"
  REPO="$FIXTURE/worktree"
  SENTINEL_OVERRIDE=
  PERMIT_OVERRIDE=
  SESSION_OVERRIDE=
  LOCK_ROOT_OVERRIDE=
  mkdir -p "$HOME_ROOT" "$GLOBAL_ROOT_OVERRIDE/agents"
  printf '%s\n' '{}' > "$HOME_ROOT/.claude.json"
  printf '%s\n' '{"hooks":{"PreToolUse":[{"matcher":"Bash","hooks":[{"type":"command","command":"~/.claude/hooks/agent-contract-validator-gate.sh"}]}]}}' > "$GLOBAL_ROOT_OVERRIDE/settings.json"
  printf '%s\n' '---' 'name: good' 'tools: [Read]' '---' > "$GLOBAL_ROOT_OVERRIDE/agents/good.md"
  printf '%s\n' 'initial' > "$GLOBAL_ROOT_OVERRIDE/README.md"
  git -C "$GLOBAL_ROOT_OVERRIDE" init -q
  git -C "$GLOBAL_ROOT_OVERRIDE" config user.email test@example.com
  git -C "$GLOBAL_ROOT_OVERRIDE" config user.name test
  git -C "$GLOBAL_ROOT_OVERRIDE" add .
  git -C "$GLOBAL_ROOT_OVERRIDE" commit -qm initial
  git -C "$GLOBAL_ROOT_OVERRIDE" worktree add -q "$REPO" -b fixture-worktree
}

run_gate() {
  local cwd=$1
  local command=$2
  local output=$3
  # Point the sentinel, permit, audit, and lock-root paths inside the fixture.
  # Without this every case would read and write the real ~/.claude/hooks state,
  # and the evaluator-integrity check would look at the real gate's dirtiness
  # instead of the fixture's.
  jq -n --arg cwd "$cwd" --arg command "$command" --arg session "${SESSION_OVERRIDE:-}" \
    '{tool_name:"Bash",cwd:$cwd,tool_input:{command:$command}} + (if $session == "" then {} else {session_id:$session} end)' |
    HOME="$HOME_ROOT" CLAUDE_CONFIG_DIR="$GLOBAL_ROOT_OVERRIDE" \
    AGENT_CONTRACT_GATE_SENTINEL="${SENTINEL_OVERRIDE:-$FIXTURE/no-such-sentinel}" \
    AGENT_CONTRACT_GATE_PERMIT="${PERMIT_OVERRIDE:-$FIXTURE/permit}" \
    AGENT_CONTRACT_GATE_AUDIT="$FIXTURE/audit.jsonl" \
    AGENT_CONTRACT_GATE_LOCK_ROOT="${LOCK_ROOT_OVERRIDE:-$REPO}" \
    "$GATE" > "$output" 2>&1
  GATE_STATUS=$?
}

assert_allow() {
  local name=$1
  local output=$2
  if [ "$GATE_STATUS" -eq 0 ] && [ ! -s "$output" ]; then
    check "$name" 0
  else
    check "$name" 1
  fi
}

assert_deny() {
  local name=$1
  local output=$2
  if [ "$GATE_STATUS" -eq 0 ] && node -e '
const fs = require("node:fs")
const data = JSON.parse(fs.readFileSync(process.argv[1], "utf8"))
if (data.hookSpecificOutput?.permissionDecision !== "deny") process.exit(1)
' "$output"; then
    check "$name" 0
  else
    check "$name" 1
  fi
}

assert_validator_diagnostic() {
  local name=$1
  local output=$2
  local code=$3
  if node -e '
const fs = require("node:fs")
const data = JSON.parse(fs.readFileSync(process.argv[1], "utf8"))
const result = JSON.parse(data.hookSpecificOutput.permissionDecisionReason)
const diagnostic = result.diagnostics.find(item => item.code === process.argv[2])
if (!diagnostic || diagnostic.status !== "error" || !diagnostic.path || !diagnostic.path.includes("/repo/") || !diagnostic.line || !diagnostic.column) process.exit(1)
' "$output" "$code"; then
    check "$name" 0
  else
    check "$name" 1
  fi
}

assert_denial_reason() {
  local name=$1
  local output=$2
  local needle=$3
  if [ "$GATE_STATUS" -eq 0 ] && node -e '
const fs = require("node:fs")
const data = JSON.parse(fs.readFileSync(process.argv[1], "utf8"))
const reason = data.hookSpecificOutput?.permissionDecisionReason ?? ""
if (data.hookSpecificOutput?.permissionDecision !== "deny" || !reason.includes(process.argv[2])) process.exit(1)
' "$output" "$needle"; then
    check "$name" 0
  else
    check "$name" 1
  fi
}

new_fixture
INDEX_BEFORE=$(git -C "$REPO" write-tree)
for NON_COMMIT_COMMAND in 'G=git; "$G" status --short' 'repo="$HOME/work"; git -C "$repo" apply --check patch.diff' 'formatter=prettier; "$formatter" --check .' 'git status "unterminated' 'G=git; "$G" COMMIT -m uppercase'; do
  OUTPUT="$FIXTURE/non-commit.json"
  run_gate "$REPO" "$NON_COMMIT_COMMAND" "$OUTPUT"
  assert_allow "literal command without lowercase commit skips inspection: $NON_COMMIT_COMMAND" "$OUTPUT"
done
[ ! -e "$FIXTURE/audit.jsonl" ] && [ ! -e "$FIXTURE/permit" ] && [ "$INDEX_BEFORE" = "$(git -C "$REPO" write-tree)" ]
check 'non-commit payloads leave audit, permit, and index unchanged' $?
OUTPUT="$FIXTURE/commit-substring.json"
run_gate "$REPO" 'G=git; "$G" status --short # recommit' "$OUTPUT"
assert_denial_reason 'commit substring anywhere still reaches parser' "$OUTPUT" 'dynamic Git executable'

new_fixture
printf '%s\n' 'extra' >> "$REPO/agents/good.md"
git -C "$REPO" add agents/good.md
OUTPUT="$FIXTURE/good.json"
run_gate "$REPO" "git commit -m 'valid contract'" "$OUTPUT"
assert_allow 'known-good staged contract allows commit' "$OUTPUT"
if git -C "$REPO" commit -qm 'valid contract'; then
  check 'known-good commit completes' 0
else
  check 'known-good commit completes' 1
fi

new_fixture
printf '%s\n' '---' 'name: demo' '---' 'subagent_type: missing-agent' > "$REPO/.claude/skills/demo/SKILL.md"
git -C "$REPO" add .claude/skills/demo/SKILL.md
OUTPUT="$FIXTURE/dynamic-git.json"
run_gate "$REPO" 'G=git; "$G" commit -m dynamic' "$OUTPUT"
assert_denial_reason 'dynamic Git executable commit fails closed' "$OUTPUT" 'dynamic Git executable'

new_fixture
printf '%s\n' '---' 'name: demo' '---' 'subagent_type: missing-agent' > "$REPO/.claude/skills/demo/SKILL.md"
git -C "$REPO" add .claude/skills/demo/SKILL.md
OUTPUT="$FIXTURE/plain-text-git.json"
run_gate "$REPO" "printf %s 'G=git; \"\$G\" commit -m text'" "$OUTPUT"
assert_allow 'plain text mentioning dynamic Git commit is ignored' "$OUTPUT"

new_global_worktree_fixture
printf '%s\n' '---' 'name: good' 'model: unsupported' '---' > "$REPO/agents/good.md"
git -C "$REPO" add agents/good.md
OUTPUT="$FIXTURE/global-worktree.json"
run_gate "$REPO" "git commit -m 'bad worktree contract'" "$OUTPUT"
assert_deny 'global repository worktree fires the gate' "$OUTPUT"

new_fixture
printf '%s\n' '---' 'name: demo' '---' 'subagent_type: missing-agent' > "$REPO/.claude/skills/demo/SKILL.md"
git -C "$REPO" add .claude/skills/demo/SKILL.md
OUTPUT="$FIXTURE/bad.json"
run_gate "$REPO" "git commit -m 'bad contract'" "$OUTPUT"
assert_deny 'known-bad staged contract denies commit' "$OUTPUT"
assert_validator_diagnostic 'known-bad keeps validator diagnostic' "$OUTPUT" UNKNOWN_AGENT_REFERENCE

new_fixture
printf '%s\n' '---' 'name: demo' '---' 'subagent_type: missing-agent' > "$REPO/.claude/skills/demo/SKILL.md"
printf '%s\n' 'unrelated' >> "$REPO/README.md"
git -C "$REPO" add README.md
OUTPUT="$FIXTURE/unstaged.json"
run_gate "$REPO" "git commit -m 'unrelated change'" "$OUTPUT"
assert_allow 'unstaged contract is excluded from staged validation' "$OUTPUT"

new_fixture
mkdir -p "$REPO/plugins/cache"
printf '%s\n' 'plugin agent content' > "$REPO/plugins/cache/agent.md"
git -C "$REPO" add plugins/cache/agent.md
OUTPUT="$FIXTURE/plugin.json"
run_gate "$REPO" "git commit -m 'plugin update'" "$OUTPUT"
assert_allow 'plugin surface remains excluded' "$OUTPUT"

new_fixture
GLOBAL_ROOT_OVERRIDE="$FIXTURE/global"
mkdir -p "$GLOBAL_ROOT_OVERRIDE"
printf '%s\n' '{}' > "$GLOBAL_ROOT_OVERRIDE/settings.json"
printf '%s\n' '{}' > "$REPO/settings.json"
git -C "$REPO" add settings.json
git -C "$REPO" commit -qm projectbaseline
printf '%s\n' '---' 'name: invalid-product-agent' 'model: unsupported' '---' > "$REPO/agents/product.md"
git -C "$REPO" add agents/product.md
OUTPUT="$FIXTURE/project-root-agent.json"
run_gate "$REPO" "git commit -m 'product agent'" "$OUTPUT"
assert_allow 'project root agents remain outside global contract surface' "$OUTPUT"

new_fixture
git -C "$REPO" mv agents/good.md agents/renamed.md
git -C "$REPO" add -A
OUTPUT="$FIXTURE/rename.json"
run_gate "$REPO" "git commit -m 'rename agent'" "$OUTPUT"
assert_deny 'staged rename fires the gate' "$OUTPUT"
assert_validator_diagnostic 'staged rename reports filename location' "$OUTPUT" AGENT_FILENAME_MISMATCH

new_fixture
git -C "$REPO" rm -q agents/removed.md
OUTPUT="$FIXTURE/delete.json"
run_gate "$REPO" "git commit -m 'delete agent'" "$OUTPUT"
assert_deny 'staged delete fires the gate' "$OUTPUT"
assert_validator_diagnostic 'staged delete reports remaining reference' "$OUTPUT" UNKNOWN_AGENT_REFERENCE

new_fixture
printf '%s\n' '---' 'name: demo' '---' 'subagent_type: missing-agent' > "$REPO/.claude/skills/demo/SKILL.md"
OUTPUT="$FIXTURE/one-liner.json"
run_gate "$REPO" "git add .claude/skills/demo/SKILL.md && git commit -m 'one liner'" "$OUTPUT"
if [ "$GATE_STATUS" -eq 0 ] && node -e '
const fs = require("node:fs")
const data = JSON.parse(fs.readFileSync(process.argv[1], "utf8"))
const reason = data.hookSpecificOutput?.permissionDecisionReason ?? ""
if (data.hookSpecificOutput?.permissionDecision !== "deny" || !reason.includes("post-add")) process.exit(1)
' "$OUTPUT"; then
  check 'one-liner add and commit fails closed' 0
else
  check 'one-liner add and commit fails closed' 1
fi

new_fixture
printf '%s\n' '---' 'name: demo' '---' 'subagent_type: missing-agent' > "$REPO/.claude/skills/demo/SKILL.md"
OUTPUT="$FIXTURE/git-stage-one-liner.json"
run_gate "$REPO" "git stage .claude/skills/demo/SKILL.md && git commit -m 'one liner'" "$OUTPUT"
if [ "$GATE_STATUS" -eq 0 ] && node -e '
const fs = require("node:fs")
const data = JSON.parse(fs.readFileSync(process.argv[1], "utf8"))
const reason = data.hookSpecificOutput?.permissionDecisionReason ?? ""
if (data.hookSpecificOutput?.permissionDecision !== "deny" || !reason.includes("post-add")) process.exit(1)
' "$OUTPUT"; then
  check 'git stage one-liner fails closed' 0
else
  check 'git stage one-liner fails closed' 1
fi

new_fixture
printf '%s\n' '---' 'name: demo' '---' 'subagent_type: missing-agent' > "$REPO/.claude/skills/demo/SKILL.md"
OUTPUT="$FIXTURE/git-c-one-liner.json"
run_gate / "git -C $REPO add .claude/skills/demo/SKILL.md && git -C $REPO commit -m 'one liner'" "$OUTPUT"
if [ "$GATE_STATUS" -eq 0 ] && node -e '
const fs = require("node:fs")
const data = JSON.parse(fs.readFileSync(process.argv[1], "utf8"))
const reason = data.hookSpecificOutput?.permissionDecisionReason ?? ""
if (data.hookSpecificOutput?.permissionDecision !== "deny" || (!reason.includes("post-add") && !reason.includes("multiple git -C"))) process.exit(1)
' "$OUTPUT"; then
  check 'git -C one-liner fails closed' 0
else
  check 'git -C one-liner fails closed' 1
fi

new_fixture
printf '%s\n' '---' 'name: demo' '---' 'subagent_type: missing-agent' > "$REPO/.claude/skills/demo/SKILL.md"
OUTPUT="$FIXTURE/nested-shell.json"
run_gate "$REPO" "bash -c 'git commit -m nested'" "$OUTPUT"
if [ "$GATE_STATUS" -eq 0 ] && node -e '
const fs = require("node:fs")
const data = JSON.parse(fs.readFileSync(process.argv[1], "utf8"))
const reason = data.hookSpecificOutput?.permissionDecisionReason ?? ""
if (data.hookSpecificOutput?.permissionDecision !== "deny" || !reason.includes("nested shell")) process.exit(1)
' "$OUTPUT"; then
  check 'nested shell commit fails closed' 0
else
  check 'nested shell commit fails closed' 1
fi

new_fixture
printf '%s\n' '---' 'name: demo' '---' 'subagent_type: missing-agent' > "$REPO/.claude/skills/demo/SKILL.md"
OUTPUT="$FIXTURE/multiple-cd.json"
run_gate / "cd / && cd $REPO && git commit -m multiple" "$OUTPUT"
if [ "$GATE_STATUS" -eq 0 ] && node -e '
const fs = require("node:fs")
const data = JSON.parse(fs.readFileSync(process.argv[1], "utf8"))
const reason = data.hookSpecificOutput?.permissionDecisionReason ?? ""
if (data.hookSpecificOutput?.permissionDecision !== "deny" || !reason.includes("multiple cd") || !reason.includes("entire command was not executed")) process.exit(1)
' "$OUTPUT"; then
  check 'multiple cd commit fails closed' 0
else
  check 'multiple cd commit fails closed' 1
fi

new_fixture
printf '%s\n' '---' 'name: demo' '---' 'subagent_type: missing-agent' > "$REPO/.claude/skills/demo/SKILL.md"
OUTPUT="$FIXTURE/git-selector.json"
run_gate "$REPO" "GIT_DIR=$REPO/.git git commit -m selector" "$OUTPUT"
if [ "$GATE_STATUS" -eq 0 ] && node -e '
const fs = require("node:fs")
const data = JSON.parse(fs.readFileSync(process.argv[1], "utf8"))
const reason = data.hookSpecificOutput?.permissionDecisionReason ?? ""
if (data.hookSpecificOutput?.permissionDecision !== "deny" || !reason.includes("Git selector")) process.exit(1)
' "$OUTPUT"; then
  check 'command-local Git selector fails closed' 0
else
  check 'command-local Git selector fails closed' 1
fi

new_fixture
printf '%s\n' '---' 'name: demo' '---' 'subagent_type: missing-agent' > "$REPO/.claude/skills/demo/SKILL.md"
OUTPUT="$FIXTURE/pathspec.json"
run_gate "$REPO" "git commit -- .claude/skills/demo/SKILL.md" "$OUTPUT"
if [ "$GATE_STATUS" -eq 0 ] && node -e '
const fs = require("node:fs")
const data = JSON.parse(fs.readFileSync(process.argv[1], "utf8"))
const reason = data.hookSpecificOutput?.permissionDecisionReason ?? ""
if (data.hookSpecificOutput?.permissionDecision !== "deny" || !reason.includes("post-add")) process.exit(1)
' "$OUTPUT"; then
  check 'commit pathspec fails closed' 0
else
  check 'commit pathspec fails closed' 1
fi

new_fixture
printf '%s\n' '---' 'name: demo' '---' 'subagent_type: missing-agent' > "$REPO/.claude/skills/demo/SKILL.md"
OUTPUT="$FIXTURE/only-option.json"
run_gate "$REPO" "git commit --only .claude/skills/demo/SKILL.md" "$OUTPUT"
assert_validator_diagnostic 'commit --only with invalid controlled contract denies with validator diagnostic' "$OUTPUT" UNKNOWN_AGENT_REFERENCE

new_fixture
printf '%s\n' '---' 'name: demo' '---' 'subagent_type: missing-agent' > "$REPO/.claude/skills/demo/SKILL.md"
OUTPUT="$FIXTURE/interactive.json"
run_gate "$REPO" "git commit --interactive" "$OUTPUT"
assert_denial_reason 'commit interactive option fails closed' "$OUTPUT" post-add

new_fixture
printf '%s\n' '---' 'name: demo' '---' 'subagent_type: missing-agent' > "$REPO/.claude/skills/demo/SKILL.md"
OUTPUT="$FIXTURE/patch.json"
run_gate "$REPO" "git commit --patch" "$OUTPUT"
assert_denial_reason 'commit patch option fails closed' "$OUTPUT" post-add

new_fixture
printf '%s\n' '---' 'name: demo' '---' 'subagent_type: missing-agent' > "$REPO/.claude/skills/demo/SKILL.md"
OUTPUT="$FIXTURE/short-patch.json"
run_gate "$REPO" "git commit -p" "$OUTPUT"
assert_denial_reason 'commit short patch option fails closed' "$OUTPUT" post-add

new_fixture
printf '%s\n' '---' 'name: demo' '---' 'subagent_type: missing-agent' > "$REPO/.claude/skills/demo/SKILL.md"
git -C "$REPO" add .claude/skills/demo/SKILL.md
OUTPUT="$FIXTURE/quoted-git-c.json"
run_gate / "git -C \"$REPO\" commit -m 'quoted path'" "$OUTPUT"
if [ "$GATE_STATUS" -eq 0 ] && node -e '
const fs = require("node:fs")
const data = JSON.parse(fs.readFileSync(process.argv[1], "utf8"))
const reason = data.hookSpecificOutput?.permissionDecisionReason ?? ""
if (data.hookSpecificOutput?.permissionDecision !== "deny" || !reason.includes("quoted git -C")) process.exit(1)
' "$OUTPUT"; then
  check 'quoted git -C path fails closed' 0
else
  check 'quoted git -C path fails closed' 1
fi

new_fixture
printf '%s\n' '---' 'name: demo' '---' 'subagent_type: missing-agent' > "$REPO/.claude/skills/demo/SKILL.md"
git -C "$REPO" add .claude/skills/demo/SKILL.md
OUTPUT="$FIXTURE/quoted-cd.json"
run_gate / "cd \"$REPO\" && git commit -m 'quoted path'" "$OUTPUT"
if [ "$GATE_STATUS" -eq 0 ] && node -e '
const fs = require("node:fs")
const data = JSON.parse(fs.readFileSync(process.argv[1], "utf8"))
const reason = data.hookSpecificOutput?.permissionDecisionReason ?? ""
if (data.hookSpecificOutput?.permissionDecision !== "deny" || !reason.includes("quoted cd")) process.exit(1)
' "$OUTPUT"; then
  check 'quoted cd path fails closed' 0
else
  check 'quoted cd path fails closed' 1
fi

new_fixture
mkdir -p "$REPO/scripts"
# The locked file must already be in HEAD for this to be a *change*. Staging one
# that HEAD has never seen is the bootstrap case, which is allowed on purpose and
# is asserted separately below -- denying it is what left the gate uninstallable.
printf '%s\n' 'original validator' > "$REPO/scripts/agent-contract-validator.mjs"
git -C "$REPO" add scripts/agent-contract-validator.mjs
git -C "$REPO" commit -qm 'add validator'
printf '%s\n' 'changed validator' > "$REPO/scripts/agent-contract-validator.mjs"
git -C "$REPO" add scripts/agent-contract-validator.mjs
OUTPUT="$FIXTURE/locked.json"
run_gate "$REPO" "git commit -m 'change validator'" "$OUTPUT"
if [ "$GATE_STATUS" -eq 0 ] && node -e '
const fs = require("node:fs")
const data = JSON.parse(fs.readFileSync(process.argv[1], "utf8"))
const reason = data.hookSpecificOutput?.permissionDecisionReason ?? ""
if (data.hookSpecificOutput?.permissionDecision !== "deny" || !reason.includes("locked")) process.exit(1)
' "$OUTPUT"; then
  check 'locked validator surface is denied' 0
else
  check 'locked validator surface is denied' 1
fi

# Reverse assertions for the 2026-09-05 subshell blind spot. Every prefix class
# in this gate used to be (^|[;&|]) or (^|[;&|[:space:]]), so a `cd` or a `git`
# sitting right after `(` matched nothing:
#   - `(git commit ...)` was not recognised as a commit at all -> exit 0
#   - `(cd other && git commit ...)` kept the payload cwd, so the gate inspected
#     the wrong repository's index and found no locked path
# The second shape is the one that actually shipped three locked-file changes
# past this gate. cd-cwd-persistence-nudge.sh actively recommends `(cd x && y)`,
# so this is a shape the harness pushes agents toward, not an exotic one.
stage_locked_validator_change() {
  mkdir -p "$REPO/scripts"
  printf '%s\n' 'original validator' > "$REPO/scripts/agent-contract-validator.mjs"
  git -C "$REPO" add scripts/agent-contract-validator.mjs
  git -C "$REPO" commit -qm 'add validator'
  printf '%s\n' 'changed validator' > "$REPO/scripts/agent-contract-validator.mjs"
  git -C "$REPO" add scripts/agent-contract-validator.mjs
}

new_fixture
stage_locked_validator_change
OUTPUT="$FIXTURE/subshell-bare-commit.json"
run_gate "$REPO" "(git commit -m 'change validator')" "$OUTPUT"
if [ "$GATE_STATUS" -eq 0 ] && node -e '
const fs = require("node:fs")
const data = JSON.parse(fs.readFileSync(process.argv[1], "utf8"))
const reason = data.hookSpecificOutput?.permissionDecisionReason ?? ""
if (data.hookSpecificOutput?.permissionDecision !== "deny" || !reason.includes("locked")) process.exit(1)
' "$OUTPUT"; then
  check 'subshell-wrapped commit is still recognised as a commit' 0
else
  check 'subshell-wrapped commit is still recognised as a commit' 1
fi

new_fixture
stage_locked_validator_change
OUTPUT="$FIXTURE/subshell-cd.json"
run_gate "$REPO" "(cd $REPO && git commit -m 'change validator')" "$OUTPUT"
if [ "$GATE_STATUS" -eq 0 ] && node -e '
const fs = require("node:fs")
const data = JSON.parse(fs.readFileSync(process.argv[1], "utf8"))
const reason = data.hookSpecificOutput?.permissionDecisionReason ?? ""
if (data.hookSpecificOutput?.permissionDecision !== "deny" || !reason.includes("locked")) process.exit(1)
' "$OUTPUT"; then
  check 'subshell cd target is resolved' 0
else
  check 'subshell cd target is resolved' 1
fi

# The shipped failure: payload cwd is a *different* real repository, so resolving
# the repo succeeds and nothing errors -- the gate simply inspects an index that
# has no locked path and allows. Without parsing the subshell cd this is silent.
# A commit message that merely mentions a directory change must not read as a
# second cd. The counters moved to the scrubbed copy for this; before that, the
# message below tripped 'multiple cd targets' and the commit could not be made
# at all -- which is how this very fix first failed to commit.
new_fixture
stage_locked_validator_change
OUTPUT="$FIXTURE/cd-in-message.json"
run_gate "$REPO" "cd $REPO && git commit -m 'note: (cd elsewhere && git commit) used to slip past'" "$OUTPUT"
if [ "$GATE_STATUS" -eq 0 ] && node -e '
const fs = require("node:fs")
const data = JSON.parse(fs.readFileSync(process.argv[1], "utf8"))
const reason = data.hookSpecificOutput?.permissionDecisionReason ?? ""
if (data.hookSpecificOutput?.permissionDecision !== "deny") process.exit(1)
if (reason.includes("multiple cd")) process.exit(1)
if (!reason.includes("locked")) process.exit(1)
' "$OUTPUT"; then
  check 'cd mentioned only in the commit message is not a second cd' 0
else
  check 'cd mentioned only in the commit message is not a second cd' 1
fi

# The 2026-09-05 external review reproduced a silent allow the previous comment
# claimed was impossible: when a commit message mentions a path that EXISTS and
# is another git repo, target extraction on the raw command retargeted the gate
# to that repo, whose index has no locked path -- allow, no audit line. The
# earlier reasoning only covered the nonexistent-path case, which does deny.
# Both prefix shapes below reproduce it; the semicolon one predates the paren
# fix, so this is not purely a regression of that change.
for cd_mention_prefix in "(cd" "; cd"; do
  new_fixture
  stage_locked_validator_change
  MENTIONED_REPO="$FIXTURE/mentioned-repo"
  mkdir -p "$MENTIONED_REPO"
  git -C "$MENTIONED_REPO" init -q
  git -C "$MENTIONED_REPO" commit -q --allow-empty -m 'mentioned repo base'
  OUTPUT="$FIXTURE/existing-path-in-message.json"
  run_gate "$REPO" "git commit -m 'note: $cd_mention_prefix $MENTIONED_REPO was the old bug'" "$OUTPUT"
  if [ "$GATE_STATUS" -eq 0 ] && node -e '
const fs = require("node:fs")
const data = JSON.parse(fs.readFileSync(process.argv[1], "utf8"))
const reason = data.hookSpecificOutput?.permissionDecisionReason ?? ""
if (data.hookSpecificOutput?.permissionDecision !== "deny" || !reason.includes("locked")) process.exit(1)
' "$OUTPUT"; then
    check "existing repo path in message does not retarget the gate ($cd_mention_prefix)" 0
  else
    check "existing repo path in message does not retarget the gate ($cd_mention_prefix)" 1
  fi
done

new_fixture
stage_locked_validator_change
OTHER_REPO="$FIXTURE/other-repo"
mkdir -p "$OTHER_REPO"
git -C "$OTHER_REPO" init -q
git -C "$OTHER_REPO" commit -q --allow-empty -m 'other repo base'
OUTPUT="$FIXTURE/subshell-cd-cwd-mismatch.json"
run_gate "$OTHER_REPO" "(cd $REPO && git commit -m 'change validator')" "$OUTPUT"
if [ "$GATE_STATUS" -eq 0 ] && node -e '
const fs = require("node:fs")
const data = JSON.parse(fs.readFileSync(process.argv[1], "utf8"))
const reason = data.hookSpecificOutput?.permissionDecisionReason ?? ""
if (data.hookSpecificOutput?.permissionDecision !== "deny" || !reason.includes("locked")) process.exit(1)
' "$OUTPUT"; then
  check 'subshell cd overrides a different payload cwd repo' 0
else
  check 'subshell cd overrides a different payload cwd repo' 1
fi

new_fixture
mkdir -p "$REPO/scripts"
printf '%s\n' 'stable validator placeholder' > "$REPO/scripts/agent-contract-validator.mjs"
git -C "$REPO" add scripts/agent-contract-validator.mjs
git -C "$REPO" commit -qm lockbaseline
printf '%s\n' 'modified validator placeholder' > "$REPO/scripts/agent-contract-validator.mjs"
printf '%s\n' '---' 'name: demo' '---' 'subagent_type: local-helper' > "$REPO/.claude/skills/demo/SKILL.md"
git -C "$REPO" add .claude/skills/demo/SKILL.md
OUTPUT="$FIXTURE/unstaged-lock.json"
run_gate "$REPO" "git commit -m 'unstaged validator change'" "$OUTPUT"
assert_allow 'dirty locked file allows staged nonlocked controlled change' "$OUTPUT"

new_fixture
printf '%s\n' '{"permissions":{"allow":["Agent(removed)"]}}' > "$REPO/settings.json"
git -C "$REPO" add settings.json
OUTPUT="$FIXTURE/settings-registration.json"
run_gate "$REPO" "git commit -m 'remove gate registration'" "$OUTPUT"
if [ "$GATE_STATUS" -eq 0 ] && node -e '
const fs = require("node:fs")
const data = JSON.parse(fs.readFileSync(process.argv[1], "utf8"))
const reason = data.hookSpecificOutput?.permissionDecisionReason ?? ""
if (data.hookSpecificOutput?.permissionDecision !== "deny" || !reason.includes("registration")) process.exit(1)
' "$OUTPUT"; then
  check 'staged settings cannot remove gate registration' 0
else
  check 'staged settings cannot remove gate registration' 1
fi

new_fixture
printf '%s\n' '{"permissions":{"allow":["Agent(removed)"]},"hooks":{"PreToolUse":[{"matcher":"Bash","hooks":[{"type":"command","command":"echo agent-contract-validator-gate.sh"}]}]}}' > "$REPO/settings.json"
git -C "$REPO" add settings.json
OUTPUT="$FIXTURE/settings-lookalike.json"
run_gate "$REPO" "git commit -m 'fake gate registration'" "$OUTPUT"
if [ "$GATE_STATUS" -eq 0 ] && node -e '
const fs = require("node:fs")
const data = JSON.parse(fs.readFileSync(process.argv[1], "utf8"))
const reason = data.hookSpecificOutput?.permissionDecisionReason ?? ""
if (data.hookSpecificOutput?.permissionDecision !== "deny" || !reason.includes("registration")) process.exit(1)
' "$OUTPUT"; then
  check 'settings lookalike cannot satisfy gate registration' 0
else
  check 'settings lookalike cannot satisfy gate registration' 1
fi

new_fixture
OUTPUT="$FIXTURE/runtime.json"
run_gate "$REPO" "node workflows/runtime.mjs" "$OUTPUT"
assert_allow 'normal runtime command skips validator gate' "$OUTPUT"

# ---------------------------------------------------------------------------
# Fixture class four: the gate's own lifecycle. The three cases above check that
# inputs are classified correctly; these check that this gate can be installed,
# changed, and switched off. Those are different kinds of death -- the gate was
# uninstallable for a day while every input-classification case stayed green.
# ---------------------------------------------------------------------------

# The staged locked path is the permit helper, a locked file that is not part of
# the evaluator; validator changes are covered by the evaluator-integrity cases
# below, which need a real gate in HEAD to hand over to.
stage_locked_change() {
  mkdir -p "$REPO/hooks"
  printf '%s\n' 'original permit helper' > "$REPO/hooks/agent-contract-gate-permit.sh"
  git -C "$REPO" add hooks/agent-contract-gate-permit.sh
  git -C "$REPO" commit -qm 'add permit helper'
  printf '%s\n' 'changed permit helper' > "$REPO/hooks/agent-contract-gate-permit.sh"
  git -C "$REPO" add hooks/agent-contract-gate-permit.sh
}

# Issue through the real helper so its staged-entry text and session binding are what the
# gate reads; PERMIT_SESSION_OVERRIDE empty means the permit binds to no session.
issue_permit() {
  AGENT_CONTRACT_GATE_REPO="$REPO" AGENT_CONTRACT_GATE_PERMIT="$1" AGENT_CONTRACT_GATE_AUDIT="$FIXTURE/audit.jsonl" \
    CLAUDE_CODE_SESSION_ID="${PERMIT_SESSION_OVERRIDE:-}" "$PERMIT_HELPER" issue > "$FIXTURE/permit-issue.out" 2>&1
}

install_real_gate() {
  mkdir -p "$REPO/hooks" "$REPO/scripts"
  cp "${1:-$GATE}" "$REPO/hooks/agent-contract-validator-gate.sh"
  cp "$ROOT/scripts/agent-contract-validator.mjs" "$REPO/scripts/agent-contract-validator.mjs"
  mkdir -p "$REPO/scripts/agent-contract-command"
  cp "$ROOT/scripts/agent-contract-command/"{main.go,go.mod,go.sum} "$REPO/scripts/agent-contract-command/"
  git -C "$REPO" add hooks/agent-contract-validator-gate.sh scripts/agent-contract-validator.mjs scripts/agent-contract-command
  git -C "$REPO" commit -qm 'install gate'
}

# bootstrap -- the commit that introduces a locked file is not blocked by it
new_fixture
mkdir -p "$REPO/scripts"
printf '%s\n' 'brand new validator' > "$REPO/scripts/agent-contract-validator.mjs"
git -C "$REPO" add scripts/agent-contract-validator.mjs
OUTPUT="$FIXTURE/bootstrap.json"
run_gate "$REPO" "git commit -m 'introduce validator'" "$OUTPUT"
assert_allow 'bootstrap: introducing a locked file is allowed' "$OUTPUT"

# bootstrap -- but a new locked file cannot escort a change to an existing one.
# Found by probing the live gate: mark_path kept only the first locked path, so
# the new file's exemption cleared the check for the whole commit.
new_fixture
mkdir -p "$REPO/hooks"
printf '%s\n' 'original permit helper' > "$REPO/hooks/agent-contract-gate-permit.sh"
git -C "$REPO" add hooks/agent-contract-gate-permit.sh
git -C "$REPO" commit -qm 'add permit helper'
printf '%s\n' 'brand new routing gate' > "$REPO/hooks/T2-routing-gate.sh"
printf '%s\n' 'changed permit helper' > "$REPO/hooks/agent-contract-gate-permit.sh"
git -C "$REPO" add hooks/T2-routing-gate.sh hooks/agent-contract-gate-permit.sh
OUTPUT="$FIXTURE/bootstrap-escort.json"
run_gate "$REPO" "git commit -m 'add routing gate and change permit helper'" "$OUTPUT"
assert_denial_reason 'bootstrap: a new locked file cannot escort a change to an existing one' "$OUTPUT" 'needs a permit'

# update -- the YAGNI permit helper and its lifecycle test are locked surfaces,
# not editable evidence a routed agent can weaken before asking T2 for access.
new_fixture
mkdir -p "$REPO/hooks"
printf '%s\n' 'original YAGNI permit helper' > "$REPO/hooks/review-spec-yagni-permit.py"
printf '%s\n' 'original YAGNI permit lifecycle test' > "$REPO/hooks/review-spec-yagni-permit.test.py"
git -C "$REPO" add hooks/review-spec-yagni-permit.py hooks/review-spec-yagni-permit.test.py
git -C "$REPO" commit -qm 'add YAGNI permit surfaces'
printf '%s\n' 'changed YAGNI permit helper' > "$REPO/hooks/review-spec-yagni-permit.py"
printf '%s\n' 'changed YAGNI permit lifecycle test' > "$REPO/hooks/review-spec-yagni-permit.test.py"
git -C "$REPO" add hooks/review-spec-yagni-permit.py hooks/review-spec-yagni-permit.test.py
OUTPUT="$FIXTURE/yagni-helper-locked.json"
run_gate "$REPO" "git commit -m 'weaken YAGNI permit surfaces'" "$OUTPUT"
assert_denial_reason 'update: YAGNI permit helper and lifecycle test need a permit' "$OUTPUT" 'needs a permit'

# update -- the out-of-band permit must bind the YAGNI helper and its lifecycle
# test, not only classify them as locked after the commit command arrives.
new_fixture
PERMIT_OVERRIDE="$FIXTURE/permit"
mkdir -p "$REPO/hooks"
printf '%s\n' 'original YAGNI permit helper' > "$REPO/hooks/review-spec-yagni-permit.py"
printf '%s\n' 'original YAGNI permit lifecycle test' > "$REPO/hooks/review-spec-yagni-permit.test.py"
git -C "$REPO" add hooks/review-spec-yagni-permit.py hooks/review-spec-yagni-permit.test.py
git -C "$REPO" commit -qm 'add YAGNI permit surfaces'
printf '%s\n' 'changed YAGNI permit helper' > "$REPO/hooks/review-spec-yagni-permit.py"
printf '%s\n' 'changed YAGNI permit lifecycle test' > "$REPO/hooks/review-spec-yagni-permit.test.py"
git -C "$REPO" add hooks/review-spec-yagni-permit.py hooks/review-spec-yagni-permit.test.py
issue_permit "$PERMIT_OVERRIDE"
[ -f "$PERMIT_OVERRIDE" ] && grep -q 'review-spec-yagni-permit.py' "$FIXTURE/permit-issue.out"
check 'update: permit issuer binds staged YAGNI permit surfaces' $?
printf '%s\n' 'changed after permit issue' > "$REPO/hooks/review-spec-yagni-permit.py"
git -C "$REPO" add hooks/review-spec-yagni-permit.py
OUTPUT="$FIXTURE/yagni-helper-permit-drift.json"
run_gate "$REPO" "git commit -m 'change YAGNI permit surfaces'" "$OUTPUT"
assert_denial_reason 'update: changing a staged YAGNI permit surface invalidates its permit' "$OUTPUT" 'different locked content'

# update -- a valid permit bound to the staged locked content lets the change land
new_fixture
PERMIT_OVERRIDE="$FIXTURE/permit"
stage_locked_change
issue_permit "$PERMIT_OVERRIDE"
OUTPUT="$FIXTURE/permit-ok.json"
run_gate "$REPO" "git commit -m 'change permit helper'" "$OUTPUT"
assert_allow 'update: a permit for this staged locked content allows the change' "$OUTPUT"
[ ! -f "$PERMIT_OVERRIDE" ]
check 'update: the permit is consumed when the commit passes' $?

# update -- the permit is single use, so replaying it denies
OUTPUT="$FIXTURE/permit-replay.json"
run_gate "$REPO" "git commit -m 'change permit helper'" "$OUTPUT"
assert_deny 'update: a consumed permit cannot be replayed' "$OUTPUT"

# update -- a permit issued for other locked content does not carry over
new_fixture
PERMIT_OVERRIDE="$FIXTURE/permit"
stage_locked_change
printf '%s -\n%s\n' "$(( $(date -u '+%s') + 900 ))" "$(printf '100644 %s 0\thooks/agent-contract-gate-permit.sh' '0000000000000000000000000000000000000000')" > "$PERMIT_OVERRIDE"
OUTPUT="$FIXTURE/permit-wrong-content.json"
run_gate "$REPO" "git commit -m 'change permit helper'" "$OUTPUT"
assert_denial_reason 'update: a permit for different locked content is refused' "$OUTPUT" 'different locked content'

# update -- the permit binds to the locked entries, not the whole index, so
# another session staging an unrelated file between issue and commit does not
# void it. 18 permits were issued for 12 successful uses in the first week
# because the tree binding did.
new_fixture
PERMIT_OVERRIDE="$FIXTURE/permit"
stage_locked_change
issue_permit "$PERMIT_OVERRIDE"
printf '%s\n' 'staged by another session' >> "$REPO/README.md"
git -C "$REPO" add README.md
OUTPUT="$FIXTURE/permit-unrelated-staging.json"
run_gate "$REPO" "git commit -m 'change permit helper plus unrelated file'" "$OUTPUT"
assert_allow 'update: staging an unrelated file after issue keeps the permit valid' "$OUTPUT"

# update -- a failed validation must not burn the permit. Reverse assertion: the
# 0dcd175 gate consumed it before running the validator, so every validator
# failure cost the user a fresh issue.
new_fixture
PERMIT_OVERRIDE="$FIXTURE/permit"
stage_locked_change
printf '%s\n' '---' 'name: demo' '---' 'subagent_type: missing-agent' > "$REPO/.claude/skills/demo/SKILL.md"
git -C "$REPO" add .claude/skills/demo/SKILL.md
issue_permit "$PERMIT_OVERRIDE"
OUTPUT="$FIXTURE/permit-validator-fail.json"
run_gate "$REPO" "git commit -m 'locked change with invalid skill'" "$OUTPUT"
assert_validator_diagnostic 'update: a permitted commit still fails validation on invalid content' "$OUTPUT" UNKNOWN_AGENT_REFERENCE
[ -f "$PERMIT_OVERRIDE" ]
check 'update: a failed validation leaves the permit for the retry' $?
printf '%s\n' '---' 'name: demo' '---' 'subagent_type: local-helper' > "$REPO/.claude/skills/demo/SKILL.md"
git -C "$REPO" add .claude/skills/demo/SKILL.md
OUTPUT="$FIXTURE/permit-validator-retry.json"
run_gate "$REPO" "git commit -m 'locked change with fixed skill'" "$OUTPUT"
assert_allow 'update: the retry after fixing the content uses the kept permit' "$OUTPUT"

# update -- a permit issued in one session is refused from another. On
# 2026-08-22 a permit issued for session A was consumed 19 seconds later by a
# concurrent session B; the permit now records the issuing session.
new_fixture
PERMIT_OVERRIDE="$FIXTURE/permit"
stage_locked_change
PERMIT_SESSION_OVERRIDE='session-a' issue_permit "$PERMIT_OVERRIDE"
SESSION_OVERRIDE='session-b'
OUTPUT="$FIXTURE/permit-other-session.json"
run_gate "$REPO" "git commit -m 'change permit helper'" "$OUTPUT"
assert_denial_reason 'update: a permit issued in another session is refused' "$OUTPUT" 'another session'
SESSION_OVERRIDE='session-a'
OUTPUT="$FIXTURE/permit-same-session.json"
run_gate "$REPO" "git commit -m 'change permit helper'" "$OUTPUT"
assert_allow 'update: the issuing session can use its own permit' "$OUTPUT"

# update -- the helper refuses to issue when no locked path is staged, so a
# permit always binds to real locked content
new_fixture
PERMIT_OVERRIDE="$FIXTURE/permit"
printf '%s\n' 'note' >> "$REPO/README.md"
git -C "$REPO" add README.md
issue_permit "$PERMIT_OVERRIDE"
[ ! -f "$PERMIT_OVERRIDE" ] && grep -q 'no locked path is staged' "$FIXTURE/permit-issue.out"
check 'update: the helper refuses to issue without a staged locked path' $?

# evaluator integrity -- while the gate or validator is mid-edit, the verdict
# comes from the HEAD copy, so other sessions' locked commits are not frozen.
# In the first week 14 of 31 denials were this freeze, all inside windows where
# someone was editing the gate.
new_fixture
PERMIT_OVERRIDE="$FIXTURE/permit"
install_real_gate
printf '\n# mid-edit, not staged\n' >> "$REPO/hooks/agent-contract-validator-gate.sh"
printf '\n// staged validator change\n' >> "$REPO/scripts/agent-contract-validator.mjs"
git -C "$REPO" add scripts/agent-contract-validator.mjs
issue_permit "$PERMIT_OVERRIDE"
OUTPUT="$FIXTURE/evaluator-handover.json"
run_gate "$REPO" "git commit -m 'validator change while gate is mid-edit'" "$OUTPUT"
assert_allow 'evaluator integrity: a dirty gate hands the verdict to the HEAD copy' "$OUTPUT"
grep -q '"reason":"head-evaluator"' "$FIXTURE/audit.jsonl"
check 'evaluator integrity: the handover is audited' $?
[ ! -f "$PERMIT_OVERRIDE" ]
check 'evaluator integrity: the HEAD copy consumes the permit on pass' $?

# evaluator integrity -- the HEAD copy still enforces the permit
new_fixture
PERMIT_OVERRIDE="$FIXTURE/permit"
install_real_gate
printf '\n# mid-edit, not staged\n' >> "$REPO/hooks/agent-contract-validator-gate.sh"
printf '\n// staged validator change\n' >> "$REPO/scripts/agent-contract-validator.mjs"
git -C "$REPO" add scripts/agent-contract-validator.mjs
OUTPUT="$FIXTURE/evaluator-handover-no-permit.json"
run_gate "$REPO" "git commit -m 'validator change while gate is mid-edit'" "$OUTPUT"
assert_denial_reason 'evaluator integrity: the HEAD copy still requires a permit' "$OUTPUT" 'needs a permit'

# 舊 HEAD 接手的自身更新仍需人控 permit；非提交不必先交給舊判讀器。
new_fixture
git -C "$ROOT" show HEAD:hooks/agent-contract-validator-gate.sh > "$FIXTURE/head-gate.sh"
install_real_gate "$FIXTURE/head-gate.sh"
cp "$GATE" "$REPO/hooks/agent-contract-validator-gate.sh"
printf '\n# staged gate update\n' >> "$REPO/hooks/agent-contract-validator-gate.sh"
git -C "$REPO" add hooks/agent-contract-validator-gate.sh
OUTPUT="$FIXTURE/gate-update-readonly.json"
run_gate "$REPO" 'G=git; "$G" status --short' "$OUTPUT"
assert_allow 'dirty gate non-commit skips old HEAD parser' "$OUTPUT"
[ ! -e "$FIXTURE/audit.jsonl" ]
check 'non-commit early return happens before HEAD handover' $?
OUTPUT="$FIXTURE/gate-update-old-head.json"
run_gate "$REPO" "git commit -m 'gate update'" "$OUTPUT"
assert_denial_reason 'gate self-update retains old HEAD permit enforcement' "$OUTPUT" 'needs a permit'
command grep -q 'head-evaluator' "$FIXTURE/audit.jsonl"
check 'gate self-update reaches the old HEAD evaluator' $?

# update -- expiry is enforced. The instant is written as ISO-8601 and converted
# by the shell, so the fixture never carries a hand-computed epoch constant.
new_fixture
PERMIT_OVERRIDE="$FIXTURE/permit"
stage_locked_change
EXPIRED_ISO='2020-01-01T00:00:00Z'
EXPIRED_EPOCH=$(date -u -j -f '%Y-%m-%dT%H:%M:%SZ' "$EXPIRED_ISO" '+%s')
printf '%s -\n%s\n' "$EXPIRED_EPOCH" "$(git -C "$REPO" ls-files --stage -- hooks/agent-contract-gate-permit.sh)" > "$PERMIT_OVERRIDE"
OUTPUT="$FIXTURE/permit-expired.json"
run_gate "$REPO" "git commit -m 'change validator'" "$OUTPUT"
assert_denial_reason 'update: an expired permit is refused' "$OUTPUT" 'expired'

# update -- a malformed permit fails closed rather than passing
new_fixture
PERMIT_OVERRIDE="$FIXTURE/permit"
stage_locked_change
printf '%s\n' 'not-a-permit' > "$PERMIT_OVERRIDE"
OUTPUT="$FIXTURE/permit-malformed.json"
run_gate "$REPO" "git commit -m 'change validator'" "$OUTPUT"
assert_deny 'update: a malformed permit fails closed' "$OUTPUT"

# update -- a permit file from before the entry-text format (digest first) is read
# without crashing and is refused as malformed
new_fixture
PERMIT_OVERRIDE="$FIXTURE/permit"
stage_locked_change
printf '%s %s -\n' '0000000000000000000000000000000000000000000000000000000000000000' "$(( $(date -u '+%s') + 900 ))" > "$PERMIT_OVERRIDE"
OUTPUT="$FIXTURE/permit-legacy-digest.json"
run_gate "$REPO" "git commit -m 'change validator'" "$OUTPUT"
assert_denial_reason 'update: a legacy digest permit is refused as malformed' "$OUTPUT" 'malformed'

# update -- the permit records the staged entry text (mode, blob id, stage, path), not a digest
new_fixture
PERMIT_OVERRIDE="$FIXTURE/permit"
stage_locked_change
issue_permit "$PERMIT_OVERRIDE"
STAGED_BLOB=$(git -C "$REPO" rev-parse :hooks/agent-contract-gate-permit.sh)
[ "$(head -n 1 "$PERMIT_OVERRIDE" | awk '{print NF}')" = '2' ] && tail -n +2 "$PERMIT_OVERRIDE" | grep -q "^100644 $STAGED_BLOB 0.hooks/agent-contract-gate-permit.sh\$" && ! grep -Eq '[0-9a-f]{64}' "$PERMIT_OVERRIDE"
check 'update: the permit holds staged entry text and no digest' $?
AGENT_CONTRACT_GATE_REPO="$REPO" AGENT_CONTRACT_GATE_PERMIT="$PERMIT_OVERRIDE" "$PERMIT_HELPER" status > "$FIXTURE/permit-status.out" 2>&1
grep -q 'entries match: yes' "$FIXTURE/permit-status.out" && ! grep -qi 'digest' "$FIXTURE/permit-status.out"
check 'update: permit status reports entry match and names no digest' $?

# recovery -- the sentinel switches the gate off without editing settings.json
new_fixture
SENTINEL_OVERRIDE="$FIXTURE/disabled"
: > "$SENTINEL_OVERRIDE"
stage_locked_change
OUTPUT="$FIXTURE/sentinel.json"
run_gate "$REPO" "git commit -m 'change validator'" "$OUTPUT"
[ "$GATE_STATUS" -eq 0 ] && grep -q 'disabled by' "$OUTPUT"
check 'recovery: the sentinel allows a locked change and says so' $?

# blast radius -- a dirty locked file must not deny commits that touch nothing
# controlled. Denying those is what made the whole repo uncommittable.
new_fixture
mkdir -p "$REPO/scripts"
printf '%s\n' 'original validator' > "$REPO/scripts/agent-contract-validator.mjs"
git -C "$REPO" add scripts/agent-contract-validator.mjs
git -C "$REPO" commit -qm 'add validator'
printf '%s\n' 'dirty working tree' > "$REPO/scripts/agent-contract-validator.mjs"
printf '%s\n' 'note' > "$REPO/NOTES.md"
git -C "$REPO" add NOTES.md
OUTPUT="$FIXTURE/dirty-unrelated.json"
run_gate "$REPO" "git commit -m 'unrelated note'" "$OUTPUT"
assert_allow 'blast radius: a dirty locked file does not block unrelated commits' "$OUTPUT"

# blast radius -- a dirty locked file does not block a staged nonlocked controlled path
printf '%s\n' '---' 'name: another' 'tools: [Read]' '---' > "$REPO/agents/another.md"
git -C "$REPO" add agents/another.md
OUTPUT="$FIXTURE/dirty-controlled.json"
run_gate "$REPO" "git commit -m 'agent change while gate is dirty'" "$OUTPUT"
assert_allow 'blast radius: a dirty locked file allows staged nonlocked controlled commits' "$OUTPUT"

# The gate is registered again now that bootstrap, update, and recovery exist.
# It was deliberately unregistered on 2026-08-22 because none of them did.
node -e '
const fs = require("node:fs")
const data = JSON.parse(fs.readFileSync(process.argv[1], "utf8"))
const hooks = data.hooks.PreToolUse ?? []
const commands = hooks.filter(item => item.matcher === "Bash").flatMap(item => item.hooks ?? []).map(item => item.command ?? "")
if (!commands.some(command => command === "~/.claude/hooks/agent-contract-validator-gate.sh")) process.exit(1)
' "$ROOT/settings.json"
check 'settings wires the commit gate to Bash' $?

new_fixture
printf '%s\n' '---' 'name: demo' '---' 'subagent_type: missing-agent' > "$REPO/.claude/skills/demo/SKILL.md"
OUTPUT="$FIXTURE/pathspec-unstaged.json"
run_gate "$REPO" "git commit -m 'bare pathspec' .claude/skills/demo/SKILL.md" "$OUTPUT"
assert_denial_reason 'bare pathspec naming an unstaged controlled path fails closed' "$OUTPUT" 'pathspec commit naming controlled path .claude/skills/demo/SKILL.md'

new_fixture
printf '%s\n' 'extra' >> "$REPO/agents/good.md"
git -C "$REPO" add agents/good.md
OUTPUT="$FIXTURE/pathspec-in-message.json"
run_gate "$REPO" "git commit -m 'touch .claude/skills/demo/SKILL.md later'" "$OUTPUT"
assert_allow 'controlled path quoted inside the commit message is not a pathspec' "$OUTPUT"

new_fixture
printf '%s\n' 'more' >> "$REPO/README.md"
OUTPUT="$FIXTURE/pathspec-uncontrolled.json"
run_gate "$REPO" "git commit -m 'readme only' README.md" "$OUTPUT"
assert_allow 'bare pathspec naming an uncontrolled path is allowed' "$OUTPUT"

new_fixture
printf '%s\n' 'extra' >> "$REPO/agents/good.md"
git -C "$REPO" add agents/good.md
OUTPUT="$FIXTURE/pathspec-after-separator.json"
run_gate "$REPO" "git commit -m 'chained' && git status --short .claude/skills/demo/SKILL.md" "$OUTPUT"
assert_allow 'controlled path in a later chained command is not a pathspec of the commit' "$OUTPUT"

new_fixture
printf '%s\n' 'extra' >> "$REPO/agents/good.md"
git -C "$REPO" add agents/good.md
printf '%s\n' '{"permissions":{}}' > "$REPO/settings.json"
OUTPUT="$FIXTURE/message-add-word.json"
run_gate "$REPO" "git commit -m 'note: add hook and settings'" "$OUTPUT"
assert_allow 'commit message containing add is not treated as auto-stage' "$OUTPUT"

new_fixture
printf '%s\n' 'extra' >> "$REPO/agents/good.md"
git -C "$REPO" add agents/good.md
printf '%s\n' '{"permissions":{}}' > "$REPO/settings.json"
OUTPUT="$FIXTURE/message-add-word-am.json"
run_gate "$REPO" "git commit -am 'add note'" "$OUTPUT"
assert_deny 'commit -am with add in message still fails closed on unstaged controlled path' "$OUTPUT"

new_fixture
OUTPUT="$FIXTURE/heredoc-mention.json"
run_gate "$REPO" "python3 - <<'EOF'
print(\"git commit -m \`x\` add\")
EOF" "$OUTPUT"
assert_allow 'heredoc body mentioning git commit and backticks is ignored' "$OUTPUT"

new_fixture
printf '%s\n' 'extra' >> "$REPO/agents/good.md"
git -C "$REPO" add agents/good.md
MULTILINE_DOUBLE='git commit -m "release notes
git add .claude/skills/demo/SKILL.md
end"'
OUTPUT="$FIXTURE/multiline-double-quote.json"
run_gate "$REPO" "$MULTILINE_DOUBLE" "$OUTPUT"
assert_allow 'multiline double-quoted commit message mentioning git add is ignored' "$OUTPUT"

new_fixture
printf '%s\n' 'extra' >> "$REPO/agents/good.md"
git -C "$REPO" add agents/good.md
MULTILINE_SINGLE="git commit -m 'release notes: prefix git add spec
continued'"
OUTPUT="$FIXTURE/multiline-single-quote.json"
run_gate "$REPO" "$MULTILINE_SINGLE" "$OUTPUT"
assert_allow 'multiline single-quoted first-line git add spec is ignored' "$OUTPUT"

new_fixture
mkdir -p "$REPO/scripts" "$REPO/hooks"
printf '%s\n' 'original validator' > "$REPO/scripts/agent-contract-validator.mjs"
printf '%s\n' 'original gate' > "$REPO/hooks/agent-contract-validator-gate.sh"
git -C "$REPO" add scripts/agent-contract-validator.mjs hooks/agent-contract-validator-gate.sh
git -C "$REPO" commit -qm 'add locked surfaces'
printf '%s\n' 'dirty validator' > "$REPO/scripts/agent-contract-validator.mjs"
printf '%s\n' 'changed gate' > "$REPO/hooks/agent-contract-validator-gate.sh"
git -C "$REPO" add hooks/agent-contract-validator-gate.sh
OUTPUT="$FIXTURE/dirty-staged-locked.json"
run_gate "$REPO" "git commit -m 'locked change while gate is dirty'" "$OUTPUT"
assert_denial_reason 'dirty evaluator with no HEAD copy to hand over to denies a staged locked path' "$OUTPUT" 'cannot take over'

new_fixture
printf '%s\n' '---' 'name: demo' '---' 'subagent_type: missing-agent' > "$REPO/.claude/skills/demo/SKILL.md"
COMMENT_DOUBLE="# \"unmatched
git add .claude/skills/demo/SKILL.md && git commit -m bad"
OUTPUT="$FIXTURE/comment-double-before-add-commit.json"
run_gate "$REPO" "$COMMENT_DOUBLE" "$OUTPUT"
assert_denial_reason 'double-quoted comment text does not hide a real add and commit' "$OUTPUT" post-add

new_fixture
printf '%s\n' '---' 'name: demo' '---' 'subagent_type: missing-agent' > "$REPO/.claude/skills/demo/SKILL.md"
COMMENT_SINGLE="# 'unmatched
git add .claude/skills/demo/SKILL.md && git commit -m bad"
OUTPUT="$FIXTURE/comment-single-before-add-commit.json"
run_gate "$REPO" "$COMMENT_SINGLE" "$OUTPUT"
assert_denial_reason 'single-quoted comment text does not hide a real add and commit' "$OUTPUT" post-add

new_fixture
printf '%s\n' '---' 'name: demo' '---' 'subagent_type: missing-agent' > "$REPO/.claude/skills/demo/SKILL.md"
git -C "$REPO" add .claude/skills/demo/SKILL.md
HASH_BOUNDARY='printf foo#bar; git commit -m boundary'
OUTPUT="$FIXTURE/hash-boundary.json"
run_gate "$REPO" "$HASH_BOUNDARY" "$OUTPUT"
assert_validator_diagnostic 'hash inside a token is not a comment' "$OUTPUT" UNKNOWN_AGENT_REFERENCE

new_fixture
printf '%s\n' 'extra' >> "$REPO/agents/good.md"
git -C "$REPO" add agents/good.md
ESCAPED_QUOTE='git commit -m "prefix \" git add spec"'
OUTPUT="$FIXTURE/escaped-quote.json"
run_gate "$REPO" "$ESCAPED_QUOTE" "$OUTPUT"
assert_allow 'escaped double quote keeps git add inside the message' "$OUTPUT"

new_fixture
mkdir -p "$REPO/scripts"
printf '%s\n' 'original validator' > "$REPO/scripts/agent-contract-validator.mjs"
git -C "$REPO" add scripts/agent-contract-validator.mjs
git -C "$REPO" commit -qm 'add validator'
printf '%s\n' 'dirty validator' > "$REPO/scripts/agent-contract-validator.mjs"
printf '%s\n' '---' 'name: demo' '---' 'subagent_type: missing-agent' > "$REPO/.claude/skills/demo/SKILL.md"
git -C "$REPO" add .claude/skills/demo/SKILL.md
OUTPUT="$FIXTURE/dirty-invalid-controlled.json"
run_gate "$REPO" "git commit -m 'invalid agent with dirty lock'" "$OUTPUT"
assert_validator_diagnostic 'dirty lock does not skip staged validator checks' "$OUTPUT" UNKNOWN_AGENT_REFERENCE

new_fixture
printf '%s\n' '---' 'name: demo' '---' 'subagent_type: missing-agent' > "$REPO/.claude/skills/demo/SKILL.md"
git -C "$REPO" add .claude/skills/demo/SKILL.md
CROSS_LINE_TOKEN="printf '%s' \"foo
bar\"#literal && git commit -m real"
OUTPUT="$FIXTURE/cross-line-token-boundary.json"
run_gate "$REPO" "$CROSS_LINE_TOKEN" "$OUTPUT"
assert_validator_diagnostic 'cross-line token boundary does not hide a real commit' "$OUTPUT" UNKNOWN_AGENT_REFERENCE

new_fixture
printf '%s\n' '---' 'name: demo' '---' 'subagent_type: missing-agent' > "$REPO/.claude/skills/demo/SKILL.md"
git -C "$REPO" add .claude/skills/demo/SKILL.md
OUTSIDE_ESCAPED_QUOTE=$(printf 'printf \134"\n%s\n' 'git commit -m real')
OUTPUT="$FIXTURE/outside-escaped-quote.json"
run_gate "$REPO" "$OUTSIDE_ESCAPED_QUOTE" "$OUTPUT"
assert_validator_diagnostic 'outside escaped quote does not hide a real commit' "$OUTPUT" UNKNOWN_AGENT_REFERENCE

new_fixture
printf '%s\n' '---' 'name: demo' '---' 'subagent_type: missing-agent' > "$REPO/.claude/skills/demo/SKILL.md"
git -C "$REPO" add .claude/skills/demo/SKILL.md
LINE_CONTINUATION=$(printf 'printf \134\n%s\n' '"foo" && git commit -m real')
OUTPUT="$FIXTURE/line-continuation.json"
run_gate "$REPO" "$LINE_CONTINUATION" "$OUTPUT"
assert_validator_diagnostic 'line continuation does not hide a real commit' "$OUTPUT" UNKNOWN_AGENT_REFERENCE

new_fixture
printf '%s\n' '---' 'name: demo' '---' 'subagent_type: missing-agent' > "$REPO/.claude/skills/demo/SKILL.md"
git -C "$REPO" add .claude/skills/demo/SKILL.md
QUOTED_DOUBLE_BACKSLASH=$(printf '%s\n' 'printf "foo\\' 'bar" && git commit -m real')
OUTPUT="$FIXTURE/quoted-double-backslash.json"
run_gate "$REPO" "$QUOTED_DOUBLE_BACKSLASH" "$OUTPUT"
assert_validator_diagnostic 'quoted double backslash preserves Bash quote semantics' "$OUTPUT" UNKNOWN_AGENT_REFERENCE

new_fixture
stage_locked_validator_change
OUTPUT="$FIXTURE/readonly-recap.json"
READONLY_RECAP='repos=$(find "$HOME/code" -maxdepth 2 -name .git -type d | xargs -I{} sh -c '\''cd "$1" && pwd -P'\'' sh {}); printf "%s\n" "$repos" | while IFS= read -r repo; do commits=$(git -C "$repo" log --branches --since="24 hours ago" --format="%H %s"); printf "%s\n" "$commits"; done'
run_gate "$REPO" "$READONLY_RECAP" "$OUTPUT"
assert_allow 'readonly recap does not confuse commits variable with execution' "$OUTPUT"

new_fixture
stage_locked_validator_change
OUTPUT="$FIXTURE/readonly-commit-argument.json"
run_gate "$REPO" 'git log --format=%s --grep commit' "$OUTPUT"
assert_allow 'commit as an argument of git log is not a commit command' "$OUTPUT"

new_fixture
stage_locked_validator_change
OUTPUT="$FIXTURE/literal-shell-commit-text.json"
run_gate "$REPO" "printf '%s\\n' 'sh -c git commit'" "$OUTPUT"
assert_allow 'quoted shell and commit words remain data' "$OUTPUT"

new_fixture
stage_locked_validator_change
OUTPUT="$FIXTURE/heredoc-shell-commit-text.json"
run_gate "$REPO" "python3 - <<'PY'
text = 'sh -c git commit'
print(text)
PY" "$OUTPUT"
assert_allow 'quoted heredoc mentioning nested shell commit remains data' "$OUTPUT"

new_fixture
stage_locked_validator_change
OUTPUT="$FIXTURE/readonly-nested-shell.json"
run_gate "$REPO" "sh -c 'git log --grep commit'" "$OUTPUT"
assert_allow 'literal nested readonly git query is not a nested commit' "$OUTPUT"

new_fixture
printf '%s\n' 'extra' >> "$REPO/agents/good.md"
git -C "$REPO" add agents/good.md
OUTPUT="$FIXTURE/message-shell-commit-text.json"
run_gate "$REPO" "git commit -m 'document sh -c git commit without executing it'" "$OUTPUT"
assert_allow 'commit message mentioning nested shell does not change classification' "$OUTPUT"

for NESTED_STAGE in 'git commit -m "$(git add agents/good.md; printf note)"' "sh -c 'git add agents/good.md'; git commit -m note" 'printf agents/good.md | xargs git add; git commit -m note'; do
  new_fixture
  printf '%s\n' unstaged >> "$REPO/agents/good.md"
  OUTPUT="$FIXTURE/nested-staging.json"
  run_gate "$REPO" "$NESTED_STAGE" "$OUTPUT"
  assert_denial_reason "nested staging still requires a separate add: $NESTED_STAGE" "$OUTPUT" post-add
done

new_fixture
printf '%s\n' unstaged >> "$REPO/agents/good.md"
OUTPUT="$FIXTURE/function-staging.json"
run_gate "$REPO" 'stage() { git add agents/good.md; }; stage; git commit -m note' "$OUTPUT"
assert_denial_reason 'function staging cannot reuse the original index' "$OUTPUT" post-add

new_fixture
stage_locked_validator_change
OUTPUT="$FIXTURE/xargs-readonly.json"
run_gate "$REPO" 'printf /repo | xargs -I{} git -C {} log' "$OUTPUT"
assert_allow 'xargs repository placeholder remains readonly query data' "$OUTPUT"

for XARGS_DYNAMIC in 'printf commit | xargs -I{} git {}' 'printf commit | xargs -I-C git -C /repo log'; do
  OUTPUT="$FIXTURE/xargs-dynamic.json"
  run_gate "$REPO" "$XARGS_DYNAMIC" "$OUTPUT"
  assert_denial_reason "xargs executable grammar remains protected: $XARGS_DYNAMIC" "$OUTPUT" 'dynamic Git subcommand'
done

for PROTECTED_PATH in scripts/agent-contract-command/main.go scripts/agent-contract-command/go.mod scripts/agent-contract-command/go.sum scripts/agent-contract-command/main_test.go hooks/agent-contract-validator-gate.test.sh; do
  new_fixture
  install_real_gate
  if [ ! -f "$REPO/$PROTECTED_PATH" ]; then
    mkdir -p "$(dirname "$REPO/$PROTECTED_PATH")"
    printf '%s\n' original > "$REPO/$PROTECTED_PATH"
    git -C "$REPO" add "$PROTECTED_PATH"
    git -C "$REPO" commit -qm 'install protected parser test surface'
  fi
  printf '\n// changed\n' >> "$REPO/$PROTECTED_PATH"
  git -C "$REPO" add "$PROTECTED_PATH"
  OUTPUT="$FIXTURE/parser-locked.json"
  run_gate "$REPO" "git commit -m 'change parser surface'" "$OUTPUT"
  assert_denial_reason "parser lifecycle: $PROTECTED_PATH requires a permit" "$OUTPUT" 'needs a permit'
  issue_permit "$FIXTURE/permit"
  printf '%s\n' changed-again > "$REPO/$PROTECTED_PATH"
  git -C "$REPO" add "$PROTECTED_PATH"
  OUTPUT="$FIXTURE/parser-drift.json"
  run_gate "$REPO" "git commit -m 'change parser surface after approval'" "$OUTPUT"
  assert_denial_reason "parser lifecycle: $PROTECTED_PATH invalidates stale permit" "$OUTPUT" 'different locked content'
  issue_permit "$FIXTURE/permit"
  OUTPUT="$FIXTURE/parser-permitted.json"
  run_gate "$REPO" "git commit -m 'approved parser surface'" "$OUTPUT"
  assert_allow "parser lifecycle: $PROTECTED_PATH accepts matching permit" "$OUTPUT"
done

new_fixture
install_real_gate
printf '\n// unfinished parser\n' >> "$REPO/scripts/agent-contract-command/main.go"
printf '\n// staged validator\n' >> "$REPO/scripts/agent-contract-validator.mjs"
git -C "$REPO" add scripts/agent-contract-validator.mjs
OUTPUT="$FIXTURE/parser-head.json"
run_gate "$REPO" "git commit -m 'validator while parser is dirty'" "$OUTPUT"
assert_denial_reason 'dirty parser hands execution to HEAD without losing permit enforcement' "$OUTPUT" 'needs a permit'
command grep -q 'head-evaluator' "$FIXTURE/audit.jsonl"
check 'dirty parser handover has an audit record' $?

new_fixture
OUTPUT="$FIXTURE/parser-syntax.json"
run_gate "$REPO" "git commit -m 'unterminated" "$OUTPUT"
assert_denial_reason 'parser syntax failure denies rather than claiming no commit' "$OUTPUT" 'command parser failed'

new_fixture
ORIGINAL_GATE="$GATE"
mkdir -p "$FIXTURE/runtime/hooks"
cp "$GATE" "$FIXTURE/runtime/hooks/agent-contract-validator-gate.sh"
GATE="$FIXTURE/runtime/hooks/agent-contract-validator-gate.sh"
OUTPUT="$FIXTURE/parser-missing-readonly.json"
run_gate "$REPO" 'G=git; "$G" status' "$OUTPUT"
assert_allow 'missing parser cannot deny a command without lowercase commit' "$OUTPUT"
OUTPUT="$FIXTURE/parser-missing.json"
run_gate "$REPO" 'git commit -m note' "$OUTPUT"
assert_denial_reason 'missing parser denies a command containing commit' "$OUTPUT" 'command parser failed'
mkdir -p "$FIXTURE/runtime/scripts/agent-contract-command"
printf '%s\n' 'module example.com/broken-parser' 'go 1.26.0' > "$FIXTURE/runtime/scripts/agent-contract-command/go.mod"
printf '%s\n' 'package main' 'import "os"' 'func main() { os.Exit(7) }' > "$FIXTURE/runtime/scripts/agent-contract-command/main.go"
OUTPUT="$FIXTURE/parser-nonzero.json"
run_gate "$REPO" 'git commit -m note' "$OUTPUT"
assert_denial_reason 'nonzero parser exit cannot allow a command' "$OUTPUT" 'command parser failed'
printf '%s\n' 'package main' 'import "fmt"' 'func main() { fmt.Print("{}") }' > "$FIXTURE/runtime/scripts/agent-contract-command/main.go"
OUTPUT="$FIXTURE/parser-invalid-result.json"
run_gate "$REPO" 'git commit -m note' "$OUTPUT"
assert_denial_reason 'incomplete parser JSON cannot allow a command' "$OUTPUT" 'invalid result'
printf '%s\n' 'package main' 'import "fmt"' 'func main() { fmt.Print("not-json") }' > "$FIXTURE/runtime/scripts/agent-contract-command/main.go"
OUTPUT="$FIXTURE/parser-malformed-result.json"
run_gate "$REPO" 'git commit -m note' "$OUTPUT"
assert_denial_reason 'malformed parser JSON cannot allow a command' "$OUTPUT" 'invalid result'
GATE="$ORIGINAL_GATE"

new_fixture
install_real_gate
printf '\n// dirty parser\n' >> "$REPO/scripts/agent-contract-command/main.go"
printf '%s\n' unrelated >> "$REPO/README.md"
git -C "$REPO" add README.md
OUTPUT="$FIXTURE/parser-unrelated.json"
run_gate "$REPO" "git commit -m 'unrelated change'" "$OUTPUT"
assert_allow 'dirty parser does not freeze unrelated commits when HEAD can take over' "$OUTPUT"

new_fixture
stage_locked_validator_change
INDEX_BEFORE=$(git -C "$REPO" write-tree)
cp "$REPO/scripts/agent-contract-validator.mjs" "$FIXTURE/validator-before.mjs"
OUTPUT="$FIXTURE/parser-no-execution.json"
run_gate "$REPO" "printf '%s' 'sh -c git commit'; touch $FIXTURE/should-not-exist" "$OUTPUT"
assert_allow 'parser treats executable input as data rather than running it' "$OUTPUT"
[ ! -e "$FIXTURE/should-not-exist" ] && [ "$INDEX_BEFORE" = "$(git -C "$REPO" write-tree)" ] && cmp -s "$FIXTURE/validator-before.mjs" "$REPO/scripts/agent-contract-validator.mjs"
check 'parser leaves input side effects, index, and unrelated source unchanged' $?

# ---------------------------------------------------------------------------
# M10.2: INSPECT_HINT reflects single-quoted -F - <<'EOF' support (reverse assertion: no "no heredoc")
# ---------------------------------------------------------------------------
new_fixture
printf '%s\n' 'extra' >> "$REPO/agents/good.md"
git -C "$REPO" add agents/good.md
OUTPUT="$FIXTURE/heredoc-commit-msg.json"
run_gate "$REPO" "git commit -F - <<'EOF'
feat(agents): allow single-quoted heredoc commit message

Body line mentioning git add without executing it.
EOF" "$OUTPUT"
assert_allow 'single-quoted -F - <<EOF heredoc commit is allowed' "$OUTPUT"

new_fixture
OUTPUT="$FIXTURE/inspect-hint-heredoc.json"
run_gate / "cd / && cd $REPO && git commit -m 'hint check'" "$OUTPUT"
assert_denial_reason 'INSPECT_HINT advertises single-quoted -F - <<EOF' "$OUTPUT" "-F - <<'EOF'"
if node -e '
const fs = require("node:fs")
const data = JSON.parse(fs.readFileSync(process.argv[1], "utf8"))
const reason = data.hookSpecificOutput?.permissionDecisionReason ?? ""
if (reason.includes("no heredoc")) process.exit(1)
' "$OUTPUT"; then
  check 'reverse assertion: INSPECT_HINT no longer says no heredoc' 0
else
  check 'reverse assertion: INSPECT_HINT no longer says no heredoc' 1
fi

# ---------------------------------------------------------------------------
# H6.1 + Advisor adjustment: dirty-worktree git merge / pull / rebase guard
# ---------------------------------------------------------------------------

# Known-good: clean worktree allows newly initiated merge, pull, and rebase
new_fixture
for CLEAN_INTEGRATION in 'git merge origin/main' 'git pull --ff-only' 'git rebase main'; do
  OUTPUT="$FIXTURE/clean-integration.json"
  run_gate "$REPO" "$CLEAN_INTEGRATION" "$OUTPUT"
  assert_allow "clean worktree allows $CLEAN_INTEGRATION" "$OUTPUT"
done

# Known-good: gitignored-only files do not make git status --porcelain dirty
new_fixture
printf '%s\n' '*.ignored.log' > "$REPO/.gitignore"
git -C "$REPO" add .gitignore
git -C "$REPO" commit -qm 'ignore logs'
printf '%s\n' 'noise' > "$REPO/build.ignored.log"
OUTPUT="$FIXTURE/ignored-only-merge.json"
run_gate "$REPO" 'git merge origin/main' "$OUTPUT"
assert_allow 'gitignored-only file allows git merge in clean worktree' "$OUTPUT"

# Known-bad: unstaged tracked, staged, and untracked files each block merge / pull / rebase
new_fixture
printf '%s\n' 'unstaged edit' >> "$REPO/README.md"
for DIRTY_CMD in 'git merge origin/main' 'git merge --ff-only origin/main' 'git pull' 'git pull --rebase' 'git rebase main'; do
  OUTPUT="$FIXTURE/dirty-unstaged.json"
  run_gate "$REPO" "$DIRTY_CMD" "$OUTPUT"
  assert_denial_reason "unstaged dirty worktree blocks $DIRTY_CMD and cites clean worktree" "$OUTPUT" 'worktree add --detach'
done

new_fixture
printf '%s\n' 'staged edit' >> "$REPO/README.md"
git -C "$REPO" add README.md
OUTPUT="$FIXTURE/dirty-staged-merge.json"
run_gate "$REPO" 'git merge origin/main' "$OUTPUT"
assert_denial_reason 'staged dirty worktree blocks newly initiated git merge' "$OUTPUT" 'dirty worktree'

new_fixture
printf '%s\n' 'untracked file' > "$REPO/unclaimed.txt"
OUTPUT="$FIXTURE/dirty-untracked-rebase.json"
run_gate "$REPO" 'git rebase origin/main' "$OUTPUT"
assert_denial_reason 'untracked dirty worktree blocks newly initiated git rebase' "$OUTPUT" 'dirty worktree'

# Known-good escape path: temporary clean worktree works even while shared checkout cwd is dirty
new_fixture
CLEAN_WT="$FIXTURE/clean-wt"
git -C "$REPO" worktree add -q --detach "$CLEAN_WT" HEAD
printf '%s\n' 'other session dirty file' > "$REPO/unclaimed.txt"
OUTPUT="$FIXTURE/clean-wt-git-c.json"
run_gate "$REPO" "git -C $CLEAN_WT merge origin/main" "$OUTPUT"
assert_allow 'git -C clean worktree merge is allowed while shared cwd is dirty' "$OUTPUT"
OUTPUT="$FIXTURE/clean-wt-subshell-cd.json"
run_gate "$REPO" "(cd $CLEAN_WT && git merge origin/main)" "$OUTPUT"
assert_allow 'subshell cd into clean worktree merge is allowed while shared cwd is dirty' "$OUTPUT"

# Known-bad target resolution: git -C, subshell cd, bash -c, and subshell pop back to dirty cwd
OUTPUT="$FIXTURE/dirty-from-clean-cwd-gitc.json"
run_gate "$CLEAN_WT" "git -C $REPO merge origin/main" "$OUTPUT"
assert_denial_reason 'git -C targeting dirty repo from clean cwd is denied' "$OUTPUT" 'dirty worktree'

OUTPUT="$FIXTURE/dirty-from-clean-cwd-cd.json"
run_gate "$CLEAN_WT" "(cd $REPO && git pull)" "$OUTPUT"
assert_denial_reason 'subshell cd targeting dirty repo from clean cwd is denied' "$OUTPUT" 'dirty worktree'

OUTPUT="$FIXTURE/dirty-after-subshell-pop.json"
run_gate "$REPO" "(cd $CLEAN_WT && git status) && git merge origin/main" "$OUTPUT"
assert_denial_reason 'subshell cd does not leak cleanliness to outer dirty merge' "$OUTPUT" 'dirty worktree'

OUTPUT="$FIXTURE/dirty-bash-c-merge.json"
run_gate "$REPO" "bash -c 'git merge origin/main'" "$OUTPUT"
assert_denial_reason 'nested bash -c git merge in dirty worktree is denied' "$OUTPUT" 'dirty worktree'

# Fail-closed on dynamic target or custom Git selector for non-exempt integration
OUTPUT="$FIXTURE/dirty-dynamic-gitc.json"
run_gate "$CLEAN_WT" 'TARGET_DIR='"$REPO"'; git -C "$TARGET_DIR" merge origin/main' "$OUTPUT"
assert_denial_reason 'dynamic git -C target on git merge fails closed' "$OUTPUT" 'dynamic cd or git -C target'

OUTPUT="$FIXTURE/dirty-selector-merge.json"
run_gate "$CLEAN_WT" "GIT_WORK_TREE=$REPO git merge origin/main" "$OUTPUT"
assert_denial_reason 'GIT_WORK_TREE selector on git merge fails closed' "$OUTPUT" 'custom Git selector'

origin_ahead_fixture() {
  new_fixture
  # An upstream addition lets the case-fold fixture work on case-insensitive disks too.
  if [ "${1:-}" = casefold ]; then git -C "$REPO" rm -q README.md; fi
  mkdir -p "$REPO/dir"
  printf '%s\n' 'upstream directory' > "$REPO/dir/tracked.txt"
  printf '%s\n' 'old' > "$REPO/old.txt"
  printf '%s\n' 'keep' > "$REPO/local-only.txt"
  printf '%s\n' 'index base' > "$REPO/staged-only.txt"
  git -C "$REPO" add dir/tracked.txt old.txt local-only.txt staged-only.txt
  git -C "$REPO" commit -qm 'seed files'
  ORIGIN="$FIXTURE/origin.git"
  git init -q --bare "$ORIGIN"
  git -C "$REPO" remote add origin "$ORIGIN"
  git -C "$REPO" push -q origin HEAD:refs/heads/main
  UPSTREAM="$FIXTURE/upstream"
  git clone -q -b main "$ORIGIN" "$UPSTREAM"
  git -C "$UPSTREAM" config user.email test@example.com
  git -C "$UPSTREAM" config user.name test
  printf '%s\n' 'upstream edit' >> "$UPSTREAM/README.md"
  printf '%s\n' 'upstream add' > "$UPSTREAM/added.txt"
  git -C "$UPSTREAM" mv old.txt renamed.txt
  git -C "$UPSTREAM" rm -q dir/tracked.txt
  printf '%s\n' 'upstream file' > "$UPSTREAM/dir"
  git -C "$UPSTREAM" add README.md added.txt dir
  git -C "$UPSTREAM" commit -qm 'upstream change'
  git -C "$UPSTREAM" push -q origin HEAD:refs/heads/main
  git -C "$REPO" fetch -q origin
}

FF_FLAGS=(--ff-only --no-autostash --no-overwrite-ignore)
origin_ahead_fixture
printf '%s\n' 'other session edit' >> "$REPO/local-only.txt"
printf '%s\n' 'other session staged' > "$REPO/staged-only.txt"
git -C "$REPO" add staged-only.txt
printf '%s\n' 'other session note' > "$REPO/unclaimed.txt"
for DISJOINT_MERGE in "git merge ${FF_FLAGS[*]} origin/main" \
  "git merge ${FF_FLAGS[*]} --no-edit origin/main" \
  "git -C '$REPO' merge -q -n ${FF_FLAGS[*]} origin/main"; do
  OUTPUT="$FIXTURE/disjoint-merge.json"
  run_gate "$REPO" "$DISJOINT_MERGE" "$OUTPUT"
  assert_allow "disjoint dirty paths allow $DISJOINT_MERGE" "$OUTPUT"
done

for DISJOINT_OTHER in 'git merge origin/main' 'git merge --ff-only origin/main' \
  "git merge --no-commit ${FF_FLAGS[*]} origin/main" \
  "git merge ${FF_FLAGS[*]} --autostash origin/main" \
  "git merge ${FF_FLAGS[*]} FETCH_HEAD" \
  'git pull --ff-only' 'git rebase origin/main'; do
  OUTPUT="$FIXTURE/disjoint-other.json"
  run_gate "$REPO" "$DISJOINT_OTHER" "$OUTPUT"
  assert_denial_reason "disjoint dirty paths still deny $DISJOINT_OTHER" "$OUTPUT" "git -C <repo> merge ${FF_FLAGS[*]} origin/<trunk>"
done

OUTPUT="$FIXTURE/actual-fast-forward-gate.json"
run_gate "$REPO" "git merge ${FF_FLAGS[*]} origin/main" "$OUTPUT"
STATUS_BEFORE=$(git -C "$REPO" status --porcelain=v1 --untracked-files=all)
if [ "$GATE_STATUS" -eq 0 ] && [ ! -s "$OUTPUT" ] &&
  git -C "$REPO" merge "${FF_FLAGS[@]}" origin/main > "$FIXTURE/actual-fast-forward.log" 2>&1 &&
  [ "$(git -C "$REPO" rev-parse HEAD)" = "$(git -C "$REPO" rev-parse origin/main)" ] &&
  [ "$STATUS_BEFORE" = $' M local-only.txt\nM  staged-only.txt\n?? unclaimed.txt' ] &&
  [ "$(git -C "$REPO" status --porcelain=v1 --untracked-files=all)" = "$STATUS_BEFORE" ] &&
  cmp -s "$REPO/local-only.txt" <(printf '%s\n' 'keep' 'other session edit') &&
  cmp -s "$REPO/staged-only.txt" <(printf '%s\n' 'other session staged') &&
  cmp -s "$REPO/unclaimed.txt" <(printf '%s\n' 'other session note') &&
  git -C "$REPO" show :staged-only.txt | cmp -s - <(printf '%s\n' 'other session staged'); then
  check 'actual fast-forward reaches origin/main and preserves unstaged, staged and untracked files and index' 0
else
  check 'actual fast-forward reaches origin/main and preserves unstaged, staged and untracked files and index' 1
fi

origin_ahead_fixture
printf '%s\n' 'local commit' > "$REPO/local-commit.txt"
git -C "$REPO" add local-commit.txt
git -C "$REPO" commit -qm 'local change'
printf '%s\n' 'other session edit' >> "$REPO/local-only.txt"
OUTPUT="$FIXTURE/diverged.json"
run_gate "$REPO" "git merge ${FF_FLAGS[*]} origin/main" "$OUTPUT"
assert_denial_reason 'diverged branches deny even a disjoint merge with all required flags' "$OUTPUT" 'not a fast-forward'

for OVERLAP_PATH in README.md added.txt old.txt readme.md dir/local.txt; do
  if [ "$OVERLAP_PATH" = readme.md ]; then origin_ahead_fixture casefold; else origin_ahead_fixture; fi
  printf '%s\n' 'other session edit' >> "$REPO/$OVERLAP_PATH"
  OUTPUT="$FIXTURE/overlap.json"
  run_gate "$REPO" "git merge ${FF_FLAGS[*]} origin/main" "$OUTPUT"
  assert_denial_reason "fast-forward denies overlap with $OVERLAP_PATH" "$OUTPUT" "changed by the merge: $OVERLAP_PATH."
done

# Git still checks ignored files, which do not appear in porcelain status.
origin_ahead_fixture
printf '%s\n' 'added.txt' >> "$REPO/.git/info/exclude"
printf '%s\n' 'ignored local file' > "$REPO/added.txt"
printf '%s\n' 'other session edit' >> "$REPO/local-only.txt"
HEAD_BEFORE=$(git -C "$REPO" rev-parse HEAD)
OUTPUT="$FIXTURE/ignored-gate.json"
run_gate "$REPO" "git merge ${FF_FLAGS[*]} origin/main" "$OUTPUT"
assert_allow 'disjoint tracked changes can reach Git’s ignored-file check' "$OUTPUT"
if ! git -C "$REPO" merge "${FF_FLAGS[@]}" origin/main > "$FIXTURE/ignored-fast-forward.log" 2>&1 &&
  [ "$(git -C "$REPO" rev-parse HEAD)" = "$HEAD_BEFORE" ] &&
  cmp -s "$REPO/added.txt" <(printf '%s\n' 'ignored local file'); then
  check 'Git rejects fast-forward over an ignored file and preserves it' 0
else
  check 'Git rejects fast-forward over an ignored file and preserves it' 1
fi

# Keep the required flags on each case so resolution failures cannot pass via the flag check.
for UNSAFE_TARGET in '' 'origin/main HEAD' 'origin/missing' '-- origin/main' -; do
  OUTPUT="$FIXTURE/unsafe-merge.json"
  run_gate "$REPO" "git merge ${FF_FLAGS[*]} $UNSAFE_TARGET" "$OUTPUT"
  assert_denial_reason "dirty worktree denies unprovable fast-forward target '$UNSAFE_TARGET'" "$OUTPUT" 'dirty worktree'
done

# Advisor adjustment: --continue / --abort / --quit / --skip / --help / -h MUST be allowed when dirty
new_fixture
printf '%s\n' 'resolved conflict content' > "$REPO/README.md"
git -C "$REPO" add README.md
printf '%s\n' 'untracked review bundle' > "$REPO/bundle.txt"
for ALLOWED_IN_PROGRESS in \
  'git merge --continue' \
  'git merge --abort' \
  'git merge --quit' \
  'git rebase --continue' \
  'git rebase --abort' \
  'git rebase --quit' \
  'git rebase --skip' \
  'git rebase --show-current-patch' \
  'git pull --continue' \
  'git pull --abort' \
  'git pull --quit' \
  'git pull --skip' \
  'git merge -h' \
  'git merge --help' \
  'git rebase --help' \
  'git pull -h' \
  'git -h merge' \
  "git -C $REPO rebase --continue"; do
  OUTPUT="$FIXTURE/in-progress-allow.json"
  run_gate "$REPO" "$ALLOWED_IN_PROGRESS" "$OUTPUT"
  assert_allow "dirty worktree allows in-progress/help command: $ALLOWED_IN_PROGRESS" "$OUTPUT"
done

# Boundary / bypass resistance: --continue as option value, after --, or chained before real merge still denies
OUTPUT="$FIXTURE/fake-continue-msg.json"
run_gate "$REPO" 'git merge -m "--continue" origin/main' "$OUTPUT"
assert_denial_reason 'option value --continue to -m does not exempt git merge' "$OUTPUT" 'dirty worktree'

OUTPUT="$FIXTURE/fake-continue-double-dash.json"
run_gate "$REPO" 'git merge origin/main -- --continue' "$OUTPUT"
assert_denial_reason 'positional --continue after -- does not exempt git merge' "$OUTPUT" 'dirty worktree'

OUTPUT="$FIXTURE/chained-abort-then-merge.json"
run_gate "$REPO" 'git merge --abort && git merge origin/main' "$OUTPUT"
assert_denial_reason 'exempt --abort chained with new git merge still denies the new merge' "$OUTPUT" 'dirty worktree'

# Boundary: mentions and non-integration commands in a dirty worktree remain allowed
new_fixture
printf '%s\n' 'dirty unstaged' >> "$REPO/README.md"
printf '%s\n' 'extra' >> "$REPO/agents/good.md"
git -C "$REPO" add agents/good.md
for NON_INTEGRATION_CMD in \
  'git merge-base HEAD main' \
  'gh pr merge 42' \
  'git log --merges -n 3' \
  'git status --short # git merge origin/main' \
  'PY=python3; "$PY" -c "pass" # prepare_merge_review.py' \
  "git commit -m 'fix: block git merge on dirty worktree'" \
  "python3 - <<'EOF'
print('git merge origin/main && git rebase main')
EOF"; do
  OUTPUT="$FIXTURE/non-integration.json"
  run_gate "$REPO" "$NON_INTEGRATION_CMD" "$OUTPUT"
  assert_allow "dirty worktree ignores non-integration command: $NON_INTEGRATION_CMD" "$OUTPUT"
done

# Lifecycle recovery: sentinel disables dirty-worktree integration guard too
new_fixture
SENTINEL_OVERRIDE="$FIXTURE/disabled-merge"
: > "$SENTINEL_OVERRIDE"
printf '%s\n' 'dirty unstaged' >> "$REPO/README.md"
OUTPUT="$FIXTURE/sentinel-merge.json"
run_gate "$REPO" 'git merge origin/main' "$OUTPUT"
[ "$GATE_STATUS" -eq 0 ] && grep -q 'disabled by' "$OUTPUT"
check 'recovery: sentinel allows dirty-worktree git merge and says so' $?

# Strict --only commit isolation: validates HEAD + named literal files without touching shared .git/index
# 1. Known-good controlled --only commit succeeds even while foreign session stages an invalid controlled file
new_fixture
printf '%s\n' '---' 'name: demo' '---' 'subagent_type: missing-agent' > "$REPO/.claude/skills/demo/SKILL.md"
git -C "$REPO" add .claude/skills/demo/SKILL.md
printf '%s\n' 'extra valid line' >> "$REPO/agents/good.md"
OUTPUT="$FIXTURE/only-good-with-foreign-staged.json"
run_gate "$REPO" "git commit --only -m 'valid only commit' -- agents/good.md" "$OUTPUT"
assert_allow 'strict --only controlled commit allows while foreign invalid file sits staged' "$OUTPUT"
if git -C "$REPO" commit --only -qm 'valid only commit' -- agents/good.md; then
  COMMITTED_ONLY=$(git -C "$REPO" show --name-only --format= HEAD)
  STAGED_AFTER=$(git -C "$REPO" diff --cached --name-only)
  if [ "$COMMITTED_ONLY" = "agents/good.md" ] && [ "$STAGED_AFTER" = ".claude/skills/demo/SKILL.md" ]; then
    check 'strict --only commits exact file and leaves foreign staged file untouched' 0
  else
    check 'strict --only commits exact file and leaves foreign staged file untouched' 1
  fi
else
  check 'strict --only commits exact file and leaves foreign staged file untouched' 1
fi

# 2. Known-good uncontrolled --only commit succeeds even while foreign session stages an invalid controlled file
new_fixture
printf '%s\n' '---' 'name: demo' '---' 'subagent_type: missing-agent' > "$REPO/.claude/skills/demo/SKILL.md"
git -C "$REPO" add .claude/skills/demo/SKILL.md
printf '%s\n' 'doc update' >> "$REPO/README.md"
OUTPUT="$FIXTURE/only-uncontrolled-with-foreign.json"
run_gate "$REPO" "git commit --only -m 'readme only' -- README.md" "$OUTPUT"
assert_allow 'strict --only uncontrolled commit ignores foreign staged invalid controlled file' "$OUTPUT"

# 3. Known-bad: --only removing gate registration in settings.json denies
new_fixture
printf '%s\n' '{"permissions":{"allow":["Agent(removed)"]}}' > "$REPO/settings.json"
OUTPUT="$FIXTURE/only-settings-unreg.json"
run_gate "$REPO" "git commit --only -m 'drop gate' -- settings.json" "$OUTPUT"
assert_denial_reason 'strict --only removing gate registration from settings.json denies' "$OUTPUT" 'registration is missing'

# 4. Evasion guard: --only naming a locked surface still denies and forces permit flow
new_fixture
mkdir -p "$REPO/hooks"
printf '%s\n' '#!/usr/bin/env bash' 'exit 0' > "$REPO/hooks/agent-contract-validator-gate.sh"
git -C "$REPO" add hooks/agent-contract-validator-gate.sh
git -C "$REPO" commit -qm 'add locked hook'
printf '%s\n' '# edited' >> "$REPO/hooks/agent-contract-validator-gate.sh"
OUTPUT="$FIXTURE/only-locked.json"
run_gate "$REPO" "git commit --only -m 'bypass locked' -- hooks/agent-contract-validator-gate.sh" "$OUTPUT"
assert_denial_reason 'strict --only refuses locked surface to preserve permit flow' "$OUTPUT" 'locked surface'

# 5. Evasion guard: directory, glob, magic, --amend, and bare non---only pathspecs still deny
new_fixture
printf '%s\n' 'extra' >> "$REPO/agents/good.md"
OUTPUT="$FIXTURE/only-dir.json"
run_gate "$REPO" "git commit --only -m 'dir' -- agents" "$OUTPUT"
assert_denial_reason 'strict --only denies directory pathspec' "$OUTPUT" 'directory pathspec'
OUTPUT="$FIXTURE/only-magic.json"
run_gate "$REPO" "git commit --only -m 'magic' -- ':(glob)agents/*'" "$OUTPUT"
assert_denial_reason 'strict --only denies pathspec magic' "$OUTPUT" 'pathspec magic'
OUTPUT="$FIXTURE/only-amend.json"
run_gate "$REPO" "git commit --only --amend -m 'amend' -- agents/good.md" "$OUTPUT"
assert_denial_reason 'strict --only combined with --amend falls back to fail-closed denial' "$OUTPUT" 'post-add'

# 6. Boundary: new controlled file via intent-to-add (-N) validated accurately (good allows, bad denies)
new_fixture
printf '%s\n' '---' 'name: fresh' 'tools: [Read]' '---' > "$REPO/agents/fresh.md"
git -C "$REPO" add --intent-to-add agents/fresh.md
OUTPUT="$FIXTURE/only-new-good.json"
run_gate "$REPO" "git commit --only -m 'add fresh agent' -- agents/fresh.md" "$OUTPUT"
assert_allow 'strict --only allows valid new controlled file after intent-to-add' "$OUTPUT"
printf '%s\n' '---' 'name: bad-fresh' 'model: unsupported' '---' > "$REPO/agents/bad-fresh.md"
git -C "$REPO" add --intent-to-add agents/bad-fresh.md
OUTPUT="$FIXTURE/only-new-bad.json"
run_gate "$REPO" "git commit --only -m 'add bad fresh agent' -- agents/bad-fresh.md" "$OUTPUT"
assert_deny 'strict --only denies invalid new controlled file after intent-to-add' "$OUTPUT"

# 7. Boundary: relative path from nested cwd resolves against cwd, not repo root
new_fixture
printf '%s\n' '---' 'name: demo' '---' 'subagent_type: missing-agent' > "$REPO/.claude/skills/demo/SKILL.md"
OUTPUT="$FIXTURE/only-nested-cwd-bad.json"
run_gate "$REPO/.claude/skills/demo" "git commit --only -m 'nested bad' -- SKILL.md" "$OUTPUT"
assert_validator_diagnostic 'strict --only resolves relative path from nested cwd and denies invalid contract' "$OUTPUT" UNKNOWN_AGENT_REFERENCE

# 8. P1-1 regression: file-to-directory replacement that implicitly deletes a locked parent file denies
new_fixture
mkdir -p "$REPO/hooks"
printf '%s\n' '#!/usr/bin/env bash' 'exit 0' > "$REPO/hooks/T2-routing-gate.sh"
git -C "$REPO" add hooks/T2-routing-gate.sh
git -C "$REPO" commit -qm 'add locked hook'
rm "$REPO/hooks/T2-routing-gate.sh"
mkdir -p "$REPO/hooks/T2-routing-gate.sh"
printf '%s\n' 'child' > "$REPO/hooks/T2-routing-gate.sh/child.txt"
OUTPUT="$FIXTURE/only-file-to-dir-locked.json"
run_gate "$REPO" "git commit --only -m 'replace locked file with dir' -- hooks/T2-routing-gate.sh/child.txt" "$OUTPUT"
assert_denial_reason 'strict --only denies file-to-dir replacement that deletes locked parent' "$OUTPUT" 'locked surface'

# 9. P1-2 regression: compound command mutating working tree before --only commit fails closed
new_fixture
printf '%s\n' 'extra' >> "$REPO/agents/good.md"
OUTPUT="$FIXTURE/only-compound-write.json"
run_gate "$REPO" "printf 'bad' > .claude/skills/demo/SKILL.md && git commit --only -m 'compound' -- .claude/skills/demo/SKILL.md" "$OUTPUT"
assert_denial_reason 'compound write before --only commit falls back to fail-closed denial' "$OUTPUT" 'post-add'

# 10. P1-3 regression: --only naming a path that already has a staged version in shared index denies
new_fixture
printf '%s\n' 'staged version' >> "$REPO/agents/good.md"
git -C "$REPO" add agents/good.md
printf '%s\n' 'worktree version' >> "$REPO/agents/good.md"
OUTPUT="$FIXTURE/only-same-path-staged.json"
run_gate "$REPO" "git commit --only -m 'clobber staged' -- agents/good.md" "$OUTPUT"
assert_denial_reason 'strict --only denies overwriting a path already staged in shared index' "$OUTPUT" 'already staged in shared index'

# 11. P1-4 regression: skills/*/friction-log.md prose citing retired agent name is ignored by validator
new_fixture
mkdir -p "$REPO/skills/demo"
printf '%s\n' '- 2026-11-20 legacy note referencing `subagent_type: retired-agent`' > "$REPO/skills/demo/friction-log.md"
git -C "$REPO" add skills/demo/friction-log.md
OUTPUT="$FIXTURE/friction-log-exempt.json"
run_gate "$REPO" "git commit -m 'log friction'" "$OUTPUT"
assert_allow 'validator ignores skills/*/friction-log.md prose references to retired agents' "$OUTPUT"

# 12. Untracked .claude.json MCP registry in global config root is visible when validating settings.json
new_fixture
printf '%s\n' '{"mcpServers":{"live_demo":{"command":"echo","args":["ok"]}}}' > "$REPO/.claude.json"
printf '%s\n' '{"permissions":{"allow":["mcp__live_demo__ping"]},"hooks":{"PreToolUse":[{"matcher":"Bash","hooks":[{"type":"command","command":"~/.claude/hooks/agent-contract-validator-gate.sh"}]}]}}' > "$REPO/settings.json"
git -C "$REPO" add settings.json
OUTPUT="$FIXTURE/mcp-untracked-staged-good.json"
run_gate "$REPO" "git commit -m 'allow live_demo mcp tool'" "$OUTPUT"
assert_allow 'staged settings.json referencing MCP server in untracked global .claude.json allows' "$OUTPUT"
git -C "$REPO" reset -q HEAD -- settings.json
OUTPUT="$FIXTURE/mcp-untracked-only-good.json"
run_gate "$REPO" "git commit --only -m 'only allow live_demo' -- settings.json" "$OUTPUT"
assert_allow 'strict --only settings.json referencing MCP server in untracked global .claude.json allows' "$OUTPUT"
printf '%s\n' '{"permissions":{"allow":["mcp__ghost_server__ping"]},"hooks":{"PreToolUse":[{"matcher":"Bash","hooks":[{"type":"command","command":"~/.claude/hooks/agent-contract-validator-gate.sh"}]}]}}' > "$REPO/settings.json"
git -C "$REPO" add settings.json
OUTPUT="$FIXTURE/mcp-untracked-bad.json"
run_gate "$REPO" "git commit -m 'allow unknown mcp tool'" "$OUTPUT"
assert_validator_diagnostic 'staged settings.json referencing undefined MCP server still denies UNKNOWN_MCP_TOOL' "$OUTPUT" UNKNOWN_MCP_TOOL

printf 'PASS=%s FAIL=%s\n' "$PASS" "$FAIL"
if [ "$FAIL" -eq 0 ]; then
  printf '%s\n' 'AGENT_CONTRACT_GATE_TESTS_PASS'
fi
[ "$FAIL" -eq 0 ]
