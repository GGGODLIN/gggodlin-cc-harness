#!/bin/sh
set -eu
[ -n "${CLAUDE_ENV_FILE:-}" ] || exit 0
[ ! -L "$CLAUDE_ENV_FILE" ] || exit 1
if [ -e "$CLAUDE_ENV_FILE" ]; then
  [ -f "$CLAUDE_ENV_FILE" ] || exit 1
  [ "$(/usr/bin/stat -f '%l' "$CLAUDE_ENV_FILE")" = 1 ] || exit 1
fi
printf '%s\n' 'harness: wiring point "better-rm" is not provided in this public copy; see WIRING.md' >&2; exit 1
