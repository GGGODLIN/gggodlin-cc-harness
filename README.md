# claude-harness（治理部分的公開版）

https://github.com/user-attachments/assets/0421df31-50ee-447b-a314-a471e8e156a3

## English summary

This repository is the governance part of one person's Claude Code harness: always-on rules (`CLAUDE.md`, `rules/`), hooks that enforce some of those rules mechanically, the skills, commands and agents that the workflow depends on, and the systems around them — a memory system, a trial (observation period) ledger, a friction log, a daily local analysis report, and compact-guard, which keeps evidence across context compaction. Personal customisation (status line, personal tools, blog pipeline, account and browser setup) is not included.

The rules are written in Traditional Chinese and are not translated. If you want them in another language or in your own style, ask Claude to translate or rewrite the files you pick.

It is a reference, not a product. You can install single pieces, but nothing guarantees the whole set runs on your machine. Places where the owner's private wiring was removed are marked in place and listed in `WIRING.md`. Issues are welcome, with no promise of a response. Pull requests are not accepted: this repository is regenerated from a private source on every publish, so a merged pull request would be overwritten by the next export. If you have an improvement, open an issue that describes it.

## 這是什麼

一份個人 Claude Code 設定裡「治理」那一半的公開版。包含：

- 常駐規則：`CLAUDE.md`、`rules/`、`output-styles/`，以及規則引用的 `references/`。
- hook：把部分規則從「靠模型自律」改成機械檢查，註冊寫在 `settings.json`。
- skill、command、agent：規劃、實作、審查、查證這條工作流用到的部分。
- 四套制度：memory（跨 session 記憶）、wiki（收斂後的知識條目）、trial（新工具與新機制的觀察期帳本）、摩擦紀錄（卡住、繞路、規則沒被遵守的事件）。四套都只公開機制，內容換成 `examples/` 裡的虛構範例。
- daily-local：每天跑一次的本機分析報告，掃規則用量、摩擦、壞掉的路徑等，程式在 `social-info/` 與 `cc-skill-doctor/`。
- compact-guard：context 壓縮前存一份可稽核的 checkpoint，壓縮後把原始對話證據注回來，含 Codex 支援，在 `compact-guard/`。

不包含：個人客製化（statusline、個人工具串接、部落格產線、帳號與瀏覽器的具體接法）、公司相關的治理、能力型 skill（畫圖、簡報之類），以及 memory、wiki、trial、摩擦紀錄的實際內容。

## 從哪裡開始

| 你想做的事 | 先看 |
|---|---|
| 已經有自己的 Claude Code 設定，想讓 agent 守紀律 | `skills/gate-authoring/SKILL.md`、`rules/common/dispatch-and-verify.md`、`friction/PROTOCOL.md` 與 `examples/trials/` |
| 想挑一個完整的工具來試 | `compact-guard/README.md`：有完整程式與測試，可以單獨安裝 |
| 想研究 agent 治理、人工授權與出錯後怎麼恢復 | 下面的「設計原則」「已知風險」，以及 `rules/common/git-workflow.md` |
| 想幾分鐘內裝好整套 | 目前做不到：路徑寫死、接線要自己補。單一元件看 `install/` |

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
- `compact-guard/` 照 `~/.claude/compact-guard` 的位置寫進 hook 註冊。
- `install/` 是各機制的安裝說明。
- `examples/` 是 memory、wiki、trial 帳本、摩擦紀錄的虛構範例，只示範格式。

## 被拿掉的接線（🔌）

原作者的私人接線在這些地方被拿掉了。文件裡會留一整行以「🔌 接線點」開頭、指向 WIRING.md 的記號；程式裡被拿掉的呼叫換成替身，一執行就在 stderr 報出接線點名稱並以非零狀態結束，不會默默略過。要用那個功能，請照 `WIRING.md` 自己接。

`WIRING.md` 列出每個接線點用到的元件、需要你提供的介面，以及原作者用的工具。標「僅定義介面」的是灰色路徑（要靠登入 cookie、網頁版內部介面、非官方鏡像或第三方轉接才拿得到的端點），只寫介面，不推薦工具。這次的接線點：

