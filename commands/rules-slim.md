---
description: rules-size channel 報 CLAUDE.md 或 rules/common 超門檻後，使用者說「來瘦身」「處理超標」「跑 rules-slim」時，找出該砍哪幾段、產草稿逐段拍板、准的才寫回。不適用：全量規則遵守率盤點（那是 ~/.claude/rule-review/ 的一次性重工）、把既有拍板的「做成機制」條目做成 hook（走 gate-authoring）、非 always-on 層的檔案瘦身。
---

<!-- 本檔在契約測試底下：python3 ~/.claude/commands/tests/test_skill_verify_one_shot_callers.py -->

# Rules Slim

為何固化：rules-size channel 每週二量得出「超標幾個 byte」，量不出「該砍哪一段」，報告因此進 digest 就沉底——CLAUDE.md 自 2026-08-04 起連續超標數週未被處理。本 command 是那個環節缺的消費端。

**既判優先**是本 command 的核心紀律：`~/.claude/rule-review/` 已經把 always-on 層切成 190 條並判過決（原作者 2026-08-25 一次性歷史盤點產物，公開版不附；外部採用者無此目錄時，略過 Step 2 與 Step 3 的 `collection.jsonl`／`split-rules.py` 比對，直接對全檔執行 Step 3 四條判定）；任何新判定之前先查既有判決還剩什麼沒落地——不只為了省工，更因為同一條規則被判兩次時兩次結論可能不一致，而使用者已經對第一次的結論拍板過。

## 接在哪

```
rules-size channel（read-only，每週二）
     ↓  報告落 ~/code/social-info/reports/local-analysis/<date>-rules-size.md
排檔（digest 放一行提醒，不自動跑本 command）
     ↓  使用者說「來瘦身」
/rules-slim  ← 唯一寫入端
```

channel 側保持 read-only 是刻意的：偵測與寫回分離，寫回全部經過使用者逐段拍板。

## 1. 讀最新超標報告

```bash
ls -1 ~/code/social-info/reports/local-analysis/*-rules-size.md | tail -1
```

檔名日期排序即時間序——不要用 `ls -t`，`~/.claude` 跨機同步會讓 mtime 與檔名日期不一致。

報告內容是 `__SILENT__` 表示當週全數在門檻內。這種情況先問使用者是不是想主動瘦身；沒有超標而使用者仍要跑，跳到 Step 3。

報告沒有「超標檔案」表、也沒有 scope 總和警告，只有「## 🪦 零使用規則候選（N）」段時，同樣代表當週全數在門檻內：Step 1 結論寫「未超標」，把零使用段照 Step 5 第 4 段的格式交給使用者，問要不要主動瘦身；不要因為報告不是 `__SILENT__` 就當成卡關。

報告有「## 🪦 零使用規則候選（N）」且 N≥1 時，把每條原樣記下來，留給 Step 5 第 4 段。N 為 0、或報告沒有這段（舊報告），就沒有第 4 段，其餘流程不變。

門檻與範圍都從報告本文讀，不要在本檔重述數字——`~/code/social-info/scripts/local-analysis/rules-size-weekly.sh` 是門檻的權威來源，重述會 stale。

**完成判準**：能說出哪幾個檔超標、各超多少 bytes，數字逐個對得回報告本文；未超標時明寫「未超標」；有零使用段時已記下 N 與每一條。

完成後接 Step 2。

## 2. 查既有判決還剩什麼沒落地

`~/.claude/rule-review/verdicts.md` 是 2026-08-25 那次全量盤點的拍板表，使用者已 accept 全部 26 列。判決分五類，只有三類會讓檔案變小：

| 判決類 | 落地後檔案會不會變小 | 誰負責落地 |
|---|---|---|
| 刪 | 會 | 本 command |
| 只在特定任務才載入 | 會（搬走） | 本 command |
| 做成機制 | 會，但只有 hook 已在跑時散文才能砍 | hook 建置走 `gate-authoring`；hook 已在跑時的散文清除是本 command |
| 留 | 不會 | — |
| 判不了 | 不會 | — |

抽出前三類的規則原文，逐條 grep 現況檔看還在不在：

```bash
check() { printf "%s\t" "$1"; if /usr/bin/grep -qF -- "$2" \
  ~/.claude/CLAUDE.md \
  ~/.claude/rules/common/*.md 2>/dev/null; \
  then echo "STILL PRESENT"; else echo "gone"; fi; }
check "<編號>" "<規則原文的獨特片段>"
```

zsh 不對變數做 word splitting，所以檔案清單要逐個寫出來，不能塞進一個變數再展開——那樣 grep 會收到一個不存在的合併路徑、全部誤判成 gone。

`STILL PRESENT` 的先分兩類，判決是「做成機制」的還要再查一層：

