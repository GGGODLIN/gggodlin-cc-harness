規則要求用繁中回報，但某些模型收尾時會整段改用英文；這支 hook 偵測英文結案並提醒改回繁中。

**安裝**：把 `hooks/opus-chinese-stop.py` 複製到 `~/.claude/hooks/opus-chinese-stop.py`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `Stop`：`python3 ~/.claude/hooks/opus-chinese-stop.py`

它優先讀 statusline 寫在 `/tmp/cc-widget-cache/model-<session>.txt` 的模型名稱，沒有這個快取時改讀 transcript，所以不裝 statusline 也能用。

**測試**：`hooks/opus-chinese-stop.test.py`；裡面的路徑照原作者的機器寫，換環境可能要改。
