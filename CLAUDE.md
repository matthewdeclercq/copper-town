# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Copper-Town** is a LiteLLM-powered multi-agent automation system. A hierarchy of agents handles business tasks (expense receipts, Google Workspace operations, etc.) using a tool-calling engine with persistent memory, dynamic skills, and agent-to-agent delegation.

## Project Structure

```
.
├── agents/                    # Agent definition files (one .md per agent)
│   ├── mini-me.md             # Top-level orchestrator
│   ├── accounting.md          # Expense receipts & accounting
│   └── google-workspace.md    # Google Workspace operations via gws CLI
├── skills/                    # Reusable skill instructions (markdown)
│   ├── _global/               # Injected into ALL agents
│   ├── gws/                   # Google Workspace CLI skills (20+ skill files)
│   └── expense-receipts.md    # Expense receipt workflow
├── tools/                     # Python tool framework
│   ├── __init__.py            # @tool decorator + ToolRegistry
│   ├── builtin.py             # read_file, list_files
│   ├── delegation.py          # delegate_to_agent (schema; engine intercepts)
│   ├── gws.py                 # gws CLI wrapper tool
│   ├── memory_tool.py         # remember tool (schema; engine intercepts)
│   ├── skills.py              # search_skills, load_skill (with in-memory index)
│   └── write_skill.py         # write_skill — creates skills/generated/<name>.md at runtime
├── skills/
│   └── generated/             # Runtime-authored skills (written by agents via write_skill)
│       └── README.md          # Constitution: what agents may/must not write
├── memory/
├── traces/                    # Per-session JSONL trace files (auto-created)
├── engine.py                  # Core: agent loading, tool dispatch, completion loop, delegation
├── config.py                  # Env loading, paths, constants
├── tracer.py                  # SessionTracer: JSONL writer + verbose stderr output
├── run.py                     # CLI entry point
├── requirements.txt           # Python dependencies
├── .env.example               # API key template
├── AGENTS.md                  # Agent inventory — what exists, when to use each
└── CLAUDE.md                  # This file
```

## Agent System

**Mini Me** is the top-level agent: in charge of all other agents and reports to the user. The full inventory is in [AGENTS.md](AGENTS.md).

### Current Agents

| Agent | Slug | Role |
|-------|------|------|
| Mini Me | `mini-me` | Orchestrator; delegates to sub-agents, reports to user |
| Accounting | `accounting` | Expense receipts and accounting tasks |
| Google Workspace | `google-workspace` | All Workspace operations via `gws` CLI |

### Agent Definition Format

Each agent is defined in `agents/<slug>.md` with YAML frontmatter + a markdown system prompt body:

```yaml
---
name: My Agent
description: "Short description for the agent inventory."
tools:
  - read_file
  - list_files
delegates_to:
  - google-workspace
skills:
  - gws-gmail-send
model: xai/grok-4-1-fast-non-reasoning-latest   # optional — overrides global MODEL
---

System prompt body goes here...
```

- `tools`: tool names the agent may call (always-on: `remember`, `search_skills`, `load_skill`, `delegate_to_agent` if `delegates_to` is set; `write_skill` must be declared explicitly)
- `delegates_to`: slugs the agent is allowed to delegate to
- `skills`: skill names injected into the system prompt at startup (searches entire `skills/` tree via `rglob`)
- `model`: optional per-agent model override (e.g. use Haiku for cheap sub-agents)

### Skills

Skills are markdown files in `skills/` with YAML frontmatter (`name`, `description`) and a body of instructions. Skills in `skills/_global/` are injected into **all** agents. Agent-declared skills are found by `rglob` anywhere in `skills/`.

The `gws/gws-shared.md` skill is the prerequisite for all `gws` skills (auth, global flags, security rules). Always load it before a specific gws skill.

### LiteLLM Engine

```bash
python3 run.py                        # interactive with Mini Me
python3 run.py accounting             # interactive with Accounting
python3 run.py -t "process receipt"   # single-task mode
python3 run.py --list-agents          # show available agents
python3 run.py --list-tools           # show available tools
python3 run.py --verbose -t "task"    # stream trace events to stderr in real-time
python3 run.py --trace -t "task"      # write trace file silently; print path at end
python3 run.py show-trace             # inspect most recent trace (timeline + summary)
python3 run.py show-trace <file>      # inspect a specific trace file
MODEL=gpt-4o python3 run.py           # different provider
```

