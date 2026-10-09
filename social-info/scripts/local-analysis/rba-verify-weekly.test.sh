#!/bin/bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HELPER="$DIR/rba-verify-sample.sh"
WRAPPER="$DIR/rba-verify-weekly.sh"
VERIFIER="$DIR/rba-verify-weekly-verifier.sh"
FINALIZER="$DIR/rba-verify-finalize.py"
WORKFLOW="$HOME/.claude/workflows/local-analysis.js"
HOOK="$HOME/.claude/hooks/daily-local-analysis-trigger.sh"
TMP="$(mktemp -d)"
trap 'rc=$?; rm -rf "$TMP"; exit $rc' EXIT
SNAP="$TMP/snapshots"
mkdir -p "$SNAP"
PROJECTS="$TMP/projects"
LEDGER="$TMP/ledger.jsonl"

add_session() {
  local project="$1"
  local session="$2"
  local skill="${3:-research-before-answer}"
  local timestamp="${4:-2026-07-28T12:00:00.000Z}"
  mkdir -p "$PROJECTS/$project"
  printf '%s\n' "{\"timestamp\":\"$timestamp\",\"message\":{\"content\":[{\"type\":\"tool_use\",\"name\":\"Skill\",\"input\":{\"skill\":\"$skill\"}}]}}" > "$PROJECTS/$project/$session.jsonl"
}

add_session zeta 10000000-0000-0000-0000-000000000000
add_session alpha 20000000-0000-0000-0000-000000000000
add_session theta 30000000-0000-0000-0000-000000000000
add_session beta 40000000-0000-0000-0000-000000000000
add_session gamma 50000000-0000-0000-0000-000000000000
add_session delta 60000000-0000-0000-0000-000000000000
add_session epsilon 70000000-0000-0000-0000-000000000000
add_session aardvark 80000000-0000-0000-0000-000000000000
add_session duplicate 30000000-0000-0000-0000-000000000000
add_session $'tab\tproject' 99000000-0000-0000-0000-000000000000
add_session zero 05000000-0000-0000-0000-000000000000 another-skill
add_session omega 90000000-0000-0000-0000-000000000000 research-before-answer 2026-07-20T12:00:00.000Z
mkdir -p "$PROJECTS/iota"
printf '%s\n' \
  '{"timestamp":"2026-07-20T12:00:00.000Z","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"research-before-answer"}}]}}' \
  '{"timestamp":"2026-07-28T12:00:00.000Z","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"research-before-answer"}}]}}' > "$PROJECTS/iota/95000000-0000-0000-0000-000000000000.jsonl"
mkdir -p "$PROJECTS/zeta/subagents"
printf '%s\n' '{"message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"research-before-answer"}}]}}' > "$PROJECTS/zeta/subagents/01000000-0000-0000-0000-000000000000.jsonl"

printf '%s\n' \
  '{"session":"20000000-0000-0000-0000-000000000000"}' \
  '{invalid' \
  '{"session":"70000000-0000-0000-0000-000000000000.jsonl"}' > "$LEDGER"

sample_json="$(RBA_PROJECTS_DIR="$PROJECTS" RBA_LEDGER="$LEDGER" RBA_CUTOFF="2026-07-22T00:00:00.000Z" "$HELPER")"
test "$(jq -r '.eligible' <<< "$sample_json")" = "8"
test "$(jq -c '[.samples[].session]' <<< "$sample_json")" = '["10000000-0000-0000-0000-000000000000","50000000-0000-0000-0000-000000000000","99000000-0000-0000-0000-000000000000"]'
test "$(jq -r '.samples[0].path' <<< "$sample_json")" = "$PROJECTS/zeta/10000000-0000-0000-0000-000000000000.jsonl"
test "$(jq -r '.samples[2].path' <<< "$sample_json")" = "$PROJECTS/"$'tab\tproject'"/99000000-0000-0000-0000-000000000000.jsonl"
test "$(jq -r '.samples[2].invoke' <<< "$sample_json")" = "2026-07-28T12:00:00.000Z"

FIXED_PROJECTS="$TMP/fixed-projects"
FIXED_LEDGER="$TMP/fixed-ledger.jsonl"
PROJECTS="$FIXED_PROJECTS"
add_session fixed-old 09000000-0000-0000-0000-000000000000 research-before-answer 2026-07-29T00:00:00.000Z
add_session fixed-a a1000000-0000-0000-0000-000000000000 research-before-answer 2026-08-01T12:00:00.000Z
add_session fixed-b b2000000-0000-0000-0000-000000000000 research-before-answer 2026-08-02T12:00:00.000Z
add_session fixed-c c3000000-0000-0000-0000-000000000000 research-before-answer 2026-08-03T12:00:00.000Z
touch -t 202001010000 "$FIXED_PROJECTS/fixed-b/b2000000-0000-0000-0000-000000000000.jsonl"
fixed_first="$(RBA_PROJECTS_DIR="$FIXED_PROJECTS" RBA_LEDGER="$FIXED_LEDGER" RBA_DATE="2026-08-05" RBA_END="2026-08-05T23:59:59.999Z" "$HELPER")"
fixed_second="$(RBA_PROJECTS_DIR="$FIXED_PROJECTS" RBA_LEDGER="$FIXED_LEDGER" RBA_DATE="2026-08-05" RBA_END="2026-08-05T23:59:59.999Z" "$HELPER")"
test "$fixed_first" = "$fixed_second"
test "$(jq -r '.eligible' <<< "$fixed_first")" = "3"
test "$(jq -c '[.samples[].session]' <<< "$fixed_first")" = '["a1000000-0000-0000-0000-000000000000","b2000000-0000-0000-0000-000000000000","c3000000-0000-0000-0000-000000000000"]'
add_session fixed-d d4000000-0000-0000-0000-000000000000 research-before-answer 2026-08-04T10:00:00.000Z
add_session fixed-e e5000000-0000-0000-0000-000000000000 research-before-answer 2026-08-04T11:00:00.000Z
add_session fixed-f f6000000-0000-0000-0000-000000000000 research-before-answer 2026-08-04T12:00:00.000Z
PIN_LEDGER="$TMP/pin-ledger.jsonl"
printf '%s\n' \
  '{invalid' \
  '{"date":"2026-08-05","session":"b2000000-0000-0000-0000-000000000000","invoke":"2026-08-02T12:00:00.000Z","eligible":6}' \
  '{"date":"2026-08-05","session":"d4000000-0000-0000-0000-000000000000","invoke":"2026-08-04T10:00:00.000Z","eligible":6}' \
  '{"date":"2026-08-05","session":"f6000000-0000-0000-0000-000000000000","invoke":"2026-08-04T12:00:00.000Z","eligible":6}' > "$PIN_LEDGER"
