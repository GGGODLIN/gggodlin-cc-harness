#!/bin/bash
# 本檔在契約測試底下：bash ~/.claude/hooks/T2-routing-gate.test.sh && python3 ~/.claude/hooks/review-spec-yagni-permit.test.py
# T2 routing-gate (project-scoped trial)
# Threat model：本 gate 防誠實但健忘的 agent 漂移；不承諾抵抗同 UID 主動竄改 transcript、環境變數或本機檔案。
# review-implement 授權只接受同 session 成功 Skill(review-implement) tool_use、matching non-error tool_result 與後續 top-level user model／axis seat 選擇；description marker 只能參照，不能單獨授權。
# direct_user_text 的 envelope 排除只認「整則 content 由該類標籤構成」的常見入口（bash-input／bash-stdout＋stderr／local-command-caveat／command-name｜message｜args）；
#   混合形狀（人類文字後面接標籤）仍算 user 文字，寧可多算一筆觸發 axis_stale，也不放行真正過期的選擇。
# 判不出授權時 fail closed；停用與回退沿用 routed-agent-enforce sentinel，不新增 permit、manifest 或 mapping 系統。
# ⚠️ 型別降級（gate-authoring §5 要求明寫）：review-implement 的「使用者選席授權」自 2026-09-18 起由安全型降為提示型。
#   降級只適用於已通過外層安全條件的 routed-judge review 席；wrong reviewer type、Fable 缺 <fable-ok>、fork、routed enforce、mech opt-in 仍走原安全型分支。
#   明文不保證：合法 routed-judge review 席若真的未問使用者，本分支只記 audit row 後放行；不保證選席授權正確。
#   代價上限是一次未經授權的 routed-judge review 席 token 成本，不是跨 agent 型別的安全 gate 繞過。要恢復攔截須改本檔，沒有 sentinel 開關可切。
# review-implement 分支只把 routed-judge 席內的授權判定失敗改寫為 action=would_deny 後放行。action 名保留 would_deny，
#   讓 trial 期間的歷史 row 與之後的資料可用同一個 jq 查詢連續盤點。
#   依據：trial 七天蒐得 8 筆自然 would_deny，逐筆對 transcript 全為假陽性（真陽性 0）；加上安裝前基準 66 筆 deny 同樣零真陽性，
#   累積 74 筆判定沒有一次抓到「LLM 未問使用者就派 review 席」。三種假陽性根因都在判讀層：選單被 markdown fence 包住使 endswith(letter_menu) 失敗、
#   自然語言選擇帶逗號與中文尾綴使 parse_model_axis 的 fullmatch 失敗、使用者寫 resolved model 名（gpt-5.6-sol）而 models 集合只認 opus/fable。
#   2026-09-12 的 d01a22f 已為同類問題補過一次正則（加「都用／全用」），四天後換個尾綴又漏——修 parser 是打地鼠，故移除攔截而非續修。
#   唯一仍 deny 的是 audit row 寫不進去（log 是本分支的唯一產物）。完整證據：trials/review-evidence/2026-09-18-36888b59.md
# 純機械 escape-token gate、無 LLM judge
# 目的：強制 main session 派 Agent tool 前過 routing decision
#
# 機制：
# - tool_input.prompt 或 description 含 <routed:實作|機械|判斷> → allow
# - 無 token → deny + permissionDecisionReason 提示 main 加 token
# - subagent_type != "general-purpose" → 跳過；routed-mech 例外，description 必須含 <mech-ok>
# - workflow context 偵測（transcript_path 含 /workflows/wf_*/） → 跳過（workflow fan-out 不擋）
# - CC_FABLE_MAIN=1（fable-gate 注入、main 為 Fable）且未指定 tool_input.model 且無 <fable-ok> → deny
# - model:fable 只接受 description 的失敗升級 <fable-ok>、architecture-critic 消耗可信 Tier 3 permit，或 routed-judge 消耗可信 YAGNI batch permit
# - YAGNI permit 由同 session 真實 /review-spec yagni、模型選單與後續人類 Fable 選擇建立，以身分欄位綁定（session、事件 uuid、permit_id、batch、packet 路徑、到期時間）；固定 marker、別 session、重放 batch、過期、model mapping 漂移均 fail closed
# - subagent_type=fork（CC v2.1.232 起內建、model 恆 = main、override 被忽略）：
#   兩軸分開（2026-09-05 起，取代 2026-08-14 B 案）——
#     脈絡軸：一律要 description 的 <fork-ok: 理由>，理由 >= 12 bytes，不分 main model
#     額度軸：CC_FABLE_MAIN=1（原生 Fable）時另需 <fable-ok>；vendor 檔位不受此軸限制

set +e

INPUT=$(cat)
TS=$(date -Iseconds)
LOG=${T2_TRACE_LOG:-$HOME/.claude/hooks/T2-routing-gate.trace.log}
AUDIT=${T2_AUDIT_LOG:-$HOME/.claude/logs/T2-routing-gate-audit.jsonl}

# routed-agent-enforce trial：sentinel 檔存在才啟用白名單強制
# sentinel 關閉會停用白名單強制，但 routed-mech 的 <mech-ok> 檢查仍保留
SENTINEL=${T2_ROUTED_SENTINEL:-$HOME/.claude/hooks/routed-enforce.on}
AGENT_DIR=${T2_AGENT_DIR:-$HOME/.claude/agents}
DUAL_PERMIT_HELPER=${REVIEW_SPEC_DUAL_PERMIT_HELPER:-$HOME/.claude/hooks/review-spec-dual-permit.py}
YAGNI_PERMIT_HELPER=${REVIEW_SPEC_YAGNI_PERMIT_HELPER:-$HOME/.claude/hooks/review-spec-yagni-permit.py}
EXTRA_ALLOW="claude-code-guide statusline-setup"
ENFORCE=0
[ -f "$SENTINEL" ] && ENFORCE=1
REVIEW_STAGE=review-implement
REVIEW_AXIS=
REVIEW_LOGICAL_MODEL=
REVIEW_RESOLVED_MODEL=
REVIEW_MODEL_OPTIONS_JSON=${T2_MODEL_OPTIONS_JSON:-$HOME/.claude.json}
resolve_native_model() {
  local logical_model=$1 resolved
  resolved=$(jq -r --arg logical_model "$logical_model" '[.additionalModelOptionsCache[]? | .value | select(type == "string" and test($logical_model))] | .[0] // empty' "$REVIEW_MODEL_OPTIONS_JSON" 2>/dev/null | sed -E 's/\[.*$//')
  printf '%s' "${resolved:-$logical_model}"
}
resolve_native_fable_model() { resolve_native_model fable; }
REVIEW_MARKER=

