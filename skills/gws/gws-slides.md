---
name: gws-slides
description: "Google Slides: Read and write presentations."
---

# slides (v1)

```bash
gws slides <resource> <method> [flags]
```

## API Resources

### presentations

  - `batchUpdate` — Applies one or more updates to the presentation. If any request is invalid the entire request fails and nothing is applied.
  - `create` — Creates a blank presentation using the title given in the request. If a `presentationId` is provided it is used as the ID of the new presentation.
  - `get` — Gets the latest version of the specified presentation.
  - `pages` — Operations on the 'pages' sub-resource (get, getThumbnail)

## Discovering Commands

```bash
gws slides --help
gws slides presentations --help
gws schema slides.presentations.get
```

Use `gws schema` output to build your `--params` and `--json` flags.
