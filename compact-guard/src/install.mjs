import { constants } from "node:fs"
import {
  chmod,
  lstat,
  mkdir,
  open,
  rename,
  unlink
} from "node:fs/promises"
import { randomUUID } from "node:crypto"
import { basename, dirname, isAbsolute, join, resolve } from "node:path"

const TARGETS = [
  { vendor: "claude", relativePath: ".claude/settings.json" },
  { vendor: "codex", relativePath: ".codex/hooks.json" }
]

const EVENT_SPECS = [
  {
    event: "PreCompact",
    eventId: "precompact",
    matcher: "manual|auto",
    statusMessage: "Compact Guard: saving checkpoint"
  },
  {
    event: "PostCompact",
    eventId: "postcompact",
    matcher: "manual|auto",
    statusMessage: "Compact Guard: auditing compaction"
  },
  {
    event: "SessionStart",
    eventId: "sessionstart",
    matcher: "compact",
    statusMessage: "Compact Guard: restoring checkpoint"
  }
]

const VENDORS = new Set(TARGETS.map(target => target.vendor))
const MANAGED_IDS = new Set(TARGETS.flatMap(({ vendor }) => EVENT_SPECS.map(({ eventId }) => `compact-guard/v1/${vendor}/${eventId}`)))
const HANDLER_TYPES_BY_VENDOR = new Map([
  ["claude", new Set(["agent", "command", "http", "mcp_tool", "prompt"])],
  ["codex", new Set(["agent", "command", "prompt"])]
])

const isObject = value => value !== null && typeof value === "object" && !Array.isArray(value)
const isPlainObject = value => isObject(value) && (Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null)
const isNonEmptyString = value => typeof value === "string" && value.trim().length > 0

const createError = (code, message) => Object.assign(new Error(message), { code })

