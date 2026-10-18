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

Keep the list of conflicted paths it reports; step 7 reviews each of them after they are resolved. If the list is lost once files are staged, `git merge-tree --write-tree --name-only HEAD MERGE_HEAD` prints it again.

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

7. **Review every conflicted file for a side whose change disappeared.** Green checks do not cover this: a resolution that keeps one side's refactor and drops the other side's addition stays green whenever nothing tested that addition. For each path from step 1, with `base=$(git merge-base HEAD MERGE_HEAD)` (in a rebase, `REBASE_HEAD` in place of `MERGE_HEAD`), produce three diffs, base to ours, base to theirs, and base to the result:

```bash
git diff "$base" HEAD -- <path>
git diff "$base" MERGE_HEAD -- <path>
git diff --cached "$base" -- <path>
```

Give them to a fresh reviewer agent with no conversation context, one file per item, asking only which hunk of ours or theirs is missing from the result and whether anything explains its absence. A file whose conflicts were all mechanical (translation dictionaries, lockfiles, a changelog) is checked by a script, not an agent: every key or entry either side added is present in the result, and a key both sides changed is reviewed by value. A lockfile is regenerated from the merged manifests rather than checked entry by entry, since an upgrade replaces entries by design. Fix what the review finds, then run step 6 again. Done when every conflicted path has a reviewer or script verdict and each missing hunk is restored or has a stated reason.

8. **Finish the merge/rebase.** Commit the completed merge. If rebasing, continue until every commit is rebased, repeating the workflow for each new conflict stop.
