# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Copper-Town** is a LiteLLM-powered multi-agent automation system. A hierarchy of agents handles business tasks (expense receipts, Google Workspace operations, etc.) using a tool-calling engine with persistent memory, dynamic skills, and agent-to-agent delegation.

## Project Structure

```
.
├── agents/                    # Per-agent directories
│   ├── mini-me/               # Top-level orchestrator
│   ├── accounting/            # Expense receipts & accounting
│   └── google-workspace/      # Google Workspace operations via gws CLI
│       └── agent.md           # YAML frontmatter + system prompt body
│       └── memory.md          # Persistent per-agent memory (auto-created)
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
│   └── skills.py              # search_skills, load_skill (with in-memory index)
├── memory/
│   └── global.md              # Shared memory across all agents
├── engine.py                  # Core: agent loading, tool dispatch, completion loop, delegation
├── config.py                  # Env loading, paths, constants
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

Each agent is defined in `agents/<slug>/agent.md` with YAML frontmatter + a markdown system prompt body:

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

- `tools`: tool names the agent may call (always-on: `remember`, `search_skills`, `load_skill`, `delegate_to_agent` if `delegates_to` is set)
- `delegates_to`: slugs the agent is allowed to delegate to
- `skills`: skill names injected into the system prompt at startup (searches entire `skills/` tree via `rglob`)
- `model`: optional per-agent model override (e.g. use Haiku for cheap sub-agents)

### Skills

Skills are markdown files in `skills/` with YAML frontmatter (`name`, `description`) and a body of instructions. Skills in `skills/_global/` are injected into **all** agents. Agent-declared skills are found by `rglob` anywhere in `skills/`.

The `gws/gws-shared.md` skill is the prerequisite for all `gws` skills (auth, global flags, security rules). Always load it before a specific gws skill.

### LiteLLM Engine

```bash
python run.py                        # interactive with Mini Me
python run.py accounting             # interactive with Accounting
python run.py -t "process receipt"   # single-task mode
python run.py --list-agents          # show available agents
python run.py --list-tools           # show available tools
MODEL=gpt-4o python run.py           # different provider
```

**Key engine features:**
- Provider-agnostic via `MODEL` env var (Anthropic, OpenAI, Gemini, Groq, Ollama)
- Agent-to-agent delegation with depth limits (`MAX_DELEGATION_DEPTH=3`) and whitelist enforcement
- Tool authorization guard: rejects tool calls not in the agent's allowed set
- Sliding context window: keeps system prompt + last `MAX_CONTEXT_MESSAGES=40` messages
- Retry logic: 3 attempts with exponential backoff on `RateLimitError`/`APIConnectionError`
- REPL exception recovery: API errors print a message and preserve the session
- Per-agent model override via `model:` frontmatter field
- Thread-safe token usage tracking via `threading.local()`
- Persistent memory: per-agent (`agents/<slug>/memory.md`) and global (`memory/global.md`), with LLM-based deduplication when over `MEMORY_MAX_LINES=100`
- End-of-session memory extraction: auto-saves durable facts from the conversation
- Env var interpolation in skills/agent bodies: `${VAR_NAME}` is replaced with the env var value at prompt-build time

## Development Commands

```bash
pip install -r requirements.txt   # Install dependencies
cp .env.example .env              # Set up API keys
python run.py --list-agents       # Verify agents loaded
python run.py --list-tools        # Verify tools registered
```

## Architecture Notes

- **`engine.py`**: `AgentDefinition` dataclass holds slug, name, description, tools, delegates_to, skills, body, and `model`. `_completion_loop` drives the LLM ↔ tool loop with context trimming and the tool authorization check. `_handle_delegation` passes an optional `context` string from the parent agent to the sub-agent's message list. `_handle_remember` returns `current_memory` in its response so agents see updated memory immediately.
- **`tools/__init__.py`**: `_python_type_to_json_schema` handles `str`, `int`, `float`, `bool`, `list`, `dict`, and `Optional[X]` / `Union[X, None]`.
- **`tools/skills.py`**: `_get_index()` builds a module-level in-memory index of all skills on first call; subsequent calls are instant.
- **`tools/delegation.py`**: `delegate_to_agent(agent, task, context="")` — `context` is forwarded as a system message to the sub-agent.
- **`config.py`**: Key constants — `MAX_TOOL_ITERATIONS=20`, `MAX_DELEGATION_DEPTH=3`, `MAX_CONTEXT_MESSAGES=40`, `MEMORY_MAX_LINES=100`.

## Adding a New Agent

1. Create `agents/<slug>/agent.md` with the frontmatter + system prompt.
2. Add a row to [AGENTS.md](AGENTS.md).
3. Add `delegates_to: [<slug>]` in any parent agent that should route to it.
4. If it needs custom tools, add `tools/<slug>.py` with `@tool`-decorated functions.

## Adding a New Skill

1. Create `skills/<name>.md` with `---\nname: <name>\ndescription: "..."\n---` frontmatter.
2. Write the instructions in the body.
3. Declare it in agent frontmatter (`skills: [<name>]`) — the engine will find it anywhere in `skills/`.
