# Backlog

Opportunity areas and known gaps. Each item defines what "done" looks like.

---

## Persistence

### Session persistence across restarts
Conversations are in-memory only. A process restart wipes all active sessions.

**Success:** Sessions (messages, agent slug, timestamps) are written to SQLite on every turn and reloaded on startup. The `SessionManager` reads from the DB on `get()` miss and writes on `create()` and after each message append. Existing in-memory behavior is unchanged when the DB is up to date.

### Trigger state persistence
Scheduler timing resets on restart. A trigger that fired 30 seconds before shutdown can double-fire on the next startup.

**Success:** `TriggerState` (last_fired, fire_count) is checkpointed to a SQLite table after each fire. On startup, the scheduler reloads state before its first tick. A trigger that was recently fired does not re-fire after a clean restart.

### Background task result retention
The 800-char result summary is delivered once via auto-respond. If the client missed it, it's gone.

**Success:** Completed task results (task_id, agent, task text, result, timestamp) are written to a `task_results` SQLite table. A `GET /api/tasks/{id}/result` endpoint returns the stored result. Results are retained for at least `SESSION_TTL_SECONDS`.

---

## Background Task Management

### Mid-flight task visibility
A running background task is opaque — you can see it's running but not what it's doing.

**Success:** Background tasks stream trace events (tool calls, LLM completions) to their parent session's `event_queue` in real time. The web UI shows an expandable activity log per in-progress task. The REPL's `/tasks` command optionally tails the live output.

### Task queuing and concurrency limits
Ten simultaneous `delegate_background` calls spawn ten parallel LLM loops immediately.

**Success:** A configurable `MAX_BACKGROUND_TASKS` env var caps concurrent background tasks. Tasks beyond the cap are queued (FIFO) and start as slots free. Queue depth is visible via `GET /api/tasks`.

### Task retry policy
Failed background tasks are reported and dropped with no recovery path.

**Success:** Agent definitions support an optional `retry: N` frontmatter field (default 0). `_bg_run` retries up to N times with exponential backoff before marking the task failed. Each attempt is logged to the trace. The notification includes attempt count.

---

## Memory

### Semantic memory retrieval
All memory is injected as a flat text block, capped by character limit. Important old facts are silently truncated when the cap is hit.

**Success:** `MemoryStore` supports a `search(query, agent_slug, limit)` method backed by SQLite FTS5. `_build_system_prompt` uses embedding-free keyword search to select the most relevant N entries rather than injecting all of them in insertion order. Pinned entries are always included regardless of search rank.

### Structured memory entries
Preferences, IDs, routing rules, and standing instructions all live in the same flat text namespace with no type distinction.

**Success:** `remember()` accepts an optional `tag` parameter (free-form string). `MemoryStore` stores and surfaces tags. Agents can query by tag via a `recall(tag)` tool. The system prompt groups memories by tag when injecting them.

### Memory change detection
The LLM compression step can silently drop facts even without `pin=True`. There's no audit of what was removed.

**Success:** Before committing a `replace_memories()` result, the engine diffs removed entries against pinned+recently-accessed entries and logs any potential loss as a `WARNING`. A `MEMORY_COMPRESSION_STRICT` env var (default false) aborts the compression rather than proceeding when potential loss is detected.

---

## Observability

### Web UI trace / audit view
No way to see what an agent did, which tools it called, or why it gave a particular answer — except via the CLI `show-trace` command.

**Success:** The web UI has a collapsible "activity" panel per message showing the tool calls, delegation events, and token counts from that turn. Data is sourced from trace events stored per-session (not from JSONL files). Requires no CLI access.

### Markdown rendering in web UI
Agent responses render as plain text. Code blocks, lists, and links are unformatted.

**Success:** The web UI renders assistant messages as Markdown using a client-side library (e.g. marked.js). Code blocks get syntax highlighting. User messages remain plain text.

### Cost tracking
Token counts are logged to JSONL but there's no summary, running total, or budget alert.

