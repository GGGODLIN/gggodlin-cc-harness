#!/bin/bash
# ticket-yagni 三支 hook ＋ runner 的 fixture 回歸。
# 四件起跳（known-good／known-bad／邊界／自身生命週期）＋ 寫檔 gate 必測（旁路未受影響／state 病態）。
# 跑法：bash ~/.claude/hooks/ticket-yagni.test.sh   全過時最後一行印 TICKET_YAGNI_TESTS_ALL_PASS_7f3a
set -u
HOOK=${TICKET_YAGNI_HOOK:-$HOME/.claude/hooks/ticket-yagni.py}
REAL_RUNNER=${TICKET_YAGNI_REAL_RUNNER:-$(dirname "$HOOK")/ticket-yagni-runner.py}
T=$(mktemp -d /tmp/ticket-yagni-test.XXXXXX)
export TICKET_YAGNI_ROOT="$T/root" MATT_TDD_ROOT="$T/matt" TICKET_YAGNI_OFF="$T/off" TICKET_YAGNI_RUNNER="$T/stub-runner.py"
export TICKET_YAGNI_PENDING_TTL=700 TICKET_YAGNI_RUNNER_TIMEOUT=20 TICKET_YAGNI_FAIL_OPEN=1
unset TICKET_YAGNI_FAKE_RESPONSE
SESSION=sess-test-0001; RUN=call_test_run
PASS=0; FAIL=0
ok(){ PASS=$((PASS+1)); echo "  PASS $1"; }
bad(){ FAIL=$((FAIL+1)); echo "  FAIL $1 :: $2"; }
check(){ if eval "$2"; then ok "$1"; else bad "$1" "$2"; fi; }

# ---- fixtures ----
mkdir -p "$MATT_TDD_ROOT/$SESSION/$RUN"
cat > "$MATT_TDD_ROOT/$SESSION/$RUN/decision.json" <<EOF
{"contract":"MATT_TDD_DECISION v1","status":"started","session_id":"$SESSION","run_id":"$RUN","tickets":[{"id":"09","decision":"required"},{"id":"03","decision":"required"},{"id":"12","decision":"waived"},{"id":"14","decision":"required"}]}
EOF
REPO="$T/repo"; mkdir -p "$REPO/.scratch/feat/issues"
git -C "$REPO" init -q; git -C "$REPO" config user.email t@t; git -C "$REPO" config user.name t
printf 'hello\n' > "$REPO/README.md"
cat > "$REPO/.scratch/feat/issues/09-wire.md" <<'EOF'
# 09 — Wire the watcher

**Status:** `ready-for-agent`

- [ ] Wire config and schedule — Source: Story 1
EOF
printf '# 03\n\n**Status:** `ready-for-agent`\n' > "$REPO/.scratch/feat/issues/03-other.md"
printf '# 12\n\n**Status:** `ready-for-agent`\n' > "$REPO/.scratch/feat/issues/12-late.md"
cat > "$REPO/.scratch/feat/2026-01-01-feat-yagni-review.md" <<'EOF'
# YAGNI review

## 一頁最簡版

一個 launchd watcher，每小時抓一次，Discord 發訊。

## 其他
無
EOF
git -C "$REPO" add -A; git -C "$REPO" commit -qm base
BASE=$(git -C "$REPO" rev-parse HEAD)
printf 'hello\nworld\n' > "$REPO/README.md"
printf 'class Foo:\n  pass\n\ndef bar():\n  return 1\n' > "$REPO/mod.py"
SNAP_BEFORE="$T/repo-before"
mkdir -p "$SNAP_BEFORE/.scratch/feat/issues"
cp "$REPO/README.md" "$REPO/mod.py" "$SNAP_BEFORE/"
cp "$REPO/.scratch/feat/issues/09-wire.md" "$SNAP_BEFORE/.scratch/feat/issues/"

