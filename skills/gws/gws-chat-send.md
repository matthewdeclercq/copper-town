---
description: 'Google Chat: Send a message to a space.'
name: gws-chat-send
version: 1.0.0
---

# chat +send

Send a message to a Chat space

## Usage

```bash
gws chat +send --space <SPACE> --text <TEXT>
```

## Flags

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--space` | ✓ | — | Chat space name, e.g. `spaces/SPACE_ID` |
| `--text` | ✓ | — | Message text to send |

## Examples

```bash
gws chat +send --space spaces/ABC123 --text 'Hello, team!'
```

## Tips

- Use `gws chat spaces list` to find space names if you don't have the ID.
- For threaded replies, use the raw API: `gws chat spaces messages create`.

> [!CAUTION]
> This is a **write** command — confirm with the user before executing.

## See Also

- `gws-shared` skill — Global flags and auth
- `gws-chat` skill — All Chat spaces and messages commands
