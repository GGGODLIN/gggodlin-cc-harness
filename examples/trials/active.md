# Active Trials（範例）

> mock 範例：trial 帳本的格式照真實的寫，這筆 trial 是虛構的。實際使用時帳本放在 `~/Desktop/projects/.claude/trials/active.md`，由 trial-review hook 讀 H2 日期提醒到期。

格式：每筆 trial 保留一個 H2，標題格式為 `## <name> (YYYY-MM-DD)`，括號內是 review 日期。H2 下固定三個索引欄位，長段內容放在 `trials/active/<slug>-<started>.md`。

## demo-linter 試用 (2026-01-12)
- started: 2026-01-05
- status: active
- detail: `active/demo-linter-2026-01-05.md`

## 結案 SOP

到了 review 日想結案、不延輪：

1. **Verdict 段**：先讀 `detail` 指針，在長段檔開頭加 `### ✅ [結案 YYYY-MM-DD · <一句結論>] <原標題> (原 review YYYY-MM-DD)` 標題 + verdict 段。
2. **整段剪到 `archived.md`**：把長段檔完整段落剪到 `~/Desktop/projects/.claude/trials/archived.md` 檔末，再從 `active.md` 移除對應 H2 與三個索引欄位。
3. **同步 append 索引行**：用 `python3 ~/.claude/scripts/ledger-lifecycle/ledger-index.py append` 把剛寫入的 archived entry 加進索引並執行 `reconcile`。
4. **資源資料夾搬遷**：執行 `python3 ~/Desktop/projects/.claude/hooks/trial-archive-resources.py <trial-slug>` 搬移試用資源，再把新格式長段檔從 `active/` 搬到 `archive/<trial-slug>/closed-detail.md`。
5. **配套 memory promote（選做）**：有跨任務可轉移的規則才 append 進對應 memory。

---

## demo-formatter 試用 (2026-01-19)
- started: 2026-01-12
- status: active
- detail: `active/demo-formatter-2026-01-12.md`