mkdir -p ~/.claude/hooks ~/.claude/logs

TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)
SUBAGENT_TYPE=$(echo "$INPUT" | jq -r '.tool_input.subagent_type // empty' 2>/dev/null)
PROMPT=$(echo "$INPUT" | jq -r '.tool_input.prompt // empty' 2>/dev/null)
DESC=$(echo "$INPUT" | jq -r '.tool_input.description // empty' 2>/dev/null)
TRANSCRIPT=$(echo "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null)
SESSION=$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)
TUSE=$(echo "$INPUT" | jq -r '.tool_use_id // empty' 2>/dev/null)

log_trace() {
  echo "$TS $1 tool=$TOOL subagent_type=$SUBAGENT_TYPE session=${SESSION:0:8} reason=$2" >> "$LOG"
}

append_audit_row() {
  local row=$1
  (
    umask 077
    mkdir -p "$(dirname "$AUDIT")" || exit 1
    printf '%s\n' "$row" | /usr/bin/lockf -t 2 "${AUDIT}.lock" /bin/sh -c 'cat >> "$1"' _ "$AUDIT" || exit 1
    chmod 600 "$AUDIT" 2>/dev/null || exit 1
    [ ! -e "${AUDIT}.lock" ] || chmod 600 "${AUDIT}.lock" 2>/dev/null
    exit 0
  )
}

audit_row() {
  local action=$1 token=$2 reason=$3 row
  row=$(jq -nc \
    --arg ts "$TS" --arg session "$SESSION" --arg tuse "$TUSE" \
    --arg subagent_type "$SUBAGENT_TYPE" --arg action "$action" --arg token "$token" \
    --arg reason "$reason" --arg prompt_head "$(echo "$PROMPT" | head -c 200)" \
    --arg desc "$DESC" \
    '{ts: $ts, session_id: $session, tool_use_id: $tuse, subagent_type: $subagent_type,
      action: $action, token: $token, reason: $reason,
      prompt_head: $prompt_head, description: $desc}') || return 1
  append_audit_row "$row"
}

audit_review_row() {
  local action=$1 token=$2 reason=$3 row
  row=$(jq -nc \
    --arg ts "$TS" --arg session "$SESSION" --arg tuse "$TUSE" \
    --arg subagent_type "$SUBAGENT_TYPE" --arg action "$action" --arg token "$token" \
    --arg reason "$reason" --arg stage "$REVIEW_STAGE" --arg axis "$REVIEW_AXIS" \
    --arg logical_model "$REVIEW_LOGICAL_MODEL" --arg resolved_model "$REVIEW_RESOLVED_MODEL" \
    '{ts: $ts, session_id: $session, tool_use_id: $tuse, subagent_type: $subagent_type,
      action: $action, token: $token, reason: $reason, stage: $stage, axis: $axis,
      logical_model: $logical_model, resolved_model: $resolved_model}') || return 1
  if append_audit_row "$row"; then
    return 0
  fi
  log_trace deny "review-implement-audit-failed"
  cat <<'JSON'
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "[T2-routing-gate] review-implement audit log 無法安全追加；已 fail closed，請修復 audit 路徑後重試。"
  }
}
JSON
  exit 0
}

review_deny() {
  local reason=$1
  audit_review_row would_deny "$REVIEW_MARKER" "$reason"
  log_trace allow "review-implement-observe($reason)"
  exit 0
}

check_mech_opt_in() {
  [ "$SUBAGENT_TYPE" = "routed-mech" ] || return 0

  if echo "$DESC" | grep -q '<mech-ok>'; then
    log_trace pass "mech-opt-in-ok"
    audit_row pass-e1 "<mech-ok>" "mech_opt_in_ok"
    exit 0
  fi

  log_trace deny "mech-opt-in-required"
  audit_row deny "" "mech_opt_in_required"
  cat <<'JSON'
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "[T2-routing-gate] routed-mech 是嚴格 opt-in，只有三項資格全成立才適用：\n  1. 輸入完整\n  2. 輸出固定\n  3. 不需搜尋／驗證／取捨\n\n唯一 marker 是 <mech-ok>，且互動式 Agent hook 只接受 description 中的 marker；prompt 中單獨出現不算。不要猜填 marker，改派 routed-judge。"
  }
}
JSON
  exit 0
}

review_implement_authorization() {
  "${T2_REVIEW_PYTHON:-python3}" - "$TRANSCRIPT" "$SESSION" "$TUSE" <<'PY'
import json
import os
import re
import stat
import sys

path, session, current_tool_id = sys.argv[1:4]


def result(status, reason="", selected_axis="", selected_model="", selected_pairs=None, invocation_id="", prior_axes=None, prior_pairs=None):
  print(json.dumps({
    "status": status,
    "reason": reason,
    "selected_axis": selected_axis,
    "selected_model": selected_model,
    "selected_pairs": selected_pairs or [],
    "invocation_id": invocation_id,
    "prior_axes": prior_axes or [],
    "prior_pairs": prior_pairs or [],
  }, separators=(",", ":")))
  raise SystemExit(0)

if not session or re.fullmatch(r"[A-Za-z0-9._-]+", session) is None:
  result("deny", "review_implement_session_invalid")
if not os.path.isabs(path) or os.path.basename(path) != f"{session}.jsonl":
  result("deny", "review_implement_session_mismatch")
try:
  descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
except OSError:
  result("deny", "review_implement_transcript_untrusted")
try:
  metadata = os.fstat(descriptor)
  if metadata.st_uid != os.getuid() or not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) & 0o022:
    result("deny", "review_implement_transcript_untrusted")
  with os.fdopen(descriptor, "rb") as handle:
    descriptor = -1
    raw = handle.read()
finally:
  if descriptor >= 0:
    os.close(descriptor)

try:
  records = []
  for line in raw.split(b"\n"):
    if not line.strip():
      continue
    record = json.loads(line)
    if not isinstance(record, dict):
      result("deny", "review_implement_transcript_invalid")
    records.append(record)
except (UnicodeDecodeError, json.JSONDecodeError):
  result("deny", "review_implement_transcript_invalid")

for record in records:
  record_session = record.get("sessionId")
  if record_session is None:
    record_session = record.get("session_id")
  if record_session is not None and record_session != session:
    result("deny", "review_implement_session_mismatch")


def message_content(record, role):
  message = record.get("message")
  if not isinstance(message, dict) or message.get("role") != role:
    return None
  content = message.get("content")
  return content if isinstance(content, list) else None


