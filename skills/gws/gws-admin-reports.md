---
name: gws-admin-reports
description: "Admin Reports: Audit logs and usage reports for Google Workspace domains."
---

# admin-reports (v1)

> **Note:** Requires domain admin privileges or delegated admin access.

```bash
gws admin-reports <resource> <method> [flags]
```

## API Resources

### activities

  - `list` — Retrieve a list of activities for a customer account and application. Use `--page-all` for large result sets.
  - `watch` — Start receiving push notifications for account activities.

Key params for `activities list`:
- `userKey`: user email or `all`
- `applicationName`: `admin`, `calendar`, `chat`, `drive`, `gplus`, `login`, `meet`, `mobile`, `rules`, `saml`, `token`, `user_accounts`, `context_aware_access`, `chrome`, `data_studio`, `jamboard`, `keep`
- `startTime` / `endTime`: RFC3339 timestamps
- `eventName`: filter by specific event
- `filters`: parameter filter string, e.g. `doc_id==abc123`

### channels

  - `stop` — Stop push notification subscription for a channel.

### customerUsageReports

  - `get` — Get a usage report for the entire customer account for a given date.

Key params: `date` (YYYY-MM-DD), `parameters` (comma-separated metric names)

### entityUsageReports

  - `get` — Get a usage report for entities (e.g. GPlus communities, shared drives).

Key params: `entityType`, `entityKey`, `date`, `parameters`

### userUsageReport

  - `get` — Get a usage report for a set of users for a given date.

Key params: `userKey` (`all` or email), `date` (YYYY-MM-DD), `parameters`, `filters`

## Discovering Commands

```bash
gws admin-reports --help
gws admin-reports activities --help
gws schema admin-reports.activities.list
```

Use `gws schema` output to build your `--params` and `--json` flags.
