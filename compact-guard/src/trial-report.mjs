import { AUDIT_ENUM_VALUES, isIsoTimestamp } from "./storage.mjs";

const isObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
const AUDIT_ENUMS = Object.fromEntries(
  Object.entries(AUDIT_ENUM_VALUES).map(([field, values]) => [field, new Set(values)])
);
const HASH_FIELDS = ["sessionHash", "transcriptHash"];
const COUNT_FIELDS = [
  "recordCount",
  "messageCount",
  "entryCount",
  "packetCharacters",
  "summaryCharacters",
  "summaryBytes",
  "checkpointTermCount",
  "summaryTermCount",
  "matchedTermCount"
];
const BOOLEAN_FIELDS = ["summaryAvailable"];
const BASE_FIELDS = ["schemaVersion", "event", "vendor", "surface", "status", "timestamp"];
const CLAUDE_SURFACES = new Set(["claude-code", "ccp-gpt"]);
const CODEX_SURFACES = new Set(["codex-desktop", "codex-cli", "codex-unknown"]);
const MANUAL_TRIGGERS = new Set(["manual", "auto"]);

const createShape = (required, optional = []) => ({
  required: new Set([...BASE_FIELDS, ...required]),
  allowed: new Set([...BASE_FIELDS, ...required, ...optional])
});

const CHECKPOINT_SHAPE = createShape([
  "trigger",
  "sessionHash",
  "transcriptHash",
  "recordCount",
  "messageCount",
  "entryCount"
]);
const INJECTION_OK_SHAPE = createShape([
  "trigger",
  "sessionHash",
  "transcriptHash",
  "recordCount",
  "messageCount",
  "entryCount",
  "packetCharacters"
], ["anchor", "anchorCharacters"]);
const INJECTION_MISSING_SHAPE = createShape(["trigger", "errorCode", "sessionHash"]);
const INJECTION_SUPERSEDED_SHAPE = createShape(["trigger", "sessionHash"]);
const INJECTION_INVALID_SESSION_SHAPE = createShape(["trigger", "errorCode"]);
const INJECTION_READ_ERROR_SHAPE = createShape(["trigger", "errorCode", "sessionHash"]);
const BLOCKED_SHAPE = createShape(["errorCode"], ["trigger", "sessionHash"]);
const POSTCOMPACT_FALSE_SHAPE = createShape(
  ["summaryAvailable"],
  ["trigger", "sessionHash", "transcriptHash"]
);
const POSTCOMPACT_TRUE_SHAPE = createShape([
  "summaryAvailable",
  "summaryCharacters",
  "summaryBytes",
  "checkpointTermCount",
  "summaryTermCount",
  "matchedTermCount",
  "lexicalCoverage"
], ["trigger", "sessionHash", "transcriptHash"]);
const POSTCOMPACT_ERROR_SHAPE = createShape(
  ["errorCode", "summaryAvailable"],
  ["trigger", "sessionHash"]
);
const DISABLED_SHAPE = createShape([], ["trigger", "sessionHash"]);

const validOptionalFields = (row, fields, validate) => fields.every(
  (field) => !Object.hasOwn(row, field) || validate(row[field])
);

const hasShape = (row, shape) => [...shape.required].every((field) => Object.hasOwn(row, field))
  && Object.keys(row).every((field) => shape.allowed.has(field));

const hasCompatibleSurface = (row) => row.vendor === "claude"
  ? CLAUDE_SURFACES.has(row.surface)
  : CODEX_SURFACES.has(row.surface);

const hasManualTrigger = (row) => MANUAL_TRIGGERS.has(row.trigger);

const hasOptionalManualTrigger = (row) => !Object.hasOwn(row, "trigger") || hasManualTrigger(row);

