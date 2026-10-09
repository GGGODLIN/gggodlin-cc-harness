import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  access,
  chmod,
  mkdir,
  readFile,
  readdir,
  rename,
  stat,
  symlink,
  writeFile
} from "node:fs/promises";
import { constants } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import test from "node:test";
import {
  appendAudit,
  isDisabled,
  markCheckpointInjected,
  readCheckpoint,
  writeCheckpoint
} from "../src/storage.mjs";

const temporaryState = async (name) => {
  const stateDir = join(
    tmpdir(),
    `compact-guard-storage-${name}-${process.pid}-${Date.now()}-${Math.random().toString(16).slice(2)}`
  );
  await mkdir(stateDir, { recursive: true });
  return stateDir;
};

const checkpoint = (overrides = {}) => ({
  schemaVersion: 1,
  vendor: "claude",
  sessionId: "raw/session:value",
  trigger: "manual",
  transcriptPath: "/private/transcripts/session.jsonl",
  transcriptHash: "a".repeat(64),
  recordCount: 10,
  messageCount: 4,
  capturedAt: "2026-07-16T00:00:00.000Z",
  entries: [],
  ...overrides
});

const entry = (overrides = {}) => {
  const text = overrides.text ?? "Decision: preserve the verified result.";
  return {
    id: "entry-1",
    role: "assistant",
    category: "decision",
    timestamp: "2026-07-16T00:00:00.000Z",
    text,
    hash: createHash("sha256").update(text).digest("hex"),
    index: 0,
    ...overrides
  };
};

const storedCheckpointPath = async (stateDir, vendor = "claude") => {
  const directory = join(stateDir, "checkpoints", vendor);
  const [name] = await readdir(directory);
  return join(directory, name);
};

test("checkpoint paths use vendor separation and a session hash", async () => {
  const stateDir = await temporaryState("paths");

  const claude = await writeCheckpoint(checkpoint(), { stateDir });
  const codex = await writeCheckpoint(checkpoint({ vendor: "codex" }), { stateDir });
  const claudeFiles = await readdir(join(stateDir, "checkpoints", "claude"));
  const codexFiles = await readdir(join(stateDir, "checkpoints", "codex"));

  assert.equal(claude.sessionId, "raw/session:value");
  assert.equal(codex.vendor, "codex");
  assert.equal(claudeFiles.length, 1);
  assert.equal(codexFiles.length, 1);
  assert.match(claudeFiles[0], /^[a-f0-9]{64}\.json$/u);
  assert.equal(codexFiles[0], claudeFiles[0]);
  assert.equal(claudeFiles[0].includes("raw"), false);
});

test("checkpoint replacement is atomic and private", async () => {
  const stateDir = await temporaryState("atomic");
  await chmod(stateDir, 0o755);

  await writeCheckpoint(checkpoint({ trigger: "manual" }), { stateDir });
  await writeCheckpoint(checkpoint({ trigger: "auto", recordCount: 12 }), { stateDir });

  const stored = await readCheckpoint(
    { vendor: "claude", sessionId: "raw/session:value" },
    { stateDir }
  );
  const files = await readdir(join(stateDir, "checkpoints", "claude"));
  const stateMode = (await stat(stateDir)).mode & 0o777;
  const fileMode = (await stat(join(stateDir, "checkpoints", "claude", files[0]))).mode & 0o777;

  assert.equal(stored.trigger, "auto");
  assert.equal(stored.recordCount, 12);
  assert.deepEqual(files.filter((name) => name.includes(".tmp-")), []);
  assert.equal(stateMode, 0o700);
  assert.equal(fileMode, 0o600);
});

test("missing checkpoints return null", async () => {
  const stateDir = await temporaryState("missing");

  const stored = await readCheckpoint(
    { vendor: "codex", sessionId: "does-not-exist" },
    { stateDir }
  );

  assert.equal(stored, null);
});

test("checkpoint writes reject invalid schemas with one fixed error code", async () => {
  const invalid = [
    checkpoint({ schemaVersion: 999 }),
    checkpoint({ trigger: "scheduled" }),
    checkpoint({ transcriptPath: "" }),
    checkpoint({ transcriptHash: "not-a-hash" }),
    checkpoint({ recordCount: -1 }),
    checkpoint({ messageCount: 1.5 }),
    checkpoint({ capturedAt: "yesterday" }),
    checkpoint({ entries: "not-an-array" }),
    checkpoint({ entries: [entry({ role: "tool" })] }),
    checkpoint({ entries: [entry({ category: "instruction" })] }),
    checkpoint({ entries: [entry({ timestamp: "not-iso" })] }),
    checkpoint({ entries: [entry({ hash: "0".repeat(64) })] }),
    checkpoint({ entries: [entry({ index: -1 })] })
  ];

  for (const [index, value] of invalid.entries()) {
    const stateDir = await temporaryState(`invalid-write-${index}`);
    await assert.rejects(
      writeCheckpoint(value, { stateDir }),
      (error) => error?.code === "invalid_checkpoint"
    );
  }
});