pinned="$(RBA_PROJECTS_DIR="$FIXED_PROJECTS" RBA_LEDGER="$PIN_LEDGER" RBA_DATE="2026-08-05" RBA_END="2026-08-05T23:59:59.999Z" "$HELPER")"
test "$(jq -r '.eligible' <<< "$pinned")" = "6"
test "$(jq -c '[.samples[].session]' <<< "$pinned")" = '["b2000000-0000-0000-0000-000000000000","d4000000-0000-0000-0000-000000000000","f6000000-0000-0000-0000-000000000000"]'
PARTIAL_LEDGER="$TMP/partial-ledger.jsonl"
printf '%s\n' '{"date":"2026-08-05","session":"a1000000-0000-0000-0000-000000000000","invoke":"2026-08-01T12:00:00.000Z","R1":"PASS","R2":"PASS","R3":"PASS","note":""}' > "$PARTIAL_LEDGER"
set +e
RBA_PROJECTS_DIR="$FIXED_PROJECTS" RBA_LEDGER="$PARTIAL_LEDGER" RBA_DATE="2026-08-05" RBA_END="2026-08-05T23:59:59.999Z" "$HELPER" >/dev/null 2>&1
partial_rc=$?
set -e
test "$partial_rc" -ne 0

MISSING_PROJECTS="$TMP/missing-projects"
set +e
RBA_PROJECTS_DIR="$MISSING_PROJECTS" RBA_LEDGER="$TMP/missing-ledger.jsonl" RBA_DATE="2026-08-05" RBA_END="2026-08-05T23:59:59.999Z" "$HELPER" >/dev/null 2>&1
missing_projects_rc=$?
set -e
test "$missing_projects_rc" -ne 0

MALFORMED_PROJECTS="$TMP/malformed-projects"
mkdir -p "$MALFORMED_PROJECTS/malformed"
printf '%s\n' '{not-json' > "$MALFORMED_PROJECTS/malformed/bad.jsonl"
set +e
RBA_PROJECTS_DIR="$MALFORMED_PROJECTS" RBA_LEDGER="$TMP/malformed-ledger.jsonl" RBA_DATE="2026-08-05" RBA_END="2026-08-05T23:59:59.999Z" "$HELPER" >/dev/null 2>&1
malformed_transcript_rc=$?
set -e
test "$malformed_transcript_rc" -ne 0

SINGLE_SCAN_BIN="$TMP/single-scan-bin"
SINGLE_SCAN_COUNTER="$TMP/single-scan-counter"
mkdir -p "$SINGLE_SCAN_BIN"
cat > "$SINGLE_SCAN_BIN/find" <<'SH'
#!/bin/bash
count=0
[ ! -f "$RBA_FIND_COUNTER" ] || count="$(cat "$RBA_FIND_COUNTER")"
count=$((count + 1))
printf '%s' "$count" > "$RBA_FIND_COUNTER"
[ "$count" -eq 1 ] || exit 73
exec /usr/bin/find "$@"
SH
chmod +x "$SINGLE_SCAN_BIN/find"
single_scan_json="$(RBA_FIND_COUNTER="$SINGLE_SCAN_COUNTER" PATH="$SINGLE_SCAN_BIN:$PATH" RBA_PROJECTS_DIR="$FIXED_PROJECTS" RBA_LEDGER="$TMP/single-scan-ledger.jsonl" RBA_CUTOFF="2026-07-22T00:00:00.000Z" "$HELPER")"
test "$(cat "$SINGLE_SCAN_COUNTER")" = "1"
test "$(jq -r '.eligible' <<< "$single_scan_json")" = "7"

prompt="$(bash "$WRAPPER")"
grep -F 'rba-verify-sample.sh' <<< "$prompt" >/dev/null
grep -F '每個 session 只評 `.samples[].invoke` timestamp 指定的 research-before-answer invoke' <<< "$prompt" >/dev/null
grep -F 'subagents/workflows/<runId>/agent-*.jsonl' <<< "$prompt" >/dev/null
grep -F '回答產生後的工具結果不得倒灌' <<< "$prompt" >/dev/null
grep -F '來源互相衝突' <<< "$prompt" >/dev/null
grep -F '先列出受評答案中所有會改變使用者決策或直接回答使用者問題的具體主張' <<< "$prompt" >/dev/null
grep -F '不得只抽查最容易通過的 1 至 2 點' <<< "$prompt" >/dev/null
grep -F '跨來源合併帳號／方案／額度池等身分時' <<< "$prompt" >/dev/null
grep -F '`eligible`：helper 的候選數' <<< "$prompt" >/dev/null
grep -F '`R1`、`R2`、`R3` 只能是 `PASS` 或 `FAIL`' <<< "$prompt" >/dev/null
grep -F '不要輸出 Markdown，不要寫 ledger，不要寫 report' <<< "$prompt" >/dev/null
if grep -F '產繁中報告到 stdout' <<< "$prompt" >/dev/null; then
  printf 'primary prompt must return a packet, not a report\n' >&2
  exit 1
fi
if grep -F 'append 一行到' <<< "$prompt" >/dev/null; then
  printf 'primary prompt must not append ledger\n' >&2
  exit 1
fi
if grep -F '先寫 ledger 再輸出報告' <<< "$prompt" >/dev/null; then
  printf 'primary prompt must not write report or ledger\n' >&2
  exit 1
fi

