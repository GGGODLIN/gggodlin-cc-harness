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
check "外來暫存保留該 repo 提交" "先保留該 repo 的提交，繼續處理其他 repo"
check "不碰他人暫存" "不要取消別人的暫存"
check "不用 mtime 推歸屬" "不用檔案 mtime 或工具呼叫時間窗推歸屬"
check "點名 add" "git -C <repo> add -- <白名單每個路徑>"
check "提交前核對暫存區" "git -C <repo> diff --cached --name-only"
check "只用普通 commit" 'git -C <repo> commit -m "<訊息>"'
check "暫存區必須等於白名單" "只有暫存區路徑與本顆白名單完全相等時才 commit"
if grep -qE -- 'commit --only|commit -m.*-- <白名單' "$COMMAND"; then
  FAIL=$((FAIL + 1)); printf '  FAIL 不得回到 gate 拒絕的提交寫法\n'
else
  PASS=$((PASS + 1)); printf '  ok   未使用 --only 或 pathspec commit\n'
fi
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
check "非 fresh 空狀態不寫乾淨" "除非 fresh \`git status\` 為空"
check "收尾前先回看記憶" "0. **記憶回看**"
check "記憶回看只看上次 self-closeout 之後" "上一次 self-closeout 回報之後"
check "記憶回看先找既有檔再新建" "主題相同就併進去，沒有才新建"
check "記憶回看接回第 1 步" "完成後接第 1 步"
check "回報有記憶欄" "記憶：新增 N、併入 M"
check "記憶欄不跳過" "「記憶」不論哪種格式都要寫"
check "記憶回看接到文件落差登記" "完成後接第 0b 步"
check "文件落差登記是編號步驟" "0b. **文件落差登記**"
check "文件落差不寫進 memory" "也不寫進 memory，交給第 0b 步"
check "文件落差寫進摩擦掃描範圍" "~/.claude/friction/doc-drift.md"
check "文件落差欄位照協議格式" "target=rule:<文件絕對路徑>"
check "回報有文件落差欄" "文件落差：新增 N"
check "文件落差欄不跳過" "「文件落差」同樣不跳過"
check "第 2 步只讀摘要" "closeout-provenance.py --repo <repo> --plan"
check "共用 checkpoint 用白名單檔 add" "add --pathspec-from-file=<shared.pathspec_file>"
check "共用 checkpoint 只看差異核對" "diff --cached --name-only | diff - <shared.pathspec_file>"
check "正常回報一行" "沒有異常時整份回報只有一行"
check "未收只給數字" "未收只寫數字、不列路徑"
check "外來暫存是異常" "\`staged_foreign\` 非空，該 repo 的提交被擋下"
check "停在非 trunk 是異常" "personal repo 的 \`branch\` 不是 trunk"
check "自己的檔沒收進來是異常" "本 session 的檔沒進 commit"
check "並行搶先收走時分開標示且未收取自 unclaimed" "已由並行 session 收走"

if [[ -x "$SCRIPT" ]] && python3 "$SCRIPT" --help >/dev/null 2>&1; then
  PASS=$((PASS + 1)); printf '  ok   provenance script 可執行\n'
else
  FAIL=$((FAIL + 1)); printf '  FAIL provenance script 可執行\n'
fi

FIXTURE=$(mktemp -d "${TMPDIR:-/tmp}/self-closeout-fixture.XXXXXX")
EMPTY_PROJECTS="$FIXTURE.empty-projects"
CODEX_TMP="$FIXTURE.codex"
mkdir -p "$EMPTY_PROJECTS" "$CODEX_TMP"

