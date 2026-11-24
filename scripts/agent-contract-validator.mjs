#!/usr/bin/env node
import { existsSync, lstatSync, readFileSync, readdirSync, realpathSync } from 'node:fs'
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

const stripBom = text => (text.charCodeAt(0) === 0xfeff ? text.slice(1) : text)

const dedupePaths = paths => {
  const seen = new Set()
  const result = []
  for (const target of paths) {
    let key = target
    if (existsSync(target)) {
      try {
        key = realpathSync(target)
      } catch {
        key = target
      }
    }
    if (seen.has(key)) continue
    seen.add(key)
    result.push(target)
  }
  return result
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
  if (/^(?:true|false|null|~|\d+(?:\.\d+)?)$/i.test(trimmed)) return null
  if (trimmed.startsWith('{') && trimmed.endsWith('}') && !/^\{\{[^}]+\}\}$/.test(trimmed)) return null
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
  const text = stripBom(readFileSync(file, 'utf8'))
  if (!text.startsWith('---')) return { file, text, fields: {}, frontmatterStart: 0, frontmatterEnd: 0 }
  const openEnd = text.indexOf('\n')
  const bodyStart = openEnd < 0 ? text.length : openEnd + 1
  const rest = text.slice(bodyStart)
  const closeMatch = rest.match(/(?:^|\r?\n)---(?=[ \t]*(?:\r?\n|$))/)
  if (!closeMatch) return { file, text, fields: null, frontmatterStart: 0, frontmatterEnd: text.length }
  const closeOffset = (closeMatch.index ?? 0) + (closeMatch[0].startsWith('\r\n') ? 2 : closeMatch[0].startsWith('\n') ? 1 : 0)
  const closing = bodyStart + closeOffset
  const frontmatter = text.slice(bodyStart, closing)
  const fields = {}
  const positions = {}
  const duplicateKeys = []
  let offset = bodyStart
  let activeListKey = null
  for (const rawLine of frontmatter.split('\n')) {
    const line = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine
    const keyMatch = line.match(/^([A-Za-z][A-Za-z0-9_-]*):[ \t]*(.*)$/)
    if (keyMatch) {
      const key = keyMatch[1]
      const value = keyMatch[2]
      if (positions[key] !== undefined) duplicateKeys.push({ key, index: offset })
      positions[key] = offset
      if (key === 'tools' || key === 'disallowedTools') {
        const trimmed = value.trim()
        if (!trimmed) {
          fields[key] = []
          activeListKey = key
        } else {
          fields[key] = parseTools(value)
          activeListKey = null
        }
      } else {
        fields[key] = parseScalar(value)
        activeListKey = null
      }
    } else if (activeListKey) {
      const itemMatch = line.match(/^[ \t]*-[ \t]+(.+)$/)
      if (itemMatch) {
        fields[activeListKey].push(parseScalar(itemMatch[1]))
      } else if (line.trim() && !line.trim().startsWith('#')) {
        activeListKey = null
      }
    }
    offset += rawLine.length + 1
  }
  return { file, text, fields, positions, duplicateKeys, frontmatterStart: 0, frontmatterEnd: closing + 3 }
}

const jsonFiles = paths => dedupePaths(paths.filter(file => existsSync(file) && lstatSync(file).isFile()))

const readJson = (file, surface, diagnostics) => {
  const text = stripBom(readFileSync(file, 'utf8'))
  try {
    return { file, text, value: JSON.parse(text) }
  } catch {
    diagnostics.push(diagnostic('MALFORMED_JSON', `invalid JSON in ${surface}`, surface, file, text, 0))
    return null
  }
}

const pluginNamespacesFrom = settingsValues => {
  const effective = new Map()
  for (const settings of settingsValues) {
    const plugins = settings?.value?.enabledPlugins
    if (!plugins || typeof plugins !== 'object' || Array.isArray(plugins)) continue
    for (const [key, enabled] of Object.entries(plugins)) {
      effective.set(key, Boolean(enabled))
    }
  }
  const namespaces = new Set(['claude-in-chrome', 'plugin'])
  const pluginNames = new Set()
  for (const [key, enabled] of effective.entries()) {
    if (!enabled) continue
    const [name] = key.split('@')
    if (!name) continue
    pluginNames.add(name)
    namespaces.add(name)
    for (const part of name.split('-')) {
      if (part) namespaces.add(part)
    }
  }
  return { namespaces, pluginNames }
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
      else if (listed && typeof listed === 'object') tools.set(name, new Set(Object.entries(listed).filter(([, enabled]) => enabled !== false).map(([tool]) => tool)))
      else tools.delete(name)
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

const isDynamicTool = value => /\$\{[^}]+\}|<[^>]+>|\{\{[^}]+\}\}/.test(value)

