---
name: deep-check
description: 全 repo 深度健檢的單一入口，也接單獨掃描某個模組或系統的狀態機與記憶波及長尾清查。Use when 使用者說「深度健檢／完整健檢／全 repo 健檢／deep check／跑完整版」、要求全庫設計與一致性檢查、要求掃某個模組或系統的（隱含）狀態機找 bug、要求清查記憶波及長尾候選，或 implement 收尾問要不要跑 /deep-check 而使用者同意。Do not use for 單票收尾的簡單版檢查（implement 收尾已內建）、每日例行前 8 檔記憶波及巡檢（memory-audit M-1 已內建）、implement 開工時選的狀態與併發核驗（照 implement）、畫狀態圖（diagram-route）、用 prototype 試狀態機設計（prototype）、修已知的狀態機 bug（debugging）、只想跑 mutation testing（mutation-testing）、多輪調優單一效能指標（hillclimb）、安全審查（security-review）、PR 審查（pr-review）。
---

<!-- 本檔在契約測試底下：python3 ~/.claude/commands/tests/test_ub_mode_grafts.py；python3 ~/.claude/commands/tests/test_skill_verify_one_shot_callers.py -->

# Deep Check

各項檢查的完整版平常沒有接線，很少被想起來；這裡把它們收成一張清單，依 repo 實況挑項。做法正本在 `~/.claude/references/verification-recipes-and-probes.md`（下稱 recipes）與 `mutation-testing` skill，本檔只管挑項與回報，不重寫做法。

如果使用者只要求掃某個模組或跨 repo 系統的狀態機（不是全 repo 健檢），就不跑下方清單與流程，在動手前讀 recipes「狀態與併發三版核驗」第 4–6 點，照其中的單獨掃描做；產出照該段，不出七項判定表、不跑本檔 Self-Verify。

如果使用者只要求清查記憶波及長尾候選（不是全 repo 七項健檢），就不跑下方清單與流程，在動手前讀 recipes「深度健檢完整版」第 4 點，照其中的記憶波及長尾清查執行並回報（每條發現附 `檔名:行號`、BM25 分數、重現指令與建議修法，只產報告不改記憶檔，不出七項判定表、不跑本檔 Self-Verify）；如果是對 `~/.claude` 跑全 repo 健檢，就在完成七項判定表外一併執行 recipes「深度健檢完整版」第 4 點併入報告。

## 清單

| 項目 | 適用條件 | 做法正本 |
|---|---|---|
| CRAP 全 repo 熱點 | 任何有原始碼的 repo；產不出覆蓋率時降為只看複雜度並寫明 | recipes「深度健檢完整版」第 1 點 |
| 全 repo 結構重複 | 任何有原始碼的 repo | recipes「深度健檢完整版」第 2 點 |
| mutation testing | JS/TS 或 Python，且目標模組已有綠燈測試 | `mutation-testing` skill；Python 走其 mutmut 路徑 |
| 冪等實跑 | 有 webhook、排程、會重試的背景工作或 migration | recipes「深度健檢完整版」第 3 點 |
| 狀態與併發核驗 | 有多步狀態機、跨 session 搶鎖、超時與重試交錯 | recipes「狀態與併發三版核驗」，預設第二版；找到要在規格定案的交錯流程才在待拍板建議第三版 |
| 驗證配方完整版 | repo 已有頁面或功能的驗收配方 | recipes「驗證配方維護」第 5 點 |
| 全庫設計與一致性檢查 | 有可確認共同契約的同職責模組，或有專案明示的依賴邊界；兩種方法分別判定 | 如果選中本項，就在取證前讀 recipes「全庫設計與一致性檢查」 |

Python 的 mutation testing 走 `mutation-testing` 的 mutmut 路徑（該 skill 的 `references/python-mutmut.md`），只挑測試全綠的模組跑。存活複驗出現假存活（套回後測試轉紅）時，這項判「跑了：結果不可信」並寫明哪幾個；測試無法被 pytest 收集時判「跳過：測試無法被 pytest 收集」並寫明卡在哪。

## 流程

1. 盤點 repo 實況與既有健檢帳本：
   - 檢查 `~/.claude/skills/deep-check/state/<repo-slug>.json`（核對檔案內的 `repo_path` 是否與目標 repo 絕對路徑相符；若同名目錄衝突則改用 `<parent>-<repo>` 作為 slug）是否存在，若存在則載入既有的 `wontfix` 清單（每筆含 `category`、`location`、`summary`、`reason`、`recorded_at`；帳本不進受檢產品或專案 repo，也不算、不存任何檔案內容雜湊）。
   - 盤點語言、測試與覆蓋率能不能產出、有沒有寫入入口（webhook、排程、重試工作、migration）、有沒有狀態機或搶鎖、有沒有驗收配方、同職責模組或明示依賴邊界。完成條件：已讀取或確認無既有帳本，且清單每一項的適用條件都有一句判斷依據（檔名、目錄或指令輸出），然後接 Step 2。
