# Skill Inventory

最後審計：2026-06-20（schema 加 `Audit` 欄 + 收 project-scoped sections + 對接 daily-local skill-desc-quality channel；目前採增量維護，見下方維護紀律，不每次重做全表審計日）
原 baseline：2026-05-13（49 個 global skill 一次性 provenance audit）

> 主要疑問：「過幾個月後我怎麼知道哪些 skill 是自己寫的、哪些是 clone 來的、來源是哪個 repo？」
> 此 INVENTORY 是給未來自己追溯來源的 source of truth。
>
> **2026-06-20 起本檔同時對接 daily-local `skill-desc-quality` channel**：wrapper 從本檔抽 `Audit = yes` / `Audit = yes (patched)` 的 row + 該 row 所屬 section path = 掃描範圍。維護紀律見尾段「維護紀律」。

## Audit 欄三 value

| Audit           | 含義                                                                                             | 進 daily-local 掃描嗎 |
| --------------- | ------------------------------------------------------------------------------------------------ | --------------------- |
| `yes`           | 純自寫 skill、user 對 description 完全負責                                                       | ✅                    |
| `yes (patched)` | Clone 上游但 user 改過 description（或計畫繼續改）、user 對 patched 後的 description 負責        | ✅                    |
| `no`            | Cloned / synced from upstream、user 不 patch description、上游動態走 skill-upstream-check weekly | ❌                    |

## Global skills (`~/.claude/skills/`)

