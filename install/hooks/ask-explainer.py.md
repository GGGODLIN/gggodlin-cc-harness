只會回「需要確認」的 gate 讓人看不懂為什麼被擋；這支包裝器在任一會跳確認框的 gate 外面附上一段白話說明。

**安裝**：把 `hooks/ask-explainer.py` 複製到 `~/.claude/hooks/ask-explainer.py`，保留執行權限。

公開版的 settings.json 沒有它的註冊（原作者唯一包住的 gate 不公開）。用法：在要包的 gate 指令前面加 `python3 ~/.claude/hooks/ask-explainer.py`，例如 `python3 ~/.claude/hooks/ask-explainer.py python3 ~/.claude/hooks/<你的 gate>.py || exit 2`。

**測試**：`hooks/ask-explainer.test.py`；裡面的路徑照原作者的機器寫，換環境可能要改。
