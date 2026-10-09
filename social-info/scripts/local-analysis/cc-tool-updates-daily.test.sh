#!/usr/bin/env bash
# cc-tool-updates-daily.sh 的 smoke test（測 --json 確定性部分：三名單分類 + JSON 結構 + graceful）。
# 用 fixture manifest/ignore 注入（CCTOOL_MANIFEST/IGNORE env），只查 sem 一個工具的網路比對。
set -uo pipefail
HELPER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/cc-tool-updates-daily.sh"
TMP="$(mktemp -d)"
trap 'rc=$?; rm -rf "$TMP"; exit $rc' EXIT
fail(){ echo "❌ FAIL: $1"; exit 1; }

export CCTOOL_PIN_CHECK=0
NOTES="$TMP/tool-upgrade-notes.json"
cat > "$NOTES" <<'EOF'
{"schema_version":1,"tools":{"skillevaluator":{"report_note":"⚠️ trial 釘版：升級要一起改 EXPECTED_COMMIT、用完整 40 碼 SHA 重裝、跑 skillevaluator-trial.test.py"}}}
EOF
export CCTOOL_UPGRADE_NOTES="$NOTES"

[ -x "$HELPER" ] || fail "helper 不存在或不可執行: $HELPER"

MANIFEST_DIR="$(dirname "$HELPER")"
python3 - "$MANIFEST_DIR/cc-tool-manifest.json" "$MANIFEST_DIR/cc-tool-ignore.txt" <<'PY' || fail "production 名單 maintenance 斷言失敗"
import json, sys
manifest_path, ignore_path = sys.argv[1:]
manifest = json.load(open(manifest_path))
by_name = {item['name']: item for item in manifest}
ignore = {line.strip() for line in open(ignore_path) if line.strip() and not line.startswith('#')}
assert by_name['steipete/tap/peekaboo'] == {
  'name': 'steipete/tap/peekaboo',
  'manager': 'brew',
  'source': 'peekaboo',
}, by_name.get('steipete/tap/peekaboo')
assert {'go', 'yarn'} <= ignore
assert not {'chungchihhan/tap/tracce', 'serena-agent'} & by_name.keys()
assert 'agent-browser' in by_name
assert by_name['ollama'] == {'name': 'ollama', 'manager': 'brew', 'source': 'ollama'}
assert not {'dev-browser', 'yarn'} & by_name.keys()
print('✅ 測 0 production 名單：go 忽略、Peekaboo／Ollama 追蹤、dev-browser/yarn 非 active npm-g owner 已移除、agent-browser 保留')
PY

# fixture：白名單追 sem（本機 cargo-git 有）、黑名單忽略 cargo-bundle（本機有）
printf '[{"name":"sem","manager":"cargo-git","source":"Ataraxy-Labs/sem"}]' > "$TMP/m.json"
printf 'cargo-bundle\n' > "$TMP/i.txt"

out=$(CCTOOL_MANIFEST="$TMP/m.json" CCTOOL_IGNORE="$TMP/i.txt" "$HELPER" --json 2>/dev/null)
rc=$?
[ $rc -eq 0 ] || fail "exit code $rc != 0"

echo "$out" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert set(d) >= {'updates','discovered','errors'}, 'JSON 缺 key: '+str(list(d))
assert isinstance(d['updates'], list) and isinstance(d['discovered'], list) and isinstance(d['errors'], list), '三 key 非 list'
disc = {x['name'] for x in d['discovered']}
assert 'sem' not in disc, 'sem 在白名單卻被當 discovered'
assert 'cargo-bundle' not in disc, 'cargo-bundle 在黑名單卻被當 discovered'
assert len(d['discovered']) > 0, 'discovered 為空（本機應有未分類工具，發現層可能壞了）'
print('✅ 測 1 三名單分類：白(sem)追蹤、黑(cargo-bundle)忽略、其餘進 discovered（'+str(len(d['discovered']))+' 個）')
print('✅ 測 2 JSON 結構：updates/discovered/errors 三 list 齊全')
" || fail "JSON 斷言失敗"

# Homebrew revision：用固定 stub 驗相同 revision、舊 revision、多 keg 順序與 revision=0
BREW_BIN="$TMP/bin"
mkdir -p "$BREW_BIN"
cat > "$BREW_BIN/brew" <<'EOF'
#!/bin/bash
case "$BREW_SCENARIO:$*" in
  same:"list --versions --formula") printf 'python@3.12 3.12.13_4 3.12.12_5\n' ;;
  older:"list --versions --formula") printf 'python@3.12 3.12.13_3 3.12.12_5\n' ;;
  zero:"list --versions --formula") printf 'ast-grep 0.45.1\n' ;;
  segments:"list --versions --formula") printf 'example 1.2_5 1.2.1\n' ;;
  *:"leaves") printf 'python@3.12\nast-grep\n' ;;
  same:"info --json=v2 python@3.12"|older:"info --json=v2 python@3.12") printf '{"formulae":[{"versions":{"stable":"3.12.13"},"revision":4}]}' ;;
  zero:"info --json=v2 ast-grep") printf '{"formulae":[{"versions":{"stable":"0.45.1"},"revision":0}]}' ;;
  segments:"info --json=v2 example") printf '{"formulae":[{"versions":{"stable":"1.2.1"},"revision":0}]}' ;;
  *) exit 1 ;;
