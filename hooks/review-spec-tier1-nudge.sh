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
{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"⚠️ design/spec doc 落檔。進 to-tickets 前先在 response 列文字選單（a) T1 自審 b) T2 單 critic c) T3 雙跑，選後回傳 `/review-spec 3 <本次 file_path 的絕對路徑>` 只有使用者真正送出 command 才執行 d) T4 跨模型 e) 跳過 review、直接進 to-tickets、不再重問 f) YAGNI 軸，模型代寫 spec 建議至少先跑，與 T1–T4 分開執行；選單最後一行固定放 `<review-spec-entry-menu:v1>`）等使用者回覆，詳見 ~/.claude/commands/review-spec.md。"}}
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
{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"plan/tasks 落檔 → best-of-N 候選拍板：挑「解空間寬／碰核心模組／難回滾」task 列文字選單（建議 N 與成本）等拍板；點頭才加 best-of-n 標記，零候選不出聲。"}}
JSON
    ;;
esac
exit 0
