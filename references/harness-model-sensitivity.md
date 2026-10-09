# Harness 模型敏感度盤點（2026-07-25、coevolution spec §5.3）

一次性盤點。維度只有 **model-sensitive y/n**，只列 y；五分類欄是 review 現場的思考起點（spec §4 明示類別在 review 時重算、本表的「類別傾向」不是權威）。

盤點範圍與實測量體：

| 面 | 量體 | 盤法 |
|---|---|---|
| always-on 注入面 | `~/.claude/CLAUDE.md` 131 行、`rules/common/` 3 檔 108 行、`~/Desktop/projects/CLAUDE.md` 61 行 | 逐行 |
| 被引用 SSOT | `references/subagent-routing.md` 144 行、`references/effort-controls.md` 7 行 | 逐行 |
| 參數實值層 | `agents/` 12 檔 23 行、`workflows/` 21 處、`settings.json` 7 處 = **51 處**（spec §5.3 估 28 處、實測偏高） | grep 全量 |
| skills / commands | 66 skills ／ 25 commands，其中 12 檔含 model/effort 字面值 | 盤點＋納管已拍板 2026-07-25（見 d 段） |

**本檔是出生證明的唯一居所**（2026-07-25 U2 拍板：不寫進 always-on 注入面，避免每 session 開場付稅；詳見 c 段 U2）。

出生證明欄格式 `〔源:<memory-slug>·<出生模型>·<日期>〕`。**出生模型的取得方法**：memory frontmatter 的 `originSessionId` → 找 `~/.claude/projects/*/<sid>.jsonl` → 取該 session 主要 `message.model`。24 個候選 20 個解出、4 個 `originSessionId` 是 slug 型或 session 檔已不存在 → `unknown`。方法交叉驗證：`feedback_verdict_must_land_in_final_chat_message` 回推得 fable-5／2026-07-12，與該條目內文記載一致。

## a. model-sensitive 規則清單

### a1. `~/.claude/CLAUDE.md`

| slug | scope | 類別傾向 | 出生證明／備註 |
|---|---|---|---|
| `anti-crystal-english` | 通用 | 偏好＋失效修正 | 〔源:feedback_opus48_chinese_term_leakage·claude-opus-4-8·2026-05-30〕出生模型直接寫在 slug 裡；opus-4-8 中文詞洩漏 |
| `plain-language-default` | main | 失效修正 | **trial 觀察中**（c 段 L1 已查證）：出生源是 trial 行為數據不是 memory——trials `plain-language-rule-wording-v2`（review 日 2026-07-28、30 天糾正 8 次、資料源 `~/code/social-info/reports/local-analysis/rule-adherence-ledger.jsonl`）；memory 側只有範圍限定 brainstorm 的 sibling〔源:feedback_brainstorm_plain_language_specs·claude-opus-4-8·2026-06-13〕。07-28 review 後補正式出生證明 |
| `discussion-not-implementation-default` | main | 失效修正 | 出生不明 |
| `no-overengineering` | 通用 | 失效修正 | 出生不明；本 spec v1 三設計被四路 review 否決即最新實證 |
| `read-before-modify` | 通用 | 失效修正 | 出生不明 |
| `apologize-without-collapse` | main | 失效修正 | 出生不明；sycophancy／自責傾向是強 model-dependent 面 |
| `split-lookup-vs-decision` | main | 失效修正 | 〔源:feedback_ask_only_major_decision_forks·unknown·2026-07-23〕c 段 L2 已裁定同源、保留兩 slug |
| `converge-questions-one-round` | main | 失效修正 | 同上族、同一 memory |
| `prefer-edit-over-write` | 通用 | 失效修正 | 出生不明 |
| `dcg-no-destructive-literals` | 通用 | 平台繞道 | 觸發面＝dcg 規則集；2026-07-25 本體實作 session 實撞一次（暫存目錄清理被 `core.filesystem:rm-rf-general` 攔）。類別欄非權威（spec §4 review 現場重算）、c 段 L5 已裁定 |
| `grep-verify-after-edit` | 通用 | 失效修正 | 〔源:feedback_batch_edit_replace_must_assert·claude-fable-5·2026-07-24〕 |
| `proactive-skill-invoke` | main | 失效修正 | 〔源:feedback_always_on_rule_adherence_empirical_low·unknown·2026-05-16〕採用率 1-2% 實證；照 [[feedback_always_on_rule_safety_net_not_enforcer]] 不可用 follow rate 當 KPI |
| `claim-evidence-alignment` | 通用 | 失效修正 | 〔源:feedback_memory_not_evidence_for_behavior_claims·claude-fable-5·2026-06-12〕**已接 L2 特徵 `claim-evidence`** |
| `verdict-in-final-message` | main | 失效修正 | 〔源:feedback_verdict_must_land_in_final_chat_message·claude-fable-5·2026-07-12〕**已接 L2 特徵 `verdict-final-msg`**；4 案全 fable-5、main-only 規則 → main 換代即可處置 |
| `search-before-claiming-absent` | 通用 | 失效修正 | 中信心；strict-liability 缺陷例外清單屬規則本體 |
| `no-escape-via-uncertainty` | 通用 | 失效修正 | 〔源:feedback_exhaust_sources_before_offload·claude-opus-4-8·2026-06-02〕 |
| `past-work-reference-must-check` | main | 失效修正 | 〔源:feedback_interview_pre_answer_archaeology·claude-fable-5·2026-07-17〕檔內載 30 天 3 犯後升精確觸發 |
| `state-doc-is-claim-not-evidence` | 通用 | 失效修正 | 與 `claim-evidence-alignment` 同族、c 段 L3 已裁定不併 |
| `no-rerun-same-verification` | 通用 | 失效修正 | 出生不明 |
| `research-before-answer-gate` | 通用 | 失效修正 | 〔源:feedback_no_secondhand_research_as_fact·claude-opus-4-7·2026-04-26〕hallucination 傾向 = 最直接的 model-sensitive 面 |
| `subagent-model-routing` | 通用 | **能力繞道** | 指向 a5 的 SSOT；換代必主動重校、不等訊號 |
| `skill-multi-match-picker` | main | 失效修正 | 〔源:feedback_always_on_rule_safety_net_not_enforcer·unknown·2026-06-29〕catch-all safety net 定位、禁用 fire rate 當主 KPI |
| `soft-injection-defense` | 通用 | 失效修正／安全 | 〔源:feedback_subagent_injection_alert_pattern·claude-opus-4-7·2026-05-13〕注入抵抗力 model-dependent |

