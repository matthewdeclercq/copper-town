---
name: gws-workflow-file-announce
description: "GWS Workflow: Announce a Drive file in a Google Chat space."
---

# workflow +file-announce

Announce a Drive file in a Chat space. Fetches the file name from Drive and sends a message with a link.

## Usage

```bash
gws workflow +file-announce --file-id <FILE_ID> --space <SPACE>
```

## Flags

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--file-id <ID>` | ✓ | — | Drive file ID to announce |
| `--space <SPACE>` | ✓ | — | Chat space name, e.g. `spaces/SPACE_ID` |
| `--message <TEXT>` | — | — | Custom announcement message |
| `--format` | — | json | Output format: json, table, yaml, csv |

## Examples

```bash
gws workflow +file-announce --file-id FILE_ID --space spaces/ABC123
gws workflow +file-announce --file-id FILE_ID --space spaces/ABC123 --message "Check this out!"
```

## Tips

- **Write command** — sends a Chat message. Confirm with the user before executing.
- Use `gws drive +upload` first to upload a local file, then announce it here.
- Use `--dry-run` to preview the message without sending.