const validateHandler = (handler, vendor) => {
  if (!isObject(handler) || !isNonEmptyString(handler.type)) {
    throw createError("INVALID_STRUCTURE", "Hook handlers must have a non-empty type")
  }
  if (!HANDLER_TYPES_BY_VENDOR.get(vendor)?.has(handler.type)) {
    throw createError("UNSUPPORTED_HANDLER_TYPE", "Hook handler type is unsupported")
  }
  if ("command" in handler && typeof handler.command !== "string") {
    throw createError("INVALID_STRUCTURE", "Hook command fields must be strings")
  }
  if ("timeout" in handler && (typeof handler.timeout !== "number" || !Number.isFinite(handler.timeout) || handler.timeout <= 0)) {
    throw createError("INVALID_STRUCTURE", "Hook timeouts must be positive finite numbers")
  }
  if ("statusMessage" in handler && typeof handler.statusMessage !== "string") {
    throw createError("INVALID_STRUCTURE", "Hook status messages must be strings")
  }
  if ("async" in handler && typeof handler.async !== "boolean") {
    throw createError("INVALID_STRUCTURE", "Hook async fields must be booleans")
  }
  if ("commandWindows" in handler && !isNonEmptyString(handler.commandWindows)) {
    throw createError("INVALID_STRUCTURE", "Hook Windows commands must be non-empty strings")
  }
  if ("args" in handler && (!Array.isArray(handler.args) || handler.args.some(value => typeof value !== "string"))) {
    throw createError("INVALID_STRUCTURE", "Hook arguments must be arrays of strings")
  }
  if ("headers" in handler && (!isPlainObject(handler.headers) || Object.values(handler.headers).some(value => typeof value !== "string"))) {
    throw createError("INVALID_STRUCTURE", "Hook headers must map strings to strings")
  }
  if (vendor === "claude" && "if" in handler && !isNonEmptyString(handler.if)) {
    throw createError("INVALID_STRUCTURE", "Hook conditions must be non-empty strings")
  }
  if (vendor === "claude" && "once" in handler && typeof handler.once !== "boolean") {
    throw createError("INVALID_STRUCTURE", "Hook once fields must be booleans")
  }
  if (handler.type === "command" && !isNonEmptyString(handler.command)) {
    throw createError("INVALID_STRUCTURE", "Command hooks must have a non-empty command")
  }
  if (vendor === "claude" && handler.type === "command" && "asyncRewake" in handler && typeof handler.asyncRewake !== "boolean") {
    throw createError("INVALID_STRUCTURE", "Hook async rewake fields must be booleans")
  }
  if (vendor === "claude" && handler.type === "command" && "shell" in handler && !["bash", "powershell"].includes(handler.shell)) {
    throw createError("INVALID_STRUCTURE", "Hook shells must be bash or powershell")
  }
  if (vendor === "claude" && (handler.type === "prompt" || handler.type === "agent") && !isNonEmptyString(handler.prompt)) {
    throw createError("INVALID_STRUCTURE", "Prompt and agent hooks must have a non-empty prompt")
  }
  if (vendor === "claude" && (handler.type === "prompt" || handler.type === "agent") && "model" in handler && typeof handler.model !== "string") {
    throw createError("INVALID_STRUCTURE", "Prompt and agent hook models must be strings")
  }
  if (vendor === "claude" && handler.type === "http" && !isNonEmptyString(handler.url)) {
    throw createError("INVALID_STRUCTURE", "HTTP hooks must have a non-empty URL")
  }
  if (vendor === "claude" && handler.type === "http" && "allowedEnvVars" in handler
    && (!Array.isArray(handler.allowedEnvVars) || handler.allowedEnvVars.some(value => typeof value !== "string"))) {
    throw createError("INVALID_STRUCTURE", "HTTP hook environment variables must be arrays of strings")
  }
  if (vendor === "claude" && handler.type === "mcp_tool" && (!isNonEmptyString(handler.server) || !isNonEmptyString(handler.tool))) {
    throw createError("INVALID_STRUCTURE", "MCP tool hooks must have a server and tool")
  }
  if (vendor === "claude" && handler.type === "mcp_tool" && "input" in handler && !isPlainObject(handler.input)) {
    throw createError("INVALID_STRUCTURE", "MCP tool hook input must be a plain object")
  }
}

const validateSettings = (settings, vendor) => {
  if (!VENDORS.has(vendor)) {
    throw createError("INVALID_VENDOR", "Vendor is not recognized")
  }
  if (!isObject(settings)) {
    throw createError("INVALID_STRUCTURE", "Settings must be an object")
  }
  if (settings.hooks === undefined) {
    return settings
  }
  if (!isObject(settings.hooks)) {
    throw createError("INVALID_STRUCTURE", "Hooks must be an object")
  }
  for (const groups of Object.values(settings.hooks)) {
    if (!Array.isArray(groups)) {
      throw createError("INVALID_STRUCTURE", "Hook events must contain arrays")
    }
    for (const group of groups) {
      if (!isObject(group) || !Array.isArray(group.hooks)) {
        throw createError("INVALID_STRUCTURE", "Hook groups must contain handler arrays")
      }
      if ("matcher" in group && typeof group.matcher !== "string") {
        throw createError("INVALID_STRUCTURE", "Hook matchers must be strings")
      }
      for (const handler of group.hooks) {
        validateHandler(handler, vendor)
      }
    }
  }
  return settings
}

const escapePattern = value => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")

const commandMentionsMarker = (command, marker) => {
  if (typeof command !== "string") {
    return false
  }
  return new RegExp(`(?:^|[^A-Za-z0-9_./-])${escapePattern(marker)}(?=$|[^A-Za-z0-9_./-])`).test(command)
}

const cloneSettings = (settings, vendor) => structuredClone(validateSettings(settings, vendor))

