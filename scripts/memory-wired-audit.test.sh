#!/usr/bin/env bash
set -u

SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/memory-wired-audit.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
pass=0
fail=0

new_fixture() {
  local root="$TMP/$1"
  mkdir -p "$root/memory" "$root/hooks" "$root/commands" "$root/skills" "$root/scripts" "$root/bin"
  printf '{"hooks":{}}\n' > "$root/settings.json"
  printf '%s\n' "$root"
}

run_audit() {
  local root="$1"
  # launchd 與 zshrc 來源預設讀真實家目錄，fixture 要指到不存在的路徑才不會把本機接線漏進測試（2026-10-16 dcg 案例因 ~/.zshrc 提到 dcg 而翻 OK）
  WIRED_ROOT="$root" WIRED_BIN_DIR="$root/bin" WIRED_LAUNCHD_DIR="$root/launchd" WIRED_ZSHRC="$root/zshrc" bash "$SCRIPT" > "$root/out" 2> "$root/err"
  printf '%s\n' "$?" > "$root/rc"
}

make_tool() {
  printf '#!/bin/sh\n' > "$1"
  chmod +x "$1"
}

check() {
  local name="$1" root="$2" expected_out="$3" expected_rc="$4"
  local actual_out actual_rc
  actual_out=$(<"$root/out")
  actual_rc=$(<"$root/rc")
  if [ "$actual_out" = "$expected_out" ] && [ "$actual_rc" = "$expected_rc" ]; then
    echo "PASS $name"
    ((pass++))
  else
    echo "FAIL $name: rc=$actual_rc out=[$actual_out] err=[$(head -c 300 "$root/err")]"
    ((fail++))
  fi
}

# 1. hook 存在但 settings 與其他 hook 都沒提到
r=$(new_fixture unwired-hook)
printf '#!/bin/bash\necho lonely\n' > "$r/hooks/lonely.sh"
printf '#!/bin/bash\necho other\n' > "$r/hooks/other.sh"
printf '{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"bash ~/.claude/hooks/other.sh"}]}]}}\n' > "$r/settings.json"
printf '# note\n看 `~/.claude/hooks/lonely.sh` 會怎樣\n' > "$r/memory/a.md"
run_audit "$r"
check "unwired hook yields exactly one UNWIRED line" "$r" "UNWIRED hooks/lonely.sh ← a.md:2" 0

# 2. local-bin 工具存在但沒有任何來源提到它或它的 wrapper
r=$(new_fixture unwired-tool)
make_tool "$r/bin/zeta-tool"
printf '要查就跑 zeta-tool 看輸出\n' > "$r/memory/tool.md"
run_audit "$r"
check "unwired local-bin tool yields one UNWIRED line" "$r" "UNWIRED zeta-tool ← tool.md:1" 0

# 3. dcg 事故重放：binary 在、wrapper 從 settings hooks 拆線、記憶還寫著要過 dcg
r=$(new_fixture dcg-replay)
make_tool "$r/bin/dcg"
printf '#!/bin/bash\nexec dcg "$@"\n' > "$r/scripts/dcg-wrapper.sh"
printf '#!/bin/bash\necho guard\n' > "$r/hooks/guard.sh"
printf '{"hooks":{"PreToolUse":[{"matcher":"Bash","hooks":[{"type":"command","command":"bash ~/.claude/hooks/guard.sh"}]}]}}\n' > "$r/settings.json"
printf '# 刪檔紀律\n\n刪檔要過 dcg allow-once\n' > "$r/memory/feedback_rm.md"
run_audit "$r"
check "dcg replay yields UNWIRED" "$r" "UNWIRED dcg ← feedback_rm.md:3" 0

