#!/usr/bin/env bash
# sem-plan-blast-radius.sh 的 smoke test。用法: sem-plan-blast-radius.test.sh [repo]
# 未指定 repo 時自動建立隔離臨時 TypeScript git fixture（不再依賴已退役的 oldco-shop）。
# 測 local tasks、非目標路徑與 graceful skip。臨時檔測完即刪（trap cleanup）。
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK="$SCRIPT_DIR/sem-plan-blast-radius.sh"
FIXTURE="utils/requireToken.ts"

fail(){ printf 'FAIL: %s\n' "$1"; exit 1; }
command -v sem >/dev/null 2>&1 || { printf 'sem 未裝，skip\n'; exit 0; }
[ -f "$HOOK" ] || fail "hook 不存在: $HOOK"

temp_repo_root=""
if [ -n "${1:-}" ]; then
  REPO="$1"
else
  temp_repo_root=$(mktemp -d) || fail "無法建立臨時 git repo"
  REPO="$temp_repo_root/repo"
  export SEM_CACHE_DIR="$temp_repo_root/.sem-cache"
  mkdir -p "$REPO/utils" "$REPO/handlers"
  cat > "$REPO/utils/requireToken.ts" <<'EOF'
export function requireToken(header: string | undefined): string {
  if (!header) {
    throw new Error("missing token");
  }
  return header.trim();
}
EOF
  cat > "$REPO/handlers/login.ts" <<'EOF'
import { requireToken } from "../utils/requireToken";

export function handleLogin(auth?: string): string {
  return requireToken(auth);
}
EOF
  git -C "$REPO" init -q || fail "git init 失敗"
  git -C "$REPO" config user.email "test@example.invalid"
  git -C "$REPO" config user.name "Sem Smoke Test"
  git -C "$REPO" add . || fail "git add 失敗"
  git -C "$REPO" commit -qm "test: seed sem fixture" || fail "git commit 失敗"
fi

git -C "$REPO" rev-parse >/dev/null 2>&1 || fail "repo 非 git: $REPO"
[ -f "$REPO/$FIXTURE" ] || fail "fixture 不存在，請改 FIXTURE 指向一個有 dependents 的檔: $REPO/$FIXTURE"

changes_root="$REPO/openspec/changes"
mkdir -p "$changes_root"
plandir=$(mktemp -d "$changes_root/.sem-smoketest.XXXXXX") || fail "無法建立 local tasks fixture"
plan="$plandir/tasks.md"
nongit_root=$(mktemp -d) || fail "無法建立 non-git fixture"
nongit_plan="$nongit_root/openspec/changes/example/tasks.md"
mkdir -p "$(dirname "$nongit_plan")"
cleanup(){
  rm -f "$plan" "$nongit_plan"
  rmdir "$plandir" 2>/dev/null
  rmdir "$changes_root" 2>/dev/null
  rmdir "$REPO/openspec" 2>/dev/null
  rmdir "$(dirname "$nongit_plan")" "$nongit_root/openspec/changes" "$nongit_root/openspec" "$nongit_root" 2>/dev/null
  [ -n "$temp_repo_root" ] && rm -rf "$temp_repo_root"
}
trap cleanup EXIT

printf '# Smoke\n\n**Files:**\n- Modify: `%s`\n- Create: `x/new.ts`\n' "$FIXTURE" > "$plan"
out=$(jq -nc --arg path "$plan" '{tool_input:{file_path:$path}}' | "$HOOK")
printf '%s' "$out" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null || fail "輸出非合法 JSON: $out"
printf '%s' "$out" | grep -q "blast radius" || fail "輸出缺 'blast radius': $out"
printf '%s' "$out" | grep -q "dependents" || fail "輸出缺 'dependents': $out"
printf 'PASS 1 local openspec tasks：合法 JSON 含 blast radius + dependents\n'

out2=$(jq -nc --arg path "$REPO/README.md" '{tool_input:{file_path:$path}}' | "$HOOK")
[ -z "$out2" ] || fail "非目標路徑應無輸出，卻有: $out2"
printf 'PASS 2 unrelated path：無輸出\n'

legacy_path="$REPO/docs/superpowers/plans/_sem_smoketest.md"
out3=$(jq -nc --arg path "$legacy_path" '{tool_input:{file_path:$path}}' | "$HOOK")
[ -z "$out3" ] || fail "legacy docs/superpowers path 應無輸出，卻有: $out3"
printf 'PASS 3 legacy boundary：無輸出\n'

scratch_ticket="$REPO/.scratch/sem-smoketest/issues/001.md"
out4=$(jq -nc --arg path "$scratch_ticket" '{tool_input:{file_path:$path}}' | "$HOOK")
[ -z "$out4" ] || fail "scratch ticket path 應無輸出，卻有: $out4"
printf 'PASS 4 scratch ticket path：無輸出\n'

printf '# Only new\n- Create: `x/new.ts`\n' > "$plan"
out5=$(jq -nc --arg path "$plan" '{tool_input:{file_path:$path}}' | "$HOOK")
[ -z "$out5" ] || fail "全新檔 tasks 應無輸出，卻有: $out5"
printf 'PASS 5 no Modify entries：無輸出\n'

printf '# Non-git\n\n**Files:**\n- Modify: `%s`\n' "$FIXTURE" > "$nongit_plan"
out6=$(jq -nc --arg path "$nongit_plan" '{tool_input:{file_path:$path}}' | "$HOOK")
[ -z "$out6" ] || fail "非 git tasks 應無輸出，卻有: $out6"
printf 'PASS 6 non-git graceful skip：無輸出\n'

printf 'RESULT 6/6\n'
