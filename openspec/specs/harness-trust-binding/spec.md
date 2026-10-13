# harness-trust-binding Specification

## Purpose
TBD - created by archiving change hash-free-harness. Update Purpose after archive.

## Requirements

### Requirement: Permits bind by identity, not content digest

A permit issued by any harness command (review-spec Tier 3 dual run, review-spec yagni batch, pr-review C4 dispatch) SHALL be bound to its consumer by identity fields only: session_id, the uuid of the command event that created it, a random permit_id, the lens or batch it authorizes, the absolute path of its subject, the path of a snapshot copy of that subject, and an expiry time. The gate MUST compare every field the calling context carries (session_id, transcript path, permit_id, lens or batch, expiry, consumption state) for equality, MUST deny when any of them differs, when the permit is already consumed, or when it is expired, and MUST NOT compute or compare a cryptographic digest of the subject. Fields the call cannot carry (the command event uuid, the subject path, the snapshot path) are verified against the transcript when the permit is issued or finalized and stay bound through the session-keyed owner-only state file. The pr-review C4 permit binds session_id, permit_id, expiry, consumption and the stored agent text only. The deny reason shown to the caller names the cause (consumed, expired, mismatch), not just the audit log.

#### Scenario: Valid permit consumed once
- **WHEN** a dispatch carries a marker whose permit_id matches an unconsumed, unexpired state file for the same session and lens
- **THEN** the gate allows the call
- **AND** marks that lens of the permit consumed

#### Scenario: Same permit used again
- **WHEN** a second dispatch carries the same permit_id and lens
- **THEN** the gate denies the call with a reason naming the permit as already consumed

#### Scenario: Permit from another session
- **WHEN** a dispatch carries a permit_id whose state file records a different session_id
- **THEN** the gate denies the call

#### Scenario: Expired permit
- **WHEN** the state file's expiry time is in the past
- **THEN** the gate denies the call with a reason naming expiry

### Requirement: Sameness of content is checked by stored text, not hash

Where a gate must confirm that a dispatched call equals what the command prepared (pr-review C4 dispatch, bitbucket-pr-mutation proposal), the command SHALL keep the prepared text in its existing owner-only state file and the gate SHALL compare the dispatched text to it for equality. A gate SHALL NOT re-verify its own owner-only state file by digest (the matt-tdd-gate prefix check is removed, not replaced). Snapshot copies of subjects SHALL remain; immutability MUST rely on copying and file permissions, not on a digest.

#### Scenario: Dispatched packet equals stored packet
- **WHEN** the dispatched prompt's packet section equals the stored text byte for byte
- **THEN** the gate allows the call

#### Scenario: Dispatched packet differs
- **WHEN** any byte differs
- **THEN** the gate denies the call with a reason saying the packet was altered after preparation

### Requirement: Receipts, manifests and envelopes carry no digest fields

Every receipt, manifest or envelope written by harness tooling (archify-safe, plannotator-review, secret-provisioning, skillevaluator-trial, bootstrap-manifest, local-analysis samples, daily-topic writeback, pi-subtask runner, config-sync, memory-ripple, social-info evidence-level receipts, watchdogs freeze manifests) SHALL NOT contain digest, checksum or `*_sha256` fields. Where an existing consumer reads freshness or version today, it SHALL use mtime and size, or path and time, instead; no new required field SHALL be added merely to replace a removed digest. Consumers that previously verified such fields MUST stop verifying them.

#### Scenario: Receipt written after a run
- **WHEN** a tool finishes and writes its receipt
- **THEN** the receipt contains the subject paths and completion time
- **AND** contains no field whose name or value is a cryptographic digest

#### Scenario: Consumer reads a receipt
- **WHEN** a verify step reads a receipt
- **THEN** it accepts the receipt without recomputing any digest

### Requirement: Identity-key hashes are preserved and not extended

Hashes used purely as data keys (dedup item id and title key, session-audit fingerprint and identity, deep-research evidence_id, taskoutput-dedup key, skill-verify-once key, watchdogs catalog change_id, repeat-verify-reminder command key, review set identity per ADR 0001) SHALL remain unchanged.

#### Scenario: Dedup key untouched
- **WHEN** the cleanup touches a file that computes a dedup item id
- **THEN** the item id computation is left as is
- **AND** the ledger records it as identity key, kept

### Requirement: External-contract exceptions are the only verification hashes left

After cleanup, the only verification-use hashes in harness code SHALL be the keychain service name derived from config_dir in cc-quota-fetcher-host, the source and archive checks in build-cc-sticky-fix, and three external formats the harness only reproduces: the Chrome Safe Storage key derivation (PBKDF2-SHA1) in scripts/cookie-extract.py, the Electron safeStorage key derivation (PBKDF2-SHA1) in scripts/cc-statusline/grok-bot-usage.mjs, and the git tree sha1 recomputed by social-info scripts/local-analysis/skill-lock-drift.py to compare against the external skills installer's skillFolderHash. A SHA-256 comparison inside a private release skill (not part of this public copy) is also permitted solely to verify a downloaded app archive against the publisher's checksum from the same release; this exception does not cover other files, receipts, manifests, or permit binding. Adding any other exception MUST require the user's explicit decision. If implementation finds the keychain naming does not match Claude Code's own convention, the ledger note records it and the disposition stays unchanged.

#### Scenario: One-time closing enumeration
- **WHEN** the cleanup closes and `command grep` enumerates hash identifiers over own code in each of the three repos
- **THEN** every hit is in the exception list or the identity-key list
- **AND** the command and its zero count are recorded in the ledger and the closing report
- **AND** no persistent lint test is added by this change

### Requirement: Every removal or retention is recorded in the removal ledger

Each file touched by the cleanup SHALL add one ledger row with: repo, mechanism family, file role, pattern category (one of: permit binding, receipt digest, manifest listing, self-output re-verification, content comparison, identity key kept, external contract kept, regex false positive left as is — a git SHA length table or object format, or a literal mention of a hash word in rubric or fixture text, with no hash computation), a reference to the audit's judged row (session and model) where one exists, disposition, and a note. The ledger MUST live in this change directory and SHALL accompany the change when it is archived.

#### Scenario: A receipt digest is removed
- **WHEN** a worker removes `report_sha256` from a receipt writer
- **THEN** the ledger gains a row with pattern category receipt digest and disposition removed

#### Scenario: Author lookup fails
- **WHEN** the file's hash was added before the audit window
- **THEN** the author column reads outside window

### Requirement: Rule documents describe identity binding only

subagent-routing.md, the review-spec command and the pr-review command SHALL describe permits in terms of identity binding and SHALL NOT describe digest-bound markers, packet hashes or snapshot byte hashes as part of the current mechanism.

#### Scenario: Reader follows the SSOT
- **WHEN** an agent reads the Fable narrow-exception section of subagent-routing.md
- **THEN** the marker format shown contains no `*_sha256` field