const parseRoutingPolicies = files => {
  const policies = new Map()
  const entries = []
  for (const file of files) {
    const text = stripBom(readFileSync(file, 'utf8'))
    const patterns = [
      /^\|\s*(routed-[A-Za-z0-9-]+)\s*\|[^|]*\|\s*(opus|sonnet|haiku)\s*\|\s*(low|medium|high|xhigh)\s*\|/gim,
      /\b(routed-[A-Za-z0-9-]+)\b[^\n]*?\bmodel\s*[:=]\s*(opus|sonnet|haiku)\b[^\n]*?\beffort\s*[:=]\s*(low|medium|high|xhigh)\b/gim,
      /\b(routed-[A-Za-z0-9-]+)\b[^\n]*?\b(opus|sonnet|haiku)\s*\+\s*(low|medium|high|xhigh)\b/gim
    ]
    for (const pattern of patterns) {
      for (const match of text.matchAll(pattern)) {
        const name = match[1]
        const policy = { name, model: match[2].toLowerCase(), effort: match[3].toLowerCase(), file, text, index: match.index ?? 0 }
        entries.push(policy)
        if (!policies.has(name)) policies.set(name, policy)
      }
    }
  }
  return { policies, entries }
}

const isEnabledPluginServer = (server, pluginRegistry) => {
  if (pluginRegistry.namespaces.has(server)) return true
  if (server.startsWith('plugin_')) {
    for (const name of pluginRegistry.pluginNames) {
      if (server === `plugin_${name}` || server.startsWith(`plugin_${name}_`)) return true
    }
  }
  return false
}

const unknownMcpToolMessage = (tool, mcpRegistry, pluginRegistry) => {
  const server = mcpServerForTool(tool)
  if (!server) return `MCP tool ${tool} is not provided by an enabled MCP server`
  const toolName = tool.slice(`mcp__${server}__`.length)
  if (!toolName) return `MCP tool ${tool} is not provided by an enabled MCP server`
  if (isEnabledPluginServer(server, pluginRegistry)) return null
  if (mcpRegistry.servers.has(server)) {
    const knownTools = mcpRegistry.tools.get(server)
    if (!knownTools || (toolName === '*' && knownTools.size > 0) || knownTools.has('*') || knownTools.has(toolName) || knownTools.has(tool)) return null
  }
  return `MCP tool ${tool} is not provided by an enabled MCP server`
}

