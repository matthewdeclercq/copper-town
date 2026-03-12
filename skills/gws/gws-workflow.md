---
name: gws-workflow
description: "GWS Workflow: Cross-service productivity helpers combining Calendar, Gmail, Drive, Tasks, and Chat."
---

# workflow (alias: wf)

Cross-service productivity helpers. All read-only commands are safe to run without confirmation; write commands require user confirmation.

```bash
gws workflow <+helper> [flags]
# or
gws wf <+helper> [flags]
```

## Available Helpers

| Helper | Description | Writes? |
|--------|-------------|---------|
| `+standup-report` | Today's meetings + open tasks | No |
| `+meeting-prep` | Next meeting: agenda, attendees, linked docs | No |
| `+weekly-digest` | This week's meetings + unread email count | No |
| `+email-to-task` | Convert a Gmail message into a Tasks entry | Yes |
| `+file-announce` | Announce a Drive file in a Chat space | Yes |

## Usage

```bash
gws workflow +standup-report
gws workflow +standup-report --format table

gws workflow +meeting-prep
gws workflow +meeting-prep --calendar CALENDAR_ID

gws workflow +weekly-digest

gws workflow +email-to-task --message-id MSG_ID
gws workflow +email-to-task --message-id MSG_ID --tasklist LIST_ID

gws workflow +file-announce --file-id FILE_ID --space spaces/SPACE_ID
gws workflow +file-announce --file-id FILE_ID --space spaces/SPACE_ID --message "Check this out!"
```

## Discovering Commands

```bash
gws workflow --help
gws workflow +standup-report --help
gws workflow +file-announce --help
```
