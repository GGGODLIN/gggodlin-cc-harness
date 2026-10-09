#!/usr/bin/env node
import { readFileSync, readdirSync, statSync, realpathSync, existsSync } from 'node:fs'
import { join, basename } from 'node:path'
import { homedir } from 'node:os'

const HOME = homedir()
const SETTINGS_PATH = join(HOME, '.claude/settings.json')
const USER_SKILLS_ROOT = join(HOME, '.claude/skills')
const PLUGIN_CACHE_ROOT = join(HOME, '.claude/plugins/cache')
const PLUGIN_MARKETPLACES_ROOT = join(HOME, '.claude/plugins/marketplaces')
const PROJECTS_ROOT = join(HOME, '.claude/projects')

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

const args = process.argv.slice(2)
const getArg = (k: string): string | undefined => {
  const i = args.indexOf(k)
  return i >= 0 ? args[i + 1] : undefined
}
const argMonths = parseInt(getArg('--months') ?? '3', 10)
const argDescThreshold = parseInt(getArg('--desc-bloat-chars') ?? '300', 10)
// 480000 = the smallest context window this machine's sessions run with (2026-09-22 user decision);
// a session with a larger window only has more headroom, so the smallest one is the binding case.
const argContextTokens = parseInt(getArg('--context-tokens') ?? '480000', 10)
const argShowInactive = args.includes('--show-inactive')
const argJson = args.includes('--json')

const tokens = (s: string) => Math.ceil(Buffer.byteLength(s, 'utf8') / 4)

function parseFrontmatter(content: string): Record<string, string> | null {
  if (!content.startsWith('---')) return null
  const end = content.indexOf('\n---', 4)
  if (end < 0) return null
  const fm = content.slice(4, end)
  const out: Record<string, string> = {}
  let key = ''
  let buf: string[] = []
  for (const line of fm.split('\n')) {
    const m = line.match(/^(\w[\w-]*):\s*(.*)$/)
    if (m) {
      if (key) out[key] = buf.join('\n').trim()
      key = m[1]
      buf = [m[2]]
    } else if (key) {
      buf.push(line)
    }
  }
  if (key) out[key] = buf.join('\n').trim()
  for (const k of Object.keys(out)) {
    out[k] = out[k].replace(/^"(.+)"$/s, '$1').replace(/^'(.+)'$/s, '$1')
  }
  return out
}

const settings = JSON.parse(readFileSync(SETTINGS_PATH, 'utf8'))
const enabledPlugins = new Set<string>(
  Object.entries(settings.enabledPlugins ?? {}).filter(([, v]) => v === true).map(([k]) => k),
)
const budgetFraction: number = settings.skillListingBudgetFraction ?? 0.04
const maxDescChars: number = settings.skillListingMaxDescChars ?? 3072
const skillOverrides: Record<string, string> = settings.skillOverrides ?? {}

// Mirrors design-router's discover grep, but matched against the DESCRIPTION only
// (the description is what surfaces for auto-triggering; matching full body over-flags
// any skill that merely discusses design). Router itself is excluded below.
const DESIGN_SIGNATURE = /anti-slop|landing.*portfolio|distinctive.*frontend|design.*taste|claude\.ai.*artifact/i
const DRIFT_EXCLUDE = new Set<string>(['design-router'])