# 4. 不存在 → MISSING；有接線 → OK（hook 由 settings、script 由 command、tool 由 skill）
r=$(new_fixture missing-ok)
printf '#!/bin/bash\n' > "$r/hooks/wired.sh"
printf '#!/usr/bin/env python3\n' > "$r/scripts/used.py"
make_tool "$r/bin/skilltool"
printf '{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"bash ~/.claude/hooks/wired.sh"}]}]}}\n' > "$r/settings.json"
printf 'run `python3 ~/.claude/scripts/used.py`\n' > "$r/commands/cmd.md"
mkdir -p "$r/skills/demo"
printf 'Use skilltool here.\n' > "$r/skills/demo/SKILL.md"
cat > "$r/memory/m.md" <<'EOF'
舊的 `~/.claude/hooks/gone.sh` 還在嗎
現行 ~/.claude/hooks/wired.sh
跑 ~/.claude/scripts/used.py 產報表
用 skilltool 做事
呼叫 ~/.local/bin/nope-tool
EOF
run_audit "$r"
check "missing refs yield MISSING, wired refs yield OK" "$r" "$(printf '%s\n' \
  'MISSING hooks/gone.sh ← m.md:1' \
  'OK hooks/wired.sh ← m.md:2' \
  'OK scripts/used.py ← m.md:3' \
  'OK skilltool ← m.md:4' \
  'MISSING nope-tool ← m.md:5')" 0

# 5. test 檔、placeholder、SELF_NOTE 都不出行
r=$(new_fixture exclusions)
printf '#!/bin/bash\n' > "$r/hooks/T2-routing-gate.test.sh"
printf '#!/bin/bash\n' > "$r/hooks/retired.sh"
make_tool "$r/bin/q"
cat > "$r/memory/ex.md" <<'EOF'
測試在 ~/.claude/hooks/T2-routing-gate.test.sh
範例 hooks/X.sh 與 ~/.claude/scripts/x.py
省略 ~/.claude/hooks/....sh 與 ~/.local/bin/...
角括號 hooks/<name>.sh
單字母 q 不是工具
`~/.claude/hooks/old-gate.sh` 已於 09-01 刪除
舊 `hooks/retired.sh` 已退役，不再掛
EOF
run_audit "$r"
check "test files, placeholders, SELF_NOTE yield no line" "$r" "" 0

# 6. F2：glob、反引號、行尾截斷不炸、不出假 MISSING
r=$(new_fixture f2)
printf '#!/bin/bash\n' > "$r/hooks/glob-a.sh"
printf '{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"bash ~/.claude/hooks/glob-a.sh"}]}]}}\n' > "$r/settings.json"
cat > "$r/memory/f2.md" <<'EOF'
一族 `~/.claude/hooks/glob-*.sh` 與 ~/.claude/hooks/glob-?.sh
怪 `hooks/`weird`.sh` 反引號
截斷在行尾 ~/.claude/hooks/trunc-
另一種截斷 ~/.claude/scripts/half
工具路徑截斷 ~/.local/bin/
EOF
run_audit "$r"
check "F2 glob/backtick/truncation: no crash, no false MISSING, glob refs not classified" "$r" "" 0

# 7. F6：空 memory dir；settings 沒有 hooks 段
r=$(new_fixture f6-empty)
run_audit "$r"
check "F6 empty memory dir: no lines, exit 0" "$r" "" 0

r=$(new_fixture f6-nohooks)
printf '{"permissions":{"allow":[]}}\n' > "$r/settings.json"
printf '這條只是文字，沒有引用\n' > "$r/memory/plain.md"
run_audit "$r"
check "F6 settings without hooks section: no lines, exit 0" "$r" "" 0

r=$(new_fixture f6-nohooks-ref)
printf '{"permissions":{"allow":[]}}\n' > "$r/settings.json"
printf '#!/bin/bash\n' > "$r/hooks/callee.sh"
printf '#!/bin/bash\nbash "$HOME/.claude/hooks/callee.sh"\n' > "$r/hooks/caller.sh"
printf 'callee 由 hooks/callee.sh 提供\n' > "$r/memory/c.md"
run_audit "$r"
check "F6 settings without hooks section still judges wiring from other sources" "$r" "OK hooks/callee.sh ← c.md:1" 0

