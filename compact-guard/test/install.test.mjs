import assert from "node:assert/strict"
import { execFile } from "node:child_process"
import { lstat, mkdtemp, mkdir, readFile, readdir, stat, symlink, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join, resolve } from "node:path"
import { promisify } from "node:util"
import test from "node:test"
import {
  install,
  mergeHooks,
  removeHooks,
  uninstall
} from "../src/install.mjs"

const fixedNow = () => new Date("2026-07-16T03:04:05.678Z")
const execFileAsync = promisify(execFile)
const baseCommand = "/absolute/node /absolute/project/bin/compact-guard.mjs"
const quoteShellWord = value => `'${value.replaceAll("'", `'"'"'`)}'`
const oldBaseCommand = `${quoteShellWord("/opt/old-node/bin/node")} ${quoteShellWord("/opt/old user's project/bin/compact-guard.mjs")}`

const managedIds = vendor => [
  `compact-guard/v1/${vendor}/precompact`,
  `compact-guard/v1/${vendor}/postcompact`,
  `compact-guard/v1/${vendor}/sessionstart`
]

const commandsById = settings => Object.values(settings.hooks ?? {})
  .flatMap(groups => groups)
  .flatMap(group => group.hooks ?? [])
  .map(handler => handler.command)
  .filter(Boolean)

const readJson = async filePath => JSON.parse(await readFile(filePath, "utf8"))

const createHome = async ({ claude = {}, codex = {} } = {}) => {
  const homeDir = await mkdtemp(join(tmpdir(), "compact-guard-install-"))
  await mkdir(join(homeDir, ".claude"), { recursive: true })
  await mkdir(join(homeDir, ".codex"), { recursive: true })
  await writeFile(join(homeDir, ".claude", "settings.json"), `${JSON.stringify(claude, null, 2)}\n`, { mode: 0o640 })
  await writeFile(join(homeDir, ".codex", "hooks.json"), `${JSON.stringify(codex, null, 2)}\n`, { mode: 0o604 })
  return homeDir
}

test("mergeHooks preserves existing groups and adds the three independent managed groups", () => {
  const existingGroup = {
    matcher: "manual",
    custom: { keep: ["byte", "equivalent"] },
    hooks: [{ type: "command", command: "/third-party --managed-id compact-guard/v1/claude/precompact-extra" }]
  }
  const settings = {
    customRoot: { keep: true },
    hooks: {
      PreCompact: [existingGroup],
      Stop: [{ hooks: [{ type: "command", command: "/stop" }] }]
    }
  }
  const original = structuredClone(settings)
  const merged = mergeHooks(settings, {
    vendor: "claude",
    command: "/absolute/node /absolute/project/bin/compact-guard.mjs"
  })

  assert.deepEqual(settings, original)
  assert.deepEqual(merged.customRoot, original.customRoot)
  assert.deepEqual(merged.hooks.Stop, original.hooks.Stop)
  assert.deepEqual(merged.hooks.PreCompact[0], existingGroup)
  assert.equal(merged.hooks.PreCompact.length, 2)
  assert.equal(merged.hooks.PostCompact.length, 1)
  assert.equal(merged.hooks.SessionStart.length, 1)
  assert.equal(merged.hooks.PreCompact.at(-1).matcher, "manual|auto")
  assert.equal(merged.hooks.PostCompact.at(-1).matcher, "manual|auto")
  assert.equal(merged.hooks.SessionStart.at(-1).matcher, "compact")
})

test("mergeHooks is idempotent and emits exact managed markers with stable handler fields", () => {
  const options = {
    vendor: "codex",
    command: baseCommand
  }
  const once = mergeHooks({}, options)
  const twice = mergeHooks(once, options)
  const commands = commandsById(twice)

  assert.deepEqual(twice, once)
  assert.equal(commands.length, 3)
  for (const id of managedIds("codex")) {
    assert.equal(commands.filter(command => command.includes(`--managed-id ${id}`)).length, 1)
  }
  for (const groups of Object.values(twice.hooks)) {
    for (const group of groups) {
      for (const handler of group.hooks) {
        assert.equal(handler.timeout, 10)
        assert.match(handler.statusMessage, /^Compact Guard: /)
      }
    }
  }
})

