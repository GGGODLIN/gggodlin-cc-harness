#!/bin/bash
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/claude-path-rot-daily.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0
ok() { echo "PASS $1"; pass=$((pass+1)); }
ng() { echo "FAIL $1"; fail=$((fail+1)); }

ROOT="$TMP/claude"
mkdir -p "$ROOT/skills/alpha" "$ROOT/commands" "$ROOT/rules/common" "$ROOT/scripts" "$ROOT/state"
touch "$ROOT/scripts/exists.sh"
WL="$TMP/whitelist.txt"
printf '# wl\n~/.claude/scripts/whitelisted-missing.sh\n' > "$WL"

run() {
  PATH_ROT_CLAUDE_ROOT="$ROOT" PATH_ROT_WHITELIST="$WL" PATH_ROT_OUT="$TMP/out.md" HOME="$TMP" \
    LOCAL_ANALYSIS_DATE=2026-01-01 bash "$SCRIPT" >/dev/null 2>&1
  cat "$TMP/out.md"
}

cat > "$ROOT/CLAUDE.md" <<'EOF'
- 見 `~/.claude/scripts/exists.sh` 與 `~/.claude/scripts/missing.sh`
- 範例 `~/.claude/skills/foo/SKILL.md`、`~/.claude/sessions/YYYY-MM-DD-x.md`、`~/.claude/memory/_index_`
- glob `~/.claude/skills/*/SKILL.md`、runtime `~/.claude/state/x.json`、`~/.claude/foo-state.json`
- 白名單 `~/.claude/scripts/whitelisted-missing.sh`
EOF
cat > "$ROOT/skills/alpha/SKILL.md" <<'EOF'
[link](~/.claude/scripts/also-missing.md)
EOF

out=$(run)
printf '%s' "$out" | grep -q 'scripts/missing.sh' && ok "known-bad: 缺檔被列出" || ng "known-bad: 缺檔未列出"
printf '%s' "$out" | grep -q 'CLAUDE.md:1' && ok "命中帶 file:line" || ng "命中缺 file:line"
printf '%s' "$out" | grep -q 'exists.sh' && ng "known-good: 存在檔被誤報" || ok "known-good: 存在檔未報"
printf '%s' "$out" | grep -qE 'foo/SKILL|YYYY|_index_`' && ng "佔位符未跳過" || ok "佔位符跳過"
printf '%s' "$out" | grep -qE 'state/x.json|foo-state.json' && ng "runtime 路徑未跳過" || ok "runtime 路徑跳過"
printf '%s' "$out" | grep -q 'whitelisted-missing' && ng "白名單未生效" || ok "白名單生效"
printf '%s' "$out" | grep -q '→ `~/.claude/skills/\*' && ng "glob 未跳過" || ok "glob 跳過"
[ -f "$TMP/out.md" ] && [ ! -L "$TMP/out.md" ] && ok "旁路：只寫 out.md" || ng "旁路：輸出型態異常"

rm -f "$ROOT/CLAUDE.md"; printf '只有 `~/.claude/scripts/exists.sh`\n' > "$ROOT/CLAUDE.md"; : > "$ROOT/skills/alpha/SKILL.md"
out=$(run)
[ "$out" = "__SILENT__" ] && ok "全部存在 → __SILENT__" || ng "全部存在未 __SILENT__（得到: ${out}）"

# --- 跨 coding agent hook 設定與外掛斷頭測試 ---
mkdir -p "$TMP/.gemini/config" "$TMP/.claude" "$TMP/.config/opencode/plugins" "$TMP/.copilot/hooks" "$TMP/.hermes"

cat > "$TMP/.gemini/config/hooks.json" <<'EOF'
{
  "hooks": [
    {
      "command": "if [ -f ~/.orca/agent-hooks/antigravity-hook.sh ]; then ~/.orca/agent-hooks/antigravity-hook.sh --secret-arg=do-not-leak; fi"
    }
  ]
}
EOF

cat > "$TMP/.gemini/settings.json" <<'EOF'
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "node \"$HOME/.petdex/bin/petdex.js\" --token=secret-param"
          }
        ]
      }
    ]
  }
}
EOF

