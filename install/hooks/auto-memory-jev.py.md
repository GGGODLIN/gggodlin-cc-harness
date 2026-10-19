該記下來的偏好或決定常在 session 結束後就消失；這支 hook 在回合結束後背景判斷是否值得記，並在下一則提問時提醒。

**安裝**：把 `hooks/auto-memory-jev.py` 複製到 `~/.claude/hooks/auto-memory-jev.py`，保留執行權限。
同時把必備隨附檔案複製到 `~/.claude/hooks/`：`hooks/memory_reminder_common.py`（與 `checkpoint-judge.sh` 共用的提醒文字與注入狀態模組，缺少時本 hook 會直接靜默退出）、`hooks/auto-memory-jev-question.json`（判官題目）、`hooks/auto-memory-jev.md`（設計與邊界說明）。
另外把 `examples/memory/feedback_memory_cluster_maintenance.md` 複製到 `~/.claude/memory/feedback_memory_cluster_maintenance.md`（或保留你自己的版本，需含 `## Tier 1:` 與 `## Tier 3:` 標題供 `memory_reminder_common.py` 抽取兩層索引維護規範）。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `Stop`：`python3 ~/.claude/hooks/auto-memory-jev.py stop`（**必須**設 `"async": true` 才會在背景執行而不阻塞回合結束；建議搭配 `"timeout": 10`）
- `UserPromptSubmit`：`python3 ~/.claude/hooks/auto-memory-jev.py deliver`

**需要自己接**：
- 第一腿免費判官（Experiential Labs `/v1/systemone` 的 `type-safe/jev-latest:free`）：在 macOS Keychain 存入服務名稱 `experiential-api-key`（執行 `security add-generic-password -U -a "$USER" -s experiential-api-key -w` 後依提示互動輸入 API key，避免真 key 留在 shell 命令歷史）。
- 第二腿備援判官（當第一腿 429／逾時／缺 key 時改問 nace `drex-v2.0`）：若 Keychain 存有服務名稱 `nace-api-key`（同樣可用 `security add-generic-password -U -a "$USER" -s nace-api-key -w` 互動存入），第一腿失敗時會自動呼叫第二腿並產生 nace 用量；若你的機器已有同名 key 但不想讓本 hook 呼叫第二腿，或想改接 OpenRouter Decisions 等其他端點，請修改 `auto-memory-jev.py` 的 `run_stop()`／`endpoint()`。
- 停用開關：設環境變數 `JEV_MEMORY_DISABLE=1` 或建立 `~/.claude/hooks/state/auto-memory-jev.disabled` 即可隨時停用自動入口（兩腿一起停）。

**測試**：`hooks/auto-memory-jev.test.py`、`hooks/auto-memory-jev.harness.test.py`；裡面的路徑照原作者的機器寫，換環境可能要改。