const isValidBaseRow = (row) => isObject(row)
  && AUDIT_ENUMS.event.has(row.event)
  && row.schemaVersion === 1
  && AUDIT_ENUMS.vendor.has(row.vendor)
  && AUDIT_ENUMS.surface.has(row.surface)
  && AUDIT_ENUMS.status.has(row.status)
  && (!Object.hasOwn(row, "trigger") || AUDIT_ENUMS.trigger.has(row.trigger))
  && (!Object.hasOwn(row, "errorCode") || AUDIT_ENUMS.errorCode.has(row.errorCode))
  && isIsoTimestamp(row.timestamp)
  && hasCompatibleSurface(row)
  && validOptionalFields(
    row,
    HASH_FIELDS,
    (value) => typeof value === "string" && /^[a-f0-9]{64}$/u.test(value)
  )
  && validOptionalFields(
    row,
    COUNT_FIELDS,
    (value) => Number.isSafeInteger(value) && value >= 0
  )
  && validOptionalFields(row, BOOLEAN_FIELDS, (value) => typeof value === "boolean")
  && (
    row.lexicalCoverage === undefined
    || (Number.isFinite(row.lexicalCoverage) && row.lexicalCoverage >= 0 && row.lexicalCoverage <= 1)
  );

const isSuccessfulCheckpoint = (row) => row.event === "checkpoint"
  && row.status === "ok"
  && hasManualTrigger(row)
  && hasShape(row, CHECKPOINT_SHAPE);

const isSuccessfulInjection = (row) => row.event === "injection"
  && row.status === "ok"
  && hasManualTrigger(row)
  && hasShape(row, INJECTION_OK_SHAPE);

const isSupersededInjection = (row) => row.event === "injection"
  && row.status === "superseded"
  && hasManualTrigger(row)
  && hasShape(row, INJECTION_SUPERSEDED_SHAPE);

const isMissingInjection = (row) => row.event === "injection"
  && row.status === "missing"
  && row.trigger === "compact"
  && row.errorCode === "missing_checkpoint"
  && hasShape(row, INJECTION_MISSING_SHAPE);

const isFailedInjection = (row) => {
  if (row.event !== "injection" || row.status !== "error" || row.trigger !== "compact") {
    return false;
  }
  if (row.errorCode === "invalid_session") {
    return hasShape(row, INJECTION_INVALID_SESSION_SHAPE);
  }
  return row.errorCode === "checkpoint_read_failed"
    && hasShape(row, INJECTION_READ_ERROR_SHAPE);
};

const isBlocked = (row) => row.event === "blocked"
  && row.status === "error"
  && row.errorCode === "checkpoint_failed"
  && hasShape(row, BLOCKED_SHAPE);

const isSuccessfulPostCompact = (row) => {
  if (row.event !== "postcompact" || row.status !== "ok" || !hasOptionalManualTrigger(row)) {
    return false;
  }
  if (row.summaryAvailable === false) {
    return hasShape(row, POSTCOMPACT_FALSE_SHAPE);
  }
  return row.vendor === "claude"
    && row.summaryAvailable === true
    && hasShape(row, POSTCOMPACT_TRUE_SHAPE);
};

const isFailedPostCompact = (row) => row.event === "postcompact"
  && row.status === "error"
  && row.errorCode === "postcompact_failed"
  && row.summaryAvailable === false
  && hasOptionalManualTrigger(row)
  && hasShape(row, POSTCOMPACT_ERROR_SHAPE);

const isDisabled = (row) => row.event === "disabled"
  && row.status === "disabled"
  && hasShape(row, DISABLED_SHAPE);

const isValidAuditRow = (row) => isValidBaseRow(row) && (
  isSuccessfulCheckpoint(row)
  || isSuccessfulInjection(row)
  || isSupersededInjection(row)
  || isMissingInjection(row)
  || isFailedInjection(row)
  || isBlocked(row)
  || isSuccessfulPostCompact(row)
  || isFailedPostCompact(row)
  || isDisabled(row)
);

const increment = (counts, value) => {
  if (typeof value !== "string" || value.length === 0) {
    return;
  }
  counts.set(value, (counts.get(value) ?? 0) + 1);
};

const sortedCounts = (counts) => Object.fromEntries(
  [...counts.entries()].sort(([left], [right]) => left.localeCompare(right))
);

const isState = (row, value) => row.event === value || row.status === value;

const pairKey = (row) => {
  const values = [row.vendor, row.surface, row.sessionHash, row.transcriptHash];
  return values.every((value) => typeof value === "string" && value.length > 0)
    ? JSON.stringify(values)
    : null;
};

