#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
COMMAND="$ROOT/commands/self-closeout.md"
SCRIPT="$ROOT/scripts/closeout-provenance.py"
PASS=0
FAIL=0

check() {
  local name="$1"
  local expected="$2"
  if [[ -f "$COMMAND" ]] && grep -qF -- "$expected" "$COMMAND"; then
    PASS=$((PASS + 1))
    printf '  ok   %s\n' "$name"
  else
    FAIL=$((FAIL + 1))
    printf '  FAIL %s\n' "$name"
  fi
}

check "標示契約測試跑法" "self-closeout-contract.test.sh"
check "模型可自行呼叫（無 disable-model-invocation）" "argument-hint"
if grep -qF -- "disable-model-invocation: true" "$COMMAND"; then
  FAIL=$((FAIL + 1)); printf '  FAIL 不得設 disable-model-invocation\n'
else
  PASS=$((PASS + 1)); printf '  ok   不得設 disable-model-invocation\n'
fi
check "範圍由 script 決定不是 cwd" "closeout-provenance.py --self-repos"
check "一般檔案歸屬由 provenance 判" "self_owned: true"
check "Bash 低信心候選要指得出那次改檔" "self_bash_only: true"
check "寫入需晚於最後 commit" "寫入時間晚於該檔最後一次 commit"
check "固定共用 repo 一定在清單" "兩個固定共用 repo"
check "共用集合不看作者" "co_written\`、\`codex_touched\`、寫入工具種類不再構成拒收理由"
check "共用集合列出五類" "references/failure-mode-taxonomy.md"
check "vendor 產物保留不收" "skills/.trash/"
check "同檔暫存與工作樹不同版就保留" "staged_differs: true"
check "staged_foreign 不再停整個 repo" "不再讓整個 repo 停下"
check "不用 mtime 推歸屬" "不用檔案 mtime 或工具呼叫時間窗推歸屬"
check "點名 add" "git -C <repo> add -- <白名單每個路徑>"
check "限定路徑 commit" "git -C <repo> commit --only -m"
check "commit 後核對內容" "git -C <repo> show --stat --format= HEAD"
check "共用 checkpoint 固定訊息" "chore(closeout): checkpoint shared ledgers"
check "禁用整包 add" "禁用 \`git add -A\`、\`git add .\`、\`git commit -a\`"
check "push 前列出發布範圍" "origin/<trunk>..<trunk>"
check "個人 trunk 照常 push 並點名別人的 commit" "含 N 顆非本 session 的 commit"
check "push 被拒走 merge 不 rebase" "不 rebase、不 force"
check "push 與收 dirty 分開判" "push 與收 dirty 分開判"
check "work scope 不寫入部署分支" "不在 \`stage\`／\`main\`／\`master\` 產生 commit"
check "別人的 worktree 不碰" "別人的 worktree 不碰"
check "不發 SendMessage" "不對其他 session 發 SendMessage"
check "DONE verdict" "Self closeout：<DONE 或 BLOCKED>"
check "已推欄" "已推："
check "保留欄" "保留："
check "未收欄" "未收："
check "保留非零不寫乾淨" "仍有 N 檔保留／未收"

if [[ -x "$SCRIPT" ]] && python3 "$SCRIPT" --help >/dev/null 2>&1; then
  PASS=$((PASS + 1)); printf '  ok   provenance script 可執行\n'
else
  FAIL=$((FAIL + 1)); printf '  FAIL provenance script 可執行\n'
fi

SELF_REPOS=$(CLAUDE_CODE_SESSION_ID=contract-test-no-such-session python3 "$SCRIPT" --self-repos 2>/dev/null || true)
if printf '%s\n' "$SELF_REPOS" | grep -qx "$ROOT"; then
  PASS=$((PASS + 1)); printf '  ok   --self-repos 永遠含固定共用 repo\n'
else
  FAIL=$((FAIL + 1)); printf '  FAIL --self-repos 永遠含固定共用 repo\n'
fi

# 行為測試：shared／vendor_managed／staged_differs 三個欄位要對真實 git 狀態判對
FIXTURE=$(mktemp -d "${TMPDIR:-/tmp}/self-closeout-fixture.XXXXXX")
git -C "$FIXTURE" init -q
mkdir -p "$FIXTURE/memory" "$FIXTURE/skills/.trash/x"
printf 'a\n' > "$FIXTURE/memory/MEMORY.md"
printf 'v\n' > "$FIXTURE/skills/.trash/x/SKILL.md"
printf 'base\n' > "$FIXTURE/plain.txt"
git -C "$FIXTURE" add plain.txt
git -C "$FIXTURE" -c user.email=t@t -c user.name=t commit -q -m base
printf 'staged\n' > "$FIXTURE/plain.txt"
git -C "$FIXTURE" add plain.txt
printf 'worktree\n' > "$FIXTURE/plain.txt"
JSON=$(CLOSEOUT_SHARED_REPOS="$FIXTURE" python3 "$SCRIPT" --repo "$FIXTURE" --json 2>/dev/null || echo '{}')
if printf '%s' "$JSON" | python3 -c '
import json,sys
r=json.load(sys.stdin); rows={d["path"]:d for d in r.get("dirty",[])}
ok = rows["memory/MEMORY.md"]["shared"] and not rows["memory/MEMORY.md"]["vendor_managed"]
ok = ok and rows["skills/.trash/x/SKILL.md"]["vendor_managed"]
ok = ok and rows["plain.txt"]["staged_differs"] and not rows["plain.txt"]["shared"]
sys.exit(0 if ok else 1)
'; then
  PASS=$((PASS + 1)); printf '  ok   --json 標 shared／vendor_managed／staged_differs\n'
else
  FAIL=$((FAIL + 1)); printf '  FAIL --json 標 shared／vendor_managed／staged_differs\n'
fi

# 回歸：普通專案 repo 有同名 memory/ 資料夾，不得被當成共用帳本（2026-10-09 REFACTOR 題）
JSON_PLAIN=$(CLOSEOUT_SHARED_REPOS="$ROOT" python3 "$SCRIPT" --repo "$FIXTURE" --json 2>/dev/null || echo '{}')
if printf '%s' "$JSON_PLAIN" | python3 -c '
import json,sys
r=json.load(sys.stdin); rows={d["path"]:d for d in r.get("dirty",[])}
sys.exit(0 if not rows["memory/MEMORY.md"]["shared"] else 1)
'; then
  PASS=$((PASS + 1)); printf '  ok   非共用 repo 的 memory/ 不算 shared\n'
else
  FAIL=$((FAIL + 1)); printf '  FAIL 非共用 repo 的 memory/ 不算 shared\n'
fi
rm -rf "$FIXTURE"

printf '\n%s PASS / %s FAIL\n' "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]]
