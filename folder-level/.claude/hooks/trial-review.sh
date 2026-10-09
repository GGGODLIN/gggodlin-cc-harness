#!/bin/bash
# UserPromptSubmit hook — 在 ~/Desktop/projects/ cwd 的第一個 prompt，
# 彙總已到期 trial 與過門檻 friction-log，導向 /trial-review。

INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)
CWD=$(echo "$INPUT" | jq -r '.cwd // empty' 2>/dev/null)

[ -z "$SESSION_ID" ] && exit 0

# 只在 cwd 剛好是 ~/Desktop/projects/ 時觸發（不含子目錄）
EXPECTED="$HOME/Desktop/projects"
[ "$CWD" != "$EXPECTED" ] && exit 0

MARKER="/tmp/trial-review-session-${SESSION_ID}"
[ -f "$MARKER" ] && exit 0

# 2026-08-06 fix: /tmp 是 symlink、BSD find 不跟隨起始點 → 補尾斜線才真的會 GC（review finding 9）
find /tmp/ -maxdepth 1 -name "trial-review-session-*" -type f -mtime +1 -delete 2>/dev/null

TRIALS_FILE="$HOME/Desktop/projects/.claude/trials/active.md"
# 2026-08-06 fix: active.md 不存在只跳過時間制段、不再整支 exit——事件制 sweep 與 trial ledger 是獨立機制（review finding 4）

# 2026-08-06 fix: 比較基準統一為「日期午夜」。舊寫法 REVIEW_TS 用 date -j -f "%Y-%m-%d" 解析
# 會繼承當下時分秒，與先抓的 TODAY_TS 差一秒即讓「今天到期」entry 整批靜默掉光（friction-sweep.test.sh c6 曝露）。
# TODAY_TS 解析失敗時為空 → 下方 guard 跳過時間制段（bash 對 [ x -le "" ] 靜默回 1，不能放進比較）。
TODAY_TS=$(date -j -f "%Y-%m-%d %H:%M:%S" "$(date +%Y-%m-%d) 00:00:00" "+%s" 2>/dev/null)
DUE_LINES=""
DUE_COUNT=0

