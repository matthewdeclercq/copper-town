# CLAUDE.md

Guidance for Claude Code when working in this repository.

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
│       ├── web_search.py      # web_search (DuckDuckGo; research agent only)
│       └── write_skill.py     # write_skill
│   └── mcp_registry.py    # MCPClientManager: lazy connect, tool dispatch
├── agents/                    # Agent definitions (one .md per agent)
├── skills/
│   ├── _global/               # Injected into ALL agents
│   ├── gws/                   # Google Workspace CLI skills (30+ files)
│   ├── generated/             # Runtime-authored skills (write_skill tool)
│   └── expense-receipts.md
├── memory/                    # SQLite memory database
├── traces/                    # Session trace JSONL files
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
- `delegate_background` — non-blocking; returns `task_id` immediately; completion notification injected at the next REPL turn via `_bg_notifications`; results truncated to `BG_RESULT_MAX_CHARS=800`

**Parallel tool execution**: when the LLM returns multiple tool calls in one response, they run concurrently via `asyncio.gather`. Not configurable.

**Memory**: `add()` exact-match deduplicates before insert. `pin=True` makes a fact immune to LLM compression. `replace_memories()` only soft-deletes unpinned rows. Session memory extraction runs only when `len(messages) >= MEMORY_MIN_MESSAGES=12`.

**Context window**: sliding window keeps last `MAX_CONTEXT_MESSAGES=40` messages. When `CONTEXT_SUMMARIZE=true`, evicted messages are LLM-summarized and prepended as a system message rather than simply dropped.

**Tool output**: truncated to `MAX_TOOL_OUTPUT_CHARS=10000` with a `[truncated N chars]` suffix.

**GWS auth errors**: `gws.py` detects keyring/auth/credential/token keywords in stderr from a non-zero exit and returns a structured error with `"Do not retry this command"`. The google-workspace agent is instructed to stop immediately and report the failure rather than loop. Users must run `gws auth login` to restore credentials.

**GWS skill regen** (`regen_gws_skills.py`): reads `metadata.openclaw.cliHelp` from frontmatter to get the help command; falls back to deriving it from the skill name (`gws-workflow-file-announce` → `gws workflow +file-announce --help`, `gws-shared` → `gws --help`). Bumps patch version in frontmatter after rewriting.

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

All handlers live in `run_interactive` in `engine.py`, after the `/cancel` block.

## Adding a New Agent

1. Create `agents/<slug>.md`
2. Add a row to `AGENTS.md`
3. Add `delegates_to: [<slug>]` in any parent agent
4. If it needs custom tools, add `copper_town/tools/<slug>.py` with `@tool`-decorated functions

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
       agents: [mini-me, research]   # or ["*"] for all agents
   ```
   Supported transports: `stdio` (command + args) and `sse` (url). Env values support `${VAR}` interpolation.
2. MCP tools are discovered at connection time and shadow same-named `@tool` functions

Agent frontmatter `mcp_servers` still works and is merged with `mcp.yml` assignments.

## Development

**Always use the project virtualenv** for running, testing, or installing packages:
```bash
.venv/bin/python run.py <agent-slug>       # run an agent
.venv/bin/pip install <package>             # install a dependency
.venv/bin/python -c "import copper_town"    # quick import check
```
Do not use the system Python — it will be missing project dependencies.