def top_level(record):
  return not record.get("isSidechain") and not record.get("agentId")


def direct_assistant_text(record):
  if record.get("type") != "assistant" or not top_level(record):
    return None
  content = message_content(record, "assistant")
  if content is None:
    return None
  texts = [
    item.get("text")
    for item in content
    if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str)
  ]
  return "\n".join(texts) if texts else None

stage_calls = []
for index, record in enumerate(records):
  if record.get("type") != "assistant" or not top_level(record):
    continue
  content = message_content(record, "assistant")
  if content is None:
    continue
  for item in content:
    if not isinstance(item, dict) or item.get("type") != "tool_use" or item.get("name") != "Skill":
      continue
    item_input = item.get("input")
    if not isinstance(item_input, dict) or item_input.get("skill") != "review-implement":
      continue
    invocation_id = item.get("id")
    if not isinstance(invocation_id, str) or not invocation_id:
      result("deny", "review_implement_invocation_invalid")
    stage_calls.append((index, invocation_id))

if not stage_calls:
  result("none")
invocation_ids = [invocation_id for _, invocation_id in stage_calls]
if len(invocation_ids) != len(set(invocation_ids)):
  result("deny", "review_implement_duplicate_invocation")
latest_index = stage_calls[-1][0]
latest_calls = [call for call in stage_calls if call[0] == latest_index]
if len(latest_calls) != 1:
  result("deny", "review_implement_duplicate_invocation")

stage_index, invocation_id = latest_calls[0]
matching_results = []
for index in range(stage_index + 1, len(records)):
  record = records[index]
  if not top_level(record):
    continue
  content = message_content(record, "user")
  if content is None:
    continue
  for item in content:
    if isinstance(item, dict) and item.get("type") == "tool_result" and item.get("tool_use_id") == invocation_id:
      matching_results.append((index, record, item))

if not matching_results:
  result("deny", "review_implement_invocation_result_missing", invocation_id=invocation_id)
if len(matching_results) != 1:
  result("deny", "review_implement_duplicate_result", invocation_id=invocation_id)

result_index, result_record, result_item = matching_results[0]
runtime = result_record.get("toolUseResult")
runtime_success = (
  isinstance(runtime, dict)
  and runtime.get("success") is True
  and runtime.get("commandName") == "review-implement"
)
if result_item.get("is_error") is True:
  result("deny", "review_implement_invocation_error", invocation_id=invocation_id)
if result_item.get("is_error") is not False and not runtime_success:
  result("deny", "review_implement_invocation_result_invalid", invocation_id=invocation_id)


def direct_user_text(record):
  if record.get("type") != "user" or not top_level(record):
    return None
  if record.get("isMeta") is True or record.get("turnCompanion") is True:
    return None
  if record.get("userType") != "external":
    return None
  origin = record.get("origin")
  if isinstance(origin, dict) and origin.get("kind") == "task-notification":
    return None
  if record.get("promptSource") == "system" or record.get("isCompactSummary") or record.get("isVisibleInTranscriptOnly"):
    return None
  message = record.get("message")
  if not isinstance(message, dict) or message.get("role") != "user":
    return None
  content = message.get("content")
  if not isinstance(content, str):
    return None
  if (
    re.fullmatch(r"<bash-input>.*</bash-input>", content, re.DOTALL)
    or re.fullmatch(r"<bash-stdout>.*</bash-stdout><bash-stderr>.*</bash-stderr>", content, re.DOTALL)
    or re.fullmatch(r"<local-command-caveat>.*</local-command-caveat>", content, re.DOTALL)
    or re.fullmatch(r"\s*(?:<command-(?:name|message|args)>.*?</command-(?:name|message|args)>\s*)+", content, re.DOTALL)
  ):
    return None
  return content

choices = {"scope", "yagni", "all", "skip"}
aliases = {"a": "all", "b": "scope", "c": "yagni", "d": "skip"}
models = {"opus", "fable"}
menu_lines = ["a. all", "b. scope", "c. yagni", "d. skip"]
letter_menu = "Choose review axes:\n" + "\n".join(menu_lines)
selections = []
for index in range(result_index + 1, len(records)):
  text = direct_user_text(records[index])
  if text is None:
    continue
  selections.append((index, " ".join(text.strip().split()).lower()))

if not selections:
  result("deny", "review_implement_axis_missing", invocation_id=invocation_id)
if len(selections) != 1:
  result("deny", "review_implement_axis_stale", invocation_id=invocation_id)
selection_index, selection = selections[0]
selected_model = "fable"
selected_pairs = []


def expand_pair(model, axis):
  if axis == "all":
    return [f"scope:{model}", f"yagni:{model}"]
  return [f"{axis}:{model}"]


def parse_model_axis(value):
  patterns = [
    (r"(?:用\s*)?(opus|fable)\s*(?:審(?:查)?|跑|for|on|的)?\s*(scope|yagni|all|skip)", True),
    (r"(scope|yagni|all|skip)\s*(?:都用|全用|用|with|using)\s*(opus|fable)", False),
    (r"(scope|yagni|all|skip)\s+(opus|fable)", False),
  ]
  for pattern, model_first in patterns:
    match = re.fullmatch(pattern, value)
    if match:
      return match.groups() if model_first else (match.group(2), match.group(1))
  return None


def parse_selection_pairs(value):
  shared_axis = re.fullmatch(
    r"(scope|yagni)\s*(?:用|with|using)\s*(opus|fable)\s*(?:和|and|\+|,)\s*(opus|fable)",
    value,
  )
  if shared_axis is not None:
    axis, first_model, second_model = shared_axis.groups()
    return expand_pair(first_model, axis) + expand_pair(second_model, axis)
  shared_model = re.fullmatch(
    r"(opus|fable)\s*(?:和|and|\+|,)\s*(opus|fable)\s*(?:審(?:查)?|跑|for|on|的)?\s*(scope|yagni)",
    value,
  )
  if shared_model is not None:
    first_model, second_model, axis = shared_model.groups()
    return expand_pair(first_model, axis) + expand_pair(second_model, axis)
  parts = re.split(r"\s*(?:[,;+、，；]|\s+(?:and|和)\s+)\s*", value)
  pairs = []
  for part in parts:
    model_axis = parse_model_axis(part)
    if model_axis is None:
      return None
    model, axis = model_axis
    pairs.extend(expand_pair(model, axis))
  return pairs


