一次升級很多工具時，個別工具的釘版或配套步驟容易被漏掉；這支 gate 在升級指令命中登記過的工具時要求先處理注意事項。

**安裝**：把 `hooks/tool-upgrade-guard.py` 複製到 `~/.claude/hooks/tool-upgrade-guard.py`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `PreToolUse`（matcher `Bash`）：`python3 ~/.claude/hooks/tool-upgrade-guard.py`

**測試**：`hooks/tool-upgrade-guard-npm.test.py`、`hooks/tool-upgrade-guard.test.sh`；裡面的路徑照原作者的機器寫，換環境可能要改。
