#!/usr/bin/env bash
set -euo pipefail

mode="${1:---paths}"
inventory="${2:-$HOME/.claude/skills/INVENTORY.md}"

if [ ! -f "$inventory" ]; then
  printf 'inventory not found: %s\n' "$inventory" >&2
  exit 2
fi

extract_paths() {
  awk -v home="$HOME" -F'|' '
    /^## Global skills/ { scope=home "/.claude/skills"; in_table=0; next }
    /^## Project: .*\(`.*`\)/ {
      s=$0
      sub(/^.*\(`/, "", s)
      sub(/`\).*$/, "", s)
      sub(/^~/, home, s)
      sub(/\/+$/, "", s)
      scope=s
      in_table=0
      next
    }
    /^## / { scope=""; in_table=0; next }
    /^\| *-+/ { in_table=1; next }
    scope != "" && in_table && /^\|/ {
      skill=$2
      audit=$4
      gsub(/^ +| +$/, "", skill)
      gsub(/^ +| +$/, "", audit)
      if (audit != "yes" && audit != "yes (patched)" && audit != "no" && audit != "-") {
        printf "invalid Audit value: %s\n", audit > "/dev/stderr"
        exit 2
      }
      is_command=0
      if (skill ~ / \(command\)$/) {
        sub(/ \(command\)$/, "", skill)
        is_command=1
      }
      if (audit == "yes" || audit == "yes (patched)") {
        if (skill !~ /^[a-z0-9]+(-[a-z0-9]+)*$/) {
          printf "invalid skill name: %s\n", skill > "/dev/stderr"
          exit 2
        }
        if (!is_command) print scope "/" skill "/SKILL.md"
      }
    }
  ' "$inventory"
}

paths=$(extract_paths)

case "$mode" in
  --paths)
    if [ -n "$paths" ]; then
      printf '%s\n' "$paths"
    fi
    ;;
  --counts)
    printf '%s\n' "$paths" | awk -v prefix="$HOME/.claude/skills/" '
      NF {
        total++
        if (index($0, prefix) == 1) global++
        else project++
      }
      END {
        printf "{\"global\":%d,\"project\":%d,\"total\":%d}\n", global, project, total
      }
    '
    ;;
  *)
    printf 'usage: %s [--paths|--counts] [inventory-path]\n' "$0" >&2
    exit 2
    ;;
esac
