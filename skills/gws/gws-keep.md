---
name: gws-keep
description: "Google Keep: Manage notes and attachments (enterprise only)."
---

# keep (v1)

> **Note:** The Keep API is intended for enterprise environments. Administrator must enable it for the organization.

```bash
gws keep <resource> <method> [flags]
```

## API Resources

### notes

  - `create` — Create a new note.
  - `delete` — Delete a note. Caller must have `OWNER` role. Deletion is immediate and irreversible.
  - `get` — Get a note by resource name.
  - `list` — List notes. Supports pagination via `pageSize` and `pageToken`.
  - `permissions` — Operations on note permissions sub-resource: `batchCreate`, `batchDelete`

### media

  - `download` — Download a note attachment. Requires `alt=media` query parameter.

## Key Parameters

- `name` (resource name): e.g. `notes/AxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxB`
- `notes.list` params: `pageSize`, `pageToken`, `filter` (e.g. `trashed = false`)

## Discovering Commands

```bash
gws keep --help
gws keep notes --help
gws schema keep.notes.list
```

Use `gws schema` output to build your `--params` and `--json` flags.