| Skill                       | Origin                                | Audit         | Source URL                          | 安裝日     | 更新方式       | 備註                                                                                                                                                 |
| --------------------------- | ------------------------------------- | ------------- | ----------------------------------- | ---------- | -------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| ui-diff | imuratalpay/ui-diff (copy patched) | yes (patched) | https://github.com/imuratalpay/ui-diff | 2026-11-21 | frontmatter watch | 固定 `3075b4c8bbbf1a352404829f84f64c26cba291e5`（MIT）；user patched description (2026-11-21)，reason: 補繁中觸發與排除詞 |
| multi-qa | self-written（借 pierridotite/mobile-agent-testers 多角色平行探索與靜態無障礙檢查概念，未複製原碼） | yes | https://github.com/example-owner/claude-config | 2026-11-23 | manual edit | 通用網頁／PWA 多裝置多角色平行探索 QA（Playwright 多分身＋零 LLM 靜態探針＋獨立看圖三態複驗＋非本機機械寫入保護，預留 `agent-device` 真機介面） |
| afk | jakubkrehel/skills (fork patched) | yes (patched) | https://github.com/jakubkrehel/skills | 2026-11-12 | frontmatter watch | 固定 `8b254eb75dadf3615a6abce87aed28e1b6e4d77c`（MIT）；user patched description/body (2026-11-12) |
| multi-ai-ideate | self-written | yes | https://github.com/example-owner/claude-config | 2026-11-21 | manual edit | 多模型平行點子發想（5 席預設 max 檔位＋預檢防閃斷重試） |
| unslop | heydamir/unslop | no | https://github.com/heydamir/unslop | 2026-11-01 | pinned copy + frontmatter watch | 固定 1d13095e4bef6ad6c74f1dd828d84c4ba309a4dc（CC-BY-4.0） |
| review-brainstorm | self-written（借 google/elephant-goldfish-model `/egm-brainstorm` 6-lens Goldfish shootdown 視角隔離設計，未複製原碼） | yes | https://github.com/example-owner/claude-config | 2026-11-23 | manual edit | `brainstorm`／`grill-me` 後 6 席獨立打槍審查（含條件式 Seat 7 與動態並發分批隔離） |
| deep-check | self-written（借 unclebob/ub-mode 的 CRAP 門檻與結構重複概念，未複製原文；評估當時 ub-mode 與其工具無授權條款，故改用 crap-score／lizard／jscpd／Semble；2026-11-25 起工具為 0BSD、Python mutation 改用 mutmut） | yes | https://github.com/example-owner/claude-config | 2026-10-28 | manual edit | 全 repo 深度健檢單一入口：七項按 repo 挑選，含全庫設計與一致性檢查（同職責對照＋依賴取證，借鑑 Desloppify 方法、未複製原碼） |
| hillclimb | self-written（借 cursor/plugins/pstack hillclimb 與 benchmark-checklist 概念，未複製原文） | yes | https://github.com/example-owner/claude-config | 2026-10-28 | manual edit | 科學化單變量爬山優化 skill（Step 1 釘定指標／測試集／隔離 worktree 與 `current_best_sha` → Step 2 接… |
| software-factory | self-written（借 mattpocock/skills#1316 九槽與三道煞車詞彙，未複製原文） | yes | https://github.com/example-owner/claude-config | 2026-11-04 | frontmatter watch | 三階段軟體工廠流程（階段 1 既有自動化反查 `scripts/inventory-existing-automations.py` → 階段 2 白話防呆訪談＋六欄重述／9 槽位／三… |
| retro-workflow (command) | self-written | yes | https://github.com/example-owner/claude-config | 2026-11-21 | manual edit | 跨session回顧、累積、四層驗證、上游低傷害分流與步驟7治理拍板；引用共用機制迭代重要性標準，明示 approve／accepted 即落實。 |
| review-method | self-written | yes | https://github.com/example-owner/claude-config | 2026-10-16 | manual edit | 審查 agent 的共用方法原則，只經 agent 定義檔的 `skills:` 預先載入 |
| humanizer-zh | op7418/Humanizer-zh | no | https://github.com/op7418/Humanizer-zh | 2026-10-16 | pinned copy + frontmatter watch | 固定 f4518a8eab97b8bfebc66a89d34320a89bef6930 |
| review-spec (command) | self-written | yes | https://github.com/example-owner/claude-config | 2026-11-20 | manual edit | YAGNI 改平鋪自由搭配選單與輕量 `<fable-ok>` 放行（trial 觀察中）、補 T3 可信路徑與槽位環境變數優先 |
| auto-on | self-written | yes | https://github.com/example-owner/claude-config | 2026-11-20 | manual edit | 手動開啟目前終端機或 session 的自動模式。 |
| auto-off | self-written | yes | https://github.com/example-owner/claude-config | 2026-11-20 | manual edit | 手動關閉目前終端機或 session 的自動模式。 |
| align-intent                | self-written                          | yes           | https://github.com/example-owner/claude-config | 2026-09-20 | manual edit | 使用者核准的通用對齊例外：將既有「你能理解我的意思嗎」固化成按需理解校準；手動與機制皆可呼叫，重述不授權，未發現差異不自稱已確認；Codex 共用 symlink；首版不修改既有流程的呼叫位置。不加常駐 Self-Verify 派工或摩擦帳本：純對話入口，沒有每次都需寫出的結構化產物或新增持久狀態。 |
| sharpen                     | self-written（改編自 cursor/plugins pstack，MIT）| yes           | https://github.com/example-owner/claude-config | 2026-11-16 | manual edit    | 唯讀查到底再帶發現回來對齊 |
| model-onboard               | self-written                          | yes           | example-owner/claude-config              | 2026-09-17 | manual edit    | 第三方模型接入＋評估一條鏈（WIRE → SMOKE → BENCH → VERDICT） |
| diagram-route | self-written | yes | https://github.com/example-owner/claude-config | 2026-10-15 | manual edit | 新技術圖先選 Diagram Design／Archify／SeeCode 或 d 全部都畫（2026-10-18 擴充三套＋all 並排比較）；明確指定與同圖續改沿用；不介入 review-spec／implement。子 skill name-only，保留可呼叫性。 |
| seecode | Aryanutkarsh/SeeCode + local wrapper | yes (patched) | https://github.com/Aryanutkarsh/SeeCode | 2026-10-18 | pinned copy + local wrapper | 固定 067ca2594e8e8ec87e7bcd14e9dcf7549f0f9913（v0.6.2）；user patched description/body (2026-10-18) |
| diagram-design | cathrynlavery/diagram-design + local wrapper | yes (patched) | https://github.com/cathrynlavery/diagram-design | 2026-10-15 | pinned copy + local wrapper | 固定 d97c5c7477e54cee17cfa6459190610da0643a05 |
| brainstorm                  | self-written                          | yes           | example-owner/claude-config              | 2026-07-30 | manual edit    | 「題目還沒定形」的開場討論協議（剝錨 → 帶收據框架發散 → 鑑別式提問 → 維度表 → 三出口閘門＋殘渣落檔） |
| handoff-impl                | self-written                          | yes           | example-owner/claude-config              | 2026-07-30 | manual edit    | 跨 session 實作委外信道（🔬 trial 至 review、friction-log 批次折 |
| agent-authoring             | self-written                          | yes           | example-owner/claude-config              | 2026-07-27 | manual edit    | 建/改 agent 定義檔流程（tools 欄語意 / per-session 載入 / result cache / smoke 閘門），routed-* `tools: []` 事… |
| write-pr-description        | self-written                          | yes           | example-owner/claude-config              | 2026-08-30 | manual edit    | 平台無關 PR title/body writer |
| caveman                     | mattpocock                            | no            | mattpocock/skills（上游已移除）      | ?          | orphaned       | 上游 2026-06-12 移除（2026-07-10 對帳發現）；本地照用、無 sync 來源、upstream check 不會再有訊號                                                       |
| check-my-stack              | self-written                          | yes           | example-owner/claude-config              | 2026-05-?  | manual edit    | v2.1 rewrite 2026-07-05（adoption-hypothesis-first + 挑戰 pass/gate 帳 + scripts/reconcile.sh |
| debugging                   | superpowers plugin fork               | yes (patched) | plugins-official/superpowers 6.1.1  | 2026-07-10 | manual edit    | fork 更名 bare debugging（CC 無 plugin same-name shadow）、shadow 由 PreToolUse hook superpowers-sy… |
| domain-modeling             | mattpocock (fork patched)             | yes (patched) | mattpocock/skills `4588b32`         | 2026-10-06 | frontmatter watch | 行為六段原樣 |
| figma-context-budget        | self-written                          | yes           | example-owner/claude-config              | ?          | manual edit    | 個人 config repo；2026-07-10 修訂：刪懸空引用（figma-use/figma-generate-design）、description 去流程摘要、Rule 2 oldco-shop 分岔、補踩坑段            |
| find-skills                 | Vercel Labs (`vercel-labs/skills`)    | yes (patched) | vercel-labs/skills                  | ?          | manual edit    | user 收窄 description (2026-06-12) |
| gate-authoring              | self-written                          | yes           | example-owner/claude-config              | 2026-11-22 | manual edit    | gate 設計 checklist（前置機制迭代重要性檢核 H1–H4／N1–N4 單次確認、threat model、surface 四分、四件回歸、加嚴歷史回放） |
| github-repo-research        | self-written                          | yes           | example-owner/claude-config              | 2026-05-?  | manual edit    | distill recon crystallize (commit 1ee67b5)；2026-07-05 Step 1a 加 unchecked-prior 對帳（graphify stale 案）                                          |
| absorb-pack                 | 自寫（2026-07-11）                    | yes           | —（自家原創）                       | 2026-08-11 | manual edit    | 全量逐條重評與碎片吸收流程固化；Q2/Q3 + 帳本 + 七層落點 + 四來源 `STACK_RECEIPT v1`；Self-Verify R0 獨立重算集合、缺欄或不一致即 FAIL |
| grill-me                    | mattpocock                            | yes (patched) | mattpocock/skills                   | 2026-07-11 | manual edit    | user patched body (2026-07-10)：吸收上游 grilling 分工線 + 等回饋 + plan-hold gate |
| ~~grill-with-docs~~         | mattpocock                            | no            | mattpocock/skills `447ca70`         | 2026-08-18 | —              | 2026-11-04 已移除、reason: 能力已併入 `grill-me`（自動判斷 `openspec/glossary.md` 或 `openspec/decisions/` … |
| agent-dispatch              | self-written                          | yes           | example-owner/claude-config            | 2026-11-21 | manual edit    | main 依完整 Herdr 身分起 worker 或唯讀單席／掃描；含信任確認框自動代按同意與關窗終態驗證 |
| implement                   | mattpocock (fork patched)             | yes (patched) | mattpocock/skills `ed37663`         | 2026-07-28 | frontmatter watch | fork 加 controller 段（ask-once subagent/inline + frontier 迴圈 + Verification Log 回… |
| mutation-testing            | self-written                          | yes           | local (no remote)                   | 2026-07-09 | manual edit    | Anti-slop mutation testing for AI-generated tests; base = hughescr disable-syntax + ZERO_SLO… |
| prototype                   | mattpocock (fork patched)             | yes (patched) | mattpocock/skills `6bcbcb0`         | 2026-08-11 | frontmatter watch | 兩分支（LOGIC 單檔 HTML（2026-08-11 隨上游 6bcbcb0 從 terminal app 換）/ UI 多變體 URL 切換） |
| research-before-answer      | self-written                          | yes           | example-owner/claude-config              | ?          | manual edit    | wiki entity `research-before-answer-skill.md` |
| receiving-code-review       | obra/superpowers (fork synced)        | no            | obra/superpowers `b36e082`          | 2026-08-20 | frontmatter watch | body 與 v6.3.0 上游同步，只加 provenance／契約與 desc-audit marker |
| resolving-merge-conflicts   | mattpocock + warpdotdev (fork patched) | yes (patched) | mattpocock/skills + warpdotdev/common-skills | 2026-10-06 | orphaned    | 2026-07-10 Q3 review 唯一引入項 |
| auto-choice                 | self-written（借 dzhng/skills audit-choices 做法，MIT；未複製原文） | yes | example-owner/claude-config | 2026-10-06 | frontmatter watch | 實作決定帳本：規格沒寫、實作者自己拍板的決定逐類追出（八類必填）、判 sound／unsound／needs-user＋把握度排序、寫 spec 旁 choices.md |
| review-implement            | self-written                          | yes           | example-owner/claude-config              | 2026-08-27 | manual edit    | Post-implementation Scope／YAGNI acceptance gate |
| review-zh                   | self-written                          | yes           | example-owner/claude-config              | ?          | manual edit    | wiki entity `review-zh-skill.md`                                                                                                                     |
| skill-creator               | Anthropic 官方 (frozen fork)          | yes (patched) | anthropics/skills `0f77e501`        | ?          | frozen         | **user 加 local norms 段 + wiring rules + provenance freeze note (commit 7f86c15)、刻意不跟上游 2026-… |
| tdd                         | mattpocock (fork patched)             | yes (patched) | mattpocock/skills `4588b32`         | 2026-10-06 | frontmatter watch | implement 的條件式參考（本批已選 tdd 且有 required 測試時由 controller 顯式 invoke）；user patched description/body (2026-10-09) |
| to-spec                     | mattpocock (fork patched)             | yes (patched) | mattpocock/skills `6654f6b`         | 2026-07-28 | frontmatter watch | 落點自適應（openspec change dir + validator 硬規則 / .scratch） |
| to-tickets                  | mattpocock (fork patched)             | yes (patched) | mattpocock/skills `8b36d4f`         | 2026-11-21 | frontmatter watch | 落點自適應（openspec tasks.md 分節 + Verification Log / .scratch per-ticket 檔） |
| to-questionnaire            | mattpocock (fork patched)             | yes (patched) | mattpocock/skills `8b36d4f`         | 2026-07-28 | frontmatter watch | 向人類收資訊的問卷信道（反向 handoff）；客製：可模型觸發＋主動提醒確認 gate＋落點 .scratch；上游在 in-progress 桶、path 變動由 watch 雷達抓            |
| wayfinder                   | mattpocock (fork patched)             | yes (patched) | mattpocock/skills `8b36d4f`         | 2026-08-02 | frontmatter watch | park 翻案落地——板子改本地檔案（openspec change dir 內 `wayfinder/` / .scratch）＋ frontier.sh … |
| wizard                      | mattpocock (fork patched)             | yes (patched) | mattpocock/skills `4ae2317`         | 2026-11-04 | frontmatter watch | v1.2 全量重評唯一新引入（Q3）：產互動 bash 精靈帶人走人類專屬步驟 |
| workflow-hardening          | self-written                          | yes           | example-owner/claude-config              | 2026-06-?  | manual edit    | F22 CDEG mods + §9 source-health (commit fae8923 / 9b77804) |
| zoom-out                    | mattpocock                            | no            | mattpocock/skills（上游已移除）      | ?          | orphaned       | 上游現行樹已無此 skill（2026-07-10 對帳發現）；本地照用、無 sync 來源                                                                                  |
| e2e-contract               | self-written                          | yes           | https://github.com/example-owner/claude-config | 2026-10-04 | manual edit | 文件／補丁行為確認與回歸材料流程；自然語言由 route 選派，手動入口保留；先人確認案例版本與操作範圍，再交所選工具契約模式；不綁 SDK、不自動修產品，保存失敗與未驗狀態。 |
| e2e-route                  | self-written                          | yes           | https://github.com/example-owner/claude-config | 2026-10-04 | manual edit | 新舊瀏覽器 E2E 的唯一自動選用入口；區分普通工作與 e2e-contract，同題確認／重跑仍先路由，有選擇不重問；子 skill 手動入口保留，不執行測試、不寫全域預設。 |
| e2e-explore-then-batch      | self-written                          | yes           | example-owner/claude-config              | 2026-08-14 | manual edit    | agent 探索 e2e 跑通一次 → 固化 pw spec（fixture/spec/trajectory 三件產物約定）→ caseMatrix 批次擴 |
| repo-guard                  | self-written                          | yes           | example-owner/claude-config              | 2026-11-20 | manual edit    | 單一產品 repo 重複寫碼錯升格為架構／型別／指路型 lint／行為測試並驗紅驗綠，已接 retro／PROTOCOL／implement 分流 |
| create-verify               | self-written                          | yes           | example-owner/claude-config              | 2026-11-20 | manual edit    | 替產品 repo 建立冷啟動可重跑專案驗證入口 `.claude/skills/verify-{app}/` 並實跑證據留存，已接 implement Preflight |

