#!/bin/bash
# List frontier tickets (open + all blockers closed) of a wayfinder board.
# Usage: frontier.sh <board-dir>   (board-dir contains map.md + tickets/)
set -euo pipefail

board="${1:?usage: frontier.sh <board-dir>}"
tickets="$board/tickets"
[ -d "$tickets" ] || { echo "no tickets dir: $tickets" >&2; exit 1; }

status_of() {
  awk -F': *' '/^status:/{print $2; exit}' "$1"
}

for f in "$tickets"/*.md; do
  [ -e "$f" ] || { echo "(no tickets)"; exit 0; }
  st="$(status_of "$f")"
  [ "$st" = "open" ] || continue
  blockers="$(awk -F'[][]' '/^blocked-by:/{print $2; exit}' "$f" | tr ',' ' ')"
  unblocked=1
  for b in $blockers; do
    b="$(echo "$b" | tr -d ' ')"
    [ -n "$b" ] || continue
    bf="$(ls "$tickets"/"$b"-*.md 2>/dev/null | head -1)"
    if [ -z "$bf" ] || [ "$(status_of "$bf")" != "closed" ]; then
      unblocked=0
      break
    fi
  done
  [ "$unblocked" = "1" ] && basename "$f"
done
