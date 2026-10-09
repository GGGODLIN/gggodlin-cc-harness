#!/usr/bin/env bash
# 本檔在契約測試底下：bash ~/.claude/hooks/session-start-state-symlink.test.sh
set -euo pipefail

HOOK="$HOME/.claude/hooks/session-start-state.sh"
[ -x "$HOOK" ] || {
  printf 'FAIL state hook is missing or not executable\n'
  exit 1
}
FIX="$(mktemp -d)"
trap 'rm -R "$FIX"' EXIT

REPO="$FIX/repo"
SECRET="$FIX/private-secret"
mkdir -p "$REPO/docs/owner"
printf '%s\n' 'SYNTHETIC_LOCAL_SECRET_SENT_TO_CONTEXT' > "$SECRET"
ln -s "$SECRET" "$REPO/docs/owner/STATE.md"

OUTPUT=$(cd "$REPO" && bash "$HOOK")
if printf '%s' "$OUTPUT" | grep -qF 'SYNTHETIC_LOCAL_SECRET_SENT_TO_CONTEXT'; then
  printf 'FAIL state symlink leaked local file\n'
  exit 1
fi

printf 'PASS state symlink is silent\n'
