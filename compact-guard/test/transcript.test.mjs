import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { extractMessages } from "../src/transcript.mjs";

const fixturePath = (name) => new URL(`./fixtures/${name}`, import.meta.url);

const expectedHash = async (path) => {
  const contents = await readFile(path);
  return createHash("sha256").update(contents).digest("hex");
};

const temporaryTranscript = async (name, records) => {
  const transcriptPath = join(tmpdir(), `compact-guard-${name}-${process.pid}.jsonl`);
  await writeFile(transcriptPath, records.map((record) => JSON.stringify(record)).join("\n"));
  return transcriptPath;
};

test("Claude extracts user strings and aggregates assistant text by stable source ID", async () => {
  const transcriptPath = fixturePath("claude.jsonl");

  const result = await extractMessages({ vendor: "claude", transcriptPath });

  assert.deepEqual(result.messages, [
    {
      id: "claude-user-1",
      role: "user",
      timestamp: "2026-07-16T00:00:00.000Z",
      text: "Keep this local only.",
      index: 0
    },
    {
      id: "claude-message-1",
      role: "assistant",
      timestamp: "2026-07-16T00:01:00.000Z",
      text: "The first finding is unsupported.\n\nThe current verdict is reject.",
      index: 1
    },
    {
      id: "claude-request-fallback",
      role: "assistant",
      timestamp: "2026-07-16T00:01:02.000Z",
      text: "Request fallback part one.\n\nRequest fallback part two.",
      index: 2
    },
    {
      id: "claude-uuid-fallback",
      role: "assistant",
      timestamp: "2026-07-16T00:01:04.000Z",
      text: "UUID fallback response.",
      index: 3
    }
  ]);
  assert.equal(result.recordCount, 17);
  assert.equal(result.transcriptHash, await expectedHash(transcriptPath));
});

