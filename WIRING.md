# WIRING

公開版拿掉了下列個人接線點。文件裡對應的位置留有 🔌 記號，程式裡的呼叫換成替身：替身一執行就在 stderr 報出接線點名稱並以非零狀態結束，不會默默略過。要啟用該功能，請自行提供下列介面，並把記號或替身換成你的接線。

## ChatGPT 網頁版席位

### 用到的元件

- `commands/advisor.md`
- `commands/pr-review.md`
- `commands/review-spec.md`
- `config/gpt-models.env`
- `scripts/pr-review-gemini-web.py`
- `scripts/test_pr_review_gemini_web.py`

### 需提供的介面

一個能把整份問題送給網頁版 ChatGPT（Pro 等級模型）、回傳對話 ID，之後再用 ID 收回完整回答的介面。advisor 的選項 2、review-spec 的外部席位與 pr-review 的 web GPT Pro 軸都只需要「送出」與「收件」兩個動作。

此接線點只定義介面，實作請自行提供。

## E2E 測試服務

### 用到的元件

- `skills/e2e-route`

### 需提供的介面

一套能從自然語言或規格產生並執行瀏覽器 E2E 測試的服務或框架，給 e2e-route 選派「新版」路線時接手。不接時，e2e-route 只用 Playwright 路線（e2e-explore-then-batch、e2e-contract）。

### 推薦工具

TesterArmy（tester-army/e2e：官方 skill 加 e2e 框架）

## session 歷史檢索

### 用到的元件

- `rules/common/code-search.md`

### 需提供的介面

一個對 `~/.claude/projects/**/*.jsonl`（含 subagent 與 workflow transcript）建全文索引、能用中文字面查詢的 CLI，回答「我之前怎麼做的、某決策發生在哪個 session」。

### 推薦工具

ccsi（原作者自寫，以 SQLite FTS5 trigram 索引 session jsonl）

## workflow-monitor 後端轉接

### 用到的元件

- `commands/workflow-monitor.md`
- `hooks/workflow-monitor-nudge.sh`

### 需提供的介面

一支轉接腳本，依 `CC_VENDOR` 回答三件事：`status` 印目前的指標、`proc` 印 watcher 的 pgrep 樣式、`resolve <session>` 印 pause 與 resume 兩行 watcher 啟動指令（含該後端的門檻）。原生 Anthropic 後端只需要把你自己的額度 watcher 腳本包起來。

### 推薦工具

自己寫一支 case 分支的 shell 腳本（原作者的版本含灰色中轉站分支，未公開）

## 中轉站

### 用到的元件

- `commands/pr-review.md`
- `commands/workflow-monitor.md`
- `references/workflow-monitor-lessons.md`

### 需提供的介面

第三方中轉服務的健康度指標（0–100，越低越差），以及在 Codex 額度用完時改走同一個 review 指令的備援 provider 設定。

此接線點只定義介面，實作請自行提供。

## 全機文件定位

### 用到的元件

- `rules/common/code-search.md`

### 需提供的介面

一個有界範圍的文件定位索引：輸入一句描述，回傳最可能的原始檔路徑與摘錄，並附索引時間與「原檔是否已變」旗標；用在「不知道東西在哪個 repo／目錄」的時候。已知 repo 的程式探索仍走程式碼搜尋、session 歷史走 session 歷史檢索；沒有這個工具時退回檔名／關鍵詞查找，空結果不代表檔案不存在。

### 推薦工具

DigUp（原作者試用中，用一支小 wrapper 包起來、掃描範圍由私人設定檔決定，兩者未公開；不是強依賴，規則其餘路由不靠它）

## 多帳號與帳號判定

### 用到的元件

- `commands/advisor.md`
- `commands/git-closeout.md`
- `commands/self-closeout.md`
- `commands/session-monitor.md`
- `hooks/session-limit-nudge.sh`
- `references/workflow-monitor-lessons.md`
- `rules/common/git-workflow.md`
- `scripts/session-limit-watch.sh`

### 需提供的介面

一個 shell 函式庫，提供 `cc_resolve_account_email`（目前登入的帳號）與 `cc_resolve_quota_file`（該帳號的額度快取檔路徑）；多帳號共用一套設定時，先看 `CLAUDE_CONFIG_DIR` 下的 `.claude.json`，再退回 `$HOME`。git 收尾另需一支檢查各帳號 config 目錄 symlink 的腳本。

### 推薦工具

自己寫一支小 shell 函式庫

## 後端標記 CC_VENDOR

### 用到的元件

- `commands/review-spec.md`
- `commands/session-monitor.md`
- `commands/workflow-monitor.md`
- `hooks/T2-routing-gate.sh`
- `hooks/checkpoint-judge.sh`
- `hooks/review-spec-dual-permit.py`
- `hooks/review-spec-yagni-permit.py`
- `hooks/session-limit-nudge.sh`
- `hooks/verify-audit-silent-log.sh`
- `hooks/websearch-parallel-enforce.sh`
- `hooks/workflow-monitor-nudge.sh`
- `references/subagent-routing.md`
- `scripts/review-spec-yagni-native.sh`

### 需提供的介面

用非 Anthropic 後端啟動 Claude Code 時，由啟動腳本 export `CC_VENDOR=<後端名稱>`；沒設時視為原生 Anthropic。列出的 hook 依這個值略過或改走另一個分支，所以只用原生後端的人不需要接。

### 推薦工具

自己的 shell launcher（原作者用一組 `ccp-*` 函式，未公開）

## 架構圖產生與審批

### 用到的元件