def parse_recommended_pairs(start_index, end_index):
  declarations = []
  for index in range(start_index, end_index):
    text = direct_assistant_text(records[index])
    if text is None:
      continue
    for line in text.splitlines():
      match = re.fullmatch(r"\s*(?:[-*]\s*)?Recommended seats:\s*(.*?)\s*", line)
      if match:
        declarations.append(match.group(1))
  if len(declarations) == 0:
    return None, "review_implement_recommendation_missing"
  if len(declarations) != 1:
    return None, "review_implement_recommendation_ambiguous"
  pairs = []
  for item in re.split(r"\s*,\s*", declarations[0]):
    match = re.fullmatch(r"(opus|fable)\s*/\s*(scope|yagni)", item.strip().lower())
    if match is None:
      return None, "review_implement_recommendation_invalid"
    model, axis = match.groups()
    pairs.append(f"{axis}:{model}")
  if not pairs or len(pairs) != len(set(pairs)):
    return None, "review_implement_recommendation_invalid"
  return pairs, ""


def choose_axis_pairs(axis, start_index, end_index):
  if axis == "skip":
    return [], ""
  recommended_pairs, recommendation_reason = parse_recommended_pairs(start_index, end_index)
  if recommended_pairs is None:
    if recommendation_reason == "review_implement_recommendation_missing":
      return expand_pair("fable", axis), ""
    return None, recommendation_reason
  required_axes = {"scope", "yagni"} if axis == "all" else {axis}
  selected = []
  for required_axis in required_axes:
    matches = [pair for pair in recommended_pairs if pair.startswith(f"{required_axis}:")]
    if len(matches) != 1:
      return None, "review_implement_recommendation_axis_missing" if not matches else "review_implement_recommendation_ambiguous"
    selected.append(matches[0])
  return selected, ""


if selection in aliases:
  assistant_texts = []
  lettered_lines = []
  menu_count = 0
  for index in range(result_index + 1, selection_index):
    text = direct_assistant_text(records[index])
    if text is None:
      continue
    assistant_texts.append(text)
    menu_count += text.count(letter_menu)
    lettered_lines.extend(
      line.strip()
      for line in text.splitlines()
      if re.fullmatch(r"[a-d]\.\s+.*", line.strip())
    )
  if (
    menu_count != 1
    or not assistant_texts
    or not assistant_texts[-1].rstrip().endswith(letter_menu)
    or lettered_lines != menu_lines
  ):
    result("deny", "review_implement_axis_alias_unbound", invocation_id=invocation_id)
  selected_axis = aliases[selection]
  selected_pairs, selection_reason = choose_axis_pairs(selected_axis, result_index + 1, selection_index)
  if selection_reason:
    result("deny", selection_reason, invocation_id=invocation_id)
  selected_models = {pair.split(":", 1)[1] for pair in selected_pairs}
  selected_model = next(iter(selected_models)) if len(selected_models) == 1 else ""
elif selection in {"推薦", "照推薦", "recommended", "follow recommendation", "use recommended"}:
  selected_pairs, recommendation_reason = parse_recommended_pairs(result_index + 1, selection_index)
  if not selected_pairs:
    result("deny", recommendation_reason, invocation_id=invocation_id)
  selected_axes = {pair.split(":", 1)[0] for pair in selected_pairs}
  selected_models = {pair.split(":", 1)[1] for pair in selected_pairs}
  selected_axis = "all" if selected_axes == {"scope", "yagni"} else next(iter(selected_axes))
  selected_model = next(iter(selected_models)) if len(selected_models) == 1 else ""
elif selection in choices:
  selected_axis = selection
  selected_pairs, selection_reason = choose_axis_pairs(selected_axis, result_index + 1, selection_index)
  if selection_reason:
    result("deny", selection_reason, invocation_id=invocation_id)
  selected_models = {pair.split(":", 1)[1] for pair in selected_pairs}
  selected_model = next(iter(selected_models)) if len(selected_models) == 1 else ""
elif re.fullmatch(r"[a-z]", selection):
  result("deny", "review_implement_axis_alias_unbound", invocation_id=invocation_id)
else:
  parsed_pairs = parse_selection_pairs(selection)
  if not parsed_pairs or len(parsed_pairs) != len(set(parsed_pairs)):
    result("deny", "review_implement_axis_stale", invocation_id=invocation_id)
  selected_pairs = parsed_pairs
  selected_axes = {pair.split(":", 1)[0] for pair in selected_pairs}
  selected_models = {pair.split(":", 1)[1] for pair in selected_pairs}
  selected_axis = "all" if selected_axes == {"scope", "yagni"} else next(iter(selected_axes))
  selected_model = next(iter(selected_models)) if len(selected_models) == 1 else ""
if selected_axis == "skip":
  result("deny", "review_implement_axis_not_selected", selected_axis=selected_axis, selected_model=selected_model, selected_pairs=[], invocation_id=invocation_id)

prior_axes = []
prior_pairs = []
for index in range(selection_index + 1, len(records)):
  record = records[index]
  if record.get("type") != "assistant" or not top_level(record):
    continue
  content = message_content(record, "assistant")
  if content is None:
    continue
  for item in content:
    if not isinstance(item, dict) or item.get("type") != "tool_use" or item.get("name") != "Agent":
      continue
    agent_id = item.get("id")
    if not isinstance(agent_id, str) or not agent_id or agent_id == current_tool_id:
      continue
    item_input = item.get("input")
    if not isinstance(item_input, dict) or item_input.get("subagent_type") != "routed-judge":
      continue
    item_model = item_input.get("model")
    description = item_input.get("description")
    if not isinstance(description, str) or item_model not in models:
      continue
    if item_model == "fable" and description.count("<fable-ok>") != 1:
      continue
    legacy_matches = re.findall(r"<review-implement-fable:v1 axis=(scope|yagni)>", description)
    selection_matches = re.findall(r"<review-implement-selection:v1 model=(opus|fable) axis=(scope|yagni)>", description)
    if len(legacy_matches) == 1 and not selection_matches and item_model == "fable":
      prior_axis = legacy_matches[0]
      prior_axes.append(prior_axis)
      prior_pairs.append(f"{prior_axis}:fable")
    elif len(selection_matches) == 1 and not legacy_matches and selection_matches[0][0] == item_model:
      prior_axis = selection_matches[0][1]
      prior_axes.append(prior_axis)
      prior_pairs.append(f"{prior_axis}:{item_model}")

result("authorized", selected_axis=selected_axis, selected_model=selected_model, selected_pairs=selected_pairs, invocation_id=invocation_id, prior_axes=prior_axes, prior_pairs=prior_pairs)
PY
}

# Tool filter: 只攔 Agent / Task tool
if [ "$TOOL" != "Agent" ] && [ "$TOOL" != "Task" ]; then
  exit 0