**Global Audit-eligible 統計**：由 `~/.claude/scripts/skill-inventory-paths.sh --counts` 動態產生；本檔不手寫衍生數字。

**全體 audit 範圍**：以 `~/.claude/scripts/skill-inventory-paths.sh --counts` 的 `total` 為準。

## Excluded paths（wrapper 永遠跳）

- `uupm-reference/.claude/skills/*` — reference DB clone（UI/UX Pro Max；[[reference_uupm_lazy_install_pattern]]）；user 不 patch description
- `**/.agents/skills/*` — npx `skills` CLI cwd-scoped 自動安裝；cloned upstream、user 不 patch（譬如 oldco-api/.agents/skills/gws-sheets / warp-fork/.agents/skills/\*）
- `~/.claude/plugins/**/SKILL.md` — plugin author 寫的 description、user 不 patch（譬如 mcp\_\_chrome-devtools 等 plugin 內含 SKILL.md）
- 任何 `Audit = no` row — global table 內已標明、cloned upstream 上游動態走 `skill-upstream-check-weekly`、不混進 description audit

## Fork provenance frontmatter（2026-07-28 起）

散檔複製型 fork（無 `.git`）的上游動態改由 SKILL.md frontmatter 自帶線索、`skill-upstream-check-weekly.sh` 第二段迴圈巡邏。新檔把 `upstream`／`upstream-path`／`upstream-pinned` 放在 validator 接受的 `metadata` 下（選配 `upstream-branch`、已知上游移除則 `upstream-status: orphaned`）；巡邏器仍相容歷史頂層格式。`upstream-pinned` 語意 =「已對賬到此」，只在看過 diff 拍板後推進。**新建 fork 型 skill 必補這組欄位**——漏加 = 脫離雷達（機制無法自動區分自寫 vs fork）。已補：grill-me / debugging（mattpocock 側；obra 側另有 hardcoded 段）/ resolving-merge-conflicts / deep-research / zoom-out（orphaned）/ caveman（orphaned）/ herdr。