export const removeHooks = (settings, { commandMarker, command }) => {
  if (!MANAGED_IDS.has(commandMarker)) {
    throw createError("INVALID_MANAGED_ID", "Managed ID is not recognized")
  }
  if (!isManagedCommandBase(command)) {
    throw createError("INVALID_COMMAND", "Command must be a non-empty string")
  }
  const next = cloneSettings(settings, managedIdDetails(commandMarker).vendor)
  const ownership = inspectManagedOwnership(next, { managedId: commandMarker, command })
  if (ownership === null) {
    return next
  }
  const groups = next.hooks[ownership.event]
  groups.splice(ownership.groupIndex, 1)
  if (groups.length === 0) {
    delete next.hooks[ownership.event]
  }
  return next
}

const baseManagedCommand = (command, vendor, managedId) => `${command} --vendor ${vendor} --managed-id ${managedId}`

const createManagedGroup = ({ command, vendor, managedId, spec }) => ({
  matcher: spec.matcher,
  hooks: [{
    type: "command",
    command: baseManagedCommand(command, vendor, managedId),
    timeout: 10,
    statusMessage: spec.statusMessage
  }]
})

const sameKeys = (value, keys) => {
  const actual = Object.keys(value).sort()
  const expected = [...keys].sort()
  return actual.length === expected.length && actual.every((key, index) => key === expected[index])
}

const isCanonicalGroupShape = (group, expected) => {
  if (!sameKeys(group, ["matcher", "hooks"]) || group.matcher !== expected.matcher || group.hooks.length !== 1) {
    return false
  }
  const [handler] = group.hooks
  const [expectedHandler] = expected.hooks
  return sameKeys(handler, ["type", "command", "timeout", "statusMessage"])
    && handler.type === expectedHandler.type
    && handler.timeout === expectedHandler.timeout
    && handler.statusMessage === expectedHandler.statusMessage
}

