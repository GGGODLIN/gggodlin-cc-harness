## 掃描範圍

extract 本次增量掃 8 個新 session jsonl；ledger 累積總行數 3,440（前次同日跑為 3,437、+3 行）。**⚠️ 2026-08-01 ledger 已全量重建**（舊格式 18,684 行 → 新格式），本輪數字與 07-28 之前任何報告的原始次數一律不可比、也不重算跨輪發生率。過門檻候選 96 個（`recurring-errors-envclass.sh stats`：環境類 8 條 / 行為類 88 條）。語意聚類後收斂為 **7 個行為類 pattern**（3 個延續既有 pattern、4 個首次達門檻的新 pattern；「延續」僅指 pattern 語意身分沿用 07-28 命名、不代表次數可加總或比較）。本輪增量 8 個 session 未改變 top-40 排序與任一 pattern 的次數/session 數，與本日稍早同名報告數字一致。

## 🔁 重複錯誤 pattern（按次數降冪）

### 🚨 dcg 破壞性指令防線持續攔截（延續、本輪 3x/3 sessions、最近 2026-07-29）
- 代表簽名：`blocked by dcg tip: dcg explain "review_root=... launch_epoch=$(date +%s) cd "$review_root" && (nohup codex review \ --base...`（3x/3s）
- 疑似 root cause：`goal_abandonment` / `tool_confusion` 混合——延續 07-14/07-21/07-28 三輪皆有樣本的同一 pattern（codex review 相關的 nohup/redirect 組合指令持續撞防線）
- 建議防線：仍是既有 dcg 防線正常運作、不是缺口；連四輪出現，若使用者想收斂可考慮抽樣看是否同一則 codex review 指示樣板反覆觸發（候選、未驗證，不要自動建）

### 🚨 shell eval 語法混淆（延續、本輪 16x/16 sessions、最近 2026-08-03）
- 代表簽名：`(eval):: == not found`（16x/16s）；同源 `(eval):: no matches found: ---`（6x/6s）、`(eval):: read-only variable: status`（5x/5s）、`(eval):cd:: no such file or directory: .worktrees`（4x/4s）、`(eval):: bad substitution`（3x/3s）、`(eval):: command not found: gh`（3x/3s）、`(eval):: parse error near ')'`（3x/3s）、`(eval):: unmatched "`（3x/3s）、`--- (eval):: no matches found:`（3x/3s）
- 疑似 root cause：`tool_confusion` — 延續前三輪同一訊號，zsh/bash 語法（`[[ ]]`、變數展開、字串轉義）在 eval 呼叫鏈中持續混用出錯，子類型比前幾輪更分散
- 建議防線：候選同前三輪——寫 shell 判斷句 / eval 呼叫前先確認 shell 種類與語法（`[[ ]]` vs POSIX `[ ]`），必要時先用 `bash -n` 語法檢查；效益未驗證，連四輪未消失（候選、未驗證，不要自動建）

### 🚨 Python 腳本 traceback / JSON decode 錯誤鏈（延續、本輪 6x/6 sessions、最近 2026-07-27）
- 代表簽名：`traceback (most recent call last): file "<stdin>"...json.load(sys.stdin)...decode(s)`（6x/6s）；同源 `traceback...file "<string>"...d=json.load(sys.stdin)`（4x/4s）、`traceback...<frozen runpy>..._run_module_as_main`（3x/3s）、`traceback...file "<string>"...d = json.load(sys.stdin)`（3x/3s）、`jq: parse error: invalid numeric literal`（5x/5s，同族但不同工具）
- 疑似 root cause：`tool_confusion` — 延續前三輪同一 pattern：一次性 python/jq 腳本沒先驗證輸入格式就直接 parse，噴例外
- 建議防線：候選同前三輪——一次性分析腳本落成暫存檔 + 先驗證輸入格式再 parse；效益未驗證，連四輪未消失（候選、未驗證，不要自動建）