### 監控來源補登（2026-10-15）

本輪只補監控 metadata，description／body 與既有作者 metadata 保留，不同步上游內容。新增來源：doc-coauthoring、frontend-design、mcp-builder、pdf、webapp-testing、find-skills、brag、e2e-tester-army、pr-lens、design-taste-frontend、html-to-image、icon-set-generator、tailwind-design-system、gws-calendar、gws-docs、gws-drive、gws-gmail、gws-sheets、gws-sheets-append、gws-sheets-read、vercel-composition-patterns、vercel-react-best-practices、vercel-react-native-skills、web-design-guidelines；另修 diagram-design 的 repo 格式。來源與路徑以各 SKILL.md 的 metadata 為準。

只有 diagram-design 與 e2e-tester-army 沿用有安裝證據的 commit；其餘不填 `upstream-pinned`，以 `upstream-status: needs-reconciliation` 記基線待對帳，不能據此宣稱已是最新版。既有週二巡檢只查指定的 SKILL.md；references、assets、scripts 不因這次登記而整包受監控。共用 symlink 保留原位置，其實體 metadata 只在本機安裝目錄修改，config repo 不會把實體檔當成已提交。

### 版本基準對帳（2026-10-20）

上述待對帳 23 份已逐份核對固定 commit 的官方原文與本地差額，補 `upstream-pinned` 並移除 `needs-reconciliation`；description／body／其他 metadata 保留。find-skills 以已讀差額的 `a80e4c9d12d607631249d4d7d059f835d4b2f13a` 作新對帳點，保留本地觸發與安裝規則；其餘沿可證內容底本。這是版本紀錄對帳，不是升級、唯一安裝 SHA 或已採用最新版的宣稱。

