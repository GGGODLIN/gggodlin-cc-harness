---
name: e2e-explore-then-batch
description: Use when e2e-route 已選派 Playwright 普通探索固化、e2e-contract 正式交入 Playwright 契約子集，或使用者手動點名 /e2e-explore-then-batch；包含擴案例與既有契約重跑。Do not use for 從自然語言自行選用（即使已選 Playwright 也先 e2e-route）、未確認契約直接執行、已選 TesterArmy、只修普通紅燈（systematic-debugging）、單元或純 API 測試、一次性驗收、網頁抓取、工具研究或 skill 設計。
---

<!-- 本檔在契約測試底下：node --test skills/tests/ticket-08-skill-structure.test.mjs；python3 ~/.claude/commands/tests/test_skill_verify_one_shot_callers.py -->

<!-- 本檔在契約測試底下：python3 ~/.claude/commands/tests/test_verification_recipe_grafts.py -->

# E2E 探索 → 固化 → 批次

為何固化：proj 實戰三階段驗證（2026-07~08）——agent 驅動探索貴且常 BLOCKED 在環境（8/10-12 spike-evidence）、跑通的軌跡沒人轉寫就死在 session 裡（7/29 probe 靠事後歸檔才留下）、環境解法沉澱成 pw 腳本後重放近乎免費（8/13 真店 E2E）。本 skill 釘死的是「探路成果必須固化成可重放資產」這個轉換步驟；探索怎麼跑的判斷力留給當下。

核心分工：**agent 探路一次，Playwright 重放無限次**。貴的觀察與決策只花在第一次。

## 入口選擇

接受 e2e-route 的普通選派、e2e-contract 的正式契約交接或手動點名。自然語言直接觸發即使已選 Playwright 仍先 `Skill(e2e-route)` 並結束，不先做 Step 1；工具選擇不是經過路由的證據。

如果 e2e-contract 交入或任務帶 `mode=contract`／既有行為契約，就在任何 setup／探索／寫測試／實跑前讀 [共同執行契約](/skills/e2e-contract/references/execution-contract.md)。核對確認子集與操作範圍，按契約模式保存與回傳後結束，不套用下方普通模式的「跑綠才固化」、成功骨架或自由修 case。手動入口只選工具，不批准案例；缺契約資料停止，不回 route 重試或降級普通模式。

普通任務依最新工具選擇接下方產物約定與 Step 1，不重問；這條原流程與原 Self-Verify 不變。

## 產物約定

每個 repo 一個 e2e 資產目錄，內含三件：

```
<e2e-dir>/
├── fixtures.ts          環境解法唯一落點（登入、route 攔截、API 捷徑）
├── specs/*.spec.ts      固化後的測試，只含業務步驟與斷言
└── trajectories/*.md    探索軌跡原始記錄（appendix：實跑輸出）
```

已定約定：oldco-shop → `docs/owner/e2e/`（gitignored 個人空間，2026-08-14 拍板）。其他 repo 首次使用時按專案慣例定位，定了就寫進該 repo 的專案指示。

## Step 1 — 探索（agent 驅動跑通一次）

1. 用可用的瀏覽器面（Chrome MCP / Codex / Playwright-assisted 皆合法）跑通目標 flow 的單一 case。oldco-shop 場景先讀 memory `pw-live-store-e2e-env-traps` 再動手，別重撞已解過的坑。
2. 沿路寫 `trajectories/<flow>-<YYYY-MM-DD>.md`，兩類內容缺一不可：
   - 環境坑＋解法（含機制，不是只寫「繞過了」）
   - 成功軌跡：進入點 URL、每一步的 role/label 定位方式、斷言觀察點、清理動作
3. 卡環境時優先想「node 側網路棧繞過瀏覽器限制」——`context.route` + `route.fetch` / `route.fulfill` 家族能解掉 CDN cookie、LNA 這類瀏覽器層攔截。

完成判準：目標 case 端到端跑通一次，且 trajectory 檔對**每一步**都有定位方式與觀察結果（「大概點了什麼」不算）。BLOCKED 收場 → 記錄阻塞因素後停在這步，先判是環境阻塞還是受測行為問題，環境阻塞照 NEEDS_USER 口徑交使用者。跑通 → 接 Step 2。

## Step 2 — 固化（軌跡 → pw spec）

