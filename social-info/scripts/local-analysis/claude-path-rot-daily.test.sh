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

echo "== $pass passed, $fail failed"
[ "$fail" -eq 0 ]
