# Drafting rules

## Evidence boundaries

| Source | What it can support |
| --- | --- |
| Committed diff and commits against the selected base | What is in the PR candidate |
| Staged or unstaged diff | A separate draft-basis note; not a PR result claim |
| Issue or spec | Motivation, constraints, and intended outcomes |
| Actual command output or captured artifact | The exact validation it directly observed |
| Repository PR template | Required body structure and ordering |
| Session investigation notes | Your understanding of the diff only; not body content |

Commit messages summarize intent; confirm material claims in the committed diff. A passing focused test supports only the behavior it exercises. A typecheck, build, unit test, screenshot, browser check, rollout, and production observation are different receipts and cannot substitute for one another.

## Density

- **Small, narrow change:** one to three Summary bullets, exact Validation receipts, and Risk only when the template requires it or a real failure mode exists.
- **Tiny diff with wide blast radius:** stay concise but name the affected population or trust boundary and add a reviewer focus guide.
- **Large foundational change:** summarize new boundaries and contracts, state what is not wired or migrated, and give a reading order. Do not list every file.

State the decision, not its derivation: “Retries the upload twice with a 500 ms backoff” rather than the timing traces, API payloads, measurements, or debugging path that settled those numbers. Reviewers read the body to judge the diff; the investigation belongs in the commit message or repository docs when it is worth keeping. This trims narrative only: a reviewer guide that the decision rules below call for stays in.

## Intent and result phrasing

Use direct result language for committed facts: “Changes the cache key to include `roleVersion`.”

Keep goals visibly conditional when evidence does not prove them: “The issue expects grants to remain unchanged” or “This foundation is intended to support a later migration.”

Avoid outcome language such as “prevents,” “ensures,” “fully migrates,” “matches the design,” or “reduces latency” unless the available diff and validation receipt directly establish that outcome.

## Validation wording

Preserve the observable receipt:

```markdown
- `uv run pytest tests/auth/order-permissions.test.ts -q` — exited 0, `6 passed`.
- Full suite: not run.
- Manual UI/browser check: not run.
```

When no receipt exists, write “No receipt available” rather than assuming a check was not run. Keep screenshots or recordings under the repository template’s evidence section and say “Not captured” when that is the supplied fact.

Pair supplied before/after receipts only when they test the same behavior with comparable inputs. Keep each command and observed result visible. With only after evidence, report that receipt alone; do not invent a before result or rerun checks merely to fill a before/after slot.

## Recovery boundary

For external effects, destructive data changes, or a new persisted format, use the existing Risk or reviewer Focus to state:

- What reverting code or disabling a flag restores, and which persisted state or external effects remain.
- The evidenced point after which reverting code alone is insufficient, such as the first write in a new format or an outbound delivery.
- Whether data recovery or compensation is evidenced; if not, mark it unverified rather than promising a safe rollback.

A code revert does not recall messages already sent or recreate deleted records; a format flag does not rewrite existing rows. Do not add a mandatory Door section or a recovery checklist to unrelated small changes.

## Reviewer guide decision

Add a guide when at least one of these signals is present:

- Review order matters to understand a cross-file invariant.
- Authorization, permission, data ownership, migration, or another trust boundary needs explicit focus.
- A small diff affects a broad user or system population.
- A foundational change introduces contracts that future work will depend on.

Use four compact slots when a guide is warranted:

- `Start`: the first exact file or symbol to read.
- `Then`: the dependent implementation path.
- `Validate`: the exact test or evidence path when one exists.
- `Focus`: the invariant or blast radius to inspect.

Omit the guide when the change is locally obvious and file order adds no value.

## Template precedence

Keep required top-level headings in their original order. Fill the closest existing section instead of appending duplicate `Summary`, `Testing`, or `Risk` sections. If a reviewer guide is warranted but the template has no slot, nest `### Reviewer guide` under `Summary`, `Architecture`, or `Risk`; append a new top-level section only when the template permits extensions.
