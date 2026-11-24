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

const DEFAULT_LOCK_STALE_MS = 10_000;
const DEFAULT_LOCK_TIMEOUT_MS = 5_000;
const LOCK_RETRY_MS = 10;

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const isWin32TransientError = (error) =>
  process.platform === "win32" && (error?.code === "EPERM" || error?.code === "EBUSY");

const isRetryableLockOpenError = (error) =>
  error?.code === "EEXIST" || isWin32TransientError(error);

const safeLstat = async (path) => {
  try {
    return await lstat(path);
  } catch (error) {
    if (error?.code === "ENOENT") {
      return null;
    }
    if (isWin32TransientError(error)) {
      return undefined;
    }
    throw error;
  }
};

const releaseOwnedLock = async (path, token, lockStat) => {
  try {
    const currentStat = await lstat(path);
    if (
      currentStat.isSymbolicLink() ||
      !currentStat.isFile() ||
      currentStat.dev !== lockStat.dev ||
      currentStat.ino !== lockStat.ino
    ) {
      return;
    }
    const flags =
      constants.O_RDONLY |
      (constants.O_NOFOLLOW ?? 0) |
      (constants.O_NONBLOCK ?? 0);
    let matches = false;
    const handle = await open(path, flags);
    try {
      const openedStat = await handle.stat();
      if (
        openedStat.isFile() &&
        openedStat.dev === lockStat.dev &&
        openedStat.ino === lockStat.ino
      ) {
        const maxBytes = Buffer.byteLength(token, "utf8") + 1;
        const buffer = Buffer.alloc(maxBytes);
        let totalRead = 0;
        while (totalRead < maxBytes) {
          const { bytesRead } = await handle.read(buffer, totalRead, maxBytes - totalRead, totalRead);
          if (bytesRead === 0) {
            break;
          }
          totalRead += bytesRead;
        }
        matches = buffer.subarray(0, totalRead).toString("utf8") === token;
      }
    } finally {
      await handle.close().catch(() => {});
    }
    if (matches) {
      await unlink(path).catch(() => {});
    }
  } catch {
    // Lock file already removed, replaced, or unreadable.
  }
};

const tryReclaimStaleLock = async (lockPath, observedMetadata, staleMs, deadline) => {
  const reclaimPath = `${lockPath}.reclaim`;
  const reclaimToken = `${randomUUID()}\n`;
  let reclaimStat;

  while (true) {
    if (Date.now() >= deadline) {
      throw storageError("checkpoint_lock_timeout");
    }
    let reclaimHandle;
    let createdReclaim = false;
    try {
      reclaimHandle = await open(reclaimPath, "wx", 0o600);
      createdReclaim = true;
      await reclaimHandle.writeFile(reclaimToken, "utf8");
      reclaimStat = await reclaimHandle.stat();
      const openedReclaim = reclaimHandle;
      reclaimHandle = null;
      await openedReclaim.close();
      break;
    } catch (error) {
      if (reclaimHandle) {
        await reclaimHandle.close().catch(() => {});
      }
      if (createdReclaim) {
        await unlink(reclaimPath).catch(() => {});
        throw error;
      }
      if (!isRetryableLockOpenError(error)) {
        throw error;
      }
      const reclaimMeta = await safeLstat(reclaimPath);
      if (reclaimMeta === undefined) {
        await delay(LOCK_RETRY_MS);
        continue;
      }
      if (reclaimMeta === null) {
        return false;
      }
      if (!reclaimMeta.isFile() && !reclaimMeta.isSymbolicLink()) {
        throw storageError("unsafe_checkpoint_file");
      }
      if (reclaimMeta.isSymbolicLink() || Date.now() - reclaimMeta.mtimeMs >= staleMs) {
        let unlinked = false;
        try {
          await unlink(reclaimPath);
          unlinked = true;
        } catch (unlinkError) {
          if (unlinkError?.code === "ENOENT") {
            unlinked = true;
          }
        }
        if (!unlinked) {
          await delay(LOCK_RETRY_MS);
        }
        continue;
      }
      return false;
    }
  }

  try {
    const current = await safeLstat(lockPath);
    if (current === undefined) {
      return false;
    }
    if (current === null) {
      return true;
    }
    if (!current.isFile() && !current.isSymbolicLink()) {
      throw storageError("unsafe_checkpoint_file");
    }
    const sameIdentity =
      current.dev === observedMetadata.dev &&
      current.ino === observedMetadata.ino;
    const shouldUnlink =
      current.isSymbolicLink() ||
      (sameIdentity &&
        current.mtimeMs === observedMetadata.mtimeMs &&
        Date.now() - current.mtimeMs >= staleMs);
    if (!shouldUnlink) {
      return false;
    }
    try {
      await unlink(lockPath);
      return true;
    } catch (unlinkError) {
      return unlinkError?.code === "ENOENT";
    }
  } finally {
    await releaseOwnedLock(reclaimPath, reclaimToken, reclaimStat);
  }
};