const parseShellWords = command => {
  if (!isNonEmptyString(command) || command !== command.trim() || /[\0\r\n]/.test(command)) {
    return null
  }
  const words = []
  let index = 0
  while (index < command.length) {
    let word = ""
    let hasSegment = false
    while (index < command.length && !/\s/.test(command[index])) {
      const character = command[index]
      if (character === "'") {
        const end = command.indexOf("'", index + 1)
        if (end === -1) {
          return null
        }
        word += command.slice(index + 1, end)
        hasSegment = true
        index = end + 1
      } else if (character === '"') {
        const end = command.indexOf('"', index + 1)
        if (end === -1 || command.slice(index + 1, end) !== "'") {
          return null
        }
        word += "'"
        hasSegment = true
        index = end + 1
      } else {
        if (/[#;&|<>`$(){}\\*?[\]!~]/.test(character)) {
          return null
        }
        word += character
        hasSegment = true
        index += 1
      }
    }
    if (!hasSegment) {
      return null
    }
    words.push(word)
    if (index < command.length) {
      while (index < command.length && /\s/.test(command[index])) {
        index += 1
      }
      if (index === command.length) {
        return null
      }
    }
  }
  return words
}

const isNodeExecutable = value => isAbsolute(value) && basename(value) === "node"

const isCompactGuardScript = value => isAbsolute(value) && value.endsWith("/bin/compact-guard.mjs")

const isManagedCommandBase = command => {
  const words = parseShellWords(command)
  return words?.length === 2 && isNodeExecutable(words[0]) && isCompactGuardScript(words[1])
}

const isOwnedManagedCommand = (command, { vendor, managedId }) => {
  const words = parseShellWords(command)
  return words?.length === 6
    && isNodeExecutable(words[0])
    && isCompactGuardScript(words[1])
    && words[2] === "--vendor"
    && words[3] === vendor
    && words[4] === "--managed-id"
    && words[5] === managedId
}

const managedIdDetails = managedId => {
  for (const { vendor } of TARGETS) {
    for (const spec of EVENT_SPECS) {
      if (managedId === `compact-guard/v1/${vendor}/${spec.eventId}`) {
        return { vendor, spec }
      }
    }
  }
  return null
}

const inspectManagedOwnership = (settings, { managedId, command }) => {
  const details = managedIdDetails(managedId)
  const matches = []
  for (const [eventName, groups] of Object.entries(settings.hooks ?? {})) {
    for (const [groupIndex, group] of groups.entries()) {
      for (const handler of group.hooks) {
        if (commandMentionsMarker(handler.command, managedId)) {
          matches.push({ eventName, groupIndex, group })
        }
      }
    }
  }
  if (matches.length === 0) {
    return null
  }
  const expected = createManagedGroup({
    command,
    vendor: details.vendor,
    managedId,
    spec: details.spec
  })
  const handler = matches[0]?.group.hooks[0]
  if (matches.length !== 1
    || matches[0].eventName !== details.spec.event
    || !isCanonicalGroupShape(matches[0].group, expected)
    || !isOwnedManagedCommand(handler?.command, { vendor: details.vendor, managedId })) {
    throw createError("MANAGED_ID_COLLISION", "Managed ID ownership is ambiguous")
  }
  return {
    event: matches[0].eventName,
    groupIndex: matches[0].groupIndex,
    current: handler.command === expected.hooks[0].command
  }
}

const assertNoForeignManagedIds = (settings, vendor) => {
  for (const managedId of MANAGED_IDS) {
    if (managedIdDetails(managedId).vendor === vendor) {
      continue
    }
    for (const groups of Object.values(settings.hooks ?? {})) {
      for (const group of groups) {
        if (group.hooks.some(handler => commandMentionsMarker(handler.command, managedId))) {
          throw createError("MANAGED_ID_COLLISION", "Managed ID belongs to another target")
        }
      }
    }
  }
}

export const mergeHooks = (settings, { vendor, command }) => {
  if (!VENDORS.has(vendor)) {
    throw createError("INVALID_VENDOR", "Vendor is not recognized")
  }
  if (!isManagedCommandBase(command)) {
    throw createError("INVALID_COMMAND", "Command must be a non-empty string")
  }
  let next = cloneSettings(settings, vendor)
  assertNoForeignManagedIds(next, vendor)
  for (const spec of EVENT_SPECS) {
    const managedId = `compact-guard/v1/${vendor}/${spec.eventId}`
    const managedGroup = createManagedGroup({ command, vendor, managedId, spec })
    const ownership = inspectManagedOwnership(next, { managedId, command })
    if (ownership?.current === true) {
      continue
    }
    next.hooks ??= {}
    next.hooks[spec.event] ??= []
    if (ownership === null) {
      next.hooks[spec.event].push(managedGroup)
    } else {
      next.hooks[ownership.event][ownership.groupIndex] = managedGroup
    }
  }
  return next
}

const shellQuote = value => `'${value.replaceAll("'", `'"'"'`)}'`

const commandForProject = projectDir => `${shellQuote(process.execPath)} ${shellQuote(resolve(projectDir, "bin", "compact-guard.mjs"))}`

const normalizeNow = now => {
  const value = typeof now === "function" ? now() : now
  const date = value instanceof Date ? value : new Date(value ?? Date.now())
  if (Number.isNaN(date.getTime())) {
    throw createError("INVALID_TIME", "Install time is invalid")
  }
  return date
}

const timestampName = date => date.toISOString().replaceAll(":", "-").replaceAll(".", "-")

const parseSettings = (raw, vendor) => {
  let settings
  try {
    settings = JSON.parse(raw)
  } catch {
    throw createError("INVALID_JSON", "Settings JSON is invalid")
  }
  return validateSettings(settings, vendor)
}

const readRegularFile = async targetPath => {
  let metadata
  try {
    metadata = await lstat(targetPath)
  } catch (error) {
    if (error.code === "ENOENT") {
      return null
    }
    throw error
  }
  if (!metadata.isFile()) {
    throw createError("UNSUPPORTED_TARGET_TYPE", "Settings target must be a regular file")
  }
  let handle
  try {
    handle = await open(targetPath, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0))
    const openedMetadata = await handle.stat()
    if (!openedMetadata.isFile()) {
      throw createError("UNSUPPORTED_TARGET_TYPE", "Settings target must remain a regular file")
    }
    const raw = await handle.readFile("utf8")
    return { raw, mode: openedMetadata.mode & 0o777 }
  } catch (error) {
    if (error.code === "ELOOP" || error.code === "EISDIR") {
      throw createError("UNSUPPORTED_TARGET_TYPE", "Settings target type changed during read")
    }
    throw error
  } finally {
    await handle?.close().catch(() => {})
  }
}