# 2026-07-03 fix: 舊 regex 要求「空格 + (純日期) 收尾」，帶尾綴 (2026-06-29 review date)
# 或全形括號直接接 (date) 的 entry 全部隱形（29 個 H2 只認得 17 個）。
# 新 regex：日期後可帶任意尾綴、日期括號前不強制空格。
re='^##[ ]+(.+)\(([0-9]{4}-[0-9]{2}-[0-9]{2})[^)]*\)[ ]*$'
TRIALS_ROOT="${TRIALS_FILE%/active.md}"
entry_metadata() {
  local target="$1"
  awk -v target="$target" '
    $0 == target {inside=1; next}
    inside && /^##[ ]+/ {exit}
    inside && /^-[ ]+started:/ {
      has_started=1
      sub(/^-[- ]*started:[ ]*/, "")
      started=$0
    }
    inside && /^-[ ]+status:/ {has_status=1}
    inside && /^-[ ]+detail:/ {
      has_detail=1
      sub(/^-[- ]*detail:[ ]*/, "")
      gsub(/`/, "")
      detail=$0
    }
    END {printf "%d\t%d\t%d\t%s\t%s\n", has_started + 0, has_status + 0, has_detail + 0, started, detail}
  ' "$TRIALS_FILE"
}
detail_key_for_path() {
  awk 'NR == 1 && /^detail-key:[ ]+/ {sub(/^detail-key:[ ]*/, ""); print}' "$1"
}
detail_title_for_path() {
  awk 'NR <= 2 && /^detail-title:[ ]+/ {sub(/^detail-title:[ ]*/, ""); print; exit}' "$1"
}
review_start_for_path() {
  python3 - "$1" <<'PY'
from pathlib import Path
import sys
import unicodedata

fields = {}
for line in Path(sys.argv[1]).read_text().splitlines()[2:]:
  if not line.strip():
    continue
  key, separator, value = line.partition(":")
  if not separator or key not in {"review-start", "review-start-reason", "review-start-gap"}:
    break
  fields[key] = value.strip()
level = fields.get("review-start")
reason = "".join(" " if unicodedata.category(c) in {"Cc", "Cf", "Zl", "Zp"} else c for c in fields.get("review-start-reason", "")).strip()
gap = "".join(" " if unicodedata.category(c) in {"Cc", "Cf", "Zl", "Zp"} else c for c in fields.get("review-start-gap", "")).strip()
if level is None:
  label = "一般起手（尚未標記）"
elif level == "general":
  label = "一般起手"
elif level == "strong" and reason:
  label = "建議強模型"
else:
  label = "建議資料待補"
text = "；" + label
if reason:
  text += "｜" + reason
if gap:
  text += "｜資料缺口：" + gap
print(text.replace("\\", "\\\\"))
PY
}
canonical_detail_stem() {
  python3 - "$1" "$2" <<'PY'
import re
import sys
import unicodedata

title, started = sys.argv[1:]
normalized = unicodedata.normalize("NFKC", title).strip().lower()
slug = re.sub(r"[\W_]+", "-", normalized, flags=re.UNICODE).strip("-")
match = re.fullmatch(r"(.+) \[run-(\d+)\]", title)
if match:
    base = re.sub(r"[\W_]+", "-", unicodedata.normalize("NFKC", match.group(1)).strip().lower(), flags=re.UNICODE).strip("-")
    slug = f"{base}-{match.group(2)}"
print(f"{slug}-{started}")
PY
}
detail_basename_matches() {
  local basename="$1"
  local stem="$2"
  local suffix
  case "$basename" in
    "$stem.md") return 0 ;;
    "$stem-"[0-9]*".md")
      suffix="${basename#"$stem-"}"
      suffix="${suffix%.md}"
      [[ "$suffix" =~ ^[1-9][0-9]*$ ]]
      return $?
      ;;
  esac
  return 1
}
if [ -f "$TRIALS_FILE" ] && [ -n "$TODAY_TS" ]; then
while IFS= read -r line; do
  if [[ "$line" =~ $re ]]; then
    NAME="${BASH_REMATCH[1]% }"
    REVIEW_DATE="${BASH_REMATCH[2]}"
    REVIEW_TS=$(date -j -f "%Y-%m-%d %H:%M:%S" "$REVIEW_DATE 00:00:00" "+%s" 2>/dev/null) || continue
    if [ "$REVIEW_TS" -le "$TODAY_TS" ]; then
      META=$(entry_metadata "$line")
      IFS=$'\t' read -r HAS_STARTED HAS_STATUS HAS_DETAIL STARTED DETAIL_REL <<< "$META"
      DETAIL_NOTE=""
      START_NOTE="；一般起手（尚未標記）"
      if [ "$HAS_STARTED" -eq 0 ] && [ "$HAS_STATUS" -eq 0 ] && [ "$HAS_DETAIL" -eq 0 ]; then
        :
      elif [ "$HAS_STARTED" -ne 1 ] || [ "$HAS_STATUS" -ne 1 ] || [ "$HAS_DETAIL" -ne 1 ]; then
        DETAIL_NOTE="；detail-missing（索引欄位不完整）"
      else
        case "$DETAIL_REL" in
          active/*.md)
            case "$DETAIL_REL" in
              *..*|active/*/*)
                DETAIL_NOTE="；detail-invalid（detail 指針無效）：$DETAIL_REL"
                ;;
              *)
                DETAIL_PATH="$TRIALS_ROOT/$DETAIL_REL"
                if [ ! -f "$DETAIL_PATH" ]; then
                  DETAIL_NOTE="；detail-missing（detail 缺失）：$DETAIL_REL"
                elif [ "$(detail_key_for_path "$DETAIL_PATH")" != "$DETAIL_REL" ] || [ "$(detail_title_for_path "$DETAIL_PATH")" != "$NAME" ]; then
                  DETAIL_NOTE="；detail-mismatch（detail 身分不符）：$DETAIL_REL"
                elif ! detail_basename_matches "$(basename "$DETAIL_REL")" "$(canonical_detail_stem "$NAME" "$STARTED")"; then
                  DETAIL_NOTE="；detail-mismatch（detail canonical 身分不符）：$DETAIL_REL"
                else
                  START_NOTE=$(review_start_for_path "$DETAIL_PATH") || START_NOTE="；建議資料待補"
                fi
                ;;
            esac
            ;;
          *)
            DETAIL_NOTE="；detail-invalid（detail 指針無效）：$DETAIL_REL"
            ;;
        esac
      fi
      [ -n "$DETAIL_NOTE" ] && START_NOTE="；建議資料待補"
      DETAIL_NOTE="${DETAIL_NOTE}${START_NOTE}"
      DAYS=$(( (TODAY_TS - REVIEW_TS) / 86400 ))
      if [ "$DAYS" -eq 0 ]; then
        DUE_LINES="${DUE_LINES}- ${NAME}（今天到期${DETAIL_NOTE}）\n"
      else
        DUE_LINES="${DUE_LINES}- ${NAME}（已過 ${DAYS} 天${DETAIL_NOTE}）\n"
      fi
      DUE_COUNT=$((DUE_COUNT + 1))
    fi
  fi
done < "$TRIALS_FILE"
fi

touch "$MARKER"

# 2026-07-03 add: active.md 超 50KB 時的低急迫提示（不燒 context、只影響維護時 Read 一口氣讀不完）
SIZE_WARN=""
if [ -f "$TRIALS_FILE" ]; then
  FILE_BYTES=$(wc -c < "$TRIALS_FILE" | tr -d ' ')
  if [ "$FILE_BYTES" -gt 51200 ]; then
    SIZE_WARN="ℹ️ active.md 已 $((FILE_BYTES / 1024))KB、超過 Read 單次上限：grep/sed 分段讀（維護規範見檔頭）\n"
  fi
fi

# ===== 事件制分區：friction-log sweep（通用摩擦協議 2026-08-06，規則見 ~/.claude/friction/PROTOCOL.md）=====
# 口徑：各檔「## 待折」段內以 "- " 開頭的行數；「單檔 ≥ 門檻」才報一行（不是總和制）。
# 協議的「同類摩擦第 2 次」條件屬語意判斷、sweep 不實作——由錨點 append 當下自行判斷提早提出（review finding 7）。
# 公司側新增檔案 → 改 COMPANY_FRICTION_FILES 清單。FRICTION_SCAN_HOME 供 fixture 測試覆寫。
FRICTION_THRESHOLD="${FRICTION_THRESHOLD:-3}"
[[ "$FRICTION_THRESHOLD" =~ ^[0-9]+$ ]] || FRICTION_THRESHOLD=3
SCAN_HOME="${FRICTION_SCAN_HOME:-$HOME}"
COMPANY_FRICTION_FILES=(
  # acme 的檔案存在但尚無「## 待折」段 → 目前恆計 0；補段後自動生效。
  # 註：/pr-review 的摩擦另存 ~/.claude/pr-review/friction.md，格式未接本協議、不在掃描口徑內。
  "$SCAN_HOME/Desktop/work/acme/docs/owner/harness-friction.md"
)
# 個人側具名檔：落在兩個 glob 之外、但仍走本協議的摩擦檔。
# pr-review/friction.md 被 .gitignore 單獨排除（條目含公司 repo 名與 PR 編號），所以不能搬進
# skills/ 樹——那會讓它進個人 config repo。改為在此具名掃描，檔案留在原處與 repos.yaml 同目錄。
PRIVATE_FRICTION_FILES=(
  "$SCAN_HOME/.claude/pr-review/friction.md"
)
FRICTION_FILES=()
while IFS= read -r f; do [ -n "$f" ] && FRICTION_FILES+=("$f"); done < <(
  find "$SCAN_HOME/.claude/skills" -maxdepth 2 -type f -name 'friction-log.md' 2>/dev/null
  find "$SCAN_HOME/.claude/friction" -maxdepth 1 -type f -name '*.md' ! -name 'PROTOCOL.md' 2>/dev/null
)
for f in "${PRIVATE_FRICTION_FILES[@]}"; do [ -f "$f" ] && FRICTION_FILES+=("$f"); done
for f in "${COMPANY_FRICTION_FILES[@]}"; do [ -f "$f" ] && FRICTION_FILES+=("$f"); done

# 2026-09-12：計數分母改為「待折段中尚未通知過的項目」，所有檔案一致（不分有主／無主）。
# 理由：待折段原本同時容納「沒看過」與「看過但決定不改」，後者已完成審閱卻因計數不變而每天重報。
# 休眠段由協議定義、不在待折段內，awk 掃到下一個 `## ` 即止，因此自動不計入。
# 水位跟著「項目」走（每行內容的 SHA-256），不跟著檔案走——用檔案 mtime 或全文 hash 會讓
# 「整理格式、搬動歷史段落」也觸發重複提醒（2026-09-12 顧問審查指出，本檔前一版即為檔案級計數）。
# 已知行為：編輯既有項目的文字會改變它的 hash、視同新項目重新通知一次。罕見且無害，不另做正規化。
# 狀態是 hash 清單 cache、不是 ledger（可安全刪除，刪掉只會讓下次全部重報一次）。
FRICTION_STATE_DIR="${FRICTION_STATE_DIR:-$SCAN_HOME/.claude/logs/friction-sweep}"
FRICTION_DUE_TOTAL=0
FRICTION_DUE_FILE_HITS=0
FRICTION_DUE_NAMES=""
FRICTION_PENDING_TOTAL=0
FRICTION_PENDING_NAMES=""
# 本 hook 刻意不開 set -u；若日後要開，空陣列展開需改 ${FRICTION_FILES[@]+"${FRICTION_FILES[@]}"}（bash 3.2 空陣列 + set -u 會炸 unbound）
for f in "${FRICTION_FILES[@]}"; do
  CNT=$(awk '/^## 待折$/{if(!seen){seen=1;flag=1};next}flag&&/^## /{flag=0;done=1}done{next}flag&&/^- /&&$0!~/\[pending_implementation /{c++}END{print c+0}' "$f" 2>/dev/null)
  PENDING_CNT=$(awk '/^## 待折$/{if(!seen){seen=1;flag=1};next}flag&&/^## /{flag=0;done=1}done{next}flag&&/^- /&&$0~/\[pending_implementation /{c++}END{print c+0}' "$f" 2>/dev/null)
  CNT="${CNT:-0}"
  PENDING_CNT="${PENDING_CNT:-0}"
  # 未通知數：待折段項目中，內容 hash 不在該檔 .notified 清單裡的數量。
  # python3 失敗或不存在時 UNNOTIFIED 為空 → 下方 guard 退回用 CNT，行為等同舊的純門檻制（fail open，
  # 這是提示型 hook、不是安全型 gate；寧可多提醒一次也不要靜默漏報）。
  # 鍵用「相對 SCAN_HOME 的完整路徑」而非 basename：skills 樹下每個 friction-log.md 的 basename 都相同，
  # 用 basename 當鍵會讓它們共用同一個 .notified，而寫入是覆寫（open(state,"w")）不是累加——
  # 後報的檔會把先報的檔水位整個抹掉，抑制對 skill 層等於沒作用（2026-09-14 修；case 7i 釘住）。
  FRICTION_STATE_FILE="$FRICTION_STATE_DIR/$(printf '%s' "${f#$SCAN_HOME/}" | tr '/' '_').notified"
  UNNOTIFIED=$(FRICTION_FILE="$f" FRICTION_NOTIFIED="$FRICTION_STATE_FILE" python3 -c '
import hashlib, os, re, sys
path = os.environ["FRICTION_FILE"]
state = os.environ["FRICTION_NOTIFIED"]
try:
    lines = open(path, encoding="utf-8").read().splitlines()
except Exception:
    sys.exit(1)
pending, seen, flag = [], False, False
for l in lines:
    if re.fullmatch(r"## 待折", l):
        if not seen: seen, flag = True, True
        continue
    if flag and l.startswith("## "):
        flag = False
        continue
    if flag and l.startswith("- ") and "[pending_implementation " not in l:
        pending.append(hashlib.sha256(l.encode("utf-8")).hexdigest())
try:
    known = set(open(state, encoding="utf-8").read().split())
except Exception:
    known = set()
print(sum(1 for h in pending if h not in known))
' 2>/dev/null)
  [[ "$UNNOTIFIED" =~ ^[0-9]+$ ]] || UNNOTIFIED="$CNT"
  FRICTION_REPORT=0
  [ "$UNNOTIFIED" -ge "$FRICTION_THRESHOLD" ] && FRICTION_REPORT=1
  if [ "$FRICTION_REPORT" -eq 1 ]; then
    # 報了就把當前待折段全部項目記為已通知（提醒一行指向整個檔，人進 review 時看得到全部）
    FRICTION_FILE="$f" FRICTION_NOTIFIED="$FRICTION_STATE_FILE" FRICTION_DIR="$FRICTION_STATE_DIR" python3 -c '
import hashlib, os, re
path = os.environ["FRICTION_FILE"]
state = os.environ["FRICTION_NOTIFIED"]
os.makedirs(os.environ["FRICTION_DIR"], mode=0o700, exist_ok=True)
lines = open(path, encoding="utf-8").read().splitlines()
out, seen, flag = [], False, False
for l in lines:
    if re.fullmatch(r"## 待折", l):
        if not seen: seen, flag = True, True
        continue
    if flag and l.startswith("## "):
        flag = False
        continue
    if flag and l.startswith("- ") and "[pending_implementation " not in l:
        out.append(hashlib.sha256(l.encode("utf-8")).hexdigest())
open(state, "w", encoding="utf-8").write("\n".join(out) + ("\n" if out else ""))
' 2>/dev/null
  fi
  if [ "$FRICTION_REPORT" -eq 1 ]; then
    FRICTION_DUE_TOTAL=$((FRICTION_DUE_TOTAL + CNT))
    FRICTION_DUE_FILE_HITS=$((FRICTION_DUE_FILE_HITS + 1))
    FRICTION_DUE_NAMES="${FRICTION_DUE_NAMES}${FRICTION_DUE_NAMES:+、}${f#$SCAN_HOME/}(${CNT})"
  fi
  if [ "$PENDING_CNT" -gt 0 ]; then
    FRICTION_PENDING_TOTAL=$((FRICTION_PENDING_TOTAL + PENDING_CNT))
    FRICTION_PENDING_NAMES="${FRICTION_PENDING_NAMES}${FRICTION_PENDING_NAMES:+、}${f#$SCAN_HOME/}(${PENDING_CNT})"
  fi
done
FRICTION_LINE=""
if [ -n "$FRICTION_DUE_NAMES" ]; then
  FRICTION_LINE="🧰 摩擦待折：${FRICTION_DUE_FILE_HITS} 檔共 ${FRICTION_DUE_TOTAL} 項，過門檻：${FRICTION_DUE_NAMES}（跑 /trial-review 處理；協議 ~/.claude/friction/PROTOCOL.md）\n"
fi
if [ -n "$FRICTION_PENDING_NAMES" ]; then
  FRICTION_LINE="${FRICTION_LINE}🧾 已拍板待落地：${FRICTION_PENDING_TOTAL} 項，位置：${FRICTION_PENDING_NAMES}（跑 /trial-review 對帳 implementation）\n"
fi
# ===== 事件制分區結束 =====

[ "$DUE_COUNT" -eq 0 ] && [ -z "$SIZE_WARN" ] && [ -z "$FRICTION_LINE" ] && exit 0

if [ "$DUE_COUNT" -gt 0 ]; then
  MSG="🔬 你有 ${DUE_COUNT} 個試用觀察到 review 期（跑 /trial-review 逐項處理）：\n${DUE_LINES}${SIZE_WARN}${FRICTION_LINE}清單檔: ${TRIALS_FILE}"
else
  MSG="${SIZE_WARN}${FRICTION_LINE}清單檔: ${TRIALS_FILE}"
fi
# 2026-08-17 systemmessage-hook-conversion：純提醒改走 systemMessage 直接顯示給使用者
# （UserPromptSubmit 渲染當日經使用者親眼實證），不再要求模型原文轉發；字面 \n 轉真實換行
jq -nc --arg msg "$(printf '%b' "$MSG")" '{systemMessage:$msg}'
