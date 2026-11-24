# Jev automatic memory reminder

Threat model: 提示型、防漂移，只協助誠實但可能忘記回查 memory 的 main。不是寫入授權、不是 missing-memory 判定、不防主動規避。任何錯誤或不確定都放行，不能阻擋手動 checkpoint 或本輪工作。字串與來源篩選只辨識常見形狀；不保證完整語意或完美敏感資料遮蔽。

## 接線

- `Stop` command hook，`async: true`：讀本回合與上一交換，優先用 payload 的 `last_assistant_message`，只問 `auto-memory-jev-question.json` 的 direct 題。命中僅存 pending 判定，不輸出提醒、不寫 memory、不跑 Git。
- 五腿順序（2026-11-14 升級第一腿，2026-11-16 插入第二腿 Vercel 免費點數備援，2026-11-17 插入第三腿 AMD Token Lab `d3` 贈點備援並補齊第一腿 HTTP `400` 冷卻；第三腿逾時以剩餘預算動態夾限，使五腿常態收在 `settings.json` `Stop` 10 秒上限內）：
  1. **第一腿 Perplexity Decider v1.3 (`:free`)**：經本機 Magpie 中繼 `http://127.0.0.1:8317/v1/systemone` 送 `openrouter/perplexity/pplx-decider-v1.3:free`（`User-Agent: auto-memory-jev` 供 Magpie `usage.jsonl` 歸因，逾時 3.0 秒；驗回傳 `usage.cost == 0`，400／404／429／缺 cost 單獨冷卻 `pplx_cooldown_until` 一小時，中繼未起或冷卻中直接退下一腿）。
  2. **第二腿 Vercel Perplexity Decider v1.3（月贈免費點數）**：第一腿失敗或冷卻時，先查 `https://ai-gateway.vercel.sh/v1/credits`（Keychain `jev-api-key`，逾時 2.0 秒，正負結果皆快取於 `vercel-free-credits.json` 一小時）確認回傳含 `token_pass: null` 且 `0 < balance <= 5.0`（未轉付費儲值且免費餘額大於 0），再經本機 Magpie 中繼送 `vercel-decide/perplexity/pplx-decider-v1.3`（逾時 2.5 秒，`patience=off` 不在閘道內重試 429；402／403／404／429 單獨冷卻 `vercel_cooldown_until` 一小時，402 先寫入負向快取）。
  3. **第三腿 AMD Token Lab `d3`（贈點備援）**：前兩腿失敗或冷卻時，經本機 Magpie 中繼送 `amd-tokenlab/d3`（單腿逾時上限 4.5 秒，並依 `Stop` 總預算 `9.2` 秒預留後兩腿 `2.5` 秒動態夾限；回件無 `usage.cost` 欄，改驗回傳 `model` 與 `noul` 並記錄 `amd_points_est`，400／402／403／404／429 單獨冷卻 `amd_cooldown_until` 一小時）。
  4. **第四腿 Experiential Jev (`:free`)**：前三腿失敗或冷卻時，直連 `https://api.experientiallabs.ai/v1/systemone` 問 `type-safe/jev-latest:free`（Keychain `experiential-api-key`，逾時 1.2 秒）。
  5. **第五腿 Drex（2026-10-17 加）**：前四腿皆失敗／冷卻時，同一題同一門檻改問 nace `drex-v2.0`（`https://console.nace.ai/v1/systemone`，Keychain `nace-api-key`，逾時 1.2 秒）。五腿都失敗才記 `unavailable`。選 v2.0 的依據與數字在 hook 檔頭註解。