test("checkpoint writes reject relative transcript paths", async () => {
  const stateDir = await temporaryState("relative-write");

  await assert.rejects(
    writeCheckpoint(checkpoint({ transcriptPath: "relative/session.jsonl" }), { stateDir }),
    (error) => error?.code === "invalid_checkpoint"
  );
});

test("checkpoint reads reject tampered schema, identity, and entry hashes", async () => {
  const cases = [
    ["schema", (stored) => ({ ...stored, schemaVersion: 999 })],
    ["vendor", (stored) => ({ ...stored, vendor: "codex" })],
    ["session", (stored) => ({ ...stored, sessionId: "different-session" })],
    ["entry-hash", (stored) => ({
      ...stored,
      entries: [{ ...stored.entries[0], hash: "0".repeat(64) }]
    })]
  ];

  for (const [name, mutate] of cases) {
    const stateDir = await temporaryState(`tampered-${name}`);
    await writeCheckpoint(checkpoint({ entries: [entry()] }), { stateDir });
    const path = await storedCheckpointPath(stateDir);
    const stored = JSON.parse(await readFile(path, "utf8"));
    await writeFile(path, `${JSON.stringify(mutate(stored))}\n`, { mode: 0o600 });
    await chmod(path, 0o600);

    await assert.rejects(
      readCheckpoint(
        { vendor: "claude", sessionId: "raw/session:value" },
        { stateDir }
      ),
      (error) => error?.code === "invalid_checkpoint"
    );
  }
});

test("checkpoint reads reject relative transcript paths", async () => {
  const stateDir = await temporaryState("relative-read");
  await writeCheckpoint(checkpoint(), { stateDir });
  const path = await storedCheckpointPath(stateDir);
  const stored = JSON.parse(await readFile(path, "utf8"));
  await writeFile(path, `${JSON.stringify({
    ...stored,
    transcriptPath: "relative/session.jsonl"
  })}\n`);
  await chmod(path, 0o600);

  await assert.rejects(
    readCheckpoint(
      { vendor: "claude", sessionId: "raw/session:value" },
      { stateDir }
    ),
    (error) => error?.code === "invalid_checkpoint"
  );
});

test("checkpoint reads reject files with group or other permissions", async () => {
  const stateDir = await temporaryState("unsafe-mode");
  await writeCheckpoint(checkpoint(), { stateDir });
  const path = await storedCheckpointPath(stateDir);
  await chmod(path, 0o644);

  await assert.rejects(
    readCheckpoint(
      { vendor: "claude", sessionId: "raw/session:value" },
      { stateDir }
    ),
    (error) => error?.code === "unsafe_checkpoint_file"
  );
});

test("checkpoint reads reject symbolic links even when the target is valid", async () => {
  const stateDir = await temporaryState("unsafe-symlink");
  await writeCheckpoint(checkpoint(), { stateDir });
  const path = await storedCheckpointPath(stateDir);
  const target = `${path}.target`;
  await rename(path, target);
  await symlink(target, path);

  await assert.rejects(
    readCheckpoint(
      { vendor: "claude", sessionId: "raw/session:value" },
      { stateDir }
    ),
    (error) => error?.code === "unsafe_checkpoint_file"
  );
});

test("audit rows use an allowlist and never retain conversation identifiers or text", async () => {
  const stateDir = await temporaryState("audit");
  const rawSessionId = "session-secret-value";
  const transcriptPath = "/private/transcripts/secret.jsonl";

  await appendAudit({
    schemaVersion: 1,
    event: "checkpoint",
    vendor: "claude",
    surface: "ccp-gpt",
    trigger: "manual",
    status: "ok",
    sessionHash: "b".repeat(64),
    transcriptHash: "c".repeat(64),
    recordCount: 9,
    messageCount: 3,
    entryCount: 2,
    timestamp: "2026-07-16T00:00:00.000Z",
    sessionId: rawSessionId,
    transcriptPath,
    prompt: "Never store me",
    summary: "Never store this summary",
    error: "Never store a free-form exception"
  }, { stateDir });

  const auditPath = join(stateDir, "audit.jsonl");
  const raw = await readFile(auditPath, "utf8");
  const row = JSON.parse(raw.trim());

  assert.deepEqual(row, {
    schemaVersion: 1,
    event: "checkpoint",
    vendor: "claude",
    surface: "ccp-gpt",
    trigger: "manual",
    status: "ok",
    sessionHash: "b".repeat(64),
    transcriptHash: "c".repeat(64),
    recordCount: 9,
    messageCount: 3,
    entryCount: 2,
    timestamp: "2026-07-16T00:00:00.000Z"
  });
  for (const forbidden of [rawSessionId, transcriptPath, "Never store", "exception"]) {
    assert.equal(raw.includes(forbidden), false);
  }
  assert.equal((await stat(auditPath)).mode & 0o777, 0o600);
});

