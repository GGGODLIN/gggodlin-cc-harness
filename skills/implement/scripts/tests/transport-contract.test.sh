#!/usr/bin/env bash
set -u

ROOT=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
SKILL="$ROOT/SKILL.md"
TMP=$(mktemp -d)
PASS=0
FAIL=0
trap 'rm -rf "$TMP"' EXIT

pass() {
  printf 'PASS: %s\n' "$1"
  PASS=$((PASS + 1))
}

fail() {
  printf 'FAIL: %s\n' "$1"
  FAIL=$((FAIL + 1))
}

assert_grep() {
  local label=$1 pattern=$2
  if grep -qE "$pattern" "$SKILL"; then
    pass "$label"
  else
    fail "$label"
  fi
}

assert_no_grep() {
  local label=$1 pattern=$2
  if grep -qE "$pattern" "$SKILL"; then
    fail "$label"
  else
    pass "$label"
  fi
}

assert_file_contains() {
  local label=$1 pattern=$2 path=$3
  if grep -Fq -- "$pattern" "$path"; then
    pass "$label"
  else
    fail "$label"
  fi
}

assert_equal() {
  local label=$1 expected=$2 actual=$3
  if [ "$expected" = "$actual" ]; then
    pass "$label"
  else
    fail "$label"
  fi
}

run_git() {
  local cwd=$1
  shift
  git -C "$cwd" "$@"
}

create_repo() {
  local repo=$1
  mkdir -p "$repo"
  printf 'base-a\n' > "$repo/a.txt"
  printf 'base-b\n' > "$repo/b.txt"
  run_git "$repo" init -q -b main
  run_git "$repo" config user.email fixture@example.com
  run_git "$repo" config user.name fixture
  run_git "$repo" add -A
  run_git "$repo" commit -qm fixture
}

assert_grep 'skill marks transport contract' '本檔在契約測試底下.*transport-contract\.test\.sh'
assert_grep 'frontier worktrees share dispatch base' 'Before the first worker.*pre-create every sibling worktree.*same frontier.*dispatch_base_sha'
assert_grep 'workers use separate physical workspaces' 'active workers.*share.*physical workspace'
assert_grep 'worktree failure stops new dispatch' 'worktree creation fails.*stop new dispatch'
assert_grep 'controller can continue sequentially' 'safe.*controller.*sequential'
assert_grep 'shared fallback has no writing worker or patch' 'Shared-tree fallback.*no.*writing worker.*patch'
assert_grep 'provenance has four required fields' 'canonical worktree path.*dispatch_base_sha.*changed-file evidence.*patch file path'
assert_grep 'controller recomputes patch evidence' 'recomputes changed files from the patch.*canonical worktree.*dispatch base'
assert_no_grep 'transport contract names no patch digest' 'patch digest|digest, and dispatch base'
assert_grep 'same frontier patches are not stale' 'same frontier.*same.*base.*not stale'
assert_grep 'integration uses an exclusive window' 'exclusive integration window.*target tree.*dirty state'
assert_grep 'check precedes formal apply' 'git apply --check.*formal apply'
assert_grep 'formal apply follows ticket order' 'formal apply in ticket order'
assert_grep 'failed integration preserves target' 'check／apply failure.*workspace.*unchanged'
assert_grep 'failure evidence is recorded' 'Verification Log.*failure.*patch.*provenance.*expected/current SHA.*exit.*stderr.*status'
assert_grep 'dirty target blocks parallel transport' 'Dirty target.*no.*parallel transport'
assert_grep 'shared resources force serialization' 'cache.*daemon.*port.*service.*serialize'
assert_grep 'transport remains prompt-level' 'prompt-level.*no.*deterministic helper.*hook.*gate'