test("Codex extracts human event messages and assistant response messages only", async () => {
  const transcriptPath = fixturePath("codex.jsonl");

  const result = await extractMessages({ vendor: "codex", transcriptPath });

  assert.deepEqual(result.messages, [
    {
      id: "codex:user:2",
      role: "user",
      timestamp: "2026-07-16T01:01:00.100Z",
      text: "Do not browse the web.",
      index: 0
    },
    {
      id: "codex-assistant-1",
      role: "assistant",
      timestamp: "2026-07-16T01:02:00.000Z",
      text: "The local evidence supports the fix.",
      index: 1
    }
  ]);
  const text = result.messages.map((message) => message.text).join("\n");
  assert.doesNotMatch(text, /<recommended_plugins>/u);
  assert.doesNotMatch(text, /# AGENTS\.md instructions/u);
  assert.doesNotMatch(text, /<environment_context>/u);
  assert.equal(result.recordCount, 9);
  assert.equal(result.transcriptHash, await expectedHash(transcriptPath));
});

test("pure Claude and metadata-marked Codex subagent transcripts reject with a fixed code", async () => {
  for (const vendor of ["claude", "codex"]) {
    await assert.rejects(
      extractMessages({
        vendor,
        transcriptPath: fixturePath(`${vendor}-subagent.jsonl`)
      }),
      (error) => error?.code === "subagent_transcript"
    );
  }
});

test("each Codex subagent metadata indicator rejects the whole transcript", async () => {
  const indicators = [
    { source: { subagent: { other: "guardian" } } },
    { parent_thread_id: "parent-thread" }
  ];

  for (const [index, indicator] of indicators.entries()) {
    const transcriptPath = await temporaryTranscript(`codex-subagent-indicator-${index}`, [
      {
        type: "session_meta",
        payload: { id: `subagent-${index}`, ...indicator }
      },
      {
        type: "event_msg",
        payload: { type: "user_message", message: "Subagent request" }
      }
    ]);
    await assert.rejects(
      extractMessages({ vendor: "codex", transcriptPath }),
      (error) => error?.code === "subagent_transcript"
    );
  }
});

test("Claude extracts user text-block arrays", async () => {
  const transcriptPath = await temporaryTranscript("claude-user-blocks", [{
    type: "user",
    uuid: "claude-user-blocks",
    timestamp: "2026-07-16T02:10:00.000Z",
    message: {
      role: "user",
      content: [
        { type: "text", text: "First user block." },
        { type: "text", text: "Second user block." }
      ]
    }
  }]);

  const result = await extractMessages({ vendor: "claude", transcriptPath });

  assert.equal(result.messages.length, 1);
  assert.equal(result.messages[0].text, "First user block.\n\nSecond user block.");
});

test("Claude excludes a whole user array when it contains a tool result", async () => {
  const transcriptPath = await temporaryTranscript("claude-mixed-tool-result", [
    {
      type: "user",
      uuid: "claude-safe-user",
      timestamp: "2026-07-16T02:11:00.000Z",
      message: { role: "user", content: "Safe user text." }
    },
    {
      type: "user",
      uuid: "claude-mixed-user",
      timestamp: "2026-07-16T02:12:00.000Z",
      message: {
        role: "user",
        content: [
          { type: "text", text: "Text beside tool output." },
          { type: "tool_result", tool_use_id: "tool-1", content: "Tool output." }
        ]
      }
    }
  ]);

  const result = await extractMessages({ vendor: "claude", transcriptPath });

  assert.deepEqual(result.messages.map(({ id, text }) => ({ id, text })), [
    { id: "claude-safe-user", text: "Safe user text." }
  ]);
});

test("Claude excludes system-originated user records such as background task notifications", async () => {
  const transcriptPath = await temporaryTranscript("claude-system-origin", [
    {
      type: "user",
      uuid: "claude-typed-user",
      timestamp: "2026-07-16T02:13:00.000Z",
      promptSource: "typed",
      turnOrigin: "human",
      message: { role: "user", content: "Why does <task-notification> keep appearing?" }
    },
    {
      type: "user",
      uuid: "claude-task-notification",
      timestamp: "2026-07-16T02:14:00.000Z",
      promptSource: "system",
      turnOrigin: "task_notification",
      message: { role: "user", content: "<task-notification>\n<status>completed</status>\n</task-notification>" }
    },
    {
      type: "user",
      uuid: "claude-system-source-only",
      timestamp: "2026-07-16T02:15:00.000Z",
      promptSource: "system",
      message: { role: "user", content: "<task-notification>\n<status>failed</status>\n</task-notification>" }
    },
    {
      type: "user",
      uuid: "claude-notification-origin-only",
      timestamp: "2026-07-16T02:16:00.000Z",
      turnOrigin: "task_notification",
      message: { role: "user", content: "This session is being continued from a previous conversation." }
    }
  ]);

  const result = await extractMessages({ vendor: "claude", transcriptPath });

  assert.deepEqual(result.messages.map(({ id }) => id), ["claude-typed-user"]);
});

test("malformed records are counted and a transcript without messages rejects", async () => {
  const transcriptPath = join(tmpdir(), `compact-guard-empty-${process.pid}.jsonl`);
  await writeFile(
    transcriptPath,
    [
      "malformed",
      JSON.stringify({ type: "event_msg", payload: { type: "user_message", message: "   " } }),
      JSON.stringify({ type: "response_item", payload: { type: "message", role: "developer", content: [] } })
    ].join("\n")
  );

  await assert.rejects(
    extractMessages({ vendor: "codex", transcriptPath }),
    /no valid conversation messages/i
  );
});

test("an incomplete final JSONL fragment is deferred instead of counted as malformed", async () => {
  const transcriptPath = join(tmpdir(), `compact-guard-partial-${process.pid}.jsonl`);
  const completeRecord = JSON.stringify({
    timestamp: "2026-07-16T02:00:00.000Z",
    type: "event_msg",
    payload: {
      type: "user_message",
      message: "Complete record"
    }
  });
  await writeFile(transcriptPath, `${completeRecord}\n{"type":"response_item"`);

  const result = await extractMessages({ vendor: "codex", transcriptPath });

  assert.equal(result.recordCount, 1);
  assert.equal(result.messages.length, 1);
  assert.equal(result.transcriptHash, await expectedHash(transcriptPath));
});
