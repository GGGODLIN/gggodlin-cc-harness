---
name: wizard
description: Generate an interactive bash wizard that walks a human through steps only they can perform. Use when provisioning infrastructure, setting up credentials or CI secrets, walking an unfamiliar third-party dashboard, or running a one-off migration or cutover. Don't invoke this for steps the agent can perform itself, nor when the procedure has fewer than 4 human steps and no values to persist — list those steps in chat instead.
upstream: mattpocock/skills
upstream-path: skills/engineering/wizard/SKILL.md
upstream-pinned: 6654f6b
---

# Wizard

A **wizard** is a bash script that walks a human, step by step, through a manual procedure that's tedious to do by hand and tedious to re-explain to an AI every time. It opens each URL, says exactly what to click and copy, captures the values, writes them where they belong (`.env`, GitHub secrets), confirms at every stage, and shows how many stages are left. It might configure third-party services, run a one-off migration, or move the project from one state to another.

The delightful UX is already solved by [template.sh](template.sh) — stage-by-stage progress, confirmation gates, cross-platform URL opening (including WSL), hidden secret entry, idempotent `.env` upserts, `gh secret`/`gh variable` writes, and a closing summary. **Your job is only to scope the procedure and author its stages.** The library above the `STAGES` marker is identical in every wizard; that consistency is the point — never hand-edit it.

A wizard is ephemeral by default — built for one run, saved to a scratch or `scripts/` path, deleted when the job's done. Commit it only when the user wants a repeatable setup path that should live in the repo.

## Process

### 1. Scope the procedure

Work out every manual step the human must take and every value that gets captured along the way. Read the repo first — don't ask cold:

- For setup: `.env`, `.env.example`, `.env.*`, `README`, `docker-compose*`, framework config, and `.github/workflows/*` (every `secrets.*` / `vars.*` reference is a value the wizard must produce).
- For a migration or transition: the current state, the target state, and the irreversible actions between them.

Then show the user the ordered list of stages and the values each produces, and confirm — they may add, drop, or reorder.

**Done when:** every stage is named in order, and for each captured value you know (a) where the human gets it, (b) where it's written (`.env`, a GitHub secret, both, or nowhere — some stages are pure actions), and (c) whether it's secret (hidden entry) or public.

### 2. Map each stage's journey

For each stage, write the precise path a human follows: which URL to open, what to do there, where a value is shown, which variable it fills — e.g. "Dashboard → Developers → API keys → Reveal test key → copy". Where you don't actually know the current UI or the exact command, say so and ask the user or check the docs — never invent steps that may not exist.

**Done when:** every stage traces to concrete instructions a stranger could follow.

### 3. Author the wizard

Copy `template.sh` to the target path. Replace the example stage with one `stage` per step, in dependency order. Use the library helpers — `stage`, `say`/`step`, `open_url`, `ask`/`ask_secret`, `write_env`, `set_secret`/`set_var`, `pause`/`confirm` — and set `TOTAL_STAGES` to the number of stages you wrote.

Hold the bar the template sets: open the URL before asking for its value, use `ask_secret` for anything secret, `write_env` every persisted value, `set_secret` only the values CI actually needs, and `confirm` before any irreversible action. Each `stage` clears the screen so only the current step is visible — keep a stage to one focused task so nothing the human needs scrolls away. Don't touch the library above the marker.

### 4. Verify and hand off

- `bash -n <script>`; run `shellcheck` if available.
- `chmod +x <script>`.
- Don't run it end-to-end yourself — it opens browsers and blocks on human input. Trace it statically instead: every value from step 1 is captured and lands where step 1 said, and every `set_secret` name exactly matches a `secrets.*` reference in CI.
- Tell the user how to run it. If it's a repeatable setup path, commit it and link it from the README so the next person runs the script instead of asking an AI.

## 踩過的坑

- 2026-08-11 graft 上游 `wizard-no-minutes`（移除 `TOTAL_MINUTES`／time-remaining 整套），四塊本地補丁零衝突。**目前 pin 只看 frontmatter `upstream-pinned`，本節不記 hash。**
- 2026-08-06 fork 自 mattpocock/skills v1.2.2（`8b36d4f`）。本地 template.sh 對上游打了四個補丁（B 組實測抓洞、8/8 test pass）：H1 無 TTY 直接 exit 64（防無人輸入時假成功寫空值）；H2 write_env 含空格／#／引號的值加雙引號轉義、拒絕換行、_existing 反解引號保 round-trip；H3 首次寫 `.env` 前驗 gitignore、未忽略要 confirm 否則 exit 65；H4 set_secret／set_var 一律顯式 `--repo`（`WIZARD_GH_REPO` 可覆寫）＋逐筆 confirm 帶 repo 與帳號名（雙帳號環境防推錯）。上游 template.sh 有更新時不可直接覆蓋、要 graft 保這四塊。
- 規模門檻（description 也有）：少於 4 個人工步驟、或沒有值要落地 → 不生成，走 dispatch-and-verify 的文字清單出口。
- 註解界線：`STAGES` 標記線以上是 vendor 函式庫（上游明令 never hand-edit、註解原樣保留＝「不寫註解」規則的 vendor 例外）；線以下由 Claude 生成的 stages 照使用者規則**不寫註解**、不要照抄範例段的註解風格。
- 不加 Self-Verify 段：產出驗證已內建在流程 step 4（bash -n＋靜態追蹤），再疊 subagent 對表是重複。
