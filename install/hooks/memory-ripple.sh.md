新增一條 memory 時，同主題的舊記憶可能已經過時或互相矛盾；這支 hook 在寫入 memory 後找出可能要一起更新的兄弟檔。

**安裝**：把 `hooks/memory-ripple.sh` 複製到 `~/.claude/hooks/memory-ripple.sh`，保留執行權限。
同時複製它用到的同名檔：`hooks/memory-ripple-gemini-prompt-v1.txt`、`hooks/memory-ripple-runtime.py`。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `PostToolUse`（matcher `Write|Edit`）：`~/.claude/hooks/memory-ripple.sh`

**需要自己接**：跨模型後端（見 `WIRING.md`）。

**測試**：`hooks/memory-ripple.test.sh`；裡面的路徑照原作者的機器寫，換環境可能要改。
