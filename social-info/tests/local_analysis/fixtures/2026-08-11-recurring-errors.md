## 掃描範圍

extract 本次增量掃 143 個新 session jsonl；ledger 累積總行數 3,763（前次同日跑 08-04 為 3,440，+323 行）。過門檻候選 105 個（`recurring-errors-envclass.sh stats`：環境類 9 條 / 行為類 96 條）。語意聚類後收斂為 **10 個行為類 pattern**（2 個延續自 08-04 且已達第 3+ 次出現、標 🚨；4 個延續自 08-04 首次出現、本輪第 2 次、標 ⚠️；4 個本輪首次達門檻的新 pattern）。ledger 目前累積 1,182 個不重複 session；08-04 當時的累積總數未持久化、查不到，**本輪各 pattern 次數僅供本輪內排序用、不可跨輪比較**（見「跨輪計數不可比」規則）。

## 🔁 重複錯誤 pattern（按次數降冪，escalation 優先排前）

### 🚨 shell eval 語法混淆（第 4+ 次延續、本輪 16x/16 sessions、最近 2026-08-10）
- 代表簽名：`exit code (eval):: no matches found:`（16x/16s）；同源 `exit code (eval):: == not found`（7x/7s）、`exit code (eval):: no matches found: ---`（6x/6s）、`exit code (eval):: read-only variable: status`（6x/6s）
- 疑似 root cause：`tool_confusion` — 延續 07-14 起連四輪的同一訊號，zsh/bash 語法（`[[ ]]`、變數展開、read-only 變數命名）在 eval 呼叫鏈中持續混用出錯
- 建議防線：候選同前四輪——eval 呼叫前先確認 shell 種類與語法、必要時 `bash -n` 先過語法檢查；效益未驗證，連五輪未消失（候選、未驗證，不要自動建）

### 🚨 Python 腳本 traceback / JSON decode 錯誤鏈（第 4+ 次延續、本輪 10x/10 sessions、最近 2026-08-08）
- 代表簽名：`traceback (most recent call last): file "<stdin>"...json.load(sys.stdin)...decode(s)`（10x/10s）；同源 `traceback...file "<string>"...keyerror: 'title'`（8x/8s，本輪新出現的子型態——直接 index 缺失 key，不再只是 decode 失敗）
- 疑似 root cause：`tool_confusion` — 一次性 python 腳本沒先驗證輸入格式（JSON 結構 / 欄位存在）就直接 parse/index
- 建議防線：候選同前——暫存腳本落檔 + 先驗證輸入格式（`.get()` 帶預設值、try/except 包 decode）再用；效益未驗證，連五輪未消失（候選、未驗證，不要自動建）

### ⚠️ 讀檔路徑錯誤（cwd 相關 file does not exist）（第 2 次延續、本輪 55x/55 sessions、最近 2026-08-10）
- 代表簽名：`file does not exist. note: your current working directory is`（55x/55s）；同源 tool_use_error 包裝版（6x/6s）
- 疑似 root cause：`tool_confusion` — 延續 08-04 首見的同一 pattern：相對路徑或記錯 cwd 呼叫 Read/Edit 等檔案工具；本輪代表簽名數字仍是本週最大宗行為類單一簽名
- 建議防線：候選同前——檔案工具一律用絕對路徑（本專案 CLAUDE.md 已明文「硬編路徑用 physical path」），呼叫前可先 `pwd`/`ls` 確認 cwd；效益未驗證，第二輪仍未消失（候選、未驗證，不要自動建）

### ⚠️ claude-in-chrome MCP tab/session 管理失效（第 2 次延續、本輪 24x/24 sessions、最近 2026-08-08）
- 代表簽名：`tab no longer exists. call tabs_context_mcp to get current tabs.`（24x/24s）；同源 `no tab available`（10x/10s）、`no mcp tab group exists. use tabs_context_mcp with createifempty: true first`（8x/8s）、`no such tool available: mcp__claude-in-chrome`（7x/7s）
- 疑似 root cause：`tool_confusion` / `context_degradation` 混合——長 session 或跨 turn 情境下 chrome tab context 遺失，呼叫端沒先確認 tab context 存在就直接操作
- 建議防線：候選同前——chrome-devtools / claude-in-chrome 操作前先呼叫 `tabs_context_mcp`（或等效存在性檢查）確認 tab context 有效；效益未驗證，第二輪仍未消失（候選、未驗證，不要自動建）