fi

MODEL_PARAM=$(echo "$INPUT" | jq -r '.tool_input.model // empty' 2>/dev/null)
COMBINED="$PROMPT $DESC"

REVIEW_MARKER_HINT=0
printf '%s\n' "$PROMPT $DESC" | grep -qE '<review-implement-(fable|selection):v1' && REVIEW_MARKER_HINT=1
YAGNI_MARKER_HINT=0
printf '%s\n' "$PROMPT $DESC" | grep -q '<review-spec-yagni:v1' && YAGNI_MARKER_HINT=1
REVIEW_OBSERVE_ELIGIBLE=0
if [ "$REVIEW_MARKER_HINT" = "1" ] && [ "$YAGNI_MARKER_HINT" = "0" ] && [ "$SUBAGENT_TYPE" = "routed-judge" ]; then
  if [ "$MODEL_PARAM" != "fable" ] || printf '%s\n' "$DESC" | grep -q '<fable-ok>'; then
    REVIEW_OBSERVE_ELIGIBLE=1
  fi
fi
if [ "$REVIEW_OBSERVE_ELIGIBLE" = "1" ]; then
  REVIEW_AUTH_JSON=$(review_implement_authorization 2>/dev/null)
  REVIEW_AUTH_STATUS=$(printf '%s' "$REVIEW_AUTH_JSON" | jq -r '.status // "invalid"' 2>/dev/null)
  REVIEW_AUTH_REASON=$(printf '%s' "$REVIEW_AUTH_JSON" | jq -r '.reason // "review_implement_authorization_invalid"' 2>/dev/null)
  REVIEW_SELECTED_AXIS=$(printf '%s' "$REVIEW_AUTH_JSON" | jq -r '.selected_axis // empty' 2>/dev/null)
  REVIEW_SELECTED_MODEL=$(printf '%s' "$REVIEW_AUTH_JSON" | jq -r '.selected_model // empty' 2>/dev/null)
  [ "$REVIEW_AUTH_STATUS" = "none" ] && REVIEW_AUTH_REASON=review_implement_stage_missing
  REVIEW_AXIS=$REVIEW_SELECTED_AXIS
  LEGACY_REVIEW_MARKER=$(printf '%s\n' "$DESC" | grep -oE '<review-implement-fable:v1 axis=(scope|yagni)>' | sed -n '1p')
  SELECTION_REVIEW_MARKER=$(printf '%s\n' "$DESC" | grep -oE '<review-implement-selection:v1 model=(opus|fable) axis=(scope|yagni)>' | sed -n '1p')
  LEGACY_REVIEW_MARKER_COUNT=$(printf '%s\n' "$DESC" | grep -oE '<review-implement-fable:v1 axis=(scope|yagni)>' | wc -l | tr -d ' ')
  SELECTION_REVIEW_MARKER_COUNT=$(printf '%s\n' "$DESC" | grep -oE '<review-implement-selection:v1 model=(opus|fable) axis=(scope|yagni)>' | wc -l | tr -d ' ')
  if [ "$((LEGACY_REVIEW_MARKER_COUNT + SELECTION_REVIEW_MARKER_COUNT))" != "1" ]; then
    review_deny review_implement_marker_invalid
  fi
  if [ -n "$LEGACY_REVIEW_MARKER" ]; then
    REVIEW_MARKER=$LEGACY_REVIEW_MARKER
    REVIEW_LOGICAL_MODEL=fable
    REVIEW_MARKER_AXIS=$(printf '%s\n' "$REVIEW_MARKER" | sed -E 's/.*axis=([^>]+).*/\1/')
  else
    REVIEW_MARKER=$SELECTION_REVIEW_MARKER
    REVIEW_LOGICAL_MODEL=$(printf '%s\n' "$REVIEW_MARKER" | sed -E 's/.*model=([^ ]+).*/\1/')
    REVIEW_MARKER_AXIS=$(printf '%s\n' "$REVIEW_MARKER" | sed -E 's/.*axis=([^>]+).*/\1/')
  fi
  REVIEW_AXIS=$REVIEW_MARKER_AXIS
  if [ -n "$LEGACY_REVIEW_MARKER" ]; then
    REVIEW_AUTHORIZED_REASON="review_implement_authorized:$REVIEW_MARKER_AXIS"
    REVIEW_DUPLICATE_REASON=review_implement_axis_already_dispatched
  else
    REVIEW_AUTHORIZED_REASON="review_implement_authorized:$REVIEW_LOGICAL_MODEL:$REVIEW_MARKER_AXIS"
    REVIEW_DUPLICATE_REASON=review_implement_selection_already_dispatched
  fi
  if [ "$MODEL_PARAM" != "$REVIEW_LOGICAL_MODEL" ]; then
    review_deny review_implement_model_required
  fi
  if [ "$REVIEW_LOGICAL_MODEL" = "fable" ]; then
    REVIEW_FABLE_MARKER_COUNT=$(printf '%s\n' "$DESC" | grep -o '<fable-ok>' | wc -l | tr -d ' ')
    if [ "$REVIEW_FABLE_MARKER_COUNT" != "1" ]; then
      review_deny review_implement_marker_invalid
    fi
    if [ -n "${CC_VENDOR:-}" ]; then
      REVIEW_RESOLVED_MODEL=$(printf '%s' "${ANTHROPIC_DEFAULT_FABLE_MODEL:-}" | sed -E 's/[[:space:]]*\([^()]*\)[[:space:]]*$//')
      if [ -z "$REVIEW_RESOLVED_MODEL" ]; then
        review_deny review_implement_model_mapping_missing
      fi
    else
      REVIEW_RESOLVED_MODEL=$(resolve_native_fable_model)
    fi
  else
    if printf '%s' "$DESC" | grep -q '<fable-ok>'; then
      review_deny review_implement_marker_invalid
    fi
    if [ -n "${CC_VENDOR:-}" ]; then
      REVIEW_RESOLVED_MODEL=$(printf '%s' "${ANTHROPIC_DEFAULT_OPUS_MODEL:-}" | sed -E 's/[[:space:]]*\([^()]*\)[[:space:]]*$//')
      if [ -z "$REVIEW_RESOLVED_MODEL" ]; then
        review_deny review_implement_model_mapping_missing
      fi
    else
      REVIEW_RESOLVED_MODEL=$(resolve_native_model opus)
    fi
  fi
  if [ "$SUBAGENT_TYPE" != "routed-judge" ]; then
    review_deny review_implement_reviewer_type_invalid
  fi
  if [ "$REVIEW_AUTH_STATUS" != "authorized" ]; then
    review_deny "${REVIEW_AUTH_REASON:-review_implement_authorization_invalid}"
  fi
  if [ "$REVIEW_SELECTED_AXIS" != "all" ] && [ "$REVIEW_SELECTED_AXIS" != "$REVIEW_MARKER_AXIS" ]; then
    review_deny review_implement_axis_not_selected
  fi
  if [ -n "$REVIEW_SELECTED_MODEL" ] && [ "$REVIEW_SELECTED_MODEL" != "$REVIEW_LOGICAL_MODEL" ]; then
    review_deny review_implement_model_not_selected
  fi
  REVIEW_SELECTED_PAIR="${REVIEW_MARKER_AXIS}:${REVIEW_LOGICAL_MODEL}"
  if ! printf '%s' "$REVIEW_AUTH_JSON" | jq -e --arg pair "$REVIEW_SELECTED_PAIR" '.selected_pairs | index($pair) != null' >/dev/null 2>&1; then
    if [ -n "$LEGACY_REVIEW_MARKER" ]; then
      review_deny review_implement_axis_not_selected
    fi
    review_deny review_implement_selection_not_selected
  fi
  if printf '%s' "$REVIEW_AUTH_JSON" | jq -e --arg pair "$REVIEW_SELECTED_PAIR" '.prior_pairs | index($pair) != null' >/dev/null 2>&1; then
    review_deny "$REVIEW_DUPLICATE_REASON"
  fi
  audit_review_row allow "$REVIEW_MARKER" "$REVIEW_AUTHORIZED_REASON"
  exit 0