SELF_REPOS=$(CLOSEOUT_PROJECTS_DIR="$EMPTY_PROJECTS" CLOSEOUT_CODEX_SESSIONS="$CODEX_TMP" CLAUDE_CODE_SESSION_ID=contract-test-no-such-session python3 "$SCRIPT" --self-repos 2>/dev/null || true)
if printf '%s\n' "$SELF_REPOS" | grep -qx "$HOME/.claude" && printf '%s\n' "$SELF_REPOS" | grep -qx "$HOME/Desktop/projects/.claude"; then
  PASS=$((PASS + 1)); printf '  ok   --self-repos 永遠含固定共用 repo\n'
else
  FAIL=$((FAIL + 1)); printf '  FAIL --self-repos 永遠含固定共用 repo\n'
fi

# 行為測試：shared／vendor_managed／staged_differs 三個欄位要對真實 git 狀態判對
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
JSON=$(CLOSEOUT_PROJECTS_DIR="$EMPTY_PROJECTS" CLOSEOUT_CODEX_SESSIONS="$CODEX_TMP" CLOSEOUT_SHARED_REPOS="$FIXTURE" python3 "$SCRIPT" --repo "$FIXTURE" --json 2>/dev/null || echo '{}')
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
JSON_PLAIN=$(CLOSEOUT_PROJECTS_DIR="$EMPTY_PROJECTS" CLOSEOUT_CODEX_SESSIONS="$CODEX_TMP" CLOSEOUT_SHARED_REPOS="$ROOT" python3 "$SCRIPT" --repo "$FIXTURE" --json 2>/dev/null || echo '{}')
if printf '%s' "$JSON_PLAIN" | python3 -c '
import json,sys
r=json.load(sys.stdin); rows={d["path"]:d for d in r.get("dirty",[])}
sys.exit(0 if not rows["memory/MEMORY.md"]["shared"] else 1)
'; then
  PASS=$((PASS + 1)); printf '  ok   非共用 repo 的 memory/ 不算 shared\n'
else
  FAIL=$((FAIL + 1)); printf '  FAIL 非共用 repo 的 memory/ 不算 shared\n'
fi

# 行為測試：--plan 只印摘要，共用白名單落檔、未收只給數字
PLAN_DIR="$FIXTURE.plan"
PLAN=$(CLOSEOUT_PROJECTS_DIR="$EMPTY_PROJECTS" CLOSEOUT_CODEX_SESSIONS="$CODEX_TMP" CLOSEOUT_SHARED_REPOS="$FIXTURE" python3 "$SCRIPT" --repo "$FIXTURE" --session contract-test-no-such-session --plan "$PLAN_DIR" 2>/dev/null || echo '{}')
if printf '%s' "$PLAN" | python3 -c '
import json,sys
p=json.load(sys.stdin)
ok = p["shared"]["count"] == 1 and open(p["shared"]["pathspec_file"]).read() == "memory/MEMORY.md\n"
ok = ok and p["held_staged_differs"] == ["plain.txt"] and p["held_vendor_managed"] == 1
ok = ok and p["has_origin"] is False and p["has_upstream"] is False
ok = ok and p["unclaimed"] == 0 and "dirty" not in p and json.load(open(p["detail"]))["dirty"]
sys.exit(0 if ok else 1)
'; then
  PASS=$((PASS + 1)); printf '  ok   --plan 摘要分欄、共用白名單落檔與 has_origin/has_upstream\n'
else
  FAIL=$((FAIL + 1)); printf '  FAIL --plan 摘要分欄、共用白名單落檔與 has_origin/has_upstream\n'
fi

