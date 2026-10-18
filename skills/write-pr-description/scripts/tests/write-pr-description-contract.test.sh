#!/usr/bin/env bash
set -euo pipefail

ROOT="${WRITER_CONTRACT_ROOT:-${HOME}/.claude}"
python3 - "$ROOT" <<'PY'
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
skill = (root / 'skills/write-pr-description/SKILL.md').read_text(encoding='utf-8')
reference = (root / 'skills/write-pr-description/references/drafting-rules.md').read_text(encoding='utf-8')
eval_file = (root / 'skills/write-pr-description/evals/eval.yaml').read_text(encoding='utf-8')
checks = []


def require(label, condition):
  checks.append((label, bool(condition)))


def contains_all(text, values):
  return all(value in text for value in values)


def section(text, start, end):
  return text.split(start, 1)[1].split(end, 1)[0]


require('writer marks contract test', '<!-- 本檔在契約測試底下：bash ~/.claude/skills/write-pr-description/scripts/tests/write-pr-description-contract.test.sh -->' in '\n'.join(skill.splitlines()[:8]))
require('description triggers draft and revise', contains_all(skill, ('title or description needs drafting or revising', 'write the PR description', 'revise the PR body')))
require('description triggers before direct PR create and body edit', contains_all(skill, ('before running `gh pr create`, `gh pr edit --body`', 'Returns prose only; the caller or provider adapter')))
require('description excludes non-description PR actions', 'Do not use for PR comments, reviews, approvals, merges, state changes, or read-only PR queries' in skill and 'Do not use when the requested action is to create' not in skill)
require('direct CLI caller keeps the write', 'return the candidate to the caller, which performs that write under its own confirmation rules' in skill)
require('investigation notes are not body content', 'Treat session investigation notes' in skill and contains_all(reference, ('Session investigation notes | Your understanding of the diff only; not body content', 'State the decision, not its derivation')))
require('core forbids provider APIs and approval artifacts', contains_all(skill, ('Do not call provider APIs', 'create approval artifacts', 'sole writer and approval/read-back owner')))
require('core reads committed evidence', contains_all(skill, ('git log <base>..HEAD', 'git diff --stat <base>...HEAD', 'relevant committed diff')))
require('core separates dirty tree', contains_all(skill, ('git status --short', 'git diff --cached', 'Treat staged and unstaged work as uncommitted', 'Draft basis (not part of PR body)')))
require('template has precedence', contains_all(skill, ('repository template outrank the default shape', 'Do not reorder its top-level headings', 'competing generic skeleton')))
require('validation uses receipts without substitution', contains_all(skill, ('actual validation receipts', 'Missing evidence means “no receipt available,” not “passed.”', 'do not convert unit, build, or typecheck receipts into UI')))
require('paired validation is wired to its rules', 'Pair available before/after receipts' in skill and contains_all(reference, ('same behavior', 'comparable inputs', 'report that receipt alone', 'do not invent a before result or rerun checks')))
require('recovery rules sit beside the risk decision', 'recovery-boundary rules' in section(skill, '3. **Choose the draft shape.', '4. **Draft from facts.') and contains_all(reference, ('## Recovery boundary', 'external effects', 'destructive data changes', 'new persisted format', 'first write', 'already sent', 'unverified', 'Do not add a mandatory Door')))
require('intent cannot become completed result', contains_all(skill, ('issue/spec goals as intent', 'Never turn “should,” “acceptance asks,” or a future rollout goal into a completed result')))
require('small PR stays concise', contains_all(skill, ('Keep a small PR to a few useful bullets', 'small changes have no ceremonial filler')))
require('reviewer guide is conditional and complete', contains_all(skill, ('only when reading order is non-obvious', 'blast radius is wider than the diff size suggests', '`Start` for the first exact file/symbol', '`Then` for the dependent implementation path', '`Validate` for the exact test/evidence path', '`Focus` for the invariant or blast radius')))
require('trust-boundary changes always get a reviewer guide', 'An authorization, permission, data-ownership, or migration change always needs the guide, however few files it touches' in skill and 'This trims narrative only: a reviewer guide that the decision rules below call for stays in' in reference)
require('authz eval names the working directory', 'Read evidence.md in the current working directory' in (root / 'skills/write-pr-description/evals/cases/authz-reading-order.yaml').read_text(encoding='utf-8'))
require('self verify skip is explained', contains_all(skill, ('Self-Verify is intentionally omitted', 'frequent prose task', 'low/medium-frequency gate')))
require('reference distinguishes evidence classes', contains_all(reference, ('Committed diff and commits', 'Staged or unstaged diff', 'Issue or spec', 'Actual command output or captured artifact')))
require('reference covers tiny-wide and foundational density', contains_all(reference, ('Tiny diff with wide blast radius', 'Large foundational change')))
require('reference rejects UI evidence substitution', contains_all(reference, ('screenshot, browser check, rollout, and production observation are different receipts', 'matches the design')))

