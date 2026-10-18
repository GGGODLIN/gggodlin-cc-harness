import { buildAnchorBlock } from "./anchor.mjs";
import { renderRecoveryPacket, selectEvidence } from "./text.mjs";
import {
  extractMessages,
  inspectTranscript,
  SUBAGENT_TRANSCRIPT_ERROR_CODE
} from "./transcript.mjs";
import {
  appendAudit,
  hashSessionId,
  isDisabled,
  markCheckpointInjected,
  readCheckpoint,
  writeCheckpoint
} from "./storage.mjs";

const EMPTY_RESULT = { stdout: "", stderr: "", exitCode: 0 };
const CHECKPOINT_FAILURE = "Compact Guard could not create a pre-compact checkpoint.";
const MISSING_CHECKPOINT = "Compact Guard found no pre-compact checkpoint; recovery context was not injected.";
const VALID_VENDORS = new Set(["claude", "codex"]);

const jsonResult = (value) => ({
  stdout: JSON.stringify(value),
  stderr: "",
  exitCode: 0
});

const errorResult = (errorCode) => ({
  stdout: "",
  stderr: errorCode,
  exitCode: 1
});

const normalizeNow = (now) => {
  const value = typeof now === "function" ? now() : now;
  const date = value instanceof Date ? value : new Date(value ?? Date.now());
  if (Number.isNaN(date.getTime())) {
    return new Date(0).toISOString();
  }
  return date.toISOString();
};

const storageOptions = (options, env) => ({
  stateDir: options?.stateDir ?? (
    typeof env?.COMPACT_GUARD_HOME === "string" && env.COMPACT_GUARD_HOME.length > 0
      ? env.COMPACT_GUARD_HOME
      : undefined
  )
});

const claudeSurface = (env) =>
  env?.CC_VENDOR === "gpt"
    ? "ccp-gpt"
    : "claude-code";

const codexOriginator = async (transcriptPath) => {
  if (typeof transcriptPath !== "string" || transcriptPath.length === 0) {
    return null;
  }
  try {
    return (await inspectTranscript({ vendor: "codex", transcriptPath })).originator;
  } catch {
    return null;
  }
};

const codexSurface = async (transcriptPath) => {
  const originator = await codexOriginator(transcriptPath);
  if (originator === "Codex Desktop") {
    return "codex-desktop";
  }
  if (originator === "codex-tui" || originator === "codex_exec") {
    return "codex-cli";
  }
  return "codex-unknown";
};

const resolveSurface = async (vendor, transcriptPath, env) =>
  vendor === "claude"
    ? claudeSurface(env)
    : codexSurface(transcriptPath);

const safeSessionHash = (sessionId) => {
  try {
    return hashSessionId(sessionId);
  } catch {
    return undefined;
  }
};

const auditBase = ({ event, vendor, surface, input, timestamp }) => ({
  schemaVersion: 1,
  event,
  vendor,
  surface,
  trigger: input?.trigger,
  sessionHash: safeSessionHash(input?.session_id),
  timestamp
});

const tryAudit = async (event, options) => {
  try {
    await appendAudit(event, options);
  } catch {
    return false;
  }
  return true;
};

const requirePreCompactInput = (input) => {
  if (
    typeof input?.session_id !== "string" ||
    input.session_id.length === 0 ||
    typeof input.transcript_path !== "string" ||
    input.transcript_path.length === 0 ||
    (input.trigger !== "manual" && input.trigger !== "auto")
  ) {
    throw new TypeError("invalid_precompact_input");
  }
};

const subagentSkipEvent = (input) =>
  input?.hook_event_name === "PreCompact" ||
  input?.hook_event_name === "PostCompact" ||
  (input?.hook_event_name === "SessionStart" && input?.source === "compact");

const hasAgentId = (input) =>
  typeof input?.agent_id === "string" && input.agent_id.trim().length > 0;

const hookTranscriptScope = async (vendor, input) => {
  if (!subagentSkipEvent(input)) {
    return "unmanaged";
  }
  if (hasAgentId(input)) {
    return "subagent";
  }
  if (typeof input?.transcript_path !== "string" || input.transcript_path.length === 0) {
    return "unknown";
  }
  try {
    const inspection = await inspectTranscript({
      vendor,
      transcriptPath: input.transcript_path
    });
    if (inspection.isSubagent) {
      return "subagent";
    }
    return inspection.isRoot ? "root" : "unknown";
  } catch {
    return "unknown";
  }
};

const codexRootCompactStart = (vendor, input) =>
  vendor === "codex" &&
  input?.hook_event_name === "SessionStart" &&
  input?.source === "compact";