test("parallel audit appends leave one valid JSON object per line", async () => {
  const stateDir = await temporaryState("parallel-audit");

  await Promise.all(Array.from({ length: 40 }, (_, index) => appendAudit({
    schemaVersion: 1,
    event: "checkpoint",
    vendor: index % 2 === 0 ? "claude" : "codex",
    surface: index % 2 === 0 ? "claude-code" : "codex-cli",
    status: "ok",
    sessionHash: index.toString(16).padStart(64, "0"),
    timestamp: "2026-07-16T00:00:00.000Z"
  }, { stateDir })));

  const lines = (await readFile(join(stateDir, "audit.jsonl"), "utf8")).trim().split("\n");
  assert.equal(lines.length, 40);
  assert.equal(lines.every((line) => JSON.parse(line).event === "checkpoint"), true);
});

test("audit string fields accept only fixed enums and strict ISO timestamps", async () => {
  const stateDir = await temporaryState("audit-enums");
  const marker = "sensitive_marker";

  await appendAudit({
    schemaVersion: 1,
    event: marker,
    vendor: marker,
    surface: marker,
    trigger: marker,
    status: marker,
    errorCode: marker,
    timestamp: marker,
    sessionHash: "d".repeat(64),
    transcriptHash: "e".repeat(64)
  }, { stateDir });

  const raw = await readFile(join(stateDir, "audit.jsonl"), "utf8");
  const row = JSON.parse(raw.trim());
  assert.equal(raw.includes(marker), false);
  assert.deepEqual(row, {
    schemaVersion: 1,
    sessionHash: "d".repeat(64),
    transcriptHash: "e".repeat(64)
  });
});

test("disabled sentinel is scoped to the guard state directory", async () => {
  const stateDir = await temporaryState("disabled");

  assert.equal(await isDisabled({ stateDir }), false);
  await writeFile(join(stateDir, "disabled"), "");
  assert.equal(await isDisabled({ stateDir }), true);
  await access(join(stateDir, "disabled"), constants.F_OK);
});

test("markCheckpointInjected stamps injectedAt and readCheckpoint round-trips it", async () => {
  const stateDir = await temporaryState("mark-injected");
  await writeCheckpoint(checkpoint(), { stateDir });

  const marked = await markCheckpointInjected({
    vendor: "claude",
    sessionId: "raw/session:value",
    injectedAt: "2026-07-23T01:02:03.000Z"
  }, { stateDir });
  const stored = await readCheckpoint(
    { vendor: "claude", sessionId: "raw/session:value" },
    { stateDir }
  );

  assert.equal(marked.injectedAt, "2026-07-23T01:02:03.000Z");
  assert.equal(stored.injectedAt, "2026-07-23T01:02:03.000Z");
});

test("markCheckpointInjected returns null when no checkpoint exists", async () => {
  const stateDir = await temporaryState("mark-injected-missing");

  const marked = await markCheckpointInjected({
    vendor: "claude",
    sessionId: "raw/session:value",
    injectedAt: "2026-07-23T01:02:03.000Z"
  }, { stateDir });

  assert.equal(marked, null);
});

test("a fresh writeCheckpoint clears a previous injectedAt stamp", async () => {
  const stateDir = await temporaryState("mark-injected-reset");
  await writeCheckpoint(checkpoint(), { stateDir });
  await markCheckpointInjected({
    vendor: "claude",
    sessionId: "raw/session:value",
    injectedAt: "2026-07-23T01:02:03.000Z"
  }, { stateDir });

  await writeCheckpoint(checkpoint(), { stateDir });
  const stored = await readCheckpoint(
    { vendor: "claude", sessionId: "raw/session:value" },
    { stateDir }
  );

  assert.equal(stored.injectedAt, undefined);
});
