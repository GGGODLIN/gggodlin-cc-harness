#!/bin/bash
# hash-reflow-daily 契約測試：fixture repo 內的 hash 識別字命中與 baseline 比對。
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/hash-reflow-daily.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0
ok() { echo "PASS $1"; pass=$((pass+1)); }
ng() { echo "FAIL $1"; fail=$((fail+1)); }

A="$TMP/repoA"; B="$TMP/repoB"
mkdir -p "$A/hooks" "$A/node_modules/x" "$A/.scratch" "$B/scripts"
BASE="$TMP/baseline.tsv"
run() {
  HASH_REFLOW_REPOS="A=$A;B=$B" HASH_REFLOW_BASELINE="$BASE" HASH_REFLOW_OUT="$TMP/out.md" \
    HASH_REFLOW_LOG_DIR="$TMP/logs" LOCAL_ANALYSIS_DATE=2026-01-01 bash "$SCRIPT" "$@" >/dev/null 2>&1
  echo "rc=$?" > "$TMP/rc"
  [ -f "$TMP/out.md" ] && cat "$TMP/out.md"
}

# 既有識別鍵檔：兩行命中；另一檔只有裸 digest／hash 字樣（regex 刻意不抓）
printf 'import hashlib\nkey = hashlib.sha1(x).hexdigest()\n' > "$A/hooks/keep.py"
printf 'digest = summarize(hash_table)\n' > "$A/hooks/plain.py"
printf '#!/bin/sh\necho shasum -a 256 x\n' > "$B/scripts/runner"; chmod +x "$B/scripts/runner"
printf 'const h = createHash("sha256")\n' > "$A/node_modules/x/dep.js"
printf 'import hashlib\n' > "$A/.scratch/probe.py"

# 1. 先寫 baseline
run --write-baseline >/dev/null
grep -q $'^A\thooks/keep.py\t2$' "$BASE" && ok "baseline：keep.py 記 2 行命中" || ng "baseline：keep.py 計數錯（$(cat "$BASE" 2>/dev/null)）"
grep -q $'^B\tscripts/runner\t1$' "$BASE" && ok "baseline：無副檔名可執行檔也納入" || ng "baseline：漏掉無副檔名可執行檔"
grep -q 'plain.py' "$BASE" && ng "baseline：裸 digest／hash 字樣被誤抓" || ok "baseline：裸 digest／hash 不抓"
grep -qE 'node_modules|\.scratch' "$BASE" && ng "baseline：排除目錄未生效" || ok "baseline：排除 node_modules／.scratch"

# 2. 無變化 → __SILENT__
out=$(run)
[ "$out" = "__SILENT__" ] && ok "無變化 → __SILENT__" || ng "無變化未 __SILENT__（得到: ${out}）"

# 3. 新檔含 hashlib → 報新檔、帶行號
printf 'import hashlib\n\nreceipt["sha256"] = hashlib.sha256(b).hexdigest()\n' > "$A/hooks/new_gate.py"
out=$(run)
printf '%s' "$out" | grep -q 'hooks/new_gate.py' && ok "新檔：被列出" || ng "新檔：未列出"
printf '%s' "$out" | grep -q 'new_gate.py:1' && ok "新檔：附行號" || ng "新檔：缺行號"
printf '%s' "$out" | grep -q '新檔 1' && ok "新檔：計數 1" || ng "新檔：計數錯"
printf '%s' "$out" | grep -q 'keep.py' && ng "既有檔未變卻被列出" || ok "既有檔未變不列"
rm -f "$A/hooks/new_gate.py"

# 4. 既有檔命中數上升 2→3 → 報上升；下降不報
printf 'import hashlib\nkey = hashlib.sha1(x).hexdigest()\nreceipt_sha256 = hashlib.sha256(y).hexdigest()\n' > "$A/hooks/keep.py"
out=$(run)
printf '%s' "$out" | grep -q 'keep.py' && ok "上升：被列出" || ng "上升：未列出"
printf '%s' "$out" | grep -qE 'keep.py.*2 *→ *3' && ok "上升：顯示 2→3" || ng "上升：未顯示 2→3"
printf 'import hashlib\n' > "$A/hooks/keep.py"
out=$(run)
[ "$out" = "__SILENT__" ] && ok "下降 → __SILENT__" || ng "下降不該報（得到: ${out}）"

# 5. 報告只寫到 OUT；log 有計數
printf 'import hashlib\nkey = hashlib.sha1(x).hexdigest()\n' > "$A/hooks/keep.py"
run >/dev/null
[ -f "$TMP/out.md" ] && [ ! -L "$TMP/out.md" ] && ok "旁路：只寫 out.md" || ng "旁路：輸出型態異常"
ls "$TMP/logs"/local-analysis-hash-reflow-2026-01-01.log >/dev/null 2>&1 && grep -q 'new=0' "$TMP/logs"/local-analysis-hash-reflow-2026-01-01.log && ok "log 記錄計數" || ng "log 缺計數"

# 6. 無 baseline 檔 → 不猜、非零退出、不寫 __SILENT__
rm -f "$BASE" "$TMP/out.md"
run >/dev/null
grep -q 'rc=0' "$TMP/rc" && ng "缺 baseline 仍退出 0" || ok "缺 baseline 非零退出"
[ -f "$TMP/out.md" ] && grep -q '__SILENT__' "$TMP/out.md" && ng "缺 baseline 卻寫 __SILENT__" || ok "缺 baseline 不寫 __SILENT__"

echo "== $pass passed, $fail failed"
[ "$fail" -eq 0 ]
