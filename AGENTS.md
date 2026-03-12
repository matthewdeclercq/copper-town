# Copper-Town Agent Inventory

This document is the single source of truth for **agents** available in this project. Use it to choose the right agent for a task or to add new agents.

## What's an agent?

An **agent** is a task-focused assistant with a defined workflow, tools, and instructions. Each agent lives in its own directory under `agents/<name>/` with an `agent.md` definition and a `memory.md` file. The LiteLLM engine loads them automatically.

## Hierarchy

- **Mini Me** (top level) – In charge of all other agents; delegates work and reports to you.
- **Sub-agents** – Task-specific agents that Mini Me delegates to (see table below).

## Current agents

| Agent | Role | Purpose | When to use | Definition |
|-------|------|---------|-------------|------------|
| **Mini Me** | Orchestrator | Top-level assistant; delegates to sub-agents and reports to the user. | Default: user talks to Mini Me. Mini Me routes tasks and reports back. | [agents/mini-me/](agents/mini-me/) |
| **Accounting** | Sub-agent | Handles accounting tasks; uses the expense-receipts skill for receipt processing (Drive, spreadsheet, receipt numbers). | Receipt to process, expense to log, or other accounting questions. | [agents/accounting/](agents/accounting/) |
| **Google Workspace** | Sub-agent | Single access point for all Google Workspace services via the `gws` CLI: Drive, Gmail, Calendar, Sheets, Docs, Tasks, Chat, and more. | Any Workspace read/write task. Delegates here from Mini Me, Accounting, or future agents (sales, engineering, marketing). | [agents/google-workspace/](agents/google-workspace/) |

## Adding a new agent

1. **Pick a clear scope** – One main workflow (e.g. "invoice creation", "client onboarding").
2. **Create the directory** – Add `agents/<name>/agent.md` with:
   - YAML frontmatter: `name`, `description`, `tools`, `delegates_to`, `skills`.
   - Step-by-step workflow and any links/templates in the body.
   - Optionally add `agents/<name>/memory.md` (created automatically on first use).
3. **Update this inventory** – Add a row to the table above and a short "when to use" note.
4. **Add tools if needed** – Create `tools/<name>.py` with `@tool`-decorated functions.

## Skills vs agents

- **Agents** = Task owners (e.g. Accounting) that handle a domain and delegate to skills or do the work themselves.
- **Skills** = Reusable "how to do X" instructions in `skills/`. Skills can be used by one or more agents.

**Project skills:** Accounting uses **expense-receipts** (`skills/expense-receipts.md`) for the receipt workflow: Drive upload, spreadsheet, receipt numbers. Global skills in `skills/_global/` are injected into all agents.

## Running agents

```bash
python3 run.py                        # interactive with Mini Me
python3 run.py accounting             # interactive with Accounting
python3 run.py -t "process receipt"   # single-task mode
python3 run.py --list-agents          # show this info programmatically
MODEL=gpt-4o python3 run.py          # swap provider
```
