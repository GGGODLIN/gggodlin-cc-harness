SKILL.md 的 description 寫得太空泛，skill 就不會在該觸發時觸發；這支 hook 在寫入 SKILL.md 後檢查 description 的品質。

**安裝**：把 `hooks/skill-description-gate.sh` 複製到 `~/.claude/hooks/skill-description-gate.sh`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `PostToolUse`（matcher `Write|Edit`）：`~/.claude/hooks/skill-description-gate.sh`

**測試**：`hooks/skill-description-gate.test.sh`；裡面的路徑照原作者的機器寫，換環境可能要改。
