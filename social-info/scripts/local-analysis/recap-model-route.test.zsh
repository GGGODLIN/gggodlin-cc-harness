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
if [[ -n "${RECAP_STREAM_FILE:-}" ]]; then
  cat "$RECAP_STREAM_FILE"
else
  printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"text","text":"# Daily Recap fixture\n\n3 session / 2 commit / 1 個新 memory / 跨 2 個 repo\n\n## 2026-09-08\n\n### 路由測試用的匿名主題\n這一段只證明正文有日期分組與主題。"}]}}'
  printf '%s\n' '{"type":"result","subtype":"success","is_error":false,"result":"# Daily Recap fixture\n\n3 session / 2 commit / 1 個新 memory / 跨 2 個 repo\n\n## 2026-09-08\n\n### 路由測試用的匿名主題\n這一段只證明正文有日期分組與主題。"}'
fi
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

# 輸出完整性。假 claude 只吐 NDJSON、不呼叫模型；報告形狀取自真實日報的匿名骨架，
# 失敗樣本取自 2026-10-18 那份被當成功收下的 compaction summary。
stream_line() {
  python3 -I -c 'import json,sys; sys.stdout.write(json.dumps(json.loads(sys.stdin.read()), ensure_ascii=False) + "\n")'
}

assistant_event() {
  ASSISTANT_TEXT="$1" python3 -I -c '
import json, os, sys
sys.stdout.write(json.dumps({
    "type": "assistant",
    "message": {"content": [{"type": "text", "text": os.environ["ASSISTANT_TEXT"]}]},
}, ensure_ascii=False) + "\n")
'
}

result_event() {
  local subtype="$1" is_error="$2" result_text="$3"
  RESULT_SUBTYPE="$subtype" RESULT_IS_ERROR="$is_error" RESULT_TEXT="$result_text" python3 -I -c '
import json, os, sys
sys.stdout.write(json.dumps({
    "type": "result",
    "subtype": os.environ["RESULT_SUBTYPE"],
    "is_error": os.environ["RESULT_IS_ERROR"] == "yes",
    "result": os.environ["RESULT_TEXT"],
}, ensure_ascii=False) + "\n")
'
}

GOOD_REPORT='# Daily Recap fixture

3 session / 2 commit / 1 個新 memory / 跨 2 個 repo

## 2026-09-08

### 路由測試用的匿名主題
這一段只證明正文有日期分組與主題，數字不代表任何真實活動。

## 2026-09-07

### 前一日的匿名主題
正文第二個日期分組，避免只靠標題過關。'

OVERVIEW_REPORT='3 session / 2 commit / 1 個新 memory / 跨 2 個 repo

## 2026-09-08

### 數字總覽開頭的匿名主題
這一種真實日報沒有井號標題，第一行就是數字總覽。

## 2026-09-07

### 前一日的匿名主題
正文要留在報告裡，不能被前言蓋掉。'

PREFACE='先整理四條來源，完成後再輸出報告。'
CLOSING='以上是今日整理。'
PROGRESS='正在核對來源，報告還沒寫。'
HEADING_ONLY='# Daily Recap fixture'
COMPACTION='<summary>
1. Primary Request and Intent
原 daily recap 尚未完成，目前只輸出這段 summary。
7. Pending Tasks
正式 Markdown 報告尚未輸出。
</summary>'

assert_status() {
  local label="$1" got="$2" want="$3"
  ((++checks))
  if ((got != want)); then
    print -ru2 -- "$label exited $got, want $want"
    ((++failures))
  fi
}

assert_file_has() {
  local file="$1" text="$2"
  ((++checks))
  if ! grep -Fq -- "$text" "$file"; then
    print -ru2 -- "report missing: $text"
    ((++failures))
  fi
}

assert_file_lacks() {
  local file="$1" text="$2"
  ((++checks))
  if grep -Fq -- "$text" "$file"; then
    print -ru2 -- "report kept rejected text: $text"
    ((++failures))
  fi
}

