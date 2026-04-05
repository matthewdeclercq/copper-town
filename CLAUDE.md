# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**Copper-Town** is a LiteLLM-powered multi-agent automation system. Agents handle business tasks via a tool-calling engine with persistent memory, dynamic skills, and agent-to-agent delegation.

## Project Structure

```
.
├── run.py                     # CLI entry point
├── copper_town/               # Main package
│   ├── __init__.py            # Re-exports Engine
│   ├── config.py              # Paths, env vars, constants
│   ├── engine.py              # Completion loop, tool dispatch, delegation
│   ├── events.py              # EventBus + EventType enum
│   ├── background.py          # BackgroundTaskManager: task state, notifications, cancellation
│   ├── repl.py                # REPLSession: interactive prompt, spinner, slash-command dispatch
│   ├── terminal.py            # ANSI color constants
│   ├── manager.py             # AgentManager: concurrent runs, timeouts, cancellation
│   ├── memory_store.py        # SQLite memory: pinned entries, compression, WAL mode
│   ├── models.py              # AgentResult, AgentStatus, AgentRun
│   ├── tracer.py              # JSONL trace writer
│   ├── utils.py               # parse_markdown_frontmatter, interpolate_env
│   └── tools/                 # @tool-decorated Python modules
│       ├── __init__.py        # @tool decorator + ToolRegistry
│       ├── builtin.py         # read_file, list_files
│       ├── delegation.py      # delegate_to_agent, delegate_background, cancel_background_task (schemas only)
│       ├── gws.py             # gws CLI wrapper
│       ├── memory_tool.py     # remember (schema only)
│       ├── regen_gws_skills.py # regen-gws-skills subcommand
│       ├── skills.py          # search_skills, load_skill
│       ├── web_search.py      # web_search (ddgs/DuckDuckGo; navigator agent only)
│       └── write_skill.py     # write_skill
│   ├── sessions.py        # Session + SessionManager for HTTP API
│   ├── api.py             # Starlette app, endpoints, auth middleware
│   ├── polling.py          # PollChecker ABC + registry for trigger checkers
│   ├── scheduler.py        # Scheduler: reads triggers.yml, fires cron/poll triggers
│   └── mcp_registry.py    # MCPClientManager: lazy connect, tool dispatch
├── agents/                    # Agent definitions (one .md per agent)
├── skills/
│   ├── _global/               # Injected into ALL agents
│   ├── gws/                   # Google Workspace CLI skills (30+ files)
│   ├── generated/             # Runtime-authored skills (write_skill tool)
│   └── expense-receipts.md
├── memory/                    # SQLite memory database
├── traces/                    # Session trace JSONL files
├── web/                       # Static PWA files (served by `serve` subcommand)
│   ├── index.html             # PWA shell
│   ├── manifest.json          # PWA manifest
│   ├── sw.js                  # Service worker (offline shell caching)
│   ├── css/style.css          # Mobile-first responsive styles
│   └── js/                    # Vanilla JS modules (app, api, store)
├── triggers.yml               # Trigger definitions for scheduler daemon
└── mcp.yml                    # MCP server config (stdio/sse servers)
```

## Agent Definition Format

`agents/<slug>.md` — YAML frontmatter + markdown system prompt:

```yaml
---
name: My Agent
description: "One-line description."
tools:
  - read_file
delegates_to:
  - quartermaster
skills:
  - gws-gmail-send
mcp_servers:
  - github
memory_guidance: |
  What to save / not save to memory.
model: xai/grok-4-1-fast-non-reasoning-latest  # optional override
---
System prompt body...
```

- `tools`: always-on: `remember`, `search_skills`, `load_skill`; `delegate_background` and `cancel_background_task` added automatically when `delegates_to` is set; `delegate_to_agent` is opt-in (declare it in `tools:` to enable synchronous/blocking delegation); `write_skill` must be declared explicitly
- `skills`: found by `rglob` anywhere in `skills/`; `skills/_global/` injected into every agent
- `mcp_servers`: list of server slugs from `mcp.yml`; MCP tools are lazily connected on first use and shadow same-named `@tool` functions
- `${VAR_NAME}` in agent bodies and skill files is replaced with the env var value at prompt-build time

## Key Design Decisions

**Skills index**: `skills/generated/` files sort last in `_get_index()`, so a generated skill with the same `name` as a base skill silently overrides it. This is how the quartermaster agent self-corrects stale gws docs.

**Delegation**: `delegate_background` (non-blocking) is auto-added for any agent with `delegates_to`. Returns `task_id` immediately; completion notification injected at the next REPL turn via `BackgroundTaskManager` (`engine._bg`); results truncated to `BG_RESULT_MAX_CHARS=800`. `delegate_to_agent` (synchronous, blocking) is available opt-in: declare it in the agent's `tools:` list. The First Mate uses sync delegation to coordinate sequential multi-step projects while running as a background task from The Captain.

**Parallel tool execution**: when the LLM returns multiple tool calls in one response, they run concurrently via `asyncio.gather`. Not configurable.

