#!/bin/bash
# trial-review.sh 事件制分區（friction sweep）fixture 回歸測試
# 跑法：bash ~/Desktop/projects/.claude/hooks/friction-sweep.test.sh
# 案例：零命中不輸出 / 門檻邊界 N-1 不報、N 報 / 計數正確 / 導向 trial-review / 噪音目錄不誤掃 / 時間制段不受影響
set -u
HOOK="$HOME/Desktop/projects/.claude/hooks/trial-review.sh"
FIX="$(mktemp -d)"
trap 'rm -rf "$FIX"; rm -f /tmp/trial-review-session-fricttest-*' EXIT
PASS=0; FAIL=0; SKIP=0

run_hook() { # $1=session_id $2=scan_home
  printf '{"session_id":"fricttest-%s","cwd":"%s/Desktop/projects"}' "$1" "$HOME" \
    | FRICTION_SCAN_HOME="$2" bash "$HOOK"
}
assert() { # $1=desc $2=expected(yes/no) $3=output
  if [ "$2" = yes ]; then
    echo "$3" | grep -q '🧰' && { echo "PASS: $1"; PASS=$((PASS+1)); } || { echo "FAIL: $1"; echo "$3"; FAIL=$((FAIL+1)); }
  else
    echo "$3" | grep -q '🧰' && { echo "FAIL: $1"; echo "$3"; FAIL=$((FAIL+1)); } || { echo "PASS: $1"; PASS=$((PASS+1)); }
  fi
}
mkfl() { # $1=path $2=待折條數
  # BSD seq 1 0 會降序輸出「1 0」而非空（review finding 2），條數 0 必須顯式跳過
  mkdir -p "$(dirname "$1")"
  { echo "# fixture"; echo; echo "## 待折"; echo
    if [ "$2" -gt 0 ]; then
      for i in $(seq 1 "$2"); do echo "- 2026-08-06 假摩擦 $i 假方向"; done
    fi
    echo; echo "## 已折／已否決"; echo "- 2026-01-01 已折的不算 落點"; } > "$1"
}

# case 1: 零命中 → 不輸出
mkdir -p "$FIX/h1/.claude/skills" "$FIX/h1/.claude/friction"
mkfl "$FIX/h1/.claude/skills/mech-a/friction-log.md" 0
OUT=$(run_hook c1 "$FIX/h1")
assert "零命中不輸出" no "$OUT"

# case 2: 單檔 2 條（門檻-1）→ 不報
mkdir -p "$FIX/h2/.claude/friction"
mkfl "$FIX/h2/.claude/skills/mech-a/friction-log.md" 2
OUT=$(run_hook c2 "$FIX/h2")
assert "門檻-1（2 條）不報" no "$OUT"

# case 3+4: 單檔 3 條達門檻 → 報，且只計過門檻檔案（另一檔 2 條不計）
mkdir -p "$FIX/h3/.claude/friction"
mkfl "$FIX/h3/.claude/skills/mech-a/friction-log.md" 3
mkfl "$FIX/h3/.claude/skills/mech-b/friction-log.md" 2
OUT=$(run_hook c3 "$FIX/h3")
assert "門檻（3 條）觸發" yes "$OUT"
echo "$OUT" | grep -q '1 檔共 3 項' && { echo "PASS: 計數只含過門檻檔案（1 檔共 3 項）"; PASS=$((PASS+1)); } || { echo "FAIL: 過門檻計數"; echo "$OUT"; FAIL=$((FAIL+1)); }
echo "$OUT" | grep -q '跑 /trial-review 處理' && { echo "PASS: 導向 trial-review 消費入口"; PASS=$((PASS+1)); } || { echo "FAIL: 未導向 trial-review"; echo "$OUT"; FAIL=$((FAIL+1)); }

# case 7: 兩檔各 2 條（總 4、max 2）→ 不報——釘住「單檔 ≥ 門檻」口徑、殺「總和制」突變（review finding 3）
mkdir -p "$FIX/h7/.claude/friction"
mkfl "$FIX/h7/.claude/skills/mech-a/friction-log.md" 2
mkfl "$FIX/h7/.claude/skills/mech-b/friction-log.md" 2
OUT=$(run_hook c7 "$FIX/h7")
assert "單檔口徑：兩檔各 2（總 4）不報" no "$OUT"