esac
EOF
chmod +x "$BREW_BIN/brew"
printf '[{"name":"python@3.12","manager":"brew","source":"python@3.12"}]' > "$TMP/m-brew.json"
printf '[{"name":"ast-grep","manager":"brew","source":"ast-grep"}]' > "$TMP/m-brew-zero.json"
printf '[{"name":"example","manager":"brew","source":"example"}]' > "$TMP/m-brew-segments.json"
out_same=$(PATH="$BREW_BIN:/usr/bin:/bin" BREW_SCENARIO=same CCTOOL_MANIFEST="$TMP/m-brew.json" CCTOOL_IGNORE="$TMP/i.txt" "$HELPER" --json 2>/dev/null)
out_older=$(PATH="$BREW_BIN:/usr/bin:/bin" BREW_SCENARIO=older CCTOOL_MANIFEST="$TMP/m-brew.json" CCTOOL_IGNORE="$TMP/i.txt" "$HELPER" --json 2>/dev/null)
out_zero=$(PATH="$BREW_BIN:/usr/bin:/bin" BREW_SCENARIO=zero CCTOOL_MANIFEST="$TMP/m-brew-zero.json" CCTOOL_IGNORE="$TMP/i.txt" "$HELPER" --json 2>/dev/null)
out_segments=$(PATH="$BREW_BIN:/usr/bin:/bin" BREW_SCENARIO=segments CCTOOL_MANIFEST="$TMP/m-brew-segments.json" CCTOOL_IGNORE="$TMP/i.txt" "$HELPER" --json 2>/dev/null)
python3 - "$out_same" "$out_older" "$out_zero" "$out_segments" <<'PY' || fail "Homebrew revision 斷言失敗"
import json, sys
same, older, zero, segments = (json.loads(value) for value in sys.argv[1:])
assert same['errors'] == [], same['errors']
assert same['updates'] == [], same['updates']
assert older['errors'] == [], older['errors']
assert older['updates'] == [{'name': 'python@3.12', 'manager': 'brew', 'current': '3.12.13_3', 'latest': '3.12.13_4', 'source': 'python@3.12', 'notes': ''}], older['updates']
assert zero['errors'] == [], zero['errors']
assert zero['updates'] == [], zero['updates']
assert segments['errors'] == [], segments['errors']
assert segments['updates'] == [], segments['updates']
print('✅ 測 3 Homebrew revision：多 keg 取新版、舊 revision 正確升級、revision=0 無後綴、基礎版本段落優先')
PY

NPM_HIGH="$TMP/npm-high"
NPM_ACTIVE="$TMP/npm-active"
NPM_BIN="$TMP/npm-bin"
mkdir -p "$NPM_HIGH/@qwen-code/qwen-code" "$NPM_ACTIVE/@qwen-code/qwen-code" "$NPM_BIN"
printf '{"name":"@qwen-code/qwen-code","version":"0.21.10","bin":{"qwen":"cli-entry.js"}}' > "$NPM_HIGH/@qwen-code/qwen-code/package.json"
printf '{"name":"@qwen-code/qwen-code","version":"0.21.6","bin":{"qwen":"cli-entry.js"}}' > "$NPM_ACTIVE/@qwen-code/qwen-code/package.json"
printf '#!/usr/bin/env node\n' > "$NPM_HIGH/@qwen-code/qwen-code/cli-entry.js"
printf '#!/usr/bin/env node\n' > "$NPM_ACTIVE/@qwen-code/qwen-code/cli-entry.js"
ln -s "$NPM_ACTIVE/@qwen-code/qwen-code/cli-entry.js" "$NPM_BIN/qwen"
cat > "$NPM_BIN/npm" <<'EOF'
#!/bin/bash
case "$*" in
  "view @qwen-code/qwen-code version") printf '0.21.11\n' ;;
  *) exit 1 ;;
esac
EOF
chmod +x "$NPM_BIN/npm" "$NPM_BIN/qwen"
printf '[{"name":"@qwen-code/qwen-code","manager":"npm-g","source":"@qwen-code/qwen-code"}]' > "$TMP/m-npm.json"
out_npm=$(PATH="$NPM_BIN:/usr/bin:/bin" CCTOOL_NPM_ROOTS="$NPM_HIGH:$NPM_ACTIVE" CCTOOL_MANIFEST="$TMP/m-npm.json" CCTOOL_IGNORE="$TMP/i.txt" "$HELPER" --json 2>/dev/null)
python3 - "$out_npm" "$NPM_ACTIVE" "$NPM_HIGH" <<'PY' || fail "npm 多 prefix 斷言失敗"
import json, sys
packet = json.loads(sys.argv[1])
active_root, other_root = sys.argv[2:]
assert packet['errors'] == [], packet['errors']
assert packet['updates'] == [{
  'name': '@qwen-code/qwen-code',
  'manager': 'npm-g',
  'current': '0.21.6',
  'latest': '0.21.11',
  'source': '@qwen-code/qwen-code',
  'notes': '',
  'active_install': active_root,
  'other_installs': [{'version': '0.21.10', 'root': other_root}],
}], packet['updates']
print('✅ 測 4 npm 多 prefix：current 採 PATH 作用中安裝，其他版本分欄保留')
PY