2. 逐項判定跑或跳過：清單七項全部進判定表，跳過的附原因；使用者點名的項目除非適用條件不成立，否則一定跑。完成條件：七項都有「跑／跳過＋原因」；全庫設計項另列兩種取證方法各自跑／跳過的理由，然後接 Step 3 讀選中方法的正本。
3. 照做法正本執行選中的項目。這是健檢不是修復：不改產品程式碼、不 commit、不打正式環境、不真的扣款或發訊息；公司 repo 的 push 與開 PR 照既有規則先問。完成條件：每個選中項目都有工具輸出，或寫明卡在哪一步，然後接 Step 4。
4. 過濾既有 `wontfix` 並依下方報告格式成稿：
   - 對照 Step 1 載入的 `wontfix` 清單：只有當發現的 `(category, location, summary)` 與已拍板舊債屬於同一筆問題（例如同一組結構重複或未惡化的同一熱點）時才直接略過不重報，並在報告末尾註記「已依健檢帳本略過 N 筆既有舊債」；若同一函式位置出現不同 `summary`（新對照組或指標明顯惡化），仍照常列出並標註「此位置另有舊裁決」，不把整個位置永久豁免。
   - 先不輸出報告，完成後接 Step 5。

報告格式：

- **判定表**：七項各一行「項目｜跑了／跳過｜結果摘要或跳過原因」；全庫設計項附同職責對照與依賴取證的實際範圍、證據與缺口
- **發現清單**：依嚴重度排序，每條附 `檔名:行號` 與重現指令或工具輸出位置（附註已依健檢帳本略過的既有舊債筆數）
- **沒查到的部分**：工具缺口（例如全 repo 改名複製）、跳過項、未驗證的假設
- **待拍板**：哪些發現要修、哪些標為舊債不修（`wontfix`），由使用者決定

## 5. Self-Verify

報告成稿後、呈現前，派一個稽核 agent 對表。

- `Agent` tool、`subagent_type: skill-verify-auditor`；Agent 的 description 必含 marker 字串 `skill-verify:deep-check`
- prompt 內嵌完整報告原文與下方 rubric 全文
- 本回合這個 skill 只有一次 auditor 額度：不論結果如何都不重派 auditor，也不用 SendMessage 續問同一個 auditor

Rubric（原文嵌入，`{report}` 換成報告全文）：

```
你是 adversarial 合規審查員，檢查一份 repo 深度健檢報告。偏置是找違規：無法從報告文本確認有遵守就判 FAIL。

報告原文：
{report}

逐條檢查（每條回 PASS / FAIL + 一句證據引述）：
R1【七項判定】判定表是否七項都在（CRAP 全 repo 熱點、全 repo 結構重複、mutation testing、冪等實跑、狀態與併發核驗、驗證配方完整版、全庫設計與一致性檢查），每項標跑了或跳過，跳過的附原因？全庫設計項是否另列同職責對照與依賴取證各自的跑／跳過理由？
R2【發現可追】每條發現是否附檔名:行號，以及重現指令或工具輸出位置？全庫設計 finding 是否有共同契約＋差異與 caller 證據，或專案邊界＋實際依賴邊，並說明違約影響？沒有任何發現且明寫「無發現」= PASS。
R3【沒有越權】報告是否顯示健檢期間沒有改產品程式碼、沒有 commit／push、沒有打正式環境？報告提到做了其中任一件 = FAIL。
R4【缺口誠實】是否有「沒查到的部分」段，列出工具缺口或跳過項？

最後一行只能是下列兩種之一：
VERDICT: COMPLIANT
VERDICT: VIOLATIONS: <R 編號逗號列表>
```

## 6. 呈現

報告全文放在回合最終訊息，末尾附一行 self-verify 狀態，只能是下列四種之一：

- 全 PASS → 「🔎 self-verify: COMPLIANT (4/4)」
- 有 FAIL 且已修正 → 先修報告再發，標「🔎 self-verify: FIXED_AFTER_AUDIT — R#（…）」並寫明「未經第二次獨立稽查」
- 有 FAIL 且修不掉 → 標「🔎 self-verify: FAILED — R#（缺口）」，並把撐不住的發現或判定刪除或收窄，不原樣交付
- 稽核 agent 失敗（timeout、空輸出、格式錯誤、agent error）→ 報告照發，標「🔎 self-verify: SKIPPED (agent error)」

報告呈現交付時，立即更新 `~/.claude/skills/deep-check/state/<repo-slug>.json` 的 `repo_path`、`checked_at`（當日 `YYYY-MM-DD`）、`head_sha`（受檢時 `git rev-parse --short HEAD`）與 `items_judged`（不等待使用者回覆修不修）；後續使用者在「待拍板」明確決定某筆舊債不修時，再將該筆 `(category, location, summary, reason, recorded_at)` 追加進 `wontfix`；若使用者是在久未執行提醒回覆跳過該 repo，則僅更新 `skipped_at`，不冒充已執行。

