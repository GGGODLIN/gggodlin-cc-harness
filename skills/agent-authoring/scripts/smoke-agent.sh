#!/bin/bash
# smoke-agent.sh [--read-only] <agent-name> — agent 定義檔上線前的工具鏈 smoke test
#
# 為什麼要有這支：2026-07-27 routed-* 事故——tools: [] 讓 agent 零工具，
# 模型把 tool call 吐成文字再幻覺假結果（連 git status 輸出都編得出來）。
# 只驗 jsonl 的 model/effort 解析值抓不到這型失敗（07-26 smoke 4/4 過、隔天 live 全滅）。
# 預設模式判準是「headless 新 process + 磁碟上真的出現 side-effect 檔」；
# --read-only 模式給沒有 Bash 或禁止寫檔的唯讀 agent 用，判準是「事前未知的隨機唯一 token
# 出現在回覆文字 + 結構化事件或 session JSONL 確實出現針對探針檔的 Read tool_use」。
#
# headless 新 process = 確保不受既有 session 快取或中途熱載入狀態影響，
# 在乾淨新行程直接載入最新定義檔受測。
#
# Exit: 0 = PASS（tool call 真實執行）/ 1 = FAIL / 2 = 用法錯誤
set -uo pipefail

usage() {
  echo "usage: smoke-agent.sh [--read-only] <agent-name>" >&2
}

READ_ONLY=0
AGENT=""
for arg in "$@"; do
  case "$arg" in
    --read-only)
      READ_ONLY=1
      ;;
    -h|--help)
      usage
      exit 2
      ;;
    -*)
      echo "smoke-agent.sh: unknown option: $arg" >&2
      usage
      exit 2
      ;;
    *)
      if [ -n "$AGENT" ]; then
        usage
        exit 2
      fi
      AGENT="$arg"
      ;;
  esac
done

if [ -z "$AGENT" ]; then
  usage
  exit 2
fi

if [[ ! "$AGENT" =~ ^[A-Za-z0-9_.:-]+$ ]] || [[ "$AGENT" == *..* ]]; then
  echo "smoke-agent.sh: invalid agent name: $AGENT" >&2
  exit 2
fi

CLAUDE_BIN="${CLAUDE_BIN:-$HOME/.local/bin/claude}"
PROOF_DIR="${SMOKE_PROOF_DIR:-/tmp/agent-smoke}"
mkdir -p "$PROOF_DIR"
SAFE_AGENT="${AGENT//:/_}"