cat > "$TMP/.claude/settings.local.json" <<'EOF'
{
  "permissions": {
    "allow": [
      "Bash(~/.nonexistent-perm-dir/only-in-permissions.sh)"
    ],
    "command": "~/.nonexistent-perm-dir/perm-command.sh"
  },
  "hooks": {}
}
EOF

cat > "$TMP/.config/opencode/plugins/petdex.js" <<'EOF'
// comment should be ignored: "~/.ignored-comment-dir/x"
const dataDir = "~/.petdex/state";
EOF

cat > "$TMP/.copilot/hooks/check.json" <<'EOF'
{
  "preTool": {
    "command": "bash ~/.copilot-missing/hook.sh"
  }
}
EOF

cat > "$TMP/.hermes/config.yaml" <<'EOF'
plugins:
  enabled:
    - orca-status
EOF

mkdir -p "$TMP/.codex/hooks"
cat > "$TMP/.codex/hooks/cc-hooks.json" <<'EOF'
{
  "hooks": [
    {
      "name": "legacy-broken",
      "command": ["bash", "~/.claude/hooks/missing-array-hook.sh"]
    }
  ]
}
EOF

out=$(run)
printf '%s' "$out" | grep -q '~/.gemini/config/hooks.json:' && printf '%s' "$out" | grep -q '~/.orca/agent-hooks/antigravity-hook.sh' && ok "gemini config hooks 缺檔抓出" || ng "gemini config hooks 缺檔未抓出"
printf '%s' "$out" | grep -q 'do-not-leak\|secret-param' && ng "洩漏整條 command 參數" || ok "未洩漏整條 command 參數"
printf '%s' "$out" | grep -q '~/.gemini/settings.json:' && printf '%s' "$out" | grep -q '~/.petdex/bin/petdex.js' && ok "gemini settings \$HOME 缺檔抓出" || ng "gemini settings \$HOME 缺檔缺抓"
printf '%s' "$out" | grep -q 'nonexistent-perm-dir' && ng "誤報 permissions 非 hook 欄位" || ok "permissions 非 hook 欄位未誤報"
printf '%s' "$out" | grep -q '~/.config/opencode/plugins/petdex.js:' && printf '%s' "$out" | grep -q '~/.petdex`' && ok "opencode plugin 缺失 ~/.petdex 抓出" || ng "opencode plugin 缺失 ~/.petdex 未抓出"
printf '%s' "$out" | grep -q 'ignored-comment-dir' && ng "註解內路徑誤報" || ok "註解內路徑未誤報"
printf '%s' "$out" | grep -q '~/.copilot/hooks/check.json:' && printf '%s' "$out" | grep -q '~/.copilot-missing/hook.sh' && ok "copilot hooks 缺檔抓出" || ng "copilot hooks 缺檔未抓出"
printf '%s' "$out" | grep -q '~/.hermes/config.yaml:' && printf '%s' "$out" | grep -q '~/.hermes/plugins/orca-status' && ok "hermes enabled plugin 缺目錄抓出" || ng "hermes enabled plugin 缺目錄未抓出"
printf '%s' "$out" | grep -q '~/.codex/hooks/cc-hooks.json:' && printf '%s' "$out" | grep -q '~/.claude/hooks/missing-array-hook.sh' && ok "codex cc-hooks 陣列 command 缺檔抓出" || ng "codex cc-hooks 陣列 command 缺檔未抓出"

# 補齊檔案後再跑一次，應回到 __SILENT__
mkdir -p "$TMP/.orca/agent-hooks" "$TMP/.petdex/bin" "$TMP/.copilot-missing" "$TMP/.hermes/plugins/orca-status" "$TMP/.claude/hooks"
touch "$TMP/.orca/agent-hooks/antigravity-hook.sh" "$TMP/.petdex/bin/petdex.js" "$TMP/.copilot-missing/hook.sh" "$TMP/.claude/hooks/missing-array-hook.sh"
out=$(run)
[ "$out" = "__SILENT__" ] && ok "補齊跨 agent 檔案後 → __SILENT__" || ng "補齊跨 agent 檔案後未 __SILENT__（得到: ${out}）"

echo "== $pass passed, $fail failed"
[ "$fail" -eq 0 ]
