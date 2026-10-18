import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { promisify } from "node:util";
import test from "node:test";
import { handleHook } from "../src/hooks.mjs";
import { appendAudit } from "../src/storage.mjs";
import { summarizeAudit } from "../src/trial-report.mjs";

const execFileAsync = promisify(execFile);
const projectDir = resolve(import.meta.dirname, "..");
const hash = (value) => value.repeat(64);
const timestamp = (minute) => new Date(Date.UTC(2026, 6, 16, 0, minute)).toISOString();
const baseRow = ({ event, status, minute, ...overrides }) => ({
  schemaVersion: 1,
  event,
  status,
  vendor: "claude",
  surface: "claude-code",
  timestamp: timestamp(minute),
  ...overrides
});
const checkpointRow = (minute, overrides = {}) => baseRow({
  event: "checkpoint",
  status: "ok",
  minute,
  trigger: "manual",
  sessionHash: hash("a"),
  transcriptHash: hash("b"),
  recordCount: 8,
  messageCount: 4,
  entryCount: 3,
  ...overrides
});
const injectionRow = (minute, overrides = {}) => baseRow({
  event: "injection",
  status: "ok",
  minute,
  trigger: "manual",
  sessionHash: hash("a"),
  transcriptHash: hash("b"),
  recordCount: 8,
  messageCount: 4,
  entryCount: 3,
  packetCharacters: 2100,
  ...overrides
});
const missingInjectionRow = (minute, overrides = {}) => baseRow({
  event: "injection",
  status: "missing",
  minute,
  trigger: "compact",
  errorCode: "missing_checkpoint",
  sessionHash: hash("a"),
  ...overrides
});
const postCompactRow = (minute, overrides = {}) => baseRow({
  event: "postcompact",
  status: "ok",
  minute,
  trigger: "auto",
  summaryAvailable: false,
  ...overrides
});
const disabledRow = (minute, overrides = {}) => baseRow({
  event: "disabled",
  status: "disabled",
  minute,
  ...overrides
});

test("summarizeAudit counts audit dimensions and pairs repeated checkpoint injections", () => {
  const shared = {
    vendor: "claude",
    surface: "claude-code",
    sessionHash: hash("a"),
    transcriptHash: hash("b")
  };
  const other = {
    vendor: "codex",
    surface: "codex-cli",
    sessionHash: hash("c"),
    transcriptHash: hash("d")
  };
  const rows = [
    checkpointRow(0, shared),
    checkpointRow(1, shared),
    injectionRow(2, { ...shared, packetCharacters: 2100 }),
    injectionRow(3, { ...shared, packetCharacters: 7300 }),
    injectionRow(4, { ...shared, packetCharacters: 1200 }),
    checkpointRow(5, { ...other, trigger: "auto" }),
    baseRow({
      event: "blocked",
      status: "error",
      minute: 6,
      trigger: "auto",
      errorCode: "checkpoint_failed",
      sessionHash: other.sessionHash,
      vendor: other.vendor,
      surface: other.surface
    }),
    disabledRow(7, {
      vendor: other.vendor,
      surface: other.surface,
      trigger: "manual",
      sessionHash: other.sessionHash
    }),
    postCompactRow(8, other)
  ];

  assert.deepEqual(summarizeAudit(rows), {
    schemaVersion: 1,
    totalRows: 9,
    validRows: 9,
    invalidRows: 0,
    eventCounts: {
      blocked: 1,
      checkpoint: 3,
      disabled: 1,
      injection: 3,
      postcompact: 1
    },
    statusCounts: { disabled: 1, error: 1, ok: 7 },
    vendorCounts: { claude: 5, codex: 4 },
    surfaceCounts: { "claude-code": 5, "codex-cli": 4 },
    triggerCounts: { auto: 3, manual: 6 },
    error: 1,
    blocked: 1,
    disabled: 1,
    matchedCheckpointInjections: 2,
    unmatchedCheckpoints: 1,
    unmatchedInjections: 1,
    supersededInjections: 0,
    matchRate: 2 / 3,
    checkpointOutcomes: {
      injected: 1,
      completedNoInjection: 1,
      noCompletion: 1
    },
    maxPacketCharacters: 7300
  });
});