# 行為測試：codex_touched 略過全程 read-only 沙箱 rollout，但保留非 read-only 或含寫檔工具之 rollout
printf 'x\n' > "$FIXTURE/ro-target.txt"
printf 'y\n' > "$FIXTURE/rw-target.txt"
RO_PATH=$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$FIXTURE/ro-target.txt")
RW_PATH=$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$FIXTURE/rw-target.txt")
cat > "$CODEX_TMP/rollout-ro.jsonl" <<EOF
{"type":"turn_context","payload":{"sandbox_policy":{"type":"read-only"}}}
{"type":"response_item","payload":{"type":"function_call","name":"exec","arguments":"cat $RO_PATH"}}
EOF
cat > "$CODEX_TMP/rollout-rw.jsonl" <<EOF
{"type":"turn_context","payload":{"sandbox_policy":{"type":"workspace-write"}}}
{"type":"response_item","payload":{"type":"function_call","name":"exec","arguments":"cat $RW_PATH"}}
EOF
JSON_CODEX=$(CLOSEOUT_PROJECTS_DIR="$EMPTY_PROJECTS" CLOSEOUT_CODEX_SESSIONS="$CODEX_TMP" CLOSEOUT_SHARED_REPOS="$ROOT" python3 "$SCRIPT" --repo "$FIXTURE" --json 2>/dev/null || echo '{}')
if printf '%s' "$JSON_CODEX" | python3 -c '
import json,sys
r=json.load(sys.stdin); rows={d["path"]:d for d in r.get("dirty",[])}
ok = rows["ro-target.txt"]["codex_touched"] is False and rows["rw-target.txt"]["codex_touched"] is True
sys.exit(0 if ok else 1)
'; then
  PASS=$((PASS + 1)); printf '  ok   codex_touched 排除純 read-only rollout 並保留非 read-only rollout\n'
else
  FAIL=$((FAIL + 1)); printf '  FAIL codex_touched 排除純 read-only rollout 並保留非 read-only rollout\n'
fi

# 行為測試：cd <repo> && ... --out <relpath> 可認領為 self_bash_only，且 rg -o 不誤認成寫入者
PROJ_TMP="$FIXTURE.projects/test-proj"
mkdir -p "$PROJ_TMP" "$FIXTURE/sub"
printf 'generated\n' > "$FIXTURE/sub/out.json"
printf 'unclaimed\n' > "$FIXTURE/sub/rg-only.json"
REAL_FIXTURE=$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$FIXTURE")
cat > "$PROJ_TMP/sess-self.jsonl" <<EOF
{"timestamp":"2099-01-01T00:00:00Z","message":{"content":[{"type":"tool_use","name":"Bash","input":{"command":"cd $REAL_FIXTURE && python3 gen.py --out sub/out.json"}}]}}
EOF
cat > "$PROJ_TMP/sess-other.jsonl" <<EOF
{"timestamp":"2099-01-01T00:00:00Z","message":{"content":[{"type":"tool_use","name":"Bash","input":{"command":"cd $REAL_FIXTURE && rg -o sub/rg-only.json README.md > /tmp/unrelated.txt"}}]}}
EOF
JSON_OUT=$(CLOSEOUT_PROJECTS_DIR="$FIXTURE.projects" CLOSEOUT_CODEX_SESSIONS="$CODEX_TMP" CLOSEOUT_SHARED_REPOS="$ROOT" python3 "$SCRIPT" --repo "$FIXTURE" --session sess-self --json 2>/dev/null || echo '{}')
if printf '%s' "$JSON_OUT" | python3 -c '
import json,sys
r=json.load(sys.stdin); rows={d["path"]:d for d in r.get("dirty",[])}
ok = rows["sub/out.json"]["self_bash_only"] is True and rows["sub/out.json"]["co_written"] is False
ok = ok and rows["sub/rg-only.json"]["candidates"] == []
sys.exit(0 if ok else 1)
'; then
  PASS=$((PASS + 1)); printf '  ok   cd <repo> && --out <relpath> 正確認領且 rg -o 不誤判為寫入者\n'
else
  FAIL=$((FAIL + 1)); printf '  FAIL cd <repo> && --out <relpath> 正確認領且 rg -o 不誤判為寫入者\n'
fi
rm -rf "$EMPTY_PROJECTS"
rm -rf "$FIXTURE.projects"
rm -rf "$CODEX_TMP"
rm -rf "$PLAN_DIR"
rm -rf "$FIXTURE"

printf '\n%s PASS / %s FAIL\n' "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]]