1. fixture 檔不存在 → 從 `assets/fixture-template.ts` 建；spec 從 `assets/spec-template.ts` 起骨架。
2. 環境解法全部進 `fixtures.ts`，spec 只留業務步驟與斷言。分界：換一個 flow 還會用到的進 fixture，只有這個 flow 用的留 spec。
3. 定位一律 `getByRole` / `getByLabel`；trajectory 裡若只有 CSS selector，先試著升級成 role/label，升不了才保留並在該行註明原因。
4. 轉寫完**實跑一次同 case**——轉寫不算固化，跑綠才算。實跑輸出（含 pass 計數）貼進 trajectory 檔尾。
5. 如果本次固化產生或更動可重用驗證配方，就在清理與 Step 2.5 前讀 `~/.claude/references/verification-recipes-and-probes.md` 的「驗證配方維護」並照做；只更新本次 flow 的既有產物，不另建全站地圖。

完成判準：spec import fixture、spec 內無環境碼殘留、trajectory 檔尾有本次實跑輸出。完成後接 Step 2.5。

## Step 2.5 — Self-Verify（固化完成後、回報使用者前）

派 verify subagent 對照 rubric，不可跳過。dispatch 規格：`Agent` tool、`subagent_type: skill-verify-auditor`、description 固定含 marker `skill-verify:e2e-explore-then-batch`。prompt 內嵌 (1) spec 檔全文 (2) trajectory 檔尾實跑輸出段 (3) 下列 rubric：

```
逐條檢查（每條回 PASS / FAIL + 一句證據引述；偏置找違規，無法確認就 FAIL）：
R1【環境碼歸位】spec 檔內無 context.route / 登入 / cookie 操作等環境碼，且 import 共用 fixture？
R2【定位品質】互動步驟以 getByRole / getByLabel 為主；出現 CSS selector 的行有註明保留原因？
R3【實跑證據】trajectory 檔尾有本次 Playwright 實跑輸出且含 pass 計數？
R4【坑有落點】本次探索遇到的環境解法已在 fixture 中（引述對應 helper 名），或明寫「本次無新環境坑」？
最後一行：VERDICT: COMPLIANT | VIOLATIONS: <R 編號逗號列表>
```

**本回合這個 skill 只有一次 auditor 額度**：不論結果如何都不得重派，也不得用 SendMessage 續問同一個 auditor。回報末尾固定一行，狀態只能是下列四個之一：

- 全 PASS → 「🔎 self-verify: COMPLIANT」
- 任一 FAIL 且已修正 → 先修再回報，標「🔎 self-verify: FIXED_AFTER_AUDIT — R#（抓到什麼、怎麼修的）」，同句明寫「未經第二次獨立稽查」
- 任一 FAIL 且修不掉 → 標「🔎 self-verify: FAILED — R#（缺口）」，並把該條涵蓋的 case 從「已固化」清單移除或降級成草稿，不得當成可重放腳本交付
- verify agent error / timeout / 空輸出 / 格式錯誤 → 照報並標「🔎 self-verify: SKIPPED (agent error)」

完成後接 Step 3；使用者只要固化不擴 case 則到此收工。

## Step 3 — 批次擴 case

1. 拿跑綠的 spec 當骨架，把假設枚舉成 `caseMatrix`（模板已含迴圈形狀），批次跑。
2. 報告口徑固定 `PASS / FAIL / SKIPPED(reason)`——SKIPPED 必附原因，不得靜默 drop。
3. 跑不過的 case 先分型再動手：斷言與預期不符 → 修 case；環境或 flow 漂了（元素消失、路徑變）→ 回 Step 1 用 agent 重探**那一條**，不要在 pw 裡瞎調 selector 硬救。
4. 如果本輪擴 case 或修正了驗證配方，就在清理與回報前讀 `~/.claude/references/verification-recipes-and-probes.md` 的「驗證配方維護」，更新同一份既有產物；未受影響入口不重驗。

完成判準：矩陣每格都有三態之一的結果行，FAIL 的格附觀察到的實際輸出。

## 踩過的坑

- oldco-shop 真店三個環境坑（CDN proxy cookie 帶不到、Chrome LNA 擋 127.0.0.1、stale compiled build）解法細節在 memory `pw-live-store-e2e-env-traps`（2026-08-13 實戰），該場景探索前必讀。
- agent 探索期的 BLOCKED 常是環境不是受測物（OAuth 被 adblock 攔、cookie 撐爆 431——2026-08-12 spike-evidence 實例），誤判成 bug 會白修。
- grep compiled build 驗 route 存在性不可靠（Closure 重組字串），用 runtime 探針（curl 打 endpoint 看 404 vs 401）。
- Playwright 版本要跟 `~/Library/Caches/ms-playwright` 既有 browser build 對上，對不上直接 `chromium.launch({ channel: 'chrome' })` 用系統 Chrome 零下載。
- 宿主 repo 沒有 Playwright 依賴時，在 e2e 資產目錄內自帶獨立 `package.json` 裝 `@playwright/test`，不動 repo 依賴（目錄 gitignored 時尤其該這樣，2026-08-14 GREEN 測試現場發現 oldco-shop 即此型）。
