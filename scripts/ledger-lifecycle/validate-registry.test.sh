#!/usr/bin/env bash
set -u

CLI="$(cd "$(dirname "$0")" && pwd)/validate-registry.py"
TMP="$(mktemp -d)"
REGISTRY="$TMP/registry.json"
OUTPUT="$TMP/output.json"
BAD_REGISTRY="$TMP/bad-registry.json"
BAD_OUTPUT="$TMP/bad-output.json"
RESOLVE_OUTPUT="$TMP/resolve-output.json"
trap 'rm -f "$REGISTRY" "$OUTPUT" "$BAD_REGISTRY" "$BAD_OUTPUT" "$RESOLVE_OUTPUT"; rmdir "$TMP"' EXIT

printf '%s\n' '{"schema_version":1,"scan_roots":["~/Desktop/work/*"],"entries":[{"path":"~/tmp/state.md","kind":"state","threshold":[{"metric":"size_bytes","unit":"bytes","operator":">","value":100}],"action":"提醒"}]}' > "$REGISTRY"

if python3 "$CLI" validate "$REGISTRY" > "$OUTPUT" 2>&1; then
  status=0
else
  status=$?
fi

if [ "$status" -ne 0 ]; then
  printf 'FAIL valid registry exit status: %s\n' "$status"
  cat "$OUTPUT"
  exit 1
fi

python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); raise SystemExit(value["status"] != "pass")' "$OUTPUT" || {
  printf 'FAIL valid registry output: '
  cat "$OUTPUT"
  exit 1
}

printf 'PASS valid registry\n'

if python3 "$CLI" "$REGISTRY" > "$OUTPUT" 2>&1; then
  direct_rc=0
else
  direct_rc=$?
fi

if [ "$direct_rc" -ne 0 ]; then
  printf 'FAIL direct registry CLI exit status: %s\n' "$direct_rc"
  cat "$OUTPUT"
  exit 1
fi

python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); raise SystemExit(value["status"] != "pass")' "$OUTPUT" || {
  printf 'FAIL direct registry CLI output: '
  cat "$OUTPUT"
  exit 1
}

printf 'PASS direct registry CLI\n'

printf '%s\n' '{"schema_version":1' > "$BAD_REGISTRY"

if python3 "$CLI" validate "$BAD_REGISTRY" > "$BAD_OUTPUT" 2>&1; then
  json_rc=0
else
  json_rc=$?
fi

if [ "$json_rc" -eq 0 ]; then
  printf 'FAIL malformed JSON accepted\n'
  cat "$BAD_OUTPUT"
  exit 1
fi

python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); raise SystemExit(not (value["status"] == "fail" and value["errors"][0]["code"] == "invalid_json"))' "$BAD_OUTPUT" || {
  printf 'FAIL malformed JSON diagnostics: '
  cat "$BAD_OUTPUT"
  exit 1
}

printf 'PASS malformed JSON diagnostics\n'

python3 -c 'import sys; open(sys.argv[1], "wb").write(bytes([255]))' "$BAD_REGISTRY"

if python3 "$CLI" validate "$BAD_REGISTRY" > "$BAD_OUTPUT" 2>&1; then
  encoding_rc=0
else
  encoding_rc=$?
fi

if [ "$encoding_rc" -eq 0 ]; then
  printf 'FAIL invalid UTF-8 accepted\n'
  cat "$BAD_OUTPUT"
  exit 1
fi

python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); raise SystemExit(not (value["status"] == "fail" and value["errors"][0]["code"] == "invalid_encoding"))' "$BAD_OUTPUT" || {
  printf 'FAIL invalid UTF-8 diagnostics: '
  cat "$BAD_OUTPUT"
  exit 1
}

printf 'PASS invalid UTF-8 diagnostics\n'

printf '%s\n' '{"schema_version":1,"scan_roots":["~/Desktop/work/*"],"entries":[{"path":"~/tmp/state.md","kind":[],"threshold":[{"metric":"size","unit":"KB","operator":[],"value":null}],"action":"提醒"}]}' > "$BAD_REGISTRY"

if python3 "$CLI" validate "$BAD_REGISTRY" > "$BAD_OUTPUT" 2>&1; then
  type_rc=0
else
  type_rc=$?
fi

if [ "$type_rc" -eq 0 ]; then
  printf 'FAIL invalid JSON value types accepted\n'
  cat "$BAD_OUTPUT"
  exit 1
fi

python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); fields={item["field"] for item in value["errors"]}; raise SystemExit(not (value["status"] == "fail" and "kind" in fields and "threshold[0].operator" in fields and "threshold[0].value" in fields))' "$BAD_OUTPUT" || {
  printf 'FAIL invalid JSON value type diagnostics: '
  cat "$BAD_OUTPUT"
  exit 1
}

