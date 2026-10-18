import { createHash, randomUUID } from "node:crypto";
import { constants } from "node:fs";
import {
  access,
  chmod,
  lstat,
  mkdir,
  open,
  rename,
  unlink
} from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, isAbsolute, join } from "node:path";

const CHECKPOINT_CATEGORIES = new Set([
  "correction",
  "decision",
  "constraint",
  "pending",
  "evidence",
  "recent"
]);
export const AUDIT_ENUM_VALUES = Object.freeze({
  event: Object.freeze(["checkpoint", "blocked", "injection", "postcompact", "disabled"]),
  vendor: Object.freeze(["claude", "codex"]),
  surface: Object.freeze([
    "claude-code",
    "ccp-gpt",
    "codex-desktop",
    "codex-cli",
    "codex-unknown"
  ]),
  trigger: Object.freeze(["manual", "auto", "compact"]),
  status: Object.freeze(["ok", "error", "missing", "disabled", "superseded"]),
  errorCode: Object.freeze([
    "checkpoint_failed",
    "invalid_session",
    "missing_checkpoint",
    "checkpoint_read_failed",
    "postcompact_failed"
  ]),
  anchor: Object.freeze(["pinned", "pin_unreadable", "nudge"])
});
const AUDIT_ENUMS = Object.fromEntries(
  Object.entries(AUDIT_ENUM_VALUES).map(([field, values]) => [field, new Set(values)])
);
const HASH_AUDIT_FIELDS = new Set(["sessionHash", "transcriptHash"]);
const COUNT_AUDIT_FIELDS = new Set([
  "recordCount",
  "messageCount",
  "entryCount",
  "packetCharacters",
  "anchorCharacters",
  "summaryCharacters",
  "summaryBytes",
  "checkpointTermCount",
  "summaryTermCount",
  "matchedTermCount"
]);
const BOOLEAN_AUDIT_FIELDS = new Set(["summaryAvailable"]);
const NUMBER_AUDIT_FIELDS = new Set(["lexicalCoverage"]);

const resolveStateDir = (options) => options?.stateDir ?? join(homedir(), ".compact-guard");

const sessionHash = (sessionId) => createHash("sha256").update(sessionId).digest("hex");

const storageError = (code) => Object.assign(new Error(code), { code });

const isPlainObject = (value) =>
  value !== null && typeof value === "object" && !Array.isArray(value);

export const isIsoTimestamp = (value) => {
  if (typeof value !== "string") {
    return false;
  }
  const date = new Date(value);
  return !Number.isNaN(date.getTime()) && date.toISOString() === value;
};

const isHash = (value) => typeof value === "string" && /^[a-f0-9]{64}$/u.test(value);

const isCount = (value) => Number.isSafeInteger(value) && value >= 0;

const requireVendor = (vendor) => {
  if (vendor !== "claude" && vendor !== "codex") {
    throw storageError("invalid_vendor");
  }
  return vendor;
};

const requireSessionId = (sessionId) => {
  if (typeof sessionId !== "string" || sessionId.length === 0) {
    throw storageError("invalid_session_id");
  }
  return sessionId;
};

const ensurePrivateDirectory = async (path) => {
  await mkdir(path, { recursive: true, mode: 0o700 });
  await chmod(path, 0o700);
};

const checkpointDirectory = (stateDir, vendor) =>
  join(stateDir, "checkpoints", requireVendor(vendor));

const checkpointPath = (stateDir, vendor, sessionId) =>
  join(checkpointDirectory(stateDir, vendor), `${sessionHash(requireSessionId(sessionId))}.json`);

const syncDirectory = async (path) => {
  const handle = await open(path, "r");
  try {
    await handle.sync();
  } finally {
    await handle.close();
  }
};

const atomicWrite = async (path, contents) => {
  const temporaryPath = `${path}.tmp-${process.pid}-${randomUUID()}`;
  let handle;
  try {
    handle = await open(temporaryPath, "wx", 0o600);
    await handle.writeFile(contents, "utf8");
    await handle.sync();
    await handle.close();
    handle = null;
    await rename(temporaryPath, path);
    await chmod(path, 0o600);
    await syncDirectory(dirname(path));
  } catch (error) {
    if (handle) {
      await handle.close().catch(() => {});
    }
    await unlink(temporaryPath).catch(() => {});
    throw error;
  }
};

const validateEntry = (entry) => {
  if (
    !isPlainObject(entry) ||
    typeof entry.id !== "string" ||
    entry.id.length === 0 ||
    (entry.role !== "user" && entry.role !== "assistant") ||
    !CHECKPOINT_CATEGORIES.has(entry.category) ||
    (entry.timestamp !== null && !isIsoTimestamp(entry.timestamp)) ||
    typeof entry.text !== "string" ||
    entry.text.length === 0 ||
    !isHash(entry.hash) ||
    entry.hash !== createHash("sha256").update(entry.text).digest("hex") ||
    !isCount(entry.index)
  ) {
    throw storageError("invalid_checkpoint");
  }
  return {
    id: entry.id,
    role: entry.role,
    category: entry.category,
    timestamp: entry.timestamp,
    text: entry.text,
    hash: entry.hash,
    index: entry.index
  };
};

