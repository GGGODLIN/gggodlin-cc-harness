# claude-harness（治理部分的公開版）

https://github.com/user-attachments/assets/0421df31-50ee-447b-a314-a471e8e156a3

## English summary

This repository is the governance part of one person's Claude Code harness: always-on rules (`CLAUDE.md`, `rules/`), hooks that enforce some of those rules mechanically, the skills, commands and agents that the workflow depends on, and the systems around them — a memory system, a trial (observation period) ledger, a friction log, a daily local analysis report, `cc-session-index` (`ccsi`, an FTS5 trigram session transcript indexer), and `compact-guard`, which keeps evidence across context compaction. Personal customisation (status line, personal tools, blog pipeline, account and browser setup) is not included.

The rules are written in Traditional Chinese and are not translated. If you want them in another language or in your own style, ask Claude to translate or rewrite the files you pick.

It is a reference, not a product. You can install single pieces, but nothing guarantees the whole set runs on your machine. Places where the owner's private wiring was removed are marked in place and listed in `WIRING.md`. Issues are welcome, with no promise of a response. Pull requests are not accepted: this repository is regenerated from a private source on every publish, so a merged pull request would be overwritten by the next export. If you have an improvement, open an issue that describes it.

## 這是什麼

一份個人 Claude Code 設定裡「治理」那一半的公開版。包含：

