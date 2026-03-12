---
name: gws-meet
description: "Google Meet: Create and manage meeting spaces and access conference records."
---

# meet (v2)

```bash
gws meet <resource> <method> [flags]
```

## API Resources

### spaces

  - `create` — Create a new meeting space.
  - `endActiveConference` — End the active conference in a space (if one is running).
  - `get` — Get details about a meeting space.
  - `patch` — Update details about a meeting space.

### conferenceRecords

  - `get` — Get a conference record by conference ID.
  - `list` — List conference records, ordered by start time descending by default.
  - `participants` — Sub-resource: `get`, `list` participants in a conference record.
  - `recordings` — Sub-resource: `get`, `list` recordings for a conference record.
  - `transcripts` — Sub-resource: `get`, `list` transcripts; `entries` sub-resource for transcript entries.

## Key Parameters

- `name` (space resource name): e.g. `spaces/jou-zhgy-xuag`
- `conferenceRecord` resource name: e.g. `conferenceRecords/abc123`
- `conferenceRecords.list` params: `pageSize`, `pageToken`, `filter`

## Discovering Commands

```bash
gws meet --help
gws meet spaces --help
gws meet conferenceRecords --help
gws schema meet.spaces.create
gws schema meet.conferenceRecords.list
```

Use `gws schema` output to build your `--params` and `--json` flags.