NPM_SHIM_ROOT="$TMP/npm-shim-root"
NPM_SHIM_BIN="$TMP/npm-shim-bin"
mkdir -p "$NPM_SHIM_ROOT/shim-tool" "$NPM_SHIM_BIN"
printf '{"name":"shim-tool","version":"1.2.3","bin":{"shim-tool":"cli-entry.js"}}' > "$NPM_SHIM_ROOT/shim-tool/package.json"
printf '#!/usr/bin/env node\n' > "$NPM_SHIM_ROOT/shim-tool/cli-entry.js"
cat > "$NPM_SHIM_ROOT/shim-tool/platform-bin" <<'EOF'
#!/bin/bash
[ "$1" = "--version" ] && { printf 'shim-tool 1.2.3\n'; exit 0; }
exit 1
EOF
ln -s "$NPM_SHIM_ROOT/shim-tool/platform-bin" "$NPM_SHIM_BIN/shim-tool"
cat > "$NPM_SHIM_BIN/npm" <<'EOF'
#!/bin/bash
[ "$*" = "view shim-tool version" ] && { printf '1.2.4\n'; exit 0; }
exit 1
EOF
chmod +x "$NPM_SHIM_ROOT/shim-tool/platform-bin" "$NPM_SHIM_BIN/npm"
printf '[{"name":"shim-tool","manager":"npm-g","source":"shim-tool"}]' > "$TMP/m-npm-shim.json"
out_npm_shim=$(PATH="$NPM_SHIM_BIN:/usr/bin:/bin" CCTOOL_NPM_ROOTS="$NPM_SHIM_ROOT" CCTOOL_MANIFEST="$TMP/m-npm-shim.json" CCTOOL_IGNORE="$TMP/i.txt" "$HELPER" --json 2>/dev/null)
python3 - "$out_npm_shim" "$NPM_SHIM_ROOT" <<'PY' || fail "npm transformed executable 斷言失敗"
import json, sys
packet = json.loads(sys.argv[1])
active_root = sys.argv[2]
assert packet['errors'] == [], packet['errors']
assert packet['updates'] == [{
  'name': 'shim-tool',
  'manager': 'npm-g',
  'current': '1.2.3',
  'latest': '1.2.4',
  'source': 'shim-tool',
  'notes': '',
  'active_install': active_root,
  'other_installs': [],
}], packet['updates']
print('✅ 測 4b npm transformed executable：package 內 platform binary 可辨識 active')
PY

NPM_UNOWNED_ROOT="$TMP/npm-unowned-root"
NPM_UNOWNED_BIN="$TMP/npm-unowned-bin"
mkdir -p "$NPM_UNOWNED_ROOT/unowned-tool" "$NPM_UNOWNED_BIN"
printf '{"name":"unowned-tool","version":"2.0.0","bin":{"unowned-tool":"cli-entry.js"}}' > "$NPM_UNOWNED_ROOT/unowned-tool/package.json"
printf '#!/usr/bin/env node\n' > "$NPM_UNOWNED_ROOT/unowned-tool/cli-entry.js"
cat > "$NPM_UNOWNED_BIN/unowned-tool" <<'EOF'
#!/bin/bash
[ "$1" = "--version" ] && { printf '2.0.0\n'; exit 0; }
exit 1
EOF
cat > "$NPM_UNOWNED_BIN/npm" <<'EOF'
#!/bin/bash
[ "$*" = "view unowned-tool version" ] && { printf '2.1.0\n'; exit 0; }
exit 1
EOF
chmod +x "$NPM_UNOWNED_BIN/unowned-tool" "$NPM_UNOWNED_BIN/npm"
printf '[{"name":"unowned-tool","manager":"npm-g","source":"unowned-tool"}]' > "$TMP/m-npm-unowned.json"
out_npm_unowned=$(PATH="$NPM_UNOWNED_BIN:/usr/bin:/bin" CCTOOL_NPM_ROOTS="$NPM_UNOWNED_ROOT" CCTOOL_MANIFEST="$TMP/m-npm-unowned.json" CCTOOL_IGNORE="$TMP/i.txt" "$HELPER" --json 2>/dev/null)
python3 - "$out_npm_unowned" <<'PY' || fail "npm unowned executable 斷言失敗"
import json, sys
packet = json.loads(sys.argv[1])
assert packet['updates'] == [], packet['updates']
assert len(packet['errors']) == 1 and 'no executable on PATH' in packet['errors'][0]['reason'], packet['errors']
print('✅ 測 4c npm unowned executable：同名同版本但不屬 package 時不誤判 active')
PY

