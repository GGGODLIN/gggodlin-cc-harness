import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { createInterface } from "node:readline";

const hasText = (text) => typeof text === "string" && text.trim().length > 0;
const isObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);

export const SUBAGENT_TRANSCRIPT_ERROR_CODE = "subagent_transcript";

const subagentTranscriptError = () => Object.assign(
  new Error(SUBAGENT_TRANSCRIPT_ERROR_CODE),
  { code: SUBAGENT_TRANSCRIPT_ERROR_CODE }
);

const createClassification = (vendor) => ({
  vendor,
  codexSubagent: false,
  codexSessionMetaCount: 0,
  claudeConversationCount: 0,
  claudeMainConversationCount: 0,
  originator: null
});

const observeClassification = (classification, record) => {
  if (!isObject(record)) {
    return;
  }
  if (classification.vendor === "claude") {
    if (record.type === "user" || record.type === "assistant") {
      classification.claudeConversationCount += 1;
      if (record.isSidechain !== true) {
        classification.claudeMainConversationCount += 1;
      }
    }
    return;
  }
  if (record.type !== "session_meta" || !isObject(record.payload)) {
    return;
  }
  classification.codexSessionMetaCount += 1;
  classification.originator ??= typeof record.payload.originator === "string"
    ? record.payload.originator
    : null;
  const hasSubagentSource = isObject(record.payload.source) &&
    Object.hasOwn(record.payload.source, "subagent");
  const hasParentThread = typeof record.payload.parent_thread_id === "string" &&
    record.payload.parent_thread_id.trim().length > 0;
  classification.codexSubagent ||= hasSubagentSource || hasParentThread;
};

const finishClassification = (classification) => {
  const isSubagent = classification.vendor === "claude"
    ? classification.claudeConversationCount > 0 &&
      classification.claudeMainConversationCount === 0
    : classification.codexSubagent;
  const isRoot = classification.vendor === "claude"
    ? classification.claudeMainConversationCount > 0
    : classification.codexSessionMetaCount > 0 && !classification.codexSubagent;
  return {
    isSubagent,
    isRoot,
    originator: classification.originator
  };
};

const requireVendor = (vendor) => {
  if (vendor !== "claude" && vendor !== "codex") {
    throw new Error(`Unsupported transcript vendor: ${vendor}`);
  }
};

const textBlocks = (content, type) =>
  Array.isArray(content)
    ? content
        .filter((block) => block?.type === type && hasText(block.text))
        .map((block) => block.text)
    : [];

// 背景任務完成通知以 user role 寫進 transcript；不排除會被當成使用者發言放進恢復內容。
// 只認來源欄位、不看文字開頭，使用者自己打出標籤字樣時才不會被誤刪。
const claudeRecordIsExcluded = (record) =>
  record.isSidechain === true ||
  record.isMeta === true ||
  record.isCompactSummary === true ||
  (record.type === "user" &&
    (record.promptSource === "system" || record.turnOrigin === "task_notification")) ||
  record.sourceToolUseID != null ||
  record.sourceToolAssistantUUID != null ||
  record.toolUseResult != null;

const claudeSourceId = (record, recordIndex) =>
  record.message?.id ?? record.requestId ?? record.uuid ?? `claude:${recordIndex}`;

const claudeUserText = (content) => {
  if (hasText(content)) {
    return content;
  }
  if (!Array.isArray(content) || content.some((block) => block?.type === "tool_result")) {
    return null;
  }
  const texts = textBlocks(content, "text");
  return texts.length > 0 ? texts.join("\n\n") : null;
};

