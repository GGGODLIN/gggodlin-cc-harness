---
description: Use when：session-limit-nudge hook 注入 95% 提醒時、啟動長時間無人值守工作（/goal、長 plan 執行）想預掛保險時、使用者問「session 撞 5h 額度怎麼自動續跑」時、或想停掉已掛的 watcher。Do not use for：背景 Workflow 的限額守護（那是 /workflow-monitor 的事，它需要 pause/resume + journal cache，session 不需要）、互動式對話（撞牆後使用者手動續即可）、額度以外的 session 錯誤處理。
---

# /session-monitor — session 層 5h 額度恢復自動續跑

`$ARGUMENTS`:
- `arm` — 掛 watcher（預設）
- `off` — 停掉 watcher
- 空 → 本 session 已有 watcher 在跑就回報狀態（pgrep 的存活 PID + 當前帳號 5h utilization，讀 quota cache 即可），沒有就 arm

## 機制（零件全部沿用 workflow-monitor 2026-06-06/07 的實測驗證）

🔌 接線點：額度資料來源 — 見 WIRING.md
- **喚醒橋** = main session 自己 `Bash(run_in_background=true)` 起的背景程序，exit 時 re-invoke main session。hook 或外部起的程序沒有這個橋，所以 arm 必須由 main session 執行（hook 只負責注入提醒）。
- **session 不需要 pause/resume**：對話 context 留在記憶體裡，撞牆 → 等恢復 → 直接繼續就接得上（使用者實證 2026-06-12）。watcher 純粹是鬧鐘。
- **rolling window 在 `resets_at` 當下歸零**（2026-06-06 實測 94%→0%），所以「等 ≤5%」的語意成立。

## Step A — ARM

1. 去重以「**本 session 是否已 arm 過**」為準——看自己 context 裡有沒有起過這支 watcher。`pgrep -f session-limit-watch.sh` 只是輔助：喚醒橋是 per-session 的，pgrep 抓到的可能是**別的 session** 掛的 watcher，那支醒不了你；跨 session 撞名時寧可多掛一支（無害，多醒一次而已）也不要因 pgrep 誤判而裸奔。本 session 已掛過才到此結束。
2. 起 watcher（必須 main session 自己起，理由見機制段的喚醒橋）：

   ```
   Bash(run_in_background=true): bash ~/.claude/scripts/session-limit-watch.sh 5 60 330
   ```

   參數 = LOW_THRESHOLD（≤5% 視為恢復）/ 輪詢秒數 / 安全超時分鐘（330 ≈ 蓋滿一個 5h 窗口）。
3. 驗證 watcher 活著：`sleep 2; pgrep -f session-limit-watch.sh`，要看到 PID。秒退（路徑錯 / 權限）就修了重掛，不要在無保險狀態下繼續燒最後幾 % 額度。
4. 進度落盤：手上的自主工作若有可落盤的進度（做到第幾項、決策、下一步），順手寫進 cwd 的 STATE.md 或同等檔案（有 /state-update 就用它）。恢復路徑依賴「CC 保持開著」這個單點——萬一 CC 被關或 watcher timeout，落盤的進度是唯一備援。
5. 簡短告知使用者：watcher 已掛，撞牆後保持 CC 開著，額度恢復會自動續跑；想提前換帳號直接 in-session `/login`，watcher 會跟著新帳號立即觸發。
6. 回到原本的工作。之後兩種喚醒結局：
   - watcher 印 `SESSION-LIMIT-WATCH ... ACTION: 額度已恢復...` → 照它說的直接繼續被中斷的工作（watcher 觸發即 exit，不必 pkill）；已被使用者手動續上就簡短回報後收尾。
   - watcher 印 `safety-timeout`（exit 2）→ 額度 330 分鐘內沒恢復過（罕見），回報使用者並問要不要重掛。

## Step B — OFF

1. `pkill -f session-limit-watch.sh 2>/dev/null; echo "session watcher stopped"`
2. 工作自然完成、不再需要保險時也走這步——別讓 watcher 留著在額度恢復時無意義喚醒一次。

## 與 workflow-monitor 的邊界

- 背景 Workflow 撞限額 → `/workflow-monitor`（它要 TaskStop + journal cache resume）。session 本體撞限額 → 本 command。兩者可同時掛，watcher 腳本檔名刻意分開（`session-limit-watch.sh` vs `workflow-limit-watch.sh`），pgrep 簽名互不干擾。

## 自動觸發接線

`~/.claude/hooks/session-limit-nudge.sh`（PostToolUse matcher `*`）在當前帳號 5h ≥ 95% 時注入提醒，引導 invoke 本 command 的 arm 模式。靜默條件：< 95% / 已有 watcher（pgrep）/ 10 分鐘 debounce（marker `~/.claude/cache/session-limit-nudge.last`）/ `CC_VENDOR` 已設（vendor session 直接靜默，2026-06-19 加——vendor session 燒自家 quota 非 Anthropic 5h）。門檻可用 env `SESSION_NUDGE_THRESHOLD` 覆寫（測試用）。收到注入時自判：長時間自主工作 → arm；純互動對話 → 忽略。

## 踩過的坑
一條坑被上游修掉或被後續條目取代就刪掉，不疊放。

- **watcher 檔名不能跟 workflow-limit-watch.sh 共用**——workflow-monitor 用 `pgrep -f workflow-limit-watch.sh` 去重，共用檔名會讓兩邊互相誤判「已有 watcher」而跳過 arm（2026-06-12 設計期攔下）。
- **arm 必須趕在被鎖死之前**——撞到 5h 上限後模型發不出任何 tool call，watcher 起不了。這就是 95% nudge 存在的理由；nudge 沒接到（例如單一巨型 turn 內從 80% 直衝 100%）就只能等使用者手動續。
- **pgrep 是機器級不是 session 級**（2026-06-13 GREEN 測試 subagent 抓到）——喚醒橋只對「自己起的」watcher 有效，別的 session 掛的 watcher 醒不了你。所以 arm 去重看自己 context、不全信 pgrep；nudge hook 的 pgrep 抑制同樣有跨 session 誤抑制的盲點，多 session 同時無人值守時第二個 session 要靠手動 `/session-monitor arm`。