# case 7b: 只數第一個精確待折段，後續同名段與前綴標題不計
mkdir -p "$FIX/h7b/.claude/friction"
mkfl "$FIX/h7b/.claude/skills/mech-a/friction-log.md" 2
printf '\n## 待折\n\n- 第二段不計\n\n## 待折舊資料\n\n- 前綴標題不計\n' >> "$FIX/h7b/.claude/skills/mech-a/friction-log.md"
OUT=$(run_hook c7b "$FIX/h7b")
assert "只數第一個精確待折段" no "$OUT"

# case 8: friction 目錄分支（無主落點檔）計數有效——補該分支測試零覆蓋（review 查核表）
mkfl "$FIX/h8/.claude/friction/workflow-general.md" 3
mkdir -p "$FIX/h8/.claude/skills"
OUT=$(run_hook c8 "$FIX/h8")
assert "friction 目錄分支達門檻觸發" yes "$OUT"

# case 9: 公司側已拍板待落地不重複計入門檻
mkdir -p "$FIX/h9/.claude/friction"
mkfl "$FIX/h9/.claude/skills/mech-a/friction-log.md" 2
python3 - "$FIX/h9/.claude/skills/mech-a/friction-log.md" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text()
s = s.replace('- 2026-08-06 假摩擦 1 假方向', '- 2026-08-06 [pending_implementation proposal_source=trial-review:file-3@test; user_decision=approved@test; implementation=N-A（等待公司側落地）] 假摩擦 1 假方向')
p.write_text(s)
PY
OUT=$(FRICTION_THRESHOLD=2 run_hook c9 "$FIX/h9")
printf '%s' "$OUT" | grep -q '摩擦待折' && { echo "FAIL: pending implementation 被算進門檻"; echo "$OUT"; FAIL=$((FAIL+1)); } || { echo "PASS: pending implementation 不計入門檻"; PASS=$((PASS+1)); }
printf '%s' "$OUT" | grep -q '已拍板待落地：1 項' && { echo "PASS: pending implementation 有獨立追蹤提醒"; PASS=$((PASS+1)); } || { echo "FAIL: pending implementation 沒有追蹤提醒"; echo "$OUT"; FAIL=$((FAIL+1)); }

# case 5: 噪音目錄（skills 樹 depth>2）不誤掃
mkdir -p "$FIX/h5/.claude/friction"
mkfl "$FIX/h5/.claude/skills/node_modules/pkg/deep/friction-log.md" 10
OUT=$(run_hook c5 "$FIX/h5")
assert "噪音目錄不誤掃" no "$OUT"

# case 6: 時間制段不受影響（有無 friction 命中，trial 段輸出相同）
# 2026-08-17 起輸出為 .systemMessage 多行真實換行：濾掉 🧰/🧾 開頭的摩擦行後比對其餘全部
# 前置斷言 T_BASE 非空：兩側同空（hook 整支崩潰）不得假綠（review finding 5）
# 2026-09-12 修：本 case 的 baseline 取自真實 active.md——FRICTION_SCAN_HOME 只覆寫 friction 掃描，
# 時間制段仍讀 $HOME 下的 ledger。沒有到期 trial 的日子 hook 整支 exit 0 不輸出，baseline 必然為空，
# 舊版把這種日子一律判 FAIL。現在先獨立判斷「今天真的沒有到期 trial」再決定 SKIP 或 FAIL，
# 兩者的差別靠 ledger 本身而不是靠 hook 輸出（hook 在 set +e 下崩潰也可能 exit 0，不能當訊號）。
REAL_LEDGER="$HOME/Desktop/projects/.claude/trials/active.md"
TODAY_ISO=$(date +%Y-%m-%d)
DUE_TODAY=0
if [ -f "$REAL_LEDGER" ]; then
  DUE_TODAY=$(grep -c "^## .*($TODAY_ISO" "$REAL_LEDGER" 2>/dev/null | tr -d ' ')