標 **n（不列表）**的代表：繁中回應、Conventional Commits、連結格式、程式碼風格 6 條、Git branch 命名、測試紀律 = 偏好類 invariant；Skill 創建流程、Gate 設計、Code search、CLI radar、Trial 紀律、beads、Figma、繁中 review 副本、個人 profile／wiki = 生態接線類（自家工具變動才動）。

### a2. `rules/common/fact-check.md`（11 條全 y）

整檔是 hallucination-prevention 紀律、模型換代必重驗。逐條出生證明：

| # | slug | 類別傾向 | 出生證明 |
|---|---|---|---|
| 1 | `no-secondhand-as-fact` | 失效修正 | 〔源:feedback_no_secondhand_research_as_fact·claude-opus-4-7·2026-04-26〕 |
| 2 | `no-partial-fact-check` | 失效修正 | 〔源:feedback_fact_check_every_point_not_just_thesis·claude-opus-4-7·2026-04-29〕 |
| 3 | `cc-feature-needs-behavior-evidence` | 失效修正 | 〔源:feedback_cc_feature_verification_method·claude-opus-4-7·2026-05-10〕 |
| 4 | `websearch-ranking-untrusted` | 平台繞道 | 〔源:feedback_websearch_misses_official_docs·claude-opus-4-7·2026-05-10〕觸發面＝搜尋引擎行為、非模型 |
| 5 | `websearch-plus-browser-serp` | 平台繞道 | 〔源:feedback_parallel_decision_by_structural_failure·claude-opus-4-7·2026-05-11〕 |
| 6 | `no-retired-tool-as-example` | 失效修正 | 〔源:feedback_no_retired_tool_as_example·claude-opus-4-7·2026-05-12〕 |
| 7 | `saas-policy-verify-official-ui` | 平台繞道 | 〔源:feedback_third_party_registrar_article_stale·claude-opus-4-7·2026-05-13〕 |
| 8 | `webfetch-4xx-browser-fallback` | 平台繞道 | 〔源:feedback_webfetch_fallback_must_trigger·claude-opus-4-7·2026-05-13〕 |
| 9 | `topic-shift-refetch` | 失效修正 | 〔源:feedback_session_topic_shift_refetch·unknown·2026-05-13〕session 檔已不存在 |
| 10 | `personal-query-wiki-plus-memory` | 生態接線 | 〔源:feedback_personal_query_must_check_wiki·claude-opus-4-7·2026-05-15〕**唯一偏生態接線者**、換代時可跳過 |
| 11 | `exhaust-source-types-before-giving-up` | 失效修正 | 〔源:feedback_exhaust_sources_before_offload·claude-opus-4-8·2026-06-02〕 |