NPM_AMBIG_A="$TMP/npm-ambig-a"
NPM_AMBIG_B="$TMP/npm-ambig-b"
NPM_AMBIG_BIN="$TMP/npm-ambig-bin"
mkdir -p "$NPM_AMBIG_A/ambiguous-tool" "$NPM_AMBIG_B/ambiguous-tool" "$NPM_AMBIG_BIN"
printf '{"name":"ambiguous-tool","version":"1.0.0","bin":{"amb-a":"a.js","amb-b":"b.js"}}' > "$NPM_AMBIG_A/ambiguous-tool/package.json"
printf '{"name":"ambiguous-tool","version":"2.0.0","bin":{"amb-a":"a.js","amb-b":"b.js"}}' > "$NPM_AMBIG_B/ambiguous-tool/package.json"
printf '#!/usr/bin/env node\n' > "$NPM_AMBIG_A/ambiguous-tool/a.js"
printf '#!/usr/bin/env node\n' > "$NPM_AMBIG_B/ambiguous-tool/b.js"
printf '#!/bin/bash\n' > "$NPM_AMBIG_A/ambiguous-tool/platform-a"
printf '#!/bin/bash\n' > "$NPM_AMBIG_B/ambiguous-tool/platform-b"
ln -s "$NPM_AMBIG_A/ambiguous-tool/platform-a" "$NPM_AMBIG_BIN/amb-a"
ln -s "$NPM_AMBIG_B/ambiguous-tool/platform-b" "$NPM_AMBIG_BIN/amb-b"
cat > "$NPM_AMBIG_BIN/npm" <<'EOF'
#!/bin/bash
[ "$*" = "view ambiguous-tool version" ] && { printf '3.0.0\n'; exit 0; }
exit 1
EOF
chmod +x "$NPM_AMBIG_A/ambiguous-tool/platform-a" "$NPM_AMBIG_B/ambiguous-tool/platform-b" "$NPM_AMBIG_BIN/npm"
printf '[{"name":"ambiguous-tool","manager":"npm-g","source":"ambiguous-tool"}]' > "$TMP/m-npm-ambig.json"
out_npm_ambig=$(PATH="$NPM_AMBIG_BIN:/usr/bin:/bin" CCTOOL_NPM_ROOTS="$NPM_AMBIG_A:$NPM_AMBIG_B" CCTOOL_MANIFEST="$TMP/m-npm-ambig.json" CCTOOL_IGNORE="$TMP/i.txt" "$HELPER" --json 2>/dev/null)
python3 - "$out_npm_ambig" <<'PY' || fail "npm ambiguous executable 斷言失敗"
import json, sys
packet = json.loads(sys.argv[1])
assert packet['updates'] == [], packet['updates']
assert len(packet['errors']) == 1 and 'ambiguous active installs' in packet['errors'][0]['reason'], packet['errors']
print('✅ 測 4d npm ambiguous executable：多 install 各有 active bin 時明確報錯')
PY

UV_HOME="$TMP/uv-home"
UV_BIN="$TMP/uv-bin"
UV_META="$UV_HOME/.local/share/uv/tools/skillevaluator/lib/python3.13/site-packages/skillevaluator-0.2.1.dist-info"
mkdir -p "$UV_BIN" "$UV_META"
printf '%s\n' 'Name: skillevaluator' 'Version: 0.2.1' > "$UV_META/METADATA"
printf '%s' '{"url":"https://github.com/NVIDIA/SkillEvaluator.git","vcs_info":{"vcs":"git","commit_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}}' > "$UV_META/direct_url.json"
cat > "$UV_BIN/uv" <<'EOF'
#!/bin/bash
if [ "$*" = "tool list" ]; then printf 'skillevaluator v0.2.1\n- skillevaluator\n'; else exit 1; fi
EOF
cat > "$UV_BIN/gh" <<'EOF'
#!/bin/bash
if [ "$*" = "api repos/NVIDIA/SkillEvaluator/commits/HEAD --jq .sha" ]; then printf 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n'; else exit 1; fi
EOF
chmod +x "$UV_BIN/uv" "$UV_BIN/gh"
printf '[{"name":"skillevaluator","manager":"uv-git","source":"NVIDIA/SkillEvaluator"}]' > "$TMP/m-uv-git.json"
out_uv_git=$(HOME="$UV_HOME" PATH="$UV_BIN:/usr/bin:/bin" CCTOOL_MANIFEST="$TMP/m-uv-git.json" CCTOOL_IGNORE="$TMP/i.txt" "$HELPER" --json 2>/dev/null)
python3 - "$out_uv_git" <<'PY' || fail "uv-git 斷言失敗"
import json, sys
packet = json.loads(sys.argv[1])
assert packet['errors'] == [], packet['errors']
assert packet['updates'] == [{
  'name': 'skillevaluator',
  'manager': 'uv-git',
  'current': 'aaaaaaaa',
  'latest': 'bbbbbbbb',
  'source': 'NVIDIA/SkillEvaluator',
  'notes': '',
  'upgrade_note': '⚠️ trial 釘版：升級要一起改 EXPECTED_COMMIT、用完整 40 碼 SHA 重裝、跑 skillevaluator-trial.test.py',
}], packet['updates']
print('✅ 測 5 uv-git：讀 direct_url commit、比對 GitHub HEAD、附升級注意事項')
PY
report_uv_git=$(HOME="$UV_HOME" PATH="$UV_BIN:/usr/bin:/bin" CCTOOL_MANIFEST="$TMP/m-uv-git.json" CCTOOL_IGNORE="$TMP/i.txt" CCTOOL_OUT="$TMP/tool-report.md" "$HELPER" 2>/dev/null)
grep -q 'skillevaluator aaaaaaaa→bbbbbbbb（uv-git） ⚠️ trial 釘版：升級要一起改 EXPECTED_COMMIT、用完整 40 碼 SHA 重裝、跑 skillevaluator-trial.test.py' "$TMP/tool-report.md" || fail "markdown report 未顯示升級注意事項: $report_uv_git"
echo '✅ 測 5b markdown：使用者拍板前同一行可看到升級注意事項'

