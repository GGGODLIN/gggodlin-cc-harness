#!/usr/bin/env zsh
set -eu

root="${0:A:h}"
script="$root/recap-daily.sh"
for marker in RECAP_CLAUDE_BIN RECAP_KEYS_FILE RECAP_GPT_MODELS_FILE RECAP_OUT_DIR RECAP_LOG_DIR PARENT_CC_VENDOR; do
  if ! grep -Fq "$marker" "$script"; then
    print -ru2 -- "RED missing route seam: $marker"
    exit 1
  fi
done

fixture=$(mktemp -d /tmp/recap-model-route.XXXXXX)
trap 'rm -rf "$fixture"' EXIT
fake="$fixture/claude"
keys="$fixture/keys.env"
relay_url='http://127.0.0.1:8317'
relay_token='fixture-relay-token'
models="$fixture/gpt-models.env"
luna='fixture-luna(max)'
checks=0
failures=0

cat > "$models" <<'MODELS'
# fixture
GPT_SOL=fixture-sol
GPT_LUNA=fixture-luna
MODELS

cat > "$keys" <<EOF
CLIPROXY_BASE_URL=$relay_url
CLIPROXY_KEY_CC=$relay_token
EOF

cat > "$fake" <<'EOF'
#!/bin/bash
set -euo pipefail
model=''
while (($#)); do
  case "$1" in
    --model) model="$2"; shift 2 ;;
    -p) shift 2 ;;
    *) shift ;;
  esac
done
{
  printf 'model=%s\n' "$model"
  printf 'cc_vendor=%s\n' "${CC_VENDOR-}"
  printf 'base_url=%s\n' "${ANTHROPIC_BASE_URL-}"
  printf 'auth_token_set=%s\n' "${ANTHROPIC_AUTH_TOKEN:+yes}"
  printf 'auth_matches_fixture=%s\n' "$([[ "${ANTHROPIC_AUTH_TOKEN-}" == "${EXPECTED_RELAY_TOKEN-}" ]] && printf yes || printf no)"
  printf 'api_key_set=%s\n' "${ANTHROPIC_API_KEY:+yes}"
  printf 'anthropic_model=%s\n' "${ANTHROPIC_MODEL-}"
  printf 'opus=%s\n' "${ANTHROPIC_DEFAULT_OPUS_MODEL-}"
  printf 'subagent=%s\n' "${CLAUDE_CODE_SUBAGENT_MODEL-}"
  printf 'go_available=%s\n' "$(go version >/dev/null 2>&1 && printf yes || printf no)"
} > "$RECAP_CAPTURE_FILE"
printf '# Daily Recap fixture\n'
EOF
chmod +x "$fake"

source_root="$fixture/source"
source_error="$fixture/source.err"
source_state="$fixture/source.state"
set +e
env -i HOME="$HOME" PATH="$PATH" RECAP_CLAUDE_BIN="$fake" RECAP_KEYS_FILE="$keys" RECAP_OUT_DIR="$source_root/out" RECAP_LOG_DIR="$source_root/log" RECAP_DATE=2026-09-08 RECAP_CAPTURE_FILE="$source_root/capture" bash -c 'before=$PWD; source "$1"; status=$?; after=$PWD; printf "%s\n%s\n" "$before" "$after" > "$2"; exit "$status"' _ "$script" "$source_state" >/dev/null 2>"$source_error"
source_status=$?
set -e
if ((source_status != 2)); then
  print -ru2 -- "source guard returned $source_status instead of 2"
  exit 1
fi
grep -Fqx 'recap route: execute this file; do not source it' "$source_error"
[[ "$(sed -n '1p' "$source_state")" == "$(sed -n '2p' "$source_state")" ]]
[[ ! -e "$source_root/capture" && ! -e "$source_root/out" && ! -e "$source_root/log" ]]

assert_line() {
  local file="$1" line="$2"
  ((++checks))
  if ! grep -Fqx -- "$line" "$file"; then
    print -ru2 -- "missing: $line"
    ((++failures))
  fi
}

run_case() {
  local label="$1" vendor="$2" base="$3"
  local capture="$fixture/$label.capture" out="$fixture/$label.out" log="$fixture/$label.log"
  env -i HOME="$HOME" PATH="$PATH" RECAP_CLAUDE_BIN="$fake" RECAP_KEYS_FILE="$keys" RECAP_GPT_MODELS_FILE="$models" RECAP_OUT_DIR="$out" RECAP_LOG_DIR="$log" RECAP_DATE=2026-09-08 RECAP_CAPTURE_FILE="$capture" EXPECTED_RELAY_TOKEN="$relay_token" CC_VENDOR="$vendor" ANTHROPIC_BASE_URL="$base" ANTHROPIC_AUTH_TOKEN='fixture-parent-token' ANTHROPIC_API_KEY='fixture-parent-api-key' bash "$script"
  assert_line "$capture" "model=$luna"
  assert_line "$capture" 'cc_vendor=headless-channel'
  assert_line "$capture" "base_url=$relay_url"
  assert_line "$capture" 'auth_matches_fixture=yes'
  assert_line "$capture" 'api_key_set='
  assert_line "$capture" "anthropic_model=$luna"
  assert_line "$capture" "opus=$luna"
  assert_line "$capture" "subagent=$luna"
  assert_line "$capture" 'go_available=yes'
  assert_line "$out/2026-09-08-recap.md" '# Daily Recap fixture'
}

