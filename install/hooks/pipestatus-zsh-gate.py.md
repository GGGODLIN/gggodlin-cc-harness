在 zsh 裡用 bash 的 $PIPESTATUS 會拿到錯的值，驗證結果因此被誤判；這支 gate 在外層 shell 不是 bash 時擋下這類指令。

**安裝**：把 `hooks/pipestatus-zsh-gate.py` 複製到 `~/.claude/hooks/pipestatus-zsh-gate.py`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `PreToolUse`（matcher `Bash`）：`python3 ~/.claude/hooks/pipestatus-zsh-gate.py`

**測試**：`hooks/pipestatus-zsh-gate.test.py`；裡面的路徑照原作者的機器寫，換環境可能要改。
