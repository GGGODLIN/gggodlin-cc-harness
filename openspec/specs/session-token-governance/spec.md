# session-token-governance Specification

## Purpose
Define how session-level automation may interrupt Claude Code work or add reviewer cost while preserving explicit user controls, reversible suspension, offline evaluation, and bounded observation.

## Requirements

### Requirement: Reversible answer-judge suspension

The session token governance change MUST disable the C068 answer judge through its existing human-controlled recovery surface and MUST preserve its implementation, audit history, tests, and reversible restore path.

#### Scenario: Eligible Fable turn occurs while C068 is disabled
- **WHEN** a main-session Fable turn otherwise satisfies the C068 user-length and tool-use filters
- **THEN** no background answer verdict is created
- **AND** no later user prompt receives C068 additional context

### Requirement: No turn-count checkpoint interruption

The checkpoint hook MUST NOT block a Stop event solely because the session reached a turn-count or refresh-window threshold. Existing user-explicit closeout triggers MUST retain their current behavior until a separately approved semantic classifier is connected.

#### Scenario: Long session without explicit closeout request
- **WHEN** a session reaches or exceeds the former checkpoint turn threshold
- **AND** the latest user message does not match an existing explicit closeout trigger
- **THEN** the hook emits no checkpoint block
- **AND** it records no `inject_short` or `inject_long` action

#### Scenario: Existing explicit closeout request
- **WHEN** the latest user message matches an existing explicit closeout trigger
- **THEN** the current `trigger_short` or `trigger_long` path still runs
- **AND** its memory and Git closeout behavior remains unchanged

### Requirement: Offline-only Groq checkpoint-intent replay

The Groq checkpoint-intent experiment MUST evaluate historical human messages without mutating the production checkpoint hook. Its positive class MUST mean an explicit request to perform closeout, memory capture, archival, or save-session now; discussion of those mechanisms MUST remain negative. The corpus MUST exclude meta, tool-result, hook-injected, and subagent messages and MUST preserve a source pointer for every labeled case.

#### Scenario: Historical candidate is replayed
- **WHEN** a human-authored historical message contains a current closeout trigger term
- **THEN** the frozen corpus records whether it is an explicit checkpoint action request or a discussion of checkpoint／closeout／memory behavior
- **AND** the Groq result is recorded separately from the human label

#### Scenario: Replay report is completed
- **WHEN** all selected cases have been evaluated or marked unavailable
- **THEN** the report includes the historical-human, trigger-candidate, and frozen-label denominators; confusion matrix; false positives; false negatives; unavailable reasons; and observed latency
- **AND** candidate-set results are not represented as recall over all checkpoint intent
- **AND** no production hook or settings entry is changed automatically

### Requirement: Conditional reviewer routing

Reviewer agent descriptions MUST route local single-language diffs to the corresponding language reviewer as primary reviewer. Generic review MUST remain available for cross-repository, cross-language, cross-module, public-contract, integration-wiring, or otherwise unsupported diffs. Security review and task verification MUST remain independently conditional on their existing responsibilities.

#### Scenario: Local Python or TypeScript diff
- **WHEN** a code change is confined to one supported language and does not cross a public or integration boundary
- **THEN** the corresponding language reviewer is the primary code reviewer
- **AND** the generic reviewer is not required merely because code changed

#### Scenario: Cross-boundary diff
- **WHEN** a change crosses repositories, languages, module responsibilities, public contracts, or integration wiring
- **THEN** the generic reviewer remains eligible alongside the relevant language reviewer
- **AND** the routing description explains why both perspectives may be used

### Requirement: Reviewer routing observation period

The description-only reviewer routing change MUST enter a seven-day trial whose review date is seven days after production activation; activation on 2026-09-22 yields a 2026-09-29 review. The trial MUST distinguish local single-language changes from cross-boundary changes, MUST enumerate review opportunities with the same inclusion rule across baseline and observation windows, and MUST NOT treat total Agent-count reduction alone as proof of success. Insufficient samples at review time MUST be reported as such and may extend the observation window without escalating the mechanism.

#### Scenario: Trial reaches review date
- **WHEN** the reviewer routing trial is reviewed
- **THEN** the evidence reports local-diff dual-review frequency, preserved cross-boundary dual-review examples, and routing corrections
- **AND** ineffective description routing may be proposed for a closer trigger or always-on surface only through a new user decision

### Requirement: Existing trial isolation

This change MUST NOT modify the wiring, thresholds, or review dates of existing active trials, and it MUST NOT implement the deferred advisor reminder mod route.

#### Scenario: Change is applied during active trials
- **WHEN** session-token governance files are modified
- **THEN** dispatch-obligation, advisor-human-reminder, ticket-yagni, and other existing trial connections remain unchanged
- **AND** advisor `$.ui.log()` work remains outside this change
