# LIVE 階段：在真的 CC session 裡跑

API 探針與能力題都是用 curl 或 python 直接打端點，測不到 CC 整合層的問題。這些問題只有真的開一個 CC session 才看得見，而它們每一個都會讓模型「API 測起來全綠、實際用起來廢掉」。

底本是 `~/Desktop/projects/cc-vendor-bridge/docs/stage-2-playbook.md` 的 Phase 2 與 Phase 3（2026-05-03 對 DeepSeek 驗出來的）。

## agent 自己跑得動，用 headless

`claude -p` 的 headless 模式會起一個完整的 CC session 並留下 jsonl，所以這階段**不必交給人類執行**：

```bash
zsh -ic 'ccp-<vendor> -p --dangerously-skip-permissions "<測試 prompt>"'
```

`ccp-*` function 是 zsh 語法，用 `zsh -ic` 呼叫才能載到。這正是 cc-vendor-bridge Path 1 sidecar 的做法。

headless 與互動 session 的差別要記在心上：沒有 TUI、沒有使用者中途介入，所以測不到「模型會不會問問題後等待」這類互動行為。其餘的 hook、MCP、subagent、CLAUDE.md 都照常生效。

需要使用者親自跑的只剩互動行為本身；那種情況才把啟動指令與測試 prompt 完整交給他，不要只描述要做什麼。

## 先設環境變數

三個 caveat 明確標「影響所有第三方 vendor」，所以每接一顆新模型都要帶：

| 變數 | 擋什麼 |
|---|---|
| `DISABLE_COMPACT=1` 配 `CLAUDE_CODE_MAX_CONTEXT_TOKENS=<實際大小>` | CC 對第三方端點會退回 200K context 假設 |
| `ENABLE_TOOL_SEARCH=auto` | ToolSearch 的延遲載入對非 Anthropic 端點預設停用 |
| `CC_VENDOR=<name>` | 本機 stop hook 會對 vendor session 發出不適用的提示，這個 marker 讓 hook 的 Defense 0 跳過 |

`~/Desktop/projects/cc-vendor-bridge/shell/ccp-functions.sh` 的既有 `ccp-*` function 已經包好這些，新模型如果還沒有對應 function，照同一個形狀加一個。

## 複合測試 prompt

一次涵蓋 MCP、subagent 派工、繁中、CLAUDE.md 遵從、自述準確性：

```
請依序做、每步附證據與觀察：
1. 用 filesystem MCP 列某個目錄的檔名與大小
2. 並行派 2 個 subagent 查兩個不同主題，兩個都回來才繼續
3. 用繁中 80 字內總結 step 1+2
4. Print 一個 JS console.log 範例（用 JSON.stringify、不寫註解、用 ?? 不用 ||）
5. 跟我講第 2 步的 subagent 用什麼 model
```

第 4 步在測 CLAUDE.md 的程式碼風格規則有沒有被遵守，第 5 步在測模型對自己執行環境的自述準不準——vendor 模型常對 CC 設定產生幻覺。

## 跑完分析 jsonl

session 檔在 `~/.claude/projects/<專案路徑>/<session-id>.jsonl`，subagent 在同目錄 `<session-id>/subagents/`。

```bash
JSONL=<path>

jq -c 'select(.type=="assistant") | .message.usage' "$JSONL"

jq -rc 'select(.type=="assistant") | .message.content[]? | select(.type=="tool_use" and .name=="ToolSearch") | .input.query' "$JSONL"

for f in <session-dir>/subagents/*.jsonl; do
  jq -r 'select(.type=="assistant") | .message.model' "$f" | sort -u
done

jq -c 'select(.type=="attachment" and (.attachment.type | contains("error")))' "$JSONL" | wc -l
```

四條依序看的是：每輪的 cache 命中、ToolSearch 有沒有在用到延遲工具前先觸發、subagent 實際用了哪顆模型、hook 有沒有報錯。

## 通過條件

- hook 錯誤數 = 0
- 用到延遲載入的工具前，ToolSearch 有先觸發
- subagent 用的模型符合預期（vendor 有 `CLAUDE_CODE_SUBAGENT_MODEL` 就該是小模型，否則同主模型）
- 最終輸出符合 CLAUDE.md 的風格規則
- 沒有在使用者沒要求的情況下寫 memory 檔

## 逐 vendor 要試的 caveat

- `tool_choice: {type:tool, name:X}` 會不會被拒（DeepSeek 確認會，其他未知；本機有 thin proxy 改寫成 `{type:any}` 的前例）
- 模型對自己的 CC 設定會不會產生幻覺（普遍發生，嚴重度不一）

## 這階段測不到的

工作邊界遵守。2026-09-06 的 worker 實測裡，`free(max)` 兩題都因違規 DQ——一次把 token 帶進 tool result，一次違反離線契約去裝套件——而它的 hidden code test 是過的。那要靠實際長時間派工或 harbor 才看得出來，一次 15 分鐘的 session 看不到。
