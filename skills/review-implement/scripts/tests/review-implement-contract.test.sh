#!/usr/bin/env bash
set -u

ROOT=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../../.." && pwd)
SKILL="$ROOT/skills/review-implement/SKILL.md"
INVENTORY="$ROOT/skills/INVENTORY.md"
PASS=0
FAIL=0

assert_file() {
  local label="$1"
  local path="$2"
  if [ -f "$path" ]; then
    printf 'PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf 'FAIL: %s\n' "$label"
    FAIL=$((FAIL + 1))
  fi
}

assert_contains() {
  local label="$1"
  local pattern="$2"
  local path="$3"
  if grep -Fq "$pattern" "$path" 2>/dev/null; then
    printf 'PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf 'FAIL: %s\n' "$label"
    FAIL=$((FAIL + 1))
  fi
}

assert_absent() {
  local label="$1"
  local pattern="$2"
  local path="$3"
  if grep -Fq "$pattern" "$path" 2>/dev/null; then
    printf 'FAIL: %s\n' "$label"
    FAIL=$((FAIL + 1))
  else
    printf 'PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  fi
}

line_for() {
  grep -nFm 1 -- "$1" "$SKILL" 2>/dev/null | cut -d: -f1
}

assert_order() {
  local label="$1"
  local first="$2"
  local second="$3"
  local first_line second_line
  first_line=$(line_for "$first")
  second_line=$(line_for "$second")
  if [ -n "$first_line" ] && [ -n "$second_line" ] && [ "$first_line" -lt "$second_line" ]; then
    printf 'PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf 'FAIL: %s\n' "$label"
    FAIL=$((FAIL + 1))
  fi
}