test("summarizeAudit treats incomplete pair keys and malformed rows as unmatched or invalid", () => {
  const rows = [
    null,
    [],
    {},
    { event: 4 },
    { event: "postcompact", packetCharacters: -1 },
    { event: "checkpoint", status: "ok", vendor: "claude", surface: "ccp-gpt" },
    {
      event: "injection",
      status: "missing",
      vendor: "claude",
      surface: "ccp-gpt"
    }
  ];
  const summary = summarizeAudit(rows);

  assert.equal(summary.totalRows, 7);
  assert.equal(summary.validRows, 0);
  assert.equal(summary.invalidRows, 7);
  assert.equal(summary.unmatchedCheckpoints, 0);
  assert.equal(summary.unmatchedInjections, 0);
  assert.equal(summary.matchedCheckpointInjections, 0);
  assert.equal(summary.matchRate, 0);
  assert.equal(summary.maxPacketCharacters, null);
});

test("summarizeAudit takes packet maximum only from successful injections", () => {
  const identity = {
    vendor: "codex",
    surface: "codex-cli",
    sessionHash: hash("e"),
    transcriptHash: hash("f")
  };
  const summary = summarizeAudit([
    injectionRow(0, { ...identity, packetCharacters: 7000 }),
    missingInjectionRow(1, {
      vendor: identity.vendor,
      surface: identity.surface,
      sessionHash: identity.sessionHash
    }),
    postCompactRow(2, identity)
  ]);

  assert.equal(summary.maxPacketCharacters, 7000);
});

test("summarizeAudit rejects successful injections without measured packet size", () => {
  const row = injectionRow(0);
  delete row.packetCharacters;

  const summary = summarizeAudit([row]);

  assert.equal(summary.validRows, 0);
  assert.equal(summary.invalidRows, 1);
  assert.equal(summary.maxPacketCharacters, null);
});

test("summarizeAudit pairs only prior checkpoints in FIFO order with causal timestamps", () => {
  const first = { sessionHash: hash("a"), transcriptHash: hash("b") };
  const second = { sessionHash: hash("c"), transcriptHash: hash("d") };
  const third = { sessionHash: hash("e"), transcriptHash: hash("f") };
  const summary = summarizeAudit([
    injectionRow(0, first),
    checkpointRow(1, first),
    checkpointRow(4, second),
    injectionRow(3, second),
    checkpointRow(5, third),
    checkpointRow(6, third),
    injectionRow(7, third),
    injectionRow(8, third)
  ]);

  assert.equal(summary.matchedCheckpointInjections, 2);
  assert.equal(summary.unmatchedCheckpoints, 2);
  assert.equal(summary.unmatchedInjections, 2);
  assert.equal(summary.matchRate, 0.5);
});

test("summarizeAudit enforces event and status specific required fields", () => {
  const incompleteCheckpoint = checkpointRow(0);
  delete incompleteCheckpoint.recordCount;
  const invalidStatus = checkpointRow(1, { status: "error" });
  const wrongSurface = checkpointRow(2, { vendor: "codex", surface: "claude-code" });
  const invalidMissing = missingInjectionRow(3, { errorCode: "invalid_session" });
  const pollutedPostCompact = postCompactRow(4, { packetCharacters: 8400 });
  const invalidDisabled = disabledRow(5, { status: "ok" });

  const summary = summarizeAudit([
    incompleteCheckpoint,
    invalidStatus,
    wrongSurface,
    invalidMissing,
    pollutedPostCompact,
    invalidDisabled
  ]);

  assert.equal(summary.validRows, 0);
  assert.equal(summary.invalidRows, 6);
  assert.equal(summary.maxPacketCharacters, null);
});

test("summarizeAudit returns null packet maximum without a successful injection", () => {
  const summary = summarizeAudit([
    missingInjectionRow(0),
    postCompactRow(1),
    disabledRow(2)
  ]);

  assert.equal(summary.validRows, 3);
  assert.equal(summary.maxPacketCharacters, null);
});