⚠️ **本段最重要的 review 訊號**：11 條裡 10 條出生於 **opus-4-7／4-8 世代**（2026-04〜06）。opus-5 已於 2026-07-25 經 alias 位移入役、隔了兩個世代 → 下次換代 review 的最高優先重驗對象就是這一批。

### a3. `rules/common/performance.md`

| slug | scope | 類別傾向 | 出生證明／備註 |
|---|---|---|---|
| `rules-dont-pin-model-name` | 通用 | 能力繞道 | 〔源:feedback_prompt_principle_over_hardcoded_list·claude-opus-4-7·2026-05-07〕本規則本身就是 coevolution 體系的前身 |
| `context-tail-avoid-heavy-work` | main | **能力繞道** | 門檻明文「依當前模型的 context window 換算」→ 換代必重校；1M 模式下較少觸發 |

### a4. `rules/common/dispatch-and-verify.md`

| slug | scope | 類別傾向 | 出生證明／備註 |
|---|---|---|---|
| `main-does-three-things` | main | 能力繞道 | 邊界（surgical edit < 3 行）是能力相關閾值 |
| `dispatch-trigger-thresholds` | main | **能力繞道** | 30K tokens／5 檔／2 次 web／30 秒 四個實值 → 換代必重校 |
| `fanout-scale-judgment` | main | **能力繞道** | 1 ／ 2-4 ／ 10+ 三檔規模判準 |
| `explore-agent-deny` | 通用 | 平台繞道 | 〔源:reference_cc_explore_agent_model_inherit_2026_07_02·claude-opus-4-7·2026-07-02〕watcher＝cc-tool-updates；deny 實值在 settings.json（見 b 段） |
| `dont-dispatch-when-7` | main | 能力繞道 | 借鑑 superpowers guard rails、非自家失效實證 |
| `inventory-mapping-main-only` | subagent | 失效修正 | 〔源:feedback_subagent_inventory_mapping_fabrication·unknown·2026-05-24〕本次 Task 6 Step 2 即照此規則不派 subagent |
| `verify-show-expected` | 通用 | 失效修正 | 出生不明；與 superpowers verification-before-completion 同源 |
| `wrong-direction-signals` | 通用 | 失效修正 | 三訊號含「繞過驗證而非通過驗證」單獨命中即停 |
| `human-blocker-five-types` | 通用 | 平台繞道 | 〔源:feedback_dont_overapply_interactive_cli_rule·claude-opus-4-7·2026-05-16〕 |
| `fix-attempt-budget-2` | 通用 | **能力繞道** | 上限 2 次是能力相關閾值；口徑 SSOT 在 subagent-routing.md |

### a5. `references/subagent-routing.md`（能力繞道類主場、整檔 y）

| slug | 類別傾向 | 備註 |
|---|---|---|
| `three-way-task-classification` | 能力繞道 ★★ | 實作／機械／判斷 的模型對照本身就是換代重校對象 |
| `security-sensitive-modifier` | 能力繞道 ★★ | 存在理由是「Fable 級模型的安全分類器可能中途拒絕正當防禦性工作」→ 換代後該假設必重驗。Re-checked 2026-09-02（fable-5-1）：官方 prompting guide 說分類器 false positive 比 Fable 5 發布時少、找漏洞明文允許，但 `stop_reason: refusal` 仍在 → 保留，理由改「機率低非零」 |
| `fable-quota-policy` | 能力繞道 ★★ | 檔內明文「政策撤了本段整段刪、不是永久凍結」= 自帶退役條件的規則典範。Re-checked 2026-09-02：support 15424964 確認 50% cap 延續、Fable 5／5.1 共用同一桶 → 未觸發退役 |
| `routed-token-gate` | 能力繞道 | T2-routing-gate 的 model 欄屬 v1.5（本 plan 未做） |
| `escalation-ladder-sonnet-opus-fable` | 能力繞道 ★★ | 三級階梯的每一級都是 model id |
| `distill-down-to-sonnet` | 能力繞道 | 「spec 完整後就是機械任務」的能力假設 |
| `t2-gate-retire-trigger` | 能力繞道 | 退役判準明文綁「vendor／model 切換事件期間攔截數」→ 與本體系直接接線 |