if [ "$READ_ONLY" -eq 1 ]; then
  if command -v uuidgen >/dev/null 2>&1; then
    NONCE_UUID=$(uuidgen | tr '[:upper:]' '[:lower:]')
  else
    NONCE_UUID=$(python3 -c 'import uuid; print(uuid.uuid4())')
  fi
  TOKEN="SMOKE_READ_NONCE_${NONCE_UUID}"
  PROBE_FILE=$(mktemp "$PROOF_DIR/${SAFE_AGENT}-read-probe.XXXXXX")
  cleanup_probe() {
    rm -f "$PROBE_FILE"
  }
  trap cleanup_probe EXIT
  printf '%s\n' "$TOKEN" > "$PROBE_FILE"
  STDOUT_LOG="$PROOF_DIR/${SAFE_AGENT}-read-stdout.log"

  env -u CLAUDECODE -u CLAUDE_CODE_ENTRYPOINT CC_VENDOR=headless-channel "$CLAUDE_BIN" \
    --agent "$AGENT" \
    --output-format stream-json --verbose \
    -p "diagnostic read-only smoke probe：這是一次唯讀工具鏈探針，不要修改、建立或刪除任何檔案。請用 Read 工具讀取 ${PROBE_FILE}，並在回覆中原樣輸出檔案裡的完整 token。" \
    > "$STDOUT_LOG" 2>&1
  CLAUDE_RC=$?

  VERIFY_REASON=$(python3 - "$STDOUT_LOG" "$PROBE_FILE" "$TOKEN" "${CLAUDE_CONFIG_DIR:-$HOME/.claude}" "$CLAUDE_RC" <<'PY'
import json
import os
import sys
from pathlib import Path

stdout_path = Path(sys.argv[1])
probe_path_str = sys.argv[2]
probe_path = Path(probe_path_str)
token = sys.argv[3]
config_dir = Path(sys.argv[4])
claude_rc = int(sys.argv[5])

if not probe_path.is_file() or probe_path.read_text(encoding="utf-8", errors="replace").strip() != token:
  print("probe_mutated: 唯讀探針檔在執行期間遭刪除或修改")
  sys.exit(1)

probe_real = os.path.realpath(probe_path_str)


def path_matches(candidate: object) -> bool:
  if not isinstance(candidate, str) or not candidate:
    return False
  return candidate == probe_path_str or os.path.realpath(candidate) == probe_real


def inspect_events(events: list[dict]) -> tuple[bool, bool, set[str]]:
  saw_token = False
  saw_read = False
  session_ids: set[str] = set()
  stream_text_parts: list[str] = []
  pending_read_json: str | None = None

  def check_tool_use_block(block: object) -> bool:
    if not isinstance(block, dict):
      return False
    if block.get("type") != "tool_use" or block.get("name") != "Read":
      return False
    tool_input = block.get("input")
    if not isinstance(tool_input, dict):
      return False
    return path_matches(tool_input.get("file_path") or tool_input.get("path"))

  for ev in events:
    if not isinstance(ev, dict):
      continue
    sid = ev.get("session_id")
    if isinstance(sid, str) and sid:
      session_ids.add(sid)

    ev_type = ev.get("type")
    if ev_type == "result":
      res_text = ev.get("result")
      if isinstance(res_text, str) and token in res_text:
        saw_token = True
    elif ev_type == "assistant":
      msg = ev.get("message")
      if isinstance(msg, dict):
        content = msg.get("content")
        if isinstance(content, list):
          for item in content:
            if not isinstance(item, dict):
              continue
            if item.get("type") == "text":
              txt = item.get("text")
              if isinstance(txt, str) and token in txt:
                saw_token = True
            elif check_tool_use_block(item):
              saw_read = True
    elif check_tool_use_block(ev):
      saw_read = True
    elif ev_type == "stream_event":
      se = ev.get("event")
      if isinstance(se, dict):
        se_type = se.get("type")
        if se_type == "content_block_start":
          cb = se.get("content_block")
          if isinstance(cb, dict) and cb.get("type") == "tool_use" and cb.get("name") == "Read":
            pending_read_json = ""
          else:
            pending_read_json = None
        elif se_type == "content_block_delta":
          delta = se.get("delta")
          if isinstance(delta, dict):
            if delta.get("type") == "text_delta" and isinstance(delta.get("text"), str):
              stream_text_parts.append(delta["text"])
            elif delta.get("type") == "input_json_delta" and pending_read_json is not None and isinstance(delta.get("partial_json"), str):
              pending_read_json += delta["partial_json"]
        elif se_type in ("content_block_stop", "message_stop") and pending_read_json is not None:
          try:
            parsed_input = json.loads(pending_read_json)
            if isinstance(parsed_input, dict) and path_matches(parsed_input.get("file_path") or parsed_input.get("path")):
              saw_read = True
          except json.JSONDecodeError:
            pass
          pending_read_json = None

    messages = ev.get("messages")
    if isinstance(messages, list):
      sub_tok, sub_read, _ = inspect_events([m if isinstance(m, dict) else {} for m in messages])
      saw_token = saw_token or sub_tok
      saw_read = saw_read or sub_read

  if stream_text_parts and token in "".join(stream_text_parts):
    saw_token = True
  return saw_token, saw_read, session_ids


raw_text = stdout_path.read_text(encoding="utf-8", errors="replace") if stdout_path.is_file() else ""
parsed_events: list[dict] = []
for raw_line in raw_text.splitlines():
  stripped = raw_line.strip()
  if not stripped:
    continue
  try:
    loaded = json.loads(stripped)
  except json.JSONDecodeError:
    continue
  if isinstance(loaded, dict):
    parsed_events.append(loaded)
  elif isinstance(loaded, list):
    parsed_events.extend(x for x in loaded if isinstance(x, dict))

if not parsed_events and raw_text.strip():
  try:
    loaded_whole = json.loads(raw_text)
    if isinstance(loaded_whole, dict):
      parsed_events.append(loaded_whole)
    elif isinstance(loaded_whole, list):
      parsed_events.extend(x for x in loaded_whole if isinstance(x, dict))
  except json.JSONDecodeError:
    pass

token_verified, read_verified, found_sids = inspect_events(parsed_events)
if not parsed_events and token in raw_text:
  token_verified = True

if not read_verified and found_sids and (config_dir / "projects").is_dir():
  for sid in found_sids:
    for jsonl_file in (config_dir / "projects").rglob(f"{sid}.jsonl"):
      session_events: list[dict] = []
      for line in jsonl_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
          continue
        try:
          obj = json.loads(line)
        except json.JSONDecodeError:
          continue
        if isinstance(obj, dict):
          session_events.append(obj)
      _, sess_read, _ = inspect_events(session_events)
      if sess_read:
        read_verified = True
        break
    if read_verified:
      break

reasons: list[str] = []
if claude_rc != 0:
  reasons.append(f"claude exit={claude_rc}")
if not token_verified:
  reasons.append("stdout 回覆未包含探針隨機 token")
if not read_verified:
  reasons.append("未驗證到針對探針檔的真實 Read 工具呼叫")

if reasons:
  print("；".join(reasons))
  sys.exit(1)

print("ok")
sys.exit(0)
PY
  )
  VERIFY_RC=$?

  if [ "$VERIFY_RC" -eq 0 ]; then
    echo "PASS: $AGENT 通過唯讀 smoke probe（隨機 token 吻合且驗證真實 Read tool call）"
    exit 0
  else
    echo "FAIL: $AGENT 未通過唯讀 smoke probe（${VERIFY_REASON}）"
    echo "  → 模型輸出見 ${STDOUT_LOG}（若見 tool call JSON 以純文字出現 = 零工具症狀，查 frontmatter tools 欄）"
    exit 1
  fi
fi

PROOF="$PROOF_DIR/${SAFE_AGENT}-$(date +%s)-$$.txt"
TOKEN="smoke-ok-$$"
STDOUT_LOG="$PROOF_DIR/${SAFE_AGENT}-stdout.log"

env -u CLAUDECODE -u CLAUDE_CODE_ENTRYPOINT CC_VENDOR=headless-channel "$CLAUDE_BIN" --agent "$AGENT" -p \
  "diagnostic smoke probe：用 Bash tool 執行 echo ${TOKEN} > ${PROOF} 然後 cat ${PROOF} 回報內容。這是在驗證你能不能發真正的 tool call。" \
  > "$STDOUT_LOG" 2>&1

if [ -f "$PROOF" ] && grep -qF "$TOKEN" "$PROOF"; then
  echo "PASS: $AGENT 發出真實 tool call（$PROOF 內容吻合）"
  rm -f "$PROOF"
  exit 0
else
  echo "FAIL: $AGENT 沒有真實執行 tool call（$PROOF 不存在或內容不符）"
  echo "  → 模型輸出見 $STDOUT_LOG（若見 tool call JSON 以純文字出現 = 零工具症狀，查 frontmatter tools 欄）"
  rm -f "$PROOF"
  exit 1
fi