test("summarizeAudit accepts semantic failure and Claude summary variants", () => {
  const summary = summarizeAudit([
    baseRow({
      event: "injection",
      status: "error",
      minute: 0,
      trigger: "compact",
      errorCode: "invalid_session"
    }),
    baseRow({
      event: "injection",
      status: "error",
      minute: 1,
      trigger: "compact",
      errorCode: "checkpoint_read_failed",
      sessionHash: hash("a")
    }),
    baseRow({
      event: "postcompact",
      status: "ok",
      minute: 2,
      trigger: "auto",
      sessionHash: hash("a"),
      transcriptHash: hash("b"),
      summaryAvailable: true,
      summaryCharacters: 120,
      summaryBytes: 140,
      checkpointTermCount: 20,
      summaryTermCount: 18,
      matchedTermCount: 12,
      lexicalCoverage: 0.6
    }),
    baseRow({
      event: "postcompact",
      status: "error",
      minute: 3,
      trigger: "auto",
      errorCode: "postcompact_failed",
      summaryAvailable: false,
      sessionHash: hash("a")
    }),
    baseRow({
      event: "blocked",
      status: "error",
      minute: 4,
      trigger: "manual",
      errorCode: "checkpoint_failed",
      sessionHash: hash("a")
    }),
    disabledRow(5, { trigger: "manual", sessionHash: hash("a") })
  ]);

  assert.equal(summary.validRows, 6);
  assert.equal(summary.invalidRows, 0);
  assert.equal(summary.error, 4);
  assert.equal(summary.blocked, 1);
  assert.equal(summary.disabled, 1);
  assert.equal(summary.unmatchedInjections, 2);
  assert.equal(summary.maxPacketCharacters, null);
});

test("summarizeAudit accepts causal audit rows emitted by real hook handlers", async () => {
  const root = await mkdtemp(join(tmpdir(), "compact-guard-report-hook-"));
  const stateDir = join(root, "state");
  const transcriptPath = join(root, "claude.jsonl");
  await writeFile(transcriptPath, `${JSON.stringify({
    type: "user",
    uuid: "report-user",
    timestamp: timestamp(0),
    message: { role: "user", content: "Decision: preserve the verified result." }
  })}\n`);

  await handleHook({
    vendor: "claude",
    input: {
      hook_event_name: "PreCompact",
      session_id: "report-session",
      transcript_path: transcriptPath,
      trigger: "manual"
    },
    env: {}
  }, { stateDir, now: new Date(timestamp(1)) });
  await handleHook({
    vendor: "claude",
    input: {
      hook_event_name: "SessionStart",
      source: "compact",
      session_id: "report-session",
      transcript_path: transcriptPath
    },
    env: {}
  }, { stateDir, now: new Date(timestamp(2)) });

  const rows = (await readFile(join(stateDir, "audit.jsonl"), "utf8"))
    .trim()
    .split("\n")
    .map((line) => JSON.parse(line));
  const summary = summarizeAudit(rows);

  assert.equal(summary.totalRows, 2);
  assert.equal(summary.validRows, 2);
  assert.equal(summary.invalidRows, 0);
  assert.equal(summary.matchedCheckpointInjections, 1);
  assert.equal(summary.unmatchedCheckpoints, 0);
  assert.equal(summary.unmatchedInjections, 0);
  assert.ok(summary.maxPacketCharacters > 0);
});

test("trial report CLI returns zero-value JSON when the audit file does not exist", async () => {
  const stateDir = await mkdtemp(join(tmpdir(), "compact-guard-report-missing-"));
  const { stdout, stderr } = await execFileAsync(
    process.execPath,
    [join(projectDir, "bin", "trial-report.mjs")],
    { env: { ...process.env, COMPACT_GUARD_HOME: join(stateDir, "absent") } }
  );
  const summary = JSON.parse(stdout);

  assert.equal(stderr, "");
  assert.equal(summary.totalRows, 0);
  assert.equal(summary.invalidRows, 0);
  assert.equal(summary.matchRate, 0);
  assert.equal(summary.maxPacketCharacters, null);
  assert.deepEqual(summary.eventCounts, {});
});

test("trial report CLI treats an empty state override as unset", async () => {
  const homeDir = await mkdtemp(join(tmpdir(), "compact-guard-report-home-"));
  const stateDir = join(homeDir, ".compact-guard");
  await mkdir(stateDir);
  await writeFile(
    join(stateDir, "audit.jsonl"),
    `${JSON.stringify(disabledRow(0))}\n`,
    { mode: 0o600 }
  );
  const { stdout } = await execFileAsync(
    process.execPath,
    [join(projectDir, "bin", "trial-report.mjs")],
    { env: { ...process.env, HOME: homeDir, COMPACT_GUARD_HOME: "" } }
  );

  assert.equal(JSON.parse(stdout).disabled, 1);
});