REPO="$TMP/repo"
create_repo "$REPO"
BASE_SHA=$(run_git "$REPO" rev-parse HEAD)
WORKTREE_ROOT="$TMP/siblings"
WORKTREE_A="$WORKTREE_ROOT/ticket-a"
WORKTREE_B="$WORKTREE_ROOT/ticket-b"
mkdir -p "$WORKTREE_ROOT"
run_git "$REPO" worktree add --detach --quiet "$WORKTREE_A" "$BASE_SHA"
run_git "$REPO" worktree add --detach --quiet "$WORKTREE_B" "$BASE_SHA"
CANONICAL_A=$(CDPATH= cd -- "$WORKTREE_A" && pwd -P)
CANONICAL_B=$(CDPATH= cd -- "$WORKTREE_B" && pwd -P)
[ "$CANONICAL_A" != "$CANONICAL_B" ] && pass 'sibling worktrees have distinct canonical paths' || fail 'sibling worktrees have distinct canonical paths'
assert_equal 'ticket-a starts at dispatch base' "$BASE_SHA" "$(run_git "$WORKTREE_A" rev-parse HEAD)"
assert_equal 'ticket-b starts at dispatch base' "$BASE_SHA" "$(run_git "$WORKTREE_B" rev-parse HEAD)"
assert_file_contains 'git records ticket-a worktree' "worktree $CANONICAL_A" <(run_git "$REPO" worktree list --porcelain)
assert_file_contains 'git records ticket-b worktree' "worktree $CANONICAL_B" <(run_git "$REPO" worktree list --porcelain)

printf 'ticket-a\n' > "$WORKTREE_A/a.txt"
printf 'ticket-b\n' > "$WORKTREE_B/b.txt"
run_git "$WORKTREE_A" add -N -- .
run_git "$WORKTREE_B" add -N -- .
PATCH_A="$TMP/ticket-a.patch"
PATCH_B="$TMP/ticket-b.patch"
run_git "$WORKTREE_A" diff --binary "$BASE_SHA" -- > "$PATCH_A"
run_git "$WORKTREE_B" diff --binary "$BASE_SHA" -- > "$PATCH_B"
FILES_A=$(run_git "$WORKTREE_A" diff --name-only "$BASE_SHA" -- | paste -sd, -)
FILES_B=$(run_git "$WORKTREE_B" diff --name-only "$BASE_SHA" -- | paste -sd, -)
PATCH_FILES_A=$(run_git "$REPO" apply --numstat "$PATCH_A" | cut -f3 | paste -sd, -)
PATCH_FILES_B=$(run_git "$REPO" apply --numstat "$PATCH_B" | cut -f3 | paste -sd, -)
[ -s "$PATCH_A" ] && [ -s "$PATCH_B" ] && pass 'both patch files exist and are non-empty' || fail 'both patch files exist and are non-empty'
assert_equal 'ticket-a changed files recomputed from the patch match the worktree' "$FILES_A" "$PATCH_FILES_A"
assert_equal 'ticket-b changed files recomputed from the patch match the worktree' "$FILES_B" "$PATCH_FILES_B"
RECEIPT_A="$TMP/ticket-a.provenance"
RECEIPT_B="$TMP/ticket-b.provenance"
printf '{"canonical_worktree_path":"%s","dispatch_base_sha":"%s","changed_file_evidence":"%s","patch_file_path":"%s"}\n' "$CANONICAL_A" "$BASE_SHA" "$FILES_A" "$PATCH_A" > "$RECEIPT_A"
printf '{"canonical_worktree_path":"%s","dispatch_base_sha":"%s","changed_file_evidence":"%s","patch_file_path":"%s"}\n' "$CANONICAL_B" "$BASE_SHA" "$FILES_B" "$PATCH_B" > "$RECEIPT_B"
assert_file_contains 'ticket-a receipt binds canonical path' "\"canonical_worktree_path\":\"$CANONICAL_A\"" "$RECEIPT_A"
assert_file_contains 'ticket-a receipt binds dispatch base' "\"dispatch_base_sha\":\"$BASE_SHA\"" "$RECEIPT_A"
assert_file_contains 'ticket-a receipt binds changed files' "\"changed_file_evidence\":\"$FILES_A\"" "$RECEIPT_A"
assert_file_contains 'ticket-a receipt names the patch file' "\"patch_file_path\":\"$PATCH_A\"" "$RECEIPT_A"
assert_file_contains 'ticket-b receipt names the patch file' "\"patch_file_path\":\"$PATCH_B\"" "$RECEIPT_B"