- 判決是「刪」或「只在特定任務才載入」→ 進本次草稿（Step 4），註明「既有拍板、8/25 已 accept」
- 判決是「做成機制」→ 還不能直接判定，先查對應的 hook 到底建好了沒

查之前先確定「這條規則對應哪支 hook」。這一步不准靠檔名或關鍵字猜——必須讀那支 hook 的內容，確認它實際注入或攔截的東西就是這條規則要求的行為。2026-09-04 首次驗證時兩個獨立 agent 在這裡各猜錯一半：一個用關鍵字搜 settings 搜不到就判「無 hook」，另一個看到 `gpt-convergence-reminder.sh` 名字像就把它當成「動工前列我假設」那條的 hook，實際讀內容才發現它注入的是 GPT 專屬的實作收斂規則加背景等待規則，跟那條規則無關。

對應關係確認不了的一律歸「無 hook」堆，並標「對應未確認」。這個保守側是刻意的：把「其實有 hook」誤判成無，代價是少砍一條、下次再砍；把「其實沒 hook」誤判成有，代價是砍掉那條規則唯一的護欄。

確認對應之後，查落地狀態要兩個訊號都看，因為檔案存在不代表在跑：

```bash
# 訊號 1：有沒有註冊（沒註冊 = 檔案躺在那但不會被觸發）
/usr/bin/grep -c "<hook 檔名去掉 .sh>" ~/.claude/settings.json ~/.claude/settings.local.json
# 訊號 2：有沒有真的跑過（state 檔是行為證據，比註冊更強）
ls ~/.claude/hooks/state/ | /usr/bin/grep -c "<hook 的 state 檔前綴>"
```

依兩個訊號分流：

| 註冊 | state 有命中 | 處置 |
|---|---|---|
| 有 | 有 | **進草稿**——機制已在跑，散文是純冗餘 |
| 有 | 無 | 進草稿但標「機制已註冊、尚無觸發紀錄」，讓使用者判要不要等觀察期 |
| 無 | — | **不進草稿**，列成「要走 `/gate-authoring` 建 hook」清單 |

這一層是本步最容易出錯的地方：把「散文還在」直接當成「機制沒落地」會讓已經有 hook 護著的條目被判成不能砍，瘦身缺口因此假性擴大、結論退化成「只能調 cap」。2026-09-04 首次行為驗證就撞到這個：7 條「做成機制」的 hook 全部已註冊且有 state 命中檔，卻被判成不能動。

**舉證要求**：如果本步的結論是「沒有任何既有判決項可砍」，必須同時附上每一條「做成機制」條目的註冊數與 state 檔數輸出。「什麼都砍不了」是需要舉證的結論，不是可以直接寫下的預設出口。

**完成判準**：前三類每一條都有 `STILL PRESENT` 或 `gone` 的結果，一條不漏；每個 `STILL PRESENT` 的「做成機制」條目都有註冊數與 state 檔數兩個數字；已按上表分好三堆。

完成後接 Step 3。

## 3. 仍超標才用四條判定掃未判過的段落

Step 2 的可砍項全部砍掉後，估算檔案還剩多少 bytes。如果已在門檻內，跳到 Step 4 只交那些既有拍板項。

仍超標才繼續掃。掃描對象分兩種，因為判定 a 的分母跟其他三條不一樣：

- **判定 a（hook 能強制的）掃全檔**，包含 8/25 判「留」的 164 條。理由是 8/25 的判決反映當時的機制覆蓋面，之後新建的 hook 會讓「留」的判決過期。2026-09-04 實例：`CLAUDE.md` 的 semble 聚合根目錄禁令自己就寫著「hook 會擋」，`semble-root-block.py` 也確實註冊在 `mcp__semble__search|mcp__semble__find_related` 上，但那條不在 8/25 前三類裡。
- **判定 b / c / d 只掃新段落**——8/25 之後新增的內容。`~/.claude/rule-review/collection.jsonl` 有當時 213 列的原文，比對得出哪些是新的。舊段落的這三軸已經判過，重判會跟既有判決打架。

四條判定（來源：humanlayer/skills 的 improve-claude-md）：

| 判定 | 砍的理由 | 替代處置 |
|---|---|---|
| a. linter / formatter / pre-commit hook 能強制的 | 工具擋得住的事寫成散文只會佔位置 | 建議改掛 hook |
| b. agent 從既有 code 就能自己學到的 | 模型是 in-context learner，codebase 用得一致，搜幾次就會跟 | 直接刪 |
| c. code snippet | 會 stale，且佔的 bytes 遠大於它省的查詢 | 改成檔案路徑指標 |
| d. 沒有具體可執行動作的話 | 「follow best practices」這類無法判定做到沒有 | 直接刪，或改寫成可觀察的條件 |