HOLD_NOTES="$TMP/tool-upgrade-notes-hold.json"
cat > "$HOLD_NOTES" <<'EOF'
{"schema_version":1,"tools":{"skillevaluator":{"report_note":"⚠️ pinned","hold_until":"2026-09-16","hold_reason":"trial 觀察窗內不換版"}}}
EOF
out_hold=$(HOME="$UV_HOME" PATH="$UV_BIN:/usr/bin:/bin" CCTOOL_MANIFEST="$TMP/m-uv-git.json" CCTOOL_IGNORE="$TMP/i.txt" CCTOOL_UPGRADE_NOTES="$HOLD_NOTES" LOCAL_ANALYSIS_DATE=2026-09-16 "$HELPER" --json 2>/dev/null)
python3 - "$out_hold" <<'PY' || fail "hold 斷言失敗"
import json, sys
packet = json.loads(sys.argv[1])
assert packet['updates'] == [], packet['updates']
assert len(packet['held']) == 1 and packet['held'][0]['name'] == 'skillevaluator', packet['held']
assert packet['held'][0]['hold_until'] == '2026-09-16' and packet['held'][0]['hold_reason'] == 'trial 觀察窗內不換版', packet['held'][0]
print('✅ 測 5c hold：hold_until 當天含當天仍暫緩、不進 updates、held 帶到期日與原因')
PY
report_hold=$(HOME="$UV_HOME" PATH="$UV_BIN:/usr/bin:/bin" CCTOOL_MANIFEST="$TMP/m-uv-git.json" CCTOOL_IGNORE="$TMP/i.txt" CCTOOL_UPGRADE_NOTES="$HOLD_NOTES" LOCAL_ANALYSIS_DATE=2026-09-16 CCTOOL_OUT="$TMP/tool-report-hold.md" "$HELPER" 2>/dev/null)
grep -q '^### 暫緩' "$TMP/tool-report-hold.md" || fail "markdown report 缺暫緩段: $report_hold"
grep -q 'skillevaluator aaaaaaaa→bbbbbbbb（uv-git）hold 至 2026-09-16；trial 觀察窗內不換版' "$TMP/tool-report-hold.md" || fail "暫緩行格式不符: $report_hold"
grep -q '^### 有更新' "$TMP/tool-report-hold.md" && fail "hold 中仍出現有更新段: $report_hold"
echo '✅ 測 5d markdown：hold 中只列暫緩段、不列有更新'
out_expired=$(HOME="$UV_HOME" PATH="$UV_BIN:/usr/bin:/bin" CCTOOL_MANIFEST="$TMP/m-uv-git.json" CCTOOL_IGNORE="$TMP/i.txt" CCTOOL_UPGRADE_NOTES="$HOLD_NOTES" LOCAL_ANALYSIS_DATE=2026-09-17 "$HELPER" --json 2>/dev/null)
python3 - "$out_expired" <<'PY' || fail "hold 到期斷言失敗"
import json, sys
packet = json.loads(sys.argv[1])
assert packet['held'] == [], packet['held']
assert len(packet['updates']) == 1 and packet['updates'][0]['name'] == 'skillevaluator', packet['updates']
print('✅ 測 5e hold 到期：隔天自動回到有更新')
PY

# graceful：fixture manifest 含不存在的 manager → 進 errors 不崩
printf '[{"name":"nonexistent-xyz","manager":"cargo-git","source":"no/such-repo"}]' > "$TMP/m2.json"
out2=$(CCTOOL_MANIFEST="$TMP/m2.json" CCTOOL_IGNORE="$TMP/i.txt" "$HELPER" --json 2>/dev/null)
rc2=$?
[ $rc2 -eq 0 ] || fail "graceful: 不存在工具讓 exit code $rc2 != 0"
echo "$out2" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert any(e['name']=='nonexistent-xyz' for e in d['errors']), '不存在工具未進 errors'
print('✅ 測 4 graceful：不存在工具進 errors、exit 0、不崩')
" || fail "graceful 斷言失敗"

# mcp-npx：釘版 MCP server 從 ~/.claude.json 讀版本、比 npm latest；未釘版與雙檔不一致進 errors
NPM_BIN="$TMP/npmbin"
mkdir -p "$NPM_BIN"
cat > "$NPM_BIN/npm" <<'EOF'
#!/bin/bash
case "$*" in
  "view chrome-devtools-mcp version") printf '1.8.0\n' ;;
  *) exit 1 ;;
