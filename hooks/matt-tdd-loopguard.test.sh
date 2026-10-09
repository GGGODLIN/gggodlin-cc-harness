#!/usr/bin/env bash
# matt-tdd-gate Stop loop guard fixtures（gate-authoring §3／§5）：正反配對、total 保險、旁路、log 病態；2026-09-06 起 gate 為提示型，guard 是提醒上限
set -u
HOOK=~/.claude/hooks/matt-tdd-gate.sh
TMP=$(mktemp -d)
export MATT_TDD_ROOT="$TMP/state" MATT_TDD_PENDING_DIR="$TMP/pending" MATT_TDD_LOOPGUARD_DIR="$TMP/lg"
mkdir -p "$MATT_TDD_ROOT" "$MATT_TDD_PENDING_DIR"
trap 'rm -r "$TMP"' EXIT
P=0; F=0
ok() { echo "PASS $1"; P=$((P+1)); }
ng() { echo "FAIL $1 :: $2"; F=$((F+1)); }
stop() { jq -nc --arg s "$1" '{hook_event_name:"Stop",tool_name:"",session_id:$s,transcript_path:"/nonexistent",tool_use_id:"t",agent_id:"",tool_input:{}}' | "$HOOK" 2>/dev/null; }
is_advise() { printf '%s' "$1" | grep -q '"systemMessage"' && ! printf '%s' "$1" | grep -q '"decision":"block"'; }
malformed() { printf '{"contract":"nope"}' > "$MATT_TDD_PENDING_DIR/$1.json"; chmod 600 "$MATT_TDD_PENDING_DIR/$1.json"; }

malformed s1
o1=$(stop s1); o2=$(stop s1); o3=$(stop s1)
is_advise "$o1" && is_advise "$o2" && is_advise "$o3" && ok "正: 同狀態前 3 次提示、不 block" || ng "前 3 次應提示" "$o3"
printf '%s' "$o3" | grep -q 'same=3 total=3' && ok "提示訊息帶計數" || ng "訊息缺計數" "$o3"
o4=$(stop s1)
[ -z "$o4" ] && ok "正: 第 4 次同狀態 -> 停止提醒" || ng "第 4 次應停止提醒" "$o4"
[ ! -e "$MATT_TDD_PENDING_DIR/s1.json" ] && ok "放行後 marker 已移除" || ng "marker 仍在" ""
grep -q '"event": "ESCAPED"' "$MATT_TDD_LOOPGUARD_DIR/audit.jsonl" && ok "audit 記 ESCAPED" || ng "audit 無 ESCAPED" "$(cat "$MATT_TDD_LOOPGUARD_DIR/audit.jsonl")"

malformed s2
stop s2 >/dev/null; stop s2 >/dev/null
printf '{"contract":"changed"}' > "$MATT_TDD_PENDING_DIR/s2.json"
o=$(stop s2)
printf '%s' "$o" | grep -q 'same=1 total=3' && ok "反: marker 內容變 -> same 歸零、total 續累" || ng "狀態變未歸零" "$o"
o=$(stop s2)
is_advise "$o" && ok "反: 狀態變後仍提示" || ng "應仍提示" "$o"

malformed s3
for i in 1 2; do stop s3 >/dev/null; printf '{"contract":"v%s"}' "$i" > "$MATT_TDD_PENDING_DIR/s3.json"; done
for i in 3 4 5 6; do stop s3 >/dev/null; printf '{"contract":"v%s"}' "$i" > "$MATT_TDD_PENDING_DIR/s3.json"; done
o=$(stop s3)
[ -z "$o" ] && ok "保險: 指紋每次都變、total 第 7 次 -> 停止提醒" || ng "total 上限未停止" "$o"

malformed s4; malformed s5
stop s4 >/dev/null
[ -e "$MATT_TDD_PENDING_DIR/s5.json" ] && [ ! -e "$MATT_TDD_LOOPGUARD_DIR/$(printf s5 | shasum -a 256 | cut -c1-24).json" ] && ok "旁路: s4 的計數不碰 s5 的 marker 與 state" || ng "旁路被碰" ""

rm -f "$MATT_TDD_LOOPGUARD_DIR/audit.jsonl"; : > "$TMP/elsewhere"; ln -s "$TMP/elsewhere" "$MATT_TDD_LOOPGUARD_DIR/audit.jsonl"
malformed s6
o=$(stop s6)
is_advise "$o" && [ ! -s "$TMP/elsewhere" ] && ok "log 病態: audit 為 symlink -> 拒寫、仍提示、目標未被寫" || ng "symlink audit 處理錯" "$o"

echo "== $P passed, $F failed"; [ "$F" -eq 0 ]
