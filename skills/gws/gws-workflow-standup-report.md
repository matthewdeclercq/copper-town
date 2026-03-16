---
description: 'Google Workflow: Today''s meetings + open tasks as a standup summary.'
name: gws-workflow-standup-report
version: 1.0.0
---

# workflow +standup-report

Today's meetings + open tasks as a standup summary

## Usage

```bash
gws workflow +standup-report
```

## Flags

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--format` | — | — | Output format: json (default), table, yaml, csv |

## Examples

```bash
gws workflow +standup-report
gws workflow +standup-report --format table
```

## Tips

- Read-only — never modifies data.
- Combines calendar agenda (today) with tasks list.

## See Also

- `gws-shared` skill — Global flags and auth
- `gws-workflow` skill — All cross-service productivity workflows commands