cat > "$TICKET_YAGNI_RUNNER" <<'EOF'
#!/usr/bin/env python3
import json,os,sys,time
a=sys.argv; out=a[a.index('--out')+1]; ticket=a[a.index('--ticket')+1]
mode=os.environ.get('STUB_MODE','keep')
if mode=='hang': time.sleep(30)
if mode=='error':
  open(os.path.join(out,'error.json'),'w').write(json.dumps({'error':'relay http 500 stub'})); sys.exit(1)
if mode=='skip':
  open(os.path.join(out,'skip.json'),'w').write(json.dumps({'skip':'empty-diff','ticket':ticket})); sys.exit(0)
vs=[{'item':'FILE:mod.py','verdict':'keep','basis':'a','ticket_quote':'Wire config','reason':'core'}]
if mode=='kill':
  vs.append({'item':'Foo','verdict':'kill','basis':'c','ticket_quote':'none','reason':'unused manager class'})
  vs.append({'item':'bar','verdict':'demote','basis':'c','ticket_quote':'none','reason':'retry loop unjustified'})
counts={k:sum(1 for v in vs if v['verdict']==k) for k in ('keep','demote','kill')}
open(os.path.join(out,'verdict.json'),'w').write(json.dumps({'ticket':ticket,'verdicts':vs,'counts':counts,'elapsed':1.0,'missing_information':[]}))
EOF
chmod +x "$TICKET_YAGNI_RUNNER"

hook(){ # $1 subcmd, $2 json ; sets OUT ERR RC
  OUT=$(printf '%s' "$2" | python3 "$HOOK" "$1" 2>"$T/err.txt"); RC=$?; ERR=$(cat "$T/err.txt")
}
j(){ python3 -c 'import json,sys;print(json.dumps(dict(a.split("=",1) for a in sys.argv[1:])))' "$@"; }
reg_input(){ # desc prompt resp session
  python3 - "$1" "$2" "$3" "$4" "$REPO" <<'EOF'
import json,sys
d,p,r,s,cwd=sys.argv[1:]
print(json.dumps({"hook_event_name":"PostToolUse","session_id":s,"cwd":cwd,"tool_name":"Agent","tool_use_id":"toolu_fg_0001","tool_input":{"description":d,"prompt":p,"subagent_type":"routed-impl"},"tool_response":r}))
EOF
}
notif(){ # task-id status session
  python3 - "$1" "$2" "$3" "$REPO" <<'EOF'
import json,sys
tid,st,s,cwd=sys.argv[1:]
p=f"<task-notification>\n<task-id>{tid}</task-id>\n<status>{st}</status>\n<summary>Agent done</summary>\n</task-notification>"
print(json.dumps({"hook_event_name":"UserPromptSubmit","session_id":s,"cwd":cwd,"prompt":p}))
EOF
}
gate_input(){ # tool file new session
  python3 - "$1" "$2" "$3" "$4" "$REPO" <<'EOF'
import json,sys
tool,f,new,s,cwd=sys.argv[1:]
ti={"file_path":f}
if tool=='Edit': ti.update({"old_string":"**Status:** `ready-for-agent`","new_string":new})
elif tool=='Write': ti.update({"content":new})
else: ti.update({"edits":[{"old_string":"x","new_string":new}]})
print(json.dumps({"hook_event_name":"PreToolUse","session_id":s,"cwd":cwd,"tool_name":tool,"tool_input":ti}))
EOF
}
REG="$TICKET_YAGNI_ROOT/$SESSION/workers.jsonl"; AUD="$TICKET_YAGNI_ROOT/audit.jsonl"
T09="$REPO/.scratch/feat/issues/09-wire.md"; T03="$REPO/.scratch/feat/issues/03-other.md"; T12="$REPO/.scratch/feat/issues/12-late.md"
T14="$REPO/.scratch/feat/issues/14-emptydiff.md"; printf '# 14 empty diff\n\n**Status:** in progress\n' > "$T14"
ASYNC_RESP='Async agent launched successfully. agentId: abc123def0 (internal ID). The agent is working in the background.'