const unprovenContinuation = (vendor, input, scope) =>
  scope === "unknown" && (
    input?.hook_event_name === "PostCompact" ||
    (
      input?.hook_event_name === "SessionStart" &&
      input?.source === "compact" &&
      !codexRootCompactStart(vendor, input)
    )
  );

const checkpointFailureOutput = (vendor) => vendor === "claude"
  ? {
      decision: "block",
      reason: CHECKPOINT_FAILURE
    }
  : {
      continue: false,
      stopReason: CHECKPOINT_FAILURE,
      systemMessage: CHECKPOINT_FAILURE
    };

const handlePreCompact = async ({ vendor, input, env }, options, state) => {
  let surface = vendor === "claude" ? claudeSurface(env) : "codex-unknown";
  try {
    requirePreCompactInput(input);
    surface = await resolveSurface(vendor, input.transcript_path, env);
    const extracted = await extractMessages({
      vendor,
      transcriptPath: input.transcript_path
    });
    const entries = selectEvidence(extracted.messages);
    const checkpoint = {
      schemaVersion: 1,
      vendor,
      sessionId: input.session_id,
      trigger: input.trigger,
      transcriptPath: input.transcript_path,
      transcriptHash: extracted.transcriptHash,
      recordCount: extracted.recordCount,
      messageCount: extracted.messages.length,
      capturedAt: normalizeNow(options?.now),
      entries
    };
    await writeCheckpoint(checkpoint, state);
    await tryAudit({
      ...auditBase({
        event: "checkpoint",
        vendor,
        surface,
        input,
        timestamp: checkpoint.capturedAt
      }),
      status: "ok",
      transcriptHash: checkpoint.transcriptHash,
      recordCount: checkpoint.recordCount,
      messageCount: checkpoint.messageCount,
      entryCount: checkpoint.entries.length
    }, state);
    return EMPTY_RESULT;
  } catch (error) {
    if (error?.code === SUBAGENT_TRANSCRIPT_ERROR_CODE) {
      return EMPTY_RESULT;
    }
    await tryAudit({
      ...auditBase({
        event: "blocked",
        vendor,
        surface,
        input,
        timestamp: normalizeNow(options?.now)
      }),
      status: "error",
      errorCode: "checkpoint_failed"
    }, state);
    return jsonResult(checkpointFailureOutput(vendor));
  }
};

const handleSessionStart = async ({ vendor, input, env }, options, state) => {
  if (input?.source !== "compact") {
    return EMPTY_RESULT;
  }
  const timestamp = normalizeNow(options?.now);
  const initialSurface = vendor === "claude" ? claudeSurface(env) : "codex-unknown";
  if (typeof input.session_id !== "string" || input.session_id.length === 0) {
    await tryAudit({
      ...auditBase({
        event: "injection",
        vendor,
        surface: initialSurface,
        input,
        timestamp
      }),
      trigger: "compact",
      status: "error",
      errorCode: "invalid_session"
    }, state);
    return jsonResult({ systemMessage: MISSING_CHECKPOINT });
  }
  try {
    const checkpoint = await readCheckpoint({
      vendor,
      sessionId: input.session_id
    }, state);
    const transcriptPath = checkpoint?.transcriptPath ?? input.transcript_path;
    const surface = await resolveSurface(vendor, transcriptPath, env);
    if (!checkpoint) {
      await tryAudit({
        ...auditBase({
          event: "injection",
          vendor,
          surface,
          input,
          timestamp
        }),
        trigger: "compact",
        status: "missing",
        errorCode: "missing_checkpoint"
      }, state);
      return jsonResult({ systemMessage: MISSING_CHECKPOINT });
    }
    if (typeof checkpoint.injectedAt === "string") {
      await tryAudit({
        ...auditBase({
          event: "injection",
          vendor,
          surface,
          input,
          timestamp
        }),
        trigger: checkpoint.trigger,
        status: "superseded"
      }, state);
      return EMPTY_RESULT;
    }
    const recoveryPacket = renderRecoveryPacket({
      ...checkpoint,
      evidence: checkpoint.entries
    });
    let anchor = null;
    if (vendor === "claude") {
      try {
        anchor = await (options?.buildAnchorBlock ?? buildAnchorBlock)({ checkpoint, env, home: options?.home });
      } catch {}
    }
    const additionalContext = anchor ? `${recoveryPacket}\n\n${anchor.text}` : recoveryPacket;
    try {
      await markCheckpointInjected({
        vendor,
        sessionId: input.session_id,
        injectedAt: timestamp
      }, state);
    } catch {}
    await tryAudit({
      ...auditBase({
        event: "injection",
        vendor,
        surface,
        input,
        timestamp
      }),
      trigger: checkpoint.trigger,
      status: "ok",
      transcriptHash: checkpoint.transcriptHash,
      recordCount: checkpoint.recordCount,
      messageCount: checkpoint.messageCount,
      entryCount: checkpoint.entries?.length,
      packetCharacters: additionalContext.length,
      ...(anchor ? { anchor: anchor.kind, anchorCharacters: anchor.characters } : {})
    }, state);
    return jsonResult({
      hookSpecificOutput: {
        hookEventName: "SessionStart",
        additionalContext
      }
    });
  } catch {
    await tryAudit({
      ...auditBase({
        event: "injection",
        vendor,
        surface: initialSurface,
        input,
        timestamp
      }),
      trigger: "compact",
      status: "error",
      errorCode: "checkpoint_read_failed"
    }, state);
    return jsonResult({ systemMessage: MISSING_CHECKPOINT });
  }
};

