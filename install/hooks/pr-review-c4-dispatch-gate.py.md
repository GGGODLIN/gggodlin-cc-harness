pr-review 的多目標審查若在選席與確認前就派 agent，會燒掉額度又得不到可比較的結果；這支 gate 檢查派工前的條件。

**安裝**：把 `hooks/pr-review-c4-dispatch-gate.py` 複製到 `~/.claude/hooks/pr-review-c4-dispatch-gate.py`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `PreToolUse`（matcher `Agent`）：`~/.claude/hooks/pr-review-c4-dispatch-gate.py || exit 2`

**測試**：`hooks/pr-review-c4-dispatch-gate.test.py`；裡面的路徑照原作者的機器寫，換環境可能要改。