保護條款：**指令表／命令表一條都不准提議刪**。原因是 agent 需要知道有哪些指令可用，即使某幾條用得少——這張表是查詢用的基礎參考，不是行為約束。

保護條款的邊界要嚴格劃，否則它會變成豁免一切的擋箭牌。受保護的是**列舉可用指令的參考表**（npm scripts 清單、CLI 子命令表、可用工具列表）。**不**受保護的是規定何時該用哪個指令的行為規則——那些是規則，照 a/b/c/d 判。

判別問句：拿掉這段之後，agent 是「不知道有這個指令存在」還是「知道指令存在但不知道何時該用」？前者受保護，後者照判。2026-09-04 首次驗證的實例：`CLAUDE.md` 的 Code search 段被誤當指令表豁免，但它規定的是「什麼情況用 semble、什麼情況用 grep」，而其中的聚合根目錄禁令已由 `semble-root-block.py` 攔下——那是判定 a 的命中項，不是受保護的表。同理 Git 段的「仍要 confirm」清單是行為規則、不是指令表。

順手量指令條數。bytes 是 proxy，條數才是真單位——校準基準寫在 rules-size wrapper 檔頭（LLM 可穩定遵循約 150-200 條、CC system prompt 與 tools 已占約 50 條、單檔理想 < 300 行）。

`~/.claude/rule-review/split-rules.py` 已經有把散文切成「可單獨違反的動作」的實作，先試跑它、不要自己重新切。但它會失敗：2026-09-04 實測在 line 254 `sys.exit`，因為內建的 ANN keys 對不回現況行號（8/25 之後 CLAUDE.md 已經改過）。跑失敗時**明寫「指令條數未產出，原因是 split-rules.py 的 ANN keys 已 stale」**，不要靜默跳過這項也不要現場改寫那支腳本——它的 collection.jsonl 是 8/25 判決的證據基礎，修它屬於另一件事。

**完成判準**：每個提議都掛在 a/b/c/d 其中一條上，掛不上任何一條的不進草稿；指令表條目零提議；指令條數有產出，或明寫未產出的具體原因。

完成後接 Step 4。

## 4. Self-Verify（mandatory — 草稿成形後、呈給使用者前）

草稿成形後先派 verify subagent，不要先把草稿輸出成文字——harness 對 tool call 之間的文字不保證顯示，Agent call 會把先輸出的草稿吞掉。

Dispatch 規格：

- `Agent` tool、`subagent_type: skill-verify-auditor`（sonnet+low、tools 僅 Read，定義檔釘死）
- description 固定含 marker 字串 `skill-verify:rules-slim`（採用率統計 grep 用，不要改字）
- prompt 內嵌：(1) 完整草稿原文 (2) 下方 template 全文

Verify prompt template（原文嵌入、`{draft}` 換成草稿全文）：

```
你是 adversarial 合規審查員，檢查一份 always-on 規則瘦身草稿是否遵守其 command 定義的規矩。偏置是「找違規」：無法從草稿文本確認有遵守就判 FAIL，不要善意推定。

草稿原文：
{draft}

逐條檢查（每條回 PASS / FAIL / N-A + 一句證據引述）：

R1【數字有出處】草稿是否引用了 rules-size 報告的實際 bytes 與門檻，而非重新量測或憑印象給數字？沒有可對回報告的數字 = FAIL。

R2【既判優先】草稿是否在提出任何新砍除提議之前，先交代了 2026-08-25 既有判決的落地檢查結果（列出未落地項，或明寫「既有判決已全數落地」）？完全沒提 = FAIL。

R3【判定歸屬】每個新砍除提議是否標明它命中四條判定（linter 可強制 / agent 自學得到 / code snippet / 無具體動作）的哪一條？有任何一條提議掛不上判定 = FAIL。

R4【指令表保護】提議清單裡是否沒有任何指令表／命令表條目？出現一條 = FAIL。

R5【hook 落地有查】每個判決為「做成機制」而散文仍存在的條目，是否都附了 settings 註冊數與 hooks/state 檔數兩個數字，且規則與 hook 的對應有讀過內容的依據（不是靠檔名或關鍵字相似）？只憑「判決類是做成機制」就判它不能砍、沒有附這兩個數字 = FAIL。草稿結論若是「沒有任何既有判決項可砍」而缺這些數字，同樣 FAIL——那是需要舉證的結論。若本次無此類條目 = N-A。

這條配一對 anchor，兩段只差「對應依據」這一件事：

- 明顯 FAIL：「C033 動工前列我假設 → 對應 `gpt-convergence-reminder.sh`，註冊 1、state 0，進草稿標尚無觸發紀錄」（對應只靠檔名像，沒讀內容）
- 明顯 PASS：「C033 動工前列我假設 → 讀 `gpt-convergence-reminder.sh` 內容，它注入的是 GPT 專屬實作收斂規則與背景等待規則，與本條無關；settings 搜不到其他對應 hook，歸無 hook 堆、標對應未確認」

輸出格式（固定，最後一行必須是 verdict 行）：

R1: PASS|FAIL — <一句證據>
R2: PASS|FAIL — <一句證據>
R3: PASS|FAIL — <一句證據>
R4: PASS|FAIL — <一句證據>
R5: PASS|FAIL|N-A — <一句證據>
<verdict 行>

verdict 行二選一，整行照抄其中一種、只把 <> 換成編號：

VERDICT: COMPLIANT
VERDICT: VIOLATIONS: <R 編號逗號列表>

下游用 grep 取這一行做二值判讀，行內出現第二個 verdict 名稱、`|`、括號補述或條件句，解析會同時拿到兩個互斥狀態。保留意見寫進該條的證據句，不要寫進 verdict 行。
```