echo "== register =="
hook register "$(reg_input 'Ticket 09 wire' "work in $REPO" "$ASYNC_RESP" other-session)"
check "R1 non-implement session silent" '[ $RC -eq 0 ] && [ -z "$OUT" ] && [ ! -e "$REG" ]'
hook register "$(reg_input 'Ticket 09 wire watcher' "既有流程續作狀態：implement。worktree: $REPO" "$ASYNC_RESP" $SESSION)"
check "R2 registers ticket/agent/base" "[ \$RC -eq 0 ] && grep -q '\"ticket\": \"09\"' '$REG' && grep -q 'abc123def0' '$REG' && grep -q '$BASE' '$REG'"
N_BEFORE=$(wc -l < "$REG")
hook register "$(reg_input 'do some stuff' 'no ticket here' "$ASYNC_RESP" $SESSION)"
check "R3 unmatched ticket -> audit, no registry line" "[ \$RC -eq 0 ] && [ \$(wc -l < '$REG') -eq $N_BEFORE ] && grep -q register-unmatched '$AUD'"
N_BEFORE_PROMPT_ONLY=$(wc -l < "$REG")
hook register "$(reg_input '<review-implement-selection:v1 model=opus axis=scope>' "review the diff, see .scratch/foo/issues/03-wire-watcher.md for context" "$ASYNC_RESP" $SESSION)"
check "R3b prompt-only ticket number does not register" "[ \$RC -eq 0 ] && [ \$(wc -l < '$REG') -eq \$N_BEFORE_PROMPT_ONLY ] && grep -q register-unmatched '$AUD'"
STUB_MODE=keep hook register "$(reg_input 'ticket 03 inline' "path $REPO" 'Final result: done, all tests green.' $SESSION)"
check "R4 foreground agent reviewed immediately (all keep -> exit 0)" "[ \$RC -eq 0 ] && ls '$TICKET_YAGNI_ROOT/$SESSION/${RUN}__03/'fg-*/verdict.json >/dev/null 2>&1 && grep -q review-done '$AUD'"

