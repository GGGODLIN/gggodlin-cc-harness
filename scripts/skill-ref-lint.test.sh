#!/usr/bin/env bash
# skill-ref-lint.test.sh — 三件 fixture 回歸（gate-authoring checklist §3）
set -u
LINT="$HOME/.claude/scripts/skill-ref-lint.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0

cat > "$TMP/fixture.md" <<'EOF'
known-good：引用存在的路徑 ~/.claude/hooks/skill-install-scan.sh 應通過。
known-bad：引用不存在的 ~/.claude/scripts/zzz-deleted-tool.sh 應被抓。
邊界 placeholder：~/Desktop/projects/<kebab-case-name>/README.md 應跳過。
邊界 glob：~/.claude/skills/*/SKILL.md 應跳過。
EOF

out=$(bash "$LINT" "$TMP")

if ! grep -q "skill-install-scan.sh" <<<"$out"; then
  echo "PASS known-good（存在路徑未被誤報）"; ((pass++))
else echo "FAIL known-good：存在路徑被誤報"; ((fail++)); fi

if grep -q "zzz-deleted-tool.sh" <<<"$out"; then
  echo "PASS known-bad（缺失路徑被抓到）"; ((pass++))
else echo "FAIL known-bad：缺失路徑漏報"; ((fail++)); fi

if ! grep -qE "kebab-case-name|SKILL.md 應跳過" <<<"$out" && ! grep -q '\*' <<<"$out"; then
  echo "PASS boundary（placeholder / glob 跳過）"; ((pass++))
else echo "FAIL boundary：placeholder 或 glob 被誤報。output: $out"; ((fail++)); fi

echo "---- $pass pass / $fail fail ----"
exit $fail