15 份共用安裝實體的來源欄位差額沿用 social-info 的 `skill-lock-source-baseline.json` source/runtime 格式登記；外部 installer lock 原值、排除清單與偵測器不改。不把 symlink commit 當成外部實體已保存。

## 維護紀律

**每次建 / 改 skill 必同步 update 本 INVENTORY.md 與對應詳檔（`skills/inventory/*.md`）。** 否則 daily-local `skill-desc-quality` channel 不會掃到、白寫。

- **薄主表＋主題詳檔雙層結構（2026-11-18 起）**：本主表保留前 6 欄（Project 區段前 4 欄）原格式供 parser 讀取，**備註欄限 ≤180 字元的一句定位／釘版或移除理由＋詳檔連結**；完整改版史、RED/GREEN/REFACTOR 驗證紀錄與借鑑細節一律寫入 `skills/inventory/{workflow-dev,review-governance,research-knowledge,browser-e2e-cloud,design-media-writing,projects}.md` 對應 `### <skill>` 段落。
- **局部讀取紀律**：更新前先用 `command grep -n "<skill>"` 定位行號，再用 `Read` 的 `offset`／`limit` 局部讀取，禁止整檔讀入。

| 情境                            | 動作                                                                                                       |
| ------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| 新 global skill                 | Global table append row、Audit=`yes`                                                                       |
| 新 project-scoped skill         | 對應 `## Project: <name>` section append row（section 不存在則新建）                                       |
| Cloned skill 開始改 description | 該 row 的 Audit 從 `no` 改 `yes (patched)`、備註欄加「user patched description (YYYY-MM-DD)、reason: ...」 |
| 停止 patch / 同步上游           | Audit 從 `yes (patched)` 改 `no`、備註欄加「reverted to upstream sync (YYYY-MM-DD)」                       |
| Skill 退役 / 刪除               | row 加 ~~刪除線~~、備註欄加「YYYY-MM-DD 已移除、reason: ...」                                              |
| 新 project base path            | 加 `## Project: <name> (<path>)` section、wrapper 自動 onboarding                                          |

