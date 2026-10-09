#!/usr/bin/env bash
# resume-workflow-with-injected-args.sh
#
# 把 sidecar args 機械注入到 Workflow script 的 args-reading 那一行 → 產 byte-faithful injected script。
# 解 main session 手貼 Workflow tool args 不可達 byte-identical 的結構性 bug：
#   - args 從 JSON sidecar 走 python file IO（byte-faithful）
#   - 注入 script literal（byte-faithful）
#   - main session call 只傳 scriptPath + resumeFromRunId（純 ASCII，無 normalize 風險）
#   - Workflow runtime 讀 script 內容 byte-faithful
#   - agent prompt hash → 跟原版 jsonl filename 一致 → cache 命中
#
# Usage:
#   resume-workflow-with-injected-args.sh <workflow-script> <sidecar-json> <output-script>
#
# Example:
#   ~/.claude/scripts/resume-workflow-with-injected-args.sh \
#     <workflow-script.js> \
#     ~/.claude/workflow-monitor-args.json \
#     /tmp/dr-paced-injected.js
#
# Then in main session:
#   Workflow({scriptPath: '/tmp/dr-paced-injected.js', resumeFromRunId: 'wf_xxx'})
#   不傳 args（QUESTION 不再依賴 args global）
#
# 支援的 script patterns（按重要性排序）:
#   pattern A: const QUESTION = (typeof args === "string" && args.trim()) || ""
#     → deep-research-paced.js 用這個（line 124, 2026-06）
#   pattern B: 其他 workflow script 自己加：
#     // INJECT_ARGS_HERE
#     的 marker，本 helper 也支援
#
# Exit codes:
#   0 = success, injected script written
#   1 = missing args
#   2 = sidecar JSON unreadable
#   3 = workflow script not found
#   4 = no replacement pattern matched
#   5 = python error

set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "Usage: $0 <workflow-script> <sidecar-json> <output-script>" >&2
  echo "" >&2
  echo "Inject sidecar args into Workflow script's args-reading line so resume" >&2
  echo "doesn't depend on main session re-passing byte-identical args." >&2
  exit 1
fi

WORKFLOW_SCRIPT="$1"
SIDECAR_JSON="$2"
OUTPUT_SCRIPT="$3"

[[ -r "$SIDECAR_JSON" ]] || { echo "sidecar JSON unreadable: $SIDECAR_JSON" >&2; exit 2; }
[[ -r "$WORKFLOW_SCRIPT" ]] || { echo "workflow script not found: $WORKFLOW_SCRIPT" >&2; exit 3; }

python3 - <<PYEOF
import json
import sys
from pathlib import Path

SIDECAR = Path("$SIDECAR_JSON")
SCRIPT = Path("$WORKFLOW_SCRIPT")
OUT = Path("$OUTPUT_SCRIPT")

# 1) 讀 sidecar args（byte-faithful：python json.loads 不做 unicode normalization）
try:
    args_value = json.loads(SIDECAR.read_text())
except json.JSONDecodeError as e:
    print(f"sidecar JSON parse error: {e}", file=sys.stderr)
    sys.exit(2)

if not isinstance(args_value, (str, dict, list)):
    print(f"sidecar args must be string/dict/list, got {type(args_value).__name__}", file=sys.stderr)
    sys.exit(2)

# 2) 讀 workflow script
script = SCRIPT.read_text()

# 3) 嘗試 pattern A：deep-research-paced 風格的 args 讀法
#    const QUESTION = (typeof args === "string" && args.trim()) || ""
pattern_a = 'const QUESTION = (typeof args === "string" && args.trim()) || ""'

# pattern C（2026-09-03）：deep-research-paced 在 07-27 加 depth tiers 時把 QUESTION 改成
# 跨行、同時吃 string 與 {question, depth} object 的寫法，單行 pattern A 從此不再匹配 ——
# resume 直接 exit 4，等於 fork 演化後 helper 靜默失去對它的支援。C 用 non-greedy regex
# 吃掉整個 `const QUESTION = (typeof args ... || ""` 運算式（不論幾行）。
import re
pattern_c_re = re.compile(r'const QUESTION = \(typeof args[\s\S]*?\|\| ""')

# args literal：用 json.dumps(ensure_ascii=False) 變成 JS string literal
#   - ensure_ascii=False 保留全形 unicode（不 escape）
#   - json.dumps 自動處理 quotes / backslash / control chars → JS-safe
args_literal = json.dumps(args_value, ensure_ascii=False)
replacement_a = f'const QUESTION = {args_literal}'

if pattern_a in script:
    script_modified = script.replace(pattern_a, replacement_a, 1)
    # sanity check：替換次數 == 1
    if script.count(pattern_a) != 1:
        print(f"WARNING: pattern A occurs {script.count(pattern_a)} times in script (expected 1)", file=sys.stderr)
    matched_pattern = "A (deep-research-paced const QUESTION line)"
elif pattern_c_re.search(script):
    n_c = len(pattern_c_re.findall(script))
    if n_c != 1:
        print(f"WARNING: pattern C occurs {n_c} times in script (expected 1)", file=sys.stderr)
    script_modified = pattern_c_re.sub(lambda _m: f'const QUESTION = {args_literal}', script, count=1)
    matched_pattern = "C (multi-line const QUESTION accepting string|object args)"
else:
    # pattern B：// INJECT_ARGS_HERE marker
    pattern_b_marker = "// INJECT_ARGS_HERE"
    if pattern_b_marker in script:
        # 注入：在 marker 上一行加 const __INJECTED_ARGS__ = <literal>
        # script 自己讀 __INJECTED_ARGS__ instead of args
        injection = f"const __INJECTED_ARGS__ = {args_literal}; // BYTE-FAITHFUL INJECTED"
        script_modified = script.replace(pattern_b_marker, injection, 1)
        matched_pattern = "B (// INJECT_ARGS_HERE marker)"
    else:
        print(f"no replacement pattern matched in {SCRIPT}", file=sys.stderr)
        print(f"  tried pattern A: {pattern_a!r}", file=sys.stderr)
        print(f"  tried pattern B marker: {pattern_b_marker!r}", file=sys.stderr)
        sys.exit(4)

# 4) 寫 output（byte-faithful：python file write 不 normalize）
OUT.write_text(script_modified)

# 5) sanity report
print(f"✓ Injected (pattern {matched_pattern})", file=sys.stderr)
print(f"  source script: {SCRIPT}", file=sys.stderr)
print(f"  sidecar args: {SIDECAR} ({len(SIDECAR.read_text())} bytes)", file=sys.stderr)
print(f"  output script: {OUT} ({len(script_modified)} bytes, +{len(script_modified)-len(script):+d} from base)", file=sys.stderr)
print(f"", file=sys.stderr)
print(f"Next step (main session):", file=sys.stderr)
print(f"  Workflow({{scriptPath: '{OUT}', resumeFromRunId: 'wf_xxx'}})", file=sys.stderr)
print(f"  ⚠️ 不傳 args（QUESTION 已 hardcoded in injected script）", file=sys.stderr)
PYEOF

# exit code from python heredoc propagates via set -e
