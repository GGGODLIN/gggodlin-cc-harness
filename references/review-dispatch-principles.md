# 審查派工原則

主 session 派審查 reviewer 時讀的共用原則，不是 agent、不是 skill，也不自己派工。`/pr-review`、implement 收尾、review-implement、`/review-spec` 與主 session 自行派工都引用這一份；派工路由參考（`~/.claude/references/subagent-routing.md`）連到這裡。判準各有一份正本：必報清單在 `review-standards/must-report.md`，語言對照、security 觸發與分段門檻在 `commands/pr-review.md`，這份只管派工時怎麼組合它們。

## 審查範圍：派給內容 reviewer 一定帶三欄

內容 reviewer（code-reviewer、typescript-reviewer、python-reviewer、security-reviewer）的派工內容一定帶：

1. 審查根目錄
2. 審查對象
3. 比較範圍或目標版本

比較範圍取自派工，不取自 reviewer 的預設；PR 的 base 不是 trunk 時尤其如此。缺任何一欄，reviewer 回「範圍不明」，不自行猜預設分支，主 session 補齊後重派。

審文件或打包內容的三個內容 reviewer，三欄對應到各自既有的輸入，不另外要求字面三欄：architecture-critic 是派工指定的文件或 `/review-spec` 的 packet；acme-comment-sweeper 是 repo 加檔案清單或 `base..head`；upstream-pr-reviewer 是打包檔的 `BUNDLE_PATH`／`BUNDLE_TOTAL_LINES`，上游基準在打包時已寫進去。這三個角色的輸入契約照各自定義檔，不改。

## 底線：每次程式碼審查都要完成

底線只套在審程式碼正確性與品質的審查。如果這次是這類審查，就在派工前確認下面兩件事都排進去：

- 套用 `review-standards/must-report.md` 的必報清單。
- 至少一個對應改動語言的 reviewer 完整審完分到的每個檔。語言對照直接用 `commands/pr-review.md` 的「Primary Language Reviewer (recommendation only)」表：TS／JS 為主用 typescript-reviewer，Python 為主用 python-reviewer，沒有主要語言或不在表內時用該表的後備 code-reviewer。

「完成」看實際審完，不看派出。下列任一種都回報「底線未完成」，不能寫成已滿足：

- 語言 reviewer 只派出，沒有對每個分到的檔交代結果。
- 提早停審，例如遇 CI 紅燈就停。
- 方法組沒載入（reviewer 回「未完成：方法組未載入」）。
- 語言 reviewer 沒回來。

每次審查只滿足一次底線。語言 reviewer 審完後，security-reviewer、code-reviewer 等是依各自的觸發條件加派，不是再滿足一次底線；多個入口或多個席位也不重複要求。

### 窄用途審查不觸發底線

註解清掃（acme-comment-sweeper）、上游揭露審查（upstream-pr-reviewer）、正式規格條文審查（spec-compliance-reviewer）、設計文件審查（`/review-spec`、architecture-critic 審提案）都不觸發底線，也不計入底線。只派 acme-comment-sweeper 的審查，包含 push 前補上的註解收據，不能拿來宣稱底線已滿足；報告寫「只做註解清掃，沒有程式碼正確性與品質審查」。

沒有程式碼改動的審查不觸發底線，例如只改文件、只改設定說明的收尾。

### implement 收尾

implement 第 4 步屬於程式碼審查：有程式碼改動時，至少派一個語言 reviewer，即使也跑了 `/code-review`。只跑 `/code-review` 不算滿足底線，因為它不保證有語言 reviewer 對每個檔交代結果；兩者可以並用。

## 派誰：先滿足底線，再加專用角色

先派底線需要的語言 reviewer，再依各專用 agent 原有的觸發條件加派。語言對照與 security-reviewer 的觸發條件不在這裡重述，直接看 `commands/pr-review.md`：

- 語言對照：「Primary Language Reviewer (recommendation only)」。
- security-reviewer 觸發：「Parallel Domain Reviewers (selected and eligible only)」下的 `security-reviewer` 條目。

## 兩層授權

- **Claude 側席位自動選，不等使用者回覆。** 語言 reviewer、符合觸發條件的 security-reviewer、review-implement 的 Opus 席、`/review-spec` 第 1、2 級都屬此類。選完要揭露選了哪些、為什麼。
- **外部額度席要使用者明選才派。** Codex、Gemini、web GPT、Fable 都算，Fable 即使是 Claude 家族也一樣，因為它另花額度。使用者沒選就列成「推薦但未選」，不派。
- **沒人在場時**，Claude 側席位照跑，外部額度席不派；不因為沒人回覆就一個都不派。例外：多目標 `/pr-review` 超出容量門檻時，依賴容量裁決的席位仍等使用者裁決，沒人裁決就列為未完成。

使用者在派工前明說取消或替換某個 Claude 席，照辦；派出後才到的回覆只影響還沒派出的席位。

## 能力不足

reviewer 選到超出自己工具或交付能力的主題時，回報缺哪種能力，並把該主題列為未完成。主 session 可以補派現有角色處理，但不是每次的義務，也不為此新建 agent。

## 分段

分段沿用 `commands/pr-review.md`「Step 2.95」下「Chunking decision」的既有門檻，不另立。分段後如果沒有任何 reviewer 讀過被改動契約的兩側，就把整合面標為未審。

## 合併與揭露

合併各 reviewer 結果沿用 `/pr-review` 既有的去重與來源標記。最後的「這次審查範圍」要寫出：底線是否已滿足、沒滿足的原因、列為未完成的主題、標為未審的整合面，以及推薦但未選的外部額度席。