expected_cases = [
  'small-bugfix.yaml',
  'tiny-wide-permission-change.yaml',
  'ui-evidence-honesty.yaml',
  'authz-reading-order.yaml',
  'dirty-tree.yaml',
  'large-foundational-pr.yaml',
  'investigation-notes-stay-out.yaml',
  'structural-change-outline.yaml',
  'paired-evidence-and-recovery.yaml',
  'after-only-no-recovery.yaml',
]
listed_cases = re.findall(r'^    - evals/cases/([^\n]+)$', eval_file, flags=re.M)
require('eval manifest lists the required cases', listed_cases == expected_cases)
case_texts = {}
for name in expected_cases:
  path = root / 'skills/write-pr-description/evals/cases' / name
  require(f'eval case exists: {name}', path.is_file())
  case_texts[name] = path.read_text(encoding='utf-8') if path.is_file() else ''
require('evals contain no private Warp fixture', all('Warp' not in text for text in case_texts.values()))
require('every eval invokes writer and excludes mutation', all('/write-pr-description' in text and 'do not call provider apis' in text.lower() for text in case_texts.values()))
require('small bugfix eval rejects reviewer guide', 'does not add a reviewer guide' in case_texts['small-bugfix.yaml'])
require('tiny permission eval requires blast radius', contains_all(case_texts['tiny-wide-permission-change.yaml'], ('all-support-agent blast radius', 'production verification were not run')))
require('UI eval requires evidence honesty', contains_all(case_texts['ui-evidence-honesty.yaml'], ('No screenshot was captured', 'does not claim the UI looks correct')))
require('authz eval requires reading order', contains_all(case_texts['authz-reading-order.yaml'], ('post-commit roleVersion update', 'cache-key construction', 'regression test', 'invalidation invariant')))
require('dirty eval excludes uncommitted work', contains_all(case_texts['dirty-tree.yaml'], ('not committed', 'out-of-body draft-basis note')))
require('investigation eval keeps notes out of body', contains_all(case_texts['investigation-notes-stay-out.yaml'], ('gh pr create', 'does not recount the IAM/CloudTrail detour', 'staging import run was not run')))
require('change outline is conditional and replaces narration', contains_all(skill, ('Add a change outline when the diff changes an API or data contract', 'the outline replaces the Summary bullets that would narrate that structure', 'a change with no structural shift gets none')) and contains_all(skill, ('`### Change outline` under Summary', 'call or data flow → call tree', 'use no Mermaid', 'a structural change has its outline')) and '## Change outline' not in reference)
require('reviewer guide slots stay in the guide bullet', 'however few files it touches. When included, use four compact slots' in skill)
require('shape step requires reading the rules', 'Done when drafting-rules.md has been read in this run' in skill)
require('outline eval requires views without narration', contains_all(case_texts['structural-change-outline.yaml'], ('fenced diff or text view', 'does not restate the contract fields', 'no Mermaid block')))
require('outline eval permits lead-ins but still rejects Summary bullet duplication', contains_all(case_texts['structural-change-outline.yaml'], ('Summary bullet prose does not restate', 'not to one short lead-in sentence before each view inside Change outline', 'even when Change outline is nested under Summary')))
writer_step = section(skill, '4. **Draft from facts.', '5. **Return the candidate.')
require('outline facts get one owner before drafting', contains_all(writer_step, ('assign each fact to one place before writing', 'field/type inventories and call order belong to the views', 'use the old body as a fact source', 'Check every Summary bullet against the views', 'Continue to Step 5')))
require('outline deduplication retains behavior and evidence', contains_all(writer_step, ('intent, effects, conditions, and limitations belong to Summary', 'A field name may still appear in a condition or effect', 'Split mixed sentences and retain the behavior', 'Keep the reviewer guide, rollout, recovery boundary, and validation receipts')))
require('small bugfix eval rejects change outline', 'change outline' in case_texts['small-bugfix.yaml'])
require('foundational eval rejects completed migration', contains_all(case_texts['large-foundational-pr.yaml'], ('No application consumer imports', 'does not claim the legacy rules system was replaced')))
require('paired eval checks evidence and recovery boundaries', contains_all(case_texts['paired-evidence-and-recovery.yaml'], ('before/after pair', 'restoring existing recipientId records', 'recalling delivered messages', 'mandatory Door section')))
require('after-only eval rejects fabricated evidence and ceremony', contains_all(case_texts['after-only-no-recovery.yaml'], ('empty Before placeholder', 'rerun checks', 'no additional Risk, Door, recovery', 'Summary then Checks')))

failed = [label for label, passed in checks if not passed]
for label, passed in checks:
  print(f"{'PASS' if passed else 'FAIL'}: {label}")
print(f'PASS={len(checks) - len(failed)} FAIL={len(failed)}')
if failed:
  raise SystemExit(1)
PY
