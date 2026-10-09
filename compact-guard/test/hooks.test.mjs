import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
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
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { handleHook } from "../src/hooks.mjs";
import { readCheckpoint, writeCheckpoint } from "../src/storage.mjs";

const compactGuardBin = fileURLToPath(new URL("../bin/compact-guard.mjs", import.meta.url));
const fixedNow = () => new Date("2026-07-16T06:00:00.000Z");

const subagentTranscriptPath = (vendor) => fileURLToPath(
  new URL(`./fixtures/${vendor}-subagent.jsonl`, import.meta.url)
);

const temporaryDirectory = async (name) => {
  const path = join(
    tmpdir(),
    `compact-guard-hooks-${name}-${process.pid}-${Date.now()}-${Math.random().toString(16).slice(2)}`
  );
  await mkdir(path, { recursive: true });
  return path;
};

const writeClaudeTranscript = async (directory, name = "claude") => {
  const path = join(directory, `${name}.jsonl`);
  const records = [
    {
      type: "user",
      uuid: `${name}-user`,
      timestamp: "2026-07-16T05:00:00.000Z",
      message: { role: "user", content: "Constraint: keep this local only." }
    },
    {
      type: "assistant",
      uuid: `${name}-assistant-record`,
      timestamp: "2026-07-16T05:01:00.000Z",
      message: {
        id: `${name}-assistant`,
        role: "assistant",
        content: [{ type: "text", text: "Decision: use the verified checkpoint." }]
      }
    }
  ];
  await writeFile(path, `${records.map((record) => JSON.stringify(record)).join("\n")}\n`);
  return path;
};

const writeCodexTranscript = async (directory, originator, name = "codex") => {
  const path = join(directory, `${name}.jsonl`);
  const records = [
    {
      timestamp: "2026-07-16T05:00:00.000Z",
      type: "session_meta",
      payload: { id: `${name}-session-meta`, originator }
    },
    {
      timestamp: "2026-07-16T05:00:30.000Z",
      type: "response_item",
      payload: {
        id: `${name}-internal-user`,
        type: "message",
        role: "user",
        content: [
          { type: "input_text", text: "<recommended_plugins>internal</recommended_plugins>" },
          { type: "input_text", text: "# AGENTS.md instructions\nInternal rules" },
          { type: "input_text", text: "<environment_context>internal</environment_context>" }
        ]
      }
    },
    {
      timestamp: "2026-07-16T05:01:00.000Z",
      type: "event_msg",
      payload: {
        type: "user_message",
        message: "Constraint: keep this local only."
      }
    },
    {
      timestamp: "2026-07-16T05:02:00.000Z",
      type: "response_item",
      payload: {
        id: `${name}-assistant`,
        type: "message",
        role: "assistant",
        content: [{ type: "output_text", text: "Decision: use the verified checkpoint." }]
      }
    }
  ];
  await writeFile(path, `${records.map((record) => JSON.stringify(record)).join("\n")}\n`);
  return path;
};

const auditRows = async (stateDir) => {
  const raw = await readFile(join(stateDir, "audit.jsonl"), "utf8");
  return raw.trim().split("\n").map((line) => JSON.parse(line));
};

const pathExists = async (path) => {
  try {
    await access(path);
    return true;
  } catch (error) {
    if (error?.code === "ENOENT") {
      return false;
    }
    throw error;
  }
};

const hookOptions = (stateDir) => ({ stateDir, now: fixedNow });

const checkpointEntry = (overrides = {}) => {
  const text = overrides.text ?? "Decision: preserve this verified conclusion.";
  return {
    id: "decision",
    role: "assistant",
    category: "decision",
    timestamp: "2026-07-16T05:58:00.000Z",
    text,
    hash: createHash("sha256").update(text).digest("hex"),
    index: 1,
    ...overrides
  };
};

const validCheckpoint = (sessionId, overrides = {}) => ({
  schemaVersion: 1,
  vendor: "claude",
  sessionId,
  trigger: "manual",
  transcriptPath: "/private/session.jsonl",
  transcriptHash: "a".repeat(64),
  recordCount: 5,
  messageCount: 2,
  capturedAt: "2026-07-16T05:59:00.000Z",
  entries: [checkpointEntry()],
  ...overrides
});

