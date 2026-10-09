#!/usr/bin/env bash
set -u

CLI="$(cd "$(dirname "$0")" && pwd)/agent-contract-validator.mjs"
TMP=$(mktemp -d)
trap 'find "$TMP" -type f -delete; find "$TMP" -depth -type d -delete' EXIT
mkdir -p "$TMP/results"

failures=0
cases=0

run_case() {
  local case_name=$1
  local expected_exit=$2
  local expected_result=$3
  local expected_diagnostic_status=$4
  local expected_surface=$5
  local expected_path=$6
  local expected_line=$7
  local expected_column=$8
  shift 8
  local output="$TMP/results/$case_name.json"
  local actual_exit
  if node "$CLI" "$@" > "$output" 2>&1; then
    actual_exit=0
  else
    actual_exit=$?
  fi
  local check_output
  if check_output=$(
    EXPECTED_EXIT="$expected_exit" \
    ACTUAL_EXIT="$actual_exit" \
    EXPECTED_RESULT="$expected_result" \
    EXPECTED_CODE="$case_name" \
    EXPECTED_DIAGNOSTIC_STATUS="$expected_diagnostic_status" \
    EXPECTED_SURFACE="$expected_surface" \
    EXPECTED_PATH="$expected_path" \
    EXPECTED_LINE="$expected_line" \
    EXPECTED_COLUMN="$expected_column" \
    node --input-type=module -e '
import { readFileSync } from "node:fs"

const data = JSON.parse(readFileSync(process.argv[1], "utf8"))
const expectedResult = process.env.EXPECTED_RESULT
const expectedCode = process.env.EXPECTED_CODE
const expectedDiagnosticStatus = process.env.EXPECTED_DIAGNOSTIC_STATUS
const expectedSurface = process.env.EXPECTED_SURFACE
const expectedPath = process.env.EXPECTED_PATH
const expectedLine = Number(process.env.EXPECTED_LINE)
const expectedColumn = Number(process.env.EXPECTED_COLUMN)
const failures = []
const diagnostic = data.diagnostics?.find(item => item.code === expectedCode)

if (Number(process.env.ACTUAL_EXIT) !== Number(process.env.EXPECTED_EXIT)) failures.push(`exit status ${process.env.ACTUAL_EXIT}`)
if (data.status !== expectedResult) failures.push(`result status ${data.status}`)
if (data.valid !== (expectedResult === "pass")) failures.push(`valid ${JSON.stringify(data.valid)}`)
if (!Array.isArray(data.diagnostics) || data.diagnostics.length !== 1) failures.push(`diagnostic count ${data.diagnostics?.length ?? "missing"}`)
if (!diagnostic) failures.push(`diagnostic code ${data.diagnostics?.map(item => item.code).join(",") ?? "missing"}`)
if (diagnostic) {
  if (diagnostic.status !== expectedDiagnosticStatus) failures.push(`diagnostic status ${diagnostic.status}`)
  if (diagnostic.surface !== expectedSurface) failures.push(`surface ${diagnostic.surface}`)
  if (diagnostic.path !== expectedPath) failures.push(`path ${diagnostic.path}`)
  if (diagnostic.line !== expectedLine) failures.push(`line ${diagnostic.line}`)
  if (diagnostic.column !== expectedColumn) failures.push(`column ${diagnostic.column}`)
}

if (failures.length) {
  process.stdout.write(JSON.stringify({ failures, result: data, expected: { code: expectedCode, status: expectedDiagnosticStatus, surface: expectedSurface, path: expectedPath, line: expectedLine, column: expectedColumn } }))
  process.exit(1)
}
' "$output" 2>&1
  ); then
    printf 'PASS %s\n' "$case_name"
  else
    printf 'FAIL %s: %s\n' "$case_name" "$check_output"
    failures=$((failures + 1))
  fi
  cases=$((cases + 1))
}

case_root="$TMP/INVALID_TOOL_ALLOWLIST"
mkdir -p "$case_root/global/agents" "$case_root/repo"
agent="$case_root/global/agents/invalid-tool-allowlist.md"
printf '%s\n' '---' 'name: invalid-tool-allowlist' 'tools: true' '---' > "$agent"
printf '%s\n' '{}' > "$case_root/mcp.json"
run_case INVALID_TOOL_ALLOWLIST 1 fail error agent-definition "$agent" 3 1 --global-root "$case_root/global" --repo-root "$case_root/repo" --mcp-config "$case_root/mcp.json"

