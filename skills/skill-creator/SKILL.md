---
name: skill-creator
description: "Guide for creating effective skills. This skill should be used when users want to create a new skill (or update an existing skill) that extends Claude's capabilities with specialized knowledge, workflows, or tool integrations. Chinese triggers include: 固化 / 記錄下來 / 流程化 / 做個 skill / 做個 slash / 做個 command. Do not use for one-off solutions, standard practices already well-documented elsewhere, project-specific conventions (those belong in CLAUDE.md), or mechanical constraints enforceable by regex/validation (automate those instead)."
license: Complete terms in LICENSE.txt
---
<!-- Modified from the original work at https://github.com/anthropics/skills/tree/main/skills/skill-creator (Apache-2.0, copyright Anthropic, PBC). See THIRD_PARTY_NOTICES.md. -->
<!-- 本檔在契約測試底下：bash ~/.claude/skills/skill-creator/scripts/tests/skill-authoring-contract.test.sh；python3 ~/.claude/commands/tests/test_skill_verify_one_shot_callers.py -->

# Skill Creator

> **出處注記（2026-06-12）**：本檔底本 = 官方 anthropics/skills `0f77e501`（2025-11-17 版，byte 級確認）。官方 2026-02-06 [#350](https://github.com/anthropics/skills/pull/350) 整支重寫為 eval-loop 路線（人造 test case + benchmark + viewer 人審），**刻意不跟**——本地驗證鏈（skill-creator 內建 RED → GREEN → REFACTOR + fresh GREEN subagent 實跑 + B 線生產資料漂移抽查）更便宜且已實證。不要「同步上游」覆蓋本檔；上游動態由 skill-upstream-check weekly 巡邏。

This skill provides guidance for creating effective skills.

## About Skills

Skills are modular, self-contained packages that extend Claude's capabilities by providing
specialized knowledge, workflows, and tools. Think of them as "onboarding guides" for specific
domains or tasks—they transform Claude from a general-purpose agent into a specialized agent
equipped with procedural knowledge that no model can fully possess.

### What Skills Provide

1. Specialized workflows - Multi-step procedures for specific domains
2. Tool integrations - Instructions for working with specific file formats or APIs
3. Domain expertise - Company-specific knowledge, schemas, business logic
4. Bundled resources - Scripts, references, and assets for complex and repetitive tasks

## Core Principles

### Concise is Key

The context window is a public good. Skills share the context window with everything else Claude needs: system prompt, conversation history, other Skills' metadata, and the actual user request.

**Default assumption: Claude is already very smart.** Only add context Claude doesn't already have. Challenge each piece of information: "Does Claude really need this explanation?" and "Does this paragraph justify its token cost?"

Prefer concise examples over verbose explanations.

### Set Appropriate Degrees of Freedom

Match the level of specificity to the task's fragility and variability:

**High freedom (text-based instructions)**: Use when multiple approaches are valid, decisions depend on context, or heuristics guide the approach.

**Medium freedom (pseudocode or scripts with parameters)**: Use when a preferred pattern exists, some variation is acceptable, or configuration affects behavior.

**Low freedom (specific scripts, few parameters)**: Use when operations are fragile and error-prone, consistency is critical, or a specific sequence must be followed.

Think of Claude as exploring a path: a narrow bridge with cliffs needs specific guardrails (low freedom), while an open field allows many routes (high freedom).

### Anatomy of a Skill

Every skill consists of a required SKILL.md file and optional bundled resources:

```
skill-name/
├── SKILL.md (required)
│   ├── YAML frontmatter metadata (required)
│   │   ├── name: (required)
│   │   └── description: (required)
│   └── Markdown instructions (required)
└── Bundled Resources (optional)
    ├── scripts/          - Executable code (Python/Bash/etc.)
    ├── references/       - Documentation intended to be loaded into context as needed
    └── assets/           - Files used in output (templates, icons, fonts, etc.)
```

#### SKILL.md (required)

Every SKILL.md consists of:

- **Frontmatter** (YAML): Contains `name` and `description` fields. These are the only fields that Claude reads to determine when the skill gets used, thus it is very important to be clear and comprehensive in describing what the skill is, and when it should be used.
- **Body** (Markdown): Instructions and guidance for using the skill. Only loaded AFTER the skill triggers (if at all).

### Separate invocation capability from trigger condition

When authoring a skill, document these as separate fields:

- **Invocation capability**: State whether the model can call the skill, which explicit user entry points exist, and which parent `Skill(...)` edges are active. Preserve Skill-to-Skill wiring by default.
- **Trigger condition**: State the observable authoring guidance for when to choose the skill. For a pipeline-gated child, keep it model-callable; describe the trigger condition as authoring guidance, not a runtime hard gate.

Do not turn a trigger condition into a hard flag that suppresses an active parent edge. Keep `disable-model-invocation` omitted by default；預設不使用它，因為 it removes a model-callable path and can silently break a parent→child edge. 使用 `disable-model-invocation` 前，先記錄 user-only 理由，再完成 inbound wiring inventory.

### Frontmatter field classes

Keep frontmatter claims in three separate classes:

- **runtime required**: Fields the Claude runtime actually consumes.
- **local validator accepted**: Fields accepted by the local validator, such as `quick_validate.py`; acceptance only describes this repository's parser.
- **local convention**: Fields or metadata used by local tooling or authoring convention, with no implied runtime behavior.

The validator `ALLOWED_PROPERTIES` is an allowlist for local validation, not evidence of platform support. Verify platform behavior from the platform contract or a real invocation before documenting it.

### Inbound wiring inventory

Before changing invocation behavior, scan skills, commands, workflows, registry entries, and frontmatter for inbound edges. Also scan `Skill(...)` calls, slash-command references, and prose references. Record every edge as `path:line`. A dynamic or planned edge without a registry entry is `unverified`, not an available trigger.

### Context pointers

Write every pointer in this form: `如果 X，就在 Y 前讀 Z`.

- `X` must be an observable（可觀察）condition.
- `Y` must name the execution timepoint（時點）.
- `Z` must name a concrete location to read.

A pointer is incomplete when it omits any slot.

#### Bundled Resources (optional)

##### Scripts (`scripts/`)

Executable code (Python/Bash/etc.) for tasks that require deterministic reliability or are repeatedly rewritten.

- **When to include**: When the same code is being rewritten repeatedly or deterministic reliability is needed
- **Example**: `scripts/rotate_pdf.py` for PDF rotation tasks
- **Benefits**: Token efficient, deterministic, may be executed without loading into context
- **Note**: Scripts may still need to be read by Claude for patching or environment-specific adjustments

##### References (`references/`)

Documentation and reference material intended to be loaded as needed into context to inform Claude's process and thinking.

- **When to include**: For documentation that Claude should reference while working
- **Examples**: `references/finance.md` for financial schemas, `references/mnda.md` for company NDA template, `references/policies.md` for company policies, `references/api_docs.md` for API specifications
- **Use cases**: Database schemas, API documentation, domain knowledge, company policies, detailed workflow guides
- **Benefits**: Keeps SKILL.md lean, loaded only when Claude determines it's needed
- **Best practice**: If files are large (>10k words), include grep search patterns in SKILL.md
- **Avoid duplication**: Information should live in either SKILL.md or references files, not both. Prefer references files for detailed information unless it's truly core to the skill—this keeps SKILL.md lean while making information discoverable without hogging the context window. Keep only essential procedural instructions and workflow guidance in SKILL.md; move detailed reference material, schemas, and examples to references files.

##### Assets (`assets/`)

Files not intended to be loaded into context, but rather used within the output Claude produces.

- **When to include**: When the skill needs files that will be used in the final output
- **Examples**: `assets/logo.png` for brand assets, `assets/slides.pptx` for PowerPoint templates, `assets/frontend-template/` for HTML/React boilerplate, `assets/font.ttf` for typography
- **Use cases**: Templates, images, icons, boilerplate code, fonts, sample documents that get copied or modified
- **Benefits**: Separates output resources from documentation, enables Claude to use files without loading them into context

#### What to Not Include in a Skill

A skill should only contain essential files that directly support its functionality. Do NOT create extraneous documentation or auxiliary files, including:

- README.md
- INSTALLATION_GUIDE.md
- QUICK_REFERENCE.md
- CHANGELOG.md
- etc.

The skill should only contain the information needed for an AI agent to do the job at hand. It should not contain auxilary context about the process that went into creating it, setup and testing procedures, user-facing documentation, etc. Creating additional documentation files just adds clutter and confusion.

### Progressive Disclosure Design Principle

Skills use a three-level loading system to manage context efficiently:

1. **Metadata (name + description)** - Always in context (~100 words)
2. **SKILL.md body** - When skill triggers (<5k words)
3. **Bundled resources** - As needed by Claude (Unlimited because scripts can be executed without reading into context window)

#### Progressive Disclosure Patterns

Keep SKILL.md body to the essentials and under 500 lines to minimize context bloat. Split content into separate files when approaching this limit. When splitting out content into other files, it is very important to reference them from SKILL.md and describe clearly when to read them, to ensure the reader of the skill knows they exist and when to use them.

**Key principle:** When a skill supports multiple variations, frameworks, or options, keep only the core workflow and selection guidance in SKILL.md. Move variant-specific details (patterns, examples, configuration) into separate reference files.

三種拆分範式的完整範例（高層導覽＋references／按領域或變體分目錄／條件式細節）在 [references/progressive-disclosure-patterns.md](references/progressive-disclosure-patterns.md)；如果要把 SKILL.md 拆成多檔，就在動手前讀它，對照自己屬於哪一型。

**Important guidelines:**

- **Avoid deeply nested references** - Keep references one level deep from SKILL.md. All reference files should link directly from SKILL.md.
- **Structure longer reference files** - For files longer than 100 lines, include a table of contents at the top so Claude can see the full scope when previewing.

## Skill Creation Process

Skill creation involves these steps:

1. Understand the skill with concrete examples
2. Plan reusable skill contents (scripts, references, assets)
3. Initialize the skill (run init_skill.py)
4. Edit the skill (implement resources and write SKILL.md)
5. Package the skill (run package_skill.py)
6. Iterate based on real usage

Follow these steps in order, skipping only if there is a clear reason why they are not applicable.

### Step 1: Understanding the Skill with Concrete Examples

Skip this step only when the skill's usage patterns are already clearly understood. It remains valuable even when working with an existing skill.

To create an effective skill, clearly understand concrete examples of how the skill will be used. This understanding can come from either direct user examples or generated examples that are validated with user feedback.

For example, when building an image-editor skill, relevant questions include:

- "What functionality should the image-editor skill support? Editing, rotating, anything else?"
- "Can you give some examples of how this skill would be used?"
- "I can imagine users asking for things like 'Remove the red-eye from this image' or 'Rotate this image'. Are there other ways you imagine this skill being used?"
- "What would a user say that should trigger this skill?"

Put the open questions to the user in one round, each with your recommended answer, unless they've asked to be interviewed one at a time.

Conclude this step when there is a clear sense of the functionality the skill should support.

### Step 2: Planning the Reusable Skill Contents

To turn concrete examples into an effective skill, analyze each example by:

1. Considering how to execute on the example from scratch
2. Identifying what scripts, references, and assets would be helpful when executing these workflows repeatedly

Example: When building a `pdf-editor` skill to handle queries like "Help me rotate this PDF," the analysis shows:

1. Rotating a PDF requires re-writing the same code each time
2. A `scripts/rotate_pdf.py` script would be helpful to store in the skill

Example: When designing a `frontend-webapp-builder` skill for queries like "Build me a todo app" or "Build me a dashboard to track my steps," the analysis shows:

1. Writing a frontend webapp requires the same boilerplate HTML/React each time
2. An `assets/hello-world/` template containing the boilerplate HTML/React project files would be helpful to store in the skill

Example: When building a `big-query` skill to handle queries like "How many users have logged in today?" the analysis shows:

1. Querying BigQuery requires re-discovering the table schemas and relationships each time
2. A `references/schema.md` file documenting the table schemas would be helpful to store in the skill

To establish the skill's contents, analyze each concrete example to create a list of the reusable resources to include: scripts, references, and assets.

### Step 3: Initializing the Skill

At this point, it is time to actually create the skill.

Skip this step only if the skill being developed already exists, and iteration or packaging is needed. In this case, continue to the next step.

When creating a new skill from scratch, always run `scripts/init_skill.py` — it generates the required directory and frontmatter template.

Usage:

```bash
scripts/init_skill.py <skill-name> --path <output-directory>
```

The script:

- Creates the skill directory at the specified path
- Generates a SKILL.md template with proper frontmatter and TODO placeholders
- Creates example resource directories: `scripts/`, `references/`, and `assets/`
- Adds example files in each directory that can be customized or deleted

After initialization, customize or remove the generated SKILL.md and example files as needed.

### Step 4: Edit the Skill

When editing the (newly-generated or existing) skill, remember that the skill is being created for another instance of Claude to use. Include information that would be beneficial and non-obvious to Claude. Consider what procedural knowledge, domain-specific details, or reusable assets would help another Claude instance execute these tasks more effectively.

#### Learn Proven Design Patterns

Consult these helpful guides based on your skill's needs:

- **Multi-step processes**: See references/workflows.md for sequential workflows and conditional logic
- **Specific output formats or quality standards**: See references/output-patterns.md for template and example patterns

These files contain established best practices for effective skill design.

#### Start with Reusable Skill Contents

To begin implementation, start with the reusable resources identified above: `scripts/`, `references/`, and `assets/` files. Note that this step may require user input. For example, when implementing a `brand-guidelines` skill, the user may need to provide brand assets or templates to store in `assets/`, or documentation to store in `references/`.

Added scripts must be tested by actually running them to ensure there are no bugs and that the output matches what is expected. If there are many similar scripts, only a representative sample needs to be tested to ensure confidence that they all work while balancing time to completion.

Any example files and directories not needed for the skill should be deleted. The initialization script creates example files in `scripts/`, `references/`, and `assets/` to demonstrate structure, but most skills won't need all of them.

#### Update SKILL.md

**Writing Guidelines:** Always use imperative/infinitive form.

##### Frontmatter

Write the YAML frontmatter with `name` and `description`:

- `name`: The skill name
- `description`: This is the primary triggering mechanism for your skill, and helps Claude understand when to use the skill.
  - Include both what the Skill does and specific triggers/contexts for when to use it.
  - `description` is the only field the router reads, so every trigger and exclusion must appear there. A body When-to-use section is a *mirror* for the executing agent: keep it in sync with the description (see 使用者本地規範 #12) or omit it.
  - Example description for a `docx` skill: "Comprehensive document creation, editing, and analysis with support for tracked changes, comments, formatting preservation, and text extraction. Use when Claude needs to work with professional documents (.docx files) for: (1) Creating new documents, (2) Modifying or editing content, (3) Working with tracked changes, (4) Adding comments, or any other document tasks"

`name` and `description` are the trigger-facing fields. Include other frontmatter only after classifying it as runtime required, local validator accepted, or local convention; validator acceptance alone is not platform support.

##### Body

Write instructions for using the skill and its bundled resources.

### Step 5: Packaging a Skill

> **本地注記（2026-07-10，實測後條件化）**：個人單機 skill **預設跳過本步驟**——35 個自寫 skill 實測打包採用 ≈ 0、備份分享走 config repo git（example-owner/claude-config），打包檔只會變 stale 殘留。只有**要對外分發**（上傳 claude.ai / 打包給他人安裝）才跑 `package_skill.py`。跳過時不算漏步驟。

Once development of the skill is complete, it must be packaged into a distributable .skill file that gets shared with the user. The packaging process automatically validates the skill first to ensure it meets all requirements:

```bash
scripts/package_skill.py <path/to/skill-folder>
```

Optional output directory specification:

```bash
scripts/package_skill.py <path/to/skill-folder> ./dist
```

The packaging script will:

1. **Validate** the skill automatically, checking:

   - YAML frontmatter format and required fields
   - Skill naming conventions and directory structure
   - Description completeness and quality
   - File organization and resource references

2. **Package** the skill if validation passes, creating a .skill file named after the skill (e.g., `my-skill.skill`) that includes all files and maintains the proper directory structure for distribution. The .skill file is a zip file with a .skill extension.

If validation fails, the script will report the errors and exit without creating a package. Fix any validation errors and run the packaging command again.

### Step 6: Iterate

After testing the skill, users may request improvements. Often this happens right after using the skill, with fresh context of how the skill performed.

**Iteration workflow:**

1. Use the skill on real tasks
2. Notice struggles or inefficiencies
3. Identify how SKILL.md or bundled resources should be updated
4. Follow the RED → GREEN → REFACTOR behavior validation below; the GREEN step owns the first text change. A mechanical edit takes the three deterministic checks at the top of that section instead.

### RED → GREEN → REFACTOR：行為驗證

Text changes need behavior evidence because a static contract can confirm wording is present but cannot show that a fresh agent follows it under pressure. Keep the loop tight:

**A mechanical edit takes deterministic checks instead of the loop.** An edit is mechanical when it only renames, re-points a path, link or pointer, and changes nothing about what an agent decides or does; adding a step, a rule, a condition or a trigger is not mechanical, and an edit you cannot classify is not mechanical. A fresh runner is the wrong instrument here: it usually works around a broken path and reports success. Run all three checks and keep their output:

1. Every path, file and link on each changed line exists (`test -e` or `ls`, one per reference, run from the directory the line's reader resolves it against).
2. Every changed command is checked against `--help` or its source for its subcommands and flags.
3. `command grep -rn` the old name or path across the skill and its callers returns nothing left behind.

Any failure is fixed and the three checks run again. Done when all three pass with their output recorded; no RED, GREEN or REFACTOR runner is dispatched.

1. **RED** — Before changing skill text, have a fresh agent run the scenario against the pre-change skill and record the observed behavior. If wording was already changed, restore the pre-change version and discard the untested wording before collecting this baseline. The RED scenario must be 同型 with the production call path: same prompt text, same input shape, and the agent judges on its own. 設計 fixture 前，先找出會在受測規則之前處理輸入的條件；只在合成資料中滿足未受測的前置條件，不把待驗規則或答案寫進 fixture，也不繞過真實權限。若 runner 因另一條前置規則而未到達受測決策點，記為無效 baseline，修正 fixture 後再跑 RED。 If RED does not turn red, estimate the original failure rate and the statistical power of this n, and record the run as an 無效 baseline — never treat "no red" as evidence the change is already fixed. Then stop the loop: do not run GREEN or REFACTOR on a failure no run has shown. Report 「無法證明有問題」 with the run, the estimate and the fixture, and let the user decide whether to change the text anyway, collect more evidence, or drop it. A RED that missed only because its fixture leaked the answer or stopped before the decision point is fixed and re-run once; that is not a second chance for a scenario that simply did not fail. When the file under test is one this same task just created, it is already live in the agent's skill／command list: a RED runner can find it and follow it, which yields a second GREEN rather than a baseline. Close both routes in the RED prompt — the file's directory and the Skill／slash-command invocation path — and treat a run whose trace shows the runner read the file under test as an 無效 baseline, the same as a run that never turned red. 節錄式 runner 只收到手貼內容時，證據副檔必須先寫明節錄邊界；它只對節錄內行為有判讀效力，節錄外偏差一律標 `out-of-scope`、不得當成 finding。若無效 baseline 的原因是 production worker 不可實例化，而非樣本量不足，直接標「行為驗證不可得」並停止補跑；把落地保證改放在 caller 對 sentinel／artifact 產物的確定性檢查，文字強化只記為未驗證。行為驗證碰到 Self-Verify「一次 auditor」硬限制時，不得另開例外來繞過；同型 production auditor 結構上叫不到時，使用最接近的合法 runner，明寫 worker mismatch 與證據降級。
2. **GREEN** — Give the same scenario to another fresh agent using the changed skill. Compare behavior, not just quoted instructions; the scenario should show the intended correction. 如果本次新增或修改 CLI 用法，就在驗收文字前，用該環境的 --help 或原始碼逐項核對子指令、旗標與列舉值；只查本次改動，不掃全庫。記下實際查詢與輸出；這只證明用法有效，不替代實際執行的行為證據。 When the scenario requires filesystem, settings, process, or another external action, require 外部可觀察 evidence: a tool receipt and the expected sentinel／artifact. `tool_uses=0` or a missing expected artifact makes the run `invalid`; agent final 自述不算行為證據. Replace it with a fresh runner that can execute and leave the required evidence. Frame every runner as a 行為單元測試: state that it must not start the command's full infrastructure, and give an explicit output shape plus a line cap (for example ≤30 lines) so the runner cannot expand into unbounded work.
3. **REFACTOR** — Add a new pressure or loophole scenario that could pass while evading the intent. After the fix, rerun the original scenario and every regression scenario, then keep only wording that survives all of them.

Treat "keep the candidate as reference" and "retrofit tests around it" as red flags. Do not archive, consult, reapply, or adapt that candidate; after RED, write the GREEN change from the observed failure.

Use this failure-form selector to choose the repair shape:

| Failure form | Guidance form | Why |
|---|---|---|
| discipline skip | prohibition / rationalization table / red flags | Close the known escape route rather than restating a rule. |
| wrong shape | positive recipe | Show the form that produces the desired behavior. |
| omission | required slot | Make the missing artifact or decision impossible to overlook. |
| conditional | observable predicate | Tie the branch to a signal an agent can inspect. |

Static validation, including grep or a contract test, does not replace behavioral evidence: it proves the text is reachable, not that an agent uses it. Keep this loop in skill-creator so later skill edits have one local source of truth; do not outsource the behavior check to another writing guide.

## 使用者本地規範（每次建/改 skill 都適用）

### 寫 skill 三判準

1. **先過濾**——只固化「領域性解題流程」，純基礎對話能力（追問 / 清單 / 推薦）不做成 skill
2. **描述段寫「為何這做法有效 / 關鍵轉折」**而非步驟流水帳；同時 description 只寫觸發條件、絕不摘要流程（摘要會讓 Claude 照 description 走捷徑跳過讀 body）
3. **踩過的坑寫進該 skill 的 `LESSONS.md`（body 只留由它改出來的規則本身）**；每條一行、規則落地後就刪掉敘事，段落不得只增不減（手動，不做自動評分）
4. **全大寫命令是黃旗**：發現自己在寫 ALWAYS / NEVER / 「必須」式剛性命令，通常代表沒把理由講清楚——改成解釋「為什麼」，模型理解理由比被命令更可靠（源自官方新版 "explain the why"）
5. **重複手寫的 code 收進 scripts/**：skill 的多次執行裡 agent 反覆現場寫同形狀的 code（同段 jq / 同個 helper）→ 寫成固定檔案放該 skill `scripts/`，以後直接跑檔不重新發明。寫作時想到就先做；沒想到的由 distill-weekly B 線第三鏡頭從生產軌跡撈（偵測機制在那邊，這裡只管 authoring 時的預判）
6. **description 寫完自己出考題**：手列 3-5 句「該觸發的使用者說法」+ 3-5 句「不該觸發的」，逐句對 description 檢查判得對不對（description-gate hook 只能查「有沒有反向排除」，查不了「排除準不準」，這條自查補洞）
7. **評估要不要加 Self-Verify 段**（2026-07-07 加；skill-self-verify trial 三 skill 對照實證：SKILL.md 內置 verify dispatch 指令採用率 100%、sonnet rubric 對表品質真實有 FAIL 有修正——完整 verdict 在 `~/Desktop/projects/.claude/trials/archived.md`）。三問全 yes 才加、任一 no 不加並在該 skill「踩過的坑」段記一行原因：
   - 有**結構化 output** 嗎？（產出可用 rubric 逐項對表——報告 / 檔案 / 固定骨架；純對話引導型無可對表產出 = no）
   - **低中頻**嗎？（< 10 invoke/週。每次多派一個 subagent 是真實成本，高頻 skill 要先設計 sampling 才能加——research-before-answer 836 次/30 天就是被這條擋下的）
   - **rubric 寫得出 3+ 條可判項**嗎？（每條要能寫成「PASS/FAIL + 一句證據引述」；寫不出來 = 這 skill 的品質不是 verify 對表能保的）
   - **出過判定漂移的可判項要配一對 anchor**（2026-08-29 加；機制借自 NeoLabHQ/context-engineering-kit 的 meta-judge，GPL 故改寫不抄原文）：在該條下附最短的「明顯 FAIL」與「明顯 PASS」兩段實例，兩段只差被判的那一件事；審查員對著 anchor 放位置，不按比例或分數帶。為什麼：只寫判準時，審查員每次自己決定「哪些算」，同一份稿兩輪答案不同（rba 信心標記 2026-08-29 實證：無 anchor 兩輪各抓 2／1 處，加 anchor 後 2/2 抓全 5–6 處）。rubric 變長是真實成本，所以先只加在已漂移的那條，不全面補
   - 加的時候照活範本抄結構：`~/.claude/commands/save-session.md` Step 4.5——dispatch 規格（marker 字串 `skill-verify:<skill名>` **放 description**、`subagent_type: skill-verify-auditor`——sonnet+low、tools 僅 Read，定義檔釘死）/ adversarial rubric prompt（偏置找違規、無法確認就 FAIL）/ 固定 VERDICT 行 / 下方四態收尾。放置位置遵守下方接線判準：output 產出步驟之後、呈現步驟之前，前一步末尾加指針
   - **一個回合、一個 skill、一次 auditor**（2026-09-22 加，配合 `hooks/skill-verify-once-gate.py` hard gate）。marker 一定放 description：gate 從那裡取 skill 名決定額度 key，prompt-only 是舊寫法、已不是正式接線。Self-Verify 段必須寫明「不得重派 auditor、也不得用 SendMessage 續問同一個 auditor」，並把收尾寫成四個可判定的分支，各自落在下列 canonical token 之一（caller 自己的行格式與 emoji 不必統一，token 要統一）：
     - `COMPLIANT` — 全 PASS／N-A
     - `FIXED_AFTER_AUDIT` — 有 FAIL 且已修正；同句明寫「未經第二次獨立稽查」
     - `FAILED` — 有 FAIL 且修不掉；同時**刪除或收窄**該條撐不住的主張，不得原樣交付
     - `SKIPPED (<reason>)` — timeout／空輸出／格式錯誤／agent error，如實揭露未完成稽查
     為什麼不留 retry：prose 寫的「第二次仍 FAIL 才停」在 production 被違反過，模型把「修完再驗一次」讀成可以一直驗。額度改由 hook 機械攔截，skill 文字只負責說清楚四態怎麼落。四態之外**不要**自創第五種狀態；auditor rubric 自己的 verdict 值（例如 `NEEDS_HUMAN_REVIEW`）是 rubric 層的字彙，要在 skill 裡明寫它併進哪一態。deterministic test、lint、build 這類不是 auditor 的檢查不受此限，照樣可以重跑
   - 結論的適用邊界：trial 驗證的是「流程末端一次性動作」的採用率；「always-on 隨時要記得的規則」是另一種體質、有低採用前科（[[feedback_always_on_rule_adherence_empirical_low]]），不要拿這個結論外推
8. **建 / 改完同步 update `~/.claude/skills/INVENTORY.md`**（2026-06-20 加；對接 daily-local skill-desc-quality channel）：
   - 新 global skill → Global table append row、Audit=`yes`
   - 新 project-scoped skill → 對應 `## Project: <name>` section append row（section 不存在則新建）
   - 開始改 cloned skill 的 description → 該 row Audit 從 `no` 改 `yes (patched)`、備註欄加「user patched description (YYYY-MM-DD)、reason: ...」
   - 停止 patch / 同步上游 → 該 row Audit 從 `yes (patched)` 改回 `no`、備註欄加「reverted to upstream sync (YYYY-MM-DD)」
   - 退役 / 刪除 skill → row 加刪除線、備註欄記「YYYY-MM-DD 已移除、reason: ...」
   - 新 project base path → 加 `## Project: <name> (<path>)` section、wrapper 自動 onboarding
   - INVENTORY.md「維護紀律」表為 SSOT、本點是 mirror——兩邊不一致以 INVENTORY 為準
   - 為什麼這條重要：INVENTORY 是 audit channel 的 source-of-truth、不 update = daily 掃描範圍漂移、description 品質檢查白寫

9. **Leading word 概念**（2026-07-09 加；源自 mattpocock/skills writing-great-skills，外部 writing-skills review lane 未覆蓋此角度）——用 pretraining 已有的短詞（`tight` / `red` / `fog of war` / `tracer bullets`）取代「反覆重述同一組性質」的長句：
   - 「fast, deterministic, low-overhead loop」→「tight loop」
   - 「a loop you believe in」→「red」（binary observable state）
   - Body 用：agent 每次看到這詞就 anchor 同一組行為
   - Description 用：prompt / docs / code 用同一組詞 → agent 更可靠把 skill 綁到那組脈絡
   - 訊號：撞到「一組性質在 3 個地方各寫一次」→ 找 leading word 收攏成一詞

10. **步驟寫 completion criterion 要 checkable + exhaustive**（2026-07-09 加；源自 mattpocock/skills writing-great-skills）——每個編號步驟結尾寫「怎樣算做完」，兩個特性都要：
    - **Checkable**：能判 done vs not-done（不是「感覺做完」）
    - **Exhaustive**（要窮盡的地方）：「每個改過的 model 都盤點」不是「產一份 change list」
    - 模糊 criterion → 邀請 premature completion（agent 感覺做完就跳走）

11. **Read path 不指名 instruction 檔名、用 context reference**（2026-07-11 加；源自 EveryInc/compound-engineering AGENTS.md）——skill 內要 agent 查專案慣例（tracker / commit 格式 / lint 指令）時，寫「用 context 裡已有的專案指示與慣例」，不要寫「去讀 CLAUDE.md / AGENTS.md」：
    - 為什麼：root instruction 檔 session 開始就自動載入，指名去讀 = 重讀已有內容；且「指名讀 instruction dotfile」是部分 prompt-injection 防禦會 flag 的形狀
    - 例外（才指名檔案）：**寫回**慣例需要目標檔；**fresh subagent** 不繼承 parent 已載入的 instructions，要它讀的檔必須指名；讀「本來就不自動載入」的檔（子目錄 scoped 指示、STRATEGY.md 之類選配 doc）
    - 同精神：描述 capability 不描述 tool（「專案的 issue tracker（如 GitHub Issues / Asana）」而非假設某支 CLI 存在）

12. **改 description 必同日對齊 body 觸發段**（2026-07-12 加；源自 muratcankoylan/Agent-Skills-for-Context-Engineering AGENTS.md）——skill 是 multi-surface artifact：觸發判斷看 frontmatter description、執行時讀 body 的 When-to-use / Do-not-use 細則。只改其一 = 兩表面漂移（router 看的跟執行讀的不一致）。任何 description 修改，同次必對讀 body 觸發相關段並同步；desc-quality channel 只看 description、抓不到跨表面不一致，靠這條在 authoring 時堵

13. **同段不混 instruction altitude**（2026-07-12 加；源自同 repo context-fundamentals）——高海拔原則式（「保持簡潔」）與低海拔硬規則式（「≤120 字元」）不要交錯擠同段：混層 = conflicting signals，模型會把原則過度執行成硬規則、或把硬規則打折成建議。例外（好模式不算混層）：硬規則緊跟它所量化的原則（原則 → 自己的量化下限）。寫/改 skill 段落時自查一輪；CLAUDE.md / rules 等 config 同判準（見 memory `_index_config_authoring_discipline`）

14. **環境即權威、文件只 cache 查不到的**（2026-08-06 加；源自 mattpocock/skills writing-for-agents v1.2）——package.json scripts / config 檔 / 目錄佈局 / `--help` 輸出本身就是權威來源，文件重述它們 = 一次 lookup 的 cache，只在 lookup 昂貴時才值得寫（且會 stale）。該 cache 的是 agent 用查的查不到的東西：不成文慣例、選擇背後的理由、config 不會招認的 gotcha。限定：「理由」的落點仍照三層分工（always-on 留指令不留原因、path-scoped 克制、完整理由歸 memory）——本條管「要不要寫」，不改變「寫到哪」
三判準跑完（含官方 Step 1-6 的 authoring 本體）→ 依上方「RED → GREEN → REFACTOR：行為驗證」跑完本輪（機械替換改跑同段的三項程式檢查），再接下方「診斷：6 種失敗模式」段逐條自檢一輪 → 摩擦盤點、帳本盤點後收工。Collie 手機面板不用手動同步：fork 的 bridge 直接讀 Claude Code 會載入的 skill 與 command 檔（Collie ADR 9009）。摩擦盤點：本次 authoring 有無預見或撞到的摩擦 → append 被改 skill 的 `friction-log.md`，無主的落 `~/.claude/friction/workflow-general.md`；建新 skill 時順手評估要不要給它配 `friction-log.md`（規則與門檻見 `~/.claude/friction/PROTOCOL.md`）；無摩擦不留紀錄。帳本盤點：本次 authoring 有無引入會被 append、供未來 agent 讀的檔案或目錄 → 登記 registry 或標明純 log；無則不留紀錄。這兩步都是 authoring 動線的最後一段、不是參考資料。Codex 已於 2026-09-20 停用，不補 `~/.codex` 端入口。

### 診斷：skill 寫作 / debug 時對照 6 種失敗模式

authoring 當下自檢 + 事後 debug 都用（源自 mattpocock/skills writing-great-skills，2026-07-09 加）。**先分軸**：

- **紀律違反軸**（agent 明知規則就 skip）→ 用上方 failure-form selector 的 discipline row，補 prohibition / rationalization table / red flags；這邊不重複（Match-the-Form 跨兩軸：discipline 類屬此軸、shape / omission / conditional 屬內容形式軸）
- **內容形式軸**（skill 本身寫壞、跟 agent 紀律無關）→ 對照下面 6 種：

1. **Premature completion**——completion criterion 太模糊、agent「感覺做完」就跳走。修：criterion 寫成 checkable + exhaustive（見上方三判準第 10 條）
2. **Duplication**——同一 meaning 出現多處。修：single source of truth
3. **Sediment**——只加不減的殘留、沒 prune discipline 的預設命運
4. **Sprawl**——太長、每行 live 也可能。修：progressive disclosure 把 reference 推到 external + 按 branch 分岔
5. **No-op**——模型本來就會做的話，逐句掃並刪除。若模糊形容詞藏著真正要求，就改寫成可觀察結果或驗證條件；不要只換成更強的形容詞。
6. **Negation**——`don't think of elephant` 反 anchor elephant。此軸**優先用**上方 failure-form selector（分類更精緻：discipline / shape / omission / conditional），再回到 RED → GREEN → REFACTOR 驗證修法

兩軸互補、不衝突。

### 修改既有 skill 的接線判準（2026-06-12 加；B 線漂移抽查實證 7 個資產同犯）

往既有 skill / command 補步驟時，失效模式是「補了內容、沒補接線」——新段落物理上存在但不在執行動線上，agent 讀過就忘（實證：/pr-review 兩個新步驟 11 次執行 0 次跑過）。四條規則：

1. **補新段必補指針**：同步在前一步末尾加「完成後接 Step X / 段名」。沒有指針指向的段落，執行 agent 預設跳過
2. **副作用動作必是編號步驟**：寫檔 / append / launchctl 等動作不能只出現在散文裡，必須升格為編號步驟或 checklist 項
3. **行動約束放決策點旁**：「不要做 X」「此路退役」「唯一例外 Y」這類影響執行路徑的約束，放在動線上對應的決策點旁，不放說明段 / 注意事項段
4. **自我檢查訊號**：「必須 / 不可跳過 / 記得」出現在非步驟段（散文 / 括號 / ⚠️ 標記）= 該動作位置錯了，需要接線

（先例脈絡：官方 docs 的 Missed connections 觀察項與 superpowers 的 edits-need-testing 是行為驗證路線；本判準是 edit-time 靜態檢查，互補不重複。）