`references/effort-controls.md` 7 行全屬使用者側操作說明 → **n**（effort 檔位語意雖 model-dependent，但檔內容是按鍵與指令、不含判斷閾值）。

### a6. 範圍外但 plan 明列的起點

| slug | 檔 | 類別傾向 | 出生證明 |
|---|---|---|---|
| `no-askuserquestion-inline-options` | `memory/MEMORY.md` Feedback 段（always-on inject） | 平台繞道 | 〔源:feedback_no_askuserquestion_inline_options_instead·claude-fable-5·2026-07-05〕 |

⚠️ `MEMORY.md` 本身是 always-on 注入面，但本次**未逐行盤**（範圍界定在 CLAUDE.md／rules／SSOT／參數層＋plan 明列起點）。是否納入下輪盤點見 c 段 L7。

## b. model/effort 參數點清單（能力繞道實值層）

換代重校時**必改**的字面值住在這裡。共 51 處。

| 檔 | 處數 | 實值 | 換代重校時必改 |
|---|---|---|---|
| `agents/` 12 檔 | 23 行 | opus×6（python/typescript/code/architecture/security/spec-compliance-reviewer）、sonnet×6（docs-lookup／deep-explore／chrome-fetcher／semble-search／parallel-search／url-fetcher）；effort xhigh×5、high×1、low×5 | ✅ 全部。**2026-07-25 alias 位移的受災面就是這 6 個 opus 檔**（零本地改動整隊換裝 claude-opus-5） |
| `workflows/` | 21 處 | `model: 'opus'`×7、`effort: 'xhigh'`×6、`model: 'sonnet'`×4、`model: 'haiku'`×3、`model: 'inherit'`×1 | ✅ opus 那 7 處同受 alias 位移影響；haiku 3 處照 SSOT「機械一律 workflow 寫死」屬刻意 |
| `settings.json` | 7 處 | `model: "opus[1m]"`（← alias、位移入口）、`fallbackModel: ["claude-opus-4-7[1m]","claude-sonnet-4-6[1m]"]`（← 釘死具體 id）、`effortLevel: "xhigh"`、`CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS: "5"`、deny `Agent(Explore)`／`Agent(model:haiku)` | ✅ `model` 用 alias 是刻意（維持浮動 alias 拍板）、但**它就是 2026-07-25 靜默換裝的單點**；fallbackModel 釘死 id 反而不受位移影響 |

觀察：**alias（浮動）與釘死 id 在同一份 settings.json 並存**——主 model 走 alias 會靜默換代、fallback 釘 id 不會。這個不對稱是換代 review 的固定檢查項。

## c. 仲裁紀錄（低信心條目、待使用者拍板）

按 spec §5.3 的門檻，本段只存「**不可重算**的資訊」。2026-07-25 首輪盤點初列 7 項候選，逐項過門檻後 **6 項不合格**（可查證或可自決）→ 已就地裁定、不佔用使用者拍板；剩 1 項延 v1.5。

### 已自決（不合格於「不可重算」門檻）

