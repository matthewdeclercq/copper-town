---
name: gws-workflow-email-to-task
version: 1.0.0
description: "Google Workflow: Convert a Gmail message into a Google Tasks entry."
metadata:
  openclaw:
    category: "productivity"
    requires:
      bins: ["gws"]
    cliHelp: "gws workflow +email-to-task --help"
---

# workflow +email-to-task

Convert a Gmail message into a Google Tasks entry

## Usage

```bash
gws workflow +email-to-task --message-id <ID>
```

## Flags

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--message-id` | ✓ | — | Gmail message ID to convert |
| `--tasklist` | — | @default | Task list ID (default: @default) |

## Examples

```bash
gws workflow +email-to-task --message-id MSG_ID
gws workflow +email-to-task --message-id MSG_ID --tasklist LIST_ID
```

## Tips

- Reads the email subject as the task title and snippet as notes.
- Creates a new task — confirm with the user before executing.

## See Also

- `gws-shared` skill — Global flags and auth
- `gws-workflow` skill — All cross-service productivity workflows commands
