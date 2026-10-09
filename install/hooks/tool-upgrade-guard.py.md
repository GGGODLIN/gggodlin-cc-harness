一次升級很多工具時，個別工具的釘版或配套步驟容易被漏掉；這支 gate 在升級指令命中登記過的工具時要求先處理注意事項。

**安裝**：把 `hooks/tool-upgrade-guard.py` 複製到 `~/.claude/hooks/tool-upgrade-guard.py`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `PreToolUse`（matcher `Bash`）：`python3 ~/.claude/hooks/tool-upgrade-guard.py`

**必要檔案**：工具清單 `~/.claude/references/tool-upgrade-notes.json`（可用環境變數 `TOOL_UPGRADE_NOTES` 改位置）。沒有這份檔、或格式不對時，任何升級指令（`brew install／upgrade`、`npm i -g`、`uv tool install` 等）都會被擋下，這是刻意的往拒絕失敗。先從 `examples/tool-upgrade-notes/tool-upgrade-notes.json` 複製一份再改成自己的工具。`mode` 填 `nudge` 只提醒；填 `pinned` 還要補釘版欄位，欄位規則見 hook 的 `load_json`。

**確認生效**：跑一次 `brew upgrade example-cli`（換成清單裡的別名），應該看到 gate 的注意事項。要暫停整支 gate，建立 `~/.claude/hooks/tool-upgrade-guard.off`。

**測試**：`hooks/tool-upgrade-guard-npm.test.py`、`hooks/tool-upgrade-guard.test.sh`；裡面的路徑照原作者的機器寫，換環境可能要改。