- `UserPromptSubmit` command hook：本機消費上一人類回合的 pending，送 `additionalContext`。不叫 API、不喚醒 idle session、不要求新回合只回 skip。通知／peer／工具結果不消費。
- 手動 checkpoint 與自動消費共用 `memory_reminder_common.py` 的簡短記憶 checklist 與 `hooks/state/long_injected_<session>` 紀錄讀取。自動入口一律送簡短 checklist 並指路在需要寫入前先讀 `feedback_memory_cluster_maintenance.md` 的 Tier 1；完整 Tier 1 僅由手動 `checkpoint-judge.sh` 注入並記錄 `long_injected_<session>`。原手動觸發、block、Git closeout 與 trigger sentinel 不共用給自動入口。
- agent 身分靠 payload `agent_id`／`agent_type` 與 subagents 路徑；不以 `CLAUDE_CODE_CHILD_SESSION` 排除，因為 Native 2.1.289 的 root SDK session 也帶 `1`（隔離 harness 已驗）。不是全部外部 worker CLI 的可靠身分識別。
- 適用整機 Claude Code 主 session（2026-10-19 KEEP 結案後拿掉 trial 期間的個人目錄白名單與公司字樣過濾，比照 T1-evidence-level）；含金鑰／私鑰的敏感封包、使用者明示不要記、明確要求 memory／closeout、或觀察到 memory 寫入的回合不送。沒有語意 keyword 前置篩選。

## 免費與限額

Jev 腿只允許固定 Experiential `/v1/systemone` 與 `type-safe/jev-latest:free`。先確認模型清單仍有這個 ID 且 input/output 定價為零；驗證結果最多快取一小時。沒有零價證據就不打 Jev（改走 Drex），不改帳戶的 credits-overflow 設定。Key 僅在 process 內從 Keychain `experiential-api-key` 取出。

Vercel 第二腿從 Vercel AI Gateway 每月免費點數扣款（免費層每模型獨立 `5 RPM`、耗盡回 `402`），回件無零價 `usage.cost` 欄而是附 `provider_metadata.gateway.cost`；因此不用零 `usage.cost` 檢查，改以每小時快取查核 `GET /v1/credits`（Keychain `jev-api-key`，正負結果皆快取一小時）確認明確含 `token_pass: null` 且 `0 < balance <= 5.0`（排除已購付費額度或點數耗盡），並將 `vercel_credit_cost` 記進 log，不寫 disabled sentinel。

Drex 第五腿不是免費：從帳號贈額扣款（依供應商公開定價換算估算成本）。AMD 第三腿使用 AMD Token Lab 免費贈點（依 input token 估算扣點），回件無 `usage.cost` 欄，hook 用 `input_tokens` 算 `amd_points_est` 記進 log，不寫 disabled sentinel。`free_guard` 模型清單檢查只管第四腿 Jev，零 `usage.cost` 檢查涵蓋第一腿 OpenRouter Perplexity 與第四腿 Jev；Drex 回件沒有 cost 欄，hook 用 input_tokens 算 `cost_usd_est` 記進 log，不寫 disabled sentinel、不啟動冷卻。贈額用盡時 nace 回錯誤，hook 記 `unavailable`，不自動儲值。

分類 API timeout 第一腿 3.0 秒、第二腿 2.5 秒、第三腿上限 4.5 秒（按剩餘預算動態夾限）、後兩腿 1.2 秒／腿，同一腿不重試；`/v1/credits` 查核最多 2.0 秒、Jev 零價模型清單查核最多 5 秒，兩者最多快取一小時，都在背景執行且常態落於 `settings.json` `Stop` 10 秒上限內，不拖住 prompt。每日最多 1,000 個候選回合／4,000,000 request bytes，每小時最多 250 個候選回合／1,000,000 bytes，五腿共用、每候選回合在送出前預留一次（若前腿送出後失敗再轉後腿，該回合實際會送出多次請求）。byte 預算是本機候選回合上限，不宣稱等同 provider token 計費或強制美元封頂。第一腿 400／404／429／缺失零價啟動 `pplx_cooldown_until` 一小時冷卻、第二腿 Vercel 402／403／404／429 啟動 `vercel_cooldown_until` 一小時冷卻、第三腿 AMD 400／402／403／404／429 啟動 `amd_cooldown_until` 一小時冷卻、第四腿 Jev 429／缺失零價啟動 `cooldown_until` 一小時冷卻（冷卻中跳過該腿往後退）；paid cost 契約違反另留 disabled sentinel，五腿一起停，需人查核後恢复。免費 lane 的供應商契約仍可能改變，client 不是供應商計費的強制邊界。

