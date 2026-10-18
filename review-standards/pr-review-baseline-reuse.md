# pr-review-baseline-reuse

`/pr-review` 的跨面向基準清單之一（Reuse）。這份基準分五組（reuse、quality、efficiency、design-decay、dependency-bumps），由 `/pr-review` 派出時五組一起套；本組帶共通說明。文中的 Step 2.7、Step 2.9 指 `/pr-review` 的步驟：派工 prompt 會帶搜尋工具與 blast radius。

## 適用

由 `/pr-review` 派出時必套：派工 prompt 寫「由 /pr-review 派出」就套用，不論語言與改動內容。其他入口派工沒有這行，不套。

## 共通說明

In addition to language- and domain-specific checks, every CC reviewer dispatched by `/pr-review` must also apply the following cross-cutting baseline. These are common code-health pitfalls that language-specific reviewers can miss because the patterns are orthogonal to the primary axis. Borrowed from Claude Code's built-in `/code-review` three-agent split (Reuse / Quality / Efficiency) plus a Design Decay section (architectural erosion smells; items 7-9 absorbed from mattpocock code-review / codebase-design, 2026-07-09), folded into one overlay so reviewer count doesn't explode.

Reviewer depth is set by each reviewer agent's pinned effort; these groups define the shared review floor, not the effort level.

These patterns overlap with — but do not replace — the search-before-flag discipline (Step 2.7) and the strict-liability list (`~/.claude/review-standards/must-report.md`, pointed to from the Step 3 shared prompt). Treat them as **additional patterns to actively scan for**, not a replacement.

Apply these patterns in addition to your language/domain checks. Search-before-flag discipline (Step 2.7) still applies — attach search-proof when flagging a Reuse 1 / Quality 5 type gap.

## 檢查項（Reuse）

1. Search for existing utilities/helpers that could replace newly written code — common locations: utility directories, shared modules, files adjacent to the changed ones. (Per Step 2.7 search discipline, attach search-proof when flagging a gap.)
2. Flag any new function that duplicates existing functionality. Suggest the existing one.
3. Flag inline logic that could use an existing utility — hand-rolled string manipulation, manual path handling, custom environment checks, ad-hoc type guards.