const validateCheckpoint = (checkpoint, expected = {}) => {
  if (
    !isPlainObject(checkpoint) ||
    checkpoint.schemaVersion !== 1 ||
    (checkpoint.vendor !== "claude" && checkpoint.vendor !== "codex") ||
    typeof checkpoint.sessionId !== "string" ||
    checkpoint.sessionId.length === 0 ||
    (checkpoint.trigger !== "manual" && checkpoint.trigger !== "auto") ||
    typeof checkpoint.transcriptPath !== "string" ||
    !isAbsolute(checkpoint.transcriptPath) ||
    !isHash(checkpoint.transcriptHash) ||
    !isCount(checkpoint.recordCount) ||
    !isCount(checkpoint.messageCount) ||
    !isIsoTimestamp(checkpoint.capturedAt) ||
    (checkpoint.injectedAt !== undefined && !isIsoTimestamp(checkpoint.injectedAt)) ||
    !Array.isArray(checkpoint.entries) ||
    (expected.vendor !== undefined && checkpoint.vendor !== expected.vendor) ||
    (expected.sessionId !== undefined && checkpoint.sessionId !== expected.sessionId)
  ) {
    throw storageError("invalid_checkpoint");
  }
  return {
    schemaVersion: 1,
    vendor: checkpoint.vendor,
    sessionId: checkpoint.sessionId,
    trigger: checkpoint.trigger,
    transcriptPath: checkpoint.transcriptPath,
    transcriptHash: checkpoint.transcriptHash,
    recordCount: checkpoint.recordCount,
    messageCount: checkpoint.messageCount,
    capturedAt: checkpoint.capturedAt,
    ...(checkpoint.injectedAt !== undefined ? { injectedAt: checkpoint.injectedAt } : {}),
    entries: checkpoint.entries.map(validateEntry)
  };
};

const sanitizeAudit = (event) => {
  const row = {};
  if (event?.schemaVersion === 1) {
    row.schemaVersion = 1;
  }
  for (const [key, value] of Object.entries(event ?? {})) {
    if (Object.hasOwn(AUDIT_ENUMS, key) && AUDIT_ENUMS[key].has(value)) {
      row[key] = value;
    } else if (key === "timestamp" && isIsoTimestamp(value)) {
      row.timestamp = value;
    } else if (HASH_AUDIT_FIELDS.has(key) && isHash(value)) {
      row[key] = value;
    } else if (COUNT_AUDIT_FIELDS.has(key) && Number.isSafeInteger(value) && value >= 0) {
      row[key] = value;
    } else if (BOOLEAN_AUDIT_FIELDS.has(key) && typeof value === "boolean") {
      row[key] = value;
    } else if (NUMBER_AUDIT_FIELDS.has(key) && Number.isFinite(value) && value >= 0 && value <= 1) {
      row[key] = value;
    }
  }
  return row;
};

export const hashSessionId = (sessionId) => sessionHash(requireSessionId(sessionId));

export const writeCheckpoint = async (input, options = {}) => {
  const checkpoint = validateCheckpoint(input);
  const vendor = requireVendor(checkpoint.vendor);
  const sessionId = requireSessionId(checkpoint.sessionId);
  const stateDir = resolveStateDir(options);
  const directory = checkpointDirectory(stateDir, vendor);
  await ensurePrivateDirectory(stateDir);
  await ensurePrivateDirectory(join(stateDir, "checkpoints"));
  await ensurePrivateDirectory(directory);
  await atomicWrite(
    checkpointPath(stateDir, vendor, sessionId),
    `${JSON.stringify(checkpoint)}\n`
  );
  return checkpoint;
};

export const markCheckpointInjected = async ({ vendor, sessionId, injectedAt }, options = {}) => {
  const checkpoint = await readCheckpoint({ vendor, sessionId }, options);
  if (!checkpoint) {
    return null;
  }
  return writeCheckpoint({ ...checkpoint, injectedAt }, options);
};

export const readCheckpoint = async ({ vendor, sessionId }, options = {}) => {
  const stateDir = resolveStateDir(options);
  const path = checkpointPath(stateDir, vendor, sessionId);
  let metadata;
  try {
    metadata = await lstat(path);
  } catch (error) {
    if (error?.code === "ENOENT") {
      return null;
    }
    throw storageError("checkpoint_access_failed");
  }
  if (metadata.isSymbolicLink() || !metadata.isFile() || (metadata.mode & 0o077) !== 0) {
    throw storageError("unsafe_checkpoint_file");
  }
  let handle;
  try {
    handle = await open(path, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
    const openedMetadata = await handle.stat();
    if (
      !openedMetadata.isFile() ||
      (openedMetadata.mode & 0o077) !== 0 ||
      openedMetadata.dev !== metadata.dev ||
      openedMetadata.ino !== metadata.ino
    ) {
      throw storageError("unsafe_checkpoint_file");
    }
    const raw = await handle.readFile("utf8");
    let parsed;
    try {
      parsed = JSON.parse(raw);
    } catch {
      throw storageError("invalid_checkpoint");
    }
    return validateCheckpoint(parsed, { vendor, sessionId });
  } catch (error) {
    if (
      error?.code === "invalid_checkpoint" ||
      error?.code === "unsafe_checkpoint_file"
    ) {
      throw error;
    }
    if (error?.code === "ENOENT") {
      return null;
    }
    if (error?.code === "ELOOP") {
      throw storageError("unsafe_checkpoint_file");
    }
    throw storageError("checkpoint_access_failed");
  } finally {
    if (handle) {
      await handle.close().catch(() => {});
    }
  }
};

export const appendAudit = async (event, options = {}) => {
  const stateDir = resolveStateDir(options);
  await ensurePrivateDirectory(stateDir);
  const path = join(stateDir, "audit.jsonl");
  const handle = await open(path, "a", 0o600);
  try {
    await handle.chmod(0o600);
    await handle.write(`${JSON.stringify(sanitizeAudit(event))}\n`);
    await handle.sync();
  } finally {
    await handle.close();
  }
};

export const isDisabled = async (options = {}) => {
  const stateDir = resolveStateDir(options);
  try {
    await access(join(stateDir, "disabled"), constants.F_OK);
    return true;
  } catch (error) {
    if (error?.code === "ENOENT") {
      return false;
    }
    throw error;
  }
};