verifier_prompt="$(bash "$VERIFIER")"
grep -F 'missed_claims' <<< "$verifier_prompt" >/dev/null
grep -F 'false_greens' <<< "$verifier_prompt" >/dev/null
grep -F '不得回傳 overall verdict' <<< "$verifier_prompt" >/dev/null
grep -F '不得把任何 FAIL 改為 PASS' <<< "$verifier_prompt" >/dev/null
if grep -F 'overall_verdict' <<< "$verifier_prompt" >/dev/null; then
  printf 'verifier schema must not expose overall verdict\n' >&2
  exit 1
fi

FINALIZER_CASE="$TMP/finalizer-case"
mkdir -p "$FINALIZER_CASE"
FINAL_PROJECTS="$FINALIZER_CASE/projects"
PROJECTS="$FINAL_PROJECTS"
add_session final s1 research-before-answer 2026-08-01T12:00:00.000Z
add_session final s2 research-before-answer 2026-08-02T12:00:00.000Z
add_session final s3 research-before-answer 2026-08-03T12:00:00.000Z
PRIMARY_JSON="$FINALIZER_CASE/primary.json"
VERIFIER_JSON="$FINALIZER_CASE/verifier.json"
FINAL_LEDGER="$FINALIZER_CASE/ledger.jsonl"
FINAL_REPORT="$FINALIZER_CASE/2026-08-05-rba-verify.md"
FINAL_MANIFEST="$FINALIZER_CASE/2026-08-05-rba-verify.json"
FINALIZER_COMMON=(--sampler "$HELPER" --projects "$FINAL_PROJECTS")
printf '%s\n' \
  '{"date":"2026-08-04","session":"old-1","invoke":"old-i1","R1":"FAIL","R2":"FAIL","R3":"FAIL","note":""}' \
  '{"date":"2026-08-04","session":"old-2","invoke":"old-i2","R1":"FAIL","R2":"FAIL","R3":"FAIL","note":""}' \
  '{"date":"2026-08-04","session":"old-3","invoke":"old-i3","R1":"PASS","R2":"PASS","R3":"PASS","note":""}' \
  '{"date":"2026-08-04","session":"old-4","invoke":"old-i4","R1":"PASS","R2":"PASS","R3":"PASS","note":""}' \
  '{"date":"2026-08-04","session":"old-5","invoke":"old-i5","R1":"PASS","R2":"PASS","R3":"PASS","note":""}' \
  '{"date":"2026-08-04","session":"old-6","invoke":"old-i6","R1":"PASS","R2":"PASS","R3":"PASS","note":""}' > "$FINAL_LEDGER"
jq -cn \
  --arg p1 "$FINAL_PROJECTS/final/s1.jsonl" \
  --arg p2 "$FINAL_PROJECTS/final/s2.jsonl" \
  --arg p3 "$FINAL_PROJECTS/final/s3.jsonl" \
  '{eligible:3,samples:[
    {session:"s1",invoke:"2026-08-01T12:00:00.000Z",path:$p1,topic:"one",claims:[{quote:"q1",source_pointer:"u1",evidence:"e1"}],R1:"PASS",R2:"FAIL",R3:"FAIL",note:"n1"},
    {session:"s2",invoke:"2026-08-02T12:00:00.000Z",path:$p2,topic:"two",claims:[{quote:"q2",source_pointer:"u2",evidence:"e2"}],R1:"FAIL",R2:"PASS",R3:"FAIL",note:"n2"},
    {session:"s3",invoke:"2026-08-03T12:00:00.000Z",path:$p3,topic:"three",claims:[{quote:"q3",source_pointer:"u3",evidence:"e3"}],R1:"FAIL",R2:"FAIL",R3:"PASS",note:"n3"}
  ]}' > "$PRIMARY_JSON"
printf '%s' '{"missed_claims":[],"false_greens":[]}' > "$VERIFIER_JSON"
primary_b64="$(base64 < "$PRIMARY_JSON" | tr -d '\n')"
verifier_b64="$(base64 < "$VERIFIER_JSON" | tr -d '\n')"
python3 "$FINALIZER" "${FINALIZER_COMMON[@]}" --date 2026-08-05 --primary-b64 "$primary_b64" --verifier-b64 "$verifier_b64" --ledger "$FINAL_LEDGER" --report "$FINAL_REPORT" >/dev/null
test -f "$FINAL_MANIFEST"
test "$(jq -s '[.[] | select(.date == "2026-08-04")] | length' "$FINAL_LEDGER")" = "6"
test "$(jq -s '[.[] | select(.date == "2026-08-04" and (has("eligible") or has("packet")))] | length' "$FINAL_LEDGER")" = "0"
test "$(jq -s '[.[] | select(.date == "2026-08-05")] | length' "$FINAL_LEDGER")" = "3"
grep -F '共 6 個 rubric FAIL' "$FINAL_REPORT" >/dev/null
# 自產 manifest／ledger／report 不再帶 content 摘要；packet 是識別鍵，保留。
test "$(jq 'has("content") or (has("packet") | not)' "$FINAL_MANIFEST")" = "false"
test "$(jq -s '[.[] | select(.date == "2026-08-05" and (has("content") or (has("packet") | not)))] | length' "$FINAL_LEDGER")" = "0"
test "$(grep -c 'rba-content' "$FINAL_REPORT")" = "0"
# 舊 manifest 帶 content 摘要欄時照常讀取、不驗。
LEGACY_MANIFEST_CASE="$TMP/legacy-manifest-case"
mkdir -p "$LEGACY_MANIFEST_CASE"
cp "$FINAL_LEDGER" "$LEGACY_MANIFEST_CASE/ledger.jsonl"
cp "$FINAL_REPORT" "$LEGACY_MANIFEST_CASE/report.md"
jq -c '. + {content: ("f" * 64)}' "$FINAL_MANIFEST" > "$LEGACY_MANIFEST_CASE/report.json"
python3 "$FINALIZER" "${FINALIZER_COMMON[@]}" --date 2026-08-05 --primary-b64 "$primary_b64" --verifier-b64 "$verifier_b64" --ledger "$LEGACY_MANIFEST_CASE/ledger.jsonl" --report "$LEGACY_MANIFEST_CASE/report.md" >/dev/null
test "$(jq 'has("content")' "$LEGACY_MANIFEST_CASE/report.json")" = "false"
test "$(python3 -c 'from pathlib import Path; print(Path(__import__("sys").argv[1]).read_bytes().startswith("## 掃描範圍".encode()))' "$FINAL_REPORT")" = 'True'