按結果收尾。**本回合這個 skill 只有一次 auditor 額度**：不論結果如何都不得重派，也不得用 SendMessage 續問同一個 auditor。草稿末尾固定一行，狀態只能是下列四個之一：

- 全 PASS / N-A → 「🔎 self-verify: COMPLIANT」
- 任一 FAIL 且已修正 → 「🔎 self-verify: FIXED_AFTER_AUDIT — R#（抓到什麼、怎麼修的）」，同句明寫「未經第二次獨立稽查」
- 任一 FAIL 且修不掉 → 「🔎 self-verify: FAILED — R#（缺口）」，並把佐證不足的那幾段從草稿刪除或收窄，不留在裡面
- Verify subagent 失敗（timeout / 空輸出 / 格式錯誤 / agent error）→ 草稿照交、標「🔎 self-verify: SKIPPED (agent error)」，不要靜默省略

**完成判準**：本回合已出現 `skill-verify:rules-slim` 的 Agent dispatch，且結果已反映在草稿末尾那一行。

完成後接 Step 5。

## 5. 交草稿、使用者逐段拍板

草稿放在 verify 之後的回合最終訊息，分三段，有零使用候選時加第 4 段：

1. **既有拍板未落地**（Step 2 產出）— 每條附編號與 8/25 判決類
2. **新提議**（Step 3 產出）— 每條附命中哪條判定、砍掉省多少 bytes
3. **等 hook 才能動**（Step 2 的「做成機制」堆）— 只列出來，不在本次動
4. **零使用候選（只呈現）**（Step 1 記下的零使用段，N≥1 才有）— 每條一行：規則原文、檔＋標題、觀察期間、最近一次遇到場合，照報告原文抄，不重量。這段只是觀察資料：「零使用」不是新的判定，不能單獨成為砍除理由；某條也命中第 1、2 段時，在那一段照原理由處理，這裡只註明「另見第 N 段」。8/25 判「留」的條目不因零使用重判。使用者看完自己指名要砍某條時，那條算使用者自行拍板，直接進 Step 6。

每條都要能單獨准或駁，所以逐條編號、每條附「砍掉後那個位置變成什麼」（刪掉／改成路徑指標／搬到哪個檔）。整段 diff 對長段落不好讀，用「原文首句 → 處置」的形式，只有短段落才貼完整 diff。

**完成判準**：草稿已在最終訊息交出，每條有編號、有處置、有 bytes 影響；使用者能對任一條說准或駁。

拍板後接 Step 6。

## 6. 只有准的才寫回

用 `Edit` 逐條寫回。不要用 `Write` 覆蓋整檔——整檔覆寫會把使用者沒准的段落一起改掉，而且失去逐條對應。

批次改多條時每條改完 grep 驗一次真的改成了：`replace_all` 為 false 的 Edit 在 old_string 不唯一時會失敗，但在「以為改了其實沒改」的 silent no-op 情境下不會報錯。

寫回後重跑一次量測，把「現在幾 bytes、還差門檻多少」回報給使用者。

**完成判準**：每條准的都有對應的 Edit 與 grep 驗證；駁的一條都沒動；已回報改後 bytes 與門檻差距。

## 首次行為驗證發現（2026-09-04）

上面各步驟的規則有六項來自建檔當天的 RED / GREEN 對照跑、不是預想，這裡只記來源方便日後回查：Step 1 的檔名排序、Step 2 的 zsh word splitting、Step 2 的 hook 落地兩訊號、Step 2 的規則→hook 對應依據要求、Step 3 的判定 a 掃全檔、Step 3 的 split-rules.py 失敗處置。

後三項是修正而非補充——修正前的版本會讓執行者把 7 條已有 hook 護著的散文判成不能砍，結論退化成「只能調 cap」。
