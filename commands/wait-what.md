---
description: 手動修復鍵：使用者剛剛沒跟上時打 /wait-what，要求補脈絡並用繁中白話重講。僅使用者手動觸發，agent 不得自行 invoke。
disable-model-invocation: true
---
<!-- 本檔在契約測試底下：bash ~/.claude/commands/tests/wait-what-contract.test.sh -->

等等——我剛剛那段沒跟上。重新講一次讓我跟丟的部分，範圍你自己判斷（讓我跟丟的通常不只上一則訊息）：

- 先一句人話講結論，再補上我缺的前提與來龍去脈
- 重講＝從頭敘事：先講這個 session 在幹嘛、每個內部代號（trial 名／event N／考題 N）是什麼，再進正題——不是把上一則再壓縮；出現內部代號就附一句它是什麼
- 先判斷這題**有沒有形狀**：呼叫關係→call tree、檔案職責→淺層 file tree、邏輯或狀態流→pseudocode、什麼變了→diff（`+`/`-` 不限 code，樹狀結構都能套）。有形狀就形狀先行、散文只補「為什麼」——順序與方向（誰先誰後、誰讀誰寫）散文裝不下。四類都不沾就是沒形狀，照舊散文
- 繁體中文白話；技術術語首次出現附一句白話註解；能翻成中文的英文詞就翻。借用 ASD-STE100 的清晰表達原則，不宣稱符合英文標準：寫清楚誰做什麼，同一概念沿用同一名稱，條件影響動作或結論時先寫條件。
- 目標是更短**而且**更清楚——只砍字不補前提等於沒重講；連續被叫兩次也不准退化成電報式短句。保留必要條件、例外與不確定性；不要把建議改成必要條件，也不要把「可能」改成「一定」。
- 用**我的詞**重講：沿用我在這次對話用過的說法、這個 repo 的 `openspec/glossary.md`、與我的個人語彙表 `~/.claude/glossary.md`（存在就以它們為準），不要把我的詞換成你的同義詞或 LLM 慣用語
- 重講若把模型詞換成了我的詞，末尾列出替換對、問一句要不要記入語彙表（repo 領域詞 → `openspec/glossary.md`、跨專案個人用語 → `~/.claude/glossary.md`）；我點頭才寫
- 回傳前自查三題：結論在前兩行？有沒有一句塞兩個意思？術語都有白話註解？任一沒過，改完才回
- 重講完，把「這次讓我跟丟的原因」照 `~/.claude/friction/PROTOCOL.md` 記一行到 `~/.claude/friction/workflow-general.md` 第一個 `## 待折` 段的最後一個項目之後（不是檔尾；寫在 `## 已折／已否決` 之後的行 hook 數不到）；owning skill 可辨識時改記到 `~/.claude/skills/<name>/friction-log.md` 的待折段。固定用 `signal_type=user-correction`；`CLAUDE_CODE_SESSION_ID` 與 owning skill 可取得時分別寫入 `source_ref=session:<id>#<turn>`、`target=skill:<name>`，否則照協議填 fallback。敘事與 `why` 只寫改寫後的原因＋影響＋建議方向，不搬 user 原話、log、error 或 code；`feedback_quote` 只留必要的短 sanitized excerpt，候選 flag 只 annotation、不影響 append

## 踩過的坑

- 2026-08-06 建檔：不加 Self-Verify（純對話重講、無結構化 output 可對表）。本檔刻意極簡——對抗「講不清楚」的指令自己越寫越長就輸了（mattpocock/skills wait-what 設計論點）；補坑每次最多一行、不新增章節
