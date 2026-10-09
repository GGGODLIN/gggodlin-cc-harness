#!/usr/bin/env bash
# 本檔在契約測試底下：bash ~/.claude/hooks/ledger-bootstrap.test.sh
set -uo pipefail

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HELPER="${LEDGER_BOOTSTRAP_HELPER:-$HOOK_DIR/../scripts/ledger-bootstrap.py}"

python3 "$HELPER" session 2>/dev/null
exit 0