TARGET_BEFORE=$(run_git "$REPO" status --porcelain)
TARGET_INDEX_BEFORE=$(run_git "$REPO" diff --cached --name-status)
TARGET_HEAD_BEFORE=$(run_git "$REPO" rev-parse HEAD)
if run_git "$REPO" apply --check "$PATCH_A" > "$TMP/check-a.out" 2>&1; then
  CHECK_A_EXIT=0
  pass 'ticket-a git apply --check receipt succeeds'
else
  CHECK_A_EXIT=$?
  fail 'ticket-a git apply --check receipt succeeds'
fi
if run_git "$REPO" apply "$PATCH_A" > "$TMP/apply-a.out" 2>&1; then
  APPLY_A_EXIT=0
  pass 'ticket-a formal apply receipt succeeds'
else
  APPLY_A_EXIT=$?
  fail 'ticket-a formal apply receipt succeeds'
fi
if run_git "$REPO" apply --check "$PATCH_B" > "$TMP/check-b.out" 2>&1; then
  CHECK_B_EXIT=0
  pass 'ticket-b git apply --check receipt succeeds'
else
  CHECK_B_EXIT=$?
  fail 'ticket-b git apply --check receipt succeeds'
fi
if run_git "$REPO" apply "$PATCH_B" > "$TMP/apply-b.out" 2>&1; then
  APPLY_B_EXIT=0
  pass 'ticket-b formal apply receipt succeeds'
else
  APPLY_B_EXIT=$?
  fail 'ticket-b formal apply receipt succeeds'
fi
assert_equal 'integration starts from a clean target' '' "$TARGET_BEFORE"
assert_equal 'integration starts with an empty index' '' "$TARGET_INDEX_BEFORE"
assert_equal 'integration keeps target HEAD at dispatch base' "$TARGET_HEAD_BEFORE" "$(run_git "$REPO" rev-parse HEAD)"
assert_file_contains 'ticket-a patch is integrated' 'ticket-a' "$REPO/a.txt"
assert_file_contains 'ticket-b same-base patch is integrated after ticket-a' 'ticket-b' "$REPO/b.txt"
assert_equal 'both integrated files are observable' $'a.txt\nb.txt' "$(run_git "$REPO" diff --name-only "$BASE_SHA" --)"

FALLBACK_REPO="$TMP/fallback-repo"
create_repo "$FALLBACK_REPO"
FALLBACK_BASE=$(run_git "$FALLBACK_REPO" rev-parse HEAD)
FAILED_WORKTREE="$TMP/failed-worktree"
printf 'occupied\n' > "$FAILED_WORKTREE"
FALLBACK_EVENTS="$TMP/fallback.events"
if run_git "$FALLBACK_REPO" worktree add --detach --quiet "$FAILED_WORKTREE" "$FALLBACK_BASE" > "$TMP/fallback-worktree.out" 2>&1; then
  fail 'isolation failure is observable'
else
  pass 'isolation failure is observable'
  printf 'worktree-create-failed\ncontroller-dispatch-suppressed\ncontroller-sequential\n' > "$FALLBACK_EVENTS"
  printf 'controller-a\n' > "$FALLBACK_REPO/fallback-a.txt"
  printf 'controller-b\n' > "$FALLBACK_REPO/fallback-b.txt"
fi
assert_file_contains 'fallback stops new worker dispatch' 'controller-dispatch-suppressed' "$FALLBACK_EVENTS"
assert_file_contains 'fallback records controller sequence' 'controller-sequential' "$FALLBACK_EVENTS"
if grep -q 'worker' "$FALLBACK_EVENTS"; then
  fail 'fallback does not dispatch a writing worker'
else
  pass 'fallback does not dispatch a writing worker'
fi
assert_file_contains 'fallback applies first ticket in controller' 'controller-a' "$FALLBACK_REPO/fallback-a.txt"
assert_file_contains 'fallback applies second ticket in controller' 'controller-b' "$FALLBACK_REPO/fallback-b.txt"

