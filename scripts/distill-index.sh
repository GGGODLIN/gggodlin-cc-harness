#!/bin/bash
# distill-index.sh — dynamic INDEX view of ~/.claude/distill-candidates/candidates/*.md
# Read-only、glob candidate frontmatter、group by status、print stdout.
# No persistence (INDEX 不落檔、避免 dual-writer race with per-candidate mutation).
#
# Usage: distill-index.sh [--status pending|approved|rejected|observing] [--json]

set -euo pipefail

CANDIDATES_DIR="$HOME/.claude/distill-candidates/candidates"

if [ ! -d "$CANDIDATES_DIR" ]; then
  echo "# Distill Candidates (empty)"
  echo "_Dir: $CANDIDATES_DIR does not exist yet._"
  exit 0
fi

FILTER_STATUS=""
FORMAT="md"
while [ $# -gt 0 ]; do
  case "$1" in
    --status) FILTER_STATUS="$2"; shift 2 ;;
    --json) FORMAT="json"; shift ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

extract_field() {
  local file="$1" field="$2"
  awk -v key="$field" '
    /^---$/ { if (in_fm) exit; in_fm=1; next }
    in_fm && $0 ~ "^" key ": " { sub("^" key ": ", ""); gsub(/^["'\'']|["'\'']$/, ""); print; exit }
  ' "$file"
}

# Collect all candidate metadata
TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT

for f in "$CANDIDATES_DIR"/*.md; do
  [ -f "$f" ] || continue
  id=$(extract_field "$f" "id")
  status=$(extract_field "$f" "status")
  first_surfaced=$(extract_field "$f" "first_surfaced")
  last_surfaced=$(extract_field "$f" "last_surfaced")
  user_ack=$(extract_field "$f" "user_ack")
  form=$(extract_field "$f" "recommended_form")
  target=$(extract_field "$f" "target_path")
  reject_reason=$(extract_field "$f" "reject_reason")
  weeks_hit=$(extract_field "$f" "weeks_hit")

  [ -n "$FILTER_STATUS" ] && [ "$status" != "$FILTER_STATUS" ] && continue

  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$status" "$id" "$first_surfaced" "$last_surfaced" "$user_ack" "$form" "$target" "$reject_reason" "$weeks_hit" >> "$TMP"
done

if [ "$FORMAT" = "json" ]; then
  awk -F'\t' 'BEGIN { print "[" } NR>1 { print "," } {
    printf "  {\"status\":\"%s\",\"id\":\"%s\",\"first_surfaced\":\"%s\",\"last_surfaced\":\"%s\",\"user_ack\":\"%s\",\"recommended_form\":\"%s\",\"target_path\":\"%s\",\"reject_reason\":\"%s\",\"weeks_hit\":\"%s\"}",
      $1,$2,$3,$4,$5,$6,$7,$8,$9
  } END { print "\n]" }' "$TMP"
  exit 0
fi

# Markdown output
echo "# Distill Candidates (dynamic view)"
echo "_As of: $(date -Iseconds || date +%Y-%m-%dT%H:%M:%S%z)_"
echo ""

total=$(wc -l < "$TMP" | tr -d ' ')
echo "**Total candidates**: $total"
echo ""

for status in pending approved rejected; do
  count=$(awk -F'\t' -v s="$status" '$1==s' "$TMP" | wc -l | tr -d ' ')
  [ "$count" = "0" ] && continue

  # Pending with user_ack=true = Observing sub-group
  if [ "$status" = "pending" ]; then
    observing_count=$(awk -F'\t' -v s="$status" '$1==s && $5=="true"' "$TMP" | wc -l | tr -d ' ')
    pending_only_count=$((count - observing_count))

    if [ "$pending_only_count" -gt 0 ]; then
      echo "## 🟡 Pending ($pending_only_count)"
      awk -F'\t' -v s="$status" '$1==s && $5!="true" {
        printf "- [%s](candidates/%s.md) — first: %s / last: %s / form: %s / weeks: %s\n", $2, $2, $3, $4, $6, $9
      }' "$TMP"
      echo ""
    fi

    if [ "$observing_count" -gt 0 ]; then
      echo "## 👀 Observing ($observing_count) — user_ack=true"
      awk -F'\t' -v s="$status" '$1==s && $5=="true" {
        printf "- [%s](candidates/%s.md) — first: %s / last: %s / form: %s / weeks: %s\n", $2, $2, $3, $4, $6, $9
      }' "$TMP"
      echo ""
    fi
  elif [ "$status" = "approved" ]; then
    echo "## ✅ Approved ($count)"
    awk -F'\t' -v s="$status" '$1==s {
      printf "- [%s](candidates/%s.md) → %s\n", $2, $2, $7
    }' "$TMP"
    echo ""
  elif [ "$status" = "rejected" ]; then
    echo "## ❌ Rejected ($count)"
    awk -F'\t' -v s="$status" '$1==s {
      printf "- [%s](candidates/%s.md) — reason: %s\n", $2, $2, $8
    }' "$TMP"
    echo ""
  fi
done