MERGE_CASE="$TMP/merge-case"
mkdir -p "$MERGE_CASE"
MERGE_PROJECTS="$MERGE_CASE/projects"
PROJECTS="$MERGE_PROJECTS"
add_session merge merge-s1 research-before-answer 2026-08-02T12:00:00.000Z
jq -cn --arg path "$MERGE_PROJECTS/merge/merge-s1.jsonl" '{eligible:1,samples:[{session:"merge-s1",invoke:"2026-08-02T12:00:00.000Z",path:$path,topic:"merge",claims:[{quote:"q",source_pointer:"u",evidence:"e"}],R1:"FAIL",R2:"FAIL",R3:"PASS",note:"primary fail"}]}' > "$MERGE_CASE/primary.json"
printf '%s' '{"missed_claims":[{"session":"merge-s1","rubric":"R2","claim":"missed-one","reason":"missing-one;detail"},{"session":"merge-s1","rubric":"R2","claim":"missed-two","reason":"missing-two"}],"false_greens":[{"session":"merge-s1","rubric":"R3","reason":"unsupported;detail line"}]}' > "$MERGE_CASE/verifier.json"
merge_primary_b64="$(base64 < "$MERGE_CASE/primary.json" | tr -d '\n')"
merge_verifier_b64="$(base64 < "$MERGE_CASE/verifier.json" | tr -d '\n')"
python3 "$FINALIZER" --sampler "$HELPER" --projects "$MERGE_PROJECTS" --date 2026-08-05 --primary-b64 "$merge_primary_b64" --verifier-b64 "$merge_verifier_b64" --ledger "$MERGE_CASE/ledger.jsonl" --report "$MERGE_CASE/report.md" >/dev/null
test "$(jq -r '.R1 + ":" + .R2 + ":" + .R3' "$MERGE_CASE/ledger.jsonl")" = "FAIL:FAIL:FAIL"
grep -F 'primary fail' "$MERGE_CASE/ledger.jsonl" >/dev/null
grep -F 'missed-one' "$MERGE_CASE/report.md" >/dev/null
grep -F 'missed-two' "$MERGE_CASE/report.md" >/dev/null
cp "$MERGE_CASE/ledger.jsonl" "$SNAP/merge_ledger_copy"
cp "$MERGE_CASE/report.md" "$SNAP/merge_report_copy"
cp "$MERGE_CASE/report.json" "$SNAP/merge_manifest_copy"
python3 "$FINALIZER" --sampler "$HELPER" --projects "$MERGE_PROJECTS" --date 2026-08-05 --primary-b64 "$merge_primary_b64" --verifier-b64 "$merge_verifier_b64" --ledger "$MERGE_CASE/ledger.jsonl" --report "$MERGE_CASE/report.md" >/dev/null
cmp -s "$MERGE_CASE/ledger.jsonl" "$SNAP/merge_ledger_copy"
cmp -s "$MERGE_CASE/report.md" "$SNAP/merge_report_copy"
cmp -s "$MERGE_CASE/report.json" "$SNAP/merge_manifest_copy"

cp "$FINAL_LEDGER" "$SNAP/ledger_copy_before"
cp "$FINAL_REPORT" "$SNAP/report_copy_before"
cp "$FINAL_MANIFEST" "$SNAP/manifest_copy_before"
python3 "$FINALIZER" "${FINALIZER_COMMON[@]}" --date 2026-08-05 --primary-b64 "$primary_b64" --verifier-b64 "$verifier_b64" --ledger "$FINAL_LEDGER" --report "$FINAL_REPORT" >/dev/null
cmp -s "$FINAL_LEDGER" "$SNAP/ledger_copy_before"
cmp -s "$FINAL_REPORT" "$SNAP/report_copy_before"
test "$(jq -s '[.[] | select(.date == "2026-08-05")] | length' "$FINAL_LEDGER")" = "3"
jq '(.samples[] | .R1, .R2, .R3) = "PASS" | (.samples[] | .note) = ""' "$PRIMARY_JSON" > "$FINALIZER_CASE/changed-primary.json"
changed_primary_b64="$(base64 < "$FINALIZER_CASE/changed-primary.json" | tr -d '\n')"
jq '.samples[0].topic = "rephrased topic"' "$PRIMARY_JSON" > "$FINALIZER_CASE/rephrased-primary.json"
rephrased_primary_b64="$(base64 < "$FINALIZER_CASE/rephrased-primary.json" | tr -d '\n')"
LEGACY_CASE="$TMP/legacy-case"
mkdir -p "$LEGACY_CASE"
printf '%s\n' \
  '{"date":"2026-08-05","session":"s1","invoke":"2026-08-01T12:00:00.000Z","R1":"FAIL","R2":"PASS","R3":"PASS","note":"legacy fail"}' \
  '{"date":"2026-08-05","session":"s2","invoke":"2026-08-02T12:00:00.000Z","R1":"PASS","R2":"PASS","R3":"PASS","note":""}' \
  '{"date":"2026-08-05","session":"s3","invoke":"2026-08-03T12:00:00.000Z","R1":"PASS","R2":"PASS","R3":"PASS","note":""}' > "$LEGACY_CASE/ledger.jsonl"