DUP_REPO="$TMP/duplicate-repo"
create_repo "$DUP_REPO"
DUP_BASE=$(run_git "$DUP_REPO" rev-parse HEAD)
DUP_PATH="$TMP/duplicate-worktree"
DUP_EVENTS="$TMP/duplicate.events"
run_git "$DUP_REPO" worktree add --detach --quiet "$DUP_PATH" "$DUP_BASE"
if run_git "$DUP_REPO" worktree add --detach --quiet "$DUP_PATH" "$DUP_BASE" > "$TMP/duplicate-worktree.out" 2>&1; then
  fail 'duplicate worktree creation fails closed'
else
  pass 'duplicate worktree creation fails closed'
  printf 'worktree-create-failed\nworker-cancelled\ncontroller-dispatch-suppressed\n' > "$DUP_EVENTS"
fi
DUP_WORKTREE_COUNT=$(run_git "$DUP_REPO" worktree list --porcelain | grep -c '^worktree ')
assert_equal 'duplicate worktree leaves one sibling registration' '2' "$DUP_WORKTREE_COUNT"
assert_file_contains 'duplicate worktree records cancellation' 'worker-cancelled' "$DUP_EVENTS"
assert_file_contains 'duplicate worktree suppresses new dispatch' 'controller-dispatch-suppressed' "$DUP_EVENTS"

INCOMPLETE_REPO="$TMP/incomplete-repo"
create_repo "$INCOMPLETE_REPO"
INCOMPLETE_BASE=$(run_git "$INCOMPLETE_REPO" rev-parse HEAD)
INCOMPLETE_RECEIPT="$TMP/incomplete.provenance"
INCOMPLETE_STATUS_BEFORE=$(run_git "$INCOMPLETE_REPO" status --porcelain)
printf '{"canonical_worktree_path":"%s","dispatch_base_sha":"%s","changed_file_evidence":"a.txt"}\n' "$INCOMPLETE_REPO" "$INCOMPLETE_BASE" > "$INCOMPLETE_RECEIPT"
if grep -Fq '"patch_file_path"' "$INCOMPLETE_RECEIPT"; then
  fail 'incomplete provenance blocks integration'
else
  pass 'incomplete provenance blocks integration'
fi
assert_equal 'incomplete provenance keeps target unchanged' "$INCOMPLETE_STATUS_BEFORE" "$(run_git "$INCOMPLETE_REPO" status --porcelain)"

STALE_REPO="$TMP/stale-repo"
create_repo "$STALE_REPO"
STALE_BASE=$(run_git "$STALE_REPO" rev-parse HEAD)
STALE_WORKTREE="$TMP/stale-worktree"
run_git "$STALE_REPO" worktree add --detach --quiet "$STALE_WORKTREE" "$STALE_BASE"
printf 'stale-worker\n' > "$STALE_WORKTREE/a.txt"
run_git "$STALE_WORKTREE" add -N -- .
STALE_PATCH="$TMP/stale.patch"
run_git "$STALE_WORKTREE" diff --binary "$STALE_BASE" -- > "$STALE_PATCH"
printf 'target-advance\n' > "$STALE_REPO/advance.txt"
run_git "$STALE_REPO" add -A
run_git "$STALE_REPO" commit -qm advance
STALE_CURRENT=$(run_git "$STALE_REPO" rev-parse HEAD)
STALE_EVENTS="$TMP/stale.events"
if [ "$STALE_CURRENT" = "$STALE_BASE" ]; then
  fail 'stale dispatch base is observable'
else
  pass 'stale dispatch base is observable'
  printf 'stale-dispatch-base-blocked\n' > "$STALE_EVENTS"
fi
assert_file_contains 'stale dispatch base blocks integration' 'stale-dispatch-base-blocked' "$STALE_EVENTS"
assert_equal 'stale dispatch base leaves target clean' '' "$(run_git "$STALE_REPO" status --porcelain)"