case_root="$TMP/MALFORMED_FRONTMATTER"
mkdir -p "$case_root/global/agents" "$case_root/repo"
agent="$case_root/global/agents/malformed-frontmatter.md"
printf '%s\n' '---' 'name: malformed-frontmatter' > "$agent"
printf '%s\n' '{}' > "$case_root/mcp.json"
run_case MALFORMED_FRONTMATTER 1 fail error agent-definition "$agent" 3 1 --global-root "$case_root/global" --repo-root "$case_root/repo" --mcp-config "$case_root/mcp.json"

case_root="$TMP/MALFORMED_JSON"
mkdir -p "$case_root/global/agents" "$case_root/repo"
settings="$case_root/settings.json"
printf '%s\n' '{' > "$settings"
printf '%s\n' '{}' > "$case_root/mcp.json"
run_case MALFORMED_JSON 1 fail error settings "$settings" 1 1 --global-root "$case_root/global" --repo-root "$case_root/repo" --settings "$settings" --mcp-config "$case_root/mcp.json"

case_root="$TMP/ROUTING_POLICY_CONFLICT"
mkdir -p "$case_root/global/agents" "$case_root/repo"
agent="$case_root/global/agents/routed-impl.md"
routing="$case_root/routing.md"
printf '%s\n' '---' 'name: routed-impl' 'model: opus' 'effort: medium' 'tools: [Read]' '---' > "$agent"
printf '%s\n' 'routed-impl model: opus effort: medium' 'routed-impl model: sonnet effort: medium' > "$routing"
printf '%s\n' '{}' > "$case_root/mcp.json"
run_case ROUTING_POLICY_CONFLICT 1 fail error routing-ssot "$routing" 2 1 --global-root "$case_root/global" --repo-root "$case_root/repo" --routing "$routing" --mcp-config "$case_root/mcp.json"

case_root="$TMP/ROUTING_POLICY_MISSING"
mkdir -p "$case_root/global/agents" "$case_root/repo"
agent="$case_root/global/agents/routed-impl.md"
routing="$case_root/routing.md"
printf '%s\n' '---' 'name: routed-impl' 'model: opus' 'effort: medium' 'tools: [Read]' '---' > "$agent"
printf '%s' '' > "$routing"
printf '%s\n' '{}' > "$case_root/mcp.json"
run_case ROUTING_POLICY_MISSING 1 fail error routing-ssot "$routing" 1 1 --global-root "$case_root/global" --repo-root "$case_root/repo" --routing "$routing" --mcp-config "$case_root/mcp.json"

case_root="$TMP/ROUTING_SSOT_MISSING"
mkdir -p "$case_root/global/agents" "$case_root/repo"
agent="$case_root/global/agents/routed-ssot-missing.md"
printf '%s\n' '---' 'name: routed-ssot-missing' 'model: opus' 'effort: medium' 'tools: [Read]' '---' > "$agent"
printf '%s\n' '{}' > "$case_root/mcp.json"
run_case ROUTING_SSOT_MISSING 1 fail error routing-ssot "$agent" 2 1 --global-root "$case_root/global" --repo-root "$case_root/repo" --mcp-config "$case_root/mcp.json"

case_root="$TMP/DYNAMIC_TOOL_UNVERIFIED"
mkdir -p "$case_root/global/agents" "$case_root/repo"
agent="$case_root/global/agents/dynamic-tool.md"
printf '%s\n' '---' 'name: dynamic-tool' 'tools: [${toolName}]' '---' > "$agent"
printf '%s\n' '{}' > "$case_root/mcp.json"
run_case DYNAMIC_TOOL_UNVERIFIED 0 pass unverified tool-reference "$agent" 3 1 --global-root "$case_root/global" --repo-root "$case_root/repo" --mcp-config "$case_root/mcp.json"

if [ "$failures" -ne 0 ]; then
  printf 'FAIL consolidated diagnostic contract: %s of %s cases failed\n' "$failures" "$cases"
  exit 1
fi

printf 'PASS consolidated diagnostic contract: %s cases\n' "$cases"