**Success:** The engine accumulates per-agent token usage in memory. `GET /api/usage` returns total and per-agent token counts since process start. An optional `TOKEN_BUDGET_WARN` env var logs a warning when a single session exceeds the threshold.

---

## Resilience

### LLM provider fallback
If the primary provider is down or rate-limited, all agents fail immediately.

**Success:** A `FALLBACK_MODEL` env var names a secondary LiteLLM model string. When a completion call raises a provider error (5xx, rate limit, connection refused), the engine retries once on the fallback model and logs a warning. The fallback is session-scoped — it doesn't persist to the next turn.

### Tool failure granularity
`DELEGATION_RETRY_COUNT` retries the entire delegation. Individual tool failures inside a sub-agent's loop have no retry.

**Success:** `TOOL_RETRY_COUNT` env var (default 0) retries individual tool executions (non-delegation tools) on exception before returning an error result to the LLM. Retries are logged to the trace. Does not apply to schema-only tools intercepted by the engine.

---

## Scheduling

### Webhook / push triggers
Triggers are cron (time-based) or poll (pull-based). There's no way to fire a trigger from an external HTTP call.

**Success:** A new trigger type `webhook` is supported in `triggers.yml`. The scheduler registers a route `POST /api/triggers/{name}/fire` at startup for each enabled webhook trigger. The request body is available as `${webhook_body}` in the task template. Auth uses the existing `API_KEY` middleware.

### Trigger audit log
No way to see when a trigger last fired, how long it ran, or whether it errored — except by reading JSONL trace files.

**Success:** Trigger fires are written to a `trigger_log` SQLite table (name, fired_at, duration_s, status, error). `GET /api/triggers` returns the last 10 fires per trigger alongside the existing trigger definition fields. The web UI has a simple trigger status page.

### Cron missed-fire recovery
If the process is down when a cron trigger was due, the trigger is silently skipped. The 2× tick window heuristic provides no recovery for longer outages.

**Success:** When the scheduler starts, it checks each cron trigger against its persisted `last_fired` timestamp (from trigger state persistence above). If a trigger is overdue by more than one period, it fires once on startup with a `missed_fire=true` flag available for task templates that want to handle catch-up differently.

---

## Web UI / API

### Cancel background task from web UI
Running background tasks can only be cancelled via REPL `/cancel`. The web UI has no cancel control and the API has no cancel endpoint.

**Success:** `DELETE /api/tasks/{task_id}` cancels the task and returns `{"status": "cancelled"}`. The web UI's task tree renders a cancel button per in-progress task. The button is removed on completion or cancellation.

### SSE stream heartbeat
The `/stream` SSE endpoint has no heartbeat. Clients can't distinguish a slow response from a dead connection.

**Success:** The `session_stream` generator yields a `comment` (`:keepalive\n\n`) every 15 seconds when idle. The web UI `subscribeStream` client detects a timeout after 30 seconds of no data and reconnects automatically.

### Conversation export
No way to save or share a session's conversation history.

**Success:** `GET /api/sessions/{id}/export` returns the session as a JSON array of `{role, content, timestamp}` objects. The web UI has an export button in the session list that triggers a browser download.

---

## Testing

### LLM mock mode
No way to test agent behavior without making real API calls. Engine refactors can only be verified by manual smoke testing.

**Success:** A `--mock-llm` flag (or `MOCK_LLM=true` env var) replaces the LiteLLM completion call with a configurable stub that returns scripted responses from a YAML fixture file. Fixture format: list of `{contains: "...", response: "..."}` matchers. Enables deterministic regression tests for tool dispatch, delegation routing, and error handling without LLM API access.

### Trace replay
No way to reproduce a past session for debugging or regression testing.

**Success:** `python run.py replay path/to/trace.jsonl` re-runs the session against the same message sequence, substituting mock LLM responses from the trace's recorded completions. Output diff shows where the new engine behavior diverges from the recorded trace.