const readTarget = async (targetPath, vendor) => {
  const target = await readRegularFile(targetPath)
  if (target === null) {
    return { exists: false, raw: null, mode: 0o600, settings: {} }
  }
  return {
    exists: true,
    raw: target.raw,
    mode: target.mode,
    settings: parseSettings(target.raw, vendor)
  }
}

const readCurrentRaw = async targetPath => {
  const target = await readRegularFile(targetPath)
  return target?.raw ?? null
}

const assertUnchanged = async (targetPath, expectedRaw) => {
  const currentRaw = await readCurrentRaw(targetPath)
  if (currentRaw !== expectedRaw) {
    throw createError("CONCURRENT_MODIFICATION", "Settings changed during installation")
  }
}

const syncDirectory = async directory => {
  const handle = await open(directory, constants.O_RDONLY)
  try {
    await handle.sync()
  } finally {
    await handle.close()
  }
}

const atomicWrite = async ({ targetPath, content, mode, expectedRaw, beforeRename }) => {
  const directory = dirname(targetPath)
  await mkdir(directory, { recursive: true, mode: 0o700 })
  const temporaryPath = join(directory, `.${basename(targetPath)}.compact-guard-${process.pid}-${randomUUID()}.tmp`)
  let handle
  try {
    handle = await open(temporaryPath, "wx", mode)
    await handle.writeFile(content, "utf8")
    await handle.sync()
    await handle.chmod(mode)
    await handle.close()
    handle = undefined
    await assertUnchanged(targetPath, expectedRaw)
    await beforeRename?.()
    await rename(temporaryPath, targetPath)
    await syncDirectory(directory)
  } catch (error) {
    if (handle !== undefined) {
      await handle.close().catch(() => {})
    }
    await unlink(temporaryPath).catch(() => {})
    throw error
  }
}

const writeBackup = async ({ homeDir, vendor, raw, date }) => {
  const directory = join(homeDir, ".compact-guard", "backups", timestampName(date))
  await mkdir(directory, { recursive: true, mode: 0o700 })
  await chmod(join(homeDir, ".compact-guard"), 0o700)
  await chmod(join(homeDir, ".compact-guard", "backups"), 0o700)
  await chmod(directory, 0o700)
  const baseName = `${vendor}.json`
  for (let suffix = 0; suffix < 1000; suffix += 1) {
    const backupPath = join(directory, suffix === 0 ? baseName : `${vendor}.${suffix}.json`)
    let handle
    try {
      handle = await open(backupPath, "wx", 0o600)
      await handle.writeFile(raw, "utf8")
      await handle.sync()
      await handle.chmod(0o600)
      await handle.close()
      await syncDirectory(directory)
      return
    } catch (error) {
      if (handle !== undefined) {
        await handle.close().catch(() => {})
      }
      if (error.code !== "EEXIST") {
        throw error
      }
    }
  }
  throw createError("BACKUP_LIMIT", "Backup name limit exceeded")
}

const serialize = settings => `${JSON.stringify(settings, null, 2)}\n`

