#!/usr/bin/env node
import { existsSync, lstatSync, readFileSync, readdirSync } from 'node:fs'
import { homedir } from 'node:os'
import { basename, extname, join, resolve } from 'node:path'

const MODEL_VALUES = new Set(['opus', 'sonnet', 'haiku'])
const EFFORT_VALUES = new Set(['low', 'medium', 'high', 'xhigh'])
const BUILTIN_TOOLS = new Set([
  'Agent',
  'AskUserQuestion',
  'Bash',
  'BashOutput',
  'Edit',
  'EnterWorktree',
  'ExitWorktree',
  'Glob',
  'Grep',
  'KillBash',
  'NotebookEdit',
  'Read',
  'Skill',
  'Task',
  'TaskStop',
  'ToolSearch',
  'WebFetch',
  'WebSearch',
  'Write',
  'Workflow'
])

const parseArgs = values => {
  const args = { mcpConfigs: [], settings: [], routings: [] }
  for (let index = 0; index < values.length; index += 1) {
    const value = values[index]
    if (value === '--help') return { help: true }
    if (!value.startsWith('--')) throw new Error(`unexpected argument: ${value}`)
    const name = value.slice(2)
    const next = values[index + 1]
    if (!next || next.startsWith('--')) throw new Error(`missing value for --${name}`)
    if (name === 'mcp-config') args.mcpConfigs.push(resolve(next))
    else if (name === 'settings') args.settings.push(resolve(next))
    else if (name === 'routing') args.routings.push(resolve(next))
    else if (name === 'global-root') args.globalRoot = resolve(next)
    else if (name === 'repo-root') args.repoRoot = resolve(next)
    else throw new Error(`unknown option: --${name}`)
    index += 1
  }
  return args
}

const locationFor = (text, index) => {
  const prefix = text.slice(0, index)
  const line = prefix.split('\n').length
  const column = index - prefix.lastIndexOf('\n')
  return { line, column }
}

const diagnostic = (code, message, surface, file, text, index, status = 'error') => {
  const location = locationFor(text, Math.max(index, 0))
  return {
    code,
    message,
    status,
    surface,
    path: file,
    file,
    line: location.line,
    column: location.column,
    location: { path: file, line: location.line, column: location.column },
    position: { line: location.line, column: location.column },
    source: { surface, path: file, line: location.line, column: location.column }
  }
}

const parseScalar = value => {
  const trimmed = value.trim()
  if ((trimmed.startsWith('"') && trimmed.endsWith('"')) || (trimmed.startsWith("'") && trimmed.endsWith("'"))) {
    return trimmed.slice(1, -1)
  }
  return trimmed
}

const parseTools = value => {
  const trimmed = value.trim()
  if (/^(?:true|false)$/i.test(trimmed)) return null
  if (trimmed.startsWith('[') && trimmed.endsWith(']')) {
    try {
      const parsed = JSON.parse(trimmed)
      return Array.isArray(parsed) ? parsed.map(item => String(item)) : null
    } catch {
      return trimmed.slice(1, -1).split(',').map(item => parseScalar(item)).filter(Boolean)
    }
  }
  if (!trimmed) return []
  return trimmed.split(',').map(item => parseScalar(item)).filter(Boolean)
}

const parseAgentFile = file => {
  const text = readFileSync(file, 'utf8')
  if (!text.startsWith('---')) return { file, text, fields: {}, frontmatterStart: 0, frontmatterEnd: 0 }
  const closing = text.indexOf('\n---', 3)
  if (closing < 0) return { file, text, fields: null, frontmatterStart: 0, frontmatterEnd: text.length }
  const frontmatter = text.slice(4, closing)
  const fields = {}
  const positions = {}
  for (const match of frontmatter.matchAll(/^([A-Za-z][A-Za-z0-9_-]*):[ \t]*(.*)$/gm)) {
    const key = match[1]
    const value = match[2]
    const index = 4 + (match.index ?? 0)
    if (positions[key] === undefined) positions[key] = index
    if (key === 'tools' || key === 'disallowedTools') fields[key] = parseTools(value)
    else fields[key] = parseScalar(value)
  }
  return { file, text, fields, positions, frontmatterStart: 0, frontmatterEnd: closing + 4 }
}

