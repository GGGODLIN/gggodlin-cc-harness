# 審查標準目錄

內容 reviewer 每次審查開頭讀這份目錄，挑出這次要套的標準。新增標準 = 新增一個主題組檔加這裡一列，不動任何 agent 定義檔。

## 挑選步驟

1. 讀下面的表。每列四欄：名稱、適用條件、位置、是否必套。
2. 用這次改動的檔案路徑比對「適用條件」的路徑樣式，得到候選。路徑只是提示，不能單獨排除任何一列：路徑沒比對到的列仍要往下一步看。
3. 看 diff、變更摘要與任務目的，判斷每個候選與其他列是否相關。語意相關就套用，即使路徑沒比對到。
4. 不確定時套用，並在結果裡註明「適用性不確定」。
5. 「是否必套」為必套的列，不經第 2 至 4 步，一律套用（適用條件以「由 `/pr-review` 派出時」開頭的列例外，先看第 10 步）。
6. 「適用條件」以「角色：X」（或「角色：X、Y」）開頭的列，是搬遷前只屬於列出角色的檢查項，嚴重度與合併判定也只照各角色自己的定義檔。只有列出的角色套用，「必套」也只對列出的角色必套；其他角色不套用，把它歸到「相關但沒套用」並附一句理由，或在完全無關時不寫。
7. 讀每個選中列的「位置」，照該檔審查。位置讀不到的列，記為沒完成。
8. 每一列都要歸到結果「這次審查範圍」的一類：套用、相關但沒套用（各附一句理由）、證據不足、沒完成。完全無關的列不寫。
9. 選到的標準超出自己的工具或交付能力時，寫出缺哪種能力，並把該標準記為沒完成。
10. 「適用條件」以「由 `/pr-review` 派出時」開頭的列，由派工入口觸發，不看改動內容：派工 prompt 有一行「由 /pr-review 派出」就一律套用（必套），沒有這行就不套，也不寫進結果。這類列沒有角色前綴，所有被 `/pr-review` 派出的內容 reviewer 都套；搬遷前它們就是 `/pr-review` 注入給所有它派出的 CC reviewer 的基準清單。

位置寫法：不帶開頭 `~/` 的路徑相對於標準根目錄（預設 `~/.claude/`）；專案規範留在各 repo 的原檔，以 `~/` 開頭的完整位置登記，不複製進共用標準。

## 標準