const contentFreeErrorCode = error => {
  const allowed = new Set([
    "BACKUP_LIMIT",
    "CONCURRENT_MODIFICATION",
    "EACCES",
    "ENOENT",
    "ENOSPC",
    "INVALID_JSON",
    "INVALID_STRUCTURE",
    "MANAGED_ID_COLLISION",
    "UNSUPPORTED_HANDLER_TYPE",
    "UNSUPPORTED_TARGET_TYPE"
  ])
  return allowed.has(error.code) ? error.code : "IO_ERROR"
}

const installTarget = async ({ homeDir, projectDir, target, date, beforeRename }) => {
  const targetPath = join(homeDir, target.relativePath)
  let backupCreated = false
  try {
    const current = await readTarget(targetPath, target.vendor)
    const merged = mergeHooks(current.settings, {
      vendor: target.vendor,
      command: commandForProject(projectDir)
    })
    if (JSON.stringify(merged) === JSON.stringify(current.settings)) {
      return { vendor: target.vendor, status: "unchanged", backupCreated: false }
    }
    await assertUnchanged(targetPath, current.raw)
    if (current.exists) {
      await writeBackup({ homeDir, vendor: target.vendor, raw: current.raw, date })
      backupCreated = true
    }
    await atomicWrite({
      targetPath,
      content: serialize(merged),
      mode: current.mode,
      expectedRaw: current.raw,
      beforeRename: () => beforeRename?.({ vendor: target.vendor })
    })
    return { vendor: target.vendor, status: "updated", backupCreated: current.exists }
  } catch (error) {
    return {
      vendor: target.vendor,
      status: "failed",
      backupCreated,
      errorCode: contentFreeErrorCode(error)
    }
  }
}

const uninstallTarget = async ({ homeDir, projectDir, target, beforeRename }) => {
  const targetPath = join(homeDir, target.relativePath)
  try {
    const current = await readTarget(targetPath, target.vendor)
    if (!current.exists) {
      return { vendor: target.vendor, status: "unchanged" }
    }
    let next = current.settings
    const command = commandForProject(projectDir)
    assertNoForeignManagedIds(next, target.vendor)
    for (const managedId of managedIdsForVendor(target.vendor)) {
      next = removeHooks(next, { commandMarker: managedId, command })
    }
    if (JSON.stringify(next) === JSON.stringify(current.settings)) {
      return { vendor: target.vendor, status: "unchanged" }
    }
    await atomicWrite({
      targetPath,
      content: serialize(next),
      mode: current.mode,
      expectedRaw: current.raw,
      beforeRename: () => beforeRename?.({ vendor: target.vendor })
    })
    return { vendor: target.vendor, status: "updated" }
  } catch (error) {
    return {
      vendor: target.vendor,
      status: "failed",
      errorCode: contentFreeErrorCode(error)
    }
  }
}

const managedIdsForVendor = vendor => EVENT_SPECS.map(({ eventId }) => `compact-guard/v1/${vendor}/${eventId}`)

const summarizeStatus = (operation, targets) => {
  const failed = targets.filter(target => target.status === "failed").length
  const updated = targets.filter(target => target.status === "updated").length
  if (failed === targets.length) {
    return "failed"
  }
  if (failed > 0) {
    return "partial"
  }
  if (updated === 0) {
    return "unchanged"
  }
  return operation === "install" ? "installed" : "uninstalled"
}

export const install = async ({ homeDir, projectDir, now = () => new Date(), beforeRename }) => {
  const date = normalizeNow(now)
  const targets = []
  for (const target of TARGETS) {
    targets.push(await installTarget({ homeDir, projectDir, target, date, beforeRename }))
  }
  return {
    operation: "install",
    status: summarizeStatus("install", targets),
    targets
  }
}

export const uninstall = async ({ homeDir, projectDir, beforeRename }) => {
  const targets = []
  for (const target of TARGETS) {
    targets.push(await uninstallTarget({ homeDir, projectDir, target, beforeRename }))
  }
  return {
    operation: "uninstall",
    status: summarizeStatus("uninstall", targets),
    targets
  }
}
