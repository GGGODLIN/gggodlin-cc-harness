派 subagent 時沒指定模型，會默默繼承 main 的（可能最貴的）模型；這支 gate 要求派工符合模型路由規則。

**安裝**：把 `hooks/T2-routing-gate.sh` 複製到 `~/.claude/hooks/T2-routing-gate.sh`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `PreToolUse`（matcher `Agent`）：`~/.claude/hooks/fable-gate.sh ~/.claude/hooks/T2-routing-gate.sh`
這支 hook 透過 `hooks/fable-gate.sh` 包裝註冊；不裝 fable-gate 時，把指令裡的包裝器拿掉即可。

**需要自己接**：後端標記 CC_VENDOR（見 `WIRING.md`）。

**測試**：`hooks/T2-routing-gate.test.sh`；裡面的路徑照原作者的機器寫，換環境可能要改。
