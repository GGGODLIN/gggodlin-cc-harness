#!/bin/bash
set -euo pipefail

PROJECTS_DIR="${RBA_PROJECTS_DIR:-$HOME/.claude/projects}"
LEDGER="${RBA_LEDGER:-$HOME/code/social-info/reports/local-analysis/rba-verify-ledger.jsonl}"
DAYS="${RBA_DAYS:-7}"
DATE="${RBA_DATE:-}"
[[ "$DAYS" =~ ^[0-9]+$ ]] && [ "$DAYS" -ge 1 ] || exit 1
WINDOW_DAYS=$((DAYS - 1))
if [ -n "${RBA_CUTOFF:-}" ]; then
  CUTOFF="$RBA_CUTOFF"
elif [ -n "$DATE" ]; then
  CUTOFF="$(LC_ALL=C date -j -u -v-"${WINDOW_DAYS}"d -f '%Y-%m-%dT%H:%M:%S' "${DATE}T00:00:00" '+%Y-%m-%dT%H:%M:%S.000Z')"
else
  CUTOFF="$(date -u -v-"${DAYS}"d '+%Y-%m-%dT%H:%M:%S.000Z')"
fi
if [ -n "${RBA_END:-}" ]; then
  END="$RBA_END"
elif [ -n "$DATE" ]; then
  END="${DATE}T23:59:59.999Z"
else
  END="$(date -u '+%Y-%m-%dT%H:%M:%S.999Z')"
fi
TMP="$(mktemp -d)"
trap 'rc=$?; rm -rf "$TMP"; exit $rc' EXIT
REVIEWED="$TMP/reviewed"
CANDIDATES="$TMP/candidates"
PINNED="$TMP/pinned"
MANIFEST="${RBA_MANIFEST:-}"
if [ -z "$MANIFEST" ] && [ -n "$DATE" ]; then
  MANIFEST="$(dirname "$LEDGER")/${DATE}-rba-verify.json"
fi

if [ -n "$DATE" ] && [ -f "$MANIFEST" ]; then
  jq -e -c --arg date "$DATE" '
    select(type == "object" and .date == $date and (.eligible | type == "number") and (.samples | type == "array"))
    | {eligible, samples: [.samples[] | {session, invoke, path}]}
    | select((.samples | length) == ([.eligible, 3] | min))
  ' "$MANIFEST"
  exit 0
fi

SCAN_MANIFEST="$TMP/scan-manifest"
if [ ! -d "$PROJECTS_DIR" ] || ! find "$PROJECTS_DIR" -maxdepth 2 -type f -name '*.jsonl' -print0 > "$SCAN_MANIFEST"; then
  exit 1
fi

if [ -n "$DATE" ] && [ -f "$LEDGER" ]; then
  jq -Rr --arg date "$DATE" 'fromjson? | select(type == "object" and .date == $date and (.session | type == "string") and (.invoke | type == "string")) | @base64' "$LEDGER" > "$PINNED"
  pinned_count="$(wc -l < "$PINNED" | tr -d ' ')"
  if [ "$pinned_count" -gt 0 ]; then
    pinned_samples="$TMP/pinned-samples"
    : > "$pinned_samples"
    eligible=""
    missing_eligible=0
    while IFS= read -r encoded; do
      row="$(printf '%s' "$encoded" | base64 -d)"
      session="$(jq -r '.session' <<< "$row")"
      invoke="$(jq -r '.invoke' <<< "$row")"
      row_eligible="$(jq -r 'if ((.eligible | type) == "number" and .eligible >= 0 and (.eligible | floor) == .eligible) then .eligible else empty end' <<< "$row")"
      if [ -z "$row_eligible" ]; then
        missing_eligible=$((missing_eligible + 1))
      elif [ -z "$eligible" ]; then
        eligible="$row_eligible"
      elif [ "$eligible" != "$row_eligible" ]; then
        exit 1
      fi
      path=""
      while IFS= read -r -d '' candidate; do
        case "$candidate" in
          */subagents/*|*widget-log*) continue ;;
        esac
        [ "$(basename "$candidate")" = "$session.jsonl" ] || continue
        if [ -z "$path" ] || [[ "$candidate" < "$path" ]]; then
          path="$candidate"
        fi
      done < "$SCAN_MANIFEST"
      [ -n "$path" ] || exit 1
      jq -cn --arg session "$session" --arg invoke "$invoke" --arg path "$path" '{session: $session, invoke: $invoke, path: $path}' >> "$pinned_samples"
    done < "$PINNED"
    samples_json="$(jq -sc '.' "$pinned_samples")"
    unique_count="$(jq 'unique_by(.session, .invoke) | length' <<< "$samples_json")"
    [ "$unique_count" -eq "$pinned_count" ] || exit 1
    [ -n "$eligible" ] || exit 1
    [ "$missing_eligible" -eq 0 ] || exit 1
    expected_count="$eligible"
    [ "$expected_count" -le 3 ] || expected_count=3
    [ "$pinned_count" -eq "$expected_count" ] || exit 1
    jq -cn --argjson eligible "$eligible" --argjson samples "$samples_json" '{eligible: $eligible, samples: $samples}'
    exit 0
  fi
fi

if [ -f "$LEDGER" ]; then
  jq -Rr 'fromjson? | select(type == "object") | .session // empty' "$LEDGER" | sed 's/\.jsonl$//' | LC_ALL=C sort -u > "$REVIEWED"
else
  : > "$REVIEWED"
fi

: > "$CANDIDATES"
while IFS= read -r -d '' file; do
  case "$file" in
    */subagents/*|*widget-log*) continue ;;
  esac
  invoke_file="$TMP/invokes"
  if ! jq -r 'select(.message.content != null) as $row | $row.message.content | if type == "array" then .[] else empty end | select(.type == "tool_use" and .name == "Skill" and (.input.skill // "") == "research-before-answer") | $row.timestamp // empty' "$file" > "$invoke_file"; then
    exit 1
  fi
  invoke_timestamp=""
  while IFS= read -r timestamp; do
    [[ "$timestamp" < "$CUTOFF" ]] && continue
    [[ "$timestamp" > "$END" ]] && break
    invoke_timestamp="$timestamp"
    break
  done < "$invoke_file"
  [ -n "$invoke_timestamp" ] || continue
  session="$(basename "$file" .jsonl)"
  if ! grep -qxF "$session" "$REVIEWED"; then
    jq -cn --arg session "$session" --arg invoke "$invoke_timestamp" --arg path "$file" '{session: $session, invoke: $invoke, path: $path}' >> "$CANDIDATES"
  fi
done < "$SCAN_MANIFEST"

candidates_json="$(jq -sc 'sort_by(.session, .path) | unique_by(.session)' "$CANDIDATES")"
count="$(jq 'length' <<< "$candidates_json")"

if [ "$count" -le 3 ]; then
  samples_json="$candidates_json"
else
  middle=$(((count - 1) / 2))
  last=$((count - 1))
  samples_json="$(jq -c --argjson middle "$middle" --argjson last "$last" '[.[0], .[$middle], .[$last]]' <<< "$candidates_json")"
fi

jq -cn --argjson eligible "$count" --argjson samples "$samples_json" '{eligible: $eligible, samples: $samples}'
