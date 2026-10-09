#!/bin/bash
# skill-verify-adoption-review.sh — skill-compliance verify trial 採用率統計
# 用法: skill-verify-adoption-review.sh [起始日 YYYY-MM-DD] [skill 名...]
# 不給 skill 名 → 預設跑 trial 三組對照
# 分母 = Skill tool invoke 數；分子 = 帶 marker 的 Agent dispatch 數
# 全 jsonl 只掃一遍（5.8GB 掃兩遍/skill 會超時）
set -euo pipefail

SINCE="${1:-2026-07-02}"
shift 2>/dev/null || true
SKILLS=("$@")
[ ${#SKILLS[@]} -eq 0 ] && SKILLS=(bitbucket-pr-review save-session github-repo-research)
PROJ="$HOME/.claude/projects"

PAT=$(IFS='|'; echo "${SKILLS[*]}")
TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT
grep -rhE "\"skill\":\"(${PAT})\"|skill-verify:(${PAT})" "$PROJ" 2>/dev/null > "$TMP" || true

dates_since() {
  awk -v since="$SINCE" 'match($0, /"timestamp":"[0-9]{4}-[0-9]{2}-[0-9]{2}/) {
    d = substr($0, RSTART + 13, 10)
    if (d >= since) print d
  }'
}

echo "=== skill-verify adoption review (since $SINCE) ==="
echo "決策門檻: >80% 留 SKILL.md-only / 50-80% 加 hook fallback / <50% 改硬機制"
for s in "${SKILLS[@]}"; do
  invoke_dates=$(grep '"name":"Skill"' "$TMP" | grep "\"skill\":\"${s}\"" | dates_since | sort) || true
  verify_dates=$(grep '"name":"Agent"' "$TMP" | grep "skill-verify:${s}" | dates_since | sort) || true
  invokes=$(printf '%s' "$invoke_dates" | grep -c . || true)
  verifies=$(printf '%s' "$verify_dates" | grep -c . || true)
  if [ "$invokes" -gt 0 ]; then
    rate="$(awk -v v="$verifies" -v i="$invokes" 'BEGIN { printf "%.0f", v / i * 100 }')%"
  else
    rate="n/a（0 invoke）"
  fi
  echo ""
  echo "--- $s ---"
  echo "invokes: $invokes | verifies: $verifies | adoption: $rate"
  echo "invoke dates:"
  [ -n "$invoke_dates" ] && printf '%s\n' "$invoke_dates" | uniq -c || echo "  (none)"
  echo "verify dates:"
  [ -n "$verify_dates" ] && printf '%s\n' "$verify_dates" | uniq -c || echo "  (none)"
done
