# browser-routing Specification

## Purpose
TBD - created by archiving change unify-browser-routing-to-obu. Update Purpose after archive.

## Requirements

### Requirement: General browser route uses OBU and Agent Chrome

Every active Claude Code route for general page navigation, reading, search, or authenticated interaction SHALL use Open Browser Use pinned to Agent Chrome. It MUST NOT fall back to daily Chrome when OBU is unavailable.

#### Scenario: Main session performs general browser work
- **WHEN** a main session needs to open, read, search, or interact with a webpage
- **THEN** it uses the user-scope `open_browser_use` MCP connected through the Agent Chrome-only resolver
- **AND** it does not select claude-in-chrome or general-purpose chrome-devtools

#### Scenario: OBU is unavailable
- **WHEN** the Agent Chrome resolver cannot identify exactly one approved socket or OBU lacks the required general-browser capability
- **THEN** the browser task stops with the route failure
- **AND** it does not fall back to daily Chrome

### Requirement: Legacy claude-in-chrome route is disabled

Active runtime guidance MUST NOT direct any general browser task to `claude-in-chrome`. User settings SHALL deny every `mcp__claude-in-chrome__*` tool.

#### Scenario: Legacy MCP tool is requested
- **WHEN** a fresh Claude Code session attempts any `mcp__claude-in-chrome__*` call
- **THEN** the settings permission layer denies the call before execution
- **AND** the legacy browser tool does not execute

#### Scenario: Active route inventory is validated
- **WHEN** the browser routing contract scans active global and project governance
- **THEN** it finds no positive claude-in-chrome routing instruction
- **AND** deny fixtures or historical records outside the active denominator do not count as routes

### Requirement: Chrome DevTools remains diagnostic-only

Active guidance SHALL select chrome-devtools only for console, network, performance, Lighthouse, heap, or explicitly isolated-browser diagnostics. It MUST NOT use chrome-devtools as a general page-fetch route.

#### Scenario: Diagnostic task requires DevTools
- **WHEN** a task centers on one of the allowed diagnostic purposes
- **THEN** chrome-devtools remains available and is selected directly
- **AND** the task is not forced through OBU

#### Scenario: Workflow only needs page content
- **WHEN** a workflow needs title, final URL, body text, navigation, or authenticated page interaction without a diagnostic purpose
- **THEN** it uses OBU on Agent Chrome
- **AND** it does not launch a chrome-devtools page-fetch agent

### Requirement: General page fetch agents use OBU

The existing page-fetch agents SHALL preserve their caller contracts while replacing claude-in-chrome and general-purpose chrome-devtools execution with one schema-compatible helper over the injected Agent Chrome-only CLI adapter. The helper MUST return the existing required fields, cap body text at 4000 characters, and finalize only its own session tabs on both success and failure.

#### Scenario: Workflow fetches one browser-rendered URL
- **WHEN** a workflow dispatches either existing page-fetch agent with one URL
- **THEN** the helper echoes the input URL, opens the URL, waits for the DOM, extracts title/final URL/body through OBU CDP, and derives the existing status／length／ok／error fields
- **AND** its agent type and output schema remain compatible with the existing caller
- **AND** body text is capped at 4000 characters

#### Scenario: Fetch navigation fails after opening a tab
- **WHEN** OBU navigation or extraction times out or fails after the session creates a tab
- **THEN** the helper returns the matching existing failure status and error evidence
- **AND** a separate same-session finalize runs before the helper exits

#### Scenario: Concurrent fetchers run
- **WHEN** multiple migrated page-fetch agents run under the same Claude parent
- **THEN** each receives a distinct OBU session id
- **AND** one fetcher's cleanup does not close or invalidate another fetcher's tab

### Requirement: Paired search preserves same-query enforcement

Google SERP plus WebSearch pairing SHALL use OBU for the browser leg while preserving the existing same-query ticket model. A navigation ticket MUST be granted only for the same normalized Google query observed through an approved OBU main-session or adapter route.

#### Scenario: Main session completes a paired search
- **WHEN** the main session opens a Google SERP through OBU for query X and then calls WebSearch with query X
- **THEN** the hook allows the WebSearch call
- **AND** consumes one query-X navigation ticket

#### Scenario: Parallel search agent completes a paired search
- **WHEN** `parallel-search` opens the Google SERP through its injected OBU adapter and then calls WebSearch with the identical query
- **THEN** the hook reads the subagent transcript, recognizes the adapter evidence, and allows the call
- **AND** the agent returns the two raw result sets in the existing output shape

#### Scenario: Query ticket is missing or mismatched
- **WHEN** WebSearch query X has no unused OBU navigation ticket for normalized query X
- **THEN** the hook denies the call with the OBU pairing instructions
- **AND** a blocked attempt does not consume a ticket

### Requirement: Browser-capable subagents retain per-agent isolation

Every browser-capable specialized agent SHALL receive an injected OBU session id and Agent Chrome-only adapter route. It MUST NOT use the parent-shared OBU MCP.

#### Scenario: Page-fetch agent or parallel-search starts
- **WHEN** any migrated page-fetch agent or `parallel-search` starts with a valid `agent_id`
- **THEN** the SubagentStart hook injects a deterministic distinct OBU session id
- **AND** names the same CLI adapter and cleanup contract used by generic routed agents

#### Scenario: Specialized agent reaches shared-MCP backstop
- **WHEN** a covered browser-capable specialized agent attempts `mcp__open_browser_use__.*`
- **THEN** the PreToolUse hook denies the shared MCP call
- **AND** returns the injected adapter route

### Requirement: Figma computed-style extraction follows the OBU route

The active dashboard Figma skill SHALL use OBU on Agent Chrome for rendered-page computed-style extraction. Main-session instructions MUST name OBU MCP CDP, and subagent-isolation instructions MUST name the CLI adapter CDP command.

#### Scenario: Main session compares rendered styles
- **WHEN** the Figma skill needs computed styles from the running dashboard
- **THEN** it uses `mcp__open_browser_use__cdp` on the Agent Chrome tab
- **AND** it does not call claude-in-chrome

#### Scenario: Covered subagent compares rendered styles
- **WHEN** the same skill runs with injected OBU subagent isolation context
- **THEN** it uses the adapter `cdp` command with the injected session id
- **AND** it does not use the parent-shared OBU MCP