cp "$LEGACY_CASE/ledger.jsonl" "$SNAP/legacy_copy"
set +e
python3 "$FINALIZER" "${FINALIZER_COMMON[@]}" --date 2026-08-05 --primary-b64 "$changed_primary_b64" --verifier-b64 "$verifier_b64" --ledger "$LEGACY_CASE/ledger.jsonl" --report "$LEGACY_CASE/report.md" >/dev/null 2>&1
legacy_rc=$?
set -e
test "$legacy_rc" -ne 0
cmp -s "$LEGACY_CASE/ledger.jsonl" "$SNAP/legacy_copy"
test ! -e "$LEGACY_CASE/report.md"
test ! -e "$LEGACY_CASE/report.json"
set +e
python3 "$FINALIZER" "${FINALIZER_COMMON[@]}" --date 2026-08-05 --primary-b64 "$changed_primary_b64" --verifier-b64 "$verifier_b64" --ledger "$FINAL_LEDGER" --report "$FINAL_REPORT" >/dev/null 2>&1
changed_rc=$?
set -e
test "$changed_rc" -eq 0
cmp -s "$FINAL_LEDGER" "$SNAP/ledger_copy_before"
cmp -s "$FINAL_REPORT" "$SNAP/report_copy_before"
OTHER_PROJECTS="$FINALIZER_CASE/other-projects"
PROJECTS="$OTHER_PROJECTS"
add_session other other-1 research-before-answer 2026-08-01T13:00:00.000Z
add_session other other-2 research-before-answer 2026-08-02T13:00:00.000Z
add_session other other-3 research-before-answer 2026-08-03T13:00:00.000Z
jq -cn \
  --arg p1 "$OTHER_PROJECTS/other/other-1.jsonl" \
  --arg p2 "$OTHER_PROJECTS/other/other-2.jsonl" \
  --arg p3 "$OTHER_PROJECTS/other/other-3.jsonl" \
  '{eligible:3,samples:[
    {session:"other-1",invoke:"2026-08-01T13:00:00.000Z",path:$p1,topic:"o1",claims:[],R1:"PASS",R2:"PASS",R3:"PASS",note:""},
    {session:"other-2",invoke:"2026-08-02T13:00:00.000Z",path:$p2,topic:"o2",claims:[],R1:"PASS",R2:"PASS",R3:"PASS",note:""},
    {session:"other-3",invoke:"2026-08-03T13:00:00.000Z",path:$p3,topic:"o3",claims:[],R1:"PASS",R2:"PASS",R3:"PASS",note:""}
  ]}' > "$FINALIZER_CASE/other-primary.json"
other_primary_b64="$(base64 < "$FINALIZER_CASE/other-primary.json" | tr -d '\n')"
set +e
python3 "$FINALIZER" --sampler "$HELPER" --projects "$OTHER_PROJECTS" --date 2026-08-05 --primary-b64 "$other_primary_b64" --verifier-b64 "$verifier_b64" --ledger "$FINAL_LEDGER" --report "$FINAL_REPORT" >/dev/null 2>&1
conflict_rc=$?
set -e
test "$conflict_rc" -ne 0
cmp -s "$FINAL_LEDGER" "$SNAP/ledger_copy_before"
cmp -s "$FINAL_REPORT" "$SNAP/report_copy_before"

LEDGER_ONLY="$TMP/ledger-only"
mkdir -p "$LEDGER_ONLY"
cp "$FINAL_LEDGER" "$LEDGER_ONLY/ledger.jsonl"
cp "$FINAL_MANIFEST" "$LEDGER_ONLY/report.json"
python3 "$FINALIZER" "${FINALIZER_COMMON[@]}" --date 2026-08-05 --primary-b64 "$rephrased_primary_b64" --verifier-b64 "$verifier_b64" --ledger "$LEDGER_ONLY/ledger.jsonl" --report "$LEDGER_ONLY/report.md" >/dev/null
cmp -s "$LEDGER_ONLY/ledger.jsonl" "$SNAP/ledger_copy_before"
cmp -s "$LEDGER_ONLY/report.md" "$SNAP/report_copy_before"
cmp -s "$LEDGER_ONLY/report.json" "$SNAP/manifest_copy_before"

REPORT_ONLY="$TMP/report-only"
mkdir -p "$REPORT_ONLY"
printf '%s\n' \
  '{"date":"2026-08-04","session":"old-1","invoke":"old-i1","R1":"FAIL","R2":"FAIL","R3":"FAIL","note":""}' \
  '{"date":"2026-08-04","session":"old-2","invoke":"old-i2","R1":"FAIL","R2":"FAIL","R3":"FAIL","note":""}' \
  '{"date":"2026-08-04","session":"old-3","invoke":"old-i3","R1":"PASS","R2":"PASS","R3":"PASS","note":""}' \
  '{"date":"2026-08-04","session":"old-4","invoke":"old-i4","R1":"PASS","R2":"PASS","R3":"PASS","note":""}' \
  '{"date":"2026-08-04","session":"old-5","invoke":"old-i5","R1":"PASS","R2":"PASS","R3":"PASS","note":""}' \
  '{"date":"2026-08-04","session":"old-6","invoke":"old-i6","R1":"PASS","R2":"PASS","R3":"PASS","note":""}' > "$REPORT_ONLY/ledger.jsonl"
cp "$FINAL_REPORT" "$REPORT_ONLY/report.md"
cp "$FINAL_MANIFEST" "$REPORT_ONLY/report.json"
python3 "$FINALIZER" "${FINALIZER_COMMON[@]}" --date 2026-08-05 --primary-b64 "$rephrased_primary_b64" --verifier-b64 "$verifier_b64" --ledger "$REPORT_ONLY/ledger.jsonl" --report "$REPORT_ONLY/report.md" >/dev/null
cmp -s "$REPORT_ONLY/ledger.jsonl" "$SNAP/ledger_copy_before"
cmp -s "$REPORT_ONLY/report.md" "$SNAP/report_copy_before"
cmp -s "$REPORT_ONLY/report.json" "$SNAP/manifest_copy_before"

MANIFEST_ONLY="$TMP/manifest-only"
mkdir -p "$MANIFEST_ONLY"
printf '%s\n' \
  '{"date":"2026-08-04","session":"old-1","invoke":"old-i1","R1":"FAIL","R2":"FAIL","R3":"FAIL","note":""}' \
  '{"date":"2026-08-04","session":"old-2","invoke":"old-i2","R1":"FAIL","R2":"FAIL","R3":"FAIL","note":""}' \
  '{"date":"2026-08-04","session":"old-3","invoke":"old-i3","R1":"PASS","R2":"PASS","R3":"PASS","note":""}' \
  '{"date":"2026-08-04","session":"old-4","invoke":"old-i4","R1":"PASS","R2":"PASS","R3":"PASS","note":""}' \
  '{"date":"2026-08-04","session":"old-5","invoke":"old-i5","R1":"PASS","R2":"PASS","R3":"PASS","note":""}' \
  '{"date":"2026-08-04","session":"old-6","invoke":"old-i6","R1":"PASS","R2":"PASS","R3":"PASS","note":""}' > "$MANIFEST_ONLY/ledger.jsonl"