test("removeHooks removes only an exact managed handler and prunes only newly empty containers", () => {
  const exact = "compact-guard/v1/claude/precompact"
  const settings = mergeHooks({
    hooks: {
      PreCompact: [
        {
          matcher: "manual",
          hooks: [{ type: "command", command: `/keep --managed-id ${exact}-extra` }]
        }
      ],
      Stop: []
    }
  }, { vendor: "claude", command: baseCommand })
  const removed = removeHooks(settings, { commandMarker: exact, command: baseCommand })

  assert.equal(removed.hooks.PreCompact.length, 1)
  assert.equal(removed.hooks.PreCompact[0].hooks[0].command, `/keep --managed-id ${exact}-extra`)
  assert.equal(removed.hooks.PostCompact.length, 1)
  assert.deepEqual(removed.hooks.Stop, [])
  assert.equal(commandsById(settings).length, 4)
})

test("settings validation rejects malformed groups and known handler shapes", () => {
  const invalidGroups = [
    { matcher: {}, hooks: [{ type: "command", command: "/valid" }] },
    { hooks: [{}] },
    { hooks: [{ type: "command", command: {} }] },
    { hooks: [{ type: "command", command: " " }] },
    { hooks: [{ type: "command", command: "/valid", timeout: {} }] },
    { hooks: [{ type: "command", command: "/valid", timeout: 0 }] },
    { hooks: [{ type: "command", command: "/valid", timeout: -1 }] },
    { hooks: [{ type: "command", command: "/valid", timeout: Number.POSITIVE_INFINITY }] },
    { hooks: [{ type: "command", command: "/valid", timeout: Number.NaN }] },
    { hooks: [{ type: "command", command: "/valid", statusMessage: {} }] },
    { hooks: [{ type: "command", command: "/valid", async: "true" }] },
    { hooks: [{ type: "command", command: "/valid", commandWindows: {} }] },
    { hooks: [{ type: "command", command: "/valid", args: ["valid", {}] }] },
    { hooks: [{ type: "http", url: "https://example.com", headers: { Authorization: {} } }] },
    { hooks: [{ type: "prompt" }] },
    { hooks: [{ type: "agent", prompt: " " }] },
    { hooks: [{ type: "http" }] },
    { hooks: [{ type: "mcp_tool", server: "server-only" }] }
  ]

  for (const group of invalidGroups) {
    assert.throws(
      () => mergeHooks({ hooks: { Stop: [group] } }, { vendor: "claude", command: baseCommand }),
      error => error.code === "INVALID_STRUCTURE"
    )
  }

  assert.doesNotThrow(() => mergeHooks({
    hooks: {
      Stop: [{
        matcher: "",
        hooks: [
          { type: "prompt", prompt: "judge", extra: true },
          { type: "agent", prompt: "verify" },
          { type: "command", command: "/valid", async: false, commandWindows: "C:\\valid.exe", args: ["--check"] },
          { type: "http", url: "https://example.com/hook", headers: { Authorization: "Bearer test" } },
          { type: "mcp_tool", server: "audit", tool: "record", input: {} },
          { type: "command", command: "/another-valid" }
        ]
      }]
    }
  }, { vendor: "claude", command: baseCommand }))

  assert.throws(
    () => mergeHooks({ hooks: { Stop: [{ hooks: [{ type: "future_handler", future: true }] }] } }, { vendor: "claude", command: baseCommand }),
    error => error.code === "UNSUPPORTED_HANDLER_TYPE"
  )
})

