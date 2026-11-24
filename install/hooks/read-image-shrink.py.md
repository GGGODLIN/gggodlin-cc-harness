在 `Read` 讀取超大尺寸圖片前自動縮放至合理邊長並改讀縮圖，避免高解析度截圖一次吞掉過多圖片 token 或觸發 API 尺寸上限。

**安裝**：把 `hooks/read-image-shrink.py` 複製到 `~/.claude/hooks/read-image-shrink.py`，保留執行權限（需 Python 與 Pillow 或 macOS `sips`）。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `PreToolUse`（matcher `Read`）：`/opt/homebrew/bin/python3 -I ~/.claude/hooks/read-image-shrink.py`

**測試**：`hooks/read-image-shrink.test.py`。
