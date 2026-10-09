#!/bin/sh
set -eu

GIT_BIN=/usr/bin/git
CMP_BIN=/usr/bin/cmp
CP_BIN=/bin/cp
CHMOD_BIN=/bin/chmod
DIRNAME_BIN=/usr/bin/dirname
LN_BIN=/bin/ln
MKDIR_BIN=/bin/mkdir
MKTEMP_BIN=/usr/bin/mktemp
MV_BIN=/bin/mv
RM_BIN=/bin/rm
MANAGED_MARKER="# personal-main-pre-push managed wrapper v2"
OLD_MANAGED_MARKER="# personal-main-pre-push managed wrapper v1"
BOUNDARY_MESSAGE="bypass boundaries: --no-verify, hook deletion or modification, remote API bypass; force push 仍須既有 human confirm; final-read race has no atomic guarantee; 安裝後另設 worktree-specific core.hooksPath 會繞過，/git-closeout 要查；命令列 -c core.hooksPath 也會繞過；run /git-closeout after push"

trusted_git() {
  /usr/bin/env -i HOME="${HOME-}" PATH=/usr/bin:/bin GIT_NO_REPLACE_OBJECTS=1 GIT_OPTIONAL_LOCKS=0 "$GIT_BIN" "$@"
}

fail() {
  printf 'personal-main-pre-push installer: DENY: %s\n' "$*" >&2
  exit 1
}

[ -x "$GIT_BIN" ] || fail "trusted Git is unavailable"
[ -x "$CMP_BIN" ] || fail "trusted cmp is unavailable"