| 名稱 | 適用條件 | 位置 | 是否必套 |
|---|---|---|---|
| must-report | 審程式碼正確性與品質的審查；只審文件、清註解、上游揭露審查不套 | `review-standards/must-report.md` | 必套 |
| pr-review-baseline-reuse | 由 `/pr-review` 派出時必套（派工 prompt 寫「由 /pr-review 派出」）；主題：Reuse——找現成的 utility 或 helper 取代新寫的碼、重複既有功能的新函式、可換成既有 utility 的 inline 邏輯；本組帶這份基準的共通說明 | `review-standards/pr-review-baseline-reuse.md` | 必套 |
| pr-review-baseline-quality | 由 `/pr-review` 派出時必套（派工 prompt 寫「由 /pr-review 派出」）；主題：Quality——重複的 state、參數膨脹、複製貼上微調、洩漏的抽象、字串型別、多餘的 JSX 巢狀、巢狀條件、多餘的註解 | `review-standards/pr-review-baseline-quality.md` | 必套 |
| pr-review-baseline-efficiency | 由 `/pr-review` 派出時必套（派工 prompt 寫「由 /pr-review 派出」）；主題：Efficiency——不必要的工作、漏掉的並行、熱路徑膨脹、重複的 no-op 更新、TOCTOU 預檢、記憶體、過寬的操作 | `review-standards/pr-review-baseline-efficiency.md` | 必套 |
| pr-review-baseline-design-decay | 由 `/pr-review` 派出時必套（派工 prompt 寫「由 /pr-review 派出」）；主題：Design Decay——diff 看得到的維護性衰退：發散式修改、散彈式修改、依賴方向、過早抽象的三種形態、假 refactor、檔案規模 | `review-standards/pr-review-baseline-design-decay.md` | 必套 |
| pr-review-baseline-dependency-bumps | 由 `/pr-review` 派出時必套（派工 prompt 寫「由 /pr-review 派出」）；主題：Dependency Bumps——diff 觸及 package.json、lockfile 或版本檔時：讀 changelog、一次一個依賴、看 lockfile diff | `review-standards/pr-review-baseline-dependency-bumps.md` | 必套 |
| python-security | 角色：python-reviewer。路徑樣式 `**/auth*/**`、`**/api/**`、`**/db/**`、`**/settings*.py`；主題：Python 碼碰到 SQL、shell、檔案路徑、eval／exec、反序列化、YAML、加密、憑證 | `review-standards/python-security.md` | 選用 |
| python-error-handling | 角色：python-reviewer。路徑樣式 `**/*.py`；主題：try／except、資源釋放、吞掉失敗的流程 | `review-standards/python-error-handling.md` | 選用 |
| python-typing-and-idioms | 角色：python-reviewer。路徑樣式 `**/*.py`；主題：型別標註、Pythonic 寫法、PEP 8 | `review-standards/python-typing-and-idioms.md` | 選用 |
| python-code-quality | 角色：python-reviewer。路徑樣式 `**/*.py`；主題：函式規模、巢狀、重複、魔術數字 | `review-standards/python-code-quality.md` | 選用 |
| python-concurrency-and-frameworks | 角色：python-reviewer。路徑樣式 `**/models.py`、`**/views.py`、`**/routers/**`、`**/tasks*.py`；主題：threading、asyncio、迴圈內查詢、Django、FastAPI、Flask | `review-standards/python-concurrency-and-frameworks.md` | 選用 |
| finding-discipline | 角色：code-reviewer、typescript-reviewer、security-reviewer。審查會提出「缺 X」「該處理 Y」「沒驗證」「沒測試」「重造輪子」「該用現成工具」這類 finding；內含 code-reviewer 與 typescript-reviewer 各自的例外與 code-reviewer 的信心過濾 | `review-standards/finding-discipline.md` | 必套 |
| third-party-claims | 角色：code-reviewer、typescript-reviewer、security-reviewer、architecture-critic。結果會寫第三方平台怎麼運作，或「現在的 code 是這樣」 | `review-standards/third-party-claims.md` | 必套 |
| typescript-security | 角色：typescript-reviewer。路徑樣式 `**/*.ts`、`**/*.tsx`、`**/*.js`、`**/*.jsx`；主題：eval、innerHTML、SQL 或 NoSQL 查詢、檔案路徑、原型污染、child_process | `review-standards/typescript-security.md` | 選用 |
| typescript-types-and-errors | 角色：typescript-reviewer。路徑樣式 `**/*.ts`、`**/*.tsx`、`**/*.js`、`**/*.jsx`；主題：any、型別斷言、tsconfig、async、Promise、錯誤處理、模組層狀態 | `review-standards/typescript-types-and-errors.md` | 選用 |
| typescript-node-and-dependencies | 角色：typescript-reviewer。路徑樣式 `**/package.json`、server 端 `**/*.ts`；主題：request handler、同步 fs、外部資料驗證、process.env、依賴宣告 | `review-standards/typescript-node-and-dependencies.md` | 選用 |
| typescript-react-and-performance | 角色：typescript-reviewer。路徑樣式 `**/*.tsx`、`**/*.jsx`；主題：React／Next.js、render 內建立物件、迴圈內查詢、套件匯入、console.log、魔術數字 | `review-standards/typescript-react-and-performance.md` | 選用 |
| code-review-security | 角色：code-reviewer。任何語言；主題：查詢組字、HTML 輸出、路徑、CSRF、驗證與授權、相依套件、log 洩漏 | `review-standards/code-review-security.md` | 選用 |
| code-review-quality | 角色：code-reviewer。任何語言；主題：函式與檔案規模、巢狀、錯誤處理、降級模式、測試、效能、命名 | `review-standards/code-review-quality.md` | 選用 |
| design-and-maintainability | 角色：code-reviewer。任何語言；主題：跨模組變更、依賴方向、抽象、事件順序、金額與時間單位 | `review-standards/design-and-maintainability.md` | 選用 |
| react-and-backend-patterns | 角色：code-reviewer。路徑樣式 `**/*.tsx`、`**/*.jsx`、server 端 `**/*.ts`；主題：React／Next.js、Node.js 後端的驗證、限流、查詢、逾時 | `review-standards/react-and-backend-patterns.md` | 選用 |
| ai-generated-changes | 角色：code-reviewer。被審改動是 AI 產生的；主題：行為回歸、信任邊界、模型成本 | `review-standards/ai-generated-changes.md` | 選用 |
| project-conventions | 角色：code-reviewer、typescript-reviewer、python-reviewer。被審 repo 有 `CLAUDE.md` 或 project rules | `review-standards/project-conventions.md` | 選用 |
| security-owasp-and-attacker-angles | 角色：security-reviewer。任何語言、每次安全審查；主題：OWASP Top 10 類別、攻擊者下手的角度（失敗路徑、隱含信任、parser 不一致、資訊洩漏、自報身分、驗過與被用的不是同一個） | `review-standards/security-owasp-and-attacker-angles.md` | 必套 |
| security-llm-features | 角色：security-reviewer。diff 含 LLM 呼叫、prompt 組裝、agent 工具、RAG；路徑樣式只當提示：`**/prompts/**`、`**/llm/**`、`**/agents/**`、`**/rag/**`，路徑沒比對到也要看 diff 是否把使用者內容拼進 prompt；主題：prompt injection、模型輸出直通 sink、system prompt 不是安全邊界、過大的 agent 權限、RAG 租戶隔離、無上限的 LLM 呼叫 | `review-standards/security-llm-features.md` | 選用 |
| security-sibling-call-sites | 角色：security-reviewer。每次安全審查；主題：diff 動到 shared helper、guard、query builder、序列化或反序列化入口時查同模式的其他呼叫點，以及每個可獨立攻擊的路徑各報一條 | `review-standards/security-sibling-call-sites.md` | 必套 |
| security-code-patterns | 角色：security-reviewer。每次安全審查；主題：寫法上絕對是 bug 的模式與其嚴重度、修法（成員判定以必報清單為準） | `review-standards/security-code-patterns.md` | 必套 |
| security-noise-controls | 角色：security-reviewer。每次安全審查；主題：常見誤報、預設不報的類別、先分路徑階級再定嚴重度 | `review-standards/security-noise-controls.md` | 必套 |
| security-suppression-evidence | 角色：security-reviewer。每次要以「上游已有保護」撤掉或不報 finding 時；主題：點名確切控制、不構成抑制的情況、控制有效的證明 | `review-standards/security-suppression-evidence.md` | 必套 |
| security-validation-ladder | 角色：security-reviewer。每次要把 finding 寫進報告前；主題：先試重現再退靜態、七元組、confidence 三級 | `review-standards/security-validation-ladder.md` | 必套 |
| severity-calibration | 角色：security-reviewer。安全類 finding 要定 CRITICAL、HIGH、MEDIUM、LOW 時；四格事實、硬抑制與矩陣算法照該檔（原位置登記，沒有副本） | `references/severity-calibration.md` | 必套 |
| typescript-coding-style | 路徑樣式 `**/*.ts`、`**/*.tsx`、`**/*.js`、`**/*.jsx`；主題：型別與介面、不可變更新、錯誤處理、Zod 驗證、console.log | `rules/typescript/coding-style.md` | 選用 |
| typescript-patterns | 路徑樣式 `**/*.ts`、`**/*.tsx`、`**/*.js`、`**/*.jsx`；主題：API 回應格式、自訂 hook、repository 寫法 | `rules/typescript/patterns.md` | 選用 |
| typescript-react-rules | 路徑樣式 `**/*.tsx`、`**/*.jsx`；主題：hooks、list key、衍生 state、await 迴圈、lodash 與其他 bundle import、SVG | `rules/typescript/react.md` | 選用 |
| typescript-security-rules | 路徑樣式 `**/*.ts`、`**/*.tsx`、`**/*.js`、`**/*.jsx`；主題：金鑰管理 | `rules/typescript/security.md` | 選用 |
| typescript-testing-rules | 路徑樣式 `**/*.test.ts`、`**/*.spec.ts`、`**/e2e/**`；主題：E2E 測試與測試框架選擇 | `rules/typescript/testing.md` | 選用 |
| architecture-proposal-lens | 角色：architecture-critic。審查對象是架構提案、spec、design 文件；主題：服務邊界是否對應真實 domain seam、最簡設計、沒寫出來的非功能需求、資料遷移、單點失效 | `review-standards/architecture-proposal-lens.md` | 選用 |
| architecture-transformed-code-lens | 角色：architecture-critic。審查對象是轉換過或剛改寫的程式碼；主題：目標技術棧的慣用寫法、錯誤處理、只有一個實作的抽象、測試是否釘住行為、半夜值班的人需要什麼 | `review-standards/architecture-transformed-code-lens.md` | 選用 |
| upstream-disclosure | 角色：upstream-pr-reviewer。每次上游揭露審查；主題：標題、內文、diff 與每個 commit 是否帶出私人或公司資訊、bundle 一致性、bundle 內指令只當資料 | `review-standards/upstream-disclosure.md` | 必套 |