**Key engine features:**
- Provider-agnostic via `MODEL` env var (Anthropic, OpenAI, Gemini, Groq, Ollama)
- Agent-to-agent delegation with depth limits (`MAX_DELEGATION_DEPTH=3`), whitelist enforcement, and auto-retry (`DELEGATION_RETRY_COUNT=1`)
- Tool authorization guard: rejects tool calls not in the agent's allowed set
- Sliding context window: keeps system prompt + last `MAX_CONTEXT_MESSAGES=40` messages
- Retry logic: 3 attempts with exponential backoff on `RateLimitError`/`APIConnectionError`
- REPL exception recovery: API errors print a message and preserve the session
- Per-agent model override via `model:` frontmatter field
- Token usage tracking via `contextvars.ContextVar`
- Persistent memory: SQLite-backed per-agent and global memory; exact-match dedup on every insert; LLM compression when over `MEMORY_MAX_LINES=30`; `pin=True` on `remember` makes a fact immune to compression
- End-of-session memory extraction: auto-saves durable facts from the conversation; wrapped in a spinner in interactive mode
- Env var interpolation in skills/agent bodies: `${VAR_NAME}` is replaced with the env var value at prompt-build time
- Runtime skill authoring: agents with `write_skill` can create `skills/generated/<name>.md` files; index is hot-reloaded immediately
- Observability: `--verbose` streams colored trace events to stderr in real-time; `--trace` writes a JSONL trace file silently; `show-trace` renders a timeline + summary for post-mortem inspection
- Interactive REPL UX: streaming token output via `_call_llm_stream`; responses rendered as rich Markdown via the `rich` library; readline history persisted to `~/.copper_history`; elapsed time shown per turn

## Development Commands

```bash
pip3 install -r requirements.txt   # Install dependencies
cp .env.example .env              # Set up API keys
python3 run.py --list-agents       # Verify agents loaded
python3 run.py --list-tools        # Verify tools registered
python3 run.py show-trace          # Inspect most recent trace
```

## Architecture Notes

- **`engine.py`**: `AgentDefinition` dataclass holds slug, name, description, tools, delegates_to, skills, body, and `model`. `_completion_loop` drives the LLM ↔ tool loop with context trimming and the tool authorization check; accepts optional `on_token: Callable[[str], None]` for streaming interactive output (non-interactive callers pass nothing); publishes `LLM_CALL_COMPLETE` with token counts and latency after each LLM call. `_call_llm_stream` yields text chunks via `litellm.acompletion(stream=True)`; silently yields nothing when the response contains tool calls so `_completion_loop` can fall back to the non-streaming path for tool dispatch. `_spinner` context manager yields a `stop_fn()` callable so the first streaming token can kill the spinner immediately. `_execute_tool_call` wraps every dispatch in try/except/finally timing and publishes `TOOL_CALL_COMPLETE` with success/error. `_handle_delegation` passes an optional `context` string from the parent agent's message list and retries up to `DELEGATION_RETRY_COUNT` times on failure. `_handle_remember` accepts `pin=True` to mark facts immune to compression; returns `current_memory` so agents see updated memory immediately. `_maybe_compress_memory` only compresses unpinned entries; pinned rows survive via `replace_memories`.
- **`tracer.py`**: `SessionTracer` subscribes to all events via `event_bus.subscribe_all()`. Writes one JSON line per event to `traces/<timestamp>_<agent>.jsonl`. With `verbose=True`, prints colored lines to stderr in real-time. `close()` writes `session_close` record and optionally prints the trace path.
- **`tools/__init__.py`**: `_python_type_to_json_schema` handles `str`, `int`, `float`, `bool`, `list`, `dict`, and `Optional[X]` / `Union[X, None]`.
- **`tools/skills.py`**: `_get_index()` builds a module-level in-memory index of all skills on first call; subsequent calls are instant. `_INDEX` can be set to `None` under `_INDEX_LOCK` to force a hot-reload (done by `write_skill`).
- **`tools/write_skill.py`**: Writes `skills/generated/<name>.md`, validates name/frontmatter/body, blocks forbidden patterns, and invalidates the skills index for immediate discoverability.
- **`tools/delegation.py`**: `delegate_to_agent(agent, task, context="")` — `context` is forwarded as a system message to the sub-agent.
- **`memory_store.py`**: `add()` does an exact-match dedup SELECT before INSERT; returns `None` on duplicate. `add_bulk()` loops through `add()`. `replace_memories()` only soft-deletes unpinned entries. `get_memory_text()` emits pinned entries first in `[Pinned]...[/Pinned]` tags.
- **`config.py`**: Key constants — `MAX_TOOL_ITERATIONS=20`, `MAX_DELEGATION_DEPTH=3`, `MAX_CONTEXT_MESSAGES=40`, `MEMORY_MAX_LINES=30` (env-overridable), `DELEGATION_RETRY_COUNT=1` (env-overridable). `TRACES_DIR` points to `traces/` in the repo root.

## Adding a New Agent

1. Create `agents/<slug>.md` with the frontmatter + system prompt.
2. Add a row to [AGENTS.md](AGENTS.md).
3. Add `delegates_to: [<slug>]` in any parent agent that should route to it.
4. If it needs custom tools, add `tools/<slug>.py` with `@tool`-decorated functions.

## Adding a New Skill

1. Create `skills/<name>.md` with `---\nname: <name>\ndescription: "..."\n---` frontmatter.
2. Write the instructions in the body.
3. Declare it in agent frontmatter (`skills: [<name>]`) — the engine will find it anywhere in `skills/`.

Agents with `write_skill` in their tools list can also create skills at runtime in `skills/generated/`. See `skills/generated/README.md` for what they may and must not write.