const collectClaudeRecord = (record, recordIndex, collected, assistantGroups) => {
  if (claudeRecordIsExcluded(record)) {
    return;
  }

  const userText = claudeUserText(record.message?.content);
  if (record.type === "user" && record.message?.role === "user" && userText != null) {
    collected.push({
      id: record.uuid ?? record.message.id ?? record.requestId ?? `claude:${recordIndex}`,
      role: "user",
      timestamp: record.timestamp ?? null,
      text: userText,
      sourceIndex: recordIndex
    });
    return;
  }

  if (record.type !== "assistant" || record.message?.role !== "assistant") {
    return;
  }

  const texts = textBlocks(record.message.content, "text");
  if (texts.length === 0) {
    return;
  }

  const id = claudeSourceId(record, recordIndex);
  const existing = assistantGroups.get(id);
  if (existing) {
    existing.texts.push(...texts);
    return;
  }

  const entry = {
    id,
    role: "assistant",
    timestamp: record.timestamp ?? null,
    texts: [...texts],
    sourceIndex: recordIndex
  };
  assistantGroups.set(id, entry);
  collected.push(entry);
};

const collectCodexRecord = (record, recordIndex, collected) => {
  const payload = record.payload;
  if (
    record.type === "event_msg" &&
    payload?.type === "user_message" &&
    hasText(payload.message)
  ) {
    collected.push({
      id: payload.id ?? record.id ?? `codex:user:${recordIndex}`,
      role: "user",
      timestamp: record.timestamp ?? payload.timestamp ?? null,
      text: payload.message,
      sourceIndex: recordIndex
    });
    return;
  }
  if (
    record.type !== "response_item" ||
    payload?.type !== "message" ||
    payload.role !== "assistant"
  ) {
    return;
  }

  const texts = textBlocks(payload.content, "output_text");
  if (texts.length === 0) {
    return;
  }

  collected.push({
    id: payload.id ?? record.id ?? `codex:${recordIndex}`,
    role: "assistant",
    timestamp: record.timestamp ?? payload.timestamp ?? null,
    text: texts.join("\n\n"),
    sourceIndex: recordIndex
  });
};

const normalizeMessages = (collected) =>
  collected
    .sort((left, right) => left.sourceIndex - right.sourceIndex)
    .map((entry, index) => ({
      id: entry.id,
      role: entry.role,
      timestamp: entry.timestamp,
      text: entry.text ?? entry.texts.join("\n\n"),
      index
    }));

export const inspectTranscript = async ({ vendor, transcriptPath }) => {
  requireVendor(vendor);
  const input = createReadStream(transcriptPath);
  const lines = createInterface({ input, crlfDelay: Infinity });
  const classification = createClassification(vendor);
  for await (const line of lines) {
    try {
      observeClassification(classification, JSON.parse(line));
    } catch {
      continue;
    }
  }
  return finishClassification(classification);
};

export const extractMessages = async ({ vendor, transcriptPath }) => {
  requireVendor(vendor);

  const input = createReadStream(transcriptPath);
  const hash = createHash("sha256");
  let endsWithLineBreak = false;
  input.on("data", (chunk) => {
    hash.update(chunk);
    endsWithLineBreak = chunk.at(-1) === 10;
  });

  const lines = createInterface({ input, crlfDelay: Infinity });
  const collected = [];
  const assistantGroups = new Map();
  const classification = createClassification(vendor);
  let recordCount = 0;
  let finalLineWasMalformed = false;

  for await (const line of lines) {
    const recordIndex = recordCount;
    recordCount += 1;
    finalLineWasMalformed = false;
    try {
      const record = JSON.parse(line);
      observeClassification(classification, record);
      if (vendor === "claude") {
        collectClaudeRecord(record, recordIndex, collected, assistantGroups);
      } else {
        collectCodexRecord(record, recordIndex, collected);
      }
    } catch {
      finalLineWasMalformed = true;
    }
  }

  if (finalLineWasMalformed && !endsWithLineBreak) {
    recordCount -= 1;
  }

  if (finishClassification(classification).isSubagent) {
    throw subagentTranscriptError();
  }
  const messages = normalizeMessages(collected);
  if (messages.length === 0) {
    throw new Error("No valid conversation messages found");
  }

  return {
    messages,
    transcriptHash: hash.digest("hex"),
    recordCount
  };
};