- 🔌 [ChatGPT 網頁版席位](WIRING.md#chatgpt-網頁版席位) — 僅定義介面（interface only），實作請自行提供
- 🔌 [E2E 測試服務](WIRING.md#e2e-測試服務) — 推薦工具：TesterArmy（tester-army/e2e：官方 skill 加 e2e 框架）
- 🔌 [better-rm](WIRING.md#better-rm) — 推薦工具：better-rm
- 🔌 [session 歷史檢索](WIRING.md#session-歷史檢索) — 推薦工具：ccsi（原作者自寫，以 SQLite FTS5 trigram 索引 session jsonl）
- 🔌 [workflow-monitor 後端轉接](WIRING.md#workflow-monitor-後端轉接) — 推薦工具：自己寫一支 case 分支的 shell 腳本（原作者的版本含灰色中轉站分支，未公開）
- 🔌 [中轉站](WIRING.md#中轉站) — 僅定義介面（interface only），實作請自行提供
- 🔌 [多帳號與帳號判定](WIRING.md#多帳號與帳號判定) — 推薦工具：自己寫一支小 shell 函式庫
- 🔌 [後端標記 CC_VENDOR](WIRING.md#後端標記-cc_vendor) — 推薦工具：自己的 shell launcher（原作者用一組 `ccp-*` 函式，未公開）
- 🔌 [架構圖產生與審批](WIRING.md#架構圖產生與審批) — 推薦工具：Archify（產圖）＋ Plannotator（瀏覽器審批）
- 🔌 [瀏覽器自動化](WIRING.md#瀏覽器自動化) — 推薦工具：LCU MCP（工具名 `mcp__lcu__js`）；console、network、效能等診斷另用 chrome-devtools MCP
- 🔌 [程式碼搜尋](WIRING.md#程式碼搜尋) — 推薦工具：semble（MinishLab/semble）
- 🔌 [終端後端](WIRING.md#終端後端) — 推薦工具：Herdr
- 🔌 [跨模型後端](WIRING.md#跨模型後端) — 推薦工具：CLIProxyAPI（本機 OpenAI 相容端點）；需要接更多模型時在前面加 LiteLLM proxy；第二意見用 Codex CLI 與 openai/codex-plugin-cc
- 🔌 [非官方內容抓取](WIRING.md#非官方內容抓取) — 僅定義介面（interface only），實作請自行提供
- 🔌 [額度資料來源](WIRING.md#額度資料來源) — 僅定義介面（interface only），實作請自行提供

## 完整目錄

- [`CLAUDE.md`](CLAUDE.md)
- [`LICENSE`](LICENSE)
- [`README.md`](README.md)
- [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)
- [`WIRING.md`](WIRING.md)
- [`agents/`](agents/) — 33 個檔案；內含 `advisor-seat.md`、`architecture-critic.md`、`architecture-critic.md.LICENSE`、`code-reviewer.md`、`code-reviewer.md.LICENSE`、`deep-explore.md`、`docs-lookup.md`、`docs-lookup.md.LICENSE`…（共 30 項）
- [`cc-skill-doctor/`](cc-skill-doctor/) — 2 個檔案；內含 `scripts/`
- [`commands/`](commands/) — 58 個檔案；內含 `advisor.md`、`aside.md`、`aside.md.LICENSE`、`daily-local.md`、`docs.md`、`docs.md.LICENSE`、`git-closeout.md`、`goal-gen.md`…（共 33 項）
- [`compact-guard/`](compact-guard/) — 23 個檔案；內含 `README.md`、`bin/`、`docs/`、`package.json`、`src/`、`test/`
- [`config/`](config/) — 1 個檔案；內含 `gpt-models.env`
- [`examples/`](examples/) — 8 個檔案；內含 `friction/`、`memory/`、`tool-upgrade-notes/`、`trials/`、`wiki/`
- [`folder-level/`](folder-level/) — 15 個檔案；內含 `.claude/`、`CLAUDE.md`
- [`friction/`](friction/) — 1 個檔案；內含 `PROTOCOL.md`
- [`hooks/`](hooks/) — 113 個檔案；內含 `T1-claim-detect-local-first.llm.test.sh`、`T1-claim-detect-local-first.sh`、`T1-claim-detect-local-first.test.sh`、`T1-evidence-level-detect.sh`、`T1-evidence-level-detect.test.sh`、`T1-evidence-level-fixtures/`、`T1-evidence-level-prompt-v2.txt`、`T1-system-prompt-v5d.txt`…（共 109 項）
- [`install/`](install/) — 45 個檔案；內含 `compact-guard/`、`folder-level/`、`hooks/`、`output-styles/`、`workflows/`
- [`model-routing.env`](model-routing.env)
- [`openspec/`](openspec/) — 3 個檔案；內含 `specs/`
- [`output-styles/`](output-styles/) — 1 個檔案；內含 `Explanatory.md`
- [`references/`](references/) — 14 個檔案；內含 `claim-evidence-examples.md`、`dispatch-and-verify-examples.md`、`effort-controls.md`、`harness-model-sensitivity.md`、`ledger-lifecycle.md`、`perspective-sub-scout.md`、`perspective-sub-scout.md.LICENSE`、`severity-calibration.md`…（共 14 項）
- [`rules/`](rules/) — 14 個檔案；內含 `common/`、`typescript/`
- [`scripts/`](scripts/) — 100 個檔案；內含 `advisor-extract-context.py`、`agent-contract-command/`、`agent-contract-validator.definition.test.sh`、`agent-contract-validator.diagnostics.test.sh`、`agent-contract-validator.frontmatter.test.sh`、`agent-contract-validator.mcp-tools.test.sh`、`agent-contract-validator.mjs`、`agent-contract-validator.name.test.sh`…（共 86 項）
- [`settings.json`](settings.json)
- [`skills/`](skills/) — 198 個檔案；內含 `INVENTORY.md`、`absorb-pack/`、`agent-authoring/`、`agent-dispatch/`、`align-intent/`、`auto-choice/`、`brainstorm/`、`caveman/`…（共 42 項）
- [`social-info/`](social-info/) — 76 個檔案；內含 `scripts/`、`tests/`
- [`workflows/`](workflows/) — 7 個檔案；內含 `best-of-n-implement.js`、`failure-mode-daily.sh`、`local-analysis.js`、`skill-changes-daily.sh`、`skillevaluator-weekly.sh`、`tests/`