### ⚠️ git 操作失敗集群（第 2 次延續、本輪 22x/22 sessions、最近 2026-08-10）
- 代表簽名：`致命錯誤: 無法建立...這個版本庫似乎有另一個 git 處理程序在執行`（index.lock，22x/22s）；同源但不同故障模式 `下列路徑根據其中一個 .gitignore 檔案而被忽略`（gitignore 擋 git add，docs 目錄 8x/8s + memory 目錄 8x/8s，合計 16x/16s）、`致命錯誤: 不是一個 git 版本庫（或者任何父目錄）：.git`（7x/7s）
- 疑似 root cause：`tool_confusion` — index.lock 為並行 git 進程搶鎖；gitignore 擋 add 為對 gitignored 路徑直接 `git add` 未先確認；「不是 git 版本庫」疑似在錯誤 cwd 下執行 git 指令
- 建議防線：候選同前——長跑/背景 git 操作前先確認無其他 git 進程佔用；`git add` 前先 `git check-ignore`；效益未驗證，第二輪仍未消失（候選、未驗證，不要自動建）

### ⚠️ Edit replace_all 未設定導致多重匹配失敗（第 2 次延續、本輪 14x/14 sessions、最近 2026-08-10）
- 代表簽名：`<tool_use_error>found matches of the string to replace, but replace_all is false. to replace all occurrences, set replace_all to true.`（14x/14s）
- 疑似 root cause：`tool_confusion` — `old_string` 在檔案中出現多次但未帶 `replace_all: true`
- 建議防線：候選同前——Edit 前先 grep 確認 `old_string` 在檔內是否唯一，非唯一則明確帶 `replace_all: true` 或擴大 old_string 範圍；效益未驗證，第二輪仍未消失（候選、未驗證，不要自動建）

### exit code ls: no such file or directory（新、本輪 18x/18 sessions、最近 2026-08-09）
- 代表簽名：`exit code ls: no such file or directory`（18x/18s）
- 疑似 root cause：`tool_confusion` — Bash 用 `ls` 探路徑時目標不存在，與上面「讀檔路徑錯誤」同族但工具不同（一個是 Read/Edit 工具內建報錯、這個是 shell `ls` 本身噴錯），先分開列避免和 file-tool 那條混算
- 建議防線：候選——探路徑前先 `ls -d` 上層目錄或用 `test -e` 確認存在，減少對不存在路徑直接操作；效益未驗證，觀察是否連續出現（候選、未驗證，不要自動建）

### javascript execution error: await 用在非 async 函式（新、本輪 13x/13 sessions、最近 2026-06-14，⚠️ 最近一次已隔近 2 個月、判斷是否仍活躍）
- 代表簽名：`javascript execution error: syntaxerror: await is only valid in async functions and the top level bodies of modules`（13x/13s）
- 疑似 root cause：`tool_confusion` — chrome-devtools `evaluate_script` 呼叫時把 `await` 寫在非 async 包裝內，語法層直接被拒
- 建議防線：候選——evaluate_script 呼叫一律包成 `(async () => { ... })()` 或用 IIFE 包住 await；效益未驗證；⚠️ 本輪累積 13x 但最近一次已是 2026-06-14、近兩個月無新樣本，可能已隨呼叫習慣改善或單純巧合未撞——不下因果結論，僅記錄（候選、未驗證，不要自動建）

### this site is not allowed due to safety restrictions（新、本輪 10x/10 sessions、最近 2026-06-23，同樣已隔約 7 週）
- 代表簽名：`this site is not allowed due to safety restrictions.`（10x/10s）
- 疑似 root cause：`tool_confusion` — chrome 自動化嘗試導覽到被安全政策擋下的網域（推測為敏感/成人/已知風險網域黑名單），呼叫端未先確認目標網域是否受限
- 建議防線：候選——chrome navigate 前對不熟網域先預判是否可能觸發安全限制，撞到即改走 fetch-fallback 或直接放棄該來源；效益未驗證；同樣近 7 週無新樣本、暫不判斷是否仍活躍（候選、未驗證，不要自動建）

## 低頻候選（<10x、跨 2 週皆未展開獨立 pattern，供留意）

- `no changes to make: old_string and new_string are exactly the same`（Edit tool_confusion，8x，08-04 同族為 6x——低幅上升但仍低於門檻，暫不展開）
- `error: access denied: path...is not within any of the configured workspace roots`（新、8x）——疑似工具在受限 workspace 外操作被擋，屬防線正常運作或路徑算錯待觀察
- `inputvalidationerror: taskcreate failed...required parameter subject is missing`（新、6x）——TaskCreate 呼叫漏帶必填欄位
- `unknown json field: "topics"`（gh api schema，9x，08-04 同為 9x，持平）
- `concurrent subagent limit reached. do not retry.`（9x）——本身是限流提示訊息，非缺口
- `api error: output_config.effort 'xhigh' is not supported when thinking is disabled`（6x，08-04 同為 6x，持平）——vendor 模型設定限制