fi
T_BASE=$(run_hook c6a "$FIX/h1" | jq -r '.systemMessage' | grep -v -e '^🧰' -e '^🧾')
T_HIT=$(run_hook c6b "$FIX/h3" | jq -r '.systemMessage' | grep -v -e '^🧰' -e '^🧾')
if [ -z "$T_BASE" ] && [ "$DUE_TODAY" = "0" ]; then
  echo "SKIP: 今天真實 ledger 無到期 trial，時間制段本來就沒輸出，case 6 無可比對基準"
  SKIP=$((SKIP+1))
elif [ -z "$T_BASE" ]; then
  echo "FAIL: baseline 為空但 ledger 有 $DUE_TODAY 筆今日到期 trial（hook 可能崩潰）"; FAIL=$((FAIL+1))
elif [ "$T_BASE" = "$T_HIT" ]; then echo "PASS: 時間制段不受影響"; PASS=$((PASS+1)); else echo "FAIL: 時間制段被影響"; diff <(echo "$T_BASE") <(echo "$T_HIT"); FAIL=$((FAIL+1)); fi

# === case 7: 項目級通知水位（2026-09-12）===
# 計數分母＝待折段中尚未通知過的項目；水位跟著項目內容 hash 走、不跟著檔案走。
# 對照組同時驗有主檔（skills 樹）與無主桶（friction 樹）行為一致。
mkdir -p "$FIX/h7/.claude/skills"
G7="$FIX/h7/.claude/friction/workflow-general.md"
# state 檔名＝相對 SCAN_HOME 的路徑把 / 換成 _（2026-09-14 起；舊版用 basename，見 case 7i）
STATE7="$FIX/h7/.claude/logs/friction-sweep/.claude_friction_workflow-general.md.notified"

# 寫指定條目內容的待折檔（跟 mkfl 不同：每行內容可控，才測得出 hash 級水位）
mkfl_items() { # $1=path，其餘=每個待折條目的文字
  local p="$1"; shift
  mkdir -p "$(dirname "$p")"
  { echo "# fixture"; echo; echo "## 待折"; echo
    for it in "$@"; do echo "- 2026-08-06 $it"; done
    echo; echo "## 休眠"; echo
    echo; echo "## 已折／已否決"; echo "- 2026-01-01 已折的不算 落點"; } > "$p"
}

mkfl_items "$G7" "甲 假方向" "乙 假方向" "丙 假方向"
OUT=$(run_hook c7a "$FIX/h7")
assert "三項未通知達門檻會報" yes "$OUT"
[ "$(wc -l < "$STATE7" 2>/dev/null | tr -d ' ')" = "3" ] && { echo "PASS: 報過後三個 hash 寫入水位"; PASS=$((PASS+1)); } || { echo "FAIL: 水位未寫入三筆（實得 '$(wc -l < "$STATE7" 2>/dev/null | tr -d ' ')'）"; FAIL=$((FAIL+1)); }

OUT=$(run_hook c7b "$FIX/h7")
assert "同一批內容不重複通知" no "$OUT"

# 加兩個新條目：未通知數 2 < 門檻 3，仍不報（門檻套在未通知數上）
mkfl_items "$G7" "甲 假方向" "乙 假方向" "丙 假方向" "丁 假方向" "戊 假方向"
OUT=$(run_hook c7c "$FIX/h7")
assert "新增未達門檻不報" no "$OUT"

# 第三個新條目進來：未通知數 3 → 報
mkfl_items "$G7" "甲 假方向" "乙 假方向" "丙 假方向" "丁 假方向" "戊 假方向" "己 假方向"
OUT=$(run_hook c7d "$FIX/h7")
assert "新增達門檻會再報" yes "$OUT"

# 顧問審查重點：拍板搬走前三項（模擬結案），剩下的三項水位不該因檔案變動而失效
mkfl_items "$G7" "丁 假方向" "戊 假方向" "己 假方向"
OUT=$(run_hook c7e "$FIX/h7")
assert "搬走其他項目不讓留下的項目重新通知" no "$OUT"

# 休眠段的條目不計入待折（協議定義休眠不計提醒）
{ echo "# fixture"; echo; echo "## 待折"; echo
  echo; echo "## 休眠"; echo
  echo "- 2026-08-06 庚 假方向 [dormant since=2026-09-12; wake-when=需使用者主動重提]"
  echo "- 2026-08-06 辛 假方向 [dormant since=2026-09-12; wake-when=需使用者主動重提]"
  echo "- 2026-08-06 壬 假方向 [dormant since=2026-09-12; wake-when=需使用者主動重提]"
  echo; echo "## 已折／已否決"; echo "- 2026-01-01 已折的不算 落點"; } > "$G7"
