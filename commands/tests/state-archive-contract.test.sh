#!/usr/bin/env bash
set -uo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
COMMAND="${STATE_ARCHIVE_COMMAND:-$ROOT/commands/state-archive.md}"
MARKER='<!-- 本檔在契約測試底下：bash ~/.claude/commands/tests/state-archive-contract.test.sh -->'
POINTER='> 帳本生命週期：規則見 `~/.claude/references/ledger-lifecycle.md`；門檻以 `~/.claude/scripts/ledger-lifecycle/registry.json` 為準。'
TMP=$(mktemp -d)
SCRIPT="$TMP/preflight.sh"
PASS=0
FAIL=0
RUN_RC=0
trap 'rm -rf "$TMP"' EXIT

check() {
  local name="$1"
  shift
  if "$@"; then
    PASS=$((PASS + 1))
    printf '  ok   %s\n' "$name"
  else
    FAIL=$((FAIL + 1))
    printf '  FAIL %s\n' "$name"
  fi
}

has() {
  grep -qF -- "$2" "$1"
}

check_eq() {
  local name="$1"
  local expected="$2"
  local actual="$3"
  if [ "$expected" = "$actual" ]; then
    PASS=$((PASS + 1))
    printf '  ok   %s\n' "$name"
  else
    FAIL=$((FAIL + 1))
    printf '  FAIL %s expect=%s actual=%s\n' "$name" "$expected" "$actual"
  fi
}

check_state_unchanged() {
  cmp -s "$1" "$2"
}

contains() {
  grep -qF -- "$2" "$1"
}

line_of() {
  grep -nF -- "$2" "$1" | cut -d: -f1 | head -1
}

init_repo() {
  local repo="$1"
  local remote="$2"
  git init -q -b main "$repo"
  git -C "$repo" config user.email test@example.com
  git -C "$repo" config user.name test
  mkdir -p "$repo/docs/owner" "$repo/openspec/decisions"
  printf '%s\n' 'STATE-SENTINEL' > "$repo/docs/owner/STATE.md"
  printf '%s\n' '# base' > "$repo/openspec/decisions/0001-base.md"
  printf '%s\n' '---' 'superseded_by: 9999' '---' 'legacy' > "$repo/openspec/decisions/0009-legacy.md"
  git -C "$repo" add .
  git -C "$repo" commit -qm base
  git init -q --bare "$remote"
  git -C "$repo" remote add origin "$remote"
  git -C "$repo" push -q -u origin main
  git -C "$repo" fetch -q origin main
  git -C "$repo" symbolic-ref refs/remotes/origin/HEAD refs/remotes/origin/main
  git -C "$repo" switch -q -c feature
}

prepare_changed_repo() {
  local repo="$1"
  local remote="$2"
  init_repo "$repo" "$remote"
  printf '%s\n' '# changed' >> "$repo/openspec/decisions/0001-base.md"
  git -C "$repo" add openspec/decisions/0001-base.md
  git -C "$repo" commit -qm changed
}

install_checker() {
  local home="$1"
  mkdir -p "$home/.claude/skills/domain-modeling/scripts"
  printf '%s\n' \
    '#!/usr/bin/env bash' \
    'printf "%s\\n" "$@" > "$CHECKER_LOG"' \
    'case "${CHECKER_MODE:-real}" in' \
    '  exit1) exit 1 ;;' \
    '  exit2) exit 2 ;;' \
    'esac' \
    'exec "$REAL_CHECKER" "$@"' \
    > "$home/.claude/skills/domain-modeling/scripts/check-decisions"
  chmod +x "$home/.claude/skills/domain-modeling/scripts/check-decisions"
}

run_script() {
  local repo="$1"
  local home="$2"
  local output="$3"
  local mode="$4"
  local log="$repo/checker.log"
  rm -f "$log"
  if (cd "$repo" && HOME="$home" CHECKER_LOG="$log" CHECKER_MODE="$mode" REAL_CHECKER="$ROOT/skills/domain-modeling/scripts/check-decisions" /bin/bash "$SCRIPT" > "$output" 2>&1); then
    RUN_RC=0
  else
    RUN_RC=$?
  fi
}

