#!/usr/bin/env bash
# skill-install-scan.test.sh — 三件 fixture 回歸（gate-authoring checklist §3）
# 用法：bash ~/.claude/hooks/skill-install-scan.test.sh
# 改 skill-install-scan.sh 後必重跑。
set -u
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
HOOK="$SCRIPT_DIR/skill-install-scan.sh"
FIXTURE=$(mktemp -d) || exit 1
trap 'rm -rf "$FIXTURE"' EXIT
export HOME="$FIXTURE/home"
USER_EMAIL="you@example.com"
pass=0; fail=0

run_hook() {
  printf '{"tool_input":{"file_path":"%s"}}' "$1" | bash "$HOOK"
}

# 1. known-good：tracked + 自家 author → 靜默 skip
GOOD_FILE="$HOME/.claude/skills/fixture/SKILL.md"
mkdir -p "$(dirname "$GOOD_FILE")" || exit 1
printf '# Fixture\n' > "$GOOD_FILE" || exit 1
git -C "$HOME/.claude" init -q || exit 1
git -C "$HOME/.claude" add -- "$GOOD_FILE" || exit 1
git -C "$HOME/.claude" -c user.name=Fixture -c user.email="$USER_EMAIL" commit -qm fixture || exit 1

out=$(run_hook "$GOOD_FILE")
if [[ -z "$out" ]]; then echo "PASS known-good ($GOOD_FILE → silent)"; ((pass++))
else echo "FAIL known-good：自家 tracked 檔誤觸發"; ((fail++)); fi

# 2. known-bad：untracked skills/ 路徑 → 觸發且含第 (4) 類導流特徵
out=$(run_hook "$HOME/.claude/skills/zzz-fixture-nonexistent/SKILL.md")
if echo "$out" | jq -e '.hookSpecificOutput.additionalContext' >/dev/null 2>&1 \
   && echo "$out" | grep -q "導流或遙測"; then
  echo "PASS known-bad（觸發 + JSON 合法 + 含第 4 類）"; ((pass++))
else
  echo "FAIL known-bad：未觸發 / JSON 壞 / 缺第 4 類。output: $out"; ((fail++))
fi

# 3. 邊界：skills/commands 之外的路徑 → 靜默 skip
out=$(run_hook "$HOME/Desktop/projects/whatever.md")
if [[ -z "$out" ]]; then echo "PASS boundary（目錄外 silent）"; ((pass++))
else echo "FAIL boundary：目錄外誤觸發"; ((fail++)); fi

echo "---- $pass pass / $fail fail ----"
exit $fail