assert_log_has() {
  local file="$1" text="$2"
  ((++checks))
  if ! grep -Fq -- "$text" "$file"; then
    print -ru2 -- "stderr/log missing: $text"
    ((++failures))
  fi
}

run_stream_case() {
  local label="$1"
  shift
  local out="$fixture/$label.out" log="$fixture/$label.log" err="$fixture/$label.err"
  mkdir -p "$out" "$log"
  if [[ -n "$1" ]]; then
    cp "$1" "$out/2026-09-08-recap.md"
  fi
  shift
  local prior_file=""
  if [[ -f "$out/2026-09-08-recap.md" ]]; then
    prior_file="$fixture/$label.prior"
    cp "$out/2026-09-08-recap.md" "$prior_file"
  fi
  local payload="$fixture/$label.ndjson"
  : > "$payload"
  local item
  for item in "$@"; do
    printf '%s\n' "$item" >> "$payload"
  done
  local run_status
  set +e
  env -i HOME="$HOME" PATH="$PATH" RECAP_CLAUDE_BIN="$fake" RECAP_KEYS_FILE="$keys" RECAP_GPT_MODELS_FILE="$models" RECAP_OUT_DIR="$out" RECAP_LOG_DIR="$log" RECAP_DATE=2026-09-08 RECAP_CAPTURE_FILE="$fixture/$label.capture" EXPECTED_RELAY_TOKEN="$relay_token" RECAP_STREAM_FILE="$payload" CC_VENDOR=gpt ANTHROPIC_BASE_URL='https://parent.invalid/gpt' bash "$script" >/dev/null 2>"$err"
  run_status=$?
  set -e
  STREAM_STATUS="$run_status"
  STREAM_OUT="$out/2026-09-08-recap.md"
  STREAM_ERR="$err"
  STREAM_LOG="$log/local-analysis-recap-2026-09-08.log"
  STREAM_PRIOR="$prior_file"
}

good_block="$(assistant_event "$GOOD_REPORT")"
closing_result="$(result_event success no "$CLOSING")"
preface_block="$(assistant_event "$PREFACE")"
closing_block="$(assistant_event "$CLOSING")"
overview_block="$(assistant_event "$OVERVIEW_REPORT")"
progress_block="$(assistant_event "$PROGRESS")"
heading_block="$(assistant_event "$HEADING_ONLY")"
compaction_block="$(assistant_event "$COMPACTION")"
late_error="$(result_event error_during_execution yes "")"

run_stream_case good "" "$good_block" "$closing_result"
assert_status good "$STREAM_STATUS" 0
assert_file_has "$STREAM_OUT" '# Daily Recap fixture'
assert_file_has "$STREAM_OUT" '## 2026-09-08'
assert_file_has "$STREAM_OUT" '路由測試用的匿名主題'

run_stream_case preface-then-report "" "$preface_block" "$good_block" "$closing_block" "$closing_result"
assert_status preface-then-report "$STREAM_STATUS" 0
assert_file_has "$STREAM_OUT" '路由測試用的匿名主題'
assert_file_lacks "$STREAM_OUT" '先整理四條來源'
assert_file_lacks "$STREAM_OUT" '以上是今日整理。'

run_stream_case overview-opening "" "$preface_block" "$overview_block" "$closing_block" "$closing_result"
assert_status overview-opening "$STREAM_STATUS" 0
assert_file_has "$STREAM_OUT" '3 session / 2 commit / 1 個新 memory / 跨 2 個 repo'
assert_file_has "$STREAM_OUT" '數字總覽開頭的匿名主題'
assert_file_lacks "$STREAM_OUT" '先整理四條來源'

run_stream_case compaction "" "$progress_block" "$compaction_block" "$closing_result"
assert_status compaction "$STREAM_STATUS" 1
assert_log_has "$STREAM_ERR" 'recap rejected'
[[ -e "$STREAM_OUT" ]] && { print -ru2 -- 'compaction left a success-looking report'; ((++failures)); }
((++checks))

run_stream_case blank "" "$closing_result"
assert_status blank "$STREAM_STATUS" 1
assert_log_has "$STREAM_ERR" 'recap rejected'
((++checks))
[[ ! -e "$STREAM_OUT" ]] || { print -ru2 -- 'blank result left a report'; ((++failures)); }

