# Copper-Town

A multi-agent AI assistant. Talk to **Mini Me** — it routes your tasks to the right specialist agents automatically.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip3 install -r requirements.txt
cp .env.example .env   # add your API key and set MODEL
```

## Running

```bash
python3 run.py                        # chat with Mini Me
python3 run.py google-workspace       # talk directly to an agent
python3 run.py -t "process receipt"   # one-shot task, then exit
```

## Agents

| Agent | What it does |
|-------|-------------|
| **Mini Me** | Orchestrator — routes tasks, delegates, reports back |
| **Accounting** | Expense receipts and logging |
| **Google Workspace** | Gmail, Drive, Calendar, Sheets, Docs, and more via `gws` CLI |

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

## Switching providers

Set `MODEL` in `.env` to any [LiteLLM-supported](https://docs.litellm.ai/docs/providers) model string:
Per-agent model overrides are set via `model:` in the agent's `.md` file.

## Observability

```bash
python3 run.py --verbose -t "task"    # stream live events to stderr
python3 run.py show-trace             # inspect the most recent trace
```

## Adding MCP servers

External tools (GitHub, Slack, filesystem, etc.) can be wired in via the [Model Context Protocol](https://modelcontextprotocol.io/) — no new Python code needed per connector.

Add a server entry to `mcp.yml` with an `agents` list to control which agents get the tools:

```yaml
servers:
  github:
    transport: stdio
    command: ["npx", "-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "${GITHUB_TOKEN}"
    agents: [mini-me, research]   # or ["*"] for all agents
```

That's it — the server connects lazily on first tool call, and its tools appear automatically. Supported transports: `stdio` (command + args) and `sse` (url). Env values support `${VAR}` interpolation from your `.env` file.

You can also assign servers per-agent via `mcp_servers` in agent frontmatter — both sources are merged.

## Keeping gws skills fresh

```bash
python3 run.py regen-gws-skills          # refresh all 30+ gws skill docs from live CLI help
python3 run.py regen-gws-skills gmail    # refresh only skills matching "gmail"
```
