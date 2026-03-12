# Copper-Town

A multi-agent AI assistant system. Talk to **Mini Me** — it routes your tasks to the right specialist agents automatically.

## Setup

**1. Create and activate a virtual environment**
```bash
python3 -m venv .venv
source .venv/bin/activate      # Mac/Linux
```

**2. Install dependencies**
```bash
pip3 install -r requirements.txt
```

**3. Configure your API keys**
```bash
cp .env.example .env
```
Open `.env` and fill in at least one API key (e.g. `XAI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`) and set `MODEL` to match.

## Running

```bash
python3 run.py
```

That's it. You're now talking to Mini Me, which will delegate to sub-agents as needed.

## Other ways to run

```bash
python3 run.py accounting             # talk directly to the Accounting agent
python3 run.py -t "process receipt"   # run a single task and exit
python3 run.py --list-agents          # see all available agents
python3 run.py --list-tools           # see all available tools
python3 run.py --verbose              # stream live trace events to stderr
python3 run.py --trace -t "task"      # write a trace file, print path at end
python3 run.py show-trace             # inspect the most recent trace
```

## Agents

| Agent | What it does |
|-------|-------------|
| **Mini Me** | Top-level assistant — routes tasks, delegates, reports back to you |
| **Accounting** | Processes expense receipts, logs expenses |
| **Google Workspace** | Gmail, Drive, Calendar, Sheets, Docs, and more via the `gws` CLI |

## Switching AI providers

Set `MODEL` in your `.env` to any LiteLLM-supported provider:

| Provider | Example MODEL value |
|----------|-------------------|
| xAI (default) | `xai/grok-4-latest` |
| Anthropic | `anthropic/claude-opus-4-6` |
| OpenAI | `openai/gpt-4o` |
| Google Gemini | `gemini/gemini-2.5-pro` |
| Groq | `groq/llama-3.3-70b-versatile` |
| Ollama (local) | `ollama/llama3.2` |

Per-agent model overrides are supported via the `model:` field in each agent's `.md` file.

## Memory

Agents automatically remember useful facts across sessions (spreadsheet IDs, standing preferences, recurring patterns). Memory is stored in a local SQLite database at `memory/copper_town.db`.

To pin a critical fact so it is never evicted by compression, use the `remember` tool with `pin=True`:
> "Remember with pin=true that my expense spreadsheet ID is ABC123"

Pinned memories always appear at the top of the agent's context, marked `[Pinned]`.

## Runtime skill creation

Mini Me can write new skills on the fly using the `write_skill` tool. Skills are saved to `skills/generated/` and are immediately searchable. This lets the system build up reusable workflows from user instructions without any code changes.

## Observability

Every run can be traced. Traces are JSONL files written to `traces/` and contain every LLM call, tool dispatch, delegation, and memory operation with timing.

```bash
# Stream colored events to stderr while running
python3 run.py --verbose -t "process receipt"

# Write a trace file silently (path printed at the end)
python3 run.py --trace -t "process receipt"

# Inspect the most recent trace
python3 run.py show-trace

# Inspect a specific file
python3 run.py show-trace traces/2026-03-11_14-22-05_mini-me.jsonl
```

`show-trace` prints a timeline (with depth-indented delegation chains) and a summary: duration, agent count, LLM calls, tool calls, token totals, and any failures.

## Configuration

Key environment variables (all optional, have defaults):

| Variable | Default | Description |
|----------|---------|-------------|
| `MODEL` | `xai/grok-4-latest` | LiteLLM model string |
| `MEMORY_MAX_LINES` | `30` | Entries before LLM compression fires |
| `MEMORY_COMPRESS_ENABLED` | `true` | Set `false` to disable LLM compression |
| `DELEGATION_RETRY_COUNT` | `1` | Times to retry a failed sub-agent delegation |
| `MAX_DELEGATION_DEPTH` | `3` | Max agent → agent nesting depth |
| `MAX_TOOL_ITERATIONS` | `20` | Tool call budget per agent turn |
| `MAX_CONTEXT_MESSAGES` | `40` | Sliding context window size |
| `LOG_LEVEL` | `WARNING` | Python logging level (e.g. `DEBUG`, `INFO`) |