check "契約 marker" has "$COMMAND" "$MARKER"
check "ledger pointer" has "$COMMAND" "$POINTER"
check "preflight 是編號步驟" has "$COMMAND" "1.5. **ADR lifecycle preflight"
check "preflight 僅適用既有 STATE" has "$COMMAND" '只在既有 `docs/owner/STATE.md` 存在且 Read 成功時執行'
check "preflight 解析 remote default ref" has "$COMMAND" "symbolic-ref --quiet --short refs/remotes/origin/HEAD"
check "preflight 計算 merge-base" has "$COMMAND" "merge-base"
check "preflight disables fsmonitor" has "$COMMAND" "core.fsmonitor=false"
check "preflight binds worktree" has "$COMMAND" '--work-tree="$ROOT"'
check "preflight clears Git env overrides" has "$COMMAND" "env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE"
check "preflight combines committed and staged" has "$COMMAND" "collect_diff indexed"
check "preflight 收集 unstaged" has "$COMMAND" "collect_diff unstaged"
check "preflight 收集 untracked including ignored" has "$COMMAND" "ls-files --others -z"
check "preflight 偵測 rename/delete" has "$COMMAND" "numbered ADR rename/delete"
check "preflight 缺 checker fail closed" has "$COMMAND" "checker executable missing"
check "preflight checker failure fail closed" has "$COMMAND" "checker exit"
check "preflight BLOCKED 保留 STATE" has "$COMMAND" '保留 `docs/owner/STATE.md` bytes 原樣'
check "preflight 成功才接 Step 2" has "$COMMAND" "才接 **Step 2**"
STEP1_LINE=$(line_of "$COMMAND" '1. **Read** `docs/owner/STATE.md`')
PREFLIGHT_LINE=$(line_of "$COMMAND" "1.5. **ADR lifecycle preflight")
STEP2_LINE=$(line_of "$COMMAND" "2. **逐項分類 + 提議 promote 目標**")
PROMOTE_LINE=$(line_of "$COMMAND" "OpenSpec target：Read")
RESET_LINE=$(line_of "$COMMAND" '顯式 reset `docs/owner/STATE.md`')
CLEANUP_LINE=$(line_of "$COMMAND" "清理 worktree")
check "Step 1 指向 preflight" bash -c "test -n '$STEP1_LINE' -a -n '$PREFLIGHT_LINE' -a '$STEP1_LINE' -lt '$PREFLIGHT_LINE'"
check "preflight 早於所有 durable mutation" bash -c "test -n '$PREFLIGHT_LINE' -a -n '$PROMOTE_LINE' -a -n '$RESET_LINE' -a -n '$CLEANUP_LINE' && test '$PREFLIGHT_LINE' -lt '$PROMOTE_LINE' -a '$PREFLIGHT_LINE' -lt '$RESET_LINE' -a '$PREFLIGHT_LINE' -lt '$CLEANUP_LINE'"

SCRIPT_READY=1
if ! python3 - "$COMMAND" "$SCRIPT" <<'PY'
from pathlib import Path
import sys

lines = Path(sys.argv[1]).read_text().splitlines()
start = lines.index('STATE_ARCHIVE_PREFLIGHT_SCRIPT=1')
if lines[start - 1] != '```bash':
  raise SystemExit('preflight script fence missing')
end = next(i for i in range(start + 1, len(lines)) if lines[i] == '```')
Path(sys.argv[2]).write_text('\n'.join(lines[start:end]) + '\n')
PY
then
  SCRIPT_READY=0
fi
check_eq "preflight script extracted" "1" "$SCRIPT_READY"