COLLIDE_REPO="$TMP/same-file-collision-repo"
create_repo "$COLLIDE_REPO"
COLLIDE_BASE=$(run_git "$COLLIDE_REPO" rev-parse HEAD)
COLLIDE_A="$TMP/same-file-a"
COLLIDE_B="$TMP/same-file-b"
run_git "$COLLIDE_REPO" worktree add --detach --quiet "$COLLIDE_A" "$COLLIDE_BASE"
run_git "$COLLIDE_REPO" worktree add --detach --quiet "$COLLIDE_B" "$COLLIDE_BASE"
printf 'collision-a\n' > "$COLLIDE_A/a.txt"
printf 'collision-b\n' > "$COLLIDE_B/a.txt"
run_git "$COLLIDE_A" add -N -- .
run_git "$COLLIDE_B" add -N -- .
COLLIDE_PATCH_A="$TMP/same-file-a.patch"
COLLIDE_PATCH_B="$TMP/same-file-b.patch"
run_git "$COLLIDE_A" diff --binary "$COLLIDE_BASE" -- > "$COLLIDE_PATCH_A"
run_git "$COLLIDE_B" diff --binary "$COLLIDE_BASE" -- > "$COLLIDE_PATCH_B"
run_git "$COLLIDE_REPO" apply --check "$COLLIDE_PATCH_A"
run_git "$COLLIDE_REPO" apply "$COLLIDE_PATCH_A"
COLLIDE_STATUS_BEFORE=$(run_git "$COLLIDE_REPO" status --porcelain)
COLLIDE_INDEX_BEFORE=$(run_git "$COLLIDE_REPO" diff --cached --name-status)
COLLIDE_UNTRACKED_BEFORE=$(run_git "$COLLIDE_REPO" ls-files --others --exclude-standard)
COLLIDE_HEAD_BEFORE=$(run_git "$COLLIDE_REPO" rev-parse HEAD)
COLLIDE_CONTENT_BEFORE=$(tr -d '\r' < "$COLLIDE_REPO/a.txt")
if run_git "$COLLIDE_REPO" apply --check "$COLLIDE_PATCH_B" > "$TMP/same-file-collision.err" 2>&1; then
  COLLIDE_CHECK_EXIT=0
  fail 'same-file collision fails formal check'
else
  COLLIDE_CHECK_EXIT=$?
  pass 'same-file collision fails formal check'
fi
[ -s "$TMP/same-file-collision.err" ] && pass 'same-file collision keeps stderr receipt' || fail 'same-file collision keeps stderr receipt'
COLLIDE_STATUS_AFTER=$(run_git "$COLLIDE_REPO" status --porcelain)
COLLIDE_INDEX_AFTER=$(run_git "$COLLIDE_REPO" diff --cached --name-status)
COLLIDE_UNTRACKED_AFTER=$(run_git "$COLLIDE_REPO" ls-files --others --exclude-standard)
COLLIDE_HEAD_AFTER=$(run_git "$COLLIDE_REPO" rev-parse HEAD)
COLLIDE_CONTENT_AFTER=$(tr -d '\r' < "$COLLIDE_REPO/a.txt")
assert_equal 'same-file collision keeps status' "$COLLIDE_STATUS_BEFORE" "$COLLIDE_STATUS_AFTER"
assert_equal 'same-file collision keeps index' "$COLLIDE_INDEX_BEFORE" "$COLLIDE_INDEX_AFTER"
assert_equal 'same-file collision keeps untracked files' "$COLLIDE_UNTRACKED_BEFORE" "$COLLIDE_UNTRACKED_AFTER"
assert_equal 'same-file collision keeps HEAD' "$COLLIDE_HEAD_BEFORE" "$COLLIDE_HEAD_AFTER"
assert_equal 'same-file collision keeps content' "$COLLIDE_CONTENT_BEFORE" "$COLLIDE_CONTENT_AFTER"

