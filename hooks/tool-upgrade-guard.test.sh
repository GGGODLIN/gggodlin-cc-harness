#!/bin/bash
set -u
HOOK="$HOME/.claude/hooks/tool-upgrade-guard.py"
T=$(mktemp -d /tmp/tool-upgrade-guard.XXXXXX)
trap 'rc=$?; rm -rf "$T"; exit $rc' EXIT
REG="$T/notes.json"; PIN="$T/pin.py"; OFF="$T/off"
OLD=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
NEW=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
PASS=0; FAIL=0
ok(){ PASS=$((PASS+1)); printf 'PASS %s\n' "$1"; }
bad(){ FAIL=$((FAIL+1)); printf 'FAIL %s\n' "$1"; }
run(){ OUT=$(printf '%s' "$(python3 -c 'import json,sys;print(json.dumps({"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":sys.argv[1]}}))' "$1")" | TOOL_UPGRADE_NOTES="$REG" TOOL_UPGRADE_GUARD_OFF="$OFF" python3 "$HOOK" 2>"$T/err"); RC=$?; }
check(){ if eval "$2"; then ok "$1"; else bad "$1"; fi; }
printf 'EXPECTED_COMMIT = "%s"\n' "$OLD" > "$PIN"
python3 - "$REG" "$PIN" <<'PY'
import json,sys
reg,pin=sys.argv[1:]
json.dump({'schema_version':1,'tools':{
  'skillevaluator':{'aliases':['skillevaluator'],'mode':'pinned','source_url':'https://github.com/NVIDIA/SkillEvaluator.git','pin_file':pin,'pin_pattern':'^EXPECTED_COMMIT\\s*=\\s*["\\\']([0-9a-f]{40})["\\\']','report_note':'trial pinned','verify_command':'python3 verify.py'},
  'semble':{'aliases':['semble'],'mode':'nudge','report_note':'refresh cache after upgrade','verify_command':'semble --version'}
}},open(reg,'w'))
PY
cp "$REG" "$T/base.json"
run 'git status'
check 'known-good non-upgrade silent' '[ $RC -eq 0 ] && [ -z "$OUT" ]'
run 'uv tool install ruff'
check 'unregistered tool upgrade silent' '[ $RC -eq 0 ] && [ -z "$OUT" ]'
run 'uv tool upgrade skillevaluator'
check 'pinned upgrade without SHA denied' 'echo "$OUT" | grep -q 'permissionDecision.*deny' && echo "$OUT" | grep -q "完整 40 碼"'
run "uv tool install 'skillevaluator @ git+https://github.com/NVIDIA/SkillEvaluator.git@$NEW'"
check 'mismatched full SHA denied' 'echo "$OUT" | grep -q 'permissionDecision.*deny' && echo "$OUT" | grep -q "$NEW" && echo "$OUT" | grep -q "$OLD"'
run "uv tool install 'skillevaluator @ git+https://github.com/NVIDIA/SkillEvaluator.git@${OLD:0:8}'"
check 'short SHA denied' 'echo "$OUT" | grep -q 'permissionDecision.*deny' && echo "$OUT" | grep -q "完整 40 碼"'
run "uv tool install 'skillevaluator @ git+https://github.com/NVIDIA/SkillEvaluator.git@$OLD'"
check 'matching full SHA allowed with verify nudge' '! echo "$OUT" | grep -q permissionDecision && echo "$OUT" | grep -q additionalContext && echo "$OUT" | grep -q "python3 verify.py"'
run 'printf "uv tool install skillevaluator"'
check 'boundary: prose containing command is denied' 'echo "$OUT" | grep -q 'permissionDecision.*deny' && echo "$OUT" | grep -q "Write／Edit"'
run 'uv tool install semble'
check 'nudge-only tool allowed with note' '! echo "$OUT" | grep -q permissionDecision && echo "$OUT" | grep -q "refresh cache"'
printf '{bad' > "$REG"
run 'uv tool install skillevaluator'
check 'malformed registry fails closed' 'echo "$OUT" | grep -q 'permissionDecision.*deny' && echo "$OUT" | grep -q "無法讀取"'
rm "$REG"; touch "$OFF"
run 'uv tool upgrade skillevaluator'
check 'recovery sentinel silences gate' '[ $RC -eq 0 ] && [ -z "$OUT" ]'
rm "$OFF"
printf 'EXPECTED_COMMIT = "short"\n' > "$PIN"
python3 - "$REG" "$PIN" <<'PY'
import json,sys
reg,pin=sys.argv[1:]
json.dump({'schema_version':1,'tools':{'skillevaluator':{'aliases':['skillevaluator'],'mode':'pinned','source_url':'https://github.com/NVIDIA/SkillEvaluator.git','pin_file':pin,'pin_pattern':'^EXPECTED_COMMIT\\s*=\\s*"([0-9a-f]{40})"','report_note':'x'}}},open(reg,'w'))
PY
run "uv tool install 'skillevaluator @ git+https://github.com/NVIDIA/SkillEvaluator.git@$OLD'"
check 'invalid pin source fails closed' 'echo "$OUT" | grep -q 'permissionDecision.*deny' && echo "$OUT" | grep -q "釘版規則無法驗證"'
printf 'EXPECTED_COMMIT = "%s"\n' "$OLD" > "$PIN"; cp "$T/base.json" "$REG"
run 'uv tool upgrade --all'
check 'uv tool upgrade --all denied when any pinned tool exists' 'echo "$OUT" | grep -q "permissionDecision.*deny" && echo "$OUT" | grep -q skillevaluator'
run 'uv tool upgrade'
check 'bare invalid uv tool upgrade is left to uv validation' '[ $RC -eq 0 ] && [ -z "$OUT" ]'
run 'npm -g install skillevaluator'
check 'npm global flag before install is detected' 'echo "$OUT" | grep -q "permissionDecision.*deny" && echo "$OUT" | grep -q "完整 40 碼"'
printf '[]' > "$REG"
run 'uv tool install skillevaluator'
check 'valid JSON with wrong root type fails closed' 'echo "$OUT" | grep -q "permissionDecision.*deny" && echo "$OUT" | grep -q "無法讀取"'
cp "$T/base.json" "$REG"; python3 - "$REG" <<'PY'
import json,sys
p=sys.argv[1]; d=json.load(open(p)); d['tools']['skillevaluator']['aliases']='skillevaluator'; json.dump(d,open(p,'w'))
PY
run 'uv tool install skillevaluator'
check 'aliases string schema error fails closed' 'echo "$OUT" | grep -q "permissionDecision.*deny" && echo "$OUT" | grep -q aliases'
cp "$T/base.json" "$REG"; python3 - "$REG" <<'PY'
import json,sys
p=sys.argv[1]; d=json.load(open(p)); d['tools']['skillevaluator']['mode']='Pinned'; json.dump(d,open(p,'w'))
PY
run "uv tool install 'skillevaluator @ git+https://github.com/NVIDIA/SkillEvaluator.git@$OLD'"
check 'unknown mode fails closed instead of nudge downgrade' 'echo "$OUT" | grep -q "permissionDecision.*deny" && echo "$OUT" | grep -q mode'
cp "$T/base.json" "$REG"; python3 - "$REG" <<'PY'
import json,sys
p=sys.argv[1]; d=json.load(open(p)); del d['tools']['skillevaluator']['source_url']; json.dump(d,open(p,'w'))
PY
run "uv tool install 'skillevaluator @ git+https://github.com/EVIL/other.git@$OLD'"
check 'missing source URL fails closed' 'echo "$OUT" | grep -q "permissionDecision.*deny" && echo "$OUT" | grep -q source_url'
cp "$T/base.json" "$REG"; python3 - "$REG" <<'PY'
import json,sys
p=sys.argv[1]; d=json.load(open(p)); d['tools']['skillevaluator']['pin_pattern']='^EXPECTED_COMMIT'; json.dump(d,open(p,'w'))
PY
run "uv tool install 'skillevaluator @ git+https://github.com/NVIDIA/SkillEvaluator.git@$OLD'"
check 'pin pattern without capture group fails closed' 'echo "$OUT" | grep -q "permissionDecision.*deny" && echo "$OUT" | grep -q "capture group"'
OUT=$(printf '[]' | TOOL_UPGRADE_NOTES="$T/base.json" TOOL_UPGRADE_GUARD_OFF="$OFF" python3 "$HOOK" 2>"$T/err"); RC=$?
check 'hook payload with wrong root type fails closed' '[ $RC -eq 0 ] && echo "$OUT" | grep -q "permissionDecision.*deny" && echo "$OUT" | grep -q "無法解析"'
printf 'PASS=%s FAIL=%s\n' "$PASS" "$FAIL"
[ $FAIL -eq 0 ] && { echo 'TOOL_UPGRADE_GUARD_ALL_PASS_87c2'; exit 0; }
exit 1