**Memory**: `add()` exact-match deduplicates before insert. `pin=True` makes a fact immune to LLM compression. `replace_memories()` only soft-deletes unpinned rows. Session memory extraction runs only when `len(messages) >= MEMORY_MIN_MESSAGES=12`.

**Context window**: sliding window keeps last `MAX_CONTEXT_MESSAGES=40` messages. When `CONTEXT_SUMMARIZE=true`, evicted messages are LLM-summarized and prepended as a system message rather than simply dropped.

**Tool output**: truncated to `MAX_TOOL_OUTPUT_CHARS=10000` with a `[truncated N chars]` suffix.

**GWS auth errors**: `gws.py` detects keyring/auth/credential/token keywords in stderr from a non-zero exit and returns a structured error with `"Do not retry this command"`. The quartermaster agent is instructed to stop immediately and report the failure rather than loop. Users must run `gws auth login` to restore credentials.

**GWS skill regen** (`regen_gws_skills.py`): fetches all skills from the upstream `googleworkspace/cli` GitHub repo at the exact installed `gws` version tag (e.g. `v0.22.3`). Converts upstream `SKILL.md` frontmatter (nested `metadata.version`, `metadata.openclaw.cliHelp`) to Copper-Town's flat format (`name`, `description`, `version`, `cli_help`). Writes to `skills/gws/<name>.md` and removes any local files not present upstream. No LLM involved — upstream content is authoritative.

**Scheduler/Triggers**: `triggers.yml` defines cron and poll triggers. The `daemon` subcommand runs a tick loop (`SCHEDULER_TICK_INTERVAL=30s`) that checks each trigger. Cron triggers fire if the most recent scheduled time is within 2x tick interval and hasn't been fired yet. Poll triggers call a `PollChecker` subclass; if it returns a truthy string, the trigger fires with `${poll_result}` interpolation. `state.running` prevents overlapping fires. No persistent state — all timing resets on restart.

**Poll checkers**: `PollChecker` ABC in `polling.py` with `check(**kwargs) -> str | None`. Register via `register_checker(name, cls)`. Checkers get `setup()`/`teardown()` lifecycle calls from the scheduler. `NullChecker` is the only built-in (always returns `None`).

**MCP connectors**: external services are wired in via `mcp.yml` — no new Python code per connector. Each entry names a transport (`stdio` or `sse`) and its connection parameters. Env values in `mcp.yml` support `${VAR}` interpolation. `MCPClientManager` (`copper_town/mcp_registry.py`) connects lazily on first tool call and keeps sessions alive for the process lifetime. MCP tool schemas shadow same-named `@tool` functions, enabling gradual migration of the gws connector. The existing `gws` connector is unchanged.

## Interactive REPL Slash Commands

Available in any interactive session (no LLM round-trip):

| Command | Description |
|---------|-------------|
| `/help` | Show all slash commands |
| `/tasks` | List active background tasks with full descriptions |
| `/cancel [task_id]` | Cancel a background task (omit `task_id` if only one active) |
| `/memory` | Show this agent's memory entries |
| `/agents` | List all loaded agents with slug, name, description, and delegation targets |
| `/clear` | Reset conversation to system prompt only |
| `/model [name]` | Show current model or switch to a new one |

All handlers live in `REPLSession` in `repl.py`.

## Adding a New Agent

1. Create `agents/<slug>.md`
2. Add `delegates_to: [<slug>]` in any parent agent
3. If it needs custom tools, add `copper_town/tools/<slug>.py` with `@tool`-decorated functions

## Adding a New Skill

1. Create `skills/<name>.md` with `name` and `description` frontmatter
2. Declare it in the agent's `skills:` list — engine finds it anywhere in `skills/`

## Adding an MCP Server

1. Add a server entry to `mcp.yml` with an `agents` list:
   ```yaml
   servers:
     github:
       transport: stdio
       command: ["npx", "-y", "@modelcontextprotocol/server-github"]
       env:
         GITHUB_PERSONAL_ACCESS_TOKEN: "${GITHUB_TOKEN}"
       agents: [captain, navigator]   # or ["*"] for all agents
   ```
   Supported transports: `stdio` (command + args) and `sse` (url). Env values support `${VAR}` interpolation.
2. MCP tools are discovered at connection time and shadow same-named `@tool` functions

Agent frontmatter `mcp_servers` still works and is merged with `mcp.yml` assignments.

## Adding a Trigger

Add an entry to `triggers.yml`:
```yaml
triggers:
  my-cron-trigger:
    type: cron
    agent: captain
    task: "Do something on schedule."
    schedule: "0 9 * * 1-5"    # cron expression
    timeout: 120
    enabled: true

  my-poll-trigger:
    type: poll
    agent: purser
    task: "Process: ${poll_result}"
    checker: my-checker          # registered PollChecker name
    checker_args:
      label: "some-value"
    interval: 300                # seconds between checks
    enabled: true
```

## Adding a Poll Checker

1. Create a `PollChecker` subclass (e.g., in `copper_town/tools/` or a new module)
2. Register it in `copper_town/polling.py`:
   ```python
   from copper_town.polling import PollChecker, register_checker

   class MyChecker(PollChecker):
       async def check(self, **kwargs) -> str | None:
           # Return a string to fire the trigger, None to skip
           return None

   register_checker("my-checker", MyChecker)
   ```