esac
EOF
chmod +x "$NPM_BIN/npm"
printf '%s' '{"mcpServers":{"chrome-devtools":{"command":"npx","args":["chrome-devtools-mcp@1.6.0","--autoConnect"]},"ctx":{"command":"npx","args":["-y","@upstash/context7-mcp@latest"]},"local-stdio":{"command":"python3","args":["server.py"]}}}' > "$TMP/c1.json"
printf '%s' '{"mcpServers":{"chrome-devtools":{"command":"npx","args":["chrome-devtools-mcp@1.6.0","--autoConnect"]}}}' > "$TMP/c2.json"
printf '%s' '{"mcpServers":{"chrome-devtools":{"command":"npx","args":["chrome-devtools-mcp@1.7.0","--autoConnect"]}}}' > "$TMP/c3.json"
printf '[{"name":"chrome-devtools","manager":"mcp-npx","source":"chrome-devtools-mcp"},{"name":"ctx","manager":"mcp-npx"}]' > "$TMP/m5.json"
out5=$(PATH="$NPM_BIN:$PATH" CCTOOL_CLAUDE_JSON="$TMP/c1.json:$TMP/c2.json" CCTOOL_MANIFEST="$TMP/m5.json" CCTOOL_IGNORE="$TMP/i.txt" "$HELPER" --json 2>/dev/null)
[ $? -eq 0 ] || fail "mcp-npx: exit code != 0"
echo "$out5" | python3 -c "
import sys, json
d = json.load(sys.stdin)
u = [x for x in d['updates'] if x['name']=='chrome-devtools']
assert u and u[0]['manager']=='mcp-npx' and u[0]['current']=='1.6.0' and u[0]['latest']=='1.8.0', 'mcp-npx 釘版比對錯: '+str(u)
assert len(u[0]['configs'])==2, 'configs 應列出兩份 .claude.json: '+str(u[0])
e = [x for x in d['errors'] if x['name']=='ctx']
assert e and 'unpinned' in e[0]['reason'], '未釘版 (@latest) 應進 errors: '+str(d['errors'])
assert not any(x['name']=='local-stdio' for x in d['discovered']+d['errors']+d['updates']), '非 npx 的 stdio server 不該被 mcp-npx 撿到'
print('✅ 測 5 mcp-npx：釘版 1.6.0 vs npm 1.8.0 進 updates、兩份 config 並列；@latest 進 errors(unpinned)；非 npx server 不撿')
" || fail "mcp-npx 斷言失敗"
out6=$(PATH="$NPM_BIN:$PATH" CCTOOL_CLAUDE_JSON="$TMP/c1.json:$TMP/c3.json" CCTOOL_MANIFEST="$TMP/m5.json" CCTOOL_IGNORE="$TMP/i.txt" "$HELPER" --json 2>/dev/null)
echo "$out6" | python3 -c "
import sys, json
d = json.load(sys.stdin)
e = [x for x in d['errors'] if x['name']=='chrome-devtools']
assert e and 'mismatch' in e[0]['reason'], '兩份 config 釘不同版應進 errors(mismatch): '+str(d['errors'])
assert not any(x['name']=='chrome-devtools' for x in d['updates']), 'mismatch 時不該進 updates'
print('✅ 測 6 mcp-npx：兩份 config 釘版不一致 → errors(config mismatch)、不比對')
" || fail "mcp-npx mismatch 斷言失敗"

GH_BIN="$TMP/gh-pin"
mkdir -p "$GH_BIN"
GH_LOG="$TMP/gh-calls.log"
CL_FIXTURE="$TMP/changelog.txt"

pin_stub(){
cat > "$GH_BIN/gh" <<EOF
#!/bin/bash
echo "\$*" >> "$GH_LOG"
case "\$*" in
  *"issues/90299 --jq .state"*) printf '$1\n' ;;
  *"issues/90537 --jq .state"*) printf '$2\n' ;;
  *"contents/CHANGELOG.md"*) base64 < "$CL_FIXTURE" ;;
  *"releases?per_page=100"*) printf 'v2.1.251\nv2.1.250\n' ;;
  *) exit 1 ;;
esac
EOF
chmod +x "$GH_BIN/gh"
}

pin_run(){
  CCTOOL_PIN_CHECK=1 PATH="$GH_BIN:/usr/bin:/bin" \
  CCTOOL_MANIFEST="$TMP/m-empty.json" CCTOOL_IGNORE="$TMP/i.txt" \
  "$HELPER" --json 2>/dev/null
}

printf "[]" > "$TMP/m-empty.json"
printf '## 2.1.251\n- Fixed something unrelated\n- Tab to toggle thinking (sticky across sessions)\n\n## 2.1.245\n- Fullscreen sticky prompt header fixed\n\n## ' > "$CL_FIXTURE"
pin_stub open open
: > "$GH_LOG"
out_pin1=$(pin_run)
rc=$?
[ $rc -eq 0 ] || fail "pin 測 7: exit code $rc != 0"
grep -q 'issues/90299' "$GH_LOG" || fail "pin 檢查未查詢受監控 issue（gh 呼叫 log: $(cat "$GH_LOG")）"
grep -q 'contents/CHANGELOG.md' "$GH_LOG" || fail "pin 檢查未查詢 CHANGELOG"
grep -q 'releases?per_page=100' "$GH_LOG" || fail "pin 檢查未查詢候選 release"
echo "$out_pin1" | python3 -c "
import sys, json
d = json.load(sys.stdin)
hits = [u for u in d['updates'] if u.get('manager') == 'claude-code-pin']
assert not hits, 'issues 全 open 且 CHANGELOG 無訊號，不該有 pin finding: ' + str(hits)
pin_err = [e for e in d['errors'] if e.get('name') == 'claude-code-pin']
assert not pin_err, 'stub gh 正常時 pin 檢查不該進 errors: ' + str(pin_err)
print('✅ 測 7 pin 靜默：issue open + CHANGELOG 無訊號 → 無 finding、不進 errors')
" || fail "pin 測 7 斷言失敗"