const lexicalTerms = (text) => new Set(
  String(text ?? "")
    .toLocaleLowerCase("en-US")
    .match(/[\p{L}\p{N}_-]{3,}/gu) ?? []
);

const coverageMetrics = (checkpoint, summary) => {
  const checkpointTerms = lexicalTerms(
    (checkpoint?.entries ?? []).map((entry) => entry?.text ?? "").join("\n")
  );
  const summaryTerms = lexicalTerms(summary);
  const matchedTermCount = [...checkpointTerms].filter((term) => summaryTerms.has(term)).length;
  return {
    checkpointTermCount: checkpointTerms.size,
    summaryTermCount: summaryTerms.size,
    matchedTermCount,
    lexicalCoverage: checkpointTerms.size === 0
      ? 0
      : matchedTermCount / checkpointTerms.size
  };
};

const handlePostCompact = async ({ vendor, input, env }, options, state) => {
  const timestamp = normalizeNow(options?.now);
  let surface = vendor === "claude" ? claudeSurface(env) : "codex-unknown";
  try {
    let checkpoint = null;
    if (typeof input?.session_id === "string" && input.session_id.length > 0) {
      checkpoint = await readCheckpoint({ vendor, sessionId: input.session_id }, state);
    }
    surface = await resolveSurface(
      vendor,
      input?.transcript_path ?? checkpoint?.transcriptPath,
      env
    );
    const audit = {
      ...auditBase({ event: "postcompact", vendor, surface, input, timestamp }),
      status: "ok",
      transcriptHash: checkpoint?.transcriptHash,
      summaryAvailable: vendor === "claude" && typeof input?.compact_summary === "string"
    };
    if (audit.summaryAvailable) {
      Object.assign(audit, {
        summaryCharacters: input.compact_summary.length,
        summaryBytes: Buffer.byteLength(input.compact_summary),
        ...coverageMetrics(checkpoint, input.compact_summary)
      });
    }
    await tryAudit(audit, state);
  } catch {
    await tryAudit({
      ...auditBase({ event: "postcompact", vendor, surface, input, timestamp }),
      status: "error",
      errorCode: "postcompact_failed",
      summaryAvailable: false
    }, state);
  }
  return EMPTY_RESULT;
};

export const handleHook = async ({ vendor, input, env = {} }, options = {}) => {
  if (!VALID_VENDORS.has(vendor)) {
    return errorResult("compact_guard_invalid_vendor");
  }
  const transcriptScope = await hookTranscriptScope(vendor, input);
  if (transcriptScope === "subagent" || unprovenContinuation(vendor, input, transcriptScope)) {
    return EMPTY_RESULT;
  }
  const state = storageOptions(options, env);
  try {
    if (await isDisabled(state)) {
      await tryAudit({
        ...auditBase({
          event: "disabled",
          vendor,
          surface: vendor === "claude" ? claudeSurface(env) : "codex-unknown",
          input,
          timestamp: normalizeNow(options?.now)
        }),
        status: "disabled"
      }, state);
      return EMPTY_RESULT;
    }
  } catch {
    if (input?.hook_event_name === "PreCompact") {
      return jsonResult(checkpointFailureOutput(vendor));
    }
    if (input?.hook_event_name === "SessionStart" && input?.source === "compact") {
      return jsonResult({ systemMessage: MISSING_CHECKPOINT });
    }
    return EMPTY_RESULT;
  }
  if (input?.hook_event_name === "PreCompact") {
    return handlePreCompact({ vendor, input, env }, options, state);
  }
  if (input?.hook_event_name === "PostCompact") {
    return handlePostCompact({ vendor, input, env }, options, state);
  }
  if (input?.hook_event_name === "SessionStart") {
    return handleSessionStart({ vendor, input, env }, options, state);
  }
  return errorResult("compact_guard_invalid_hook_event");
};