native_capture="$fixture/native.capture"
env -i HOME="$HOME" PATH="$PATH" RECAP_CLAUDE_BIN="$fake" RECAP_KEYS_FILE="$keys" RECAP_OUT_DIR="$fixture/native.out" RECAP_LOG_DIR="$fixture/native.log" RECAP_DATE=2026-09-08 RECAP_CAPTURE_FILE="$native_capture" EXPECTED_RELAY_TOKEN="$relay_token" ANTHROPIC_AUTH_TOKEN='fixture-parent-token' ANTHROPIC_API_KEY='fixture-native-key' ANTHROPIC_MODEL='polluted-main' ANTHROPIC_DEFAULT_OPUS_MODEL='free(max)' CLAUDE_CODE_SUBAGENT_MODEL='free(max)' bash "$script"
assert_line "$native_capture" 'model=opus'
assert_line "$native_capture" 'cc_vendor=headless-channel'
assert_line "$native_capture" 'base_url='
assert_line "$native_capture" 'auth_token_set='
assert_line "$native_capture" 'auth_matches_fixture=no'
assert_line "$native_capture" 'api_key_set=yes'
assert_line "$native_capture" 'anthropic_model='
assert_line "$native_capture" 'opus='
assert_line "$native_capture" 'subagent='
assert_line "$native_capture" 'go_available=yes'
assert_line "$fixture/native.out/2026-09-08-recap.md" '# Daily Recap fixture'

for vendor in deepseek glm mimo mimo-payg relay rapid-mlx relay gpt gemini-pro gemini-flash free mix-gpt mix; do
  run_case "$vendor" "$vendor" "https://parent.invalid/$vendor"
done
run_case base-only '' 'https://parent.invalid/custom'

remote_keys="$fixture/remote.env"
cat > "$remote_keys" <<EOF
CLIPROXY_BASE_URL=https://attacker.invalid
CLIPROXY_KEY_CC=$relay_token
EOF
set +e
env -i HOME="$HOME" PATH="$PATH" RECAP_CLAUDE_BIN="$fake" RECAP_KEYS_FILE="$remote_keys" RECAP_OUT_DIR="$fixture/remote.out" RECAP_LOG_DIR="$fixture/remote.log" RECAP_DATE=2026-09-08 RECAP_CAPTURE_FILE="$fixture/remote.capture" CC_VENDOR=gpt ANTHROPIC_BASE_URL='https://parent.invalid/gpt' bash "$script" >/dev/null 2>&1
remote_status=$?
set -e
((++checks))
if ((remote_status == 0)) || [[ -e "$fixture/remote.capture" ]]; then
  print -ru2 -- 'remote relay URL did not fail closed'
  ((++failures))
fi

malicious_keys="$fixture/malicious.env"
cat > "$malicious_keys" <<EOF
CLIPROXY_BASE_URL=$relay_url
CLIPROXY_KEY_CC=$relay_token
touch "$fixture/source-executed"
EOF
env -i HOME="$HOME" PATH="$PATH" RECAP_CLAUDE_BIN="$fake" RECAP_KEYS_FILE="$malicious_keys" RECAP_OUT_DIR="$fixture/malicious.out" RECAP_LOG_DIR="$fixture/malicious.log" RECAP_DATE=2026-09-08 RECAP_CAPTURE_FILE="$fixture/malicious.capture" EXPECTED_RELAY_TOKEN="$relay_token" CC_VENDOR=gpt ANTHROPIC_BASE_URL='https://parent.invalid/gpt' bash "$script"
((++checks))
if [[ -e "$fixture/source-executed" ]]; then
  print -ru2 -- 'keys file content executed as shell code'
  ((++failures))
fi

set +e
env -i HOME="$HOME" PATH="$PATH" RECAP_CLAUDE_BIN="$fake" RECAP_KEYS_FILE="$fixture/missing.env" RECAP_OUT_DIR="$fixture/missing.out" RECAP_LOG_DIR="$fixture/missing.log" RECAP_DATE=2026-09-08 RECAP_CAPTURE_FILE="$fixture/missing.capture" CC_VENDOR=gpt ANTHROPIC_BASE_URL='https://parent.invalid/gpt' bash "$script" >/dev/null 2>&1
missing_status=$?
set -e
((++checks))
if ((missing_status == 0)) || [[ -e "$fixture/missing.capture" ]]; then
  print -ru2 -- 'missing keys case did not fail closed'
  ((++failures))
fi

set +e
env -i HOME="$HOME" PATH="$PATH" RECAP_CLAUDE_BIN="$fake" RECAP_KEYS_FILE="$keys" RECAP_GPT_MODELS_FILE="$fixture/missing-models.env" RECAP_OUT_DIR="$fixture/nomodels.out" RECAP_LOG_DIR="$fixture/nomodels.log" RECAP_DATE=2026-09-08 RECAP_CAPTURE_FILE="$fixture/nomodels.capture" EXPECTED_RELAY_TOKEN="$relay_token" CC_VENDOR=gpt ANTHROPIC_BASE_URL='https://parent.invalid/gpt' bash "$script" >/dev/null 2>&1
nomodels_status=$?
set -e
((++checks))
if ((nomodels_status == 0)) || [[ -e "$fixture/nomodels.capture" ]]; then
  print -ru2 -- 'missing GPT version table did not fail closed'
  ((++failures))
fi

print -r -- "recap-model-route: checks=$checks failures=$failures"
((failures == 0))