const jsonFiles = paths => [...new Set(paths)].filter(file => existsSync(file) && lstatSync(file).isFile())

const readJson = (file, surface, diagnostics) => {
  const text = readFileSync(file, 'utf8')
  try {
    return { file, text, value: JSON.parse(text) }
  } catch {
    diagnostics.push(diagnostic('MALFORMED_JSON', `invalid JSON in ${surface}`, surface, file, text, 0))
    return null
  }
}

const pluginNamespacesFrom = settingsValues => {
  const namespaces = new Set(['claude-in-chrome', 'plugin'])
  for (const settings of settingsValues) {
    const plugins = settings?.value?.enabledPlugins
    if (!plugins || typeof plugins !== 'object') continue
    for (const [key, enabled] of Object.entries(plugins)) {
      if (!enabled) continue
      const [name] = key.split('@')
      namespaces.add(name)
      for (const part of name.split('-')) namespaces.add(part)
    }
  }
  return namespaces
}

const mcpRegistryFrom = configs => {
  const servers = new Set()
  const tools = new Map()
  const disabled = new Set(configs.flatMap(config => {
    const values = config?.value?.disabledMcpServers
    return Array.isArray(values) ? values.map(String) : []
  }))
  for (const config of configs) {
    const value = config?.value
    const entries = value?.mcpServers ?? value?.servers
    if (!entries || typeof entries !== 'object' || Array.isArray(entries)) continue
    for (const [name, definition] of Object.entries(entries)) {
      if (disabled.has(name)) continue
      servers.add(name)
      const listed = definition?.tools ?? definition?.enabledTools
      if (Array.isArray(listed)) tools.set(name, new Set(listed.map(String)))
      else if (listed && typeof listed === 'object') tools.set(name, new Set(Object.keys(listed)))
    }
  }
  return { servers, tools }
}

const disabledAgentsFrom = settingsValues => {
  const disabled = new Set()
  for (const settings of settingsValues) {
    const deny = settings?.value?.permissions?.deny
    if (!Array.isArray(deny)) continue
    for (const entry of deny) {
      const match = String(entry).match(/^Agent\(\s*([^()]+?)\s*\)$/)
      if (match) disabled.add(match[1])
    }
  }
  return disabled
}

const mcpServerForTool = tool => tool.match(/^mcp__(.+?)__/)?.[1] ?? null