assert_file "review-implement skill exists" "$SKILL"
assert_contains "skill names review-implement" "name: review-implement" "$SKILL"
assert_contains "skill marks its contract test" "本檔在契約測試底下：bash ~/.claude/skills/review-implement/scripts/tests/review-implement-contract.test.sh" "$SKILL"
assert_contains "description is post-implementation" "post-implementation" "$SKILL"
assert_contains "stage sits before shipping" "final push／PR handback／archiving 前" "$SKILL"
assert_contains "description excludes pre-implementation review" "Do not use for pre-implementation spec review" "$SKILL"
assert_contains "stage asks all axes and skip" "Choose review axes:" "$SKILL"
assert_contains "fixed preface states implement test commit completed" "剛完成 implement、測試與 commit。" "$SKILL"
assert_contains "fixed preface states accepted scope and shrink purpose" "現在要確認實作留在 accepted scope 內，並看看能不能縮小。" "$SKILL"
assert_contains "fixed preface states selected axis behavior" "選 a/all 跑兩軸；選 b/scope 或 c/yagni 跑單軸；選 d/skip 只記 WAIVED，不跑 review。" "$SKILL"
assert_contains "fixed menu maps a to all" "a. all" "$SKILL"
assert_contains "fixed menu maps b to scope" "b. scope" "$SKILL"
assert_contains "fixed menu maps c to yagni" "c. yagni" "$SKILL"
assert_contains "fixed menu maps d to skip" "d. skip" "$SKILL"
assert_contains "letters normalize to semantic axes" "把字母轉成 semantic axis 後再寫 report" "$SKILL"
assert_absent "stage does not use AskUserQuestion" "AskUserQuestion" "$SKILL"
assert_contains "stage waits for top-level answer" "沒有回答就停止，不代選" "$SKILL"
assert_contains "ordinary work recommends scope" '一般 spec-backed work 建議 `scope`' "$SKILL"
assert_contains "long-axis work recommends all" "long-axis signal" "$SKILL"
assert_contains "scope and model stay separate" "先把 Scope／YAGNI 當工作目的、把 model／execution path 當執行選擇" "$SKILL"
assert_contains "matrix uses model rows" "模型／執行路徑為列" "$SKILL"
assert_contains "matrix uses axis columns" "當次適用審查角度為欄" "$SKILL"
assert_contains "matrix includes fable route" '`routed-judge`／`fable`' "$SKILL"
assert_contains "matrix includes opus route" '`routed-judge`／`opus`' "$SKILL"
assert_contains "matrix lists every cell status" '每個 cell 都標 `推薦`、`可選`、`需補材料／工具` 或 `不可用`' "$SKILL"
assert_contains "matrix status is task scoped" "不是固定推薦；每次依本次任務與材料" "$SKILL"
assert_contains "example is not default" "這只是示例，不是預設或能力排名" "$SKILL"
assert_contains "recommendation binding line" 'Recommended seats: <model>/<axis>[, ...]' "$SKILL"
assert_contains "selection accepts natural language" '使用者可用自然語言回「照推薦」' "$SKILL"
assert_contains "selection records seats" "report 記錄 semantic axes 與 selected seats" "$SKILL"
assert_contains "unmentioned seats stay off" "未明說的 seat 不啟動" "$SKILL"
assert_contains "unknown resolved model is explicit" 'resolved model 寫成 `unknown`' "$SKILL"
assert_contains "unavailable cell states reason" "缺 mapping、材料或工具能力的 cell 不派工" "$SKILL"
assert_contains "same axis can use two models" "同一 axis 可選兩個不同 model" "$SKILL"
assert_contains "same-grade premise is not ranking" "同級模型是選用前提，不把名稱或階級寫成量測排名" "$SKILL"
assert_order "preface implement line precedes purpose" "剛完成 implement、測試與 commit。" "現在要確認實作留在 accepted scope 內，並看看能不能縮小。"
assert_order "preface purpose precedes axis behavior" "現在要確認實作留在 accepted scope 內，並看看能不能縮小。" "選 a/all 跑兩軸；選 b/scope 或 c/yagni 跑單軸；選 d/skip 只記 WAIVED，不跑 review。"
assert_order "preface precedes recommendation" "剛完成 implement、測試與 commit。" '一般 spec-backed work 建議 `scope`'
assert_order "recommendation precedes menu" '一般 spec-backed work 建議 `scope`' "Choose review axes:"
assert_contains "stable base sha is required" 'stable `base_sha` 與 `head_sha`' "$SKILL"
assert_contains "skip bypasses target validation" '回答為 `skip` 時直接接第 8 節' "$SKILL"
assert_contains "uncommitted target blocks" "未 commit 的 working tree" "$SKILL"
assert_contains "openspec report path" "openspec/changes/<change>/review-implement.md" "$SKILL"
assert_contains "scratch report path" ".scratch/<feature>/review-implement.md" "$SKILL"
assert_contains "scope reconstructs save resume chain" "save／resume handoff" "$SKILL"
assert_contains "scope follows session IDs and transcripts" "session IDs 與 transcript references" "$SKILL"
assert_contains "scope requires unique edge evidence" "每條 edge 都記錄一個唯一" "$SKILL"
assert_contains "scope missing chain blocks" 'Scope axis 記為 `failed`、Run 記為 `BLOCKED`' "$SKILL"
assert_contains "scope does not guess chain" "不猜 chain" "$SKILL"
assert_contains "scope authority starts with top-level user" "explicit top-level user-authored decision" "$SKILL"
assert_contains "assistant evidence needs acceptance" "後續 top-level user 明確接受後才升為 scope" "$SKILL"
assert_contains "same-level conflict is plausible" '`PLAUSIBLE` scope finding' "$SKILL"
assert_contains "scope packet is raw paths only" "Scope packet 只交 raw-session paths、authority contract 與 stable diff" "$SKILL"
assert_contains "yagni packet has confirmed requirements" "confirmed requirements、acceptance clauses／IDs 與 stable final diff" "$SKILL"
assert_contains "yagni excludes author defense" "作者辯護、implement-author conclusion、前輪 findings" "$SKILL"
assert_contains "yagni findings have diff alternative acceptance" "diff hunk、較小替代方案，以及仍滿足的 acceptance IDs" "$SKILL"
assert_contains "stage separates logical and resolved models" "logical model 與 resolved model 分開記錄" "$SKILL"
assert_contains "reviewer uses routed judge" "subagent_type: \"routed-judge\"" "$SKILL"
assert_contains "reviewer offers fable model" "model: \"fable\"" "$SKILL"
assert_contains "reviewer offers opus selection marker" "<review-implement-selection:v1 model=opus axis=scope>" "$SKILL"
assert_contains "reviewer offers fable selection marker" "<fable-ok> <review-implement-selection:v1 model=fable axis=scope>" "$SKILL"
assert_contains "all selected seats dispatch in parallel" '選 `all` 時平行派出本輪明確選定的 seat' "$SKILL"
assert_contains "model prompts stay isolated" "兩個不同 model 的 prompt 不放對方 output、finding 或結論" "$SKILL"
assert_contains "main waits for all seat results" "等本輪所有 selected seat reviewer results 都回來後才進 Main triage" "$SKILL"
assert_contains "reviewer failure blocks" "Reviewer failure、實際發生的 context overflow" "$SKILL"
assert_contains "no speculative size gate" "不要用 speculative session／byte limit 先拒絕" "$SKILL"
assert_contains "partial seat success is retained" "成功 seat output 仍附在同一 Run" "$SKILL"
assert_contains "retry only failed seat" '只派失敗的 `<model, axis>` seat' "$SKILL"
assert_contains "retry uses fresh stage invocation" 'failed-seat retry 先以新的成功 `Skill(review-implement)` invocation' "$SKILL"
assert_contains "retry reuses matrix and menu" "顯示同一份矩陣與固定選單" "$SKILL"
assert_contains "fixed menu keeps scope alias" "b. scope" "$SKILL"
assert_contains "fixed menu keeps yagni alias" "c. yagni" "$SKILL"
assert_contains "scope finding evidence contract" "session path、event／turn ID、verbatim top-level user quote 與 implementation file:line" "$SKILL"
assert_contains "scope confirmed blocks" '`CONFIRMED` scope finding block completion' "$SKILL"
assert_contains "scope plausible surfaces" '`PLAUSIBLE` scope finding 上呈使用者' "$SKILL"
assert_contains "scope IDs are per run axis IDs" 'Scope finding 用 `S1`、`S2`' "$SKILL"
assert_contains "yagni IDs are per run axis IDs" 'YAGNI finding 用 `Y1`、`Y2`' "$SKILL"
assert_contains "main accepts or disputes yagni" 'Main 對每條做 `accept` 或 `dispute`' "$SKILL"
assert_contains "synthesis uses selected seats only" '合成只使用本輪 selected seats 的 output' "$SKILL"
assert_contains "unselected seats are not completed" "未選 seat 不補成缺席、不寫成完成" "$SKILL"
assert_contains "more than five pauses automation" "待決策列 >5，停止自動處理" "$SKILL"
assert_contains "overview does not hide findings" "不隱藏、刪除或合併到使用者看不到的 finding" "$SKILL"
assert_contains "review is read-only" "Reviewer 與 review-implement 不修改 production code" "$SKILL"
assert_contains "targeted recheck is original IDs only" "只對 accepted 的原始 finding IDs" "$SKILL"
assert_contains "targeted recheck cannot add findings" "targeted recheck 不得新增 finding" "$SKILL"
assert_contains "targeted failure remains blocked" '失敗就維持 `BLOCKED`' "$SKILL"
assert_contains "no automatic full review" "不要在 targeted recheck 後自動開新的 full review" "$SKILL"
assert_contains "single report history" "一個 feature 只使用一份 report" "$SKILL"
assert_contains "append events without rewriting history" "歷史 event 不覆寫" "$SKILL"
assert_contains "report has selected seats" "selected_seats" "$SKILL"
assert_contains "report has logical model list" "logical_models" "$SKILL"
assert_contains "report has resolved model list" "resolved_models" "$SKILL"
assert_contains "report has trial metrics" "session_count" "$SKILL"
assert_contains "report only lists selected seats" "報告只列本輪 selected seats" "$SKILL"
assert_contains "axis statuses are constrained" "scope: completed | failed | waived" "$SKILL"
assert_contains "run statuses are constrained" "Run status: PASS | BLOCKED | WAIVED" "$SKILL"
assert_contains "pass uses selected seats" '每個 selected seat 所屬 axis 都是 `completed`' "$SKILL"
assert_contains "skip is explicit waived" 'explicit `WAIVED` Run event' "$SKILL"
assert_contains "letter d is explicit skip" '使用者選 `skip` 或固定選單的 `d` 時不派 reviewer' "$SKILL"
assert_contains "skip records no seats" '`selected_seats: none`' "$SKILL"
assert_contains "skip cannot claim pass" '不可以宣稱 review `PASS`' "$SKILL"
assert_contains "v1 avoids new control plane" "不新增 Workflow、hook、binary、reducer、manifest、agent definition" "$SKILL"
assert_contains "contract scope avoids deterministic claim" "不宣稱 reviewer reasoning、dedupe 或 status reduction deterministic" "$SKILL"
assert_contains "every finding carries a fixed-shape disposition line" 'disposition: <ID> | <class> | main=<verdict> | user=<verdict> |' "$SKILL"
assert_contains "disposition shape is shared with review-spec" "與 /review-spec 落檔共用同一形狀" "$SKILL"
assert_contains "user verdict vocabulary is fixed" '`accepted`／`dismissed`／`deferred`／`n/a`' "$SKILL"
assert_contains "n/a means main decided without escalating" '`n/a` 代表 Main 自決、沒上呈' "$SKILL"
assert_contains "report reserves a dispositions section" "### Dispositions" "$SKILL"
assert_contains "prior dispositions are read back before dispatch" "派 reviewer 前先讀回同一份 report 既有 Run 的 disposition 行" "$SKILL"
assert_contains "rubber-stamp tally is computed from the record" "連續 2+ 輪有 substantive findings 而 0 條 accepted" "$SKILL"
assert_contains "first run states no prior record rather than clean" "首輪查無前輪 disposition 就明寫查無" "$SKILL"

assert_file "inventory exists" "$INVENTORY"
assert_contains "inventory wires review-implement" "| review-implement" "$INVENTORY"

printf '%s\n' "PASS=$PASS FAIL=$FAIL"
if [ "$FAIL" -ne 0 ]; then
  exit 1
fi
printf '%s\n' 'REVIEW_IMPLEMENT_CONTRACT_ALL_PASS'