OUT=$(run_hook c7f "$FIX/h7")
assert "休眠段三項不計入提醒" no "$OUT"

# 對照組：有主檔走同一套水位
rm -f "$G7"
mkfl_items "$FIX/h7/.claude/skills/somewhere/friction-log.md" "癸 假方向" "子 假方向" "丑 假方向"
OUT=$(run_hook c7g "$FIX/h7")
assert "有主檔首次達門檻會報" yes "$OUT"
OUT=$(run_hook c7h "$FIX/h7")
assert "有主檔同一批內容也不重複通知" no "$OUT"

# === case 7i: 多個有主檔的水位互不覆寫（2026-09-14）===
# 反向斷言：state 檔名若用 basename 當鍵，27 個 skill 的 friction-log.md 會共用同一個 .notified，
# 且寫入是覆寫不是累加，導致後報的檔把先報的檔水位抹掉、抑制對 skill 層整片失效。
# 2026-09-14 前的實作即為此形；本 case 釘住「鍵必須能區分來源檔」。
H7I="$FIX/h7i"
mkdir -p "$H7I/.claude/skills"
mkfl_items "$H7I/.claude/skills/alpha/friction-log.md" "A1 假方向" "A2 假方向" "A3 假方向"
OUT=$(run_hook c7i_a "$H7I")
assert "alpha 首次達門檻會報" yes "$OUT"

# beta 進場：alpha 已通知（未通知 0、不計），beta 3 項未通知 → 報
mkfl_items "$H7I/.claude/skills/beta/friction-log.md" "B1 假方向" "B2 假方向" "B3 假方向"
OUT=$(run_hook c7i_b "$H7I")
assert "beta 首次達門檻會報" yes "$OUT"
printf '%s' "$OUT" | grep -q 'skills/beta/friction-log.md' && { echo "PASS: 報的是 beta"; PASS=$((PASS+1)); } || { echo "FAIL: beta 未出現在報告行"; echo "$OUT"; FAIL=$((FAIL+1)); }

# 關鍵斷言：alpha 內容完全沒變，不該因為 beta 報過而重新通知
OUT=$(run_hook c7i_c "$H7I")
assert "beta 報過後 alpha 水位仍在（不重複通知）" no "$OUT"

# 兩個來源檔各自有獨立 state 檔
S7I=$(find "$H7I/.claude/logs/friction-sweep" -name '*.notified' 2>/dev/null | wc -l | tr -d ' ')
[ "$S7I" = "2" ] && { echo "PASS: 兩個來源檔各有獨立水位檔（實得 ${S7I}）"; PASS=$((PASS+1)); } || { echo "FAIL: 水位檔數應為 2、實得 ${S7I}，basename 撞名"; FAIL=$((FAIL+1)); }

# === case 8: 個人側具名檔進掃描範圍（2026-09-12）===
# pr-review/friction.md 被 gitignore 單獨排除、不能搬進 skills/ 樹，改由 PRIVATE_FRICTION_FILES 具名掃描。
# 「待折 0 所以不報」與「根本沒被掃到」在輸出上同形，所以這裡用「有內容就必須報」反向驗證。
mkfl "$FIX/h8/.claude/pr-review/friction.md" 3
OUT=$(run_hook c8a "$FIX/h8")
assert "具名檔有三項會被掃到並報" yes "$OUT"
printf '%s' "$OUT" | grep -q 'pr-review/friction.md' && { echo "PASS: 報出的路徑正確"; PASS=$((PASS+1)); } || { echo "FAIL: 報了但路徑不是 pr-review/friction.md"; echo "$OUT"; FAIL=$((FAIL+1)); }

# 具名檔不存在時不得讓整支掛掉
rm -f "$FIX/h8/.claude/pr-review/friction.md"
mkfl "$FIX/h8/.claude/skills/other/friction-log.md" 3
OUT=$(run_hook c8b "$FIX/h8")
assert "具名檔不存在時其餘掃描照常" yes "$OUT"

python3 - "$HOOK" <<'PY'
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid

hook = sys.argv[1]

class OpeningAdvice(unittest.TestCase):
  def setUp(self):
    self.temp = tempfile.TemporaryDirectory()
    self.addCleanup(self.temp.cleanup)
    self.home = Path(self.temp.name)
    self.root = self.home / 'Desktop/projects/.claude/trials'
    (self.root / 'active').mkdir(parents=True)
    self.ledger = self.root / 'active.md'
    self.detail = self.root / 'active/demo-2026-01-01.md'
    self.session = 'opening-test-' + uuid.uuid4().hex
    self.addCleanup(lambda: Path('/tmp/trial-review-session-' + self.session).unlink(missing_ok=True))
    self.ledger.write_text('## demo (2026-01-01)\n- started: 2026-01-01\n- status: 觀察中\n- detail: active/demo-2026-01-01.md\n')
    self.detail.write_text('detail-key: active/demo-2026-01-01.md\ndetail-title: demo\n\n')

  def run_hook(self):
    before = (self.ledger.read_bytes(), self.detail.read_bytes())
    result = subprocess.run(['/bin/bash', hook], input=json.dumps({'session_id': self.session, 'cwd': str(self.home / 'Desktop/projects')}), text=True, capture_output=True, env={**os.environ, 'HOME': str(self.home), 'FRICTION_SCAN_HOME': str(self.home), 'FRICTION_STATE_DIR': str(self.home / 'state')})
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(before, (self.ledger.read_bytes(), self.detail.read_bytes()))
    return json.loads(result.stdout)['systemMessage'] if result.stdout.strip() else ''

  def metadata(self, text):
    self.detail.write_text(self.detail.read_text() + text + '\n')

  def test_unmarked(self):
    self.assertIn('一般起手（尚未標記）', self.run_hook())
    self.assertEqual(self.run_hook(), '')

  def test_general(self):
    self.metadata('review-start: general\nreview-start-reason: 核對固定條件')
    output = self.run_hook()
    self.assertIn('一般起手', output)
    self.assertIn('核對固定條件', output)
    self.assertIn('1 個試用觀察', output)

  def test_strong_and_gap(self):
    self.metadata('review-start: strong\nreview-start-reason: 本輪重訂判定條件\nreview-start-gap: 缺下一輪觀察目標')
    output = self.run_hook()
    self.assertIn('建議強模型', output)
    self.assertIn('本輪重訂判定條件', output)
    self.assertIn('資料缺口：缺下一輪觀察目標', output)

  def test_invalid(self):
    self.metadata('review-start: other')
    self.assertIn('建議資料待補', self.run_hook())

  def test_strong_without_reason(self):
    self.metadata('review-start: strong')
    output = self.run_hook()
    self.assertIn('建議資料待補', output)
    self.assertNotIn('建議強模型', output)

  def test_literal_text(self):
    literal = r'核對 \n 與 \x1b[31m 及 \c 與 \\server'
    self.metadata('review-start: general\nreview-start-reason: ' + literal + '\x1b\t‮\nreview-start-gap: 缺目標')
    output = self.run_hook()
    advice = next(line for line in output.splitlines() if line.startswith('- demo'))
    self.assertIn(literal, advice)
    self.assertIn('資料缺口：缺目標', advice)
    self.assertNotIn('\x1b', advice)
    self.assertNotIn('‮', advice)
    self.assertNotIn('\t', advice)

  def test_identity_mismatch(self):
    self.detail.write_text('detail-key: active/other.md\ndetail-title: other\nreview-start: strong\nreview-start-reason: 不應讀取\n')
    output = self.run_hook()
    self.assertIn('detail-mismatch', output)
    self.assertNotIn('不應讀取', output)

  def test_future_and_empty(self):
    self.ledger.write_text(self.ledger.read_text().replace('(2026-01-01)', '(2099-01-01)'))
    self.assertEqual(self.run_hook(), '')

suite = unittest.defaultTestLoader.loadTestsFromTestCase(OpeningAdvice)
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(not result.wasSuccessful())
PY
if [ "$?" -eq 0 ]; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); fi

echo "----"
echo "PASS=$PASS FAIL=$FAIL SKIP=$SKIP"
[ "$FAIL" -eq 0 ]