run_stream_case progress-only "" "$progress_block" "$closing_result"
assert_status progress-only "$STREAM_STATUS" 1
assert_log_has "$STREAM_ERR" 'recap rejected'

run_stream_case heading-only "" "$heading_block" "$closing_result"
assert_status heading-only "$STREAM_STATUS" 1
assert_log_has "$STREAM_ERR" 'recap rejected'

run_stream_case result-error "" "$good_block" "$(result_event error_during_execution yes "")"
assert_status result-error "$STREAM_STATUS" 1
assert_log_has "$STREAM_ERR" 'recap rejected'
((++checks))
[[ ! -e "$STREAM_OUT" ]] || { print -ru2 -- 'result error left a report'; ((++failures)); }

prior="$fixture/prior-good.md"
printf '%s\n' "$GOOD_REPORT" > "$prior"
run_stream_case keep-prior "$prior" "$progress_block" "$compaction_block" "$closing_result"
assert_status keep-prior "$STREAM_STATUS" 1
((++checks))
if ! cmp -s "$STREAM_OUT" "$STREAM_PRIOR"; then
  print -ru2 -- 'rejection replaced the previous valid report'
  ((++failures))
fi
assert_file_has "$STREAM_OUT" '路由測試用的匿名主題'
assert_file_lacks "$STREAM_OUT" '<summary>'

for prior_report in "" "$prior"; do
  run_stream_case report-then-summary "$prior_report" "$overview_block" "$compaction_block" "$(result_event success no "$COMPACTION")"
  assert_status report-then-summary "$STREAM_STATUS" 1
  assert_log_has "$STREAM_LOG" '原 daily recap 尚未完成'
  ((++checks))
  if [[ -n "$prior_report" ]]; then
    if ! cmp -s "$STREAM_OUT" "$STREAM_PRIOR"; then
      print -ru2 -- 'late summary replaced the previous valid report'
      ((++failures))
    fi
  elif [[ -e "$STREAM_OUT" ]]; then
    print -ru2 -- 'late summary published the earlier report'
    ((++failures))
  fi
done

run_stream_case late-error "" "$good_block" "$closing_block" "$late_error"
assert_status late-error "$STREAM_STATUS" 1
assert_log_has "$STREAM_ERR" 'recap rejected'
((++checks))
[[ ! -e "$STREAM_OUT" ]] || { print -ru2 -- 'late error published the earlier report'; ((++failures)); }

upstream_fake="$fixture/claude-upstream-fail"
cat > "$upstream_fake" <<'EOF'
#!/bin/bash
printf 'upstream failed\n' >&2
exit 9
EOF
chmod +x "$upstream_fake"
upstream_out="$fixture/upstream.out"
upstream_log="$fixture/upstream.log"
upstream_err="$fixture/upstream.err"
mkdir -p "$upstream_out" "$upstream_log"
set +e
env -i HOME="$HOME" PATH="$PATH" RECAP_CLAUDE_BIN="$upstream_fake" RECAP_KEYS_FILE="$keys" RECAP_GPT_MODELS_FILE="$models" RECAP_OUT_DIR="$upstream_out" RECAP_LOG_DIR="$upstream_log" RECAP_DATE=2026-09-08 CC_VENDOR=gpt ANTHROPIC_BASE_URL='https://parent.invalid/gpt' bash "$script" >/dev/null 2>"$upstream_err"
upstream_status=$?
set -e
assert_status upstream-nonzero "$upstream_status" 9
assert_log_has "$upstream_log/local-analysis-recap-2026-09-08.log" 'upstream failed'
assert_log_has "$upstream_log/local-analysis-recap-2026-09-08.log" 'upstream exit 9'
((++checks))
[[ ! -s "$upstream_out/2026-09-08-recap.md" ]] || { print -ru2 -- 'upstream failure left a report'; ((++failures)); }

print -r -- "recap-model-route: checks=$checks failures=$failures"
((failures == 0))