const validateTool = (entry, tool, field, mcpRegistry, pluginRegistry, diagnostics) => {
  const parsed = entry.parsed
  const position = parsed.positions[field] ?? 0
  if (!tool || isDynamicTool(tool)) {
    diagnostics.push(diagnostic('DYNAMIC_TOOL_UNVERIFIED', `dynamic ${field} reference ${tool || '<empty>'} cannot be verified`, 'tool-reference', entry.file, parsed.text, position, 'unverified'))
    return
  }
  if (tool.includes(':')) return
  if (tool.startsWith('mcp__')) {
    const message = unknownMcpToolMessage(tool, mcpRegistry, pluginRegistry)
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

const isSkillFrictionLog = (root, file) => {
  const skillsPrefix = join(root, 'skills') + '/'
  if (!file.startsWith(skillsPrefix)) return false
  const parts = file.slice(skillsPrefix.length).split('/')
  return parts.length === 2 && parts[1] === 'friction-log.md'
}

const collectSurfaceFiles = roots => roots.flatMap(root => [
  ...walk(join(root, 'skills')).filter(file => !isSkillFrictionLog(root, file)),
  ...walk(join(root, 'commands')),
  ...walk(join(root, 'workflows'))
]).filter(file => ['.md', '.js', '.mjs', '.cjs', '.ts', '.json', '.sh'].includes(extname(file)))

const isMarkdownDispatchSyntax = (file, text, index, kind) => {
  if (extname(file) !== '.md') return true
  const lineStart = text.lastIndexOf('\n', index - 1) + 1
  const lineEnd = text.indexOf('\n', index)
  const line = text.slice(lineStart, lineEnd < 0 ? text.length : lineEnd)
  const fenceCount = (text.slice(0, index).match(/^[ \t]*```/gm) ?? []).length
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
  const dynamicKeyPattern = /(?:(["'])(subagent_type|agentType)\1|\b(subagent_type|agentType)\b)\s*:\s*((?:"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\\n])*`|[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*)(?:[ \t]*\+[ \t]*(?:"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\\n])*`|[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*))+|`[^`\n]*\$\{[^}\n]+\}[^`\n]*`|[A-Za-z0-9_.:-]*\$\{[^}\n]+\}(?:[A-Za-z0-9_.:-]+|\$\{[^}\n]+\})*|[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*)/g
  for (const match of text.matchAll(dynamicKeyPattern)) {
    const kind = match[2] ?? match[3]
    const name = match[4]
    const index = (match.index ?? 0) + match[0].lastIndexOf(name)
    if ((isDynamicValue(name) || name.includes('.') || name.startsWith('$') || name.includes('+')) && isMarkdownDispatchSyntax(file, text, index, kind)) {
      add({ file, text, name, index, kind, dynamic: true })
    }
  }
  const dynamicAgentPattern = /\bAgent\(\s*(`[^`\n]*\$\{[^}\n]+\}[^`\n]*`|\$\{[^}\n]+\}|[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*)\s*\)/g
  for (const match of text.matchAll(dynamicAgentPattern)) {
    const name = match[1]
    const index = (match.index ?? 0) + match[0].lastIndexOf(name)
    if ((isDynamicValue(name) || name.includes('.') || name.startsWith('$')) && isMarkdownDispatchSyntax(file, text, index, 'Agent')) {
      add({ file, text, name, index, kind: 'Agent', dynamic: true })
    }
  }
  const keyStaticPattern = /(?:(["'])(subagent_type|agentType)\1|\b(subagent_type|agentType)\b)\s*:\s*(?:(["'`])([A-Za-z0-9_.:-]+)\4(?![ \t]*\+)|([A-Za-z0-9_.:-]+)(?![A-Za-z0-9_.:-])(?![ \t]*[+${]))/g
  for (const match of text.matchAll(keyStaticPattern)) {
    const kind = match[2] ?? match[3]
    const name = match[5] ?? match[6]
    const index = (match.index ?? 0) + match[0].lastIndexOf(name)
    if (!isMarkdownDispatchSyntax(file, text, index, kind)) continue
    add({ file, text, name, index, kind, dynamic: isDynamicValue(name) })
  }
  const agentStaticPattern = /\bAgent\(\s*(?:(["'`])([A-Za-z0-9_.:-]+)\1(?![ \t]*\+)|([A-Za-z0-9_.:-]+)(?![ \t]*[+${]))\s*\)/g
  for (const match of text.matchAll(agentStaticPattern)) {
    const name = match[2] ?? match[3]
    const index = (match.index ?? 0) + match[0].lastIndexOf(name)
    if (!isMarkdownDispatchSyntax(file, text, index, 'Agent')) continue
    add({ file, text, name, index, kind: 'Agent', dynamic: isDynamicValue(name) })
  }
  return references
}

const validate = args => {
  const globalRoot = args.globalRoot ?? resolve(process.env.CLAUDE_CONFIG_DIR ?? join(homedir(), '.claude'))
  const repoRoot = args.repoRoot ?? resolve(process.cwd())
  const roots = dedupePaths([globalRoot, join(repoRoot, '.claude')])
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
  const routingFiles = dedupePaths(routingPaths.filter(file => existsSync(file) && lstatSync(file).isFile()))
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
    for (const dup of parsed.duplicateKeys ?? []) {
      diagnostics.push(diagnostic('DUPLICATE_FRONTMATTER_KEY', `frontmatter key ${dup.key} is defined more than once`, 'agent-definition', file, parsed.text, dup.index))
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
        const targetText = routingFiles[0] ? stripBom(readFileSync(targetFile, 'utf8')) : parsed.text
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
    const permissionsSection = settings.text.indexOf('"permissions"')
    const allowSection = settings.text.indexOf('"allow"', permissionsSection >= 0 ? permissionsSection : 0)
    let searchFrom = allowSection >= 0 ? allowSection : 0
    for (const entry of allow) {
      const value = String(entry)
      const token = JSON.stringify(value)
      let index = settings.text.indexOf(token, searchFrom)
      if (index < 0) index = settings.text.indexOf(value, searchFrom)
      if (index < 0) index = settings.text.indexOf(value)
      if (index >= 0) searchFrom = index + token.length
      const agentMatch = value.match(/^Agent\(\s*([^()]+?)\s*\)$/)
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
      const builtin = value.match(/^([A-Za-z][A-Za-z0-9]*)(?:\(|$)/)?.[1]
      if (builtin && !BUILTIN_TOOLS.has(builtin)) {
        diagnostics.push(diagnostic('UNKNOWN_BUILTIN_TOOL', `settings allow references unknown built-in tool ${builtin}`, 'settings', settings.file, settings.text, index))
      }
    }
  }
  for (const file of collectSurfaceFiles(roots)) {
    const text = stripBom(readFileSync(file, 'utf8'))
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