3. Reference it by name in `triggers.yml` `checker` field

## HTTP API (`serve` subcommand)

Starts a Starlette app on `API_HOST:API_PORT`. Auth: `X-Api-Key` header if `API_KEY` is set (`/health` is always public).

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness check |
| `GET` | `/api/agents` | List all loaded agents |
| `POST` | `/api/sessions` | Create session `{"agent": "<slug>"}` → `{"session_id": ..., "agent": ...}` |
| `GET` | `/api/sessions` | List active sessions |
| `DELETE` | `/api/sessions/{id}` | Delete session (triggers background memory extraction) |
| `POST` | `/api/sessions/{id}/messages` | Send message `{"content": "..."}` → SSE stream |
| `GET` | `/api/sessions/{id}/messages` | Fetch user/assistant messages |
| `GET` | `/api/tasks` | List active background tasks |

**SSE event types** (from `POST .../messages`):
- `token` — streaming token chunk `{"t": "..."}`
- `done` — final response `{"content": "..."}`
- `error` — failure `{"error": "..."}`
- `notifications` — completed background task summaries (array of strings)
- `tasks` — newly launched background tasks `[{"task_id": ..., "name": ...}]`

Static PWA files from `web/` are mounted at `/` if the directory exists.

## Development

**Setup** (first time):
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # then fill in API keys
```

**Always use the project virtualenv** for running or installing packages:
```bash
.venv/bin/python run.py <agent-slug>       # interactive REPL with an agent (default: captain)
.venv/bin/python run.py -t "do something"  # single-task, non-interactive
.venv/bin/pip install <package>             # install a dependency
.venv/bin/python -c "import copper_town"    # quick import check
```
Do not use the system Python — it will be missing project dependencies.

There are no automated tests or linting configs in this project.

**CLI subcommands** (not routed through argparse):
```bash
.venv/bin/python run.py show-trace              # inspect most recent trace
.venv/bin/python run.py show-trace path/to.jsonl  # inspect a specific trace
.venv/bin/python run.py regen-gws-skills        # regenerate all gws skill files
.venv/bin/python run.py regen-gws-skills gmail  # regenerate only matching skills
.venv/bin/python run.py daemon                  # run scheduler daemon
.venv/bin/python run.py daemon -v               # daemon with verbose trace output
.venv/bin/python run.py serve                   # start HTTP API + PWA server
.venv/bin/python run.py serve -v                # serve with verbose trace output
```

**Useful flags**:
```bash
--verbose / -v    # stream trace events to stderr in real time
--trace           # write trace file silently; print path at end
--model NAME      # override MODEL env var for this run
--list-agents     # show all agents with tools and delegation targets
--list-tools      # show all registered @tool functions
--parallel "agent1:task1" "agent2:task2"  # run multiple agents concurrently
```

**Environment variables** (set in `.env` or shell; see `.env.example`):
- `MODEL` — LiteLLM model string, e.g. `xai/grok-4-latest`, `anthropic/claude-sonnet-4-20250514` (default: `xai/grok-4-latest`)
- `XAI_API_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / etc. — provider key for the chosen model
- `ALLOWED_READ_DIRS` — colon-separated dirs agents may read (default: project root only)
- `LOG_LEVEL` — Python logging level (default: `WARNING`)
- `CONTEXT_SUMMARIZE` — `true`/`false`; summarize evicted context instead of dropping (default: `true`)
- `MEMORY_COMPRESS_ENABLED` — set to `false` if memory contains sensitive data you don't want sent to the LLM
- `MEMORY_MAX_LINES` — row count threshold that triggers LLM memory compression (default: `30`)
- `MEMORY_WRITE_MAX_CHARS` — max chars accepted per `remember()` call (default: `2000`)
- `MAX_PARALLEL_TOOLS` — max concurrent tool calls per LLM response (default: `4`)
- `MAX_TOOL_OUTPUT_CHARS` — tool output truncation limit (default: `10000`)
- `MAX_SYSTEM_PROMPT_CHARS` — system prompt truncation limit (default: `50000`)
- `DELEGATION_RETRY_COUNT` — times to retry a failed delegation (default: `1`)
- `MAX_CONCURRENT_AGENTS` — max agents running in parallel via AgentManager (default: `10`)
- `AGENT_DEFAULT_TIMEOUT` — timeout for parallel agent runs in seconds (default: `300.0`)
- `SCHEDULER_TICK_INTERVAL` — seconds between scheduler ticks (default: `30.0`)
- `TRIGGER_DEFAULT_TIMEOUT` — default timeout for trigger-fired tasks in seconds (default: `300.0`)
- `API_HOST` — bind address for HTTP API (default: `0.0.0.0`)
- `API_PORT` — port for HTTP API (default: `8420`)
- `API_KEY` — API key for authenticating `/api/*` requests (empty = no auth)
- `SESSION_TTL_SECONDS` — session expiry in seconds (default: `7200`)
- `MAX_CONCURRENT_SESSIONS` — max simultaneous chat sessions (default: `20`)