pin_stub closed open
out_pin2=$(pin_run)
rc=$?
[ $rc -eq 0 ] || fail "pin 測 8: exit code $rc != 0"
echo "$out_pin2" | python3 -c "
import sys, json
d = json.load(sys.stdin)
hits = [u for u in d['updates'] if u.get('manager') == 'claude-code-pin']
assert hits, 'issue closed + 有候選 release，該產生 pin finding'
u = hits[0]
assert u['latest'] == 'v2.1.251' and u['current'] == '2.1.246', 'finding 應列 pin 版本與候選 release: ' + str(u)
assert '重新驗證' in u['notes'], 'finding 應要求人工重新驗證: ' + str(u)
assert '未驗證是否已修復' in u['notes'], 'finding 必須附未驗證免責聲明、不得宣稱已修復: ' + str(u)
print('✅ 測 8 pin finding：issue closed → 提醒人工重新驗證、附候選 release')
" || fail "pin 測 8 斷言失敗"

pin_stub open open
printf '## 2.1.250\n- Fullscreen sticky prompt header renders again\n' > "$CL_FIXTURE"
out_pin3=$(pin_run)
echo "$out_pin3" | python3 -c "
import sys, json
d = json.load(sys.stdin)
hits = [u for u in d['updates'] if u.get('manager') == 'claude-code-pin']
assert hits, 'CHANGELOG 命中 sticky prompt 應產生 finding'
assert 'sticky prompt' in hits[0]['notes'], 'notes 應標命中原因: ' + str(hits[0])
assert hits[0]['latest'] == 'v2.1.251' and hits[0]['current'] == '2.1.246', '版本對比錯: ' + str(hits[0])
print('✅ 測 9 CHANGELOG 命中 sticky prompt → finding')
" || fail "pin 測 9 斷言失敗"

printf '## 2.1.250\n- Fix fullscreen regression (#90537)\n' > "$CL_FIXTURE"
out_pin4=$(pin_run)
echo "$out_pin4" | python3 -c "
import sys, json
d = json.load(sys.stdin)
hits = [u for u in d['updates'] if u.get('manager') == 'claude-code-pin']
assert hits, 'CHANGELOG 命中 issue #90537 應產生 finding'
assert '#90537' in hits[0]['notes'], 'notes 應標命中 issue 編號: ' + str(hits[0])
print('✅ 測 10 CHANGELOG 命中受監控 issue 編號 → finding')
" || fail "pin 測 10 斷言失敗"

printf '## 2.1.252\n- Restored fullscreen sticky prompt header\n' > "$CL_FIXTURE"
cat > "$GH_BIN/gh" <<EOF
#!/bin/bash
case "\$*" in
  *"issues/90299 --jq .state"*|*"issues/90537 --jq .state"*) printf 'open\n' ;;
  *"contents/CHANGELOG.md"*) base64 < "$CL_FIXTURE" ;;
  *"releases?per_page=5"*) printf 'v2.1.257\nv2.1.256\nv2.1.255\nv2.1.254\nv2.1.253\n' ;;
  *"releases?per_page=100"*) printf 'v2.1.257\nv2.1.256\nv2.1.255\nv2.1.254\nv2.1.253\nv2.1.252\n' ;;
  *) exit 1 ;;
esac
EOF
chmod +x "$GH_BIN/gh"
out_pin5=$(pin_run)
echo "$out_pin5" | python3 -c "
import sys, json
d = json.load(sys.stdin)
hits = [u for u in d['updates'] if u.get('manager') == 'claude-code-pin']
assert hits, '較早候選 release 的修復訊號不該被查詢窗口擠出'
assert hits[0]['latest'] == 'v2.1.257', 'finding 應仍列最新候選 release: ' + str(hits[0])
print('✅ 測 11 release 窗口：第六筆候選版本含修復訊號仍會 finding')
" || fail "pin 測 11 斷言失敗"

cat > "$GH_BIN/gh" <<'EOF'
#!/bin/bash
exit 1
EOF
chmod +x "$GH_BIN/gh"
out_pin6=$(pin_run)
rc=$?
[ $rc -eq 0 ] || fail "pin 測 12: exit code $rc != 0"
echo "$out_pin6" | python3 -c "
import sys, json
d = json.load(sys.stdin)
hits = [u for u in d['updates'] if u.get('manager') == 'claude-code-pin']
assert not hits, '查詢失敗不得當成修復訊號: ' + str(hits)
errs = [e for e in d['errors'] if e.get('name') == 'claude-code-pin']
assert errs, '查詢失敗應進 errors'
print('✅ 測 12 gh 失敗：只進 errors、無修復 finding、exit 0')
" || fail "pin 測 12 斷言失敗"