fi

if [ "$YAGNI_MARKER_HINT" = "1" ]; then
  PERMIT_RESULT=$(printf '%s' "$INPUT" | "$YAGNI_PERMIT_HELPER" consume 2>/dev/null)
  PERMIT_STATUS=$?
  PERMIT_ALLOWED=$(printf '%s' "$PERMIT_RESULT" | jq -r '.allowed // false' 2>/dev/null)
  PERMIT_BATCH=$(printf '%s' "$PERMIT_RESULT" | jq -r '.batch // empty' 2>/dev/null)
  PERMIT_REASON=$(printf '%s' "$PERMIT_RESULT" | jq -r '.reason // "helper-error"' 2>/dev/null)
  [ -n "$PERMIT_REASON" ] || PERMIT_REASON=helper-error

  if [ "$PERMIT_STATUS" = "0" ] && [ "$PERMIT_ALLOWED" = "true" ]; then
    log_trace pass "review-spec-yagni-permit($PERMIT_BATCH)"
    audit_row pass-e1 "<review-spec-yagni:v1>" "review_spec_yagni_permit:$PERMIT_BATCH"
    exit 0
  fi

  log_trace deny "review-spec-yagni-permit($PERMIT_REASON)"
  audit_row deny "<review-spec-yagni:v1>" "review_spec_yagni_permit:$PERMIT_REASON"
  cat <<JSON
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "[T2-routing-gate] /review-spec YAGNI 的 Fable batch 沒有可消耗的可信 permit（原因：${PERMIT_REASON}）。固定 marker 或 generic <fable-ok> 不構成授權；permit 必須綁定同 session 的真實模型選擇事件、permit_id、packet 路徑與單一 stories／decisions batch，到期或使用一次後即失效。目前 marker 格式：<review-spec-yagni:v1 permit_id=<id> batch=<stories|decisions>>。請回到 YAGNI 模型選單後的 permit 步驟，不要手動補 marker。"
  }
}
JSON
  exit 0
fi

if [ "$MODEL_PARAM" = "fable" ] &&
   [ "$SUBAGENT_TYPE" = "architecture-critic" ] &&
   echo "$DESC" | grep -q '<review-spec-dual:v1'; then
  PERMIT_RESULT=$(printf '%s' "$INPUT" | "$DUAL_PERMIT_HELPER" consume 2>/dev/null)
  PERMIT_STATUS=$?
  PERMIT_ALLOWED=$(printf '%s' "$PERMIT_RESULT" | jq -r '.allowed // false' 2>/dev/null)
  PERMIT_LENS=$(printf '%s' "$PERMIT_RESULT" | jq -r '.lens // empty' 2>/dev/null)
  PERMIT_REASON=$(printf '%s' "$PERMIT_RESULT" | jq -r '.reason // "helper-error"' 2>/dev/null)

  if [ "$PERMIT_STATUS" = "0" ] && [ "$PERMIT_ALLOWED" = "true" ]; then
    log_trace pass "review-spec-dual-permit($PERMIT_LENS)"
    audit_row pass-e1 "<review-spec-dual:v1>" "review_spec_dual_permit:$PERMIT_LENS"
    exit 0
  fi

  log_trace deny "review-spec-dual-permit($PERMIT_REASON)"
  audit_row deny "<review-spec-dual:v1>" "review_spec_dual_permit:$PERMIT_REASON"
  cat <<JSON
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "[T2-routing-gate] /review-spec Tier 3 的 Fable 支線沒有可消耗的可信 permit（原因：${PERMIT_REASON}）。固定 marker 本身不構成授權；permit 必須由真實 /review-spec Tier 3 使用者事件建立，綁定 session、command 事件、permit_id、單一 lens 與到期時間，使用一次後即失效。目前 marker 格式：<review-spec-dual:v1 permit_id=<id> lens=<slug>>。請重新從 /review-spec Tier 3 的 permit 步驟開始，不要手動補 marker。"
  }
}
JSON
  exit 0
fi

if [ "$MODEL_PARAM" = "fable" ] && [ "$SUBAGENT_TYPE" = "architecture-critic" ]; then
  log_trace deny "architecture-critic-fable-requires-dual-permit"
  audit_row deny "" "architecture_critic_fable_requires_dual_permit"
  cat <<'JSON'
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "[T2-routing-gate] architecture-critic 的 Fable 呼叫只允許 /review-spec Tier 3 可信 permit；裸 <fable-ok>、固定 marker、Tier 2、/grill-me-one-shot 與其他場景都不授權。"
  }
}
JSON
  exit 0
fi

if [ "$MODEL_PARAM" = "fable" ] && ! echo "$DESC" | grep -q '<fable-ok>'; then
  log_trace deny "fable-no-marker($SUBAGENT_TYPE)"
  audit_row deny "" "fable_no_marker:${SUBAGENT_TYPE:-empty}"
  cat <<'JSON'
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "[T2-routing-gate] model:\"fable\" 需要可信授權。失敗升級終級只接受 description 的 <fable-ok>，prompt 內同名文字不算；architecture-critic 不接受裸 <fable-ok>，只能消耗 /review-spec Tier 3 permit。"
  }
}
JSON
  exit 0
