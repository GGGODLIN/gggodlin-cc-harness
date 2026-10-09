#!/bin/bash
set -euo pipefail
packet="${1:?usage: review-spec-yagni-native.sh <packet-file>}"
[[ -f "$packet" ]] || { echo "packet file not found: $packet" >&2; exit 1; }
exec env \
  -u ANTHROPIC_AUTH_TOKEN \
  -u ANTHROPIC_BASE_URL \
  -u ANTHROPIC_CUSTOM_HEADERS \
  -u ANTHROPIC_CUSTOM_MODEL_OPTION \
  -u ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION \
  -u ANTHROPIC_CUSTOM_MODEL_OPTION_NAME \
  -u ANTHROPIC_DEFAULT_FABLE_MODEL \
  -u ANTHROPIC_DEFAULT_HAIKU_MODEL \
  -u ANTHROPIC_DEFAULT_OPUS_MODEL \
  -u ANTHROPIC_DEFAULT_SONNET_MODEL \
  -u ANTHROPIC_MODEL \
  -u CC_VENDOR \
  -u CLAUDE_CODE_SUBAGENT_MODEL \
  claude --model opus -p "$(printf '%s\n\n' '【輸出硬規則】你只有一次回覆機會：最簡版方案、完整逐條表、總評三句必須全部放在你的最後一則（也是唯一一則）回覆裡，不要分段回覆。'; cat "$packet")"