## Surface 與生命週期

| 面 | 所有權／路徑 |
|---|---|
| Locked | 本 hook、共用 helper、凍結 question；bootstrap 按本次使用者批准加接線；update 需使用者批准、fixture／harness 重驗與 commit |
| Editable | pending／去重／quota state，由 hook 以安全 regular-file 操作更新；`pending` 暫存當輪清理後最多 4,000 字元的助理回覆（供下輪比對是否過期，消費或下一輪 Stop 即覆寫），不存使用者提問或 memory 檔案本文 |
| Append-only | `logs/auto-memory-jev.jsonl`，純 log；只存匿名 session／turn hash、判定、usage、延遲、delivery version／skip reason |
| Human-controlled | settings 接線、停用與 trial KEEP／MODIFY／KILL；`JEV_MEMORY_DISABLE=1` 或 `hooks/state/auto-memory-jev.disabled` 可立即停自動入口（五腿一起停），手動不受影響；`~/.cli-proxy-api/keys.env`（`CLIPROXY_KEY_CC`／`ADMIN`）與 Keychain `jev-api-key`／`experiential-api-key`／`nace-api-key` 及儲值由使用者管 |

Recovery：建立停用 sentinel 或移除這兩條 settings entry；共用 helper 可繼續服務手動 checkpoint。停用不刪 log／state／memory。壞掉的 log、state、lock、long marker（symlink／hard link／FIFO）不讀寫、不等候，該次提示跳過。

## 盲區與失敗路徑

| 場景 | 行為／限制 |
|---|---|
| Jev false negative／開放提案被當 settled | main 仍負責回查與判斷；手動入口照常；trial 不把分類分數當效益 |
| prompt injection／秘密藏在未識別形式 | state 明示不可信；只输出固定提醒，常見敏感形狀在 clipping 前拒送；不是可靠 egress security gate |
| Bash／helper 寫 memory 沒有直接 Write/Edit trace | 可能漏掉 already-handled；Jev 題與 main 查重補位，review 回查原 trace，不宣稱全覆蓋 |
| compact／換人類回合／已有 memory 寫入／手動收尾 | pending stale 或 redundant 就放棄；自動不碰 manual trigger sentinel |
| 同 Stop 多次／同封包重播／並行 callback | session lock＋turn hash 去重；不等待 lock。API 回來後再查來源是否仍一致 |
| idle、headless teardown 或沒有下一個人類 prompt | 提醒可能不送達；不靠 asyncRewake 冒充非阻擋。不把 pending 數當注入／遵循數 |
| Drex 腿與 Jev 校準不同 | 同題同門檻下 Drex v2.0 觸發略少（120 回合對照 11 對 16、一致 107/120）；五腿的判定在 log 以 `model` 欄分軌，review 分開統計、不混算 |

## 驗證與 trial

Tests: `python3 hooks/auto-memory-jev.test.py`、`bash hooks/checkpoint-judge.test.sh`、`python3 hooks/auto-memory-jev.harness.test.py`；隔離真實 Claude harness probe 使用本機假 API 與假 Jev，不碰正式 log／memory 或付費服務。已命中／未命中／邊界／錯誤／生命周期／旁路不變／病態檔案均須覆蓋。

Trial 指針在個人 projects 的 active trial ledger。Review +7 天：看自然送達後是否真回查既有 memory、合理更新／新增／skip、重複與不必要中斷、API unavailable／cost／用量、以及對手動觸發的回歸。0 delivery 先區分沒出題、沒有下一次 prompt、判官漏抓、或接線缺席，不用更多 prompt tuning 湊成功。
