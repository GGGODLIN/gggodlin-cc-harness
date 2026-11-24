#!/usr/bin/env node
import { readFileSync, readdirSync, statSync, realpathSync, existsSync } from 'node:fs'
import { join, basename } from 'node:path'
import { homedir } from 'node:os'

const HOME = homedir()
const ENV_CONFIG_DIR = process.env.CLAUDE_CONFIG_DIR?.trim() || undefined
const CONFIG_DIR = ENV_CONFIG_DIR ?? join(HOME, '.claude')
const SETTINGS_PATH = join(CONFIG_DIR, 'settings.json')
const USER_SKILLS_ROOT = join(CONFIG_DIR, 'skills')
const PLUGIN_CACHE_ROOT = join(CONFIG_DIR, 'plugins/cache')
const PLUGIN_MARKETPLACES_ROOT = join(CONFIG_DIR, 'plugins/marketplaces')
const PROJECTS_ROOT = join(CONFIG_DIR, 'projects')
const USER_COMMANDS_ROOT = join(CONFIG_DIR, 'commands')

type Origin = 'user' | 'plugin-active' | 'plugin-marketplace-inactive'

interface Skill {
  name: string
  description: string
  bodyTokens: number
  descTokens: number
  descChars: number
  path: string
  realpath: string
  origin: Origin
  isDesignSkill: boolean
  pluginId?: string
  invokes: number
  lastInvoke?: string
}

function parseIntArg(flag: string, value: string | undefined, min: number): number {
  if (value === undefined || !/^\d+$/.test(value)) {
    console.error(`Invalid value for ${flag}: ${value ?? '(missing)'}`)
    process.exit(1)
  }
  const n = Number(value)
  if (!Number.isSafeInteger(n) || n < min) {
    console.error(`${flag} must be an integer >= ${min}, got ${value}`)
    process.exit(1)
  }
  return n
}

const args = process.argv.slice(2)
let argMonths = 3
let argDescThreshold = 300
// 480000 = the smallest context window this machine's sessions run with (2026-09-22 user decision);
// a session with a larger window only has more headroom, so the smallest one is the binding case.
let argContextTokens = 480000
let argShowInactive = false
let argJson = false

for (let i = 0; i < args.length; i++) {
  const a = args[i]
  if (a === '--months') {
    argMonths = parseIntArg(a, args[++i], 1)
  } else if (a === '--desc-bloat-chars') {
    argDescThreshold = parseIntArg(a, args[++i], 0)
  } else if (a === '--context-tokens') {
    argContextTokens = parseIntArg(a, args[++i], 1)
  } else if (a === '--show-inactive') {
    argShowInactive = true
  } else if (a === '--json') {
    argJson = true
  } else {
    console.error(`Unknown argument: ${a}`)
    process.exit(1)
  }
}

const tokens = (s: string) => Math.ceil(Buffer.byteLength(s, 'utf8') / 4)

interface FmEntry {
  mode: 'plain' | 'literal' | 'folded'
  lines: string[]
}

function finalizeFmEntry(entry: FmEntry): string {
  if (entry.mode === 'plain') {
    const joined = entry.lines.map(l => l.trim()).filter(Boolean).join(' ').trim()
    if (/^"(.*)"$/s.test(joined)) return joined.replace(/^"(.*)"$/s, '$1')
    if (/^'(.*)'$/s.test(joined)) return joined.replace(/^'(.*)'$/s, '$1')
    return joined
  }

  const nonEmpty = entry.lines.filter(l => l.trim().length > 0)
  const minIndent = nonEmpty.length > 0
    ? Math.min(...nonEmpty.map(l => l.match(/^[ \t]*/)?.[0].length ?? 0))
    : 0
  const dedented = entry.lines.map(l => (l.length >= minIndent ? l.slice(minIndent) : ''))

  if (entry.mode === 'literal') {
    return dedented.join('\n').trim()
  }

  const paragraphs: string[] = []
  let current: string[] = []
  for (const l of dedented) {
    if (l.trim() === '') {
      if (current.length > 0) {
        paragraphs.push(current.join(' '))
        current = []
      }
    } else {
      current.push(l.trim())
    }
  }
  if (current.length > 0) paragraphs.push(current.join(' '))
  return paragraphs.join('\n').trim()
}