| # | 議題 | 裁定與依據 |
|---|---|---|
| L1 | `plain-language-default` 的出生來源 | **查證解決、非決策**：出生源是 trial 行為數據（trials `plain-language-rule-wording-v2`、30 天糾正 8 次、資料源 `~/code/social-info/reports/local-analysis/rule-adherence-ledger.jsonl`、review 日 2026-07-28、07-21 已拍板補觀察期），memory 側只有範圍限定 brainstorm 的 sibling `feedback_brainstorm_plain_language_specs`（claude-opus-4-8·2026-06-13）。本規則標「trial 觀察中」、07-28 review 後補出生證明 |
| L2 | `split-lookup-vs-decision` 與 `converge-questions-one-round` 是否同源 | **自決**：slug 粒度屬「可逆內部格式」（[[feedback_ask_only_major_decision_forks]] 明文不問）。判同源於 `ask_only_major_decision_forks`、保留兩 slug（一條管「問不問」、一條管「怎麼問」，換代時可能一留一退） |
| L3 | `state-doc-is-claim-not-evidence` 是否併入 `claim-evidence-alignment` | **自決**（同 L2 理由）：不併 |
| L4 | 偏好類 enforcement 注入文字要不要列 y | **自決**：只列有出生證明的 `anti-crystal-english`；繁中／commit 規範標 n。理由＝反過度工程、enforcement 退役屬 review 現場判斷 |
| L5 | `dcg-no-destructive-literals` 的類別歸屬 | **自決、且仲裁本身無意義**：spec §4 明文「類別在 review 現場由 LLM 重算」、本表類別欄非權威。記平台繞道＋備註模型面 |
| L6 | 4 條出生模型 `unknown` 追不追 | **事實、非決策**：4 條的 `originSessionId` 是 slug 型或 session 檔已不存在、無可回推來源。接受 unknown |

### 延 v1.5（不阻塞 v1）

| # | 議題 | 處置 |
|---|---|---|
| L7 | `MEMORY.md`（也是 always-on 注入面）要不要納入逐行盤點 | 排 v1.5、不現在拍。它是 157 條 feedback 的索引、逐行盤等於盤整個 memory 層 |

### 真待拍板（送使用者）

| # | 議題 | 狀態 |
|---|---|---|
| U1 | skills／commands 納管範圍 | ✅ **2026-07-25 使用者拍板：照建議**——納管 5 檔（`review-spec` / `grill-me-one-shot` / `pr-review` / `save-session` / `workflow-hardening`），其餘 7 檔標 FYI 不納管。詳見 d 段 |
| U2 | 定向回填的 always-on context 稅 | ✅ **2026-07-25 使用者拍板：選 (b) 刪掉 inline 標記**。原本回填進 always-on 面的 26 處 `〔源:…〕`（實測 +1,854 位元組 / 每 session 開場都付）已全數移除，驗證 `rules/common/` 對 HEAD 零差異、`CLAUDE.md` 僅剩無關的既有改動。**出生證明自此只住本檔**（a 段 29 筆、on-demand 讀）。<br>拍板依據：出生證明的消費時機是換代 review（一年幾次），不是每次對話；且維護面 (a)(b) 平手——inline 漏貼一張看不出來，本檔至少有量體數字可對帳。<br>⚠️ 過程修正：原提案的「搬到檔尾區塊」選項**無效**，always-on 檔是整檔注入、字放第 7 行或第 200 行成本相同 |

## d. skills／commands 層納管（✅ 2026-07-25 使用者拍板：照建議）

66 skills／25 commands，含 model/effort 字面值者 **12 檔**：

| 層 | 檔 | 字面值性質 | 裁定（已拍板） |
|---|---|---|---|
| commands | `review-spec.md` / `grill-me-one-shot.md` / `pr-review.md` | `review-spec` Tier 3 正式 Opus＋Fable 配對；`grill-me-one-shot` 與 `pr-review` reviewer 的 opus+xhigh 實值 | **納管** ✅——2026-08-13 起只有 `review-spec` Tier 3 保留正式雙跑；`grill-me-one-shot` 單 Opus，`pr-review` Fable 影子已退役，歷史 ledger 凍結唯讀 |
| commands | `save-session.md` | `model: sonnet`（rubric 對表、刻意降級為機械類） | **納管** ✅（單一實值、換代時屬機械類重校面） |
| skills | `workflow-hardening/SKILL.md` | §8 明文是 subagent-routing SSOT 的 workflow 延伸、含 `{model:'sonnet'}`／`{model:'opus',effort:'xhigh'}` 實值 | **納管** ✅——SSOT 的合法第二現場、不納管會漂 |
| skills | `absorb-pack` / `bitbucket-pr-review` / `check-my-stack` / `explain-diff` / `github-repo-research` / `mutation-testing` | 多為「派某 model 做某事」的操作敘述 | **不納管、標 FYI** ✅——反過度工程；真要改時 grep 這幾檔即可 |

其餘 58 skills／21 commands 無 model/effort 字面值 → 不納管。

## 維護方式（本檔**不常駐維護**）

照 spec §5.2 拍板的原則——「換代 review 時帳本視圖一次性 grep 生成、不常駐維護」。本檔是**快照**、不是活帳本。四條：

