# Copper-Town

> **Learning project:** Built to explore multi-agent harness design patterns. The CLI is functional; the web UI was never tested.


A LiteLLM-powered multi-agent AI assistant. Talk to **The Captain** — it routes your tasks to the right specialist agent automatically.

## How it works

Each agent is a plain Markdown file in `agents/` with YAML frontmatter declaring its name, tools, and delegation permissions. The engine reads these definitions at startup — no code changes needed to add or reconfigure an agent.

When you send a message, it goes to **The Captain**. The Captain decides whether to handle it directly or dispatch it to a specialist via `delegate_background`. Delegation is non-blocking: the Captain reports back immediately and delivers the result when the sub-agent finishes. Sub-agents can delegate further (The First Mate orchestrates multi-step pipelines across the rest of the crew).

MCP servers are wired in via `mcp.yml` and mounted lazily per-agent on first tool call. Memory is per-agent and persisted across turns. Scheduled tasks and poll-based triggers are defined in `triggers.yml`.

## Prerequisites

- Python 3.11+
- Docker (required for The Boatswain's sandboxed code execution)
- API key for any [LiteLLM-supported](https://docs.litellm.ai/docs/providers) provider

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # add your API key and set MODEL
```

## Running

```bash
.venv/bin/python run.py                        # chat with The Captain (default)
.venv/bin/python run.py purser                 # talk directly to a specific agent
.venv/bin/python run.py -t "process receipt"   # one-shot task, then exit
```

## Agents

| Agent | What it does |
|-------|-------------|
| **The Captain** | Top-level orchestrator — routes tasks, delegates to the crew, reports back |
| **The First Mate** | Project coordinator — breaks complex tasks into steps and runs them in sequence |
| **The Purser** | Accounting — expense receipts and tracking |
| **The Quartermaster** | Google Workspace — Gmail, Drive, Calendar, Sheets, Docs, and more |
| **The Navigator** | Web search and research |
| **The Helmsman** | Browser control — navigate pages, fill forms, take screenshots |
| **The Boatswain** | Code execution — writes and runs scripts in a sandboxed workspace |
| **The Signalman** | Notifications — sends summaries and alerts via Gmail |

## Slash commands

Type these in the interactive REPL for instant control without an LLM round-trip:

| Command | Description |
|---------|-------------|
| `/help` | Show all slash commands |
| `/tasks` | List active background tasks |
| `/cancel [task_id]` | Cancel a background task |
| `/memory` | Show this agent's memory entries |
| `/agents` | List all available agents |
| `/clear` | Clear conversation history (keeps system prompt) |
| `/model [name]` | Show current model or switch to a new one |

## Switching models

Set `MODEL` in `.env` to any [LiteLLM-supported](https://docs.litellm.ai/docs/providers) model string. Per-agent overrides go in the agent's `model:` frontmatter field.

## Observability

```bash
.venv/bin/python run.py --verbose -t "task"   # stream live events to stderr
.venv/bin/python run.py show-trace            # inspect the most recent trace
```

## Adding MCP servers

Wire in external tools (GitHub, Slack, filesystem, etc.) via `mcp.yml` — no new Python code needed per connector:

```yaml
servers:
  github:
    transport: stdio
    command: ["npx", "-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "${GITHUB_TOKEN}"
    agents: [captain, navigator]   # or ["*"] for all agents
```

The server connects lazily on first tool call. Supported transports: `stdio` and `sse`. You can also assign servers per-agent via `mcp_servers` in agent frontmatter — both sources are merged.

## Security

### File system access

Agents can only read files within explicitly allowed directories. By default this is the project root only. To grant access to other paths (e.g. `~/Downloads` for receipt uploads), set `ALLOWED_READ_DIRS` in `.env`:

```bash
ALLOWED_READ_DIRS=/Users/you/Downloads:/Users/you/Desktop
```

Write access is restricted to The Boatswain, which is further constrained to `BOATSWAIN_SANDBOX_DIR` (default: `sandbox/` inside the project root).

### Boatswain sandbox (`run_shell`)

The Boatswain executes shell commands inside a disposable Docker container — no fallback to the host environment. Docker must be running.

| Property | Value |
|---|---|
| Filesystem | `sandbox/` only |
| Network | None |
| Memory | 512 MB cap |
| CPU | 1 core cap |

```bash
# .env — customize the runtime image
BOATSWAIN_DOCKER_IMAGE=python:3.12-slim   # or node:20-slim, ubuntu:24.04, etc.
```

## Scheduled triggers

Define cron and poll-based triggers in `triggers.yml` — no code required:

```yaml
triggers:
  daily-summary:
    type: cron
    agent: captain
    task: "Summarize today's activity."
    schedule: "0 18 * * *"   # 6 PM daily
    enabled: true

  new-receipts:
    type: poll
    agent: purser
    task: "Process new receipt: ${poll_result}"
    checker: gmail-label
    checker_args:
      label: "Receipts/Unprocessed"
    interval: 300             # seconds between checks
    enabled: true
```

The scheduler runs automatically alongside the API server. Trigger state (last fired, fire count) is tracked in memory.

## Keeping gws skills fresh

```bash
.venv/bin/python run.py regen-gws-skills          # refresh all 30+ gws skill docs
.venv/bin/python run.py regen-gws-skills gmail    # refresh only skills matching "gmail"
```

## Backlog

Known gaps and future directions are tracked in [BACKLOG.md](BACKLOG.md).