function parseFrontmatter(content: string): Record<string, string> | null {
  const normalized = content.replace(/^\uFEFF/, '').replace(/\r\n?/g, '\n')
  const openMatch = normalized.match(/^---[ \t]*\n/)
  if (!openMatch) return null
  const rest = normalized.slice(openMatch[0].length)
  const closeMatch = rest.match(/^---[ \t]*(?:\n|$)/m)
  if (!closeMatch || closeMatch.index === undefined) return null
  const fm = rest.slice(0, closeMatch.index)
  const out: Record<string, string> = {}
  let key = ''
  let current: FmEntry | null = null
  for (const line of fm.split('\n')) {
    const m = line.match(/^(\w[\w-]*):(?:[ \t]+(.*)|[ \t]*)$/)
    if (m) {
      if (key && current) out[key] = finalizeFmEntry(current)
      key = m[1]
      const rawVal = (m[2] ?? '').trimEnd()
      const blockMatch = rawVal.match(/^([|>])([+-]?\d*|\d*[+-]?)(?:[ \t]+#.*)?$/)
      if (blockMatch) {
        current = { mode: blockMatch[1] === '|' ? 'literal' : 'folded', lines: [] }
      } else {
        current = { mode: 'plain', lines: rawVal === '' ? [] : [rawVal] }
      }
    } else if (key && current) {
      if (current.mode === 'plain' && /^[ \t]*#/.test(line)) continue
      current.lines.push(line)
    }
  }
  if (key && current) out[key] = finalizeFmEntry(current)
  return out
}

function loadSettings(): Record<string, any> {
  if (!existsSync(SETTINGS_PATH)) return {}
  let raw: string
  try {
    raw = readFileSync(SETTINGS_PATH, 'utf8')
  } catch (err: unknown) {
    console.error(`Failed to read ${SETTINGS_PATH}: ${err instanceof Error ? err.message : String(err)}`)
    process.exit(1)
  }
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch (err: unknown) {
    console.error(`Invalid JSON in ${SETTINGS_PATH}: ${err instanceof Error ? err.message : String(err)}`)
    process.exit(1)
  }
  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
    console.error(`Invalid ${SETTINGS_PATH}: expected a JSON object`)
    process.exit(1)
  }
  return parsed as Record<string, any>
}

const settings = loadSettings()
const rawEnabledPlugins = settings.enabledPlugins
const enabledPlugins = new Set<string>(
  rawEnabledPlugins && typeof rawEnabledPlugins === 'object' && !Array.isArray(rawEnabledPlugins)
    ? Object.entries(rawEnabledPlugins).filter(([, v]) => v === true).map(([k]) => k)
    : [],
)
const budgetFraction: number = settings.skillListingBudgetFraction ?? 0.04
if (typeof budgetFraction !== 'number' || !Number.isFinite(budgetFraction) || budgetFraction <= 0) {
  console.error(`Invalid skillListingBudgetFraction in ${SETTINGS_PATH}: expected finite number > 0`)
  process.exit(1)
}
const maxDescChars: number = settings.skillListingMaxDescChars ?? 3072
if (typeof maxDescChars !== 'number' || !Number.isFinite(maxDescChars) || maxDescChars < 0) {
  console.error(`Invalid skillListingMaxDescChars in ${SETTINGS_PATH}: expected finite number >= 0`)
  process.exit(1)
}
const rawOverrides = settings.skillOverrides
const skillOverrides: Record<string, string> =
  rawOverrides && typeof rawOverrides === 'object' && !Array.isArray(rawOverrides)
    ? (rawOverrides as Record<string, string>)
    : {}

// Mirrors design-router's discover grep, but matched against the DESCRIPTION only
// (the description is what surfaces for auto-triggering; matching full body over-flags
// any skill that merely discusses design). Router itself is excluded below.
const DESIGN_SIGNATURE = /anti-slop|landing.*portfolio|distinctive.*frontend|design.*taste|claude\.ai.*artifact/i
const DRIFT_EXCLUDE = new Set<string>(['design-router', 'docs'])

function scanRoot(rootPath: string, origin: Origin, pluginIdResolver?: (skillPath: string) => string | undefined): Skill[] {
  try {
    if (!statSync(rootPath).isDirectory()) return []
  } catch {
    return []
  }
  const out: Skill[] = []
  const ancestors = new Set<string>()
  const walk = (dir: string, depth: number): void => {
    if (depth > 6) return
    let dirRp: string
    try {
      dirRp = realpathSync(dir)
    } catch {
      return
    }
    if (ancestors.has(dirRp)) return
    ancestors.add(dirRp)
    try {
      let entries: string[]
      try { entries = readdirSync(dir) } catch { return }
      for (const e of entries) {
        if (e.startsWith('.')) continue
        const p = join(dir, e)
        let st
        try { st = statSync(p) } catch { continue }
        if (!st.isDirectory()) continue
        let pRp: string
        try { pRp = realpathSync(p) } catch { continue }
        if (ancestors.has(pRp)) continue
        const skillFile = join(p, 'SKILL.md')
        if (existsSync(skillFile)) {
          try {
            const content = readFileSync(skillFile, 'utf8')
            const fm = parseFrontmatter(content)
            const rawName = (fm?.name ?? '').trim()
            const name = rawName !== '' ? rawName : basename(p)
            const description = fm?.description ?? ''
            const rp = realpathSync(skillFile)
            out.push({
              name,
              description,
              bodyTokens: tokens(content),
              descTokens: tokens(description),
              descChars: description.length,
              path: skillFile,
              realpath: rp,
              origin,
              isDesignSkill: DESIGN_SIGNATURE.test(description),
              pluginId: pluginIdResolver?.(skillFile),
              invokes: 0,
            })
          } catch {}
        }
        walk(p, depth + 1)
      }
    } finally {
      ancestors.delete(dirRp)
    }
  }
  walk(rootPath, 0)
  return out
}

const userSkillsRaw = scanRoot(USER_SKILLS_ROOT, 'user')

// skills/synced/<orgUuid>_<accountUuid>/ holds one copy of the claude.ai-synced official
// skills per signed-in account. CC loads only the copy for the current account, so counting
// every copy double-books the budget (2026-09-22: two acme accounts → 8 skills counted twice).
const SYNCED_DIR_RE = /\/skills\/synced\/([0-9a-f-]+)_([0-9a-f-]+)\//
const currentAccountUuid: string | undefined = (() => {
  const candidates = ENV_CONFIG_DIR
    ? [join(CONFIG_DIR, '.claude.json')]
    : [join(HOME, '.claude.json'), join(CONFIG_DIR, '.claude.json')]
  for (const candidate of candidates) {
    try {
      const uuid = JSON.parse(readFileSync(candidate, 'utf8')).oauthAccount?.accountUuid
      if (typeof uuid === 'string' && uuid.length > 0) return uuid
    } catch {}
  }
  return undefined
})()
const syncedDirs = [...new Set(userSkillsRaw.map(s => SYNCED_DIR_RE.exec(s.path)?.[0]).filter((d): d is string => !!d))]
const keptSyncedDir: string | undefined = syncedDirs.length <= 1
  ? syncedDirs[0]
  : syncedDirs.find(d => currentAccountUuid !== undefined && d.endsWith(`_${currentAccountUuid}/`))
    ?? syncedDirs.sort((a, b) => {
      const ma = (() => { try { return statSync(join(USER_SKILLS_ROOT, 'synced', basename(a))).mtimeMs } catch { return 0 } })()
      const mb = (() => { try { return statSync(join(USER_SKILLS_ROOT, 'synced', basename(b))).mtimeMs } catch { return 0 } })()
      return mb - ma
    })[0]
const userSkills = userSkillsRaw.filter(s => {
  const dir = SYNCED_DIR_RE.exec(s.path)?.[0]
  return dir === undefined || dir === keptSyncedDir
})
const syncedDropped = userSkillsRaw.length - userSkills.length

const cacheSkills: Skill[] = []
let cacheMarketplaces: string[] = []
try {
  if (statSync(PLUGIN_CACHE_ROOT).isDirectory()) {
    cacheMarketplaces = readdirSync(PLUGIN_CACHE_ROOT)
  }
} catch {}
for (const mp of cacheMarketplaces) {
  if (mp.endsWith('.bak')) continue
  const mpPath = join(PLUGIN_CACHE_ROOT, mp)
  let plugins: string[]
  try {
    if (!statSync(mpPath).isDirectory()) continue
    plugins = readdirSync(mpPath)
  } catch {
    continue
  }
  for (const plugin of plugins) {
    const pluginPath = join(mpPath, plugin)
    let versionNames: string[]
    try {
      if (!statSync(pluginPath).isDirectory()) continue
      versionNames = readdirSync(pluginPath)
    } catch {
      continue
    }
    const versions = versionNames
      .map(v => {
        const vp = join(pluginPath, v)
        try {
          const vst = statSync(vp)
          return vst.isDirectory() ? { v, path: vp, mtimeMs: vst.mtimeMs } : null
        } catch {
          return null
        }
      })
      .filter((x): x is { v: string; path: string; mtimeMs: number } => x !== null)
      .sort((a, b) => b.mtimeMs - a.mtimeMs)
    const latest = versions[0]
    if (!latest) continue
    const pluginId = `${plugin}@${mp}`
    const active = enabledPlugins.has(pluginId)
    const skills = scanRoot(latest.path, active ? 'plugin-active' : 'plugin-marketplace-inactive', () => pluginId)
    cacheSkills.push(...skills)
  }
}

const marketplaceSkills: Skill[] = []
let marketplaceEntries: string[] = []
try {
  if (statSync(PLUGIN_MARKETPLACES_ROOT).isDirectory()) {
    marketplaceEntries = readdirSync(PLUGIN_MARKETPLACES_ROOT)
  }
} catch {}
for (const mp of marketplaceEntries) {
  if (mp.endsWith('.bak')) continue
  const mpPath = join(PLUGIN_MARKETPLACES_ROOT, mp)
  try {
    if (!statSync(mpPath).isDirectory()) continue
  } catch {
    continue
  }
  const skills = scanRoot(mpPath, 'plugin-marketplace-inactive', () => mp)
  marketplaceSkills.push(...skills)
}

const allRaw = [...userSkills, ...cacheSkills, ...marketplaceSkills]
const seenRP = new Set<string>()
const all: Skill[] = []
for (const s of allRaw) {
  if (seenRP.has(s.realpath)) continue
  seenRP.add(s.realpath)
  all.push(s)
}

const cutoff = Date.now() - argMonths * 30 * 24 * 3600 * 1000
const invokeRe = /"name":"Skill","input":\{"skill":"([^"]+)"/g
const bareLookup = new Map<string, Skill[]>()
const qualifiedLookup = new Map<string, Skill[]>()
const addLookup = (map: Map<string, Skill[]>, key: string, skill: Skill): void => {
  let arr = map.get(key)
  if (!arr) {
    arr = []
    map.set(key, arr)
  }
  if (!arr.includes(skill)) arr.push(skill)
}

for (const s of all) {
  addLookup(bareLookup, s.name.toLowerCase(), s)
  if (s.pluginId) {
    addLookup(qualifiedLookup, `${s.pluginId}:${s.name}`.toLowerCase(), s)
    const pluginShort = s.pluginId.split('@')[0]
    if (pluginShort) addLookup(qualifiedLookup, `${pluginShort}:${s.name}`.toLowerCase(), s)
  }
}

function resolveInvokedSkills(raw: string): Skill[] {
  const lower = raw.toLowerCase()
  if (raw.includes(':')) {
    const qMatches = qualifiedLookup.get(lower)
    if (qMatches && qMatches.length > 0) {
      const activeQ = qMatches.filter(s => s.origin === 'plugin-active')
      return activeQ.length > 0 ? activeQ : qMatches
    }
    const exactBare = bareLookup.get(lower)
    return exactBare ?? []
  }
  const bMatches = bareLookup.get(lower) ?? []
  const activeB = bMatches.filter(s => s.origin === 'user' || s.origin === 'plugin-active')
  return activeB.length > 0 ? activeB : bMatches
}

function scanProjects(): void {
  let projects: string[] = []
  try {
    if (!statSync(PROJECTS_ROOT).isDirectory()) return
    projects = readdirSync(PROJECTS_ROOT)
  } catch {
    return
  }
  for (const proj of projects) {
    const projPath = join(PROJECTS_ROOT, proj)
    let files: string[]
    try {
      if (!statSync(projPath).isDirectory()) continue
      files = readdirSync(projPath)
    } catch {
      continue
    }
    for (const f of files) {
      if (!f.endsWith('.jsonl')) continue
      const fp = join(projPath, f)
      let fst
      try { fst = statSync(fp) } catch { continue }
      if (fst.mtimeMs < cutoff) continue
      let content: string
      try { content = readFileSync(fp, 'utf8') } catch { continue }
      invokeRe.lastIndex = 0
      let m: RegExpExecArray | null
      while ((m = invokeRe.exec(content)) !== null) {
        const matches = resolveInvokedSkills(m[1])
        for (const s of matches) {
          s.invokes++
          const iso = new Date(fst.mtimeMs).toISOString().slice(0, 10)
          if (!s.lastInvoke || iso > s.lastInvoke) s.lastInvoke = iso
        }
      }
    }
  }
}

scanProjects()

const byName = new Map<string, Skill[]>()
for (const s of all) {
  if (!byName.has(s.name)) byName.set(s.name, [])
  byName.get(s.name)!.push(s)
}
const duplicates = [...byName.entries()].filter(([_, v]) => v.length > 1)

const activeSkills = all.filter(s => s.origin === 'user' || s.origin === 'plugin-active')
const bloat = activeSkills
  .filter(s => s.descChars > argDescThreshold)
  .sort((a, b) => b.descTokens - a.descTokens)
const unused = activeSkills.filter(s => s.invokes === 0)
// Mirrors CC 2.1.278 `q5t`: the listing budget is measured in CHARACTERS =
// contextTokens × bytesPerToken(4) × skillListingBudgetFraction. Each entry costs
// name.length + 4 + min(desc.length, skillListingMaxDescChars); a name-only entry costs
// name.length + 2; entries are joined by one separator char. Commands (~/.claude/commands/*.md)
// are part of the same listing. Bundled built-in skills live inside the binary and are not
// counted here, so the real total is a few thousand chars higher than reported.
const commandEntries: { name: string; descChars: number }[] = []
try {
  if (statSync(USER_COMMANDS_ROOT).isDirectory()) {
    for (const f of readdirSync(USER_COMMANDS_ROOT)) {
      if (!f.endsWith('.md')) continue
      const fullPath = join(USER_COMMANDS_ROOT, f)
      try {
        if (!statSync(fullPath).isFile()) continue
        const fm = parseFrontmatter(readFileSync(fullPath, 'utf8'))
        commandEntries.push({ name: f.slice(0, -3), descChars: (fm?.description ?? '').length })
      } catch {}
    }
  }
} catch {}
const isNameOnly = (name: string) => skillOverrides[name] === 'name-only' || skillOverrides[name.split(':').pop() ?? name] === 'name-only'
const entryChars = (name: string, descChars: number) =>
  isNameOnly(name) ? name.length + 2 : name.length + 4 + Math.min(descChars, maxDescChars)
const listingName = (s: Skill) =>
  s.origin === 'plugin-active' && s.pluginId ? `${s.pluginId}:${s.name}` : s.name
const listingEntries = [
  ...activeSkills.map(s => ({ name: listingName(s), descChars: s.descChars })),
  ...commandEntries,
]
const activeDescChars = listingEntries.reduce((acc, e) => acc + entryChars(e.name, e.descChars), 0) + Math.max(0, listingEntries.length - 1)
const activeDescTokens = activeSkills.reduce(
  (acc, s) => acc + (isNameOnly(listingName(s)) ? 0 : s.descTokens),
  0,
)
const BYTES_PER_TOKEN = 4
const budgetCap = Math.floor(argContextTokens * BYTES_PER_TOKEN * budgetFraction)
const budgetUsedPct = budgetCap > 0 ? (activeDescChars / budgetCap) * 100 : 0

const byOrigin = new Map<string, number>()
for (const s of all) byOrigin.set(s.origin, (byOrigin.get(s.origin) ?? 0) + 1)

const lines: string[] = []
const out = (s = '') => lines.push(s)

out('# CC Skill Doctor Report\n')
out(`Generated: ${new Date().toISOString().slice(0, 19)}`)
out(`Args: months=${argMonths} desc-bloat-chars=${argDescThreshold} context-tokens=${argContextTokens.toLocaleString()}`)
out(`Settings: skillListingBudgetFraction=${budgetFraction} skillListingMaxDescChars=${maxDescChars}`)
out(`Budget cap: ${argContextTokens.toLocaleString()} ctx × ${BYTES_PER_TOKEN} chars/tok × ${(budgetFraction * 100).toFixed(1)}% = ${budgetCap.toLocaleString()} chars (CC q5t formula; smallest context window in use)`)
out()

out('## 1. Budget overview')
out(`Active skills: ${activeSkills.length} (user=${activeSkills.filter(s => s.origin === 'user').length}, plugin-active=${activeSkills.filter(s => s.origin === 'plugin-active').length})`)
if (syncedDirs.length > 1) out(`Synced official skills: ${syncedDirs.length} account copies found, counted only ${keptSyncedDir?.replace(/^.*\/synced\//, 'synced/') ?? '(none)'} (${syncedDropped} duplicate entries dropped; CC loads one copy per signed-in account)`)
out(`Listing size: ${activeDescChars.toLocaleString()} chars (${activeSkills.length} skills + ${commandEntries.length} commands; name-only entries cost name+2; bundled built-in skills not counted)`)
out(`Sum description tokens (bytes/4, informational): ${activeDescTokens.toLocaleString()}`)
out(`Budget used: ${budgetUsedPct.toFixed(1)}% of ${budgetCap.toLocaleString()} chars`)
if (activeDescChars > budgetCap) out(`⚠️  OVER BUDGET by ${(activeDescChars - budgetCap).toLocaleString()} chars — CC switches to priority mode and drops descriptions of the least-used skills until the listing fits`)
out()

out(`## 2. Description bloat (active, desc > ${argDescThreshold} chars)`)
if (bloat.length === 0) out('(none)')
else {
  out('| skill | origin | desc chars | desc tokens | invokes |')
  out('|---|---|---|---|---|')
  for (const s of bloat.slice(0, 25)) out(`| ${s.name} | ${s.origin} | ${s.descChars} | ${s.descTokens} | ${s.invokes} |`)
}
out()

out('## 3. Duplicates (by name)')
if (duplicates.length === 0) out('(none)')
else {
  for (const [name, copies] of duplicates) {
    out(`### ${name}`)
    for (const c of copies) out(`- [${c.origin}] ${c.path.replace(HOME, '~')}`)
  }
}
out()

out(`## 4. Unused candidates (active, 0 invoke past ${argMonths}mo)`)
if (unused.length === 0) out('(none)')
else {
  out('| skill | origin | desc tokens | body tokens |')
  out('|---|---|---|---|')
  for (const s of unused.sort((a, b) => b.descTokens - a.descTokens)) {
    out(`| ${s.name} | ${s.origin} | ${s.descTokens} | ${s.bodyTokens} |`)
  }
}
out()

out('## 5. Root summary')
for (const [k, v] of byOrigin) out(`- ${k}: ${v}`)
out()

const NAME_ONLY = 'name-only'
const designUserDrift = all.filter(s => s.origin === 'user' && s.isDesignSkill && !DRIFT_EXCLUDE.has(s.name) && (skillOverrides[s.name] ?? 'on') !== NAME_ONLY)
const designPluginActive = all.filter(s => s.origin === 'plugin-active' && s.isDesignSkill && !DRIFT_EXCLUDE.has(s.name))

out('## 6. Design-router drift (skillOverrides)')
out('Design skills should be `name-only` so design-router is the sole auto-trigger entry (it still Skill-invokes them).')
if (designUserDrift.length === 0 && designPluginActive.length === 0) out('(none — design skills correctly routed via design-router)')
else {
  if (designUserDrift.length > 0) {
    out('\n**User design skills NOT name-only → fix in ~/.claude/settings.json skillOverrides:**')
    out('| skill | current state | fix |')
    out('|---|---|---|')
    for (const s of designUserDrift) out(`| ${s.name} | ${skillOverrides[s.name] ?? 'on (default)'} | "${s.name}": "name-only" |`)
  }
  if (designPluginActive.length > 0) {
    out('\n**Plugin design skills active (skillOverrides cannot quiet — disable plugin or accept it competes with design-router):**')
    for (const s of designPluginActive) out(`- ${s.name} [${s.pluginId}]`)
  }
}
out()

out(`## Top 10 most-invoked (active, past ${argMonths}mo)`)
const topInvoked = activeSkills.filter(s => s.invokes > 0).sort((a, b) => b.invokes - a.invokes).slice(0, 10)
if (topInvoked.length === 0) out('(none — no Skill tool calls matched in window; may indicate slash-command usage instead)')
else {
  out('| skill | invokes | last | desc tokens |')
  out('|---|---|---|---|')
  for (const s of topInvoked) out(`| ${s.name} | ${s.invokes} | ${s.lastInvoke ?? '-'} | ${s.descTokens} |`)
}

if (argShowInactive) {
  out()
  out('## Inactive marketplace skills (not in enabledPlugins)')
  const inactive = all.filter(s => s.origin === 'plugin-marketplace-inactive')
  out(`Count: ${inactive.length}`)
  for (const s of inactive.slice(0, 30)) out(`- [${s.pluginId}] ${s.name}`)
}

console.log(lines.join('\n'))

if (argJson) {
  console.log('\n---JSON---')
  console.log(JSON.stringify({
    activeDescChars,
    activeDescTokens,
    budgetCap,
    budgetUsedPct,
    overBudget: activeDescChars > budgetCap,
    counts: Object.fromEntries(byOrigin),
    duplicates: duplicates.map(([n, v]) => ({ name: n, copies: v.map(s => s.path) })),
    unused: unused.map(s => ({ name: s.name, origin: s.origin, descTokens: s.descTokens })),
    bloat: bloat.map(s => ({ name: s.name, descChars: s.descChars, descTokens: s.descTokens, invokes: s.invokes })),
    topInvoked: topInvoked.map(s => ({ name: s.name, invokes: s.invokes, lastInvoke: s.lastInvoke })),
    designDrift: {
      userNotNameOnly: designUserDrift.map(s => ({ name: s.name, state: skillOverrides[s.name] ?? 'on' })),
      pluginActive: designPluginActive.map(s => ({ name: s.name, pluginId: s.pluginId })),
    },
  }, null, 2))
}