const pairCheckpointInjections = (rows) => {
  const checkpointQueues = new Map();
  let unmatchedInjections = 0;
  let checkpointTotal = 0;
  let injectionTotal = 0;
  let matchedCheckpointInjections = 0;
  let supersededInjections = 0;

  for (const row of rows) {
    if (isSuccessfulCheckpoint(row)) {
      checkpointTotal += 1;
      const key = pairKey(row);
      const queue = checkpointQueues.get(key) ?? [];
      queue.push(row);
      checkpointQueues.set(key, queue);
    } else if (isSupersededInjection(row)) {
      supersededInjections += 1;
    } else if (row.event === "injection") {
      injectionTotal += 1;
      if (!isSuccessfulInjection(row)) {
        unmatchedInjections += 1;
        continue;
      }
      const queue = checkpointQueues.get(pairKey(row)) ?? [];
      const checkpoint = queue[0];
      if (checkpoint && checkpoint.timestamp <= row.timestamp) {
        queue.shift();
        matchedCheckpointInjections += 1;
      } else {
        unmatchedInjections += 1;
      }
    }
  }

  const denominator = Math.max(checkpointTotal, injectionTotal);
  return {
    matchedCheckpointInjections,
    unmatchedCheckpoints: checkpointTotal - matchedCheckpointInjections,
    unmatchedInjections,
    supersededInjections,
    matchRate: denominator === 0 ? 0 : matchedCheckpointInjections / denominator
  };
};

const outcomeKey = (row) => {
  const values = [row.vendor, row.surface, row.sessionHash];
  return values.every((value) => typeof value === "string" && value.length > 0)
    ? JSON.stringify(values)
    : null;
};

const classifyCheckpoints = (rows) => {
  const groups = new Map();
  for (const row of rows) {
    const key = outcomeKey(row);
    if (key === null) {
      continue;
    }
    const group = groups.get(key) ?? [];
    group.push(row);
    groups.set(key, group);
  }
  const outcomes = { injected: 0, completedNoInjection: 0, noCompletion: 0 };
  for (const group of groups.values()) {
    group.sort((left, right) => left.timestamp.localeCompare(right.timestamp));
    for (let index = 0; index < group.length; index += 1) {
      if (!isSuccessfulCheckpoint(group[index])) {
        continue;
      }
      let outcome = "noCompletion";
      for (let cursor = index + 1; cursor < group.length; cursor += 1) {
        const row = group[cursor];
        if (isSuccessfulCheckpoint(row)) {
          break;
        }
        if (isSuccessfulInjection(row)) {
          outcome = "injected";
          break;
        }
        if (row.event === "postcompact") {
          outcome = "completedNoInjection";
        }
      }
      outcomes[outcome] += 1;
    }
  }
  return outcomes;
};

export const summarizeAudit = (rows) => {
  const values = Array.isArray(rows) ? rows : [];
  const validRows = values.filter(isValidAuditRow);
  const eventCounts = new Map();
  const statusCounts = new Map();
  const vendorCounts = new Map();
  const surfaceCounts = new Map();
  const triggerCounts = new Map();

  for (const row of validRows) {
    increment(eventCounts, row.event);
    increment(statusCounts, row.status);
    increment(vendorCounts, row.vendor);
    increment(surfaceCounts, row.surface);
    increment(triggerCounts, row.trigger);
  }

  const pairing = pairCheckpointInjections(validRows);
  const maxPacketCharacters = validRows.reduce(
    (maximum, row) => isSuccessfulInjection(row)
      ? Math.max(maximum ?? row.packetCharacters, row.packetCharacters)
      : maximum,
    null
  );

  return {
    schemaVersion: 1,
    totalRows: values.length,
    validRows: validRows.length,
    invalidRows: values.length - validRows.length,
    eventCounts: sortedCounts(eventCounts),
    statusCounts: sortedCounts(statusCounts),
    vendorCounts: sortedCounts(vendorCounts),
    surfaceCounts: sortedCounts(surfaceCounts),
    triggerCounts: sortedCounts(triggerCounts),
    error: validRows.filter((row) => isState(row, "error")).length,
    blocked: validRows.filter((row) => isState(row, "blocked")).length,
    disabled: validRows.filter((row) => isState(row, "disabled")).length,
    ...pairing,
    checkpointOutcomes: classifyCheckpoints(validRows),
    maxPacketCharacters
  };
};