printf 'PASS invalid JSON value types\n'

printf '%s\n' '{"schema_version":2,"scan_roots":["~/Desktop/work/*"],"entries":[{"path":"~/tmp/state.md","kind":"state","threshold":[{"metric":"size_bytes","unit":"bytes","operator":">","value":100}],"action":"提醒"}]}' > "$BAD_REGISTRY"

if python3 "$CLI" validate "$BAD_REGISTRY" > "$BAD_OUTPUT" 2>&1; then
  version_rc=0
else
  version_rc=$?
fi

if [ "$version_rc" -eq 0 ]; then
  printf 'FAIL unsupported schema version accepted\n'
  cat "$BAD_OUTPUT"
  exit 1
fi

python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); raise SystemExit(not any(item["field"] == "schema_version" for item in value["errors"]))' "$BAD_OUTPUT" || {
  printf 'FAIL unsupported schema version diagnostics: '
  cat "$BAD_OUTPUT"
  exit 1
}

printf 'PASS unsupported schema version rejected\n'

printf '%s\n' '{"schema_version":1,"scan_roots":["~/Desktop/work/*"],"entries":[{"path":"~/tmp/state.md","kind":"state","threshold":[{"metric":"size_bytes","unit":"bytes","operator":">","value":100}]}]}' > "$BAD_REGISTRY"

if python3 "$CLI" validate "$BAD_REGISTRY" > "$BAD_OUTPUT" 2>&1; then
  bad_rc=0
else
  bad_rc=$?
fi

if [ "$bad_rc" -eq 0 ]; then
  printf 'FAIL missing required field accepted\n'
  cat "$BAD_OUTPUT"
  exit 1
fi

python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); raise SystemExit(not (value["status"] == "fail" and any(item["entry"] == 0 and item["field"] == "action" for item in value["errors"])))' "$BAD_OUTPUT" || {
  printf 'FAIL missing required field diagnostics: '
  cat "$BAD_OUTPUT"
  exit 1
}

printf 'PASS missing required field\n'

printf '%s\n' '{"schema_version":1,"scan_roots":["~/Desktop/work/*"],"entries":[{"path":"~/.claude/logs/*.jsonl","kind":"pure-log"}]}' > "$BAD_REGISTRY"

if python3 "$CLI" validate "$BAD_REGISTRY" > "$BAD_OUTPUT" 2>&1; then
  pure_log_rc=0
else
  pure_log_rc=$?
fi

if [ "$pure_log_rc" -ne 0 ]; then
  printf 'FAIL pure-log without threshold rejected: %s\n' "$pure_log_rc"
  cat "$BAD_OUTPUT"
  exit 1
fi

python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); raise SystemExit(value["status"] != "pass")' "$BAD_OUTPUT" || {
  printf 'FAIL pure-log output: '
  cat "$BAD_OUTPUT"
  exit 1
}

printf 'PASS pure-log without threshold\n'

printf '%s\n' '{"schema_version":1,"scan_roots":["~/Desktop/work/*"],"entries":[{"path":"~/tmp/state.md","kind":"state","threshold":[{"metric":"size","operator":">","value":100}],"action":"提醒"}]}' > "$BAD_REGISTRY"

if python3 "$CLI" validate "$BAD_REGISTRY" > "$BAD_OUTPUT" 2>&1; then
  missing_unit_rc=0
else
  missing_unit_rc=$?
fi

if [ "$missing_unit_rc" -eq 0 ]; then
  printf 'FAIL threshold without unit accepted\n'
  cat "$BAD_OUTPUT"
  exit 1
fi

python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); raise SystemExit(not any(item["field"] == "threshold[0].unit" for item in value["errors"]))' "$BAD_OUTPUT" || {
  printf 'FAIL missing threshold unit diagnostics: '
  cat "$BAD_OUTPUT"
  exit 1
}

printf 'PASS threshold unit required\n'

printf '%s\n' '{"schema_version":1,"scan_roots":["~/Desktop/work/*"],"entries":[{"path":"~/tmp/state.md","kind":"state","threshold":[{"metric":"unknown_metric","unit":"units","operator":">","value":100}],"action":"提醒"}]}' > "$BAD_REGISTRY"

if python3 "$CLI" validate "$BAD_REGISTRY" > "$BAD_OUTPUT" 2>&1; then
  unknown_metric_rc=0
else
  unknown_metric_rc=$?
fi

if [ "$unknown_metric_rc" -eq 0 ]; then
  printf 'FAIL unknown metric accepted\n'
  cat "$BAD_OUTPUT"
  exit 1
