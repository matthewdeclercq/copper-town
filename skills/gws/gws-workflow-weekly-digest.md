---
description: 'GWS Workflow: Weekly summary of this week''s meetings and unread email
  count.'
metadata:
  openclaw:
    category: productivity
    cliHelp: gws workflow +weekly-digest --help
    requires:
      bins:
      - gws
name: gws-workflow-weekly-digest
version: 1.0.1
---

# workflow +weekly-digest

Weekly summary: this week's meetings + unread email count.

## Usage

```bash
gws workflow +weekly-digest
```

## Flags

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--format` | — | json | Output format: json (default), table, yaml, csv |
| `--sanitize` | — | — | Sanitize API responses through a Model Armor template. Requires cloud-platform scope. Format: projects/PROJECT/locations/LOCATION/templates/TEMPLATE. Also reads GWS_SANITIZE_TEMPLATE env var. |
| `--dry-run` | — | — | Validate the request locally without sending it to the API |

## Examples

```bash
gws workflow +weekly-digest
gws workflow +weekly-digest --format table
```

## Tips

- Read-only — never modifies data.
- Combines calendar agenda (week) with gmail triage summary.
