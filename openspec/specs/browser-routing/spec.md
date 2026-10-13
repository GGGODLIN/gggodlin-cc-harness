# browser-routing Specification

## Purpose
Route every general browser task through LCU on the user's daily Chrome, keep chrome-devtools for diagnostics only, and keep the retired claude-in-chrome, Open Browser Use, and Agent Chrome routes out of active guidance.

## Requirements

### Requirement: General browser route uses LCU on daily Chrome

Every active Claude Code route for general page navigation, reading, search, or authenticated interaction SHALL use the formal LCU MCP (`mcp__lcu__js`) on the approved daily Chrome. It MUST NOT fall back to Open Browser Use, Agent Chrome, Cua, or a directly launched runtime when LCU is unavailable.

#### Scenario: Main session performs general browser work
- **WHEN** a main session needs to open, read, search, or interact with a webpage
- **THEN** it uses `mcp__lcu__js` on a tab the task names or creates
- **AND** it does not select claude-in-chrome, Open Browser Use, or general-purpose chrome-devtools

#### Scenario: LCU is unavailable
- **WHEN** the LCU MCP is not loaded, not connected, or lacks the required capability
- **THEN** the browser task stops and reports the concrete blocker
- **AND** it does not fall back to Open Browser Use, Agent Chrome, or Cua

### Requirement: Retired browser routes stay disabled

Active runtime guidance MUST NOT direct any browser task to `claude-in-chrome`, Open Browser Use, or Agent Chrome. User settings SHALL deny every `mcp__claude-in-chrome__*` tool and SHALL NOT allow any `mcp__open_browser_use__*` tool. No launch agent SHALL start the Agent Chrome profile at login, and no MCP server SHALL attach to it over a remote debugging port.

#### Scenario: Legacy MCP tool is requested
- **WHEN** a fresh Claude Code session attempts any `mcp__claude-in-chrome__*` call
- **THEN** the settings permission layer denies the call before execution

#### Scenario: Active route inventory is validated
- **WHEN** the browser routing contract scans active global governance
- **THEN** it finds no positive claude-in-chrome, Open Browser Use, or Agent Chrome routing instruction
- **AND** prohibitions, deny fixtures, and historical records outside the active denominator do not count as routes

### Requirement: Chrome DevTools remains diagnostic-only

Active guidance SHALL select chrome-devtools only for console, network, performance, Lighthouse, heap, or explicitly isolated-browser diagnostics. It MUST NOT use chrome-devtools as a general page-fetch route. The user-scope chrome-devtools server SHALL launch Chrome Beta on demand with the Agent Chrome profile as its user data dir, so the diagnostic browser never registers under the daily Chrome bundle id.

#### Scenario: Diagnostic task requires DevTools
- **WHEN** a task centers on one of the allowed diagnostic purposes
- **THEN** chrome-devtools is selected directly

#### Scenario: Diagnostic browser is running when the user opens a link
- **WHEN** chrome-devtools has Chrome Beta open on the Agent Chrome profile and the user opens a link
- **THEN** the link opens in daily Chrome, not in the diagnostic browser
- **AND** the diagnostic browser exits when the chrome-devtools server exits

#### Scenario: Workflow only needs page content
- **WHEN** a workflow needs title, final URL, body text, navigation, or authenticated page interaction without a diagnostic purpose
- **THEN** it dispatches a page-fetch agent that reads through LCU
- **AND** it does not launch a chrome-devtools page-fetch agent

### Requirement: Page-fetch agents read through LCU

The page-fetch agents (`chrome-fetcher`, `chrome-devtools-fetcher`) SHALL keep their agent types and caller schema while reading through `mcp__lcu__js` only. They MUST return the existing required fields, cap body text at 4000 characters, compute `body_text_len` from the returned string, and close only the tabs they created on both success and failure.

#### Scenario: Workflow fetches one browser-rendered URL
- **WHEN** a workflow dispatches either page-fetch agent with one URL
- **THEN** the agent opens its own LCU task tab, reads title, final URL, and visible body from the real result, and returns the existing status／length／ok／error fields
- **AND** body text is capped at 4000 characters

#### Scenario: LCU read fails
- **WHEN** LCU is unavailable or navigation or extraction fails
- **THEN** the agent returns `ok=false` with the real error and does not fabricate page content

### Requirement: Paired search preserves same-query enforcement

Google SERP plus WebSearch pairing SHALL use LCU for the browser leg while preserving the same-query ticket model. A navigation ticket MUST be granted only for the same normalized Google query observed in a non-error LCU navigation result.

#### Scenario: Paired search completes
- **WHEN** a main session or `parallel-search` opens a Google SERP through LCU for query X and then calls WebSearch with query X
- **THEN** the hook allows the WebSearch call and consumes one query-X navigation ticket

#### Scenario: Query ticket is missing or mismatched
- **WHEN** WebSearch query X has no unused LCU navigation ticket for normalized query X
- **THEN** the hook denies the call with the pairing instructions
- **AND** a blocked attempt does not consume a ticket
