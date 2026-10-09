session 用量接近上限時沒人注意，撞牆後工作就斷在半路；這支 hook 在用量超過門檻時提醒掛上 session-monitor。

**安裝**：把 `hooks/session-limit-nudge.sh` 複製到 `~/.claude/hooks/session-limit-nudge.sh`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `PostToolUse`（matcher `*`）：`~/.claude/hooks/session-limit-nudge.sh`

**需要自己接**：多帳號與帳號判定、額度資料來源（見 `WIRING.md`）。