fi

python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); raise SystemExit(not any(item["field"] == "threshold[0].metric" for item in value["errors"]))' "$BAD_OUTPUT" || {
  printf 'FAIL unknown metric diagnostics: '
  cat "$BAD_OUTPUT"
  exit 1
}

printf 'PASS unknown metric rejected\n'

printf '%s\n' '{"schema_version":1,"scan_roots":["~/Desktop/work/*"],"entries":[{"path":"~/tmp/state.md","kind":"state","threshold":[{"metric":"size","unit":"widgets","operator":">","value":100}],"action":"提醒"}]}' > "$BAD_REGISTRY"

if python3 "$CLI" validate "$BAD_REGISTRY" > "$BAD_OUTPUT" 2>&1; then
  unknown_unit_rc=0
else
  unknown_unit_rc=$?
fi

if [ "$unknown_unit_rc" -eq 0 ]; then
  printf 'FAIL unknown metric unit accepted\n'
  cat "$BAD_OUTPUT"
  exit 1
fi

python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); raise SystemExit(not any(item["field"] == "threshold[0].unit" for item in value["errors"]))' "$BAD_OUTPUT" || {
  printf 'FAIL unknown metric unit diagnostics: '
  cat "$BAD_OUTPUT"
  exit 1
}

printf 'PASS unknown metric unit rejected\n'

printf '%s\n' "{\"schema_version\":1,\"scan_roots\":[\"$TMP/project/*\"],\"entries\":[{\"path\":\"$TMP/project/*/STATE.md\",\"kind\":\"state\",\"threshold\":[{\"metric\":\"size_bytes\",\"unit\":\"bytes\",\"operator\":\">\",\"value\":100}],\"action\":\"樣板動作\"},{\"path\":\"$TMP/project/demo/STATE.md\",\"kind\":\"state\",\"threshold\":[{\"metric\":\"size_bytes\",\"unit\":\"bytes\",\"operator\":\">\",\"value\":200}],\"action\":\"具體動作\"}]}" > "$BAD_REGISTRY"

if python3 "$CLI" resolve "$BAD_REGISTRY" "$TMP/project/demo/STATE.md" > "$RESOLVE_OUTPUT" 2>&1; then
  resolve_rc=0
else
  resolve_rc=$?
fi

if [ "$resolve_rc" -ne 0 ]; then
  printf 'FAIL resolve exact path exit status: %s\n' "$resolve_rc"
  cat "$RESOLVE_OUTPUT"
  exit 1
fi

python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); raise SystemExit(not (value["matched_by"] == "exact" and value["entry"]["action"] == "具體動作"))' "$RESOLVE_OUTPUT" || {
  printf 'FAIL exact path did not override template: '
  cat "$RESOLVE_OUTPUT"
  exit 1
}

printf 'PASS exact path overrides template\n'

printf '%s\n' "{\"schema_version\":1,\"scan_roots\":[\"$TMP/project/*\"],\"entries\":[{\"path\":\"$TMP/project/*/STATE.md\",\"kind\":\"state\",\"threshold\":[{\"metric\":\"size\",\"unit\":\"KB\",\"operator\":\">\",\"value\":100}],\"action\":\"樣板動作\"}]}" > "$BAD_REGISTRY"

if python3 "$CLI" resolve "$BAD_REGISTRY" "$TMP/project/other/STATE.md" > "$RESOLVE_OUTPUT" 2>&1; then
  template_rc=0
else
  template_rc=$?
fi

if [ "$template_rc" -ne 0 ]; then
  printf 'FAIL resolve template path exit status: %s\n' "$template_rc"
  cat "$RESOLVE_OUTPUT"
  exit 1
fi

python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); raise SystemExit(not (value["matched_by"] == "template" and value["entry"]["action"] == "樣板動作"))' "$RESOLVE_OUTPUT" || {
  printf 'FAIL template path did not resolve: '
  cat "$RESOLVE_OUTPUT"
  exit 1
}

printf 'PASS template path resolves\n'

printf '%s\n' "{\"schema_version\":1,\"scan_roots\":[\"$TMP/project/*\"],\"entries\":[{\"path\":\"$TMP/project/**/STATE.md\",\"kind\":\"state\",\"threshold\":[{\"metric\":\"size\",\"unit\":\"KB\",\"operator\":\">\",\"value\":100}],\"action\":\"遞迴樣板\"}]}" > "$BAD_REGISTRY"

if python3 "$CLI" resolve "$BAD_REGISTRY" "$TMP/project/a/b/STATE.md" > "$RESOLVE_OUTPUT" 2>&1; then
  recursive_rc=0
else
  recursive_rc=$?
fi