echo "== deliver =="
hook deliver "$(j hook_event_name=UserPromptSubmit session_id=$SESSION prompt='hello there')"
check "D1 plain prompt silent" '[ $RC -eq 0 ] && [ -z "$OUT" ] && [ -z "$ERR" ]'
hook deliver "$(notif zzz999 completed $SESSION)"
check "D2 unregistered task-id -> audit" "[ \$RC -eq 0 ] && grep -q deliver-unregistered '$AUD'"
hook deliver "$(python3 -c 'import json;print(json.dumps({"hook_event_name":"UserPromptSubmit","session_id":"'$SESSION'","prompt":"<task-notification>\n<summary>Stop hook feedback</summary>\n</task-notification>\n<system-reminder>x</system-reminder>"}))')"
check "D3 rewake-shaped notification (no task-id) silent" '[ $RC -eq 0 ] && [ -z "$OUT" ] && [ -z "$ERR" ]'
STUB_MODE=kill hook deliver "$(notif abc123def0 completed $SESSION)"
V09="$TICKET_YAGNI_ROOT/$SESSION/${RUN}__09/abc123def0"
check "D4 registered delivery with kill -> exit 2 + summary" "[ \$RC -eq 2 ] && echo \"\$ERR\" | grep -q 'kill 1／demote 1' && echo \"\$ERR\" | grep -q 'Foo' && [ -f '$V09/verdict.json' ] && [ ! -e '$V09/pending.json' ]"
STUB_MODE=kill hook deliver "$(notif abc123def0 completed $SESSION)"
check "D5 same worker second delivery not re-reviewed" "[ \$RC -eq 0 ] && grep -q deliver-already-reviewed '$AUD'"
hook register "$(reg_input 'Ticket 03 second worker' "$REPO" 'Async agent launched successfully. agentId: def456abc0 (internal)' $SESSION)"
STUB_MODE=keep hook deliver "$(notif def456abc0 completed $SESSION)"
check "D6 all-keep delivery -> exit 0, no wake" '[ $RC -eq 0 ] && [ -z "$ERR" ]'
hook register "$(reg_input 'Ticket 03 third worker' "$REPO" 'Async agent launched successfully. agentId: errr010000 (internal)' $SESSION)"
STUB_MODE=error hook deliver "$(notif errr010000 completed $SESSION)"
check "D7 runner error -> exit 2 + failure notice + error.json" "[ \$RC -eq 2 ] && echo \"\$ERR\" | grep -q '審查失敗' && [ -f '$TICKET_YAGNI_ROOT/$SESSION/${RUN}__03/errr010000/error.json' ]"
hook register "$(reg_input 'Ticket 03 hang worker' "$REPO" 'Async agent launched successfully. agentId: hang010000 (internal)' $SESSION)"
STUB_MODE=hang TICKET_YAGNI_RUNNER_TIMEOUT=2 hook deliver "$(notif hang010000 completed $SESSION)"
check "D8 runner timeout -> error.json with timeout, exit 2" "[ \$RC -eq 2 ] && grep -q 'timeout' '$TICKET_YAGNI_ROOT/$SESSION/${RUN}__03/hang010000/error.json'"
echo "== gate =="
DONE_LINE='**Status:** `completed`'
hook gate "$(gate_input Edit "$REPO/src/app.py" "$DONE_LINE" $SESSION)"
check "G1 non-ticket file silent" '[ $RC -eq 0 ] && [ -z "$OUT" ]'
hook gate "$(gate_input Edit "$T09" '- [x] done wiring' $SESSION)'"
check "G2 boundary: 'done' outside Status line silent" '[ $RC -eq 0 ] && [ -z "$OUT" ]'
hook gate "$(gate_input Edit "$T09" "$DONE_LINE" other-session)"
check "G3 non-implement session silent" '[ $RC -eq 0 ] && [ -z "$OUT" ]'
hook gate "$(gate_input Edit "$REPO/.scratch/feat/issues/05-none.md" "$DONE_LINE" $SESSION)"
check "G4 ticket not in decision silent" '[ $RC -eq 0 ] && [ -z "$OUT" ]'
hook gate "$(gate_input Edit "$T09" "$DONE_LINE" $SESSION)"
check "G5 verdict with kill -> deny once with item list" "[ \$RC -eq 0 ] && echo \"\$OUT\" | grep -q '\"permissionDecision\": \"deny\"' && echo \"\$OUT\" | grep -q 'kill Foo' && [ -f '$V09/delivered' ]"
hook gate "$(gate_input Edit "$T09" "$DONE_LINE" $SESSION)"
check "G6 second attempt after delivery -> allow" '[ $RC -eq 0 ] && [ -z "$OUT" ]'
hook gate "$(gate_input Edit "$T03" "$DONE_LINE" $SESSION)"
check "G7 latest worker has error.json -> fail-open allow + audit" "[ \$RC -eq 0 ] && [ -z \"\$OUT\" ] && grep -q gate-allow-fail-open-error '$AUD'"
hook register "$(reg_input 'Ticket 03 pending worker' "$REPO" 'Async agent launched successfully. agentId: pend010000 (internal)' $SESSION)"
PD="$TICKET_YAGNI_ROOT/$SESSION/${RUN}__03/pend010000"; mkdir -p "$PD"
python3 -c "import json,time;open('$PD/pending.json','w').write(json.dumps({'started':time.time()}))"
hook gate "$(gate_input Edit "$T03" "$DONE_LINE" $SESSION)"
check "G8 fresh pending -> deny" "echo \"\$OUT\" | grep -q deny && echo \"\$OUT\" | grep -q '還在跑'"
python3 -c "import json,time;open('$PD/pending.json','w').write(json.dumps({'started':time.time()-800}))"
hook gate "$(gate_input Edit "$T03" "$DONE_LINE" $SESSION)"
check "G9 stale pending -> fail-open allow + audit" "[ -z \"\$OUT\" ] && grep -q gate-allow-fail-open-stale-pending '$AUD'"
TICKET_YAGNI_FAIL_OPEN=0 hook gate "$(gate_input Edit "$T03" "$DONE_LINE" $SESSION)"
check "G14 fail-closed policy: stale pending -> deny" 'echo "$OUT" | grep -q deny'
hook gate "$(gate_input Edit "$T12" "$DONE_LINE" $SESSION)"
check "G10 unregistered ticket -> deny with remedy" "echo \"\$OUT\" | grep -q deny && echo \"\$OUT\" | grep -q '沒有登記' && echo \"\$OUT\" | grep -q -- '--manual'"
# 2026-10-14：Inline（沒有 worker）時補救指令要直接可跑——票檔與 worktree 填好、不要求不存在的 worker worktree
REPO_TOP=$(git -C "$REPO" rev-parse --show-toplevel)
check "G10b unregistered remedy is runnable for Inline: ticket-file + toplevel worktree filled, no worker placeholder" "echo \"\$OUT\" | grep -qF -- '--ticket-file $T12' && echo \"\$OUT\" | grep -qF -- '--worktree $REPO_TOP ' && ! echo \"\$OUT\" | grep -qF '<worker worktree>' && echo \"\$OUT\" | grep -q '開工前'"
hook gate "$(gate_input Edit "$T12" '**Status:** implementation complete — thin runner verified' $SESSION)"
check "G11 boundary: R1-style 'implementation complete' counts as completion" 'echo "$OUT" | grep -q deny'
hook gate "$(gate_input Write "$T12" "# 12\n\n$DONE_LINE\n" $SESSION)"
check "G12 Write tool content also gated" 'echo "$OUT" | grep -q deny'
hook register "$(reg_input 'Ticket 12 nodeliver' "$REPO" 'Async agent launched successfully. agentId: nodl010000 (internal)' $SESSION)"
hook gate "$(gate_input Edit "$T12" "$DONE_LINE" $SESSION)"
check "G13 registered but no delivery -> deny" 'echo "$OUT" | grep -q "沒有交件審查紀錄"'
mkdir -p "$TICKET_YAGNI_ROOT/$SESSION/${RUN}__12/manual"; printf '{"verdicts":[],"counts":{"keep":0,"demote":0,"kill":0}}' > "$TICKET_YAGNI_ROOT/$SESSION/${RUN}__12/manual/verdict.json"
hook gate "$(gate_input Edit "$T12" "$DONE_LINE" $SESSION)"
check "G15 manual runner verdict unlocks close" '[ -z "$OUT" ]'
hook register "$(reg_input 'Ticket 03 failed worker' "$REPO" 'Async agent launched successfully. agentId: fail010000 (internal)' $SESSION)"
hook deliver "$(notif fail010000 failed $SESSION)"
check "D9 failed task status -> not reviewed" "[ \$RC -eq 0 ] && grep -q deliver-not-completed '$AUD' && [ ! -e '$TICKET_YAGNI_ROOT/$SESSION/${RUN}__03/fail010000/verdict.json' ]"