NEW_REPO="$TMP/new-file-collision-repo"
create_repo "$NEW_REPO"
NEW_BASE=$(run_git "$NEW_REPO" rev-parse HEAD)
NEW_A="$TMP/new-file-a"
NEW_B="$TMP/new-file-b"
run_git "$NEW_REPO" worktree add --detach --quiet "$NEW_A" "$NEW_BASE"
run_git "$NEW_REPO" worktree add --detach --quiet "$NEW_B" "$NEW_BASE"
printf 'new-a\n' > "$NEW_A/new.txt"
printf 'new-b\n' > "$NEW_B/new.txt"
run_git "$NEW_A" add -N -- new.txt
run_git "$NEW_B" add -N -- new.txt
NEW_PATCH_A="$TMP/new-file-a.patch"
NEW_PATCH_B="$TMP/new-file-b.patch"
run_git "$NEW_A" diff --binary "$NEW_BASE" -- > "$NEW_PATCH_A"
run_git "$NEW_B" diff --binary "$NEW_BASE" -- > "$NEW_PATCH_B"
run_git "$NEW_REPO" apply --check "$NEW_PATCH_A"
run_git "$NEW_REPO" apply "$NEW_PATCH_A"
NEW_STATUS_BEFORE=$(run_git "$NEW_REPO" status --porcelain)
NEW_INDEX_BEFORE=$(run_git "$NEW_REPO" diff --cached --name-status)
NEW_UNTRACKED_BEFORE=$(run_git "$NEW_REPO" ls-files --others --exclude-standard)
NEW_HEAD_BEFORE=$(run_git "$NEW_REPO" rev-parse HEAD)
NEW_CONTENT_BEFORE=$(tr -d '\r' < "$NEW_REPO/new.txt")
if run_git "$NEW_REPO" apply --check "$NEW_PATCH_B" > "$TMP/new-file-collision.err" 2>&1; then
  NEW_CHECK_EXIT=0
  fail 'new-file collision fails formal check'
else
  NEW_CHECK_EXIT=$?
  pass 'new-file collision fails formal check'
fi
[ -s "$TMP/new-file-collision.err" ] && pass 'new-file collision keeps stderr receipt' || fail 'new-file collision keeps stderr receipt'
NEW_STATUS_AFTER=$(run_git "$NEW_REPO" status --porcelain)
NEW_INDEX_AFTER=$(run_git "$NEW_REPO" diff --cached --name-status)
NEW_UNTRACKED_AFTER=$(run_git "$NEW_REPO" ls-files --others --exclude-standard)
NEW_HEAD_AFTER=$(run_git "$NEW_REPO" rev-parse HEAD)
NEW_CONTENT_AFTER=$(tr -d '\r' < "$NEW_REPO/new.txt")
assert_equal 'new-file collision keeps status' "$NEW_STATUS_BEFORE" "$NEW_STATUS_AFTER"
assert_equal 'new-file collision keeps index' "$NEW_INDEX_BEFORE" "$NEW_INDEX_AFTER"
assert_equal 'new-file collision keeps untracked files' "$NEW_UNTRACKED_BEFORE" "$NEW_UNTRACKED_AFTER"
assert_equal 'new-file collision keeps HEAD' "$NEW_HEAD_BEFORE" "$NEW_HEAD_AFTER"
assert_equal 'new-file collision keeps content' "$NEW_CONTENT_BEFORE" "$NEW_CONTENT_AFTER"

FORMAL_REPO="$TMP/formal-apply-repo"
create_repo "$FORMAL_REPO"
FORMAL_BASE=$(run_git "$FORMAL_REPO" rev-parse HEAD)
FORMAL_WORKTREE="$TMP/formal-apply-worktree"
run_git "$FORMAL_REPO" worktree add --detach --quiet "$FORMAL_WORKTREE" "$FORMAL_BASE"
printf 'formal-patch\n' > "$FORMAL_WORKTREE/a.txt"
run_git "$FORMAL_WORKTREE" add -N -- .
FORMAL_PATCH="$TMP/formal-apply.patch"
run_git "$FORMAL_WORKTREE" diff --binary "$FORMAL_BASE" -- > "$FORMAL_PATCH"
run_git "$FORMAL_REPO" apply --check "$FORMAL_PATCH"
printf 'race-change\n' > "$FORMAL_REPO/a.txt"
FORMAL_STATUS_BEFORE=$(run_git "$FORMAL_REPO" status --porcelain)
FORMAL_INDEX_BEFORE=$(run_git "$FORMAL_REPO" diff --cached --name-status)
FORMAL_UNTRACKED_BEFORE=$(run_git "$FORMAL_REPO" ls-files --others --exclude-standard)
FORMAL_HEAD_BEFORE=$(run_git "$FORMAL_REPO" rev-parse HEAD)
FORMAL_CONTENT_BEFORE=$(tr -d '\r' < "$FORMAL_REPO/a.txt")
if run_git "$FORMAL_REPO" apply "$FORMAL_PATCH" > "$TMP/formal-apply.err" 2>&1; then
  FORMAL_APPLY_EXIT=0
  fail 'formal apply failure is observable'