# 7b. review 補：.py hook 也要抽；symlink 的 skill 目錄算接線來源；更正行整行是歷史敘述
r=$(new_fixture review-fixes)
printf 'print(1)\n' > "$r/hooks/lonely-gate.py"
printf '#!/bin/bash\n' > "$r/hooks/old-guard.sh"
printf '#!/bin/bash\n' > "$r/hooks/linked.sh"
mkdir -p "$r/real-skill"; printf '用 `~/.claude/hooks/linked.sh`\n' > "$r/real-skill/SKILL.md"
ln -s "$r/real-skill" "$r/skills/linked-skill"
printf '{"hooks":{}}\n' > "$r/settings.json"
printf 'a `~/.claude/hooks/lonely-gate.py` b\n`~/.claude/hooks/gone-gate.py`\n看 `~/.claude/hooks/linked.sh`\n' > "$r/memory/py.md"
printf '> 更正行 2026-09-25：撤下「刪檔要過 hooks/old-guard.sh」；現況來源：settings.json\n' > "$r/memory/fixed.md"
run_audit "$r"
check "review: .py hook, symlink skill source, correction line excluded" "$r" "$(printf '%s\n' \
  "UNWIRED hooks/lonely-gate.py ← py.md:1" \
  "MISSING hooks/gone-gate.py ← py.md:2" \
  "OK hooks/linked.sh ← py.md:3")" 0

# 8. 內部失敗 → 固定 unavailable marker、非零 exit
r=$(new_fixture fail-missing-dir)
rmdir "$r/memory"
run_audit "$r"
if [ "$(<"$r/out")" = "WIRED-CHECK-UNAVAILABLE" ] && [ "$(<"$r/rc")" != 0 ]; then
  echo "PASS missing memory dir prints unavailable marker with non-zero exit"
  ((pass++))
else
  echo "FAIL missing memory dir: rc=$(<"$r/rc") out=[$(<"$r/out")]"
  ((fail++))
fi

# 新來源：rules/ 的 md 與 ~/.zshrc alias 引用 scripts/ 內的腳本時算接線（2026-10-16 加掃 rules／references／agents／workflows／zshrc）
r=$(new_fixture rules-and-zshrc-sources)
mkdir -p "$r/rules/common"
printf '#!/bin/bash\necho bundle\n' > "$r/scripts/bundle.sh"
printf '#!/bin/bash\necho radar\n' > "$r/scripts/radar.sh"
printf '#!/bin/bash\necho orphan\n' > "$r/scripts/orphan.sh"
printf '先跑 `~/.claude/scripts/bundle.sh` 打包\n' > "$r/rules/common/flow.md"
printf 'alias radar="bash ~/.claude/scripts/radar.sh"\n' > "$r/zshrc"
printf '打包用 `~/.claude/scripts/bundle.sh`；雷達用 `~/.claude/scripts/radar.sh`；另有 `~/.claude/scripts/orphan.sh`\n' > "$r/memory/wired.md"
run_audit "$r"
check "rules md and zshrc alias count as wiring sources" "$r" "$(printf 'OK scripts/bundle.sh ← wired.md:1\nOK scripts/radar.sh ← wired.md:1\nUNWIRED scripts/orphan.sh ← wired.md:1')" 0

# workflows/ 的 .sh 呼叫 scripts/ 腳本算接線（2026-10-17：failure-mode-daily.py 只被 workflow wrapper 呼叫，曾被判 UNWIRED）
r=$(new_fixture workflow-sources)
mkdir -p "$r/workflows"
printf '#!/usr/bin/env python3\n' > "$r/scripts/wf-only.py"
printf '#!/usr/bin/env python3\n' > "$r/scripts/nobody.py"
printf '#!/bin/bash\npython3 ~/.claude/scripts/wf-only.py --date today\n' > "$r/workflows/wf-only-daily.sh"
printf '每日由 `~/.claude/scripts/wf-only.py` 算筆數；`~/.claude/scripts/nobody.py` 沒人叫\n' > "$r/memory/wf.md"
run_audit "$r"
check "workflow wrapper counts as wiring source" "$r" "$(printf 'OK scripts/wf-only.py ← wf.md:1\nUNWIRED scripts/nobody.py ← wf.md:1')" 0

echo "== $pass pass / $fail fail =="
[ "$fail" -eq 0 ]