const isDynamicValue = value => /[$<>{}\[\()\.]|\b(?:agentType|subagent_type|variable|dynamic)\b/.test(value) || /^[a-z]+[A-Z]/.test(value)

const parseRoutingPolicies = files => {
  const policies = new Map()
  const entries = []
  for (const file of files) {
    const text = readFileSync(file, 'utf8')
    const patterns = [
      /^\|\s*(routed-[A-Za-z0-9-]+)\s*\|[^|]*\|\s*(opus|sonnet|haiku)\s*\|\s*(low|medium|high|xhigh)\s*\|/gim,
      /\b(routed-[A-Za-z0-9-]+)\b[^\n]*?\bmodel\s*[:=]\s*(opus|sonnet|haiku)\b[^\n]*?\beffort\s*[:=]\s*(low|medium|high|xhigh)\b/gim,
      /\b(routed-[A-Za-z0-9-]+)\b[^\n]*?\b(opus|sonnet|haiku)\s*\+\s*(low|medium|high|xhigh)\b/gim
    ]
    for (const pattern of patterns) {
      for (const match of text.matchAll(pattern)) {
        const name = match[1]
        const policy = { name, model: match[2], effort: match[3], file, text, index: match.index ?? 0 }
        entries.push(policy)
        if (!policies.has(name)) policies.set(name, policy)
      }
    }
  }
  return { policies, entries }
}

const unknownMcpToolMessage = (tool, mcpRegistry, pluginNamespaces) => {
  const server = mcpServerForTool(tool)
  if (server && pluginNamespaces.has(server)) return null
  if (server && mcpRegistry.servers.has(server)) {
    const knownTools = mcpRegistry.tools.get(server)
    const toolName = tool.slice(`mcp__${server}__`.length)
    if (!knownTools || knownTools.has('*') || knownTools.has(toolName) || knownTools.has(tool)) return null
  }
  return `MCP tool ${tool} is not provided by an enabled MCP server`
}

const validateTool = (entry, tool, field, mcpRegistry, pluginNamespaces, diagnostics) => {
  const parsed = entry.parsed
  const position = parsed.positions[field] ?? 0
  if (!tool || isDynamicValue(tool)) {
    diagnostics.push(diagnostic('DYNAMIC_TOOL_UNVERIFIED', `dynamic ${field} reference ${tool || '<empty>'} cannot be verified`, 'tool-reference', entry.file, parsed.text, position, 'unverified'))
    return
  }
  if (tool.includes(':')) return
  if (tool.startsWith('mcp__')) {
    const message = unknownMcpToolMessage(tool, mcpRegistry, pluginNamespaces)
    if (message) diagnostics.push(diagnostic('UNKNOWN_MCP_TOOL', message, 'tool-reference', entry.file, parsed.text, position))
    return
  }
  if (!BUILTIN_TOOLS.has(tool)) {
    diagnostics.push(diagnostic('UNKNOWN_BUILTIN_TOOL', `built-in tool ${tool} is not known`, 'tool-reference', entry.file, parsed.text, position))
  }
}

const walk = directory => {
  if (!existsSync(directory) || !lstatSync(directory).isDirectory()) return []
  const files = []
  const visit = current => {
    for (const entry of readdirSync(current, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      const file = join(current, entry.name)
      if (entry.isSymbolicLink()) continue
      if (entry.isDirectory()) visit(file)
      else if (entry.isFile()) files.push(file)
    }
  }
  visit(directory)
  return files
}

const collectAgentFiles = roots => roots.flatMap(root => walk(join(root, 'agents')).filter(file => extname(file) === '.md'))

const collectSurfaceFiles = roots => roots.flatMap(root => [
  ...walk(join(root, 'skills')),
  ...walk(join(root, 'commands')),
  ...walk(join(root, 'workflows'))
]).filter(file => ['.md', '.js', '.mjs', '.cjs', '.ts', '.json', '.sh'].includes(extname(file)))

const isMarkdownDispatchSyntax = (file, text, index, kind) => {
  if (extname(file) !== '.md') return true
  const lineStart = text.lastIndexOf('\n', index - 1) + 1
  const lineEnd = text.indexOf('\n', index)
  const line = text.slice(lineStart, lineEnd < 0 ? text.length : lineEnd)
  const fenceCount = (text.slice(0, index).match(/^```/gm) ?? []).length
  const normalizedLine = line.trim().replace(/^[-*]\s+/, '')
  return fenceCount % 2 === 1 || line.includes('`') || line.includes('Agent(') || line.includes('agent(') || normalizedLine.startsWith(`${kind}:`)
}

const extractDispatchReferences = (file, text) => {
  const references = []
  const seen = new Set()
  const add = reference => {
    const key = `${reference.kind}:${reference.index}:${reference.name}`
    if (seen.has(key)) return
    seen.add(key)
    references.push(reference)
  }
  const patterns = [
    { kind: 'subagent_type', regex: /\bsubagent_type\s*:\s*(?:["'`])?([A-Za-z0-9_.:-]+)(?:["'`])?/g },
    { kind: 'agentType', regex: /\bagentType\s*:\s*(?:["'`])?([A-Za-z0-9_.:-]+)(?:["'`])?/g },
    { kind: 'Agent', regex: /\bAgent\(\s*(?:["'`])?([A-Za-z0-9_.:-]+)(?:["'`])?\s*\)/g }
  ]
  for (const pattern of patterns) {
    for (const match of text.matchAll(pattern.regex)) {
      const name = match[1]
      const index = (match.index ?? 0) + match[0].indexOf(name)
      if (!isMarkdownDispatchSyntax(file, text, index, pattern.kind)) continue
      add({ file, text, name, index, kind: pattern.kind, dynamic: isDynamicValue(name) })
    }
  }
  const dynamicPattern = /\b(subagent_type|agentType)\s*:\s*(\$\{[^}\n]+\}|[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*)/g
  for (const match of text.matchAll(dynamicPattern)) {
    const name = match[2]
    const index = (match.index ?? 0) + match[0].indexOf(name)
    if ((isDynamicValue(name) || name.includes('.') || name.startsWith('$')) && isMarkdownDispatchSyntax(file, text, index, match[1])) {
      add({ file, text, name, index, kind: match[1], dynamic: true })
    }
  }
  return references
}

const validate = args => {
  const globalRoot = args.globalRoot ?? resolve(process.env.CLAUDE_CONFIG_DIR ?? join(homedir(), '.claude'))
  const repoRoot = args.repoRoot ?? resolve(process.cwd())
  const roots = [...new Set([globalRoot, join(repoRoot, '.claude')])]
  const diagnostics = []
  const settingsPaths = args.settings.length
    ? args.settings
    : [join(globalRoot, 'settings.json'), join(repoRoot, '.claude', 'settings.json'), join(repoRoot, 'settings.json')]
  const settingsValues = jsonFiles(settingsPaths).map(file => readJson(file, 'settings', diagnostics)).filter(Boolean)
  const mcpPaths = args.mcpConfigs.length
    ? args.mcpConfigs
    : [join(globalRoot, '.claude.json'), join(repoRoot, '.claude.json'), join(homedir(), '.claude.json')]
  const mcpValues = jsonFiles(mcpPaths).map(file => readJson(file, 'mcp-config', diagnostics)).filter(Boolean)
  const mcpRegistry = mcpRegistryFrom([...settingsValues, ...mcpValues])
  const pluginNamespaces = pluginNamespacesFrom(settingsValues)
  const disabledAgents = new Set(['general-purpose', 'claude', ...disabledAgentsFrom(settingsValues)])
  const routingPaths = args.routings.length
    ? args.routings
    : [join(globalRoot, 'references', 'subagent-routing.md'), join(repoRoot, '.claude', 'references', 'subagent-routing.md')]
  const routingFiles = [...new Set(routingPaths)].filter(file => existsSync(file) && lstatSync(file).isFile())
  const routing = parseRoutingPolicies(routingFiles)
  for (const entry of routing.entries.slice(1)) {
    const existing = routing.policies.get(entry.name)
    if (existing && (existing.model !== entry.model || existing.effort !== entry.effort)) {
      diagnostics.push(diagnostic('ROUTING_POLICY_CONFLICT', `routing policy ${entry.name} has conflicting model or effort values`, 'routing-ssot', entry.file, entry.text, entry.index))
    }
  }
  const agents = new Map()
  for (const file of collectAgentFiles(roots)) {
    const parsed = parseAgentFile(file)
    if (parsed.fields === null) {
      diagnostics.push(diagnostic('MALFORMED_FRONTMATTER', 'agent definition frontmatter is not closed', 'agent-definition', file, parsed.text, parsed.frontmatterEnd))
      continue
    }
    const name = parsed.fields.name
    if (!name) {
      diagnostics.push(diagnostic('MISSING_AGENT_NAME', 'agent definition must declare a name', 'agent-definition', file, parsed.text, parsed.positions?.name ?? 0))
      continue
    }
    if (name.includes(':')) continue
    if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(name)) {
      diagnostics.push(diagnostic('INVALID_AGENT_NAME', `agent name ${name} must use kebab-case`, 'agent-definition', file, parsed.text, parsed.positions.name ?? 0))
    }
    const entry = { file, name, parsed }
    const existing = agents.get(name)
    if (existing) {
      diagnostics.push(diagnostic('DUPLICATE_AGENT_NAME', `agent name ${name} is defined more than once`, 'agent-definition', file, parsed.text, parsed.positions.name ?? 0))
      diagnostics.push(diagnostic('DUPLICATE_AGENT_NAME', `agent name ${name} is defined more than once`, 'agent-definition', existing.file, existing.parsed.text, existing.parsed.positions.name ?? 0))
    } else {
      agents.set(name, entry)
    }
    if (basename(file, '.md') !== name) {
      diagnostics.push(diagnostic('AGENT_FILENAME_MISMATCH', `agent filename does not match declared name ${name}`, 'agent-definition', file, parsed.text, parsed.positions.name ?? 0))
    }
    if (parsed.fields.model && !MODEL_VALUES.has(parsed.fields.model)) {
      diagnostics.push(diagnostic('INVALID_MODEL', `agent model ${parsed.fields.model} is not supported`, 'agent-definition', file, parsed.text, parsed.positions.model ?? 0))
    }
    if (parsed.fields.effort && !EFFORT_VALUES.has(parsed.fields.effort)) {
      diagnostics.push(diagnostic('INVALID_EFFORT', `agent effort ${parsed.fields.effort} is not supported`, 'agent-definition', file, parsed.text, parsed.positions.effort ?? 0))
    }
    for (const field of ['tools', 'disallowedTools']) {
      if (parsed.fields[field] === null) {
        diagnostics.push(diagnostic('INVALID_TOOL_ALLOWLIST', `${field} must be a list`, 'agent-definition', file, parsed.text, parsed.positions[field] ?? 0))
        continue
      }
      if (!Array.isArray(parsed.fields[field])) continue
      if (field === 'tools' && parsed.fields[field].length === 0 && !parsed.text.includes('<!-- intentional-zero-tools -->')) {
        diagnostics.push(diagnostic('ZERO_TOOLS_UNMARKED', 'tools: [] requires an intentional-zero-tools marker', 'agent-definition', file, parsed.text, parsed.positions[field] ?? 0))
      }
      for (const tool of parsed.fields[field]) validateTool(entry, tool, field, mcpRegistry, pluginNamespaces, diagnostics)
    }
    if (name.startsWith('routed-')) {
      const policy = routing.policies.get(name)
      if (!policy) {
        const targetFile = routingFiles[0] ?? file
        const targetText = routingFiles[0] ? readFileSync(targetFile, 'utf8') : parsed.text
        diagnostics.push(diagnostic(routingFiles.length ? 'ROUTING_POLICY_MISSING' : 'ROUTING_SSOT_MISSING', `routing policy for ${name} is missing`, 'routing-ssot', targetFile, targetText, routingFiles.length ? 0 : parsed.positions.name ?? 0))
      } else {
        if (parsed.fields.model !== policy.model) {
          diagnostics.push(diagnostic('ROUTING_POLICY_MISMATCH', `routing policy for ${name} requires model ${policy.model}`, 'routing-ssot', file, parsed.text, parsed.positions.model ?? parsed.positions.name ?? 0))
        }
        if (parsed.fields.effort !== policy.effort) {
          diagnostics.push(diagnostic('ROUTING_POLICY_MISMATCH', `routing policy for ${name} requires effort ${policy.effort}`, 'routing-ssot', file, parsed.text, parsed.positions.effort ?? parsed.positions.name ?? 0))
        }
      }
    }
  }
  for (const settings of settingsValues) {
    const allow = settings.value?.permissions?.allow
    if (!Array.isArray(allow)) continue
    for (const entry of allow) {
      const value = String(entry)
      const agentMatch = value.match(/^Agent\(\s*([^()]+?)\s*\)$/)
      const index = settings.text.indexOf(value)
      if (agentMatch) {
        const name = agentMatch[1]
        if (name.includes(':')) continue
        if (disabledAgents.has(name)) {
          diagnostics.push(diagnostic('DISABLED_AGENT_REFERENCE', `settings allow references disabled agent ${name}`, 'settings', settings.file, settings.text, index))
        } else if (!agents.has(name)) {
          diagnostics.push(diagnostic('UNKNOWN_AGENT_REFERENCE', `settings allow references unknown agent ${name}`, 'settings', settings.file, settings.text, index))
        }
        continue
      }
      if (value.startsWith('mcp__')) {
        const message = unknownMcpToolMessage(value, mcpRegistry, pluginNamespaces)
        if (message) diagnostics.push(diagnostic('UNKNOWN_MCP_TOOL', message, 'settings', settings.file, settings.text, index))
        continue
      }
      const builtin = value.match(/^([A-Za-z][A-Za-z0-9]*)\(/)?.[1]
      if (builtin && !BUILTIN_TOOLS.has(builtin)) {
        diagnostics.push(diagnostic('UNKNOWN_BUILTIN_TOOL', `settings allow references unknown built-in tool ${builtin}`, 'settings', settings.file, settings.text, index))
      }
    }
  }
  for (const file of collectSurfaceFiles(roots)) {
    const text = readFileSync(file, 'utf8')
    for (const reference of extractDispatchReferences(file, text)) {
      if (reference.dynamic) {
        diagnostics.push(diagnostic('DYNAMIC_AGENT_REFERENCE_UNVERIFIED', `dynamic agent reference ${reference.name} cannot be verified`, 'dispatch-reference', file, text, reference.index, 'unverified'))
        continue
      }
      if (reference.name.includes(':')) continue
      if (disabledAgents.has(reference.name)) {
        diagnostics.push(diagnostic('DISABLED_AGENT_REFERENCE', `dispatch reference uses disabled agent ${reference.name}`, 'dispatch-reference', file, text, reference.index))
      } else if (!agents.has(reference.name)) {
        diagnostics.push(diagnostic('UNKNOWN_AGENT_REFERENCE', `dispatch reference points to unknown agent ${reference.name}`, 'dispatch-reference', file, text, reference.index))
      }
    }
  }
  diagnostics.sort((left, right) => left.path.localeCompare(right.path) || left.line - right.line || left.column - right.column || left.code.localeCompare(right.code))
  const errors = diagnostics.filter(item => item.status === 'error')
  const unverified = diagnostics.filter(item => item.status === 'unverified')
  return {
    status: errors.length ? 'fail' : 'pass',
    valid: errors.length === 0,
    diagnostics,
    unverified,
    summary: { errors: errors.length, unverified: unverified.length, diagnostics: diagnostics.length }
  }
}

const printHelp = () => {
  process.stdout.write('Usage: node scripts/agent-contract-validator.mjs [options]\n')
  process.stdout.write('  --global-root <path>\n  --repo-root <path>\n  --settings <path>\n  --routing <path>\n  --mcp-config <path>\n')
}

try {
  const args = parseArgs(process.argv.slice(2))
  if (args.help) {
    printHelp()
    process.exitCode = 0
  } else {
    const result = validate(args)
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`)
    process.exitCode = result.valid ? 0 : 1
  }
} catch (error) {
  process.stdout.write(`${JSON.stringify({ status: 'fail', valid: false, diagnostics: [{ code: 'CLI_ERROR', status: 'error', message: error.message }], summary: { errors: 1, unverified: 0, diagnostics: 1 } }, null, 2)}\n`)
  process.exitCode = 2
}
