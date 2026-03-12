---
name: gws-forms
description: "Google Forms: Read and write forms and collect responses."
---

# forms (v1)

```bash
gws forms <resource> <method> [flags]
```

## API Resources

### forms

  - `batchUpdate` — Change the form with a batch of updates (add/modify/delete items, settings, etc.).
  - `create` — Create a new form. Only `form.info.title` and `form.info.document_title` are used from the request body.
  - `get` — Get a form by ID.
  - `setPublishSettings` — Update publish settings of a form (not supported on legacy forms).
  - `responses` — Operations on form responses sub-resource: `get`, `list`
  - `watches` — Operations on form watches sub-resource: `create`, `delete`, `list`, `renew`

## Key Parameters

- `formId` (required): the form's Drive file ID
- `responses.list` supports `filter` param, e.g. `timestamp > 2024-01-01T00:00:00Z`

## Discovering Commands

```bash
gws forms --help
gws forms forms --help
gws schema forms.forms.get
gws schema forms.forms.responses.list
```

Use `gws schema` output to build your `--params` and `--json` flags.
