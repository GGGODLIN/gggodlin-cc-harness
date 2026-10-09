agent 用 rm 誤刪的檔案直接消失、救不回來；這支 hook 在 session 開始時把「rm 改丟垃圾桶」的 shim 放到 PATH 最前面。

**安裝**：把 `hooks/better-rm-env.sh` 複製到 `~/.claude/hooks/better-rm-env.sh`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `SessionStart`：`/bin/sh ~/.claude/hooks/better-rm-env.sh`

**需要自己接**：better-rm（見 `WIRING.md`）。

**測試**：`hooks/better-rm-env.test.sh`；裡面的路徑照原作者的機器寫，換環境可能要改。
