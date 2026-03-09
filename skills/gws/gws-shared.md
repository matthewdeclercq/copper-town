---
name: gws-shared
description: "GWS CLI: auth setup, global flags, and security rules for all gws commands."
---

# GWS Shared — Auth, Global Flags & Security Rules

This file is a prerequisite for all `gws` skills. Read it before using any `gws` command.

## Authentication

The `gws` CLI authenticates via one of two methods:

1. **Keyring (default):** Credentials are stored in the system keyring after running `gws auth login`. No environment variable needed.
2. **Credentials file:** Set `GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE` to the path of a JSON credentials file:
   ```bash
   export GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE=/path/to/credentials.json
   ```

To verify authentication is working:
```bash
gws auth whoami
```

## Global Flags

These flags are available on every `gws` subcommand:

| Flag | Description |
|------|-------------|
| `--user <EMAIL>` | Act as a specific user (requires domain-admin delegation) |
| `--format <json\|table\|csv>` | Output format (default: `table`) |
| `--quiet` | Suppress non-essential output |
| `--dry-run` | Show what would happen without making changes |

## Security Rules

- **Always confirm before write operations.** Any command that creates, modifies, sends, or deletes data must be confirmed with the user before execution.
- Use `--dry-run` when available to preview changes before applying them.
- Never store credentials in code or commit them to version control.
- When acting on behalf of another user (`--user`), confirm the target address with the user first.