### claude-in-chrome MCP tab/session 管理失效（新、本輪 23x/23 sessions、最近 2026-07-17）
- 代表簽名：`tab no longer exists. call tabs_context_mcp to get current tabs.`（23x/23s）；同源 `no tab available`（10x/10s）、`no mcp tab group exists. use tabs_context_mcp with createifempty: true first`（8x/8s）、`this session's tab group no longer exists (tabs were closed)`（4x/4s）、`no such tool available: mcp__claude-in-chrome`（7x/7s）、`could not connect to chrome...devtoolsactiveport`（5x/5s）
- 疑似 root cause：`tool_confusion` / `context_degradation` 混合——長 session 或跨 turn 情境下 chrome tab context 遺失（tab 被關閉、tab group 過期、MCP server 未連線），呼叫端沒先確認 tab context 存在就直接操作；07-28 之前的報告未見此群聚，可能是首次跨 ≥2 session 累積足量樣本
- 建議防線：候選——chrome-devtools / claude-in-chrome 操作前先呼叫 `tabs_context_mcp`（或等效存在性檢查）確認 tab context 有效，失效才重建；效益未驗證，觀察是否連續出現（候選、未驗證，不要自動建）

### git 操作失敗集群（新、代表簽名 19x/19 sessions、最近 2026-08-03）
- 代表簽名：`致命錯誤: 無法建立...這個版本庫似乎有另一個 git 處理程序在執行`（index.lock，19x/19s）；同源但不同故障模式 `下列路徑根據其中一個 .gitignore 檔案而被忽略`（gitignore 擋 git add，memory 目錄 8x/8s + docs 目錄 7x/7s，合計 15x/15s）、`致命錯誤: 不是一個 git 版本庫（或者任何父目錄）：.git`（5x/5s）
- 疑似 root cause：`tool_confusion` — index.lock 為並行 git 進程搶鎖（07-21 曾 4x/4s 未達門檻，本輪明顯上升，但因 ledger 重建不可直接比較次數）；gitignore 擋 add 為對 gitignored 路徑直接 `git add` 未先確認是否已排除；「不是 git 版本庫」疑似在錯誤 cwd 下執行 git 指令
- 建議防線：候選——長跑/背景 git 操作前先確認無其他 git 進程佔用（`git status` 探測）；`git add` 前先 `git check-ignore` 確認路徑非刻意排除；效益未驗證，觀察是否連續出現（候選、未驗證，不要自動建）

### 讀檔路徑錯誤（cwd 相關 file does not exist）（新、51x/51 sessions、最近 2026-08-03）
- 代表簽名：`file does not exist. note: your current working directory is`（45x/45s）+ 同源 tool_use_error 包裝版（6x/6s）
- 疑似 root cause：`tool_confusion` — 用相對路徑或記錯 cwd 呼叫 Read/Edit 等檔案工具，工具回報「目前 cwd 是 X」提示路徑解析錯誤；本輪單一簽名即達 45x/45 sessions，量體不小
- 建議防線：候選——檔案工具一律用絕對路徑（本專案 CLAUDE.md 已明文「硬編路徑用 physical path」），呼叫前可先 `pwd`/`ls` 確認 cwd 再組路徑；效益未驗證，觀察是否連續出現（候選、未驗證，不要自動建）

### Edit replace_all 未設定導致多重匹配失敗（新、11x/11 sessions、最近 2026-07-30）
- 代表簽名：`<tool_use_error>found matches of the string to replace, but replace_all is false. to replace all occurrences, set replace_all to true.`（11x/11s）
- 疑似 root cause：`tool_confusion` — `old_string` 在檔案中出現多次但未帶 `replace_all: true`，與已拍殺的「未讀先寫」「old_string 找不到匹配」是不同故障模式（這批是找得到但重複、參數沒設對）
- 建議防線：候選——Edit 前先 grep 確認 `old_string` 在檔內是否唯一，非唯一則明確帶 `replace_all: true` 或擴大 old_string 範圍；效益未驗證，觀察是否連續出現（候選、未驗證，不要自動建）

