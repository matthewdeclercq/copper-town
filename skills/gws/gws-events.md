---
name: gws-events
description: "Google Workspace Events: Subscribe to and manage push event notifications across Workspace apps."
---

# events (v1)

```bash
gws events <resource> <method> [flags]
```

## Helper Commands

| Command | Description |
|---------|-------------|
| `gws events +subscribe` | Subscribe to Workspace events and stream them as NDJSON |
| `gws events +renew` | Renew or reactivate existing subscriptions |

## API Resources

### subscriptions

  - `create` — Create a Google Workspace subscription (push notifications to a Cloud Pub/Sub topic).
  - `delete` — Delete a subscription.
  - `get` — Get details about a subscription.
  - `list` — List all subscriptions.
  - `patch` — Update or renew a subscription.
  - `reactivate` — Reactivate a suspended subscription (resets state to `ACTIVE`).

### operations

  - `get` — Get the status of a long-running operation.

### message / tasks

  - Internal sub-resources used by the helper commands.

## Key Concepts

- Subscriptions deliver events to a **Cloud Pub/Sub topic** you specify.
- Supported event targets: Chat spaces/messages, Calendar events, Meet conferences, Drive files.
- Subscriptions have a TTL and must be renewed before they expire.

## Key Parameters for `subscriptions.create`

```json
{
  "targetResource": "//chat.googleapis.com/spaces/SPACE_ID",
  "eventTypes": ["google.workspace.chat.message.v1.created"],
  "notificationEndpoint": {
    "pubsubTopic": "projects/PROJECT/topics/TOPIC"
  }
}
```

## Discovering Commands

```bash
gws events --help
gws events subscriptions --help
gws schema events.subscriptions.create
```

Use `gws schema` output to build your `--params` and `--json` flags.