test("trial report CLI counts malformed complete lines without exposing their contents", async () => {
  const stateDir = await mkdtemp(join(tmpdir(), "compact-guard-report-lines-"));
  const auditPath = join(stateDir, "audit.jsonl");
  await writeFile(auditPath, [
    JSON.stringify(disabledRow(0, { vendor: "codex", surface: "codex-desktop" })),
    "not-json-secret-content",
    ""
  ].join("\n"), { mode: 0o600 });
  const { stdout } = await execFileAsync(
    process.execPath,
    [join(projectDir, "bin", "trial-report.mjs"), "--audit", auditPath]
  );
  const summary = JSON.parse(stdout);

  assert.equal(summary.totalRows, 2);
  assert.equal(summary.validRows, 1);
  assert.equal(summary.invalidRows, 1);
  assert.equal(summary.disabled, 1);
  assert.equal(stdout.includes("secret-content"), false);
});

test("trial report CLI rejects tampered audit dimensions without reflecting their values", async () => {
  const stateDir = await mkdtemp(join(tmpdir(), "compact-guard-report-enums-"));
  const auditPath = join(stateDir, "audit.jsonl");
  const marker = "sensitive_dimension_marker";
  const base = checkpointRow(0);
  const rows = [
    { ...base, event: marker },
    { ...base, status: marker },
    { ...base, vendor: marker },
    { ...base, surface: marker },
    { ...base, trigger: marker },
    { ...base, errorCode: marker },
    { ...base, timestamp: marker }
  ];
  await writeFile(
    auditPath,
    `${rows.map((row) => JSON.stringify(row)).join("\n")}\n`,
    { mode: 0o600 }
  );
  const { stdout } = await execFileAsync(
    process.execPath,
    [join(projectDir, "bin", "trial-report.mjs"), "--audit", auditPath]
  );
  const summary = JSON.parse(stdout);

  assert.equal(summary.totalRows, 7);
  assert.equal(summary.validRows, 0);
  assert.equal(summary.invalidRows, 7);
  assert.deepEqual(summary.eventCounts, {});
  assert.equal(stdout.includes(marker), false);
});

test("summarizeAudit counts superseded injections and classifies checkpoint outcomes", () => {
  const shared = {
    vendor: "claude",
    surface: "claude-code",
    sessionHash: hash("a"),
    transcriptHash: hash("b")
  };
  const supersededRow = (minute) => baseRow({
    event: "injection",
    status: "superseded",
    minute,
    trigger: "auto",
    sessionHash: shared.sessionHash
  });
  const summary = summarizeAudit([
    checkpointRow(0, shared),
    injectionRow(1, shared),
    supersededRow(2),
    checkpointRow(3, shared),
    postCompactRow(4, { sessionHash: shared.sessionHash }),
    checkpointRow(5, {
      vendor: "codex",
      surface: "codex-desktop",
      sessionHash: hash("c"),
      transcriptHash: hash("d"),
      trigger: "auto"
    })
  ]);

  assert.equal(summary.invalidRows, 0);
  assert.equal(summary.supersededInjections, 1);
  assert.equal(summary.unmatchedInjections, 0);
  assert.deepEqual(summary.checkpointOutcomes, {
    injected: 1,
    completedNoInjection: 1,
    noCompletion: 1
  });
});

test("injection rows carrying anchor fields stay valid and still match their checkpoint", () => {
  const rows = [
    checkpointRow(0),
    injectionRow(1, { anchor: "pinned", anchorCharacters: 120 }),
    checkpointRow(2),
    injectionRow(3, { anchor: "nudge", anchorCharacters: 0 })
  ];
  const summary = summarizeAudit(rows);
  assert.equal(summary.invalidRows, 0);
  assert.equal(summary.matchedCheckpointInjections, 2);
});

test("audit writes drop anchor values outside the enum", async () => {
  const stateDir = await mkdtemp(join(tmpdir(), "compact-guard-anchor-audit-"));
  await appendAudit(injectionRow(1, { anchor: "/Users/someone/rubric.md", anchorCharacters: -5 }), { stateDir });
  await appendAudit(injectionRow(2, { anchor: "pinned", anchorCharacters: 40 }), { stateDir });
  const [bad, good] = (await readFile(join(stateDir, "audit.jsonl"), "utf8")).trim().split("\n").map((line) => JSON.parse(line));
  assert.equal("anchor" in bad, false);
  assert.equal("anchorCharacters" in bad, false);
  assert.equal(good.anchor, "pinned");
  assert.equal(good.anchorCharacters, 40);
});
