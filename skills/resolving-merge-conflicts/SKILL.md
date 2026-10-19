---
name: resolving-merge-conflicts
description: "Use when you need to resolve an in-progress git merge/rebase conflict. Do not use for ordinary code or test failures without unmerged Git paths."
upstream: mattpocock/skills
upstream-path: skills/engineering/resolving-merge-conflicts/SKILL.md
upstream-pinned: 6654f6b
upstream-status: orphaned
---

<!-- 本檔在契約測試底下：bash ~/.claude/skills/resolving-merge-conflicts/scripts/tests/resolving-merge-conflicts-contract.test.sh -->

# Resolving Merge Conflicts

Use this workflow only while Git reports unmerged paths; ordinary code or test failures belong elsewhere.

1. **Start with a compact summary** of the in-progress merge/rebase and every unresolved path.

```bash
python3 ~/.claude/skills/resolving-merge-conflicts/scripts/extract_conflict_context.py --repo .
```

Keep the list of conflicted paths it reports; step 7 reviews each of them after they are resolved. If the list is lost once files are staged, `git merge-tree --write-tree --name-only HEAD MERGE_HEAD` prints it again (or `git merge-tree --write-tree --name-only HEAD^1 HEAD^2` when inspecting an already-committed merge).

2. **Find the primary sources** for each conflict. Understand why each change was made and what the original intent was. Read the commit messages, check the PRs, and check original issues/tickets.

3. **Inspect one conflicted file at a time.**

```bash
python3 ~/.claude/skills/resolving-merge-conflicts/scripts/extract_conflict_context.py --repo . --file <path>
```

Use the compact hunk or index-stage output first. Read the full file only when the compact output is insufficient to preserve the surrounding behavior or intent. For binary, rename, or submodule conflicts, a missing text preview is not sufficient evidence: inspect the relevant index stages, object modes or commits, and history before choosing a resolution.

4. **Resolve that file.** Preserve both intents where possible. Where they are incompatible, choose the result matching the merge's stated goal and note the trade-off. Do not invent new behavior. Always resolve; never `--abort`. Stage that file alone with `git add -- <path>` or `git rm -- <path>`.

5. **Re-check unresolved conflicts after each file.**

```bash
python3 ~/.claude/skills/resolving-merge-conflicts/scripts/extract_conflict_context.py --repo .
git diff --name-only --diff-filter=U
```

Repeat Steps 2–5 until both commands report no unresolved paths.

6. Discover the project's **automated checks** and run them—typically typecheck, tests, then format. Fix anything the merge broke, and verify no conflict markers remain in resolved text files.

7. **Review every conflicted file for a side whose change disappeared.** Green checks do not cover this: a resolution that keeps one side's refactor and drops the other side's addition stays green whenever nothing tested that addition. Build the three-diff bundle (base to ours, base to theirs, and base to the result) and run the mechanical checks with `prepare_merge_review.py`:

```bash
# In-progress merge after staging resolved files (MERGE_HEAD present):
python3 ~/.claude/skills/resolving-merge-conflicts/scripts/prepare_merge_review.py --repo . --staged --out /tmp/merge-review-bundle.txt

# Already-committed merge or delegated worker handoff (computes conflicts from HEAD^1 and HEAD^2):
python3 ~/.claude/skills/resolving-merge-conflicts/scripts/prepare_merge_review.py --repo . --commit HEAD --out /tmp/merge-review-bundle.txt
```

(In a rebase where `REBASE_HEAD` is active instead of a two-parent merge, compute `base=$(git merge-base HEAD REBASE_HEAD)` and produce `git diff "$base" HEAD -- <path>`, `git diff "$base" REBASE_HEAD -- <path>`, and `git diff --cached "$base" -- <path>` for each path from step 1.)

A file whose conflicts were all mechanical (translation dictionaries, lockfiles, a changelog, or a manifest where only `version` changed) is checked by a script, not an agent: every key or entry either side added is present in the result, and a key both sides changed or a manifest that also modified `scripts` or `dependencies` is kept in `REVIEW_FILES_COUNT` rather than exempted by filename. Lockfiles are regenerated from the merged manifests rather than checked entry by entry. When `REVIEW_FILES_COUNT > 0`, give `BUNDLE_PATH` to a fresh reviewer agent with no conversation context, one file per item, asking only which hunk of ours or theirs is missing from the result and whether anything explains its absence. Reading `BUNDLE_PATH` in the resolving session does not substitute for the fresh reviewer even when `REVIEW_FILES_COUNT` is 1 or the bundle is short, because the resolver already expects its resolution to be complete. Whether main resolves the merge directly or receives a commit from a delegated worker that cannot spawn subagents, main must obtain that fresh reviewer's per-file verdicts and fix what the review finds (then re-run step 6) before the merge counts as done. Done when every conflicted path has a script or fresh-reviewer verdict and each missing hunk is restored or has a stated reason. Proceed to step 8.

8. **Finish the merge/rebase.** Commit the completed merge. If rebasing, continue until every commit is rebased, repeating the workflow for each new conflict stop.