function scanRoot(rootPath: string, origin: Origin, pluginIdResolver?: (skillPath: string) => string | undefined): Skill[] {
  if (!existsSync(rootPath)) return []
  const out: Skill[] = []
  const walk = (dir: string, depth: number): void => {
    if (depth > 6) return
    let entries: string[]
    try { entries = readdirSync(dir) } catch { return }
    for (const e of entries) {
      const p = join(dir, e)
      let st
      try { st = statSync(p) } catch { continue }
      if (!st.isDirectory()) continue
      const skillFile = join(p, 'SKILL.md')
      if (existsSync(skillFile)) {
        try {
          const content = readFileSync(skillFile, 'utf8')
          const fm = parseFrontmatter(content)
          const name = fm?.name ?? basename(p)
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
  const configDir = process.env.CLAUDE_CONFIG_DIR ?? join(HOME, '.claude')
  try {
    return JSON.parse(readFileSync(join(configDir, '.claude.json'), 'utf8')).oauthAccount?.accountUuid
  } catch { return undefined }
})()
const syncedDirs = [...new Set(userSkillsRaw.map(s => SYNCED_DIR_RE.exec(s.path)?.[0]).filter((d): d is string => !!d))]
const keptSyncedDir: string | undefined = syncedDirs.length <= 1
  ? syncedDirs[0]
  : syncedDirs.find(d => currentAccountUuid !== undefined && d.endsWith(`_${currentAccountUuid}/`))
    ?? syncedDirs.sort((a, b) => statSync(join(USER_SKILLS_ROOT, 'synced', basename(b))).mtimeMs - statSync(join(USER_SKILLS_ROOT, 'synced', basename(a))).mtimeMs)[0]
const userSkills = userSkillsRaw.filter(s => {
  const dir = SYNCED_DIR_RE.exec(s.path)?.[0]
  return dir === undefined || dir === keptSyncedDir
})
const syncedDropped = userSkillsRaw.length - userSkills.length

const cacheSkills: Skill[] = []
if (existsSync(PLUGIN_CACHE_ROOT)) {
  for (const mp of readdirSync(PLUGIN_CACHE_ROOT)) {
    if (mp.endsWith('.bak')) continue
    const mpPath = join(PLUGIN_CACHE_ROOT, mp)
    let st
    try { st = statSync(mpPath) } catch { continue }
    if (!st.isDirectory()) continue
    for (const plugin of readdirSync(mpPath)) {
      const pluginPath = join(mpPath, plugin)
      let pst
      try { pst = statSync(pluginPath) } catch { continue }
      if (!pst.isDirectory()) continue
      const versions = readdirSync(pluginPath)
        .map(v => ({ v, path: join(pluginPath, v) }))
        .filter(x => { try { return statSync(x.path).isDirectory() } catch { return false } })
        .sort((a, b) => statSync(b.path).mtimeMs - statSync(a.path).mtimeMs)
      const latest = versions[0]
      if (!latest) continue
      const pluginId = `${plugin}@${mp}`
      const active = enabledPlugins.has(pluginId)
      const skills = scanRoot(latest.path, active ? 'plugin-active' : 'plugin-marketplace-inactive', () => pluginId)
      cacheSkills.push(...skills)
    }
  }
}

const marketplaceSkills: Skill[] = []
if (existsSync(PLUGIN_MARKETPLACES_ROOT)) {
  for (const mp of readdirSync(PLUGIN_MARKETPLACES_ROOT)) {
    if (mp.endsWith('.bak')) continue
    const mpPath = join(PLUGIN_MARKETPLACES_ROOT, mp)
    let st
    try { st = statSync(mpPath) } catch { continue }
    if (!st.isDirectory()) continue
    const skills = scanRoot(mpPath, 'plugin-marketplace-inactive', () => mp)
    marketplaceSkills.push(...skills)
  }
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
const nameLookup = new Map<string, Skill[]>()
for (const s of all) {
  const lower = s.name.toLowerCase()
  if (!nameLookup.has(lower)) nameLookup.set(lower, [])
  nameLookup.get(lower)!.push(s)
}

function scanProjects(): void {
  if (!existsSync(PROJECTS_ROOT)) return
  for (const proj of readdirSync(PROJECTS_ROOT)) {
    const projPath = join(PROJECTS_ROOT, proj)
    let pst
    try { pst = statSync(projPath) } catch { continue }
    if (!pst.isDirectory()) continue
    let files: string[]
    try { files = readdirSync(projPath) } catch { continue }
    for (const f of files) {
      if (!f.endsWith('.jsonl')) continue
      const fp = join(projPath, f)
      let fst
      try { fst = statSync(fp) } catch { continue }
      if (fst.mtimeMs < cutoff) continue
      let content: string
      try { content = readFileSync(fp, 'utf8') } catch { continue }
      let m: RegExpExecArray | null
      while ((m = invokeRe.exec(content)) !== null) {
        const raw = m[1]
        const stripped = raw.includes(':') ? raw.split(':').pop()! : raw
        const matches = nameLookup.get(raw.toLowerCase()) ?? nameLookup.get(stripped.toLowerCase()) ?? []
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
const USER_COMMANDS_ROOT = join(HOME, '.claude/commands')
const commandEntries: { name: string; descChars: number }[] = existsSync(USER_COMMANDS_ROOT)
  ? readdirSync(USER_COMMANDS_ROOT).filter(f => f.endsWith('.md')).map(f => {
      const fm = parseFrontmatter(readFileSync(join(USER_COMMANDS_ROOT, f), 'utf8'))
      return { name: f.slice(0, -3), descChars: (fm?.description ?? '').length }
    })
  : []
const isNameOnly = (name: string) => skillOverrides[name] === 'name-only' || skillOverrides[name.split(':').pop() ?? name] === 'name-only'
const entryChars = (name: string, descChars: number) =>
  isNameOnly(name) ? name.length + 2 : name.length + 4 + Math.min(descChars, maxDescChars)
const listingEntries = [
  ...activeSkills.map(s => ({ name: s.origin === 'plugin-active' && s.pluginId ? `${s.pluginId}:${s.name}` : s.name, descChars: s.descChars })),
  ...commandEntries,
]
const activeDescChars = listingEntries.reduce((acc, e) => acc + entryChars(e.name, e.descChars), 0) + Math.max(0, listingEntries.length - 1)
const activeDescTokens = activeSkills.reduce(
  (acc, s) => acc + (isNameOnly(s.name) ? 0 : s.descTokens),
  0,
)
const BYTES_PER_TOKEN = 4
const budgetCap = Math.floor(argContextTokens * BYTES_PER_TOKEN * budgetFraction)
const budgetUsedPct = (activeDescChars / budgetCap) * 100

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
    activeDescTokens,
    budgetCap,
    overBudget: activeDescTokens > budgetCap,
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
