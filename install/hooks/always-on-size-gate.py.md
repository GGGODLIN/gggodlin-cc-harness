防止修改 always-on 規則檔（`CLAUDE.md`、`rules/common/*.md` 等）時無限制膨脹字數與行數；超過上限就攔截寫入並提示先精簡或拆出到 reference。

**安裝**：把 `hooks/always-on-size-gate.py` 複製到 `~/.claude/hooks/always-on-size-gate.py`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `PreToolUse`（matcher `Edit|Write|MultiEdit`）：`python3 ~/.claude/hooks/always-on-size-gate.py`

**測試**：`hooks/always-on-size-gate.test.py`。