if [ "$SCRIPT_READY" -eq 1 ]; then
  REPO="$TMP/all-sources"
  REMOTE="$TMP/all-sources.remote"
  HOME_FIXTURE="$TMP/all-home"
  OUTPUT="$TMP/all-output"
  init_repo "$REPO" "$REMOTE"
  printf '%s\n' '# committed modification' >> "$REPO/openspec/decisions/0001-base.md"
  printf '%s\n' '# committed addition' > "$REPO/openspec/decisions/0002-committed.md"
  git -C "$REPO" add openspec/decisions/0001-base.md openspec/decisions/0002-committed.md
  git -C "$REPO" commit -qm feature
  printf '%s\n' '# staged modification' >> "$REPO/openspec/decisions/0001-base.md"
  git -C "$REPO" add openspec/decisions/0001-base.md
  printf '%s\n' '# unstaged modification' >> "$REPO/openspec/decisions/0002-committed.md"
  printf '%s\n' '# untracked addition' > "$REPO/openspec/decisions/0003-untracked.md"
  install_checker "$HOME_FIXTURE"
  cp "$REPO/docs/owner/STATE.md" "$REPO/docs/owner/STATE.before"
  run_script "$REPO" "$HOME_FIXTURE" "$OUTPUT" real
  check_eq "all source states pass" "0" "$RUN_RC"
  check "all source states report pass" has "$OUTPUT" "STATE_ARCHIVE: ADR preflight PASS"
  REPO_CANONICAL=$(cd "$REPO" && pwd -P)
  printf '%s\n' \
    "$REPO_CANONICAL/openspec/decisions" \
    "$REPO_CANONICAL/openspec/decisions/0001-base.md" \
    "$REPO_CANONICAL/openspec/decisions/0002-committed.md" \
    "$REPO_CANONICAL/openspec/decisions/0003-untracked.md" > "$TMP/expected-args"
  sort "$TMP/expected-args" > "$TMP/expected-args.sorted"
  sort "$REPO/checker.log" > "$TMP/checker-args.sorted"
  check "checker receives only changed numbered sources" cmp -s "$TMP/expected-args.sorted" "$TMP/checker-args.sorted"
  check "all source states preserve STATE bytes" check_state_unchanged "$REPO/docs/owner/STATE.md" "$REPO/docs/owner/STATE.before"

  NO_CHANGE_REPO="$TMP/no-change"
  NO_CHANGE_REMOTE="$TMP/no-change.remote"
  NO_CHANGE_HOME="$TMP/no-change-home"
  NO_CHANGE_OUTPUT="$TMP/no-change-output"
  init_repo "$NO_CHANGE_REPO" "$NO_CHANGE_REMOTE"
  install_checker "$NO_CHANGE_HOME"
  cp "$NO_CHANGE_REPO/docs/owner/STATE.md" "$NO_CHANGE_REPO/docs/owner/STATE.before"
  run_script "$NO_CHANGE_REPO" "$NO_CHANGE_HOME" "$NO_CHANGE_OUTPUT" real
  check_eq "no decision changes continue" "0" "$RUN_RC"
  check "no decision changes skip checker" contains "$NO_CHANGE_OUTPUT" "STATE_ARCHIVE: no decision changes; checker skipped"
  check "unchanged legacy violation does not block" test ! -e "$NO_CHANGE_REPO/checker.log"
  check "no decision changes preserve STATE bytes" check_state_unchanged "$NO_CHANGE_REPO/docs/owner/STATE.md" "$NO_CHANGE_REPO/docs/owner/STATE.before"

  MISSING_STATE_REPO="$TMP/missing-state"
  MISSING_STATE_REMOTE="$TMP/missing-state.remote"
  MISSING_STATE_HOME="$TMP/missing-state-home"
  MISSING_STATE_OUTPUT="$TMP/missing-state-output"
  init_repo "$MISSING_STATE_REPO" "$MISSING_STATE_REMOTE"
  rm "$MISSING_STATE_REPO/docs/owner/STATE.md"
  install_checker "$MISSING_STATE_HOME"
  run_script "$MISSING_STATE_REPO" "$MISSING_STATE_HOME" "$MISSING_STATE_OUTPUT" real
  check_eq "missing STATE is not applicable" "0" "$RUN_RC"
  check "missing STATE reports not applicable" contains "$MISSING_STATE_OUTPUT" "STATE_ARCHIVE: NOT_APPLICABLE missing docs/owner/STATE.md"
  check "missing STATE skips checker" test ! -e "$MISSING_STATE_REPO/checker.log"

  RENAME_REPO="$TMP/rename"
  RENAME_REMOTE="$TMP/rename.remote"
  RENAME_HOME="$TMP/rename-home"
  RENAME_OUTPUT="$TMP/rename-output"
  prepare_changed_repo "$RENAME_REPO" "$RENAME_REMOTE"
  git -C "$RENAME_REPO" mv openspec/decisions/0001-base.md openspec/decisions/0001-renamed.md
  git -C "$RENAME_REPO" commit -qm rename
  install_checker "$RENAME_HOME"
  cp "$RENAME_REPO/docs/owner/STATE.md" "$RENAME_REPO/docs/owner/STATE.before"
  run_script "$RENAME_REPO" "$RENAME_HOME" "$RENAME_OUTPUT" real
  check_eq "numbered rename blocks" "1" "$RUN_RC"
  check "numbered rename reports BLOCKED" contains "$RENAME_OUTPUT" "STATE_ARCHIVE: BLOCKED numbered ADR rename/delete"
  check "numbered rename skips checker" test ! -e "$RENAME_REPO/checker.log"
  check "numbered rename preserves STATE bytes" check_state_unchanged "$RENAME_REPO/docs/owner/STATE.md" "$RENAME_REPO/docs/owner/STATE.before"

  DELETE_REPO="$TMP/delete"
  DELETE_REMOTE="$TMP/delete.remote"
  DELETE_HOME="$TMP/delete-home"
  DELETE_OUTPUT="$TMP/delete-output"
  prepare_changed_repo "$DELETE_REPO" "$DELETE_REMOTE"
  git -C "$DELETE_REPO" rm -q openspec/decisions/0001-base.md
  git -C "$DELETE_REPO" commit -qm delete
  install_checker "$DELETE_HOME"
  cp "$DELETE_REPO/docs/owner/STATE.md" "$DELETE_REPO/docs/owner/STATE.before"
  run_script "$DELETE_REPO" "$DELETE_HOME" "$DELETE_OUTPUT" real
  check_eq "numbered delete blocks" "1" "$RUN_RC"
  check "numbered delete reports BLOCKED" contains "$DELETE_OUTPUT" "STATE_ARCHIVE: BLOCKED numbered ADR rename/delete"
  check "numbered delete skips checker" test ! -e "$DELETE_REPO/checker.log"
  check "numbered delete preserves STATE bytes" check_state_unchanged "$DELETE_REPO/docs/owner/STATE.md" "$DELETE_REPO/docs/owner/STATE.before"

  STAGED_RENAME_REPO="$TMP/staged-rename"
  STAGED_RENAME_REMOTE="$TMP/staged-rename.remote"
  STAGED_RENAME_HOME="$TMP/staged-rename-home"
  STAGED_RENAME_OUTPUT="$TMP/staged-rename-output"
  prepare_changed_repo "$STAGED_RENAME_REPO" "$STAGED_RENAME_REMOTE"
  git -C "$STAGED_RENAME_REPO" mv openspec/decisions/0001-base.md openspec/decisions/0001-staged-renamed.md
  install_checker "$STAGED_RENAME_HOME"
  cp "$STAGED_RENAME_REPO/docs/owner/STATE.md" "$STAGED_RENAME_REPO/docs/owner/STATE.before"
  run_script "$STAGED_RENAME_REPO" "$STAGED_RENAME_HOME" "$STAGED_RENAME_OUTPUT" real
  check_eq "staged numbered rename blocks" "1" "$RUN_RC"
  check "staged numbered rename reports BLOCKED" contains "$STAGED_RENAME_OUTPUT" "STATE_ARCHIVE: BLOCKED numbered ADR rename/delete"
  check "staged numbered rename skips checker" test ! -e "$STAGED_RENAME_REPO/checker.log"
  check "staged numbered rename preserves STATE bytes" check_state_unchanged "$STAGED_RENAME_REPO/docs/owner/STATE.md" "$STAGED_RENAME_REPO/docs/owner/STATE.before"

  UNSTAGED_DELETE_REPO="$TMP/unstaged-delete"
  UNSTAGED_DELETE_REMOTE="$TMP/unstaged-delete.remote"
  UNSTAGED_DELETE_HOME="$TMP/unstaged-delete-home"
  UNSTAGED_DELETE_OUTPUT="$TMP/unstaged-delete-output"
  prepare_changed_repo "$UNSTAGED_DELETE_REPO" "$UNSTAGED_DELETE_REMOTE"
  rm "$UNSTAGED_DELETE_REPO/openspec/decisions/0001-base.md"
  install_checker "$UNSTAGED_DELETE_HOME"
  cp "$UNSTAGED_DELETE_REPO/docs/owner/STATE.md" "$UNSTAGED_DELETE_REPO/docs/owner/STATE.before"
  run_script "$UNSTAGED_DELETE_REPO" "$UNSTAGED_DELETE_HOME" "$UNSTAGED_DELETE_OUTPUT" real
  check_eq "unstaged numbered delete blocks" "1" "$RUN_RC"
  check "unstaged numbered delete reports BLOCKED" contains "$UNSTAGED_DELETE_OUTPUT" "STATE_ARCHIVE: BLOCKED numbered ADR rename/delete"
  check "unstaged numbered delete skips checker" test ! -e "$UNSTAGED_DELETE_REPO/checker.log"
  check "unstaged numbered delete preserves STATE bytes" check_state_unchanged "$UNSTAGED_DELETE_REPO/docs/owner/STATE.md" "$UNSTAGED_DELETE_REPO/docs/owner/STATE.before"

  RESTORED_REPO="$TMP/restored-index"
  RESTORED_REMOTE="$TMP/restored-index.remote"
  RESTORED_HOME="$TMP/restored-index-home"
  RESTORED_OUTPUT="$TMP/restored-index-output"
  init_repo "$RESTORED_REPO" "$RESTORED_REMOTE"
  git -C "$RESTORED_REPO" mv openspec/decisions/0001-base.md openspec/decisions/0001-intermediate.md
  git -C "$RESTORED_REPO" commit -qm intermediate-rename
  git -C "$RESTORED_REPO" mv openspec/decisions/0001-intermediate.md openspec/decisions/0001-base.md
  install_checker "$RESTORED_HOME"
  cp "$RESTORED_REPO/docs/owner/STATE.md" "$RESTORED_REPO/docs/owner/STATE.before"
  run_script "$RESTORED_REPO" "$RESTORED_HOME" "$RESTORED_OUTPUT" real
  check_eq "staged restore of committed rename continues" "0" "$RUN_RC"
  check "staged restore skips checker" contains "$RESTORED_OUTPUT" "STATE_ARCHIVE: no decision changes; checker skipped"
  check "staged restore preserves STATE bytes" check_state_unchanged "$RESTORED_REPO/docs/owner/STATE.md" "$RESTORED_REPO/docs/owner/STATE.before"

  NO_BASE_REPO="$TMP/no-base"
  NO_BASE_REMOTE="$TMP/no-base.remote"
  NO_BASE_HOME="$TMP/no-base-home"
  NO_BASE_OUTPUT="$TMP/no-base-output"
  init_repo "$NO_BASE_REPO" "$NO_BASE_REMOTE"
  git -C "$NO_BASE_REPO" switch -q --orphan unrelated
  mkdir -p "$NO_BASE_REPO/docs/owner" "$NO_BASE_REPO/openspec/decisions"
  printf '%s\n' 'STATE-SENTINEL' > "$NO_BASE_REPO/docs/owner/STATE.md"
  printf '%s\n' '# unrelated' > "$NO_BASE_REPO/openspec/decisions/0001-unrelated.md"
  printf '%s\n' '# legacy' > "$NO_BASE_REPO/openspec/decisions/0009-legacy.md"
  git -C "$NO_BASE_REPO" add docs/owner/STATE.md openspec/decisions/0001-unrelated.md openspec/decisions/0009-legacy.md
  git -C "$NO_BASE_REPO" commit -qm unrelated
  install_checker "$NO_BASE_HOME"
  cp "$NO_BASE_REPO/docs/owner/STATE.md" "$NO_BASE_REPO/docs/owner/STATE.before"
  run_script "$NO_BASE_REPO" "$NO_BASE_HOME" "$NO_BASE_OUTPUT" real
  check_eq "no merge-base blocks" "1" "$RUN_RC"
  check "no merge-base reports BLOCKED" contains "$NO_BASE_OUTPUT" "STATE_ARCHIVE: BLOCKED merge-base unresolved"
  check "no merge-base skips checker" test ! -e "$NO_BASE_REPO/checker.log"
  check "no merge-base preserves STATE bytes" check_state_unchanged "$NO_BASE_REPO/docs/owner/STATE.md" "$NO_BASE_REPO/docs/owner/STATE.before"

  BASE_REPO="$TMP/unresolved-base"
  BASE_REMOTE="$TMP/unresolved-base.remote"
  BASE_HOME="$TMP/unresolved-base-home"
  BASE_OUTPUT="$TMP/unresolved-base-output"
  prepare_changed_repo "$BASE_REPO" "$BASE_REMOTE"
  git -C "$BASE_REMOTE" symbolic-ref HEAD refs/heads/missing
  git -C "$BASE_REPO" update-ref -d refs/remotes/origin/HEAD
  install_checker "$BASE_HOME"
  cp "$BASE_REPO/docs/owner/STATE.md" "$BASE_REPO/docs/owner/STATE.before"
  run_script "$BASE_REPO" "$BASE_HOME" "$BASE_OUTPUT" real
  check_eq "unresolved remote base blocks" "1" "$RUN_RC"
  check "unresolved remote base reports BLOCKED" contains "$BASE_OUTPUT" "STATE_ARCHIVE: BLOCKED remote default ref unresolved"
  check "unresolved remote base skips checker" test ! -e "$BASE_REPO/checker.log"
  check "unresolved remote base preserves STATE bytes" check_state_unchanged "$BASE_REPO/docs/owner/STATE.md" "$BASE_REPO/docs/owner/STATE.before"

  MISSING_CHECKER_REPO="$TMP/missing-checker"
  MISSING_CHECKER_REMOTE="$TMP/missing-checker.remote"
  MISSING_CHECKER_HOME="$TMP/missing-checker-home"
  MISSING_CHECKER_OUTPUT="$TMP/missing-checker-output"
  prepare_changed_repo "$MISSING_CHECKER_REPO" "$MISSING_CHECKER_REMOTE"
  install_checker "$MISSING_CHECKER_HOME"
  chmod 644 "$MISSING_CHECKER_HOME/.claude/skills/domain-modeling/scripts/check-decisions"
  cp "$MISSING_CHECKER_REPO/docs/owner/STATE.md" "$MISSING_CHECKER_REPO/docs/owner/STATE.before"
  run_script "$MISSING_CHECKER_REPO" "$MISSING_CHECKER_HOME" "$MISSING_CHECKER_OUTPUT" real
  check_eq "missing checker blocks" "1" "$RUN_RC"
  check "missing checker reports BLOCKED" contains "$MISSING_CHECKER_OUTPUT" "STATE_ARCHIVE: BLOCKED checker executable missing"
  check "missing checker preserves STATE bytes" check_state_unchanged "$MISSING_CHECKER_REPO/docs/owner/STATE.md" "$MISSING_CHECKER_REPO/docs/owner/STATE.before"

  for CHECKER_MODE_CASE in exit1 exit2; do
    CHECKER_REPO="$TMP/checker-$CHECKER_MODE_CASE"
    CHECKER_REMOTE="$TMP/checker-$CHECKER_MODE_CASE.remote"
    CHECKER_HOME="$TMP/checker-$CHECKER_MODE_CASE-home"
    CHECKER_OUTPUT="$TMP/checker-$CHECKER_MODE_CASE-output"
    prepare_changed_repo "$CHECKER_REPO" "$CHECKER_REMOTE"
    install_checker "$CHECKER_HOME"
    cp "$CHECKER_REPO/docs/owner/STATE.md" "$CHECKER_REPO/docs/owner/STATE.before"
    run_script "$CHECKER_REPO" "$CHECKER_HOME" "$CHECKER_OUTPUT" "$CHECKER_MODE_CASE"
    check_eq "checker $CHECKER_MODE_CASE blocks" "1" "$RUN_RC"
    check "checker $CHECKER_MODE_CASE reports BLOCKED" contains "$CHECKER_OUTPUT" "STATE_ARCHIVE: BLOCKED checker exit ${CHECKER_MODE_CASE#exit}"
    check "checker $CHECKER_MODE_CASE preserves STATE bytes" check_state_unchanged "$CHECKER_REPO/docs/owner/STATE.md" "$CHECKER_REPO/docs/owner/STATE.before"
  done

  CORE_WORKTREE_REPO="$TMP/core-worktree"
  CORE_WORKTREE_REMOTE="$TMP/core-worktree.remote"
  CORE_WORKTREE_HOME="$TMP/core-worktree-home"
  CORE_WORKTREE_OUTPUT="$TMP/core-worktree-output"
  CORE_WORKTREE_ALT="$TMP/core-worktree-alt"
  init_repo "$CORE_WORKTREE_REPO" "$CORE_WORKTREE_REMOTE"
  mkdir -p "$CORE_WORKTREE_ALT"
  git -C "$CORE_WORKTREE_REPO" --work-tree="$CORE_WORKTREE_ALT" checkout -q -f HEAD -- .
  git -C "$CORE_WORKTREE_REPO" config core.worktree "$CORE_WORKTREE_ALT"
  printf '%s\n' '---' 'superseded_by: 9999' '---' '# Invalid root' > "$CORE_WORKTREE_REPO/openspec/decisions/0001-base.md"
  install_checker "$CORE_WORKTREE_HOME"
  cp "$CORE_WORKTREE_REPO/docs/owner/STATE.md" "$CORE_WORKTREE_REPO/docs/owner/STATE.before"
  run_script "$CORE_WORKTREE_REPO" "$CORE_WORKTREE_HOME" "$CORE_WORKTREE_OUTPUT" real
  check_eq "core.worktree override still checks ROOT" "1" "$RUN_RC"
  check "core.worktree fixture reaches checker" contains "$CORE_WORKTREE_OUTPUT" "STATE_ARCHIVE: BLOCKED checker exit 1"
  check "core.worktree fixture preserves STATE bytes" check_state_unchanged "$CORE_WORKTREE_REPO/docs/owner/STATE.md" "$CORE_WORKTREE_REPO/docs/owner/STATE.before"

  FSMONITOR_REPO="$TMP/fsmonitor"
  FSMONITOR_REMOTE="$TMP/fsmonitor.remote"
  FSMONITOR_HOME="$TMP/fsmonitor-home"
  FSMONITOR_OUTPUT="$TMP/fsmonitor-output"
  init_repo "$FSMONITOR_REPO" "$FSMONITOR_REMOTE"
  FSMONITOR_MARKER="$FSMONITOR_REPO/fsmonitor-ran"
  FSMONITOR_HOOK="$FSMONITOR_REPO/fsmonitor-hook"
  printf '%s\n' '#!/usr/bin/env bash' "printf '%s\\n' ran > '$FSMONITOR_MARKER'" 'exit 0' > "$FSMONITOR_HOOK"
  chmod +x "$FSMONITOR_HOOK"
  git -C "$FSMONITOR_REPO" config core.fsmonitor "$FSMONITOR_HOOK"
  printf '%s\n' '---' 'superseded_by: 9999' '---' '# Invalid' > "$FSMONITOR_REPO/openspec/decisions/0002-invalid.md"
  install_checker "$FSMONITOR_HOME"
  cp "$FSMONITOR_REPO/docs/owner/STATE.md" "$FSMONITOR_REPO/docs/owner/STATE.before"
  run_script "$FSMONITOR_REPO" "$FSMONITOR_HOME" "$FSMONITOR_OUTPUT" real
  check_eq "fsmonitor fixture blocks on invalid ADR" "1" "$RUN_RC"
  check "fsmonitor hook is disabled" test ! -e "$FSMONITOR_MARKER"
  check "fsmonitor fixture reaches checker" contains "$FSMONITOR_OUTPUT" "STATE_ARCHIVE: BLOCKED checker exit 1"
  check "fsmonitor fixture preserves STATE bytes" check_state_unchanged "$FSMONITOR_REPO/docs/owner/STATE.md" "$FSMONITOR_REPO/docs/owner/STATE.before"

  IGNORED_REPO="$TMP/ignored-untracked"
  IGNORED_REMOTE="$TMP/ignored-untracked.remote"
  IGNORED_HOME="$TMP/ignored-untracked-home"
  IGNORED_OUTPUT="$TMP/ignored-untracked-output"
  init_repo "$IGNORED_REPO" "$IGNORED_REMOTE"
  printf '%s\n' 'openspec/decisions/0002-ignored.md' > "$IGNORED_REPO/.gitignore"
  printf '%s\n' '---' 'superseded_by: 9999' '---' '# Ignored' > "$IGNORED_REPO/openspec/decisions/0002-ignored.md"
  install_checker "$IGNORED_HOME"
  cp "$IGNORED_REPO/docs/owner/STATE.md" "$IGNORED_REPO/docs/owner/STATE.before"
  run_script "$IGNORED_REPO" "$IGNORED_HOME" "$IGNORED_OUTPUT" real
  check_eq "ignored untracked ADR blocks" "1" "$RUN_RC"
  check "ignored untracked ADR reaches checker" test -s "$IGNORED_REPO/checker.log"
  check "ignored untracked ADR reports checker failure" contains "$IGNORED_OUTPUT" "STATE_ARCHIVE: BLOCKED checker exit 1"
  check "ignored untracked ADR preserves STATE bytes" check_state_unchanged "$IGNORED_REPO/docs/owner/STATE.md" "$IGNORED_REPO/docs/owner/STATE.before"

  NESTED_REPO="$TMP/nested-path"
  NESTED_REMOTE="$TMP/nested-path.remote"
  NESTED_HOME="$TMP/nested-path-home"
  NESTED_OUTPUT="$TMP/nested-path-output"
  init_repo "$NESTED_REPO" "$NESTED_REMOTE"
  mkdir -p "$NESTED_REPO/openspec/decisions/0002-nested"
  printf '%s\n' '---' 'superseded_by: 9999' '---' '# Nested' > "$NESTED_REPO/openspec/decisions/0002-nested/child.md"
  install_checker "$NESTED_HOME"
  cp "$NESTED_REPO/docs/owner/STATE.md" "$NESTED_REPO/docs/owner/STATE.before"
  run_script "$NESTED_REPO" "$NESTED_HOME" "$NESTED_OUTPUT" real
  check_eq "nested path is ignored" "0" "$RUN_RC"
  check "nested path skips checker" test ! -e "$NESTED_REPO/checker.log"
  check "nested path reports no decision changes" contains "$NESTED_OUTPUT" "STATE_ARCHIVE: no decision changes; checker skipped"
  check "nested path preserves STATE bytes" check_state_unchanged "$NESTED_REPO/docs/owner/STATE.md" "$NESTED_REPO/docs/owner/STATE.before"

  QUOTED_REPO="$TMP/quoted-path"
  QUOTED_REMOTE="$TMP/quoted-path.remote"
  QUOTED_HOME="$TMP/quoted-path-home"
  QUOTED_OUTPUT="$TMP/quoted-path-output"
  init_repo "$QUOTED_REPO" "$QUOTED_REMOTE"
  QUOTED_PATH=$'openspec/decisions/0002-bad\tname.md'
  printf '%s\n' '---' 'superseded_by: 9999' '---' '# Quoted' > "$QUOTED_REPO/$QUOTED_PATH"
  git -C "$QUOTED_REPO" add "$QUOTED_PATH"
  git -C "$QUOTED_REPO" commit -qm quoted-path
  install_checker "$QUOTED_HOME"
  cp "$QUOTED_REPO/docs/owner/STATE.md" "$QUOTED_REPO/docs/owner/STATE.before"
  run_script "$QUOTED_REPO" "$QUOTED_HOME" "$QUOTED_OUTPUT" real
  check_eq "quoted numbered ADR blocks" "1" "$RUN_RC"
  check "quoted numbered ADR reaches checker" test -s "$QUOTED_REPO/checker.log"
  check "quoted numbered ADR reports checker failure" contains "$QUOTED_OUTPUT" "STATE_ARCHIVE: BLOCKED checker exit 1"
  check "quoted numbered ADR preserves STATE bytes" check_state_unchanged "$QUOTED_REPO/docs/owner/STATE.md" "$QUOTED_REPO/docs/owner/STATE.before"

  LAST_DELETE_REPO="$TMP/last-delete"
  LAST_DELETE_REMOTE="$TMP/last-delete.remote"
  LAST_DELETE_HOME="$TMP/last-delete-home"
  LAST_DELETE_OUTPUT="$TMP/last-delete-output"
  init_repo "$LAST_DELETE_REPO" "$LAST_DELETE_REMOTE"
  git -C "$LAST_DELETE_REPO" rm -q openspec/decisions/0001-base.md openspec/decisions/0009-legacy.md
  git -C "$LAST_DELETE_REPO" commit -qm delete-all-decisions
  install_checker "$LAST_DELETE_HOME"
  cp "$LAST_DELETE_REPO/docs/owner/STATE.md" "$LAST_DELETE_REPO/docs/owner/STATE.before"
  run_script "$LAST_DELETE_REPO" "$LAST_DELETE_HOME" "$LAST_DELETE_OUTPUT" real
  check_eq "last numbered ADR deletion blocks" "1" "$RUN_RC"
  check "last numbered ADR deletion reports BLOCKED" contains "$LAST_DELETE_OUTPUT" "STATE_ARCHIVE: BLOCKED numbered ADR rename/delete"
  check "last numbered ADR deletion skips checker" test ! -e "$LAST_DELETE_REPO/checker.log"
  check "last numbered ADR deletion preserves STATE bytes" check_state_unchanged "$LAST_DELETE_REPO/docs/owner/STATE.md" "$LAST_DELETE_REPO/docs/owner/STATE.before"

  DETECTION_REPO="$TMP/detection-failure"
  DETECTION_REMOTE="$TMP/detection-failure.remote"
  DETECTION_HOME="$TMP/detection-failure-home"
  DETECTION_OUTPUT="$TMP/detection-failure-output"
  prepare_changed_repo "$DETECTION_REPO" "$DETECTION_REMOTE"
  mv "$DETECTION_REPO/.git/index" "$DETECTION_REPO/.git/index.saved"
  mkdir "$DETECTION_REPO/.git/index"
  install_checker "$DETECTION_HOME"
  cp "$DETECTION_REPO/docs/owner/STATE.md" "$DETECTION_REPO/docs/owner/STATE.before"
  run_script "$DETECTION_REPO" "$DETECTION_HOME" "$DETECTION_OUTPUT" real
  check_eq "change-set detection failure blocks" "1" "$RUN_RC"
  check "change-set detection failure reports BLOCKED" contains "$DETECTION_OUTPUT" "STATE_ARCHIVE: BLOCKED change-set detection failure"
  check "change-set detection failure preserves STATE bytes" check_state_unchanged "$DETECTION_REPO/docs/owner/STATE.md" "$DETECTION_REPO/docs/owner/STATE.before"
else
  FAIL=$((FAIL + 1))
  printf '  FAIL dynamic preflight scenarios skipped\n'
fi

printf '\n%s PASS / %s FAIL\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