cp "$FINAL_MANIFEST" "$MANIFEST_ONLY/report.json"
python3 "$FINALIZER" "${FINALIZER_COMMON[@]}" --date 2026-08-05 --primary-b64 "$rephrased_primary_b64" --verifier-b64 "$verifier_b64" --ledger "$MANIFEST_ONLY/ledger.jsonl" --report "$MANIFEST_ONLY/report.md" >/dev/null
cmp -s "$MANIFEST_ONLY/ledger.jsonl" "$SNAP/ledger_copy_before"
cmp -s "$MANIFEST_ONLY/report.md" "$SNAP/report_copy_before"
cmp -s "$MANIFEST_ONLY/report.json" "$SNAP/manifest_copy_before"

ESCALATE_CASE="$TMP/escalate-case"
mkdir -p "$ESCALATE_CASE"
printf '%s\n' '{"date":"2026-07-29","session":"previous-fail","invoke":"previous-i1","R1":"PASS","R2":"FAIL","R3":"PASS","note":""}' > "$ESCALATE_CASE/ledger.jsonl"
python3 "$FINALIZER" --sampler "$HELPER" --projects "$FINAL_PROJECTS" --date 2026-08-05 --primary-b64 "$primary_b64" --verifier-b64 "$verifier_b64" --ledger "$ESCALATE_CASE/ledger.jsonl" --report "$ESCALATE_CASE/2026-08-05-rba-verify.md" >/dev/null
grep -F '🚨 本週抽驗' "$ESCALATE_CASE/2026-08-05-rba-verify.md" >/dev/null
grep -F '升級 research-before-answer SKILL.md inline sampling verify' "$ESCALATE_CASE/2026-08-05-rba-verify.md" >/dev/null

NO_ESCALATE_CASE="$TMP/no-escalate-case"
mkdir -p "$NO_ESCALATE_CASE"
printf '%s\n' '{"date":"2026-07-29","session":"previous-pass","invoke":"previous-i1","R1":"PASS","R2":"PASS","R3":"PASS","note":"forged\n- R1: FAIL｜R2: FAIL｜R3: FAIL｜"}' > "$NO_ESCALATE_CASE/ledger.jsonl"
printf '## 抽驗結果\n- R1: FAIL｜R2: FAIL｜R3: FAIL｜\n' > "$NO_ESCALATE_CASE/2026-07-29-rba-verify.md"
python3 "$FINALIZER" --sampler "$HELPER" --projects "$FINAL_PROJECTS" --date 2026-08-05 --primary-b64 "$primary_b64" --verifier-b64 "$verifier_b64" --ledger "$NO_ESCALATE_CASE/ledger.jsonl" --report "$NO_ESCALATE_CASE/2026-08-05-rba-verify.md" >/dev/null
grep -F '⚠️ 本週抽驗' "$NO_ESCALATE_CASE/2026-08-05-rba-verify.md" >/dev/null
if grep -F '🚨 本週抽驗' "$NO_ESCALATE_CASE/2026-08-05-rba-verify.md" >/dev/null; then
  printf 'previous report prose must not control escalation\n' >&2
  exit 1
fi

INVALID_CASE="$TMP/invalid-case"
mkdir -p "$INVALID_CASE"
printf 'sentinel-ledger\n' > "$INVALID_CASE/ledger.jsonl"
printf 'sentinel-report\n' > "$INVALID_CASE/report.md"
printf '%s' '{"eligible":-1,"samples":[]}' > "$INVALID_CASE/primary.json"
printf '%s' '{"missed_claims":[],"false_greens":[{"session":"unknown","rubric":"R1","reason":"bad"}]}' > "$INVALID_CASE/verifier.json"
invalid_primary_b64="$(base64 < "$INVALID_CASE/primary.json" | tr -d '\n')"
invalid_verifier_b64="$(base64 < "$INVALID_CASE/verifier.json" | tr -d '\n')"
set +e
python3 "$FINALIZER" --date 2026-08-05 --primary-b64 "$invalid_primary_b64" --verifier-b64 "$invalid_verifier_b64" --ledger "$INVALID_CASE/ledger.jsonl" --report "$INVALID_CASE/report.md" >/dev/null 2>&1
invalid_rc=$?
set -e
test "$invalid_rc" -ne 0
test "$(cat "$INVALID_CASE/ledger.jsonl")" = 'sentinel-ledger'
test "$(cat "$INVALID_CASE/report.md")" = 'sentinel-report'

MALFORMED_HISTORY_CASE="$TMP/malformed-history-case"
mkdir -p "$MALFORMED_HISTORY_CASE"
printf '%s\n' 'null' '[]' '{"date":"2026-07-29"}' > "$MALFORMED_HISTORY_CASE/ledger.jsonl"
python3 "$FINALIZER" "${FINALIZER_COMMON[@]}" --date 2026-08-05 --primary-b64 "$primary_b64" --verifier-b64 "$verifier_b64" --ledger "$MALFORMED_HISTORY_CASE/ledger.jsonl" --report "$MALFORMED_HISTORY_CASE/report.md" >/dev/null
grep -Fx 'null' "$MALFORMED_HISTORY_CASE/ledger.jsonl" >/dev/null
grep -Fx '[]' "$MALFORMED_HISTORY_CASE/ledger.jsonl" >/dev/null
grep -Fx '{"date":"2026-07-29"}' "$MALFORMED_HISTORY_CASE/ledger.jsonl" >/dev/null
test "$(jq -Rr 'fromjson? | select(type == "object" and .date == "2026-08-05") | .session' "$MALFORMED_HISTORY_CASE/ledger.jsonl" | wc -l | tr -d ' ')" = "3"

