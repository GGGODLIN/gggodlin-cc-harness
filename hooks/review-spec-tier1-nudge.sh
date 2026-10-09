#!/usr/bin/env bash
# PostToolUse(Write|Edit) nudge: 當 local design/spec doc 落檔，
# 在 response 用文字選單讓使用者選 review-spec Tier 1-4（2026-07-02 改：原本直接餵 T1 指令、
# 導致 CC 幾乎永遠停在 T1（13:3）；改成使用者主動拍板 Tier）。
# 盯輸出路徑、不修改 review-spec command。
# 對應 command: ~/.claude/commands/review-spec.md
# 本機 spec 路徑：openspec/changes/<change>/design.md 或 .scratch/<feature>/spec.md。
# 2026-07-10: AskUserQuestion 已 deny（2026-07-05 settings.json permissions.deny）、
# 兩個 nudge 都改成 response 文字選單，比照 feedback_no_askuserquestion_inline_options_instead 慣例。
set -euo pipefail

input=$(cat)
file_path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // ""' 2>/dev/null || echo "")

case "$file_path" in
  *openspec/changes/*/design.md|*/.scratch/*/spec.md)
    cat <<'JSON'
{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"⚠️ design/spec doc 落檔。進 to-tickets 前先提議 review-spec；使用者可跳過並直接繼續。不要自己默認 T1：在 response 用文字列選單（a/b/c/d/e/f 選項）讓使用者選——a) T1 唱反調自審（in-context 零成本）b) T2 單 architecture-critic（fresh-context）c) T3 多 lens Opus＋Fable 雙跑 + synthesize（需原生 Claude、最多 8 路）d) T4 外部跨模型（codex + agy）e) 跳過 review、直接進 to-tickets f) YAGNI 軸（模型代寫 spec 建議至少先跑；審值不值得，與 T1–T4 分開執行）。每個選項附一行「什麼時候選」的差異，並依這份 spec 的複雜度（改幾檔 / 動不動核心架構 / 碰不碰生產資料）在建議的選項標（建議）。選單最後一行固定放 `<review-spec-entry-menu:v1>`（YAGNI 入口標記：使用者緊接著回 f，Fable 許可就把它當成親手輸入 /review-spec yagni）。列完選單就結束回合等使用者回覆、不要代選。使用者選 a／b／d 後照 ~/.claude/commands/review-spec.md 該 Tier 執行；選 c 後回傳可貼上的 `/review-spec 3 <本次 file_path 的絕對路徑>` 並停止該輪，只有使用者真正送出 command 才執行；選 e 後直接繼續 to-tickets、不再重問；選 f 後照 ~/.claude/commands/review-spec.md 的 YAGNI 軸執行，完成後再由使用者決定是否跑 Tier review 或進 to-tickets；T1 三問與呈現紀律都在該檔。"}}
JSON
    ;;
  *openspec/changes/*/tasks.md)
    # 2026-06-12 加：plan/tasks 落檔 → best-of-N 候選拍板 nudge（借鑑 MiMoCode Max Mode）。
    # 2026-07-08：micro YAGNI 掃描 nudge（ponytail Gate A）已 kill——trial 14 天 16 次 fire、0 次 read-through，見 trials/archived.md。
    # Guard：plan 內 stamp `best-of-n` 後本 hook 不再 fire。
    edited_content=$(printf '%s' "$input" | jq -r '(.tool_input.new_string // .tool_input.content) // ""' 2>/dev/null || echo "")
    if printf '%s' "$edited_content" | grep -qi 'best-of-n'; then
      exit 0
    fi
    cat <<'JSON'
{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"plan/tasks 落檔 → **best-of-N 候選拍板**（高風險 task 平行多解選優）：掃 task 清單找 best-of-N 候選——只挑「解空間寬 / 碰核心模組 / 難回滾」的實作 task，多數 plan 沒有候選是正常的。有候選 → 在 response 用文字列出候選（task + 建議 N 值 + 預估 token 成本、約 N 倍單 task），結束回合等使用者拍板；使用者點頭的才在 plan 該 task 加一行標記「best-of-N: invoke Workflow {name: best-of-n-implement, args: {task: <完整 task 描述含驗收標準>, n: <N>, testCmd: <測試指令>}}，勝者 diff 由 main git apply 後重跑測試」。沒點頭不標、零候選不出聲、執行階段照標記辦事不自行加碼。Guard：plan 內 stamp `best-of-n` 後本 hook 不再 fire。"}}
JSON
    ;;
esac
exit 0
