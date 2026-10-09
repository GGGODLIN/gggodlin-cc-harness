PR review 報告被 agent 從流程外直接改寫，就不再是審查的原始結果；這支 gate 只允許經過 pr-review 流程的寫入。

**安裝**：把 `hooks/pr-review-report-write-gate.py` 複製到 `~/.claude/hooks/pr-review-report-write-gate.py`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `PreToolUse`（matcher `Write|Edit`）：`python3 ~/.claude/hooks/pr-review-report-write-gate.py`
