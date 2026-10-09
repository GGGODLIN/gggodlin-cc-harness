Bash 工具的工作目錄會跨呼叫保留，一次相對 cd 之後的指令可能在錯的目錄跑；這支 hook 偵測相對 cd 並提醒。

**安裝**：把 `hooks/cd-cwd-persistence-nudge.sh` 複製到 `~/.claude/hooks/cd-cwd-persistence-nudge.sh`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `PreToolUse`（matcher `Bash`）：`~/.claude/hooks/fable-gate.sh ~/.claude/hooks/cd-cwd-persistence-nudge.sh`
這支 hook 透過 `hooks/fable-gate.sh` 包裝註冊；不裝 fable-gate 時，把指令裡的包裝器拿掉即可。