const storedCheckpointPath = async (stateDir, vendor = "claude") => {
  const directory = join(stateDir, "checkpoints", vendor);
  const [name] = await readdir(directory);
  return join(directory, name);
};

test("Claude and Codex PreCompact write the same private checkpoint schema", async () => {
  for (const vendor of ["claude", "codex"]) {
    const root = await temporaryDirectory(`precompact-${vendor}`);
    const stateDir = join(root, "state");
    const transcriptPath = vendor === "claude"
      ? await writeClaudeTranscript(root)
      : await writeCodexTranscript(root, "codex-tui");
    const input = {
      hook_event_name: "PreCompact",
      session_id: `${vendor}-session`,
      transcript_path: transcriptPath,
      trigger: "manual"
    };

    const result = await handleHook({ vendor, input, env: {} }, hookOptions(stateDir));
    const stored = await readCheckpoint(
      { vendor, sessionId: `${vendor}-session` },
      { stateDir }
    );

    assert.deepEqual(result, { stdout: "", stderr: "", exitCode: 0 });
    assert.deepEqual(Object.keys(stored), [
      "schemaVersion",
      "vendor",
      "sessionId",
      "trigger",
      "transcriptPath",
      "transcriptHash",
      "recordCount",
      "messageCount",
      "capturedAt",
      "entries"
    ]);
    assert.equal(stored.schemaVersion, 1);
    assert.equal(stored.vendor, vendor);
    assert.equal(stored.sessionId, `${vendor}-session`);
    assert.equal(stored.trigger, "manual");
    assert.equal(stored.messageCount, 2);
    assert.ok(stored.entries.length >= 1);
    if (vendor === "codex") {
      const text = stored.entries.map((entry) => entry.text).join("\n");
      assert.match(text, /keep this local only/u);
      assert.match(text, /use the verified checkpoint/u);
      assert.doesNotMatch(text, /<recommended_plugins>/u);
      assert.doesNotMatch(text, /# AGENTS\.md instructions/u);
      assert.doesNotMatch(text, /<environment_context>/u);
    }
    assert.equal((await stat(join(stateDir, "audit.jsonl"))).mode & 0o777, 0o600);
  }
});

test("PreCompact fails closed with vendor-specific fixed output", async () => {
  const stateDir = await temporaryDirectory("precompact-failure");
  const input = {
    hook_event_name: "PreCompact",
    session_id: "failed-session",
    transcript_path: join(stateDir, "missing.jsonl"),
    trigger: "auto"
  };

  const claude = await handleHook({ vendor: "claude", input, env: {} }, hookOptions(stateDir));
  const codex = await handleHook({ vendor: "codex", input, env: {} }, hookOptions(stateDir));

  assert.deepEqual(JSON.parse(claude.stdout), {
    decision: "block",
    reason: "Compact Guard could not create a pre-compact checkpoint."
  });
  assert.deepEqual(JSON.parse(codex.stdout), {
    continue: false,
    stopReason: "Compact Guard could not create a pre-compact checkpoint.",
    systemMessage: "Compact Guard could not create a pre-compact checkpoint."
  });
  assert.equal(claude.stderr, "");
  assert.equal(codex.stderr, "");
  assert.equal(claude.exitCode, 0);
  assert.equal(codex.exitCode, 0);
  const rawAudit = await readFile(join(stateDir, "audit.jsonl"), "utf8");
  assert.equal(rawAudit.includes("missing.jsonl"), false);
  assert.equal(rawAudit.includes("ENOENT"), false);
  assert.equal(rawAudit.trim().split("\n").every((line) => JSON.parse(line).errorCode === "checkpoint_failed"), true);
});

test("PreCompact still fails closed when guard state cannot be inspected", async () => {
  const root = await temporaryDirectory("state-inspection-failure");
  const stateDir = join(root, "state-file");
  await writeFile(stateDir, "not a directory");

  const result = await handleHook({
    vendor: "claude",
    input: {
      hook_event_name: "PreCompact",
      session_id: "state-failure-session",
      transcript_path: join(root, "unused.jsonl"),
      trigger: "manual"
    },
    env: {}
  }, hookOptions(stateDir));

  assert.deepEqual(JSON.parse(result.stdout), {
    decision: "block",
    reason: "Compact Guard could not create a pre-compact checkpoint."
  });
  assert.equal(result.exitCode, 0);
});

test("Claude and Codex subagent compact lifecycle events are nonblocking no-ops", async () => {
  const events = [
    {
      hook_event_name: "PreCompact",
      trigger: "auto"
    },
    {
      hook_event_name: "SessionStart",
      source: "compact"
    },
    {
      hook_event_name: "PostCompact",
      trigger: "auto"
    }
  ];

  for (const vendor of ["claude", "codex"]) {
    for (const event of events) {
      const root = await temporaryDirectory(`subagent-${vendor}-${event.hook_event_name}`);
      const stateDir = join(root, "state");
      const result = await handleHook({
        vendor,
        input: {
          ...event,
          session_id: `${vendor}-parent-session`,
          transcript_path: subagentTranscriptPath(vendor)
        },
        env: {}
      }, hookOptions(stateDir));

      assert.deepEqual(result, { stdout: "", stderr: "", exitCode: 0 });
      assert.equal(await pathExists(join(stateDir, "audit.jsonl")), false);
      assert.equal(await pathExists(join(stateDir, "checkpoints")), false);
    }
  }
});

test("agent_id makes compact lifecycle events no-ops even with a readable main transcript", async () => {
  for (const vendor of ["claude", "codex"]) {
    const root = await temporaryDirectory(`agent-id-${vendor}`);
    const stateDir = join(root, "state");
    const transcriptPath = vendor === "claude"
      ? await writeClaudeTranscript(root, "agent-id")
      : await writeCodexTranscript(root, "codex-tui", "agent-id");
    const sessionId = `${vendor}-parent-session`;
    await writeCheckpoint(validCheckpoint(sessionId, {
      vendor,
      transcriptPath
    }), { stateDir });

    const results = [];
    for (const event of [
      { hook_event_name: "PreCompact", trigger: "auto" },
      { hook_event_name: "SessionStart", source: "compact" },
      { hook_event_name: "PostCompact", trigger: "auto" }
    ]) {
      results.push(await handleHook({
        vendor,
        input: {
          ...event,
          agent_id: `${vendor}-child-agent`,
          session_id: sessionId,
          transcript_path: transcriptPath
        },
        env: {}
      }, hookOptions(stateDir)));
    }

    assert.equal(results.every((result) => (
      result.stdout === "" && result.stderr === "" && result.exitCode === 0
    )), true);
    assert.equal(await pathExists(join(stateDir, "audit.jsonl")), false);
  }
});

test("unproven Claude continuations and Codex PostCompact cannot use a parent checkpoint", async () => {
  const cases = [
    ["claude", { hook_event_name: "SessionStart", source: "compact" }],
    ["claude", { hook_event_name: "PostCompact", trigger: "auto" }],
    ["codex", { hook_event_name: "PostCompact", trigger: "auto" }]
  ];

  for (const [vendor, event] of cases) {
    for (const transcriptPath of [null, "/missing/child-transcript.jsonl"]) {
      const root = await temporaryDirectory(`unproven-${vendor}-${event.hook_event_name}`);
      const stateDir = join(root, "state");
      const sessionId = `${vendor}-shared-parent-session`;
      await writeCheckpoint(validCheckpoint(sessionId, {
        vendor,
        transcriptPath: "/private/parent-session.jsonl"
      }), { stateDir });

      const result = await handleHook({
        vendor,
        input: {
          ...event,
          session_id: sessionId,
          transcript_path: transcriptPath
        },
        env: {}
      }, hookOptions(stateDir));

      assert.deepEqual(result, { stdout: "", stderr: "", exitCode: 0 });
      assert.equal(await pathExists(join(stateDir, "audit.jsonl")), false);
    }
  }
});

test("Codex compact SessionStart recovers when the runtime omits transcript_path", async () => {
  const root = await temporaryDirectory("codex-null-compact-start");
  const stateDir = join(root, "state");
  const transcriptPath = await writeCodexTranscript(root, "codex-tui", "codex-null-compact-start");
  const sessionId = "codex-null-compact-session";
  await handleHook({
    vendor: "codex",
    input: {
      hook_event_name: "PreCompact",
      session_id: sessionId,
      transcript_path: transcriptPath,
      trigger: "manual"
    },
    env: {}
  }, hookOptions(stateDir));

  const result = await handleHook({
    vendor: "codex",
    input: {
      hook_event_name: "SessionStart",
      source: "compact",
      session_id: sessionId,
      transcript_path: null
    },
    env: {}
  }, hookOptions(stateDir));
  const output = JSON.parse(result.stdout);
  const rows = await auditRows(stateDir);

  assert.equal(result.stderr, "");
  assert.equal(result.exitCode, 0);
  assert.equal(output.hookSpecificOutput.hookEventName, "SessionStart");
  assert.match(output.hookSpecificOutput.additionalContext, /use the verified checkpoint/u);
  assert.deepEqual(rows.map((row) => row.event), ["checkpoint", "injection"]);
  assert.deepEqual(rows.map((row) => row.surface), ["codex-cli", "codex-cli"]);
  assert.equal(rows[1].sessionHash, rows[0].sessionHash);
  assert.equal(rows[1].transcriptHash, rows[0].transcriptHash);
});

test("Codex compact SessionStart correlates an unreadable continuation to the trusted checkpoint", async () => {
  const root = await temporaryDirectory("codex-unreadable-compact-start");
  const stateDir = join(root, "state");
  const transcriptPath = await writeCodexTranscript(
    root,
    "Codex Desktop",
    "codex-unreadable-compact-start"
  );
  const sessionId = "codex-unreadable-compact-session";
  await handleHook({
    vendor: "codex",
    input: {
      hook_event_name: "PreCompact",
      session_id: sessionId,
      transcript_path: transcriptPath,
      trigger: "auto"
    },
    env: {}
  }, hookOptions(stateDir));

  const result = await handleHook({
    vendor: "codex",
    input: {
      hook_event_name: "SessionStart",
      source: "compact",
      session_id: sessionId,
      transcript_path: join(root, "missing-continuation.jsonl")
    },
    env: {}
  }, hookOptions(stateDir));
  const output = JSON.parse(result.stdout);
  const rows = await auditRows(stateDir);

  assert.equal(output.hookSpecificOutput.hookEventName, "SessionStart");
  assert.match(output.hookSpecificOutput.additionalContext, /use the verified checkpoint/u);
  assert.deepEqual(rows.map((row) => row.surface), ["codex-desktop", "codex-desktop"]);
  assert.equal(rows[1].sessionHash, rows[0].sessionHash);
  assert.equal(rows[1].transcriptHash, rows[0].transcriptHash);
});

test("non-compact SessionStart is a no-op", async () => {
  const stateDir = await temporaryDirectory("noncompact-start");

  const result = await handleHook({
    vendor: "claude",
    input: {
      hook_event_name: "SessionStart",
      source: "startup",
      session_id: "startup-session"
    },
    env: {}
  }, hookOptions(stateDir));

  assert.deepEqual(result, { stdout: "", stderr: "", exitCode: 0 });
});

test("compact SessionStart reads the PreCompact checkpoint directly", async () => {
  const root = await temporaryDirectory("compact-start");
  const stateDir = join(root, "state");
  const transcriptPath = await writeClaudeTranscript(root, "compact-start");
  await writeCheckpoint(validCheckpoint("recovery-session", { transcriptPath }), { stateDir });

  const result = await handleHook({
    vendor: "claude",
    input: {
      hook_event_name: "SessionStart",
      source: "compact",
      session_id: "recovery-session",
      transcript_path: transcriptPath
    },
    env: {}
  }, hookOptions(stateDir));
  const output = JSON.parse(result.stdout);

  assert.equal(result.stderr, "");
  assert.equal(result.exitCode, 0);
  assert.equal(output.hookSpecificOutput.hookEventName, "SessionStart");
  assert.match(output.hookSpecificOutput.additionalContext, /preserve this verified conclusion/u);
  assert.ok(output.hookSpecificOutput.additionalContext.length <= 8_500);
  const rows = await auditRows(stateDir);
  assert.equal(rows.at(-1).event, "injection");
  assert.equal(rows.at(-1).packetCharacters, output.hookSpecificOutput.additionalContext.length);
});

test("missing compact checkpoint returns a visible fixed warning", async () => {
  const root = await temporaryDirectory("missing-start");
  const stateDir = join(root, "state");
  const transcriptPath = await writeCodexTranscript(root, "codex-tui", "missing-start");

  const result = await handleHook({
    vendor: "codex",
    input: {
      hook_event_name: "SessionStart",
      source: "compact",
      session_id: "missing-session",
      transcript_path: transcriptPath,
      trigger: "auto"
    },
    env: {}
  }, hookOptions(stateDir));

  assert.deepEqual(JSON.parse(result.stdout), {
    systemMessage: "Compact Guard found no pre-compact checkpoint; recovery context was not injected."
  });
  assert.equal(result.exitCode, 0);
  const row = (await auditRows(stateDir)).at(-1);
  assert.equal(row.status, "missing");
  assert.equal(row.trigger, "compact");
});

test("SessionStart rejects unsafe or tampered checkpoints without injecting", async () => {
  const cases = [
    ["mode-0644", async (path) => chmod(path, 0o644)],
    ["symlink", async (path) => {
      const target = `${path}.target`;
      await rename(path, target);
      await symlink(target, path);
    }],
    ["schema-999", async (path, stored) => {
      await writeFile(path, `${JSON.stringify({ ...stored, schemaVersion: 999 })}\n`);
    }],
    ["wrong-vendor", async (path, stored) => {
      await writeFile(path, `${JSON.stringify({ ...stored, vendor: "codex" })}\n`);
    }],
    ["wrong-session", async (path, stored) => {
      await writeFile(path, `${JSON.stringify({ ...stored, sessionId: "other-session" })}\n`);
    }],
    ["entry-hash", async (path, stored) => {
      await writeFile(path, `${JSON.stringify({
        ...stored,
        entries: [{ ...stored.entries[0], hash: "0".repeat(64) }]
      })}\n`);
    }]
  ];

  for (const [name, corrupt] of cases) {
    const root = await temporaryDirectory(`rejected-${name}`);
    const stateDir = join(root, "state");
    const transcriptPath = await writeClaudeTranscript(root, `rejected-${name}`);
    const sessionId = `rejected-${name}`;
    await writeCheckpoint(validCheckpoint(sessionId, { transcriptPath }), { stateDir });
    const path = await storedCheckpointPath(stateDir);
    const stored = JSON.parse(await readFile(path, "utf8"));
    await corrupt(path, stored);
    const result = await handleHook({
      vendor: "claude",
      input: {
        hook_event_name: "SessionStart",
        source: "compact",
        session_id: sessionId,
        transcript_path: transcriptPath
      },
      env: {}
    }, hookOptions(stateDir));

    assert.deepEqual(JSON.parse(result.stdout), {
      systemMessage: "Compact Guard found no pre-compact checkpoint; recovery context was not injected."
    });
    assert.equal(result.stderr, "");
    assert.equal(result.exitCode, 0);
    assert.equal("hookSpecificOutput" in JSON.parse(result.stdout), false);
    assert.equal((await auditRows(stateDir)).at(-1).errorCode, "checkpoint_read_failed");
  }
});

test("successful injection audit reuses checkpoint correlation and trigger", async () => {
  const root = await temporaryDirectory("audit-correlation");
  const stateDir = join(root, "state");
  const transcriptPath = await writeClaudeTranscript(root, "correlation");
  const sessionId = "correlation-session";
  await handleHook({
    vendor: "claude",
    input: {
      hook_event_name: "PreCompact",
      session_id: sessionId,
      transcript_path: transcriptPath,
      trigger: "manual"
    },
    env: {}
  }, hookOptions(stateDir));
  await handleHook({
    vendor: "claude",
    input: {
      hook_event_name: "SessionStart",
      source: "compact",
      session_id: sessionId,
      transcript_path: transcriptPath,
      trigger: "auto"
    },
    env: {}
  }, hookOptions(stateDir));

  const [checkpointRow, injectionRow] = await auditRows(stateDir);
  assert.equal(checkpointRow.event, "checkpoint");
  assert.equal(injectionRow.event, "injection");
  assert.equal(injectionRow.trigger, "manual");
  assert.equal(injectionRow.trigger, checkpointRow.trigger);
  assert.equal(injectionRow.sessionHash, checkpointRow.sessionHash);
  assert.equal(injectionRow.transcriptHash, checkpointRow.transcriptHash);
});

test("Claude PostCompact stores only byte and lexical coverage metrics", async () => {
  const root = await temporaryDirectory("claude-postcompact");
  const stateDir = join(root, "state");
  const transcriptPath = await writeClaudeTranscript(root, "claude-postcompact");
  await writeCheckpoint(validCheckpoint("post-session", {
    trigger: "auto",
    transcriptPath,
    transcriptHash: "c".repeat(64),
    recordCount: 8,
    messageCount: 4,
    entries: [checkpointEntry({ text: "Decision keep local evidence" })]
  }), { stateDir });
  const summary = "Keep local evidence and decision.";

  const result = await handleHook({
    vendor: "claude",
    input: {
      hook_event_name: "PostCompact",
      session_id: "post-session",
      transcript_path: transcriptPath,
      trigger: "auto",
      compact_summary: summary
    },
    env: {}
  }, hookOptions(stateDir));
  const raw = await readFile(join(stateDir, "audit.jsonl"), "utf8");
  const row = JSON.parse(raw.trim());

  assert.deepEqual(result, { stdout: "", stderr: "", exitCode: 0 });
  assert.equal(row.event, "postcompact");
  assert.equal(row.summaryAvailable, true);
  assert.equal(row.summaryCharacters, summary.length);
  assert.equal(row.summaryBytes, Buffer.byteLength(summary));
  assert.equal(row.checkpointTermCount, 4);
  assert.equal(row.matchedTermCount, 4);
  assert.equal(row.lexicalCoverage, 1);
  assert.equal(raw.includes(summary), false);
  assert.equal(raw.includes("local evidence"), false);
});

test("Codex PostCompact records that no readable summary is available", async () => {
  const root = await temporaryDirectory("codex-postcompact");
  const stateDir = join(root, "state");
  const transcriptPath = await writeCodexTranscript(root, "codex-tui", "codex-postcompact");

  const result = await handleHook({
    vendor: "codex",
    input: {
      hook_event_name: "PostCompact",
      session_id: "codex-post-session",
      transcript_path: transcriptPath,
      trigger: "manual"
    },
    env: {}
  }, hookOptions(stateDir));
  const row = (await auditRows(stateDir)).at(-1);

  assert.deepEqual(result, { stdout: "", stderr: "", exitCode: 0 });
  assert.equal(row.event, "postcompact");
  assert.equal(row.summaryAvailable, false);
  assert.equal("summaryCharacters" in row, false);
});

test("CC_VENDOR labels ccp-gpt without skipping the checkpoint", async () => {
  const root = await temporaryDirectory("ccp-gpt");
  const stateDir = join(root, "state");
  const transcriptPath = await writeClaudeTranscript(root, "ccp");

  const result = await handleHook({
    vendor: "claude",
    input: {
      hook_event_name: "PreCompact",
      session_id: "ccp-session",
      transcript_path: transcriptPath,
      trigger: "manual"
    },
    env: { CC_VENDOR: "gpt" }
  }, hookOptions(stateDir));
  const stored = await readCheckpoint(
    { vendor: "claude", sessionId: "ccp-session" },
    { stateDir }
  );

  assert.equal(result.stdout, "");
  assert.equal(stored.sessionId, "ccp-session");
  assert.equal((await auditRows(stateDir)).at(-1).surface, "ccp-gpt");
});

test("unrelated CC_VENDOR values remain labeled as Claude Code", async () => {
  const root = await temporaryDirectory("non-ccp-vendor");
  const stateDir = join(root, "state");
  const transcriptPath = await writeClaudeTranscript(root, "non-ccp");

  const result = await handleHook({
    vendor: "claude",
    input: {
      hook_event_name: "PreCompact",
      session_id: "non-ccp-session",
      transcript_path: transcriptPath,
      trigger: "manual"
    },
    env: { CC_VENDOR: "glm" }
  }, hookOptions(stateDir));

  assert.equal(result.stdout, "");
  assert.equal((await auditRows(stateDir)).at(-1).surface, "claude-code");
});

test("Codex surface detection uses the first session originator", async () => {
  const cases = [
    ["Codex Desktop", "codex-desktop"],
    ["codex-tui", "codex-cli"],
    ["codex_exec", "codex-cli"],
    ["future-client", "codex-unknown"]
  ];

  for (const [originator, expectedSurface] of cases) {
    const root = await temporaryDirectory(`surface-${expectedSurface}`);
    const stateDir = join(root, "state");
    const transcriptPath = await writeCodexTranscript(root, originator, originator.replace(/\W+/gu, "-"));
    await handleHook({
      vendor: "codex",
      input: {
        hook_event_name: "PreCompact",
        session_id: `surface-${originator}`,
        transcript_path: transcriptPath,
        trigger: "auto"
      },
      env: {}
    }, hookOptions(stateDir));

    assert.equal((await auditRows(stateDir)).at(-1).surface, expectedSurface);
  }
});

test("disabled sentinel makes every guard event a non-blocking no-op", async () => {
  const stateDir = await temporaryDirectory("disabled");
  await writeFile(join(stateDir, "disabled"), "");

  const result = await handleHook({
    vendor: "claude",
    input: {
      hook_event_name: "PreCompact",
      session_id: "disabled-session",
      transcript_path: join(stateDir, "missing.jsonl"),
      trigger: "auto"
    },
    env: {}
  }, hookOptions(stateDir));

  assert.deepEqual(result, { stdout: "", stderr: "", exitCode: 0 });
  assert.equal((await auditRows(stateDir)).at(-1).event, "disabled");
});

test("CLI requires a matching vendor and managed hook event", async () => {
  const input = JSON.stringify({
    hook_event_name: "PreCompact",
    session_id: "cli-session",
    transcript_path: "/missing.jsonl",
    trigger: "manual"
  });
  const mismatch = spawnSync(process.execPath, [
    compactGuardBin,
    "--vendor",
    "claude",
    "--managed-id",
    "compact-guard/v1/claude/sessionstart"
  ], { encoding: "utf8", input });
  const wrongVendor = spawnSync(process.execPath, [
    compactGuardBin,
    "--vendor",
    "codex",
    "--managed-id",
    "compact-guard/v1/claude/precompact"
  ], { encoding: "utf8", input });

  assert.equal(mismatch.status, 1);
  assert.equal(mismatch.stdout, "");
  assert.equal(mismatch.stderr, "compact_guard_event_mismatch");
  assert.equal(wrongVendor.status, 1);
  assert.equal(wrongVendor.stdout, "");
  assert.equal(wrongVendor.stderr, "compact_guard_managed_id_mismatch");
});

test("CLI accepts exactly one JSON object and writes only hook output", async () => {
  const root = await temporaryDirectory("cli");
  const stateDir = join(root, "state");
  const transcriptPath = await writeClaudeTranscript(root, "cli");
  const input = {
    hook_event_name: "PreCompact",
    session_id: "cli-session",
    transcript_path: transcriptPath,
    trigger: "manual"
  };
  const success = spawnSync(process.execPath, [
    compactGuardBin,
    "--vendor",
    "claude",
    "--managed-id",
    "compact-guard/v1/claude/precompact"
  ], {
    encoding: "utf8",
    env: { ...process.env, COMPACT_GUARD_HOME: stateDir },
    input: JSON.stringify(input)
  });
  const multiple = spawnSync(process.execPath, [
    compactGuardBin,
    "--vendor",
    "claude",
    "--managed-id",
    "compact-guard/v1/claude/precompact"
  ], {
    encoding: "utf8",
    env: { ...process.env, COMPACT_GUARD_HOME: stateDir },
    input: `${JSON.stringify(input)}\n${JSON.stringify(input)}`
  });

  assert.equal(success.status, 0);
  assert.equal(success.stdout, "");
  assert.equal(success.stderr, "");
  assert.equal((await readCheckpoint(
    { vendor: "claude", sessionId: "cli-session" },
    { stateDir }
  )).sessionId, "cli-session");
  assert.equal(multiple.status, 1);
  assert.equal(multiple.stdout, "");
  assert.equal(multiple.stderr, "compact_guard_invalid_input");
});

test("queued compact SessionStart events inject once and mark later ones superseded", async () => {
  const root = await temporaryDirectory("codex-superseded-injection");
  const stateDir = join(root, "state");
  const transcriptPath = await writeCodexTranscript(root, "codex-tui", "codex-superseded-injection");
  const sessionId = "codex-superseded-session";
  const sessionStartInput = {
    hook_event_name: "SessionStart",
    source: "compact",
    session_id: sessionId,
    transcript_path: transcriptPath
  };
  await handleHook({
    vendor: "codex",
    input: {
      hook_event_name: "PreCompact",
      session_id: sessionId,
      transcript_path: transcriptPath,
      trigger: "auto"
    },
    env: {}
  }, hookOptions(stateDir));

  const first = await handleHook(
    { vendor: "codex", input: sessionStartInput, env: {} },
    hookOptions(stateDir)
  );
  const second = await handleHook(
    { vendor: "codex", input: sessionStartInput, env: {} },
    hookOptions(stateDir)
  );
  const rows = await auditRows(stateDir);

  assert.match(
    JSON.parse(first.stdout).hookSpecificOutput.additionalContext,
    /use the verified checkpoint/u
  );
  assert.deepEqual(second, { stdout: "", stderr: "", exitCode: 0 });
  assert.deepEqual(rows.map((row) => row.event), ["checkpoint", "injection", "injection"]);
  assert.equal(rows[1].status, "ok");
  assert.equal(rows[2].status, "superseded");
  assert.equal(rows[2].sessionHash, rows[0].sessionHash);
});

test("a fresh compact after a consumed checkpoint injects again", async () => {
  const root = await temporaryDirectory("codex-reinjection");
  const stateDir = join(root, "state");
  const transcriptPath = await writeCodexTranscript(root, "codex-tui", "codex-reinjection");
  const sessionId = "codex-reinjection-session";
  const preCompactInput = {
    hook_event_name: "PreCompact",
    session_id: sessionId,
    transcript_path: transcriptPath,
    trigger: "auto"
  };
  const sessionStartInput = {
    hook_event_name: "SessionStart",
    source: "compact",
    session_id: sessionId,
    transcript_path: transcriptPath
  };

  await handleHook({ vendor: "codex", input: preCompactInput, env: {} }, hookOptions(stateDir));
  await handleHook({ vendor: "codex", input: sessionStartInput, env: {} }, hookOptions(stateDir));
  await handleHook({ vendor: "codex", input: preCompactInput, env: {} }, hookOptions(stateDir));
  const reinjection = await handleHook(
    { vendor: "codex", input: sessionStartInput, env: {} },
    hookOptions(stateDir)
  );

  assert.match(
    JSON.parse(reinjection.stdout).hookSpecificOutput.additionalContext,
    /use the verified checkpoint/u
  );
});
