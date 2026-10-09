#!/usr/bin/env bash
# Issue, inspect, or revoke the out-of-band permit that lets a commit change a
# locked agent-contract surface. Run it yourself from the input box:
#
#   ! ~/.claude/hooks/agent-contract-gate-permit.sh issue
#
# The permit records the staged index entries for the locked paths (git's own
# mode, blob id, stage and path lines), expires, records the issuing session when
# CLAUDE_CODE_SESSION_ID is set, and is consumed by the gate only after a commit
# passes every check. Binding to the locked entries rather than the whole tree
# means another session staging unrelated files does not void it; changing a
# locked file's staged content changes its blob id and does.
# File layout: first line "<expiry epoch> <session or ->", then the entry lines.
# It is a drift guard, not a security boundary: anything running as this user can
# write the same file. See hooks/agent-contract-validator-gate.sh for the model.
set -u
set -o pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
PERMIT_FILE=${AGENT_CONTRACT_GATE_PERMIT:-$SCRIPT_DIR/state/agent-contract-gate-permit}
AUDIT_LOG=${AGENT_CONTRACT_GATE_AUDIT:-$SCRIPT_DIR/../logs/agent-contract-gate.jsonl}
TTL_SECONDS=${AGENT_CONTRACT_GATE_TTL:-900}
REPO=${AGENT_CONTRACT_GATE_REPO:-$(cd "$SCRIPT_DIR/.." && pwd -P)}

audit() {
  local dir
  dir=$(dirname "$AUDIT_LOG")
  [ -d "$dir" ] || mkdir -p "$dir" 2>/dev/null || return 0
  printf '{"ts":"%s","decision":"%s","reason":"%s","detail":"%s"}\n' \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$1" "$2" "${3:-}" >> "$AUDIT_LOG" 2>/dev/null || true
}

usage() {
  printf 'usage: %s issue|status|revoke\n' "$(basename "$0")" >&2
  exit 2
}

[ $# -ge 1 ] || usage

LOCKED_PATHSPECS='hooks/T2-routing-gate* hooks/review-spec-yagni-permit.py hooks/review-spec-yagni-permit.test.py scripts/agent-contract-validator.mjs scripts/agent-contract-command/* hooks/agent-contract-validator-gate.sh hooks/agent-contract-validator-gate.test.sh hooks/agent-contract-gate-permit.sh .claude/hooks/T2-routing-gate* .claude/hooks/review-spec-yagni-permit.py .claude/hooks/review-spec-yagni-permit.test.py .claude/scripts/agent-contract-validator.mjs .claude/scripts/agent-contract-command/* .claude/hooks/agent-contract-validator-gate.sh .claude/hooks/agent-contract-validator-gate.test.sh .claude/hooks/agent-contract-gate-permit.sh'

locked_entries() {
  # shellcheck disable=SC2086
  git -C "$1" ls-files --stage -- $LOCKED_PATHSPECS 2>/dev/null | LC_ALL=C sort
}

staged_locked_paths() {
  # shellcheck disable=SC2086
  git -C "$1" diff --cached --name-only -- $LOCKED_PATHSPECS 2>/dev/null
}

case "$1" in
  issue)
    if ! git -C "$REPO" rev-parse --show-toplevel >/dev/null 2>&1; then
      printf 'cannot read the staged index in %s -- stage the change first\n' "$REPO" >&2
      exit 1
    fi
    LOCKED_STAGED=$(staged_locked_paths "$REPO")
    if [ -z "$LOCKED_STAGED" ]; then
      printf 'no locked path is staged in %s -- run git add on the gate, validator, permit helper, or T2 routing gate first, so the permit binds to real content\n' "$REPO" >&2
      exit 1
    fi
    ENTRIES=$(locked_entries "$REPO")
    SESSION=${CLAUDE_CODE_SESSION_ID:--}
    EXPIRES=$(( $(date -u '+%s') + TTL_SECONDS ))
    mkdir -p "$(dirname "$PERMIT_FILE")" || exit 1
    umask 077
    printf '%s %s\n%s\n' "$EXPIRES" "$SESSION" "$ENTRIES" > "$PERMIT_FILE" || exit 1
    audit issue permit "$(printf '%s' "$LOCKED_STAGED" | tr '\n' ',')"
    printf 'permit issued for the staged locked entries:\n'
    printf '%s\n' "$ENTRIES" | sed 's/^/  /'
    printf 'bound to session %s\n' "$SESSION"
    printf 'valid for %s seconds, single use, consumed by the gate when the commit passes validation\n' "$TTL_SECONDS"
    printf 'staged locked paths:\n'
    printf '%s\n' "$LOCKED_STAGED" | sed 's/^/  /'
    ;;
  status)
    if [ ! -f "$PERMIT_FILE" ]; then
      printf 'no permit\n'
      exit 0
    fi
    EXPIRES=$(awk 'NR==1{print $1}' "$PERMIT_FILE")
    SESSION=$(awk 'NR==1{print $2}' "$PERMIT_FILE")
    NOW=$(date -u '+%s')
    PERMITTED=$(tail -n +2 "$PERMIT_FILE")
    CURRENT=$(locked_entries "$REPO")
    printf 'entries match: %s\n' "$([ -n "$CURRENT" ] && [ "$PERMITTED" = "$CURRENT" ] && printf yes || printf no)"
    printf 'session       : %s\n' "${SESSION:--}"
    printf 'expires in    : %s seconds\n' "$(( EXPIRES - NOW ))"
    ;;
  revoke)
    rm -f "$PERMIT_FILE"
    audit revoke permit ''
    printf 'permit revoked\n'
    ;;
  *)
    usage
    ;;
esac
