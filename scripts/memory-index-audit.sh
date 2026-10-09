#!/bin/bash
set -uo pipefail

MEMORY_DIR="${1:?usage: memory-index-audit.sh <memory-dir>}"
WIKI_DIR="${2:-$(dirname "$MEMORY_DIR")/wiki}"
[ -d "$MEMORY_DIR" ] || { printf 'memory dir not found: %s\n' "$MEMORY_DIR" >&2; exit 2; }
cd "$MEMORY_DIR" || exit 2

for d in general work/*/ projects/*/; do
  d="${d%/}"
  [ -d "$d" ] || continue
  if [ ! -e "$d/_INDEX.md" ]; then
    printf 'MISSING _INDEX: %s/\n' "$d"
    continue
  fi
  md_listed=$(find "$d" -maxdepth 1 \( -name '_INDEX.md' -o -name '_index_*.md' \) -exec grep -hoE '\([^() ]+\.md(#[^)]*)?\)' {} + 2>/dev/null | sed -E 's/^\(//; s/\)$//; s/#.*$//' | sort -u)
  wiki_listed=$(find "$d" -maxdepth 1 \( -name '_INDEX.md' -o -name '_index_*.md' \) -exec grep -hoE '\[\[[^][]+\]\]' {} + 2>/dev/null | sed -E 's/^\[\[//; s/\]\]$//; s/#.*$//' | sort -u | while read -r slug; do
    [ -n "$slug" ] || continue
    [ -f "$WIKI_DIR/$slug.md" ] && continue
    target=$(find "$MEMORY_DIR" -name '*.md' -type f -exec grep -lFx "name: $slug" {} + 2>/dev/null | head -1)
    [ -n "$target" ] || target=$(find "$MEMORY_DIR" -name "$slug.md" -type f -print -quit)
    if [[ "$target" == "$MEMORY_DIR/$d/"* ]]; then
      basename "$target"
    fi
  done | sort -u)
  actual=$(find "$d" -maxdepth 1 -name '*.md' ! -name '_INDEX.md' | sed "s|^$d/||" | sort -u)
  comm -23 <(printf '%s\n' "$actual" | grep .) <(printf '%s\n%s\n' "$md_listed" "$wiki_listed" | grep . | sort -u) | sed "s|^|UNLISTED: $d/|"
  printf '%s\n' "$md_listed" | grep -vE '/|^$' | while read -r f; do
    [ -e "$d/$f" ] || printf 'LISTED-BUT-MISSING: %s/%s\n' "$d" "$f"
  done
done

for top in work projects; do
  routed=$(grep -hoE '\([^() ]+/_INDEX\.md\)' "$top/_INDEX.md" 2>/dev/null | sed -E 's/^\(//; s/\)$//' | sort -u)
  for sub in "$top"/*/; do
    sub="${sub%/}"
    [ -d "$sub" ] || continue
    rel="${sub#$top/}/_INDEX.md"
    printf '%s\n' "$routed" | grep -qxF "$rel" || printf 'ROUTER MISSING: %s/_INDEX.md 未列 %s\n' "$top" "$rel"
  done
  printf '%s\n' "$routed" | while read -r r; do
    [ -n "$r" ] && [ ! -e "$top/$r" ] && printf 'ROUTER DEAD LINK: %s/%s\n' "$top" "$r"
  done
done

exit 0
