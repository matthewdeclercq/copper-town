---
name: gws-shared
description: "GWS CLI: auth setup, global flags, and security rules for all gws commands."
---

# GWS Shared — Auth, Global Flags & Security Rules

This file is a prerequisite for all `gws` skills. Load it before using any `gws` command.

## Authentication

The `gws` CLI authenticates via one of these methods (highest to lowest priority):

1. **Access token env var:** Set `GOOGLE_WORKSPACE_CLI_TOKEN` to a pre-obtained OAuth2 access token.
2. **Keyring (default):** Credentials stored in the system keyring after running `gws auth login`.
3. **Credentials file:** Set `GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE` to the path of a JSON credentials file.

To verify authentication is working:
```bash
gws auth whoami
```

## Global Flags

These flags are available on every `gws` subcommand:

| Flag | Description |
|------|-------------|
| `--params <JSON>` | URL/query parameters as JSON |
| `--json <JSON>` | Request body as JSON (POST/PATCH/PUT) |
| `--upload <PATH>` | Local file to upload as media content (multipart) |
| `--output <PATH>` | Output file path for binary responses (e.g. downloads) |
| `--format <json\|table\|yaml\|csv>` | Output format (default: `json`) |
| `--api-version <VER>` | Override API version, e.g. `v2` or `v3` |
| `--page-all` | Auto-paginate; returns NDJSON (one JSON object per line) |
| `--page-limit <N>` | Max pages to fetch with `--page-all` (default: 10) |
| `--page-delay <MS>` | Delay between pages in ms (default: 100) |
| `--dry-run` | Validate the request locally without sending it to the API |

## Environment Variables

| Variable | Description |
|----------|-------------|
| `GOOGLE_WORKSPACE_CLI_TOKEN` | Pre-obtained OAuth2 access token (highest priority) |
| `GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE` | Path to OAuth credentials JSON file |
| `GOOGLE_WORKSPACE_CLI_CLIENT_ID` | OAuth client ID (for `gws auth login`) |
| `GOOGLE_WORKSPACE_CLI_CLIENT_SECRET` | OAuth client secret (for `gws auth login`) |
| `GOOGLE_WORKSPACE_CLI_CONFIG_DIR` | Override config directory (default: `~/.config/gws`) |
| `GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND` | Keyring backend: `keyring` (default) or `file` |
| `GOOGLE_WORKSPACE_CLI_SANITIZE_TEMPLATE` | Default Model Armor template for response sanitization |
| `GOOGLE_WORKSPACE_CLI_SANITIZE_MODE` | Sanitization mode: `warn` (default) or `block` |
| `GOOGLE_WORKSPACE_PROJECT_ID` | Override GCP project ID for quota and billing |

## Available Services

| Service | Alias | Description |
|---------|-------|-------------|
| `drive` | — | Files, folders, and shared drives |
| `sheets` | — | Read and write spreadsheets |
| `gmail` | — | Send, read, and manage email |
| `calendar` | — | Calendars and events |
| `docs` | — | Read and write Google Docs |
| `slides` | — | Read and write presentations |
| `tasks` | — | Task lists and tasks |
| `chat` | — | Chat spaces and messages |
| `people` | — | Contacts and profiles |
| `forms` | — | Google Forms and responses |
| `keep` | — | Google Keep notes |
| `meet` | — | Google Meet conferences |
| `admin-reports` | `reports` | Audit logs and usage reports |
| `events` | — | Google Workspace Events (push subscriptions) |
| `workflow` | `wf` | Cross-service productivity workflows |

## Discovering Commands

```bash
# List resources for a service
gws <service> --help

# List methods for a resource
gws <service> <resource> --help

# Inspect a method's parameters, types, and defaults
gws schema <service>.<resource>.<method>
gws schema <service>.<resource>.<method> --resolve-refs
```

Always call `gws schema` before constructing `--params` or `--json` bodies.

## Security Rules

- **Always confirm before write operations.** Any command that creates, modifies, sends, or deletes data must be confirmed with the user before execution.
- Use `--dry-run` when available to preview changes before applying them.
- Never store credentials in code or commit them to version control.
- When acting on behalf of another user (`--user`), confirm the target address with the user first.