fi

# fork 一律要 description 的 <fork-ok: 理由>（ENFORCE 兩態共用；legacy 的 E1 會放行 fork、必須在它之前攔）
#
# Threat model：本分支防「順手 fork」——沒想過需不需要完整脈絡就派。
# 它不防編理由：marker 是自我聲明、純字串比對，模型想過關隨時寫得出一句話。
# 換到的是「決定必須落成文字」，不是「決定必須正確」。
# 明文不保證：空洞但夠長的理由照過；Workflow agent() 派 fork 完全不 fire 本 hook。
#
# 兩軸分開管（2026-09-05 使用者拍板兩種額度結構分開對待）：
#   脈絡軸 <fork-ok: 理由> —— 一律要，不分 main model。fork 的成本來自「帶整個對話」，
#     與 main 是誰無關。
#   額度軸 <fable-ok>      —— 只有 CC_FABLE_MAIN=1（原生 claude-fable-*）才另外要。
#     原生 Fable 是硬牆（週配額 50% cap，燒完就沒）；vendor 檔位走訂閱制，
#     對 fork 只需要防「當通用工具用」，不需要額度授權。
# CC_FABLE_MAIN 由 fable-gate.sh 以 *[Ff]able* 字串比對注入，所以額度軸只涵蓋原生
# Fable：gpt-6-astra / gpt-5.6-sol 等 vendor 最強檔位偵測不到，且刻意不修——
# 使用者 2026-09-05 判定映射檔位只需要脈絡軸。
#
# 歸屬更正：「不分 main model」原記為使用者拍板，實為 agent 自行泛化後事後揭露；
# 使用者當時原話講的是「最強模型 + 完整脈絡」。本版依實際拍板改為兩軸分開。
#
# Recovery：fork 分支在 ENFORCE 兩態共用位置，`routed-enforce.on` 改名救不了它。
# 誤攔時 `touch ~/.claude/hooks/fork-gate.off` 單獨停用本分支，放行仍寫 audit。
FORK_GATE_OFF=${T2_FORK_GATE_OFF:-$HOME/.claude/hooks/fork-gate.off}
FORK_REASON_MIN_BYTES=12
if [ "$SUBAGENT_TYPE" = "fork" ]; then
  if [ -f "$FORK_GATE_OFF" ]; then
    log_trace pass "fork-gate-disabled"
    audit_row pass-e1 "" "fork_gate_disabled"
    exit 0
  fi
  # 理由容許內含 '>'：抓到最後一個 '>' 為止，而不是第一個。舊的 [^>]* 會把
  # "需要 A -> B 的脈絡" 截成 "需要 A -"，然後回報「理由太短」誤導作者。
  FORK_MARKER=$(printf '%s' "$DESC" | grep -oE '<fork-ok:.*>' | head -1)
  if [ -n "$FORK_MARKER" ]; then
    FORK_REASON=$(printf '%s' "$FORK_MARKER" \
      | sed -E 's/^<fork-ok:[[:space:]]*//; s/>$//; s/[[:space:]]+$//')
    FORK_REASON_BYTES=$(printf '%s' "$FORK_REASON" | wc -c | tr -d ' ')
    if [ "$FORK_REASON_BYTES" -lt "$FORK_REASON_MIN_BYTES" ]; then
      log_trace deny "fork-reason-too-thin"
      audit_row deny "$FORK_MARKER" "fork_reason_too_thin"
      cat <<'JSON'
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "[T2-routing-gate] <fork-ok:> 的理由太短。寫一句話說明為什麼這個任務需要「完整對話」，而不只是任務描述。\n\n要寫得出：是哪一段脈絡、為什麼打包進 prompt 不夠。寫不出來通常代表不需要 fork —— 改派 routed-judge / routed-impl / parallel-search 成本低很多。\n\n（本訊息刻意不給可直接複製的範例：貼上範例不構成「想過」。）"
  }
}
JSON
      exit 0
    fi
    # 脈絡軸過了，再看額度軸：原生 Fable 當 main 另外要 <fable-ok>
    if [ "${CC_FABLE_MAIN:-}" = "1" ] && ! echo "$DESC" | grep -q '<fable-ok>'; then
      log_trace deny "fork-fable-main-no-quota-marker"
      audit_row deny "$FORK_MARKER" "fork_fable_main_no_marker"
      cat <<'JSON'
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "[T2-routing-gate] 脈絡理由收到了，但 main 是原生 Fable，fork 必然繼承它、燒的是週配額 50% cap（硬牆，燒完就沒）。\n\n額度是另一軸，要另外授權：description 同時放 <fable-ok>。\n\n不值得燒配額就改派 routed-*（判斷 → routed-judge、實作 → routed-impl、查證 → parallel-search）。\n\nvendor 檔位（gpt-6-astra / gpt-5.6-sol 等）走訂閱制，不受本軸限制。判準見 ~/.claude/references/subagent-routing.md「Fable 配額政策」段。"
  }
}
JSON
      exit 0
    fi
    log_trace pass "fork-ok(fable_main=${CC_FABLE_MAIN:-0})"
    audit_row pass-e1 "$FORK_MARKER" "fork_ok"
    exit 0
  fi
  log_trace deny "fork-no-marker(fable_main=${CC_FABLE_MAIN:-0})"
  audit_row deny "" "fork_no_marker"
  if [ "${CC_FABLE_MAIN:-}" = "1" ]; then
    cat <<'JSON'
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "[T2-routing-gate] fork 會把整個對話帶進 subagent，是最貴的派工形式（完整脈絡 × main 的 model）。main 是原生 Fable，這一發燒的是週配額 50% cap。\n\n兩軸都要：\n  1. 脈絡 —— description 放 <fork-ok: …>，寫明為什麼需要「完整對話」而不只是任務描述\n  2. 額度 —— description 同時放 <fable-ok>\n\n不需要脈絡的任務改派 routed-*（判斷 → routed-judge、實作 → routed-impl、查證 → parallel-search）。\n\nmarker 必須在 description，prompt 內同名文字不算。判準見 ~/.claude/references/subagent-routing.md「Fable 配額政策」段。"
  }
}
JSON
    exit 0
  fi
  cat <<'JSON'
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "[T2-routing-gate] fork 會把整個對話帶進 subagent，是最貴的派工形式（完整脈絡 × main 的 model）。\n\n要派就在 description 放 <fork-ok: …>，寫明為什麼需要「完整對話」而不只是任務描述 —— 是哪一段脈絡、為什麼打包進 prompt 不夠。\n\n不需要脈絡的任務改派 routed-*（判斷 → routed-judge、實作 → routed-impl、查證 → parallel-search）。\n\nmarker 必須在 description，prompt 內同名文字不算。判準見 ~/.claude/references/subagent-routing.md「Fable 配額政策」段。"
  }
}
JSON
  exit 0
