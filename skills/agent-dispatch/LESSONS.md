# LESSONS

每條一行；規則落地到 SKILL.md 後就刪敘事。

- brief 寫「用 implement 做這張票（TDD required）」被 worker 讀成授權，跳過 implement 的問題輪 → 模板加「問題輪照常問、不代答」。
- main 自己寫的一句判讀（「截圖 parked 可接受」）被 worker 當使用者裁決寫進交付 → 原話逐字加標籤、判讀另段；worker 宣稱授權前先找人類 turn。
- 一票一 worker 讓每票各跑 review 與 mutation，成本翻倍 → 一包票一 worker。
- watcher 從 nohup 殼送中文被 herdr 拒 UTF-8 → `LC_ALL` 加 ASCII 訊息；被 kill 的 watcher 送出假喚醒 → rc ≥ 128 不送。
- watcher 腳本放 scratchpad，`/resume` 後消失 → 放 skill `scripts/`。
- review-implement 在 worker 裡連被 routing gate 拒六次（gate 要真人在 invoke 下一輪回答）→ review 由 main 對 worktree 跑。
- 做完的 worker tab 留著，使用者分不清哪個還活著 → 對帳完 `tab close`、留 session id。
- 手動截圖放 `test-results/`，被後跑的 e2e 清掉、票檔引用變空 → 收據目錄選不會被測試清的位置。
- firstmate 不適用：每次派工 reset 到 `origin/<default>`，acme 開發基準是 `stage` 且要疊在本地 feature branch 上。
- Self-Verify 段不加：產出（brief、狀態檔更新）可對表，但頻率與 rubric 條數還不夠支撐多派一個 subagent；累積幾次真實派工後再評估。

- 2026-09-16 `start-worker.sh`：`herdr tab create` 回來後立刻 `herdr agent start` 可能撞 `agent_pane_busy: agent target pane … is not an available shell`（shell 尚未就緒的競態；同一台機器另一支 worker 在跑時出現一次）。tab 已建好、pane 上是乾淨 shell 提示時，直接對同一個 pane 重跑 `herdr agent start <name> --kind claude --pane <pane> -- --model … --effort …`，再手動送「讀 brief」prompt 與掛 watcher 即可，不要重建 tab。可考慮在腳本 tab create 之後加 `sleep 2` 或重試一次。

## 2026-09-16 worker 與 main 同 worktree 時 worker-turns.py 撈錯 session

`scripts/worker-turns.py <worktree>` 用 cwd 找 jsonl，main 自己也在同一個 worktree 開 session 時會撈到 main 的 jsonl（human 欄位是使用者對 main 說的話、last_assistant 是 main 的回覆）。症狀：`main` 欄位是空陣列、`human` 一大串與 worker 無關。解法：拿 start JSON 的 `session_id` 直接讀 `~/.claude/projects/<cwd-slug>/<session_id>.jsonl`，不要靠 cwd。順帶：herdr-watch 在本機記憶體吃緊時會被 OS 殺掉（拉 codegen 期間 saas dev server 開著就撞過一次），watcher 被殺沒有通知、只有 task-notification status=killed；用完即關 dev server 再重掛。
- 2026-09-23 worker 生命週期沒定義：View A 兩天同一 worker 續派六包一路不關，saas 舊 worker 則不知何時消失。RED（fresh routed-judge）讀舊文照 L103 會在 Step 4 末尾關 tab，但「本次」在多包續派下無解、PR 留言回修用誰 skill silent。修法＝Step 4 第 5 點改成可觀察條件「branch 開了 PR（含 Draft）才關、還有下一包就續派並在狀態檔寫『續派中、待哪一包』」＋Step 5 加「PR 留言另派新 worker、不 resume 舊 session」。GREEN／REFACTOR（各一 fresh routed-judge）：PR 後關兩隻並另派新 worker；壓力情境「交完就關省資源」「resume 舊 session 最懂」皆不採、引 L101／L109。契約測試 explicit-consent ok。
