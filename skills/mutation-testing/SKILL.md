---
name: mutation-testing
description: Use when a coding agent just wrote tests and quality needs validation, when suspecting existing tests are green-but-hollow (test theater = passes but doesn't assert behavior), when auditing AI-generated tests, when reading a Stryker mutation report and deciding what to do with survived mutants, or when the user mentions mutation testing / stryker / mutation score / survived mutant. Includes a zero-install npx path, so repos with no Stryker in package.json are in scope. Do not use for authoring initial unit tests (that is ordinary test-writing, not this skill).
---

<!-- 本檔在契約測試底下：python3 ~/.claude/commands/tests/test_skill_verify_one_shot_callers.py -->

# Mutation Testing

> **出處注記（2026-07-09 建、2026-07-10 補注記）**：本 skill 為三源 graft + 自家實證——骨架與 disable-syntax / NoCoverage 合法 pattern 取自 [hughescr/claude-code-config](https://github.com/hughescr/claude-code-config) 的 `plugins/javascript/skills/stryker-mutation-testing`；「anti-AI-slop killer」framing 語言取自 [snava10/alist](https://github.com/snava10/alist) 的 ZERO_SLOP_AI_SKILL；changed-files workflow 取自 [otomatty/zedi](https://github.com/otomatty/zedi) 的 `stryker-mutation-diff` skill + `stryker.config.mutation-changed.mjs`；proj 76% case study 為自家實跑。出處鏈 2026-07-10 經 gh CLI + session 取證核實。

抓 AI 產出的「test theater」——test 跑得過但沒真的 assert 行為。

## 什麼時候用這個 skill

| 用這個 skill | 用別的 |
|---|---|
| 剛叫 CC 寫完新 test、想驗品質 | 從零寫新 test（走 `tdd` skill 或一般 test-first 流程） |
| 懷疑既有 test 是綠燈幌子 | 要把 Stryker 正式裝進 repo / 接進 CI → 另案（本 skill 用零安裝 npx 跑，不需要先裝） |
| 讀完 stryker report 要判 survived 怎麼處理 | 寫 E2E |
| Audit AI 產的 test 有沒有 assert value | 寫 property-based test |

## 心法（為什麼 AI 產 test 特別需要這招）

**Anti-slop framing**：Mutation testing 是 anti-slop killer——Stryker 故意改壞 code，若 test 沒紅代表 test 根本沒在 assert 行為。

Coding agent 學到「test 綠燈 = 目標達成」，會**找最省事的路徑達成**（Goodhart's law）。典型 test theater：

```ts
// AI 寫的（跑到 line 但沒 assert value）
expect(discount(100, 'vip')).toBeDefined()

// 真在 assert
expect(discount(100, 'vip')).toBe(70)
```

Line coverage 對第一種給綠燈——**mutation score 是目前唯一還沒被 game 掉的 metric**。

## 前置條件

唯一的硬前置是**目標 test 檔 baseline 全綠**——mutation score 對一個本來就紅的 suite 沒有意義。

Stryker 本身**不需要事先裝**：走下方「零安裝執行路徑（npx）」。repo 若已裝好 `@stryker-mutator/core` + runner 且 `stryker.conf.json` 跑得起來，直接用既有安裝也可以。

## 零安裝執行路徑（npx）

不必把 Stryker 寫進 `package.json`。三個 `-p` 缺一不可（下面解釋為什麼）：

**jest 面**——在 repo 根跑，會自動讀該目錄的 `stryker.conf.json`：

```bash
npx -y -p @stryker-mutator/core@9.6.1 -p @stryker-mutator/jest-runner@9.6.1 -p typescript@5.9.3 \
  stryker run --testRunner jest --mutate "<檔案或 glob>" --reporters clear-text --concurrency 2
```

**vitest 面**——`cd` 到那個獨立套件目錄（monorepo 裡每個 extension / package 各自有 `vitest.config.*` 與 `node_modules`），通常零設定檔就跑得動：

```bash
npx -y -p @stryker-mutator/core@9.6.1 -p @stryker-mutator/vitest-runner@9.6.1 -p typescript@5.9.3 \
  stryker run --testRunner vitest --mutate "<檔案或 glob>" --reporters clear-text,progress --concurrency 2
```

⚠️ `--mutate` 別照抄 `src/**/*.ts`：真實的 src 常混 `.tsx` / `.jsx`（那樣會漏掉），而 `*.ts` 又會**咬到 `.d.ts` 型別宣告檔**（mutate 純型別沒有意義）。按該套件實際副檔名寫，並確認排除 `.d.ts`。Step 2 的收斂原則優先——日常循環給**單一檔案**最有效。

`--concurrency 2` 是保守值、不是推導出來的最佳解，機器夠力可以往上調。

**cwd 在 `.worktrees/` 裡面是安全的**（實測過）：sandbox 只複製 cwd 這棵樹，所以在 `.worktrees/<某 worktree>/extensions/<套件>` 底下跑不會踩到下面那個 `.worktrees` 遞迴複製問題——那個問題只在**專案根**發生。

**為什麼一定要帶 `typescript`**：目錄裡只要有 `tsconfig.json`，Stryker 就會跑 TS 設定預處理，那步會 `import 'typescript'`；npx 環境沒有就整個 crash（`Cannot find package 'typescript'`）。專案自己不一定需要 typescript（用 vitest + esbuild 轉 TS 就不需要），但 Stryker 需要。

**為什麼要釘精確版號**（不是 `typescript@5`）：見「踩過的坑」的 npx cache 條。

**monorepo 注意**：Stryker 會把整個專案複製進 sandbox，所以根目錄那份 `stryker.conf.json` 的 `ignorePatterns` **不能為了「零設定檔」而省掉**——省掉會炸，同一段有實證。

多 runner 的 repo（root 用 jest、各套件用 vitest、另有 nx / 別的 runner）沒有「一發打完」的跑法：Stryker 一次只吃一種 runner，所以是**一條命令對一個測試面**。要全專案覆蓋就是一張命令對照表，不是一份大設定。

## 主 workflow：CC 寫完 test 後 5 步

### Step 1. Baseline 驗全綠

跑目標 test 檔，確認 pass count = expected：

```bash
yarn jest <target-test-path>
```

**Completion criterion**：所有目標 test PASS、記錄 pass count 當 baseline。有 fail → 停下先修 test，不要進 mutation stage。

### Step 2. 縮 mutate 範圍

原則：**只 mutate 這次改動的 pure logic 檔**，不 mutate 整個 repo（一次跑幾小時沒人跑）。

編輯 `stryker.conf.json` 的 `mutate` array：

```json
"mutate": ["utils/setupStatus.ts", "utils/widgetStatus.ts"]
```

走零安裝路徑時不必動設定檔——用 `--mutate "<檔案或 glob>"` 直接帶，範圍收斂的要求一樣。

進階變體：只跑 git-changed 檔（適合日常 CC 循環）——見 `references/changed-files-workflow.md`。

**Completion criterion**：`mutate` 只列這次相關檔、沒有拉整個 `src/**/*.ts`。

### Step 3. 跑 Stryker

repo 已裝好 Stryker → `npx stryker run` 就夠。**沒裝 → 用「零安裝執行路徑（npx）」那段的完整命令**（三個 `-p`、typescript 要釘精確版號）。

觀察 output 的 mutation score summary（總分、killed、survived、no cov、timeout）。

**Completion criterion**：stryker 跑完、產出 HTML report 在 `reports/mutation/` 底下、terminal 看到 score 表格。

### Step 4. 對每個 survived mutant 走三選一決策

不要無腦補 test 追 100%。每個 survived 依 `references/survived-decision-tree.md` 判：

- **A. 寫新 test 或補 assertion kill 它**（大部分情況）
- **B. 判定為等價 mutant**：repo 有裝 Stryker 就在原始碼加 `// Stryker disable next-line <MutatorName>` comment；repo 沒裝 Stryker（走 npx 零安裝路徑）或 repo 慣例不收這種 comment 時，把 mutant 位置與等價理由寫進票檔或活規格的 mutation 段，原始碼不加註。理由：Stryker 不在 package.json 的 repo 裡，那行 comment 對團隊是死字，reviewer 讀不到它的用途
- **C. 判定為合法 NoCoverage**（防禦性寫法、fallback branch 難觸發），理由落點同 B

若對某個 mutant 三選一難決 → 讀 `references/survived-patterns.md` 找對應 pattern。加 disable comment 前讀 `references/disable-syntax.md`——位置限制多、放錯 silently 失效。

**Completion criterion**：**每個** survived mutant 都有明確歸類 A/B/C（不要跳 mutant）。歸 B/C 的都有一行原因，落在原始碼 comment 或票檔／活規格其中一處。

### Step 5. Rerun 驗證

補完 assertion / 加完 disable comment 後 rerun：

```bash
npx stryker run
```

**Completion criterion**：mutation score **有提升**（或所有剩下 survived 都是 B/C 分類、有 comment 記錄）。若分數沒動 = 你補的 assertion 沒真的 kill mutant，回 Step 4 檢查。

## 判分紀律：不追 100%

| Score | 動作 |
|---|---|
| 90%+ | 維持 |
| 80–89% | 挑高價值 mutant 補 |
| 70–79% | 補明顯盲點（value assertion 類優先） |
| < 70% | 系統性 review test suite |

**紀律**：agent 陷入死追高分是失敗模式。當 survived mutant 是合法等價 → 加 disable comment 附原因、繼續。

## Self-Verify（Step 5 完成後、交付前跑）

跑完 workflow 後派 subagent 對表 rubric——**不要自己 review**（自己 review 會給自己過關）。

派 subagent：`Agent tool → subagent_type: skill-verify-auditor`（sonnet+low、tools 僅 Read，定義檔釘死），description 固定含 marker 字串 `skill-verify:mutation-testing`（採用率統計 grep 用，不要改字），prompt 用：

```
Audit mutation-testing skill 執行結果

Skill 執行資料：
- Baseline test 檔案跟數量：[填]
- Stryker mutation score before/after：[填]
- Survived mutant 處理清單：[列每個 mutant → A/B/C + 原因]

對以下 rubric 逐項回 PASS/FAIL + 一句證據引述：

R1. Baseline 全綠：Step 1 有記錄目標 test PASS 且 count 符合預期
R2. Mutate 範圍收斂：mutate 範圍（conf 的 array 或 CLI 的 --mutate）只列這次改動檔、沒拉整個 src/
R3. 每個 survived 有分類：清單覆蓋所有 survived mutant、每個標 A/B/C
R4. B/C 分類有原因：每個 B/C mutant 都有一行理由，位置是原始碼 disable comment，或（repo 未裝 Stryker／慣例不收 comment 時）票檔或活規格的 mutation 段；兩處都沒有才 FAIL
R5. Rerun 有實跑：Step 5 有 rerun stryker、score 有變化或明確理由不變
R6. 沒偷分數：assertion 補在 test、等價判定走 B 的兩條落點之一，沒用 test.skip / mock 掩蓋

無法確認 = FAIL（偏置嚴審）。最後一行輸出 VERDICT: PASS | FAIL
```

**本回合這個 skill 只有一次 auditor 額度**：不論結果如何都不得重派，也不得用 SendMessage 續問同一個 auditor。交付末尾固定一行，狀態只能是下列四個之一：

- `VERDICT: PASS` → 「🔎 self-verify: COMPLIANT」
- FAIL 且已修正 → 先修再交付，標「🔎 self-verify: FIXED_AFTER_AUDIT — R#（抓到什麼、怎麼修的）」，同句明寫「未經第二次獨立稽查」。注意修法本身仍受 R6 約束：不得用 test.skip／mock 把 FAIL 修綠
- FAIL 且修不掉 → 標「🔎 self-verify: FAILED — R#（缺口）」，並把該條涵蓋的 mutant 從「已處理」清單移回 survived，不得宣稱 score 已改善
- Agent error / timeout / 空輸出 / 格式錯誤 → 標「🔎 self-verify: SKIPPED (agent error)」、不靜默跳過

## 常見 survived pattern 快查

看到某類 mutant 反覆 survived → 讀 `references/survived-patterns.md` 拿完整分析。快速索引：

| Pattern | 判準 | 修法 |
|---|---|---|
| ObjectLiteral 沒 assert 內容 | test 只驗 flow 不驗回傳 shape | 補 `expect(x).toEqual({...})` |
| StringLiteral 沒 assert 值 | test 只驗 truthy | 補 `expect(x).toBe('specific')` |
| ArrayDeclaration 沒探邊界 | `?? []` fallback 沒測 nullish | 補 null/undefined 輸入的 test case |
| `.join(sep)` separator | 只 test 單元素 array | test 2+ 元素讓 separator 出現 |
| Early-return optimization | 移除 guard test 仍過 | 判定為 B（disable + 附原因） |
| I/O method call | fs / fetch / spawn | 判定為 C（`// Stryker disable all`） |

## 踩過的坑（撞新 case 就往下補）

- **2026-07-09（proj 首跑 76%）**：CC 產 test 的三大盲點是 ObjectLiteral / StringLiteral / ArrayDeclaration——都是「驗 flow 沒驗 value」。若跑完 survived mutant 有大量 StringLiteral / ObjectLiteral 且對應 test 只有 `.toBeDefined()` / `.toBeTruthy()`——這是 test theater signal，優先補 value assertion。
- **2026-07-09**：Stryker sandbox 預設 copy 整個 repo，大 repo（proj 4GB+）會撞 socket file 或超慢。用 `ignorePatterns` 排除 `.worktrees` / `out` / `proj-app` / build cache。**（2026-08-03 補實證）**這條不只是效能問題：拿一份空 config 純 CLI 跑，會直接 crash 在 `ENOTSUP: operation not supported on socket, copyfile` ——它試著把 `.worktrees/<每個 worktree>/.claude/commands` 這個 symlink 複製進 sandbox。所以在有多 worktree 的 repo，帶 `ignorePatterns` 的那份 conf 是**必要的**，不能為了追求「零設定檔」而省掉。
- **2026-08-03（npx 版本坑，兩個都真的咬過）**：`-p typescript` 會抓到 **7.x**（Go 重寫版，`ts.parseConfigFileTextToJson` 已不存在）→ 報 `ts.parseConfigFileTextToJson is not a function`。改 `typescript@5` 這種 range 也不行，因為**npx 的 cache key 按套件組合算、不受 `-p` 順序影響**：某個 key 的 cache 目錄一旦缺 typescript（早期失敗留下的），之後帶同樣 range 都會落回那個壞目錄，換 `-p` 順序完全無效（實測換過，仍是同一個 hash 目錄）。解法是釘**精確版號**（`typescript@5.9.3`）產生新 key 逼它重裝。判別法：`ls ~/.npm/_npx/<hash>/node_modules/typescript`，不存在就是咬到壞 cache——那個 hash 會出現在錯誤堆疊的路徑裡。
- **只 mutate 一個檔就夠**：mutant 數由被 mutate 的那個檔決定、跟該套件 test 總數無關，所以收斂範圍下單次跑得進幾十秒。runner 自報的 test 數與 grep `it(`／`test(` 的字面數會差（參數化測試執行期展開）——對照數字以 runner 輸出為準。

## References

- `references/survived-patterns.md` — 6 大 survived pattern 詳細分析 + code example + 修法
- `references/survived-decision-tree.md` — Survived mutant A/B/C 判定流程
- `references/changed-files-workflow.md` — 只跑 git-changed 檔的變體工作流
- `references/disable-syntax.md` — `// Stryker disable` comment 完整規則跟位置限制