echo "== empty-diff skip path (2026-09-13 review: 空 diff 佔 runner 失敗 29%) =="
hook register "$(reg_input 'Ticket 03 skip worker' "$REPO" 'Async agent launched successfully. agentId: skip010000 (internal)' $SESSION)"
STUB_MODE=skip hook deliver "$(notif skip010000 completed $SESSION)"
check "D10 empty diff delivery -> exit 0, skip audit, no wake, no error.json" "[ \$RC -eq 0 ] && [ -z \"\$ERR\" ] && grep -q review-skip-empty-diff '$AUD' && [ -f '$TICKET_YAGNI_ROOT/$SESSION/${RUN}__03/skip010000/skip.json' ] && [ ! -e '$TICKET_YAGNI_ROOT/$SESSION/${RUN}__03/skip010000/error.json' ]"
SKIPD="$TICKET_YAGNI_ROOT/$SESSION/${RUN}__14/manual"; mkdir -p "$SKIPD"; printf '{"skip":"empty-diff"}' > "$SKIPD/skip.json"
hook register "$(reg_input 'Ticket 14 skiponly' "$REPO" 'Async agent launched successfully. agentId: skiponly00 (internal)' $SESSION)"
mkdir -p "$TICKET_YAGNI_ROOT/$SESSION/${RUN}__14/skiponly00"; printf '{"skip":"empty-diff"}' > "$TICKET_YAGNI_ROOT/$SESSION/${RUN}__14/skiponly00/skip.json"
hook gate "$(gate_input Edit "$T14" "$DONE_LINE" $SESSION)"
check "G16 skip.json -> allow + gate-allow-empty-diff audit" "[ \$RC -eq 0 ] && [ -z \"\$OUT\" ] && grep -q gate-allow-empty-diff '$AUD'"
TICKET_YAGNI_FAIL_OPEN=0 hook gate "$(gate_input Edit "$T14" "$DONE_LINE" $SESSION)"
check "G17 skip allow is policy-independent: fail-closed still allows empty diff" "[ \$RC -eq 0 ] && [ -z \"\$OUT\" ]"
printf '{"error":"relay http 500 stub"}' > "$TICKET_YAGNI_ROOT/$SESSION/${RUN}__14/skiponly00/error.json"
TICKET_YAGNI_FAIL_OPEN=0 hook gate "$(gate_input Edit "$T14" "$DONE_LINE" $SESSION)"
check "G18 boundary: error.json + skip.json both present -> error wins (fail-closed deny)" 'echo "$OUT" | grep -q deny && echo "$OUT" | grep -q "fail-closed"'
rm -f "$TICKET_YAGNI_ROOT/$SESSION/${RUN}__14/skiponly00/error.json"