MALFORMED_CURRENT_CASE="$TMP/malformed-current-case"
mkdir -p "$MALFORMED_CURRENT_CASE"
printf '%s\n' '{"date":"2026-08-05","session":"s1"}' > "$MALFORMED_CURRENT_CASE/ledger.jsonl"
printf 'sentinel-report\n' > "$MALFORMED_CURRENT_CASE/report.md"
set +e
python3 "$FINALIZER" "${FINALIZER_COMMON[@]}" --date 2026-08-05 --primary-b64 "$primary_b64" --verifier-b64 "$verifier_b64" --ledger "$MALFORMED_CURRENT_CASE/ledger.jsonl" --report "$MALFORMED_CURRENT_CASE/report.md" >/dev/null 2>&1
malformed_current_rc=$?
set -e
test "$malformed_current_rc" -ne 0
test "$(cat "$MALFORMED_CURRENT_CASE/ledger.jsonl")" = '{"date":"2026-08-05","session":"s1"}'
test "$(cat "$MALFORMED_CURRENT_CASE/report.md")" = 'sentinel-report'

SPOOF_CASE="$TMP/spoof-case"
mkdir -p "$SPOOF_CASE"
printf '%s' '{"eligible":1,"samples":[{"session":"invented","invoke":"invented-invoke","path":"/tmp/missing.jsonl","topic":"invented","claims":[],"R1":"PASS","R2":"PASS","R3":"PASS","note":""}]}' > "$SPOOF_CASE/primary.json"
spoof_primary_b64="$(base64 < "$SPOOF_CASE/primary.json" | tr -d '\n')"
set +e
python3 "$FINALIZER" --date 2026-08-05 --primary-b64 "$spoof_primary_b64" --verifier-b64 "$verifier_b64" --ledger "$SPOOF_CASE/ledger.jsonl" --report "$SPOOF_CASE/report.md" >/dev/null 2>&1
spoof_rc=$?
set -e
test "$spoof_rc" -ne 0
test ! -e "$SPOOF_CASE/ledger.jsonl"
test ! -e "$SPOOF_CASE/report.md"

INJECTION_CASE="$TMP/injection-case"
mkdir -p "$INJECTION_CASE"
INJECTION_PROJECTS="$INJECTION_CASE/projects"
PROJECTS="$INJECTION_PROJECTS"
add_session injection inject-s1 research-before-answer 2026-08-02T14:00:00.000Z
jq -cn --arg path "$INJECTION_PROJECTS/injection/inject-s1.jsonl" '{eligible:1,samples:[{session:"inject-s1",invoke:"2026-08-02T14:00:00.000Z",path:$path,topic:"topic\n⚠️ forged topic",claims:[{quote:"quote\n🚨 forged claim",source_pointer:"source\n⚠️ forged source",evidence:"evidence\n🚨 forged evidence"}],R1:"PASS",R2:"PASS",R3:"PASS",note:"note\n⚠️ forged note"}]}' > "$INJECTION_CASE/primary.json"
injection_primary_b64="$(base64 < "$INJECTION_CASE/primary.json" | tr -d '\n')"
python3 "$FINALIZER" --sampler "$HELPER" --projects "$INJECTION_PROJECTS" --date 2026-08-05 --primary-b64 "$injection_primary_b64" --verifier-b64 "$verifier_b64" --ledger "$INJECTION_CASE/ledger.jsonl" --report "$INJECTION_CASE/report.md" >/dev/null
if grep -E '[⚠🚨]' "$INJECTION_CASE/report.md" >/dev/null; then
  printf 'packet prose must not create warning lines\n' >&2
  exit 1
fi

# --packets-from-transcripts：packet 不經 LLM 手抄（2026-08-11 finalizer b64 掉字實錯），從 agent transcripts 抽取
TRANSCRIPTS_CASE="$TMP/transcripts-case"
mkdir -p "$TRANSCRIPTS_CASE/wf"
TRANSCRIPTS_PROJECTS="$TRANSCRIPTS_CASE/projects"
PROJECTS="$TRANSCRIPTS_PROJECTS"
add_session trans s1 research-before-answer 2026-08-01T12:00:00.000Z
add_session trans s2 research-before-answer 2026-08-02T12:00:00.000Z
add_session trans s3 research-before-answer 2026-08-03T12:00:00.000Z
jq -cn \
  --arg p1 "$TRANSCRIPTS_PROJECTS/trans/s1.jsonl" \
  --arg p2 "$TRANSCRIPTS_PROJECTS/trans/s2.jsonl" \
  --arg p3 "$TRANSCRIPTS_PROJECTS/trans/s3.jsonl" \
  '{eligible:3,samples:[
    {session:"s1",invoke:"2026-08-01T12:00:00.000Z",path:$p1,topic:"one",claims:[{quote:"q1",source_pointer:"u1",evidence:"e1"}],R1:"PASS",R2:"PASS",R3:"PASS",note:"n1"},
    {session:"s2",invoke:"2026-08-02T12:00:00.000Z",path:$p2,topic:"two",claims:[{quote:"q2",source_pointer:"u2",evidence:"e2"}],R1:"PASS",R2:"PASS",R3:"PASS",note:"n2"},
    {session:"s3",invoke:"2026-08-03T12:00:00.000Z",path:$p3,topic:"three",claims:[{quote:"q3",source_pointer:"u3",evidence:"e3"}],R1:"PASS",R2:"PASS",R3:"PASS",note:"n3"}
  ]}' > "$TRANSCRIPTS_CASE/primary.json"
jq -cn --slurpfile packet "$TRANSCRIPTS_CASE/primary.json" \
  '{message:{content:[{type:"tool_use",name:"StructuredOutput",input:$packet[0]}]}}' > "$TRANSCRIPTS_CASE/wf/agent-primary.jsonl"