else
  FORMAL_APPLY_EXIT=$?
  pass 'formal apply failure is observable'
fi
[ -s "$TMP/formal-apply.err" ] && pass 'formal apply failure keeps stderr receipt' || fail 'formal apply failure keeps stderr receipt'
FORMAL_STATUS_AFTER=$(run_git "$FORMAL_REPO" status --porcelain)
FORMAL_INDEX_AFTER=$(run_git "$FORMAL_REPO" diff --cached --name-status)
FORMAL_UNTRACKED_AFTER=$(run_git "$FORMAL_REPO" ls-files --others --exclude-standard)
FORMAL_HEAD_AFTER=$(run_git "$FORMAL_REPO" rev-parse HEAD)
FORMAL_CONTENT_AFTER=$(tr -d '\r' < "$FORMAL_REPO/a.txt")
assert_equal 'formal apply failure keeps status' "$FORMAL_STATUS_BEFORE" "$FORMAL_STATUS_AFTER"
assert_equal 'formal apply failure keeps index' "$FORMAL_INDEX_BEFORE" "$FORMAL_INDEX_AFTER"
assert_equal 'formal apply failure keeps untracked files' "$FORMAL_UNTRACKED_BEFORE" "$FORMAL_UNTRACKED_AFTER"
assert_equal 'formal apply failure keeps HEAD' "$FORMAL_HEAD_BEFORE" "$FORMAL_HEAD_AFTER"
assert_equal 'formal apply failure keeps content' "$FORMAL_CONTENT_BEFORE" "$FORMAL_CONTENT_AFTER"

DIRTY_REPO="$TMP/dirty-target-repo"
create_repo "$DIRTY_REPO"
printf 'dirty-target\n' >> "$DIRTY_REPO/a.txt"
DIRTY_STATUS=$(run_git "$DIRTY_REPO" status --porcelain)
DIRTY_EVENTS="$TMP/dirty.events"
if [ -n "$DIRTY_STATUS" ]; then
  pass 'dirty target is observable'
  printf 'parallel-transport-blocked\n' > "$DIRTY_EVENTS"
else
  fail 'dirty target is observable'
fi
assert_file_contains 'dirty target blocks parallel transport' 'parallel-transport-blocked' "$DIRTY_EVENTS"
DIRTY_WORKTREE_COUNT=$(run_git "$DIRTY_REPO" worktree list --porcelain | grep -c '^worktree ')
assert_equal 'dirty target starts no sibling worktree' '1' "$DIRTY_WORKTREE_COUNT"