const withCheckpointLock = async ({ vendor, sessionId }, options, callback) => {
  const stateDir = resolveStateDir(options);
  const directory = checkpointDirectory(stateDir, vendor);
  await ensurePrivateDirectory(stateDir);
  await ensurePrivateDirectory(join(stateDir, "checkpoints"));
  await ensurePrivateDirectory(directory);

  const lockPath = `${checkpointPath(stateDir, vendor, sessionId)}.lock`;
  const token = `${randomUUID()}\n`;
  const staleMs = options?.lockStaleMs ?? DEFAULT_LOCK_STALE_MS;
  const timeoutMs = options?.lockTimeoutMs ?? DEFAULT_LOCK_TIMEOUT_MS;
  const deadline = Date.now() + timeoutMs;
  let lockStat;
  let acquiredAt;

  while (true) {
    let lockHandle;
    let created = false;
    try {
      lockHandle = await open(lockPath, "wx", 0o600);
      created = true;
      await lockHandle.writeFile(token, "utf8");
      lockStat = await lockHandle.stat();
      acquiredAt = Date.now();
      const opened = lockHandle;
      lockHandle = null;
      await opened.close();
      break;
    } catch (error) {
      if (lockHandle) {
        await lockHandle.close().catch(() => {});
      }
      if (created) {
        await unlink(lockPath).catch(() => {});
        throw error;
      }
      if (!isRetryableLockOpenError(error)) {
        throw error;
      }
      if (Date.now() >= deadline) {
        throw storageError("checkpoint_lock_timeout");
      }
      const metadata = await safeLstat(lockPath);
      if (metadata === undefined) {
        await delay(LOCK_RETRY_MS);
        continue;
      }
      if (metadata === null) {
        if (error?.code !== "EEXIST") {
          await delay(LOCK_RETRY_MS);
        }
        continue;
      }
      if (!metadata.isFile() && !metadata.isSymbolicLink()) {
        throw storageError("unsafe_checkpoint_file");
      }
      if (metadata.isSymbolicLink() || Date.now() - metadata.mtimeMs >= staleMs) {
        const reclaimed = await tryReclaimStaleLock(lockPath, metadata, staleMs, deadline);
        if (reclaimed) {
          continue;
        }
      }
      await delay(LOCK_RETRY_MS);
    }
  }

  try {
    return await callback({ acquiredAt });
  } finally {
    await releaseOwnedLock(lockPath, token, lockStat);
  }
};

const writeCheckpointUnlocked = async (input, options = {}) => {
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

export const writeCheckpoint = async (input, options = {}) => {
  const checkpoint = validateCheckpoint(input);
  return withCheckpointLock(
    { vendor: checkpoint.vendor, sessionId: checkpoint.sessionId },
    options,
    () => writeCheckpointUnlocked(checkpoint, options)
  );
};

export const markCheckpointInjected = async (
  { vendor, sessionId, injectedAt, expectedCapturedAt, expectedTranscriptHash },
  options = {}
) => {
  requireVendor(vendor);
  requireSessionId(sessionId);
  return withCheckpointLock({ vendor, sessionId }, options, async () => {
    const checkpoint = await readCheckpoint({ vendor, sessionId }, options);
    if (!checkpoint || typeof checkpoint.injectedAt === "string") {
      return null;
    }
    if (expectedCapturedAt !== undefined && checkpoint.capturedAt !== expectedCapturedAt) {
      return null;
    }
    if (expectedTranscriptHash !== undefined && checkpoint.transcriptHash !== expectedTranscriptHash) {
      return null;
    }
    return writeCheckpointUnlocked({ ...checkpoint, injectedAt }, options);
  });
};

export const claimCheckpointInjection = async (
  { vendor, sessionId, injectedAt },
  options = {}
) => {
  requireVendor(vendor);
  requireSessionId(sessionId);
  return withCheckpointLock({ vendor, sessionId }, options, async () => {
    const checkpoint = await readCheckpoint({ vendor, sessionId }, options);
    if (!checkpoint) {
      return { status: "missing", checkpoint: null };
    }
    if (typeof checkpoint.injectedAt === "string") {
      return { status: "already_injected", checkpoint };
    }
    const updated = await writeCheckpointUnlocked({ ...checkpoint, injectedAt }, options);
    return { status: "claimed", checkpoint: updated };
  });
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
  const metadata = await lstat(path).catch((error) => {
    if (error?.code === "ENOENT") {
      return null;
    }
    throw error;
  });
  if (metadata && (metadata.isSymbolicLink() || !metadata.isFile())) {
    throw storageError("unsafe_audit_file");
  }
  const flags = constants.O_WRONLY | constants.O_CREAT | constants.O_APPEND | (constants.O_NOFOLLOW ?? 0);
  const handle = await open(path, flags, 0o600);
  try {
    const openedMetadata = await handle.stat();
    if (!openedMetadata.isFile()) {
      throw storageError("unsafe_audit_file");
    }
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
