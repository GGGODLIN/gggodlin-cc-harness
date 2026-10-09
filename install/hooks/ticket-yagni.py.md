ticket 交付時常夾帶規格沒要求的額外功能；這支 hook 在交付前對 ticket 做一次 YAGNI 審查並把結論送回 main session。

**安裝**：把 `hooks/ticket-yagni.py` 複製到 `~/.claude/hooks/ticket-yagni.py`，保留執行權限。
同時複製它用到的同名檔：`hooks/ticket-yagni-runner.py`。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `PostToolUse`（matcher `Agent`）：`python3 ~/.claude/hooks/ticket-yagni.py register`
- `PreToolUse`（matcher `Edit|Write|MultiEdit`）：`python3 ~/.claude/hooks/ticket-yagni.py gate`
- `UserPromptSubmit`：`python3 ~/.claude/hooks/ticket-yagni.py deliver`

**需要自己接**：跨模型後端（見 `WIRING.md`）。

**測試**：`hooks/ticket-yagni-pi.test.py`、`hooks/ticket-yagni-prompt-source.test.py`、`hooks/ticket-yagni-runner-unreviewed.test.py`、`hooks/ticket-yagni-sync-delivery.test.py`、`hooks/ticket-yagni-ticket-file.test.py`、`hooks/ticket-yagni.test.sh`；裡面的路徑照原作者的機器寫，換環境可能要改。