# ---- 測 13 npm min-release-age：@latest 未滿天數 → 有更新退到已滿天數的最高版、新版進 release_pending 附解禁日 ----
AGE_BIN="$TMP/npm-age-bin"
mkdir -p "$AGE_BIN"
ln -s "$NPM_ACTIVE/@qwen-code/qwen-code/cli-entry.js" "$AGE_BIN/qwen"
cat > "$AGE_BIN/npm" <<'EOF'
#!/bin/bash
case "$*" in
  "config get min-release-age") printf '7\n' ;;
  "view @qwen-code/qwen-code version") printf '0.21.11\n' ;;
  "view @qwen-code/qwen-code time --json") printf '{"created":"2025-01-01T00:00:00.000Z","modified":"2026-09-17T00:00:00.000Z","0.21.6":"2026-08-20T00:00:00.000Z","0.21.10":"2026-09-01T00:00:00.000Z","0.21.11-rc.1":"2026-09-02T00:00:00.000Z","0.21.11":"2026-09-17T00:00:00.000Z"}\n' ;;
  *) exit 1 ;;
esac
EOF
chmod +x "$AGE_BIN/npm"
out_age=$(PATH="$AGE_BIN:/usr/bin:/bin" CCTOOL_NPM_ROOTS="$NPM_HIGH:$NPM_ACTIVE" CCTOOL_MANIFEST="$TMP/m-npm.json" CCTOOL_IGNORE="$TMP/i.txt" LOCAL_ANALYSIS_DATE=2026-09-20 "$HELPER" --json 2>/dev/null)
report_age=$(PATH="$AGE_BIN:/usr/bin:/bin" CCTOOL_NPM_ROOTS="$NPM_HIGH:$NPM_ACTIVE" CCTOOL_MANIFEST="$TMP/m-npm.json" CCTOOL_IGNORE="$TMP/i.txt" LOCAL_ANALYSIS_DATE=2026-09-20 CCTOOL_OUT="$TMP/tool-report-age.md" "$HELPER" 2>/dev/null)
out_age_current=$(PATH="$AGE_BIN:/usr/bin:/bin" CCTOOL_NPM_ROOTS="$NPM_HIGH:$NPM_ACTIVE" CCTOOL_MANIFEST="$TMP/m-npm.json" CCTOOL_IGNORE="$TMP/i.txt" LOCAL_ANALYSIS_DATE=2026-09-24 "$HELPER" --json 2>/dev/null)
python3 - "$out_age" "$report_age" "$out_age_current" <<'PY' || fail "npm min-release-age 斷言失敗"
import json, sys
packet, report, unlocked = json.loads(sys.argv[1]), sys.argv[2], json.loads(sys.argv[3])
assert packet['errors'] == [], packet['errors']
assert [(u['current'], u['latest']) for u in packet['updates']] == [('0.21.6', '0.21.10')], packet['updates']
assert packet['release_pending'] == [{
  'name': '@qwen-code/qwen-code', 'manager': 'npm-g', 'current': '0.21.6', 'installable': '0.21.10',
  'version': '0.21.11', 'published': '2026-09-17', 'unlock_date': '2026-09-24', 'min_release_age': 7,
}], packet['release_pending']
assert '### ⏳ 未滿 release age' in report and '0.21.11' in report and '2026-09-24 解禁' in report, report
assert [(u['current'], u['latest']) for u in unlocked['updates']] == [('0.21.6', '0.21.11')], unlocked['updates']
assert unlocked['release_pending'] == [], unlocked['release_pending']
print('✅ 測 13 npm min-release-age：有更新退到已滿 7 天的 0.21.10、0.21.11 進 ⏳ 附解禁日、prerelease 不計、到期日當天回到有更新')
PY

# ---- 測 14 npm 已裝版本比「已滿天數最高版」新 → 不得報成有更新（降版誤報） ----
DOWN_BIN="$TMP/npm-down-bin"
mkdir -p "$DOWN_BIN"
ln -s "$NPM_ACTIVE/@qwen-code/qwen-code/cli-entry.js" "$DOWN_BIN/qwen"
cat > "$DOWN_BIN/npm" <<'EOF'
#!/bin/bash
case "$*" in
  "config get min-release-age") printf '7\n' ;;
  "view @qwen-code/qwen-code version") printf '0.21.11\n' ;;
  "view @qwen-code/qwen-code time --json") printf '{"created":"2025-01-01T00:00:00.000Z","modified":"2026-09-19T00:00:00.000Z","0.21.5":"2026-09-01T00:00:00.000Z","0.21.6":"2026-09-18T00:00:00.000Z","0.21.11":"2026-09-19T00:00:00.000Z"}\n' ;;
  *) exit 1 ;;
esac
EOF
chmod +x "$DOWN_BIN/npm"
out_down=$(PATH="$DOWN_BIN:/usr/bin:/bin" CCTOOL_NPM_ROOTS="$NPM_HIGH:$NPM_ACTIVE" CCTOOL_MANIFEST="$TMP/m-npm.json" CCTOOL_IGNORE="$TMP/i.txt" LOCAL_ANALYSIS_DATE=2026-09-20 "$HELPER" --json 2>/dev/null)
python3 - "$out_down" <<'PY' || fail "npm 降版誤報斷言失敗"
import json, sys
packet = json.loads(sys.argv[1])
assert packet['errors'] == [], packet['errors']
assert packet['updates'] == [], packet['updates']
assert [(p['current'], p['version']) for p in packet['release_pending']] == [('0.21.6', '0.21.11')], packet['release_pending']
print('✅ 測 14 npm 降版：已裝 0.21.6 比已滿 7 天的 0.21.5 新 → 不進有更新、0.21.11 仍進 ⏳')
PY

echo "🎉 ALL PASS"
