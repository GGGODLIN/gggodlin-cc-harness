#!/bin/bash
# recurring-errors-envclass.sh 的回歸 fixture（gate-authoring §3：known-good / known-bad / 邊界）
# 跑法：bash recurring-errors-envclass.test.sh
# 改詞表後必重跑。鎖住的線 = 「真環境類要抓到、agent 自己的錯不准被判成環境、
# 子字串與裸 token 兩個已撞過的假陽性不准復發」。

set -uo pipefail
SCRIPT="$(dirname "$0")/recurring-errors-envclass.sh"
TMP=$(mktemp -d); trap 'rc=$?; rm -rf "$TMP"; exit $rc' EXIT
pass=0; fail=0

mk() {
  : > "$TMP/led.jsonl"
  local i=0
  for sig in "$@"; do
    for s in a b c; do
      printf '{"date":"2026-08-01","sig":%s,"session":"%s%d"}\n' "$(jq -Rc . <<<"$sig")" "$s" "$i" >> "$TMP/led.jsonl"
    done
    i=$((i+1))
  done
}

expect() {
  local mode=$1 sig=$2 want=$3 name=$4
  mk "$sig"
  local out
  out=$(ENVCLASS_LEDGER="$TMP/led.jsonl" bash "$SCRIPT" "$mode")
  local got="absent"; [ -n "$out" ] && got="present"
  if [ "$got" = "$want" ]; then
    printf '  PASS  %s\n' "$name"; pass=$((pass+1))
  else
    printf '  FAIL  %s\n        want %s in `%s`, got %s\n' "$name" "$want" "$mode" "$got"; fail=$((fail+1))
  fi
}

printf '\n=== known-good：真環境類必須落 env ===\n'
expect env "command timed out after 120000 ms"                                    present "指令逾時"
expect env 'error capturing screenshot: cdp sendcommand "page.capturescreenshot" timed out' present "CDP 截圖逾時"
expect env "git@github.com: permission denied (publickey)."                        present "SSH 金鑰認證失敗"
expect env "the socket connection was closed unexpectedly"                         present "socket 斷線"
expect env "error: enotfound registry.npmjs.org"                                   present "DNS 查不到（獨立 token）"
expect env "request failed with status code 429 too many requests"                 present "被限流"
expect env "no space left on device"                                               present "磁碟滿"
expect env "did not become interactive within the configured timeout"              present "元素等待逾時"

printf '\n=== known-bad（迴歸兩個撞過的假陽性）：agent 自己的錯不准判成環境 ===\n'
expect env "filenotfounderror: [errno 2] no such file or directory: '/x'"          absent  "fil-enotfound-error 子字串（真實簽名）"
expect env "modulenotfounderror: no module named 'yaml'"                           absent  "modul-enotfound-error 子字串（真實簽名）"
expect env "return opener.open(url, data, timeout)"                                absent  "traceback 程式碼行含裸 timeout（真實簽名）"
expect env "string to replace not found in file."                                  absent  "Edit 比對失敗＝agent 錯"
expect env "file has not been read yet. read it first before writing to it."       absent  "未讀先寫＝agent 錯"

printf '\n=== 互斥性：同一簽名只能落一邊 ===\n'
mk "command timed out after 120000 ms"
e=$(ENVCLASS_LEDGER="$TMP/led.jsonl" bash "$SCRIPT" env | grep -c . || true)
b=$(ENVCLASS_LEDGER="$TMP/led.jsonl" bash "$SCRIPT" behavior | grep -c . || true)
if [ "$e" = "1" ] && [ "$b" = "0" ]; then
  printf '  PASS  環境類不重複出現在 behavior\n'; pass=$((pass+1))
else
  printf '  FAIL  互斥性破了（env=%s behavior=%s）\n' "$e" "$b"; fail=$((fail+1))
fi

mk "string to replace not found in file."
e=$(ENVCLASS_LEDGER="$TMP/led.jsonl" bash "$SCRIPT" env | grep -c . || true)
b=$(ENVCLASS_LEDGER="$TMP/led.jsonl" bash "$SCRIPT" behavior | grep -c . || true)
if [ "$e" = "0" ] && [ "$b" = "1" ]; then
  printf '  PASS  行為類不重複出現在 env\n'; pass=$((pass+1))
else
  printf '  FAIL  互斥性破了（env=%s behavior=%s）\n' "$e" "$b"; fail=$((fail+1))
fi

printf '\n=== 邊界：門檻與空輸入 ===\n'
: > "$TMP/led.jsonl"
out=$(ENVCLASS_LEDGER="$TMP/led.jsonl" bash "$SCRIPT" stats 2>&1)
if [ "$out" = "candidates=0 environment=0 behavior=0" ]; then
  printf '  PASS  空 ledger → 全零、不炸\n'; pass=$((pass+1))
else
  printf '  FAIL  空 ledger 輸出異常：%s\n' "$out"; fail=$((fail+1))
fi

printf '{"date":"2026-08-01","sig":"command timed out after 1 ms","session":"solo"}\n' > "$TMP/led.jsonl"
out=$(ENVCLASS_LEDGER="$TMP/led.jsonl" bash "$SCRIPT" env)
if [ -z "$out" ]; then
  printf '  PASS  單次單 session 未過門檻 → 不列（治一次性抖動）\n'; pass=$((pass+1))
else
  printf '  FAIL  未過門檻卻被列出\n'; fail=$((fail+1))
fi

out=$(ENVCLASS_LEDGER="$TMP/led.jsonl" bash "$SCRIPT" bogus 2>&1); rc=$?
if [ "$rc" = "2" ]; then
  printf '  PASS  未知模式 → exit 2\n'; pass=$((pass+1))
else
  printf '  FAIL  未知模式 exit=%s\n' "$rc"; fail=$((fail+1))
fi

printf '\n---- %d passed, %d failed ----\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