## 🌐 環境失敗（確定性分流，不建防線）

- 28x 跨 28 sessions、最近 2026-08-03｜`exit code command timed out after m s`——跨度大，可能值得查是否有特定長跑指令基礎設施偏慢
- 7x 跨 7 sessions、最近 2026-06-29｜`error capturing screenshot: cdp sendcommand "page.capturescreenshot" timed out after ms on tab. the renderer may be frozen or unresponsive.`
- 7x 跨 7 sessions、最近 2026-05-17｜`timeout of ms exceeded`
- 6x 跨 6 sessions、最近 2026-08-01｜`ripgrep search timed out after seconds. the search may have matched files but did not complete in time.`
- 4x 跨 4 sessions、最近 2026-07-29｜`error: failed to interact with the element with uid...did not become interactive within the configured timeout.`
- 4x 跨 4 sessions、最近 2026-07-11｜`failed to execute javascript: cdp sendcommand "runtime.evaluate" timed out after ms on tab. the renderer may be frozen or unresponsive.`
- 4x 跨 4 sessions、最近 2026-05-21｜`network.enable timed out. increase the 'protocoltimeout' setting in launch calls for a higher timeout if needed.`
- 3x 跨 3 sessions、最近 2026-05-25｜`the socket connection was closed unexpectedly. for more information, pass \`verbose: true\` in the second argument to fetch().`

## 噪音／已判定不報

- **Edit/Write 未讀先寫 + 讀後過期 family**（`file has not been read yet` 376x + `[write-needs-read] fabricated` 122x + `[write-needs-read] write` 26x + `file has been modified since read` 72x，合計本輪最大宗）：07-19 使用者已拍板 killed（原生工具限制即防線，恢復 hook 屬過度工程化）——僅記 baseline 統計，不列 pattern、不觸發 escalation
- **Read 大檔超限**（`file content exceeds maximum allowed tokens` 57x + `exceeds maximum allowed size (kb)` 14x）：07-28 使用者已拍板 killed（工具使用學習曲線、無資產可修）——僅 baseline
- **Workflow deferred tool 未知參數**（`unexpected parameter run_in_background` 26x）：07-28 使用者已拍板 killed——僅 baseline
- **permission 拒絕**（`the user doesn't want to proceed with this tool use` 107x）：使用者主動決策，非坑，不報
- **t-routing-gate / routed-agent-enforce 提示文字**（13x + 7x + 6x「permission to use agent with model:haiku has been denied」）：是 gate 正常攔截未指定 model 派工的說明訊息，屬防線運作中，非缺口
- **reddit 抓取失敗**（`claude code is unable to fetch from www.reddit.com` 11x）：本專案 KNOWN_ISSUES.md / CLAUDE.md「已知 fetcher gap」已有完整應對機制（reddit 鏡像 API → old.reddit → fetch-fallback 階梯），非新缺口
- **使用者已 fork debugging skill 說明文字**（7x）：非錯誤，是機制訊息
- **低頻候選（<10x，未展開獨立 pattern，供留意）**：`unknown json field "topics"`（gh api schema，9x）、`effort 'xhigh' not supported when thinking disabled`（vendor 模型設定，6x）、`concurrent subagent limit reached`（6x）、`no changes to make: old_string and new_string identical`（Edit tool_confusion，6x）、`askuserquestion questions type expected array`（5x）、`grep: no such tool available`（5x）——樣本量小，本輪不展開建議

## Ledger cross-check

已 grep `pending-actions.jsonl`：本輪所有 pattern 中，僅「Edit/Write 未讀先寫 + 讀後過期」「Read 大檔超限」「Workflow deferred tool 未知參數」三族命中 status=killed 條目，已比照規則列入 baseline-only、不進建議與 escalation。其餘（dcg / shell eval / python traceback / chrome tab 管理 / git 操作失敗 / 讀檔路徑錯誤 cwd / Edit replace_all 多重匹配）未命中既有 killed 條目。
