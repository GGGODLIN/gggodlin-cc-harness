對家目錄或 `~/.claude` 執行無限制遞迴搜尋卻忘記排除 `projects/`，會掃進數萬份歷史對話紀錄而卡死逾時；這支 gate 攔截未排除 `projects` 的大範圍搜尋與未加 `command` 前綴的遞迴 `grep`。

**安裝**：把 `hooks/code-search-root-gate.py` 複製到 `~/.claude/hooks/code-search-root-gate.py`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `PreToolUse`（matcher `Bash`）：`python3 ~/.claude/hooks/code-search-root-gate.py`

**測試**：`hooks/code-search-root-gate.test.py`。