if [ "$recursive_rc" -ne 0 ]; then
  printf 'FAIL recursive glob path exit status: %s\n' "$recursive_rc"
  cat "$RESOLVE_OUTPUT"
  exit 1
fi

python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); raise SystemExit(not (value["matched_by"] == "template" and value["entry"]["action"] == "遞迴樣板"))' "$RESOLVE_OUTPUT" || {
  printf 'FAIL recursive glob path did not resolve: '
  cat "$RESOLVE_OUTPUT"
  exit 1
}

printf 'PASS recursive glob path resolves\n'

printf '%s\n' "{\"schema_version\":1,\"scan_roots\":[\"$TMP/project/*\"],\"entries\":[{\"path\":\"$TMP/project/*/STATE.md\",\"kind\":\"state\",\"threshold\":[{\"metric\":\"size\",\"unit\":\"KB\",\"operator\":\">\",\"value\":100}],\"action\":\"寬樣板\"},{\"path\":\"$TMP/project/????/STATE.md\",\"kind\":\"state\",\"threshold\":[{\"metric\":\"size\",\"unit\":\"KB\",\"operator\":\">\",\"value\":200}],\"action\":\"窄樣板\"}]}" > "$BAD_REGISTRY"

if python3 "$CLI" resolve "$BAD_REGISTRY" "$TMP/project/demo/STATE.md" > "$RESOLVE_OUTPUT" 2>&1; then
  specificity_rc=0
else
  specificity_rc=$?
fi

if [ "$specificity_rc" -ne 0 ]; then
  printf 'FAIL template specificity exit status: %s\n' "$specificity_rc"
  cat "$RESOLVE_OUTPUT"
  exit 1
fi

python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); raise SystemExit(value["entry"]["action"] != "窄樣板")' "$RESOLVE_OUTPUT" || {
  printf 'FAIL more specific template did not win: '
  cat "$RESOLVE_OUTPUT"
  exit 1
}

printf 'PASS more specific template wins\n'

printf '%s\n' '{"schema_version":1,"scan_roots":["~/Desktop/work/*"],"entries":[{"path":"~/tmp/state.md","kind":"state","threshold":null,"action":null}]}' > "$BAD_REGISTRY"

if python3 "$CLI" validate "$BAD_REGISTRY" > "$BAD_OUTPUT" 2>&1; then
  null_rc=0
else
  null_rc=$?
fi

if [ "$null_rc" -eq 0 ]; then
  printf 'FAIL empty required values accepted\n'
  cat "$BAD_OUTPUT"
  exit 1
fi

python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); fields={item["field"] for item in value["errors"]}; raise SystemExit(not (value["status"] == "fail" and "threshold" in fields and "action" in fields))' "$BAD_OUTPUT" || {
  printf 'FAIL empty required value diagnostics: '
  cat "$BAD_OUTPUT"
  exit 1
}

printf 'PASS empty required values rejected\n'

printf '%s\n' '{"schema_version":1,"scan_roots":["~/Desktop/work/*"],"entries":[{"path":"~/tmp/one.md","kind":"state"},{"path":"~/tmp/two.md","kind":"unknown"}]}' > "$BAD_REGISTRY"

if python3 "$CLI" validate "$BAD_REGISTRY" > "$BAD_OUTPUT" 2>&1; then
  multi_rc=0
else
  multi_rc=$?
fi

if [ "$multi_rc" -eq 0 ]; then
  printf 'FAIL multiple invalid entries accepted\n'
  cat "$BAD_OUTPUT"
  exit 1
fi

python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); entries={item["entry"] for item in value["errors"]}; raise SystemExit(entries != {0,1})' "$BAD_OUTPUT" || {
  printf 'FAIL diagnostics did not cover every invalid entry: '
  cat "$BAD_OUTPUT"
  exit 1
}

printf 'PASS diagnostics cover every invalid entry\n'

PRODUCTION_REGISTRY="$(cd "$(dirname "$0")/../.." && pwd)/scripts/ledger-lifecycle/registry.json"
if python3 "$CLI" validate "$PRODUCTION_REGISTRY" > "$OUTPUT" 2>&1; then
  production_rc=0
else
  production_rc=$?
fi

if [ "$production_rc" -ne 0 ]; then
  printf 'FAIL production registry: %s\n' "$production_rc"
  cat "$OUTPUT"
  exit 1
fi

python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); raise SystemExit(not {"~/Desktop/work/*","~/Desktop/projects/*","~/code/*"} <= set(value["scan_roots"]))' "$PRODUCTION_REGISTRY" || {
  printf 'FAIL production scan roots\n'
  exit 1
}

printf 'PASS production registry and scan roots\n'