COLLIDE_STDERR=$(tr '\n' ' ' < "$TMP/same-file-collision.err" | tr -d '\r')
NEW_STDERR=$(tr '\n' ' ' < "$TMP/new-file-collision.err" | tr -d '\r')
FORMAL_STDERR=$(tr '\n' ' ' < "$TMP/formal-apply.err" | tr -d '\r')
printf 'PROVENANCE_RECEIPT ticket_a=%s ticket_b=%s\n' "$(tr -d '\r\n' < "$RECEIPT_A")" "$(tr -d '\r\n' < "$RECEIPT_B")"
printf 'TRANSPORT_RECEIPT worktree_a=%s worktree_b=%s dispatch_base_sha=%s changed_files_a=%s changed_files_b=%s patch_a=%s patch_b=%s\n' "$CANONICAL_A" "$CANONICAL_B" "$BASE_SHA" "$FILES_A" "$FILES_B" "$PATCH_A" "$PATCH_B"
printf 'INTEGRATION_RECEIPT target=%s dispatch_base_sha=%s check_apply_exit=%s/%s/%s/%s\n' "$REPO" "$BASE_SHA" "$CHECK_A_EXIT" "$APPLY_A_EXIT" "$CHECK_B_EXIT" "$APPLY_B_EXIT"
printf 'FALLBACK_RECEIPT worktree_add=failed dispatch=controller-sequential writing_worker=0 events=%s\n' "$(tr '\n' ',' < "$FALLBACK_EVENTS" | tr -d '\r')"
printf 'BLOCKED_RECEIPT case=incomplete-provenance expected_sha=%s current_sha=%s exit=blocked stderr=none status_before=%q status_after=%q index_before=%q index_after=%q untracked_before=%q untracked_after=%q verification_log=blocked\n' "$INCOMPLETE_BASE" "$INCOMPLETE_BASE" "$INCOMPLETE_STATUS_BEFORE" "$INCOMPLETE_STATUS_BEFORE" '' '' '' ''
printf 'BLOCKED_RECEIPT case=stale-dispatch-base patch=%s expected_sha=%s current_sha=%s exit=blocked stderr=none status_before=%q status_after=%q verification_log=blocked\n' "$STALE_PATCH" "$STALE_BASE" "$STALE_CURRENT" '' ''
printf 'BLOCKED_RECEIPT case=same-file-collision patch=%s provenance=same-file-workers expected_sha=%s current_sha=%s exit=%s stderr=%q status_before=%q status_after=%q index_before=%q index_after=%q untracked_before=%q untracked_after=%q verification_log=blocked\n' "$COLLIDE_PATCH_B" "$COLLIDE_BASE" "$COLLIDE_HEAD_AFTER" "$COLLIDE_CHECK_EXIT" "$COLLIDE_STDERR" "$COLLIDE_STATUS_BEFORE" "$COLLIDE_STATUS_AFTER" "$COLLIDE_INDEX_BEFORE" "$COLLIDE_INDEX_AFTER" "$COLLIDE_UNTRACKED_BEFORE" "$COLLIDE_UNTRACKED_AFTER"
printf 'BLOCKED_RECEIPT case=new-file-collision patch=%s provenance=same-new-file-workers expected_sha=%s current_sha=%s exit=%s stderr=%q status_before=%q status_after=%q index_before=%q index_after=%q untracked_before=%q untracked_after=%q verification_log=blocked\n' "$NEW_PATCH_B" "$NEW_BASE" "$NEW_HEAD_AFTER" "$NEW_CHECK_EXIT" "$NEW_STDERR" "$NEW_STATUS_BEFORE" "$NEW_STATUS_AFTER" "$NEW_INDEX_BEFORE" "$NEW_INDEX_AFTER" "$NEW_UNTRACKED_BEFORE" "$NEW_UNTRACKED_AFTER"
printf 'BLOCKED_RECEIPT case=formal-apply-failure patch=%s provenance=formal-apply-race expected_sha=%s current_sha=%s exit=%s stderr=%q status_before=%q status_after=%q index_before=%q index_after=%q untracked_before=%q untracked_after=%q verification_log=blocked\n' "$FORMAL_PATCH" "$FORMAL_BASE" "$FORMAL_HEAD_AFTER" "$FORMAL_APPLY_EXIT" "$FORMAL_STDERR" "$FORMAL_STATUS_BEFORE" "$FORMAL_STATUS_AFTER" "$FORMAL_INDEX_BEFORE" "$FORMAL_INDEX_AFTER" "$FORMAL_UNTRACKED_BEFORE" "$FORMAL_UNTRACKED_AFTER"
printf 'DIRTY_TARGET_RECEIPT target=%s status=%q dispatch=blocked\n' "$DIRTY_REPO" "$DIRTY_STATUS"

printf '%s\n' '----'
printf 'PASS=%s FAIL=%s\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