echo "== lifecycle: recovery sentinel =="
touch "$TICKET_YAGNI_OFF"
hook gate "$(gate_input Edit "$T12" "$DONE_LINE" $SESSION)"; G=$RC; GO=$OUT
STUB_MODE=kill hook deliver "$(notif abc123def0 completed $SESSION)"; D=$RC; DE=$ERR
hook register "$(reg_input 'Ticket 09 x' "$REPO" "$ASYNC_RESP" $SESSION)"; R=$RC
check "S1 sentinel silences all three" '[ $G -eq 0 ] && [ -z "$GO" ] && [ $D -eq 0 ] && [ -z "$DE" ] && [ $R -eq 0 ]'
rm -f "$TICKET_YAGNI_OFF"

echo "== state pathology =="
mv "$AUD" "$AUD.bak"; mkfifo "$AUD"
( printf '%s' "$(gate_input Edit "$T12" "$DONE_LINE" $SESSION)" | python3 "$HOOK" gate >/dev/null 2>&1; echo $? > "$T/p1.rc" ) &
P1PID=$!; for i in 1 2 3 4 5 6 7 8 9 10; do kill -0 $P1PID 2>/dev/null || break; sleep 0.5; done
if kill -0 $P1PID 2>/dev/null; then kill $P1PID 2>/dev/null; RC=124; else RC=$(cat "$T/p1.rc"); fi
check "P1 audit as FIFO: no hang, no crash" '[ $RC -eq 0 ]'
rm -f "$AUD"; mv "$AUD.bak" "$AUD"
mv "$REG" "$REG.bak"; ln -s "$AUD" "$REG"
hook register "$(reg_input 'Ticket 09 symlink' "$REPO" "$ASYNC_RESP" $SESSION)"
check "P2 registry as symlink: write refused, audit untouched by registry line" "[ \$RC -eq 0 ] && grep -q register-write-refused '$AUD' && ! grep -q '\"description\": \"Ticket 09 symlink' '$AUD'"
rm -f "$REG"; mv "$REG.bak" "$REG"