**1. 新規則的出生證明走機器、不靠往本檔補。** 2026-07-25 起 L0 蓋欄已上線（`memory-ripple.sh` 每次 memory 寫入自動記 `model`＋`cc_version` 進 audit）＋ Tier 1 慣例行要求 feedback／violation 條目內文帶「模型:」「CC 版本:」。所以此後出生的規則，出生證明長在 memory 條目自己身上。本檔 a 段的出生證明欄是**歷史 26 筆的一次性回填**，不是需要逐事件追加的帳。

**2. 消費時機只有一個：換代 review（spec §8）。** review 第一步跑 staleness 對帳（實測 0.04 秒）：

```bash
printf "CLAUDE.md規則行 %s\n"    "$(grep -c '^- \|^## ' ~/.claude/CLAUDE.md)"
printf "fact-check條 %s\n"       "$(grep -c '^[0-9]\+\. \*\*' ~/.claude/rules/common/fact-check.md)"
printf "dispatch規則行 %s\n"     "$(grep -c '^- \|^[0-9]\+\. \*\*' ~/.claude/rules/common/dispatch-and-verify.md)"
printf "performance行 %s\n"      "$(grep -c '^- ' ~/.claude/rules/common/performance.md)"
printf "routing-SSOT段 %s\n"     "$(grep -c '^## \|^### ' ~/.claude/references/subagent-routing.md)"
printf "agents參數行 %s\n"       "$(grep -rh -E '^(model|effort):' ~/.claude/agents/*.md | wc -l | tr -d ' ')"
printf "workflows參數處 %s\n"    "$(grep -roh -E "model: *'[a-z0-9.-]+'|effort: *'[a-z]+'" ~/.claude/workflows/*.js | wc -l | tr -d ' ')"
printf "skills含參數檔 %s\n"     "$(grep -rl -E "model: *['\"]?(haiku|sonnet|opus|fable)|effort: *['\"]?(low|medium|high|xhigh|max)" ~/.claude/skills/*/SKILL.md ~/.claude/commands/*.md 2>/dev/null | wc -l | tr -d ' ')"
```

**對帳基準（2026-07-25 首次盤點、harness_sha `bdfb403c7f51-dirty`——與 L2 baseline 產生時同值，U2 刪 inline 後注入面內容回到位元組級一致）**：CLAUDE.md規則行 76／fact-check條 11／dispatch規則行 19／performance行 3／routing-SSOT段 15／agents參數行 23／workflows參數處 21／skills含參數檔 12。

**3. 對不上就增量重算、不重做全量。** 數字有差 → grep 出當前規則行清單、diff 對照本檔 a 段 slug 清單、只對「新出現／消失」的規則做 y/n 判斷。首輪全量盤點實耗約 40 分鐘；增量通常 < 5 分鐘。

**4. 誰提醒去 review。** 每次換代在 `~/Desktop/projects/.claude/trials/active.md` 開一條 `<model>-swap-review` H2（例：`opus-5-5-swap-review`），由它的 review 日觸發（`trial-review.sh` hook 是唯一 ledger）。機制本身的觀察 trial `model-harness-coevolution-mechanism` 已於 2026-09-24 KEEP 結案、見 `archived.md`。本檔不自帶提醒機制、也不該自帶。

**已知殘留風險（設計選擇、非缺陷）**：兩次 review 之間本檔會 stale。這是 spec 拍板的取捨——換「零常駐維護成本」，代價是 review 當天多跑一次增量對帳。對照組是「常駐維護」：每次動 always-on 規則都要記得同步本檔，照 [[feedback_always_on_rule_adherence_empirical_low]]（自律型規則命中率 1-2%）那條路會靜默失敗，比 stale 更糟。

## Cross-link

- 設計 SSOT：`~/Desktop/projects/memory-backlog-research/docs/superpowers/specs/2026-07-25-model-harness-coevolution-design.md`（v2）
- 能力繞道類 SSOT：`~/.claude/references/subagent-routing.md`
- L2 成績單 baseline：`~/Desktop/projects/memory-backlog-research/docs/superpowers/specs/2026-07-25-l2-scorecard-baseline.md`
- 換代事件實錘：memory `reference_opus5_alias_drift_2026_07_25`
- 偵測 hook：`~/.claude/hooks/model-drift-watch.sh`（seen 清單 `hooks/state/seen-models.txt`）
