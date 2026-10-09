Self-Verify 稽查第一次沒過時，main 容易再派一次 auditor 或叫它改判，讓稽查失去意義；這支 gate 擋下同一回合對同一 skill 的第二次稽查。

**安裝**：把 `hooks/skill-verify-once-gate.py` 複製到 `~/.claude/hooks/skill-verify-once-gate.py`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `PostToolUse`（matcher `Agent`）：`python3 ~/.claude/hooks/skill-verify-once-gate.py post-agent`
- `PreToolUse`（matcher `Agent`）：`python3 ~/.claude/hooks/skill-verify-once-gate.py pre-agent || exit 2`
- `PreToolUse`（matcher `SendMessage`）：`python3 ~/.claude/hooks/skill-verify-once-gate.py pre-sendmessage || exit 2`

**測試**：`hooks/skill-verify-once-gate.test.py`；裡面的路徑照原作者的機器寫，換環境可能要改。