- 常駐規則：`CLAUDE.md`、`rules/`、`output-styles/`，以及規則引用的 `references/`。
- hook：把部分規則從「靠模型自律」改成機械檢查，註冊寫在 `settings.json`。
- skill、command、agent 與審查標準：規劃、實作、審查、查證這條工作流用到的部分，以及按變更條件載入的 34 份審查標準（`review-standards/`）。
- 四套制度：memory（跨 session 記憶）、wiki（收斂後的知識條目）、trial（新工具與新機制的觀察期帳本）、摩擦紀錄（卡住、繞路、規則沒被遵守的事件）。四套都只公開機制，內容換成 `examples/` 裡的虛構範例。
- daily-local：每天跑一次的本機分析報告，掃規則用量、摩擦、壞掉的路徑等，程式在 `social-info/` 與 `cc-skill-doctor/`。
- cc-session-index（`ccsi`）：對 Claude Code、Codex 與 Pi 的 `.jsonl` 對話紀錄建 SQLite FTS5 `trigram` 全文索引與正規化事件流，在 `cc-session-index/`（獨立 repo 見 [`example-owner/cc-session-index`](https://github.com/example-owner/cc-session-index)）。
- compact-guard：context 壓縮前存一份可稽核的 checkpoint，壓縮後把原始對話證據注回來，含 Codex 支援，在 `compact-guard/`。

不包含：個人客製化（statusline、個人工具串接、部落格產線、帳號與瀏覽器的具體接法）、公司相關的治理、能力型 skill（畫圖、簡報之類），以及 memory、wiki、trial、摩擦紀錄的實際內容。

## 從哪裡開始

| 你想做的事 | 先看 |
|---|---|
| 已經有自己的 Claude Code 設定，想讓 agent 守紀律 | [`skills/gate-authoring/SKILL.md`](/skills/gate-authoring/SKILL.md)、[`rules/common/dispatch-and-verify.md`](/rules/common/dispatch-and-verify.md)、[`friction/PROTOCOL.md`](/friction/PROTOCOL.md) 與 [`examples/trials/`](/examples/trials/) |
| 想挑一個完整的工具來試 | [`cc-session-index/README.md`](/cc-session-index/README.md)（單一 Python 檔對話索引）或 [`compact-guard/README.md`](/compact-guard/README.md)：有完整程式與測試，可以單獨安裝 |
| 想看大型機制與工作流怎麼咬合（附寬版 SVG 架構圖） | 下方「核心機制與大型 Skill 圖解導覽」表格，點進各機制的圖解檔即可看完整三階段流程 |
| 想研究 agent 治理、人工授權與出錯後怎麼恢復 | 下面的「設計原則」「已知風險」，以及 [`rules/common/git-workflow.md`](/rules/common/git-workflow.md) |
| 想幾分鐘內裝好整套 | 目前做不到：路徑寫死、接線要自己補。單一元件看 [`install/`](/install/) 與下方「怎麼讓你的 Claude Code 幫你挑選與改裝」 |

## 核心機制與大型 Skill 圖解導覽

這座 repo 最複雜的 10 個機制都附有同層的寬版 SVG 運作流程圖、摺疊 Mermaid 結構原始碼與隨附元件對照表（Skill 直接放在該目錄的 `README.md`，點進資料夾就會在 GitHub 網頁下方自動展開；Command 放在同層的 `.overview.md`）：

| 機制／Skill | 解決什麼問題 | 圖解導覽（含 SVG 流程圖） | 規範正本 |
|---|---|---|---|
| **`/pr-review`** | 多目標／分支隔離 worktree、自動選 Claude 側審查席、雙閘門守衛（派工授權＋報告寫入）與跨模型比較報告 | [`commands/pr-review.overview.md`](/commands/pr-review.overview.md) | [`commands/pr-review.md`](/commands/pr-review.md) |
| **`implement`** | 按依賴圖逐批跑完票券、強制對齊 TDD 決策清單（`matt-tdd-gate`），收尾串起全套測試、跨軸審查與架構視覺核對 | [`skills/implement/README.md`](/skills/implement/README.md) | [`skills/implement/SKILL.md`](/skills/implement/SKILL.md) |
| **`agent-dispatch`** | 經 Herdr 在隔離 worktree 啟動完整終端 worker（Claude Code／Codex CLI／pi），由主 session 負責同意門檻、背景監看與收工對帳 | [`skills/agent-dispatch/README.md`](/skills/agent-dispatch/README.md) | [`skills/agent-dispatch/SKILL.md`](/skills/agent-dispatch/SKILL.md) |
| **`research-before-answer`** | 回答前先分流最新外部事實與個人歷史，強制雙軌搜尋與第一手查證，並在交付前通過 R1–R3 自查 | [`skills/research-before-answer/README.md`](/skills/research-before-answer/README.md) | [`skills/research-before-answer/SKILL.md`](/skills/research-before-answer/SKILL.md) |
| **`skill-creator`** | 撰寫與修改 skill／command 的單一規範來源：三層漸進揭露設計，加上新鮮 subagent 的 `RED → GREEN → REFACTOR` 行為實測 | [`skills/skill-creator/README.md`](/skills/skill-creator/README.md) | [`skills/skill-creator/SKILL.md`](/skills/skill-creator/SKILL.md) |
| **`model-onboard`** | 把第三方模型接進本機模型池，用五階段（WIRE → SMOKE 三態 → BENCH → LIVE → 回歸關卡）分離環境限流與模型能力 | [`skills/model-onboard/README.md`](/skills/model-onboard/README.md) | [`skills/model-onboard/SKILL.md`](/skills/model-onboard/SKILL.md) |
| **`/review-spec`** | 規格進入實作前的第 1–4 級對抗式審查與 YAGNI（砍過度設計）需求定價，強制隔離作者辯護理由並一次收斂拍板表 | [`commands/review-spec.overview.md`](/commands/review-spec.overview.md) | [`commands/review-spec.md`](/commands/review-spec.md) |
| **`/advisor`** | 不切換主 session 模型，把單次架構取捨或盲審打包交給 Fable、網頁版 GPT Pro 或 Codex CLI，收回獨立意見與差異對照 | [`commands/advisor.overview.md`](/commands/advisor.overview.md) | [`commands/advisor.md`](/commands/advisor.md) |
| **`/trial-review`** | 統一盤點 7 天觀察期到期的工具／hook 與累積達門檻的摩擦帳本，用真實行為證據與事件歸因封包決定留、改或撤 | [`folder-level/.claude/commands/trial-review.overview.md`](/folder-level/.claude/commands/trial-review.overview.md) | [`folder-level/.claude/commands/trial-review.md`](/folder-level/.claude/commands/trial-review.md) |
| **`local-analysis`（`/daily-local`）** | 每日與每週自動掃描 30 個治理頻道（規則退化、摩擦、記憶審計、證據層級抽樣），對帳後產出優先度 Digest | [`install/workflows/local-analysis.js.md`](/install/workflows/local-analysis.js.md) | [`workflows/local-analysis.js`](/workflows/local-analysis.js) |

## 元件分類地圖（依採用門檻挑選）

如果你想挑單一機制裝進自己的 `~/.claude`，建議按下面的依賴門檻由淺入深挑選（每個 hook 的具體安裝步驟與必備隨附檔案都在 [`install/`](/install/)）：

1. **零外部依賴、單純擋誤操作或補提醒的入門 Hook**（只需 Bash／Python 3，不需本地模型池或特殊服務）：
   - 防止 `cd && git ...` 污染後續工作目錄：[`install/hooks/cd-cwd-persistence-nudge.sh.md`](/install/hooks/cd-cwd-persistence-nudge.sh.md)
   - 攔截 zsh 下誤用 `$PIPESTATUS`：[`install/hooks/pipestatus-zsh-gate.py.md`](/install/hooks/pipestatus-zsh-gate.py.md)
   - 連續重跑同一驗證指令時提醒換角度：[`install/hooks/repeat-verify-reminder.sh.md`](/install/hooks/repeat-verify-reminder.sh.md)
   - 攔截重複的 `TaskOutput` 輪詢：[`install/hooks/taskoutput-dedup-hook.py.md`](/install/hooks/taskoutput-dedup-hook.py.md)
   - 修改規則或新增 hook 時提醒對齊治理規範：[`install/hooks/gate-authoring-nudge.sh.md`](/install/hooks/gate-authoring-nudge.sh.md)、[`install/hooks/skill-description-gate.sh.md`](/install/hooks/skill-description-gate.sh.md)
2. **規劃 → 實作 → 審查工作流組**（適合整組借鑑流程設計）：
   - 釐清模糊意圖與探索邊界：[`skills/align-intent/`](/skills/align-intent/SKILL.md) → [`skills/grill-me/`](/skills/grill-me/SKILL.md) → [`skills/wayfinder/`](/skills/wayfinder/SKILL.md)
   - 規格撰寫、審查與拆票：[`skills/to-spec/`](/skills/to-spec/SKILL.md) → [`commands/review-spec.md`](/commands/review-spec.md) → [`skills/to-tickets/`](/skills/to-tickets/SKILL.md)
   - 實作、TDD 守門與收尾審查：[`skills/implement/`](/skills/implement/README.md) ＋ [`install/hooks/matt-tdd-gate.sh.md`](/install/hooks/matt-tdd-gate.sh.md) → [`skills/review-implement/`](/skills/review-implement/SKILL.md) → [`commands/pr-review.md`](/commands/pr-review.md)（搭配 [`review-standards/`](/review-standards/catalog.md)）
3. **宣稱證據與模型路由守門組**（部分需接 [`WIRING.md`](/WIRING.md) 的跨模型後端或判官 API）：
   - 宣稱詞本地偵測與證據層級判官：[`install/hooks/T1-claim-detect-local-first.sh.md`](/install/hooks/T1-claim-detect-local-first.sh.md)、[`install/hooks/T1-evidence-level-detect.sh.md`](/install/hooks/T1-evidence-level-detect.sh.md)
   - Subagent 路由與高單價模型守門：[`references/subagent-routing.md`](/references/subagent-routing.md)、[`install/hooks/T2-routing-gate.sh.md`](/install/hooks/T2-routing-gate.sh.md)、[`install/hooks/fable-gate.sh.md`](/install/hooks/fable-gate.sh.md)
4. **四大回饋帳本與跨壓縮守衛**：
   - 跨 session 兩層記憶提醒（背景小模型判官＋手動收尾檢查點）：[`install/hooks/auto-memory-jev.py.md`](/install/hooks/auto-memory-jev.py.md)、[`install/hooks/checkpoint-judge.sh.md`](/install/hooks/checkpoint-judge.sh.md)、[`examples/memory/`](/examples/memory/)
   - 跨 session 歷史對話全文檢索與正規化事件流：[`cc-session-index/README.zh-TW.md`](/cc-session-index/README.zh-TW.md)（可獨立安裝）
   - 壓縮前後保留原始證據：[`compact-guard/README.md`](/compact-guard/README.md)（可獨立安裝）
   - 觀察期帳本、摩擦協議與失敗模式分類表：[`examples/trials/`](/examples/trials/)、[`friction/PROTOCOL.md`](/friction/PROTOCOL.md)、[`references/failure-mode-taxonomy.md`](/references/failure-mode-taxonomy.md)、[`install/hooks/ledger-bootstrap.sh.md`](/install/hooks/ledger-bootstrap.sh.md)

## 怎麼讓你的 Claude Code 幫你挑選與改裝

因為這座 repo 的路徑與接線是照原作者環境寫的，最省力的方式是 clone 下來後，請你自己的 Claude Code 照下面順序幫你評估與移植：

1. **先讓 agent 讀導覽與風險邊界**：請它先讀本檔（[`README.md`](/README.md)）的「已知風險」「元件分類地圖」與 [`WIRING.md`](/WIRING.md)。
2. **挑定單一元件後，必讀對應的 `install/` 說明**：例如想裝某支 hook，請 agent 先讀 `install/hooks/<名稱>.md`，確認列出的「隨附檔案」（設定 JSON、helper 腳本、契約測試）有哪些，連同隨附檔案一起複製，不要只抄單一 `.sh` 或 `.py`。
3. **請 agent 檢查並替換三類環境綁定**：
   - **寫死的目錄結構**：例如 `~/Desktop/work/`（公司 repo）與 `~/Desktop/projects/`（個人 repo）、`~/code/social-info` 等路徑，請 agent 改成你機器上的實際路徑。
   - **🔌 接線點替身**：凡是檔案內標有 `🔌` 或執行時報出 `WIRING.md` 的段落，請 agent 對照 [`WIRING.md`](/WIRING.md) 裡的「需提供的介面」，換成你自己的 CLI／MCP 工具，或把該選用分支裁掉。
   - **跑隨附契約測試確認移植結果**：多數 hook、script 與 skill 在同目錄或 `commands/tests/`、`skills/*/scripts/tests/` 附有 `.test.sh`／`.test.py`／`.test.mjs`，改完後直接跑對應測試確認沒有漏拷檔案。

## 設計原則

- **決策歸使用者，觸發歸機制。** 該不該做由人拍板；什麼時候提醒、什麼時候擋下，交給 hook 與排程，不靠模型記得。
- **宣稱要附證據。** 說「做完了」「全部」「會擋」時，同一句附上指令與輸出；附不出來就把話縮小到實際驗過的範圍。
- **能用機制強制的，不靠自律。** 規則寫在文字裡容易被忽略，重要的會配一支 hook；hook 擋不住的情況也寫明。
- **先查再問，問就一次問完。** 查得到的事實自己查；只有會改變範圍、權威、對外行為或風險的事才停下來問。
- **新東西先進觀察期。** 新工具、新 hook 先登記 trial 並排 review 日，到期用真實使用紀錄決定留或撤；摩擦事件先記下來，累積到門檻再一起處理。

這些原則是大部分規則的「為什麼」，所以規則本身不逐條補理由。

## 採用前要知道的

- 不保證整套能跑：裡面的路徑、工具與排程是照原作者的機器寫的，被拿掉的接線要自己接。
- issue 歡迎開，但不保證回應或修正。
- 不收 pull request。公開版每次發布都由私人版整份重建，直接改這裡的檔案會在下次匯出時被蓋掉；想貢獻改法，請開 issue 描述。
- 授權：自寫內容用 MIT（見 `LICENSE`）；來自上游的檔案保留原授權與署名，列在 `THIRD_PARTY_NOTICES.md`。`skills/mutation-testing` 含 Business Source License 1.1 的內容，不屬 MIT。

## 已知風險：照抄前先讀

下面幾個檔案在原作者的環境裡這樣運作，換到別人的機器上可能出事。照用之前先讀過原檔。

- `commands/pr-review.md`：審查時暫時改 `~/.codex/config.toml`，用固定名稱的 `.pr-review-bak` 備份，結束時整份還原。中途被打斷，或之後又跑一次，這段期間你自己加進該設定檔的內容會被舊備份蓋掉。
- `commands/pr-review.md`：用 `git worktree remove --force` 移除審查用的 worktree，建立新的之前也會先移除。那個 worktree 裡尚未 commit 或未追蹤的檔案會一併刪掉。
- `commands/pr-review.md`：變更含 JSX／TSX 時，在審查席位確認之前就先跑 `npx -y react-doctor@latest`。就算你沒選那個角度，也會下載並執行第三方套件。
- `skills/model-onboard/references/regress-gate.md`：用前後各一次 `ls -A ~` 的差異判斷「家目錄多出的新檔」並清掉。這段期間別人（或別的程式）在家目錄建立的檔案，可能被一起刪掉。
- `commands/self-closeout.md`：靠資料夾位置判斷是公司 repo 還是個人 repo，位置規則是照原作者的目錄配置寫的；個人 repo 會自動 commit 並 push，push 被拒時還會合併後重試。目錄配置不同的人，可能把公司 repo 推出去。
- `commands/session-monitor.md`：用 `pkill -f session-limit-watch.sh` 停掉監看程序，同一台機器上其他 session 的監看程序也會一起被殺。
- `commands/workflow-monitor.md`：同一個 runId 暫停兩次時，journal 與 transcript 的 GOLDEN 備份可能來自不同次暫停；失敗還原時會把較新的 journal 配上較舊的 transcript。
- `skills/check-my-stack/SKILL.md`：把「有安裝指令、也有本機輸入」的工具判成 `Runnable now`，並照指示直接安裝、執行（先做安裝前快照），沒有另外徵求同意。評估一個工具的過程可能因此執行第三方程式。
- `social-info/scripts/local-analysis/recap-daily.sh`：內嵌的分析提示要 agent 用 `xargs -I{} sh -c 'cd {} && pwd -P'` 掃描各個 repo 目錄。目錄名稱會被直接拼進 shell 指令；掃描範圍內如果有名稱含 `$()` 或反引號的資料夾，就會執行其中的指令。只在你信任的目錄樹上跑。
- `social-info/scripts/local-analysis/agnix-daily.sh`：以 `npm_config_ignore_scripts=false npx -y "agnix@$AGNIX_VERSION"` 執行，會蓋掉你自己設定的 `ignore-scripts`，讓該套件的安裝腳本照跑。如果你刻意關掉 npm 的安裝腳本，這支排程會繞過那個保護。
- `social-info/scripts/local-analysis/skill-trigger-health.py`：讀登記檔失敗（檔案讀不到或 JSON 壞掉）時當成空登記檔處理，接著把結果寫回原路徑。你手動標過 `decided: true` 的項目會因此被重設。跑之前先備份登記檔。
- `social-info/scripts/local-analysis/rules-size-weekly.sh`：「零使用規則候選」那一段要呼叫同目錄的 `session-audit.py`，這支沒有公開。少了它，週報只會多一行「零使用清單產生失敗」，其他段落照常產生；要這段功能就得自己接一支輸出同樣格式的程式。

## 目錄怎麼對應

目錄的排法對應原作者的 `~/.claude`：`hooks/`、`rules/`、`skills/` 等目錄放進 `~/.claude` 底下就是原本的位置，`settings.json` 裡的 hook 指令也照這個位置寫。例外：

- `folder-level/` 是放在「專案資料夾根目錄」那一層的設定（原作者的是 `~/Desktop/projects/`），trial 帳本與摩擦機制的 hook 在這裡。
- `social-info/` 與 `cc-skill-doctor/` 是 daily-local 的程式；原作者把它們放在 `~/code/social-info` 與 `~/Desktop/projects/cc-skill-doctor`，程式裡的路徑照那樣寫，換位置時要一起改。
- `cc-session-index/` 的 `ccsi` 執行檔建議連到 `~/.local/bin/ccsi`（見 [`install/cc-session-index/ccsi.md`](/install/cc-session-index/ccsi.md)）。
- `compact-guard/` 照 `~/.claude/compact-guard` 的位置寫進 hook 註冊。
- `install/` 是各機制的安裝說明。
- `examples/` 是 memory、wiki、trial 帳本、摩擦紀錄的虛構範例，只示範格式。

## 被拿掉的接線（🔌）

原作者的私人接線在這些地方被拿掉了。文件裡會留一整行以「🔌 接線點」開頭、指向 WIRING.md 的記號；程式裡被拿掉的呼叫換成替身，一執行就在 stderr 報出接線點名稱並以非零狀態結束，不會默默略過。要用那個功能，請照 `WIRING.md` 自己接。

`WIRING.md` 列出每個接線點用到的元件、需要你提供的介面，以及原作者用的工具。標「僅定義介面」的是灰色路徑（要靠登入 cookie、網頁版內部介面、非官方鏡像或第三方轉接才拿得到的端點），只寫介面，不推薦工具。這次的接線點：

- 🔌 [ChatGPT 網頁版席位](WIRING.md#chatgpt-網頁版席位) — 僅定義介面（interface only），實作請自行提供
- 🔌 [E2E 測試服務](WIRING.md#e2e-測試服務) — 推薦工具：TesterArmy（tester-army/e2e：官方 skill 加 e2e 框架）
- 🔌 [workflow-monitor 後端轉接](WIRING.md#workflow-monitor-後端轉接) — 推薦工具：自己寫一支 case 分支的 shell 腳本（原作者的版本含灰色中轉站分支，未公開）
- 🔌 [中轉站](WIRING.md#中轉站) — 僅定義介面（interface only），實作請自行提供
- 🔌 [全機文件定位](WIRING.md#全機文件定位) — 推薦工具：DigUp（原作者試用中，用一支小 wrapper 包起來、掃描範圍由私人設定檔決定，兩者未公開；不是強依賴，規則其餘路由不靠它）
- 🔌 [多帳號與帳號判定](WIRING.md#多帳號與帳號判定) — 推薦工具：自己寫一支小 shell 函式庫
- 🔌 [後端標記 CC_VENDOR](WIRING.md#後端標記-cc_vendor) — 推薦工具：自己的 shell launcher（原作者用一組 `ccp-*` 函式，未公開）
- 🔌 [架構圖產生與審批](WIRING.md#架構圖產生與審批) — 推薦工具：Archify（產圖）＋ Plannotator（瀏覽器審批）
- 🔌 [瀏覽器自動化](WIRING.md#瀏覽器自動化) — 推薦工具：LCU MCP（工具名 `mcp__lcu__js`）；console、network、效能等診斷另用 chrome-devtools MCP
- 🔌 [程式碼搜尋](WIRING.md#程式碼搜尋) — 推薦工具：semble（MinishLab/semble）
- 🔌 [終端後端](WIRING.md#終端後端) — 推薦工具：Herdr
- 🔌 [跨模型後端](WIRING.md#跨模型後端) — 推薦工具：Magpie 或 CLIProxyAPI（本機多模型代理端點，可選擇搭配 LiteLLM proxy）；第二意見席位用 Codex CLI 與 openai/codex-plugin-cc
- 🔌 [非官方內容抓取](WIRING.md#非官方內容抓取) — 僅定義介面（interface only），實作請自行提供
- 🔌 [額度資料來源](WIRING.md#額度資料來源) — 僅定義介面（interface only），實作請自行提供

## 完整目錄

- [`CHANGELOG.md`](CHANGELOG.md)
- [`CLAUDE.md`](CLAUDE.md)
- [`LICENSE`](LICENSE)
- [`README.md`](README.md)
- [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)
- [`WIRING.md`](WIRING.md)
- [`agents/`](agents/) — 33 個檔案；內含 `advisor-seat.md`、`architecture-critic.md`、`architecture-critic.md.LICENSE`、`code-reviewer.md`、`code-reviewer.md.LICENSE`、`deep-explore.md`、`docs-lookup.md`、`docs-lookup.md.LICENSE`…（共 30 項）
- [`cc-session-index/`](cc-session-index/) — 5 個檔案；內含 `LICENSE`、`README.md`、`README.zh-TW.md`、`ccsi`、`test_ccsi.py`
- [`cc-skill-doctor/`](cc-skill-doctor/) — 2 個檔案；內含 `scripts/`
- [`commands/`](commands/) — 64 個檔案；內含 `advisor-flow.svg`、`advisor.md`、`advisor.overview.md`、`aside.md`、`aside.md.LICENSE`、`daily-local.md`、`docs.md`、`docs.md.LICENSE`…（共 39 項）
- [`compact-guard/`](compact-guard/) — 23 個檔案；內含 `README.md`、`bin/`、`docs/`、`package.json`、`src/`、`test/`
- [`config/`](config/) — 1 個檔案；內含 `gpt-models.env`
- [`examples/`](examples/) — 10 個檔案；內含 `friction/`、`memory/`、`tool-upgrade-notes/`、`trials/`、`wiki/`
- [`folder-level/`](folder-level/) — 17 個檔案；內含 `.claude/`、`CLAUDE.md`
- [`friction/`](friction/) — 1 個檔案；內含 `PROTOCOL.md`
- [`hooks/`](hooks/) — 110 個檔案；內含 `T1-claim-detect-local-first.llm.test.sh`、`T1-claim-detect-local-first.sh`、`T1-claim-detect-local-first.test.sh`、`T1-evidence-level-detect.sh`、`T1-evidence-level-detect.test.sh`、`T1-evidence-level-fixtures/`、`T1-evidence-level-prompt-v2.txt`、`T1-system-prompt-v5d.txt`…（共 106 項）
- [`install/`](install/) — 45 個檔案；內含 `cc-session-index/`、`compact-guard/`、`folder-level/`、`hooks/`、`output-styles/`、`workflows/`
- [`model-routing.env`](model-routing.env)
- [`openspec/`](openspec/) — 3 個檔案；內含 `specs/`
- [`output-styles/`](output-styles/) — 1 個檔案；內含 `Explanatory.md`
- [`references/`](references/) — 16 個檔案；內含 `claim-evidence-examples.md`、`dispatch-and-verify-examples.md`、`effort-controls.md`、`failure-mode-taxonomy.md`、`harness-model-sensitivity.md`、`ledger-lifecycle.md`、`perspective-sub-scout.md`、`perspective-sub-scout.md.LICENSE`…（共 16 項）
- [`review-standards/`](review-standards/) — 34 個檔案；內含 `ai-generated-changes.md`、`architecture-proposal-lens.md`、`architecture-transformed-code-lens.md`、`catalog.md`、`code-review-quality.md`、`code-review-security.md`、`design-and-maintainability.md`、`finding-discipline.md`…（共 34 項）
- [`rules/`](rules/) — 14 個檔案；內含 `common/`、`typescript/`
- [`scripts/`](scripts/) — 100 個檔案；內含 `advisor-extract-context.py`、`agent-contract-command/`、`agent-contract-validator.definition.test.sh`、`agent-contract-validator.diagnostics.test.sh`、`agent-contract-validator.frontmatter.test.sh`、`agent-contract-validator.mcp-tools.test.sh`、`agent-contract-validator.mjs`、`agent-contract-validator.name.test.sh`…（共 86 項）
- [`settings.json`](settings.json)
- [`skills/`](skills/) — 213 個檔案；內含 `INVENTORY.md`、`absorb-pack/`、`agent-authoring/`、`agent-dispatch/`、`align-intent/`、`auto-choice/`、`brainstorm/`、`caveman/`…（共 43 項）
- [`social-info/`](social-info/) — 76 個檔案；內含 `scripts/`、`tests/`
- [`workflows/`](workflows/) — 8 個檔案；內含 `best-of-n-implement.js`、`failure-mode-daily.sh`、`local-analysis-flow.svg`、`local-analysis.js`、`skill-changes-daily.sh`、`skillevaluator-weekly.sh`、`tests/`