此紀律 mirror 進 `~/.claude/skills/skill-creator/SKILL.md` 「使用者本地規範」段的「建 / 改完同步 update INVENTORY」條（2026-06-20 加；插條後編號會漂、以條目名錨定）作為 enforcement point。

## audit channel wrapper 對接 spec

`~/.claude/scripts/skill-inventory-paths.sh` 是 audit-eligible path 與衍生數字的唯一 parser owner：

```bash
bash ~/.claude/scripts/skill-inventory-paths.sh --paths
bash ~/.claude/scripts/skill-inventory-paths.sh --counts
```

`~/code/social-info/scripts/local-analysis/skill-desc-quality-daily.sh` 只呼叫這個 parser，不複製解析邏輯。`--paths` 輸出 absolute path list，接著依 state file 篩 changed → LLM judge → markdown report；`--counts` 輸出 `global / project / total`，供報告與 parity 驗證使用。

`(command)` 後綴由 parser 跳過：`align (command)` / `harness (command)` / `trial-review (command)` 這類 row 是 slash command、沒有 description discriminative trigger 問題，不進 audit。

## 2026-05-13 第二輪深入比對結果（歷史保留）

使用者要求對 4 個 Unknown 比對社群 repo 找 canonical。結果：

| Skill                      | 結論                                                   | 證據                                                                               |
| -------------------------- | ------------------------------------------------------ | ---------------------------------------------------------------------------------- |
| **design-taste-frontend**  | ✅ `Leonxlnx/taste-skill` (17,148★ MIT)                | nexu-io/open-design 自己 frontmatter 寫 `upstream: Leonxlnx/taste-skill`           |
| **find-skills**            | ✅ `vercel-labs/skills` (18,302★, npm `skills` source) | `npm view skills repository.url` → `git+https://github.com/vercel-labs/skills.git` |
| **html-to-image**          | ⚠️ 仍未明                                              | html2png.dev SaaS、SKILL.md 多社群 repo 散播、無 canonical author                  |
| **tailwind-design-system** | ⚠️ 仍未明                                              | wshobson/agents (35,305★) 收錄但非 lead author；無明確 origin                      |