echo "== bypass untouched =="
check "B1 gate/deliver never wrote to repo or ticket files" 'cmp -s "$REPO/README.md" "$SNAP_BEFORE/README.md" && cmp -s "$REPO/mod.py" "$SNAP_BEFORE/mod.py" && cmp -s "$REPO/.scratch/feat/issues/09-wire.md" "$SNAP_BEFORE/.scratch/feat/issues/09-wire.md"'

echo "== runner =="
RO="$T/runner-out"; mkdir -p "$RO"
python3 "$REAL_RUNNER" --session $SESSION --run $RUN --ticket 09 --agent t --worktree "$REPO" --base "$BASE" --cwd "$REPO" --out "$RO" --dry-run --ticket-file "$REPO/.scratch/feat/issues/09-wire.md" > "$T/rn1.out" 2>&1; RC=$?
check "RN1 dry-run builds packet with ticket, spec-min, items, diff" "[ \$RC -eq 0 ] && grep -q '## 票原文' '$RO/packet.md' && grep -q '一頁最簡版' '$RO/packet.md' && grep -q -- '- FILE:mod.py' '$RO/packet.md' && grep -q -- '- Foo' '$RO/packet.md' && grep -q -- '- bar' '$RO/packet.md' && grep -q -- '- FILE:README.md' '$RO/packet.md' && grep -q '^+world' '$RO/packet.md'"
cat > "$T/fake.json" <<'EOF'
{"model":"gpt-5.6-sol","choices":[{"message":{"content":"{\"verdicts\":[{\"item\":\"FILE:README.md\",\"verdict\":\"keep\",\"basis\":\"a\",\"ticket_quote\":\"Wire\",\"reason\":\"ok\"},{\"item\":\"FILE:mod.py\",\"verdict\":\"keep\",\"basis\":\"a\",\"ticket_quote\":\"Wire\",\"reason\":\"ok\"},{\"item\":\"Foo\",\"verdict\":\"kill\",\"basis\":\"c\",\"ticket_quote\":\"none\",\"reason\":\"unused\"}],\"missing_information\":[],\"summary\":\"s\"}"},"finish_reason":"stop"}],"usage":{"completion_tokens":10}}
EOF
RO2="$T/runner-out2"; mkdir -p "$RO2"
TICKET_YAGNI_FAKE_RESPONSE="$T/fake.json" python3 "$REAL_RUNNER" --session $SESSION --run $RUN --ticket 09 --agent t --worktree "$REPO" --base "$BASE" --cwd "$REPO" --out "$RO2" --ticket-file "$REPO/.scratch/feat/issues/09-wire.md" > "$T/rn2.out" 2>&1; RC=$?
check "RN2 fake relay response -> verdict.json with counts and coverage" "[ \$RC -eq 0 ] && grep -q '\"kill\": 1' '$RO2/verdict.json' && grep -q '\"missing\"' '$RO2/verdict.json' && grep -q '\"bar\"' '$RO2/verdict.json'"
check "RN2b verdict.json carries no packet digest field (packet is saved as packet.md)" "[ -f '$RO2/packet.md' ] && ! grep -q 'sha256' '$RO2/verdict.json'"
printf '{"model":"x","choices":[{"message":{"content":"sorry, cannot"}}]}' > "$T/fake-bad.json"; RO3="$T/runner-out3"; mkdir -p "$RO3"
TICKET_YAGNI_FAKE_RESPONSE="$T/fake-bad.json" python3 "$REAL_RUNNER" --session $SESSION --run $RUN --ticket 09 --agent t --worktree "$REPO" --base "$BASE" --cwd "$REPO" --out "$RO3" --ticket-file "$REPO/.scratch/feat/issues/09-wire.md" > "$T/rn3.out" 2>&1; RC=$?
check "RN3 non-JSON model reply -> error.json, exit 1" "[ \$RC -eq 1 ] && [ -f '$RO3/error.json' ] && grep -q 'no JSON object' '$RO3/error.json'"
RO4="$T/runner-out4"; mkdir -p "$RO4"
python3 "$REAL_RUNNER" --session $SESSION --run $RUN --ticket 77 --agent t --worktree "$REPO" --base "$BASE" --cwd "$REPO" --out "$RO4" --dry-run --manual > "$T/rn4.out" 2>&1; RC=$?
check "RN4 manual review, missing ticket file -> error.json, exit 1" "[ \$RC -eq 1 ] && grep -q 'not found' '$RO4/error.json'"
mkdir -p "$REPO/.scratch/other/issues"; printf '# 09 dup\n' > "$REPO/.scratch/other/issues/09-dup.md"
RO6="$T/runner-out6"; mkdir -p "$RO6"
python3 "$REAL_RUNNER" --session $SESSION --run $RUN --ticket 09 --agent t --worktree "$REPO" --base "$BASE" --cwd "$REPO" --out "$RO6" --dry-run --manual > "$T/rn6.out" 2>&1; RC=$?
check "RN6 manual review, ticket number in two feature dirs -> error listing both, exit 1 (2026-09-10 票 12 被解成別 feature 的 12)" "[ \$RC -eq 1 ] && grep -q 'matches 2 files' '$RO6/error.json' && grep -q 'ticket-file' '$RO6/error.json' && grep -q '09-dup.md' '$RO6/error.json'"
RO7="$T/runner-out7"; mkdir -p "$RO7"
python3 "$REAL_RUNNER" --session $SESSION --run $RUN --ticket 09 --agent t --worktree "$REPO" --base "$BASE" --cwd "$REPO" --out "$RO7" --dry-run --ticket-file "$REPO/.scratch/feat/issues/09-wire.md" > "$T/rn7.out" 2>&1; RC=$?
check "RN7 same layout with --ticket-file -> resolves, exit 0" "[ \$RC -eq 0 ] && grep -q '## 票原文' '$RO7/packet.md'"
rm -rf "$REPO/.scratch/other"
CLEAN="$T/clean-repo"; mkdir -p "$CLEAN/.scratch/feat/issues"
git -C "$CLEAN" init -q; git -C "$CLEAN" config user.email t@t; git -C "$CLEAN" config user.name t
printf '# 09 wire\n\nWire config.\n' > "$CLEAN/.scratch/feat/issues/09-wire.md"; printf 'x\n' > "$CLEAN/keep.txt"
git -C "$CLEAN" add -A; git -C "$CLEAN" commit -qm base
CLEAN_BASE=$(git -C "$CLEAN" rev-parse HEAD)
RO8="$T/runner-out8"; mkdir -p "$RO8"
python3 "$REAL_RUNNER" --session $SESSION --run $RUN --ticket 09 --agent t --worktree "$CLEAN" --base "$CLEAN_BASE" --cwd "$CLEAN" --out "$RO8" --ticket-file "$CLEAN/.scratch/feat/issues/09-wire.md" > "$T/rn8.out" 2>&1; RC=$?
check "RN8 empty diff -> skip.json, exit 0, no error.json, no relay call (firing branch, not stub)" "[ \$RC -eq 0 ] && [ -f '$RO8/skip.json' ] && grep -q 'empty-diff' '$RO8/skip.json' && [ ! -e '$RO8/error.json' ] && [ ! -e '$RO8/packet.md' ]"
check "RN5 relay key never written into outputs" "! grep -rq 'Authorization' '$RO2' '$RO3' 2>/dev/null"

echo
echo "PASS=$PASS FAIL=$FAIL  (tmp: $T)"
if [ $FAIL -eq 0 ]; then rm -rf "$T"; echo "TICKET_YAGNI_TESTS_ALL_PASS_7f3a"; exit 0; fi
exit 1