test("Claude schema rejects seven malformed handler fields without changing or leaking the target", async () => {
  const cases = [
    secret => ({ type: "command", command: `/private/${secret}`, if: " " }),
    secret => ({ type: "command", command: `/private/${secret}`, once: "true" }),
    secret => ({ type: "command", command: `/private/${secret}`, asyncRewake: "true" }),
    secret => ({ type: "command", command: `/private/${secret}`, shell: "zsh" }),
    secret => ({ type: "http", url: `https://example.com/${secret}`, allowedEnvVars: ["TOKEN", 7] }),
    secret => ({ type: "mcp_tool", server: "audit", tool: "record", input: [secret] }),
    secret => ({ type: "prompt", prompt: "judge", model: { secret } })
  ]

  for (const [index, createHandler] of cases.entries()) {
    const secret = `schema-secret-${index}`
    const claude = { hooks: { Stop: [{ hooks: [createHandler(secret)] }] } }
    const homeDir = await createHome({ claude })
    const targetPath = join(homeDir, ".claude", "settings.json")
    const before = await readFile(targetPath, "utf8")
    const report = await install({ homeDir, projectDir: resolve(homeDir, "project"), now: fixedNow })
    const serializedReport = JSON.stringify(report)

    assert.equal(report.status, "partial")
    assert.deepEqual(report.targets[0], {
      vendor: "claude",
      status: "failed",
      backupCreated: false,
      errorCode: "INVALID_STRUCTURE"
    })
    assert.equal(await readFile(targetPath, "utf8"), before)
    assert.doesNotMatch(serializedReport, new RegExp(homeDir.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")))
    assert.doesNotMatch(serializedReport, new RegExp(secret))
    assert.doesNotMatch(serializedReport, /settings\.json/)
  }
})

test("vendor schemas accept their documented handler types and reject unsupported Codex handlers", async () => {
  assert.doesNotThrow(() => mergeHooks({
    hooks: {
      Stop: [{
        hooks: [
          { type: "command", command: "/valid", if: "Bash(*)", once: true, asyncRewake: false, shell: "bash" },
          { type: "command", command: "/valid-powershell", shell: "powershell" },
          { type: "http", url: "https://example.com/hook", allowedEnvVars: ["TOKEN"] },
          { type: "mcp_tool", server: "audit", tool: "record", input: {} },
          { type: "prompt", prompt: "judge", model: "haiku" },
          { type: "agent", prompt: "verify", model: "haiku" }
        ]
      }]
    }
  }, { vendor: "claude", command: baseCommand }))

  assert.doesNotThrow(() => mergeHooks({
    hooks: {
      Stop: [{
        hooks: [
          { type: "command", command: "/valid" },
          { type: "prompt" },
          { type: "agent" }
        ]
      }]
    }
  }, { vendor: "codex", command: baseCommand }))

  for (const handler of [
    { type: "http", url: "https://example.com/hook" },
    { type: "mcp_tool", server: "audit", tool: "record" }
  ]) {
    assert.throws(
      () => mergeHooks({ hooks: { Stop: [{ hooks: [handler] }] } }, { vendor: "codex", command: baseCommand }),
      error => error.code === "UNSUPPORTED_HANDLER_TYPE"
    )
  }

  for (const handler of [
    { type: "agent", prompt: "verify", model: {} },
    { type: "prompt", prompt: "judge", model: [] }
  ]) {
    assert.throws(
      () => mergeHooks({ hooks: { Stop: [{ hooks: [handler] }] } }, { vendor: "claude", command: baseCommand }),
      error => error.code === "INVALID_STRUCTURE"
    )
  }

  for (const type of ["http", "mcp_tool"]) {
    const secret = `codex-${type}-secret`
    const handler = type === "http"
      ? { type, url: `https://example.com/${secret}` }
      : { type, server: secret, tool: "record" }
    const homeDir = await createHome({ codex: { hooks: { Stop: [{ hooks: [handler] }] } } })
    const targetPath = join(homeDir, ".codex", "hooks.json")
    const before = await readFile(targetPath, "utf8")
    const report = await install({ homeDir, projectDir: resolve(homeDir, "project"), now: fixedNow })
    const serializedReport = JSON.stringify(report)

    assert.equal(report.status, "partial")
    assert.equal(report.targets[1].errorCode, "UNSUPPORTED_HANDLER_TYPE")
    assert.equal(await readFile(targetPath, "utf8"), before)
    assert.doesNotMatch(serializedReport, new RegExp(secret))
    assert.doesNotMatch(serializedReport, /hooks\.json/)
  }
})

test("managed ID mentions outside one canonical owned group fail closed", () => {
  const id = "compact-guard/v1/claude/precompact"
  const canonical = mergeHooks({}, { vendor: "claude", command: baseCommand }).hooks.PreCompact[0]
  const collisionGroups = [
    { event: "PreCompact", group: { matcher: "manual|auto", hooks: [{ type: "command", command: `/third-party # --managed-id ${id}` }] } },
    { event: "PreCompact", group: { matcher: "manual|auto", hooks: [{ type: "command", command: `/echo '--managed-id ${id}'` }] } },
    { event: "Stop", group: structuredClone(canonical) },
    { event: "PreCompact", group: { ...structuredClone(canonical), matcher: "manual" } },
    {
      event: "PreCompact",
      group: {
        ...structuredClone(canonical),
        hooks: [{ ...canonical.hooks[0], command: `${canonical.hooks[0].command} ` }]
      }
    },
    {
      event: "PreCompact",
      group: {
        ...structuredClone(canonical),
        hooks: [{
          ...canonical.hooks[0],
          command: `/usr/bin/printf /other/bin/compact-guard.mjs --vendor claude --managed-id ${id}`
        }]
      }
    },
    {
      event: "PreCompact",
      group: {
        ...structuredClone(canonical),
        hooks: [{
          ...canonical.hooks[0],
          command: `/opt/*/node /other/bin/compact-guard.mjs --vendor claude --managed-id ${id}`
        }]
      }
    },
    {
      event: "PreCompact",
      group: {
        ...structuredClone(canonical),
        hooks: [{ ...canonical.hooks[0], timeout: 11 }]
      }
    },
    {
      event: "PreCompact",
      group: {
        ...structuredClone(canonical),
        hooks: [{ ...canonical.hooks[0], extra: true }]
      }
    }
  ]

  for (const { event, group } of collisionGroups) {
    const settings = { hooks: { [event]: [group] } }
    assert.throws(
      () => mergeHooks(settings, { vendor: "claude", command: baseCommand }),
      error => error.code === "MANAGED_ID_COLLISION"
    )
    assert.throws(
      () => removeHooks(settings, { commandMarker: id, command: baseCommand }),
      error => error.code === "MANAGED_ID_COLLISION"
    )
  }
})

test("canonical hooks from an old Node and project path upgrade once and remain removable", async () => {
  const oldClaude = mergeHooks({}, { vendor: "claude", command: oldBaseCommand })
  const oldCodex = mergeHooks({}, { vendor: "codex", command: oldBaseCommand })
  const upgradeHome = await createHome({ claude: oldClaude, codex: oldCodex })
  const currentProjectDir = resolve(upgradeHome, "current user's project")
  const first = await install({ homeDir: upgradeHome, projectDir: currentProjectDir, now: fixedNow })
  const upgradedClaude = await readJson(join(upgradeHome, ".claude", "settings.json"))
  const upgradedCodex = await readJson(join(upgradeHome, ".codex", "hooks.json"))
  const upgradedCommands = [...commandsById(upgradedClaude), ...commandsById(upgradedCodex)]
    .filter(command => command.includes("compact-guard/v1/"))
  const second = await install({ homeDir: upgradeHome, projectDir: currentProjectDir, now: fixedNow })

  assert.equal(first.status, "installed")
  assert.deepEqual(first.targets.map(target => target.status), ["updated", "updated"])
  assert.equal(upgradedCommands.length, 6)
  assert.equal(upgradedCommands.some(command => command.includes("/opt/old-node/bin/node")), false)
  assert.equal(upgradedCommands.every(command => command.includes(`current user'"'"'s project/bin/compact-guard.mjs`)), true)
  assert.equal(second.status, "unchanged")

  const uninstallHome = await createHome({ claude: oldClaude, codex: oldCodex })
  const removed = await uninstall({ homeDir: uninstallHome, projectDir: currentProjectDir })
  const removedCommands = [
    ...commandsById(await readJson(join(uninstallHome, ".claude", "settings.json"))),
    ...commandsById(await readJson(join(uninstallHome, ".codex", "hooks.json")))
  ]

  assert.equal(removed.status, "uninstalled")
  assert.equal(removedCommands.some(command => command.includes("compact-guard/v1/")), false)
})

test("unknown handler types fail the target without changing its bytes", async () => {
  const claude = { hooks: { Stop: [{ hooks: [{ type: "future_handler", value: true }] }] } }
  const homeDir = await createHome({ claude })
  const targetPath = join(homeDir, ".claude", "settings.json")
  const before = await readFile(targetPath, "utf8")
  const report = await install({ homeDir, projectDir: resolve(homeDir, "project"), now: fixedNow })

  assert.equal(report.status, "partial")
  assert.equal(report.targets[0].errorCode, "UNSUPPORTED_HANDLER_TYPE")
  assert.equal(await readFile(targetPath, "utf8"), before)
})

test("install writes both configs atomically, preserves modes, and creates private backups", async () => {
  const homeDir = await createHome({
    claude: { hooks: { Stop: [{ hooks: [{ type: "command", command: "/claude-stop" }] }] } },
    codex: { hooks: { Stop: [{ hooks: [{ type: "command", command: "/codex-stop" }] }] } }
  })
  const projectDir = resolve(homeDir, "project with spaces")
  const localSettingsPath = join(homeDir, ".claude", "settings.local.json")
  const localSettings = '{"hooks":{"SessionStart":[]}}\n'
  await writeFile(localSettingsPath, localSettings, { mode: 0o600 })
  const report = await install({ homeDir, projectDir, now: fixedNow })
  const claudePath = join(homeDir, ".claude", "settings.json")
  const codexPath = join(homeDir, ".codex", "hooks.json")
  const claude = await readJson(claudePath)
  const codex = await readJson(codexPath)
  const backupRoot = join(homeDir, ".compact-guard", "backups")
  const backupFiles = (await readdir(backupRoot, { recursive: true, withFileTypes: true }))
    .filter(entry => entry.isFile())

  assert.equal(report.status, "installed")
  assert.deepEqual(report.targets.map(target => target.status), ["updated", "updated"])
  assert.equal(await readFile(localSettingsPath, "utf8"), localSettings)
  assert.doesNotMatch(JSON.stringify(report), /claude-stop|codex-stop|project with spaces|settings\.json/)
  assert.equal(commandsById(claude).length, 4)
  assert.equal(commandsById(codex).length, 4)
  const installedIds = [...commandsById(claude), ...commandsById(codex)]
    .flatMap(command => command.match(/--managed-id (compact-guard\/v1\/[^\s]+)/)?.slice(1) ?? [])
  assert.equal(installedIds.length, 6)
  assert.deepEqual(new Set(installedIds), new Set([...managedIds("claude"), ...managedIds("codex")]))
  assert.equal((await stat(claudePath)).mode & 0o777, 0o640)
  assert.equal((await stat(codexPath)).mode & 0o777, 0o604)
  assert.equal(backupFiles.length, 2)
  for (const entry of backupFiles) {
    assert.equal((await stat(join(entry.parentPath, entry.name))).mode & 0o777, 0o600)
  }
  for (const command of [...commandsById(claude), ...commandsById(codex)].filter(command => command.includes("compact-guard/v1/"))) {
    assert.match(command, new RegExp(`^'${process.execPath.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}' `))
    assert.match(command, /'\/.*project with spaces\/bin\/compact-guard\.mjs'/)
  }
})

test("repeated install changes neither config nor backup inventory", async () => {
  const homeDir = await createHome()
  const projectDir = resolve(homeDir, "project")
  await install({ homeDir, projectDir, now: fixedNow })
  const beforeClaude = await readFile(join(homeDir, ".claude", "settings.json"), "utf8")
  const beforeCodex = await readFile(join(homeDir, ".codex", "hooks.json"), "utf8")
  const backupRoot = join(homeDir, ".compact-guard", "backups")
  const beforeBackups = (await readdir(backupRoot, { recursive: true })).length
  const report = await install({ homeDir, projectDir, now: fixedNow })

  assert.equal(report.status, "unchanged")
  assert.deepEqual(report.targets.map(target => target.status), ["unchanged", "unchanged"])
  assert.equal(await readFile(join(homeDir, ".claude", "settings.json"), "utf8"), beforeClaude)
  assert.equal(await readFile(join(homeDir, ".codex", "hooks.json"), "utf8"), beforeCodex)
  assert.equal((await readdir(backupRoot, { recursive: true })).length, beforeBackups)
})

test("rerun keeps canonical managed group position after a later third-party addition", async () => {
  const homeDir = await createHome()
  const projectDir = resolve(homeDir, "project")
  await install({ homeDir, projectDir, now: fixedNow })
  const codexPath = join(homeDir, ".codex", "hooks.json")
  const codex = await readJson(codexPath)
  codex.hooks.SessionStart.push({ hooks: [{ type: "command", command: "/later-third-party" }] })
  await writeFile(codexPath, `${JSON.stringify(codex, null, 2)}\n`)
  const before = await readFile(codexPath, "utf8")
  const backupRoot = join(homeDir, ".compact-guard", "backups")
  const beforeBackups = (await readdir(backupRoot, { recursive: true })).length
  const report = await install({ homeDir, projectDir, now: fixedNow })

  assert.equal(report.status, "unchanged")
  assert.equal(await readFile(codexPath, "utf8"), before)
  assert.equal((await readdir(backupRoot, { recursive: true })).length, beforeBackups)
})

test("a second-target failure remains partial and rerun preserves later third-party changes", async () => {
  const homeDir = await createHome()
  const projectDir = resolve(homeDir, "project")
  const codexPath = join(homeDir, ".codex", "hooks.json")
  await writeFile(codexPath, "{invalid\n", { mode: 0o600 })
  const partial = await install({ homeDir, projectDir, now: fixedNow })
  const claudePath = join(homeDir, ".claude", "settings.json")
  const claudeAfterPartial = await readJson(claudePath)

  assert.equal(partial.status, "partial")
  assert.deepEqual(partial.targets.map(target => target.status), ["updated", "failed"])
  assert.equal(commandsById(claudeAfterPartial).filter(command => command.includes("compact-guard/v1/")).length, 3)

  claudeAfterPartial.hooks.Stop = [{ hooks: [{ type: "command", command: "/added-after-partial" }] }]
  await writeFile(claudePath, `${JSON.stringify(claudeAfterPartial, null, 2)}\n`)
  await writeFile(codexPath, `${JSON.stringify({ hooks: { Stop: [{ hooks: [{ type: "command", command: "/codex-third-party" }] }] } }, null, 2)}\n`)
  const rerun = await install({ homeDir, projectDir, now: fixedNow })
  const finalClaude = await readJson(claudePath)
  const finalCodex = await readJson(codexPath)

  assert.equal(rerun.status, "installed")
  assert.equal(finalClaude.hooks.Stop[0].hooks[0].command, "/added-after-partial")
  assert.equal(finalCodex.hooks.Stop[0].hooks[0].command, "/codex-third-party")
  assert.equal(commandsById(finalClaude).filter(command => command.includes("compact-guard/v1/")).length, 3)
  assert.equal(commandsById(finalCodex).filter(command => command.includes("compact-guard/v1/")).length, 3)
})

test("install and uninstall reject non-canonical managed ID ownership without changing that target", async () => {
  const id = "compact-guard/v1/claude/precompact"
  const collision = {
    hooks: {
      PreCompact: [{
        matcher: "manual|auto",
        hooks: [{ type: "command", command: `/echo '--managed-id ${id}'` }]
      }]
    }
  }
  const installHome = await createHome({ claude: collision })
  const installPath = join(installHome, ".claude", "settings.json")
  const installBefore = await readFile(installPath, "utf8")
  const installReport = await install({ homeDir: installHome, projectDir: resolve(installHome, "project"), now: fixedNow })

  assert.equal(installReport.status, "partial")
  assert.equal(installReport.targets[0].errorCode, "MANAGED_ID_COLLISION")
  assert.equal(installReport.targets[0].backupCreated, false)
  assert.doesNotMatch(JSON.stringify(installReport), new RegExp(installHome.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")))
  assert.equal(await readFile(installPath, "utf8"), installBefore)

  const uninstallHome = await createHome()
  const projectDir = resolve(uninstallHome, "project")
  await install({ homeDir: uninstallHome, projectDir, now: fixedNow })
  const uninstallPath = join(uninstallHome, ".claude", "settings.json")
  const installed = await readJson(uninstallPath)
  installed.hooks.PreCompact[0].hooks[0].command += " # altered"
  await writeFile(uninstallPath, `${JSON.stringify(installed, null, 2)}\n`)
  const uninstallBefore = await readFile(uninstallPath, "utf8")
  const uninstallReport = await uninstall({ homeDir: uninstallHome, projectDir })

  assert.equal(uninstallReport.status, "partial")
  assert.equal(uninstallReport.targets[0].errorCode, "MANAGED_ID_COLLISION")
  assert.equal(await readFile(uninstallPath, "utf8"), uninstallBefore)
})

test("unsupported target types are rejected without following links or blocking on special files", async () => {
  const cases = ["symlink", "directory", "fifo"]
  for (const kind of cases) {
    const homeDir = await mkdtemp(join(tmpdir(), `compact-guard-${kind}-`))
    const claudeDir = join(homeDir, ".claude")
    const codexDir = join(homeDir, ".codex")
    const targetPath = join(claudeDir, "settings.json")
    await mkdir(claudeDir, { recursive: true })
    await mkdir(codexDir, { recursive: true })
    await writeFile(join(codexDir, "hooks.json"), "{}\n")
    let linkedPath
    if (kind === "symlink") {
      linkedPath = join(homeDir, "linked-settings.json")
      await writeFile(linkedPath, '{"linked":true}\n')
      await symlink(linkedPath, targetPath)
    } else if (kind === "directory") {
      await mkdir(targetPath)
    } else {
      await execFileAsync("mkfifo", [targetPath])
    }
    const linkedBefore = linkedPath === undefined ? null : await readFile(linkedPath, "utf8")
    const report = await install({ homeDir, projectDir: resolve(homeDir, "project"), now: fixedNow })
    const metadata = await lstat(targetPath)

    assert.equal(report.status, "partial")
    assert.equal(report.targets[0].errorCode, "UNSUPPORTED_TARGET_TYPE")
    assert.equal(metadata.isSymbolicLink(), kind === "symlink")
    assert.equal(metadata.isDirectory(), kind === "directory")
    assert.equal(metadata.isFIFO(), kind === "fifo")
    if (linkedPath !== undefined) {
      assert.equal(await readFile(linkedPath, "utf8"), linkedBefore)
    }
  }
})

test("a pre-rename failure keeps target bytes and removes every temporary file", async () => {
  const homeDir = await createHome({
    claude: { existing: "claude" },
    codex: { existing: "codex" }
  })
  const claudePath = join(homeDir, ".claude", "settings.json")
  const before = await readFile(claudePath, "utf8")
  const report = await install({
    homeDir,
    projectDir: resolve(homeDir, "project"),
    now: fixedNow,
    beforeRename: ({ vendor }) => {
      if (vendor === "claude") {
        throw Object.assign(new Error("injected"), { code: "TEST_PRE_RENAME_FAILURE" })
      }
    }
  })
  const leftovers = (await readdir(join(homeDir, ".claude")))
    .filter(name => name.includes(".compact-guard-") && name.endsWith(".tmp"))

  assert.equal(report.status, "partial")
  assert.equal(report.targets[0].errorCode, "IO_ERROR")
  assert.equal(await readFile(claudePath, "utf8"), before)
  assert.deepEqual(leftovers, [])
})

test("uninstall removes all six managed handlers while preserving third-party hooks and backups", async () => {
  const thirdParty = { hooks: { SessionStart: [{ hooks: [{ type: "command", command: "/third-party" }] }] } }
  const homeDir = await createHome({ claude: thirdParty, codex: thirdParty })
  const projectDir = resolve(homeDir, "project")
  await install({ homeDir, projectDir, now: fixedNow })
  const backupRoot = join(homeDir, ".compact-guard", "backups")
  const backupsBefore = (await readdir(backupRoot, { recursive: true })).length
  const report = await uninstall({ homeDir, projectDir })
  const claude = await readJson(join(homeDir, ".claude", "settings.json"))
  const codex = await readJson(join(homeDir, ".codex", "hooks.json"))

  assert.equal(report.status, "uninstalled")
  assert.equal(commandsById(claude).some(command => command.includes("compact-guard/v1/")), false)
  assert.equal(commandsById(codex).some(command => command.includes("compact-guard/v1/")), false)
  assert.equal("PreCompact" in claude.hooks, false)
  assert.equal("PostCompact" in claude.hooks, false)
  assert.equal("PreCompact" in codex.hooks, false)
  assert.equal("PostCompact" in codex.hooks, false)
  assert.equal(claude.hooks.SessionStart[0].hooks[0].command, "/third-party")
  assert.equal(codex.hooks.SessionStart[0].hooks[0].command, "/third-party")
  assert.equal((await readdir(backupRoot, { recursive: true })).length, backupsBefore)
})

test("invalid hook structure fails validation without modifying the target", async () => {
  const homeDir = await createHome({ claude: { hooks: { Stop: "not-an-array" } } })
  const projectDir = resolve(homeDir, "project")
  const claudePath = join(homeDir, ".claude", "settings.json")
  const before = await readFile(claudePath, "utf8")
  const report = await install({ homeDir, projectDir, now: fixedNow })

  assert.equal(report.status, "partial")
  assert.equal(report.targets[0].status, "failed")
  assert.equal(await readFile(claudePath, "utf8"), before)
})