fi

# ─────────────────────────────────────────────────────────────
# routed-agent-enforce 分支（ENFORCE=1 才進；白名單邏輯不與下方 legacy token 路徑共用）
# ─────────────────────────────────────────────────────────────
if [ "$ENFORCE" = "1" ]; then
  # E2 優先：workflow fan-out 不擋
  if echo "$TRANSCRIPT" | grep -qE '/workflows/wf_[^/]+/'; then
    log_trace skip "E2-workflow-context(enforce)"
    audit_row pass-e2 "" "workflow_context"
    exit 0
  fi

  check_mech_opt_in

  # N2: 白名單制 — 只有「有定義檔（model/effort 已釘死）」的 agent 才准派
  #     有定義檔 / plugin agent（含冒號）/ EXTRA_ALLOW 明列者 → pass
  #     general-purpose / 空值 / claude / 其他無定義檔者 → deny（fail-closed）
  ALLOWED=0
  case "$SUBAGENT_TYPE" in
    "" | general-purpose | claude)
      ALLOWED=0
      ;;
    *:*)
      ALLOWED=1
      ;;
    *)
      if [ -f "$AGENT_DIR/${SUBAGENT_TYPE}.md" ]; then
        ALLOWED=1
      else
        case " $EXTRA_ALLOW " in
          *" $SUBAGENT_TYPE "*) ALLOWED=1 ;;
        esac
      fi
      ;;
  esac

  if [ "$ALLOWED" = "1" ]; then
    log_trace skip "enforce-allowed($SUBAGENT_TYPE)"
    audit_row pass-e1 "" "enforce_allowed:$SUBAGENT_TYPE"
    exit 0
  fi

  log_trace deny "enforce-routed-required(${SUBAGENT_TYPE:-empty})"
  audit_row deny "" "enforce_routed_required:${SUBAGENT_TYPE:-empty}"
  cat <<'JSON'
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "[T2-routing-gate] routed-agent-enforce trial 生效中：general-purpose 與無定義檔的 agent 已停用（model / effort 無法釘死）。\n\n改派下列四個之一（model + effort 已釘死，不需 <routed:> token）：\n  routed-impl    實作類（production code / 多檔整合 / 重構）— opus + medium\n  routed-mech    機械類（翻譯 / 摘要 / 格式轉換 / 大量 chunk）— sonnet + low；description 另需 <mech-ok>\n  routed-judge   判斷類（架構決策 / synthesis / verify / 主軸抽取）— opus + xhigh\n  routed-secure  安全敏感（authz / crypto / secret 處理 / 漏洞修補）— opus + high\n\n有定義檔的 specialized agent（deep-explore / code-reviewer 等）與 workflow agent() 不受影響。判類別看 ~/.claude/references/subagent-routing.md。\n\n回退：把 ~/.claude/hooks/routed-enforce.on 改名只會停用白名單強制；routed-mech 的 opt-in 仍保留。完整回退需同時還原 mech gate、agent 契約與 routing 文件。"
  }
}
JSON
  exit 0
fi

# ── 以下為 ENFORCE=0 的 legacy token 路徑；workflow E2 優先，互動式 routed-mech 仍檢查 <mech-ok> ──

# E2: workflow context 跳過（transcript_path 含 /workflows/wf_*/）
if echo "$TRANSCRIPT" | grep -qE '/workflows/wf_[^/]+/'; then
  log_trace skip "E2-workflow-context"
  audit_row pass-e2 "" "workflow_context"
  exit 0
fi

check_mech_opt_in

# E1: specialized agent 跳過
if [ -n "$SUBAGENT_TYPE" ] && [ "$SUBAGENT_TYPE" != "general-purpose" ]; then
  log_trace skip "E1-specialized-agent($SUBAGENT_TYPE)"
  audit_row pass-e1 "" "specialized_agent:$SUBAGENT_TYPE"
  exit 0
fi

# Token check: prompt 或 description 含 <routed:實作|機械|判斷>
COMBINED="$PROMPT $DESC"
TOKEN_MATCH=$(echo "$COMBINED" | grep -oE '<routed:(實作|機械|判斷)>' | head -1)

if [ -n "$TOKEN_MATCH" ]; then
  # Fable-main 檢查：未指定 model = 默默繼承 Fable → 攔
  MODEL_PARAM=$(echo "$INPUT" | jq -r '.tool_input.model // empty' 2>/dev/null)
  if [ "${CC_FABLE_MAIN:-}" = "1" ] && [ -z "$MODEL_PARAM" ]; then
    if echo "$DESC" | grep -q '<fable-ok>'; then
      log_trace pass "token-match=$TOKEN_MATCH fable-ok"
      audit_row allow "$TOKEN_MATCH" "fable_ok_marker"
      exit 0
    fi
    log_trace deny "fable-inherit-no-model"
    audit_row deny "$TOKEN_MATCH" "fable_inherit_no_model"
    cat <<'JSON'
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "[T2-routing-gate] main 是 Fable、未指定 model 會默默繼承 Fable 燒配額。\n\n重派時按 ~/.claude/references/subagent-routing.md 指定 model：判斷類 → model: opus（prompt 註明 effort xhigh）；機械/實作 → sonnet。刻意要 Fable（失敗升級終級）→ description 加 <fable-ok> 並簡述失敗軌跡；prompt 內 marker 不算授權。"
  }
}
JSON
    exit 0
  fi
  log_trace pass "token-match=$TOKEN_MATCH${MODEL_PARAM:+ model=$MODEL_PARAM}"
  audit_row allow "$TOKEN_MATCH" "${MODEL_PARAM:+model:$MODEL_PARAM}"
  exit 0
fi

# 無 token → deny
log_trace deny "no-token"
audit_row deny "" "no_routing_token"

cat <<'JSON'
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "[T2-routing-gate] 派 Agent tool 前過 routing decision。\n\n看 ~/.claude/references/subagent-routing.md 判類別、重派時在 prompt 或 description 加標記 <routed:實作>、<routed:機械> 或 <routed:判斷>。\n\n例外：specialized subagent_type / workflow agent() 自動 pass、不需 token。"
  }
}
JSON
