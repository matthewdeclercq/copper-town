---
name: gws-workflow-meeting-prep
version: 1.0.0
description: "Google Workflow: Prepare for your next meeting: agenda, attendees, and linked docs."
metadata:
  openclaw:
    category: "productivity"
    requires:
      bins: ["gws"]
    cliHelp: "gws workflow +meeting-prep --help"
---

# workflow +meeting-prep

Prepare for your next meeting: agenda, attendees, and linked docs

## Usage

```bash
gws workflow +meeting-prep
```

## Flags

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--calendar` | — | primary | Calendar ID (default: primary) |
| `--format` | — | — | Output format: json (default), table, yaml, csv |

## Examples

```bash
gws workflow +meeting-prep
gws workflow +meeting-prep --calendar Work
```

## Tips

- Read-only — never modifies data.
- Shows the next upcoming event with attendees and description.

## See Also

- `gws-shared` skill — Global flags and auth
- `gws-workflow` skill — All cross-service productivity workflows commands
