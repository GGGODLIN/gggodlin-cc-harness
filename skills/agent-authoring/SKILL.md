---
name: agent-authoring
description: 建立或修改 subagent 定義檔（~/.claude/agents/*.md 或專案 .claude/agents/*.md）前必讀的流程 skill——frontmatter 欄位語意、tools 欄陷阱、載入時機、上線前 smoke test。觸發：「建 / 寫 / 加一個 agent」「改 agent 定義檔」「調 agent 的 model / effort / tools」「新增 subagent 類型」；症狀觸發：subagent 0 個 tool call、把 tool call 吐成文字、回報改了檔但磁碟沒變、改了定義檔卻沒生效。Do not use for：派工時挑用哪個既有 agent（看 subagent-routing.md）、寫 hook / gate（gate-authoring）、寫 skill（skill-creator）、Workflow script 內的 agent() 呼叫（workflow-hardening）。
---

<!-- 本檔在契約測試底下：bash ~/.claude/skills/agent-authoring/scripts/tests/agent-contract-validator-closeout.test.sh -->

# Agent Authoring

Agent 定義檔的失效模式跟 skill / hook 不同：**壞掉的 agent 不會報錯，會無聲幻覺**——拿不到工具的模型把 tool call 吐成文字、自產假 tool result、最後交出含假驗證證據的完成報告（2026-07-27 routed-* 事故：6 派全滅、其一編出完整 git status 輸出）。所以本 skill 的核心是三個「寫的時候看不出錯」的機制事實 + 一個機械 smoke 閘門。

## Step 1: frontmatter 欄位

```yaml
---
name: <kebab-case，與檔名一致>
description: <觸發條件 + Do-not-use，這是 main 挑 agent 的唯一依據>
model: opus | sonnet | haiku    # 省略 = 繼承派工方指定或 main
effort: low | medium | high | xhigh   # 省略 = 繼承 session effort；max 存在於 workflow opts.effort 值域、定義檔吃不吃 max 未實測
tools: Read, Grep, Bash          # ⚠️ 見 Step 2，省略與空陣列語意相反
---
```

- `model` + `effort` 在 spawn 時**覆寫** caller 的指定（不是 fallback）——釘死路由就靠這兩欄，per-call Agent tool 沒有 effort 參數
- 高頻 agent（探索 / fetch 類）effort 一律釘 low/medium，不釘會繼承到 xhigh session 變貴

完成判準：frontmatter 每一欄都是刻意寫或刻意省略，說得出理由。

## Step 2: tools 欄——三種寫法、語意相反

| 寫法 | runtime 語意 |
|---|---|
| **省略整欄** | 繼承全工具（要全工具就這樣寫）|
| `tools: []` | **空白名單 = 零工具**。模型會把 tool call 吐成文字並幻覺假結果；session 啟動清單卻渲染成「(Tools: All tools)」——顯示層與 runtime 相反，看清單驗證會誤判 |
| 明列清單 | 只有列出的工具；**沒有 ToolSearch 就載不了 deferred schema**，漏列 = 比「不選用」更死 |

明列清單時兩個檢查（**只在明列時跑**；省略欄位=繼承全工具，幽靈 MCP 引用屬全域 audit 面、不歸單一 agent 檔負責）：

1. **MCP 工具先驗 server 存在**：`python3 -c "import json; d=json.load(open('$HOME/.claude.json')); print(sorted((d.get('mcpServers') or {}).keys()))"` 加各 project scope。列了不存在 server 的工具不報錯、只是永遠缺席（前車之鑑：三個 reviewer agent 引用已移除的 claude-context server 數月無人發現）
2. 需要用到 deferred MCP 工具的 restricted agent → tools 加 `ToolSearch`，或把該 MCP 工具明列（明列會在 spawn 時載 schema）

該放哪些——角色類型 → 預設白名單起點（2026-08-03 加，源自 VoltAgent pack CLAUDE.md 的 role→tools 表、內容按本機改寫。起點不是上限，按任務加減；要全工具就省略整欄）：

| 角色類型 | 預設 tools 起點 | 瘦身理由 |
|---|---|---|
| 機械對表（rubric auditor）| `Read` | 素材全嵌 prompt，實測 0-tool-call 也吃 ~40K schema 預載，砍到只剩保險 |
| 只讀審查（reviewer / critic）| `Read, Grep, Glob, Bash` | code 審查要跑測試留 Bash；語意搜尋另加 semble 兩件 |
| 研究抓取（fetch / search）| `Read, WebFetch, WebSearch` + 按需 `ToolSearch` | deferred MCP 靠 ToolSearch 載，不預載全套 |
| 寫檔實作（implementer）| `Read, Write, Edit, Bash, Grep, Glob` | |
| 文件維運（wiki / docs）| `Read, Write, Edit, Grep, Glob, Bash` | 散文語料搜尋走 `semble search ... --content docs` CLI（走 Bash）；**不要**用 code 版 `mcp__semble__search`，它是 code-only 註冊、查散文會靜默回程式碼檔。舊的 `semble-docs` MCP server 已於 2026-08-08 移除 |

完成判準：tools 欄的每個名字都對過「這工具在這台機器現在真的存在」。

## Step 3: 載入時機——改完檔不等於生效

- Agent 定義檔 **per-session 載入**：新建 / 修改後，現行 session 派的還是舊定義（新建檔會 `Agent type not found`、改欄位靜默用舊值）。驗證一律走 headless 新 process 或新 session
- **Agent result cache 以 prompt 為 key**：同 session 內同 prompt 重派會原样回放舊結果（token 數逐位相同可辨識）。修完定義在同 session 用同 prompt 重測 = 測到的是快取不是修復
- 若有 gate / hook 強制導向新 agent（如 T2-routing-gate sentinel）：**開關必須等新 session 載入 agent 後才開**，否則該 session 舊路被擋、新 agent 不存在，即興派工全鎖死

完成載入時機檢查後，接 Step 4：contract validator closeout，再進 smoke。

## Step 4: contract validator closeout

完成一個 Agent 定義、routing SSOT 或相關派工引用的邏輯修改單元後，在較貴的 smoke／測試前執行。一行或單欄 frontmatter／metadata 變更也算一個邏輯修改單元；不得以「只是小修」或「smoke 很快」直接跳到 Step 5。

```bash
CONFIG_ROOT=${CLAUDE_CONFIG_DIR:-$HOME/.claude}
ACTIVE_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || true)
if [ -n "$ACTIVE_ROOT" ] && [ "$(git -C "$ACTIVE_ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" = "$(git -C "$CONFIG_ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" ]; then
  CONFIG_ROOT=$ACTIVE_ROOT
fi
node "$CONFIG_ROOT/scripts/agent-contract-validator.mjs" --global-root "$CONFIG_ROOT"
```

如果 validator exit status 非 0，停止 closeout，把 validator 原始 JSON 診斷原樣保留在回報，不進 Step 5。Validator 只在 authoring closeout 執行；正常 Agent／Workflow 執行不呼叫 validator。

完成判準：validator exit 0 且 output status=pass；否則 closeout 未完成。

## Step 5: 上線前 smoke test（機械閘門、不可跳過）

跑 `scripts/smoke-agent.sh <agent-name>`——headless 新 process 派該 agent 用 Bash 寫檔，**以磁碟上真的出現 side-effect 檔為唯一判準**。

```bash
bash ~/.claude/skills/agent-authoring/scripts/smoke-agent.sh <agent-name>
```

為什麼不能用別的判準：

- 驗 jsonl 的 model / effort 解析值 ≠ 驗工具能用（07-26 smoke 4/4 過、隔天 live 全滅的實證）
- 信 agent 的文字回報 ≠ 驗證（幻覺型會編出完整驗收證據）；這條同樣適用日常——**subagent 說改了檔，main 驗收一律磁碟實查**
- 角色紀律強的 agent（如 reviewer 類）可能拒絕 off-role probe——這是好事不是 FAIL，改用一次最小真實任務驗，並在該 agent 檔記「首次真實使用時驗」

完成判準：smoke PASS 輸出貼在交付訊息裡，或明寫「拒絕 probe、待首次真實任務驗」。

## Step 6: 接線收尾

按場景挑子項：**新建 / 修改** → 前兩項；**刪除 / 退役** → 第三項。Step 5 的 smoke PASS 是品質終點，本步是接線終點，兩個都要。

- 有 agent 白名單 gate 的機器：新 agent 有定義檔即自動過 E1 白名單，不用改 gate；但 gate 的測試 fixture 若枚舉 agent 清單要同步
- description 改動必同日對齊 body 內相關敘述（multi-surface 漂移同 skill 的判準）
- 刪除 / 退役 agent：grep 全 config（gate EXTRA_ALLOW、workflow script agentType、其他 skill 的派工指引）確認無殘留引用
- 摩擦盤點（所有場景）：本次 authoring 有無預見或撞到的摩擦 → append 該 agent 或本 skill 的 `friction-log.md`，無主的落 `~/.claude/friction/workflow-general.md`（規則見 `~/.claude/friction/PROTOCOL.md`）；無摩擦不留紀錄
- 帳本盤點：本次 authoring 有無引入會被 append、供未來 agent 讀的檔案或目錄 → 登記 registry 或標明純 log；無則不留紀錄

完成判準：gate fixture 測試組跑過全綠（有 gate 的機器）；刪除場景 grep 輸出 0 命中貼出。