## 來源驗證 heuristic（給未來自己）

| 訊號                                                                           | 推導結果                                                            |
| ------------------------------------------------------------------------------ | ------------------------------------------------------------------- |
| `.git/` 目錄存在                                                               | 從 `git remote -v` 直接讀 origin                                    |
| `.gitmodules` 含此 path                                                        | git submodule、user fork upstream                                   |
| frontmatter `license: Proprietary. LICENSE.txt has complete terms`             | 100% Anthropic 官方                                                 |
| frontmatter `license: Complete terms in LICENSE.txt`                           | 高機率 Anthropic 官方（用 anthropics/skills repo dir 列表交叉確認） |
| frontmatter `license: MIT` + `metadata.author: vercel`                         | Vercel Labs                                                         |
| frontmatter `metadata.openclaw:` block                                         | googleworkspace/cli 或其他 OpenClaw 配套                            |
| frontmatter `metadata.mcp-server: figma, figma-desktop`                        | 隨 Figma MCP server 投送（不在 git tracked）                        |
| SKILL.md 內含「## 出處注記」/「frozen fork of」blockquote                      | User patched cloned skill、Audit 應標 `yes (patched)`               |
| `gh search code "<獨特句子>" --filename SKILL.md` hit `example-owner/claude-config` | 自寫（個人 config repo）                                            |
| git log `feat(skill[s])` commit 影響此 path                                    | User actively iterate；可能 self-written 也可能 patched cloned      |

## 個人 config repo

- `example-owner/claude-config`（cross-machine sync repo）
- Description: 「Claude Code cross-machine sync — config, skills, commands, rules, and cross-machine task system」
- 自寫 global skill 推這裡 + SKILL.md 加 `source:` 欄位（未來）