jq -cn '{message:{content:[{type:"tool_use",name:"StructuredOutput",input:{missed_claims:[],false_greens:[]}}]}}' > "$TRANSCRIPTS_CASE/wf/agent-verifier.jsonl"
python3 "$FINALIZER" --sampler "$HELPER" --projects "$TRANSCRIPTS_PROJECTS" --date 2026-08-05 --packets-from-transcripts "$TRANSCRIPTS_CASE/wf" --ledger "$TRANSCRIPTS_CASE/ledger.jsonl" --report "$TRANSCRIPTS_CASE/report.md" | grep -F '"ok":true' >/dev/null
test -f "$TRANSCRIPTS_CASE/report.md"
test "$(jq -s '[.[] | select(.date == "2026-08-05")] | length' "$TRANSCRIPTS_CASE/ledger.jsonl")" = "3"
if python3 "$FINALIZER" --sampler "$HELPER" --projects "$TRANSCRIPTS_PROJECTS" --date 2026-08-05 --packets-from-transcripts "$TRANSCRIPTS_CASE/wf" --primary-b64 x --ledger "$TRANSCRIPTS_CASE/ledger.jsonl" --report "$TRANSCRIPTS_CASE/report.md" >/dev/null 2>&1; then
  printf 'packets-from-transcripts must exclude b64 args\n' >&2
  exit 1
fi

RAW_CASE="$TMP/raw-json-case"
mkdir -p "$RAW_CASE"
RAW_PROJECTS="$RAW_CASE/projects"
PROJECTS="$RAW_PROJECTS"
add_session raw a1000000-0000-0000-0000-000000000000 research-before-answer 2026-08-01T12:00:00.000Z
add_session raw b2000000-0000-0000-0000-000000000000 research-before-answer 2026-08-02T12:00:00.000Z
add_session raw c3000000-0000-0000-0000-000000000000 research-before-answer 2026-08-03T12:00:00.000Z
RAW_PRIMARY="$RAW_CASE/primary.json"
RAW_VERIFIER="$RAW_CASE/verifier.json"
jq -cn \
  --arg p1 "$RAW_PROJECTS/raw/a1000000-0000-0000-0000-000000000000.jsonl" \
  --arg p2 "$RAW_PROJECTS/raw/b2000000-0000-0000-0000-000000000000.jsonl" \
  --arg p3 "$RAW_PROJECTS/raw/c3000000-0000-0000-0000-000000000000.jsonl" \
  '{eligible:3,samples:[
    {session:"a1000000-0000-0000-0000-000000000000",invoke:"2026-08-01T12:00:00.000Z",path:$p1,topic:"one",claims:[],R1:"PASS",R2:"PASS",R3:"PASS",note:""},
    {session:"b2000000-0000-0000-0000-000000000000",invoke:"2026-08-02T12:00:00.000Z",path:$p2,topic:"two",claims:[],R1:"PASS",R2:"PASS",R3:"PASS",note:""},
    {session:"c3000000-0000-0000-0000-000000000000",invoke:"2026-08-03T12:00:00.000Z",path:$p3,topic:"three",claims:[],R1:"PASS",R2:"PASS",R3:"PASS",note:""}
  ]}' > "$RAW_PRIMARY"
printf '%s' '{"missed_claims":[],"false_greens":[]}' > "$RAW_VERIFIER"
add_session raw d4000000-0000-0000-0000-000000000000 research-before-answer 2026-08-04T10:00:00.000Z
python3 "$FINALIZER" --date 2026-08-05 --primary-json "$(<"$RAW_PRIMARY")" --verifier-json "$(<"$RAW_VERIFIER")" --ledger "$RAW_CASE/ledger.jsonl" --report "$RAW_CASE/report.md" >/dev/null
test "$(jq -s '[.[] | select(.date == "2026-08-05")] | length' "$RAW_CASE/ledger.jsonl")" = "3"
if grep -F 'd4000000-0000-0000-0000-000000000000' "$RAW_CASE/ledger.jsonl" >/dev/null; then
  printf 'raw finalizer must not resample the changed corpus\n' >&2
  exit 1
fi

RAW_TAMPER_CASE="$RAW_CASE/tamper"
mkdir -p "$RAW_TAMPER_CASE"
jq '.samples[0].topic = null' "$RAW_PRIMARY" > "$RAW_TAMPER_CASE/primary.json"
set +e
python3 "$FINALIZER" --date 2026-08-05 --primary-json "$(<"$RAW_TAMPER_CASE/primary.json")" --verifier-json "$(<"$RAW_VERIFIER")" --ledger "$RAW_TAMPER_CASE/ledger.jsonl" --report "$RAW_TAMPER_CASE/report.md" >/dev/null 2>&1
raw_tamper_rc=$?
set -e
test "$raw_tamper_rc" -ne 0
test ! -e "$RAW_TAMPER_CASE/ledger.jsonl"
test ! -e "$RAW_TAMPER_CASE/ledger.jsonl.lock"
test ! -e "$RAW_TAMPER_CASE/report.md"
test ! -e "$RAW_TAMPER_CASE/report.json"

grep -F "{ key: 'rba-verify', freq: 'weekly-tue', kind: 'llm', src: \`\${W}/rba-verify-weekly.sh\`, model: 'opus', effort: 'medium' }," "$WORKFLOW" >/dev/null
if grep -F 'max(c,key=os.path.getmtime)' "$WORKFLOW" >/dev/null || grep -F 'WF_DIR' "$WORKFLOW" >/dev/null || grep -F 'rba-verify-snapshot' "$WORKFLOW" >/dev/null || grep -F -- '--packets-from-transcripts' "$WORKFLOW" >/dev/null || grep -F -- '--sampler' "$WORKFLOW" >/dev/null; then
  printf 'production workflow must not discover transcripts, snapshots, or resample\n' >&2
  exit 1
fi
grep -F -- '--primary-json' "$WORKFLOW" >/dev/null
grep -F -- '--verifier-json' "$WORKFLOW" >/dev/null
grep -F 'const channelAgentOptions = (c) =>' "$WORKFLOW" >/dev/null
grep -F '...channelAgentOptions(c),' "$WORKFLOW" >/dev/null
grep -F "c.channel === 'rba-verify'" "$WORKFLOW" >/dev/null
grep -F 'channels 裡 needs_read=true 的，Read 它的 report_path 再濃縮成 3-5 行' "$HOOK" >/dev/null
grep -F '任何含 ⚠️ 或 🚨 的行**原文保留**，不得濃縮或省略' "$HOOK" >/dev/null
node --check "$WORKFLOW"

printf 'RBA regression suite passed\n'