- `commands/review-spec.md`
- `scripts/plannotator-review.mjs`
- `scripts/plannotator-review.test.mjs`
- `skills/implement`

### 需提供的介面

兩件事：一支把架構 JSON 畫成前後對照圖的 CLI，以及一個能在瀏覽器裡顯示圖、讓使用者按核准或退回、並把結果寫成檔案的審批工具。`scripts/plannotator-review.mjs` 是後者的轉接器；沒有它們時，implement 的架構邊界關卡與 review-spec 的架構圖段落只能選「跳過」。

### 推薦工具

Archify（產圖）＋ Plannotator（瀏覽器審批）

## 瀏覽器自動化

### 用到的元件

- `agents/parallel-search.md`
- `hooks/websearch-parallel-enforce.sh`
- `hooks/websearch-parallel-enforce.test.py`
- `openspec/specs/browser-routing`
- `rules/common/browser-routing.md`
- `rules/common/desktop-app-routing.md`
- `rules/common/fact-check.md`
- `skills/research-before-answer`
- `skills/workflow-hardening`

### 需提供的介面

一個能操作使用者日常 Chrome 的 MCP：開自己的分頁、導航到指定網址、讀回頁面文字與元素、關掉自己開的分頁；另需讓 PreToolUse／Stop hook 知道目前的 session 與回合，websearch-parallel-enforce 才能確認「搜尋頁真的讀回來了」。桌面 app 操作沿用同一個工具。

### 推薦工具

LCU MCP（工具名 `mcp__lcu__js`）；console、network、效能等診斷另用 chrome-devtools MCP

## 程式碼搜尋

### 用到的元件

- `agents/semble-search.md`
- `hooks/semble-root-block.py`
- `rules/common/code-search.md`

### 需提供的介面

一個語意程式碼搜尋工具，MCP 介面提供 `search`（自然語言或精確名稱）與 `find_related`（給 file:line 找相似程式），另有 CLI 能搜 Markdown 筆記。沒有時規則退回 `command grep` 加 Read。

### 推薦工具

semble（MinishLab/semble）

## 終端後端

### 用到的元件

- `hooks/api-error-auto-continue.py`
- `references/subagent-routing.md`
- `rules/common/dispatch-and-verify.md`
- `rules/common/terminal-backend-routing.md`
- `skills/agent-dispatch`
- `skills/implement`
- `skills/skill-creator`

### 需提供的介面

一個能管理多個終端 pane 的後端：開新的 worker pane 並在其中啟動 agent、往指定 pane 送文字、讀 pane 狀態，並用環境變數（例如 pane ID 與 workspace ID）告訴目前的 session 它跑在哪個 pane。沒有這些身分變數時，相關 skill 與 hook 會退回一般 shell 或不動作。

### 推薦工具

Herdr

## 跨模型後端

### 用到的元件

- `agents/advisor-seat.md`
- `commands/advisor.md`
- `commands/pr-review.md`
- `commands/review-spec.md`
- `config/gpt-models.env`
- `hooks/T1-claim-detect-local-first.sh`
- `hooks/T1-evidence-level-detect.sh`
- `hooks/T1-warning-check.sh`
- `hooks/dispatch-obligation-nudge.py`
- `hooks/memory-ripple-runtime.py`
- `hooks/ticket-yagni-runner.py`
- `hooks/ticket-yagni.py`
- `model-routing.env`
- `references/strong-models.md`
- `scripts/model-routing.sh`
- `scripts/pr-review-codex-set.mjs`
- `scripts/skillevaluator-trial.py`
- `skills/handoff-impl`
- `skills/implement`
- `skills/model-onboard`
- `social-info/scripts/local-analysis/recap-daily.sh`

### 需提供的介面

一個本機的 OpenAI／Anthropic 相容代理端點（預設 `:8317`）、它的金鑰（hook 從 `CLIPROXY_KEY_CC` 這類環境變數讀），以及 `model-routing.env`、`config/gpt-models.env` 裡的模型名稱；第二意見席位另需 Codex CLI 或同類 CLI。沒有這些時，依賴它的 hook 會略過或報錯，判斷照常由主 session 做。

### 推薦工具

Magpie 或 CLIProxyAPI（本機多模型代理端點，可選擇搭配 LiteLLM proxy）；第二意見席位用 Codex CLI 與 openai/codex-plugin-cc

## 非官方內容抓取

### 用到的元件

- `rules/common/fact-check.md`
- `skills/github-repo-research`
- `skills/research-before-answer`

### 需提供的介面

四個抓取能力：一支通用的網址抓取退路（WebFetch 失敗後第一個試，輸入網址、輸出 Markdown 文字，拿不到時以 exit 75 交還瀏覽器路線）、X／Twitter 單篇貼文全文、Reddit 討論串留言、需要特殊處理的付費牆網域清單。輸入是網址，輸出是 Markdown 文字。

此接線點只定義介面，實作請自行提供。

## 額度資料來源

### 用到的元件

- `commands/advisor.md`
- `commands/session-monitor.md`
- `commands/workflow-monitor.md`
- `hooks/session-limit-nudge.sh`
- `references/workflow-monitor-lessons.md`
- `scripts/session-limit-watch.sh`

### 需提供的介面

一支背景程式，定期把目前帳號的 5 小時與 7 天用量百分比、重置時間寫進 `~/.claude/cache/quota-<帳號>.json`（欄位 `.data.five_hour.utilization` 等）。session-monitor、workflow-monitor 與 session-limit-nudge 只讀這個檔，讀不到就不動作或報「看不到額度」。

此接線點只定義介面，實作請自行提供。
