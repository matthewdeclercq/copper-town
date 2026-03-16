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
│       ├── delegation.py      # delegate_to_agent, delegate_background (schemas only)
│       ├── gws.py             # gws CLI wrapper
│       ├── memory_tool.py     # remember (schema only)
│       ├── regen_gws_skills.py # regen-gws-skills subcommand
│       ├── skills.py          # search_skills, load_skill
│       ├── web_search.py      # web_search (ddgs/DuckDuckGo; web-surfer agent only)
│       └── write_skill.py     # write_skill
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
  - google-workspace
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

- `tools`: always-on: `remember`, `search_skills`, `load_skill`; delegation tools added automatically when `delegates_to` is set; `write_skill` must be declared explicitly
- `skills`: found by `rglob` anywhere in `skills/`; `skills/_global/` injected into every agent
- `mcp_servers`: list of server slugs from `mcp.yml`; MCP tools are lazily connected on first use and shadow same-named `@tool` functions
- `${VAR_NAME}` in agent bodies and skill files is replaced with the env var value at prompt-build time

## Key Design Decisions

**Skills index**: `skills/generated/` files sort last in `_get_index()`, so a generated skill with the same `name` as a base skill silently overrides it. This is how the google-workspace agent self-corrects stale gws docs.

**Delegation**:
- `delegate_to_agent` — synchronous; blocks until sub-agent finishes; passes optional `context` as a system message
- `delegate_background` — non-blocking; returns `task_id` immediately; completion notification injected at the next REPL turn via `BackgroundTaskManager` (`engine._bg`); results truncated to `BG_RESULT_MAX_CHARS=800`

**Parallel tool execution**: when the LLM returns multiple tool calls in one response, they run concurrently via `asyncio.gather`. Not configurable.

**Memory**: `add()` exact-match deduplicates before insert. `pin=True` makes a fact immune to LLM compression. `replace_memories()` only soft-deletes unpinned rows. Session memory extraction runs only when `len(messages) >= MEMORY_MIN_MESSAGES=12`.

**Context window**: sliding window keeps last `MAX_CONTEXT_MESSAGES=40` messages. When `CONTEXT_SUMMARIZE=true`, evicted messages are LLM-summarized and prepended as a system message rather than simply dropped.

**Tool output**: truncated to `MAX_TOOL_OUTPUT_CHARS=10000` with a `[truncated N chars]` suffix.

**GWS auth errors**: `gws.py` detects keyring/auth/credential/token keywords in stderr from a non-zero exit and returns a structured error with `"Do not retry this command"`. The google-workspace agent is instructed to stop immediately and report the failure rather than loop. Users must run `gws auth login` to restore credentials.

**GWS skill regen** (`regen_gws_skills.py`): reads `metadata.openclaw.cliHelp` from frontmatter to get the help command; falls back to deriving it from the skill name (`gws-workflow-file-announce` → `gws workflow +file-announce --help`, `gws-shared` → `gws --help`). Bumps patch version in frontmatter after rewriting.

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
       agents: [mini-me, web-surfer]   # or ["*"] for all agents
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
    agent: mini-me
    task: "Do something on schedule."
    schedule: "0 9 * * 1-5"    # cron expression
    timeout: 120
    enabled: true

  my-poll-trigger:
    type: poll
    agent: accounting
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

## Development

**Setup** (first time):
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # then fill in API keys
```

**Always use the project virtualenv** for running or installing packages:
```bash
.venv/bin/python run.py <agent-slug>       # interactive REPL with an agent
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
- `CONTEXT_SUMMARIZE` — `true`/`false`; summarize evicted context instead of dropping it
- `MEMORY_COMPRESS_ENABLED` — set to `false` if memory contains sensitive data you don't want sent to the LLM
- `SCHEDULER_TICK_INTERVAL` — seconds between scheduler ticks (default: `30.0`)
- `TRIGGER_DEFAULT_TIMEOUT` — default timeout for trigger-fired tasks in seconds (default: `300.0`)