MODE=${1-}
CURRENT_DIR=${PWD}
TOPLEVEL=$(trusted_git -C "$CURRENT_DIR" rev-parse --show-toplevel 2>/dev/null) || fail "not inside a Git worktree"
HOOK_DIR=$(trusted_git -C "$CURRENT_DIR" rev-parse --path-format=absolute --git-path hooks 2>/dev/null) || fail "Git could not resolve hooks directory"
case "$HOOK_DIR" in
  /*) ;;
  *) fail "Git returned a non-absolute hooks directory" ;;
esac

SOURCE_HELPER="$TOPLEVEL/hooks/personal-main-pre-push.py"
HOOK="$HOOK_DIR/pre-push"
INSTALLED_HELPER="$HOOK_DIR/personal-main-pre-push.py"
TMP_WORKTREES=$($MKTEMP_BIN "${TMPDIR:-/tmp}/personal-main-pre-push-worktrees.XXXXXX") || fail "cannot create worktree inspection file"
TMP_WRAPPER=
TMP_OLD_WRAPPER=
TMP_HELPER=

cleanup() {
  [ -z "$TMP_WORKTREES" ] || $RM_BIN -f "$TMP_WORKTREES"
  [ -z "$TMP_WRAPPER" ] || $RM_BIN -f "$TMP_WRAPPER"
  [ -z "$TMP_OLD_WRAPPER" ] || $RM_BIN -f "$TMP_OLD_WRAPPER"
  [ -z "$TMP_HELPER" ] || $RM_BIN -f "$TMP_HELPER"
}
trap cleanup EXIT HUP INT TERM

trusted_git -C "$CURRENT_DIR" worktree list --porcelain > "$TMP_WORKTREES" 2>/dev/null || fail "cannot enumerate all worktrees"
found_worktree=0
while IFS= read -r line; do
  case "$line" in
    "worktree "*)
      found_worktree=1
      worktree=${line#worktree }
      [ -n "$worktree" ] || fail "worktree path is empty"
      [ -d "$worktree" ] || fail "cannot inspect worktree: $worktree"
      if trusted_git -C "$worktree" config --get-all core.hooksPath >/dev/null 2>&1; then
        fail "custom core.hooksPath is configured in worktree: $worktree"
      else
        config_status=$?
        [ "$config_status" -eq 1 ] || fail "cannot inspect core.hooksPath in worktree: $worktree"
      fi
      ;;
  esac
done < "$TMP_WORKTREES"
[ "$found_worktree" -eq 1 ] || fail "Git returned no worktrees"

if [ ! -d "$HOOK_DIR" ]; then
  [ "$MODE" = "--disable" ] && {
    printf '%s\n' 'personal-main-pre-push installer: already disabled'
    exit 0
  }
  $MKDIR_BIN -p "$HOOK_DIR" || fail "cannot create hooks directory"
fi
[ -L "$HOOK_DIR" ] && fail "hooks directory is a symlink"

check_hook_shape() {
  if [ -L "$HOOK" ] || { [ -e "$HOOK" ] && [ ! -f "$HOOK" ]; }; then
    fail "existing pre-push is not a regular local hook"
  fi
}

is_managed_hook() {
  [ -f "$HOOK" ] && [ ! -L "$HOOK" ] || return 1
  $CMP_BIN -s "$TMP_WRAPPER" "$HOOK" && return 0
  $CMP_BIN -s "$TMP_OLD_WRAPPER" "$HOOK"
}

require_source_helper() {
  [ -L "$SOURCE_HELPER" ] && fail "tracked helper is a symlink"
  [ -f "$SOURCE_HELPER" ] || fail "tracked helper is missing"
  [ -x "$SOURCE_HELPER" ] || fail "tracked helper is not executable"
}

write_wrapper() {
  cat <<EOF
#!/bin/sh
$MANAGED_MARKER
set -eu

DIRNAME_BIN=/usr/bin/dirname
HOOK_DIR=\$($DIRNAME_BIN "\$0" 2>/dev/null) || {
  printf '%s\\n' 'personal-main-pre-push: DENY: cannot resolve installed hook directory' >&2
  exit 1
}
HOOK_DIR=\$(CDPATH= cd "\$HOOK_DIR" 2>/dev/null && pwd -P) || {
  printf '%s\\n' 'personal-main-pre-push: DENY: cannot resolve installed hook directory' >&2
  exit 1
}
HELPER=\$HOOK_DIR/personal-main-pre-push.py
if [ -L "\$HELPER" ] || [ ! -f "\$HELPER" ] || [ ! -x "\$HELPER" ]; then
  printf '%s\\n' 'personal-main-pre-push: DENY: installed helper is missing or not executable' >&2
  exit 1
fi
exec "\$HELPER" "\$@"
EOF
}

write_old_wrapper() {
  cat <<EOF
#!/bin/sh
$OLD_MANAGED_MARKER
set -eu

GIT_BIN=/usr/bin/git
unset GIT_DIR GIT_WORK_TREE GIT_COMMON_DIR GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES 2>/dev/null || true
TOPLEVEL=\$($GIT_BIN rev-parse --show-toplevel 2>/dev/null) || {
  printf '%s\\n' 'personal-main-pre-push: DENY: cannot resolve invoking worktree' >&2
  exit 1
}
HELPER=\$TOPLEVEL/hooks/personal-main-pre-push.py
if [ -L "\$HELPER" ] || [ ! -f "\$HELPER" ] || [ ! -x "\$HELPER" ]; then
  printf '%s\\n' 'personal-main-pre-push: DENY: tracked helper is missing or not executable' >&2
  exit 1
fi
exec "\$HELPER" "\$@"
EOF
}

prepare_wrappers() {
  TMP_WRAPPER=$($MKTEMP_BIN "$HOOK_DIR/.personal-main-pre-push-wrapper.XXXXXX") || fail "cannot create temporary wrapper"
  TMP_OLD_WRAPPER=$($MKTEMP_BIN "$HOOK_DIR/.personal-main-pre-push-old-wrapper.XXXXXX") || fail "cannot create old wrapper"
  write_wrapper > "$TMP_WRAPPER" || fail "cannot write managed wrapper"
  write_old_wrapper > "$TMP_OLD_WRAPPER" || fail "cannot write old managed wrapper"
  $CHMOD_BIN 755 "$TMP_WRAPPER" "$TMP_OLD_WRAPPER" || fail "cannot make wrapper executable"
}

prepare_payloads() {
  prepare_wrappers
  TMP_HELPER=$($MKTEMP_BIN "$HOOK_DIR/.personal-main-pre-push-helper.XXXXXX") || fail "cannot create temporary helper"
  $CP_BIN "$SOURCE_HELPER" "$TMP_HELPER" || fail "cannot copy tracked helper"
  $CHMOD_BIN 755 "$TMP_HELPER" || fail "cannot make helper executable"
}

check_existing_installed_helper() {
  if [ -L "$INSTALLED_HELPER" ] || { [ -e "$INSTALLED_HELPER" ] && [ ! -f "$INSTALLED_HELPER" ]; }; then
    fail "installed helper is not a regular local file"
  fi
}

require_installed_helper() {
  check_existing_installed_helper
  [ -e "$INSTALLED_HELPER" ] || fail "installed helper is missing"
  [ -x "$INSTALLED_HELPER" ] || fail "installed helper is not executable"
  $CMP_BIN -s "$TMP_HELPER" "$INSTALLED_HELPER" || fail "installed helper bytes differ from tracked helper"
}

install_helper() {
  allow_replace=${1-0}
  if [ -e "$INSTALLED_HELPER" ]; then
    if $CMP_BIN -s "$TMP_HELPER" "$INSTALLED_HELPER"; then
      $CHMOD_BIN 755 "$INSTALLED_HELPER" || fail "cannot make installed helper executable"
      return
    fi
    [ "$allow_replace" = 1 ] || fail "installed helper is foreign or differs from tracked helper"
    $MV_BIN "$TMP_HELPER" "$INSTALLED_HELPER" || fail "cannot atomically upgrade installed helper"
    TMP_HELPER=
    return
  fi
  $LN_BIN "$TMP_HELPER" "$INSTALLED_HELPER" || fail "installed helper appeared before managed install"
  $RM_BIN -f "$TMP_HELPER"
  TMP_HELPER=
}

install_absent_wrapper() {
  $LN_BIN "$TMP_WRAPPER" "$HOOK" || fail "pre-push appeared before managed install"
  $RM_BIN -f "$TMP_WRAPPER"
  TMP_WRAPPER=
}

print_boundaries() {
  printf '%s\n' "$BOUNDARY_MESSAGE"
}

case "$MODE" in
  "")
    require_source_helper
    prepare_payloads
    check_hook_shape
    if [ -e "$HOOK" ]; then
      is_managed_hook || fail "existing pre-push is foreign or differs from managed wrapper"
      check_existing_installed_helper
      if ! $CMP_BIN -s "$TMP_WRAPPER" "$HOOK"; then
        $MV_BIN "$TMP_WRAPPER" "$HOOK" || fail "cannot atomically upgrade managed wrapper"
        TMP_WRAPPER=
      else
        [ -x "$HOOK" ] || $CHMOD_BIN 755 "$HOOK"
      fi
      install_helper 1
      printf '%s\n' 'personal-main-pre-push installer: installed'
    else
      check_existing_installed_helper
      install_helper 0
      install_absent_wrapper
      printf '%s\n' 'personal-main-pre-push installer: installed'
    fi
    print_boundaries
    exit 0
    ;;
  --check)
    require_source_helper
    prepare_payloads
    check_hook_shape
    [ -e "$HOOK" ] || fail "managed pre-push is not installed"
    is_managed_hook || fail "pre-push is foreign or differs from managed wrapper"
    $CMP_BIN -s "$TMP_WRAPPER" "$HOOK" || fail "managed wrapper needs upgrade"
    [ -x "$HOOK" ] || fail "managed wrapper is not executable"
    require_installed_helper
    printf '%s\n' 'personal-main-pre-push installer: managed wrapper installed'
    print_boundaries
    exit 0
    ;;
  --disable)
    check_hook_shape
    if [ ! -e "$HOOK" ]; then
      printf '%s\n' 'personal-main-pre-push installer: already disabled'
      exit 0
    fi
    prepare_wrappers
    is_managed_hook || fail "refusing to remove foreign or changed pre-push"
    $RM_BIN "$HOOK" || fail "cannot remove managed pre-push"
    printf '%s\n' 'personal-main-pre-push installer: disabled'
    exit 0
    ;;
  *)
    fail "usage: install-personal-main-pre-push.sh [--check|--disable]"
    ;;
esac