## 🌐 環境失敗（確定性分流，不建防線）

- 32x 跨 32 sessions、最近 2026-08-06｜`exit code command timed out after m s`——跨度大，可能值得查是否有特定長跑指令基礎設施偏慢
- 7x 跨 7 sessions、最近 2026-06-29｜`error capturing screenshot: cdp sendcommand "page.capturescreenshot" timed out after ms on tab. the renderer may be frozen or unresponsive.`
- 7x 跨 7 sessions、最近 2026-05-17｜`timeout of ms exceeded`
- 6x 跨 6 sessions、最近 2026-08-01｜`ripgrep search timed out after seconds. the search may have matched files but did not complete in time.`
- 5x 跨 5 sessions、最近 2026-08-05｜`error: failed to interact with the element with uid...did not become interactive within the configured timeout.`
- 4x 跨 4 sessions、最近 2026-07-11｜`failed to execute javascript: cdp sendcommand "runtime.evaluate" timed out after ms on tab. the renderer may be frozen or unresponsive.`
- 4x 跨 4 sessions、最近 2026-05-21｜`network.enable timed out. increase the 'protocoltimeout' setting in launch calls for a higher timeout if needed.`
- 3x 跨 3 sessions、最近 2026-08-10｜`error: timed out after waiting ms`
- 3x 跨 3 sessions、最近 2026-05-25｜`the socket connection was closed unexpectedly. for more information, pass \`verbose: true\` in the second argument to fetch().`

## 噪音／已判定不報

- **Edit/Write 未讀先寫 + 讀後過期 family**（`file has not been read yet` 383x + `[write-needs-read] fabricated edit` 122x + `[write-needs-read] write` 26x + `file has been modified since read` 73x，合計本輪最大宗 604x）：07-19 使用者已拍板 killed（原生工具限制即防線，恢復 hook 屬過度工程化）——僅記 baseline 統計，不列 pattern、不觸發 escalation
- **Read 大檔超限**（`file content exceeds maximum allowed tokens` 60x + `exceeds maximum allowed size (kb)` 15x，合計 75x）：07-28 使用者已拍板 killed（工具使用學習曲線、無資產可修）——僅 baseline
- **Workflow deferred tool 未知參數**（`unexpected parameter run_in_background` 26x）：07-28 使用者已拍板 killed——僅 baseline
- **permission 拒絕**（`the user doesn't want to proceed with this tool use` 107x）：使用者主動決策，非坑，不報
- **t-routing-gate 提示文字**（`routed-agent-enforce trial 生效中` 21x + `派 agent tool 前過 routing decision` 7x）：是 gate 正常攔截未指定 model 派工的說明訊息，屬防線運作中，非缺口
- **reddit 抓取失敗**（`claude code is unable to fetch from www.reddit.com` 11x）：本專案 KNOWN_ISSUES.md / CLAUDE.md「已知 fetcher gap」已有完整應對機制，非新缺口
- **使用者已 fork debugging skill 說明文字**（7x）：非錯誤，是機制訊息
- **⚠️ 資料品質備註**：`exit code .. (claude code) --- --- agents agents.md claude.md commands...`（25x/25s，最近 2026-04-25）經查是 `ls` 目錄列表輸出被 extract script 誤判為錯誤簽名（原始內容是檔名清單，不含任何錯誤字樣），非真實 pattern，本輪不列建議；標記供之後若要收斂 extract script 誤判規則參考，本 channel 職責內不改 script
- **dcg 破壞性指令防線**：本輪未達候選門檻——194 次 dcg 攔截散在 190 個不同簽名（每則指令內容不同、簽名未去參數化聚合），單一簽名最高僅 3x，低於 ≥3 且需同簽名 ≥2 sessions 的門檻。**不下「已改善」結論**——這是簽名粒度問題（每條被攔指令文字不同導致無法聚合成同一 sig），不代表 dcg 攔截次數真的下降，僅代表本輪聚合方式看不到它，供未來調整簽名正規化時參考

## Ledger cross-check

已 grep `pending-actions.jsonl`：本輪命中 status=killed 的三族（Edit/Write 未讀先寫+讀後過期 / Read 大檔超限 / Workflow deferred tool 未知參數）已比照規則列入 baseline-only、不進建議與 escalation。其餘（shell eval / python traceback / cwd 讀檔路徑 / chrome tab 管理 / git 操作失敗 / Edit replace_all / ls 路徑不存在 / js await 語法 / safety restrictions）未命中既有 killed 條目。
