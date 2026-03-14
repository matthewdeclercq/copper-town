---
description: 'GWS Workflow: Announce a Drive file in a Google Chat space.'
metadata:
  openclaw:
    category: productivity
    cliHelp: gws workflow +file-announce --help
    requires:
      bins:
      - gws
name: gws-workflow-file-announce
version: 1.0.1
---

# workflow +file-announce

Announce a Drive file in a Chat space. Fetches the file name from Drive to build the announcement.

## Usage

```bash
gws workflow +file-announce [OPTIONS] --file-id <ID> --space <SPACE>
```

## Flags

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--file-id <ID>` | ✓ | — | Drive file ID to announce |
| `--space <SPACE>` | ✓ | — | Chat space name (e.g. spaces/SPACE_ID) |
| `--message <TEXT>` | — | — | Custom announcement message |
| `--dry-run` | — | — | Validate the request locally without sending it to the API |
| `--format <FORMAT>` | — | json | Output format: json (default), table, yaml, csv |
| `--sanitize <TEMPLATE>` | — | — | Sanitize API responses through a Model Armor template. Requires cloud-platform scope. Format: projects/PROJECT/locations/LOCATION/templates/TEMPLATE. Also reads GWS_SANITIZE_TEMPLATE env var. |

## Examples

```bash
gws workflow +file-announce --file-id FILE_ID --space spaces/ABC123
gws workflow +file-announce --file-id FILE_ID --space spaces/ABC123 --message "Check this out!"
```

## Tips

- **Write command** — sends a Chat message.
- Use `gws drive +upload` first to upload the file, then announce it here.
- Fetches the file name from Drive to build the announcement.
- Use `--dry-run` to preview the message without sending.
