---
name: gws-sheets-update
version: 1.0.0
description: "Google Sheets: Write or overwrite values in a spreadsheet range."
metadata:
  openclaw:
    category: "productivity"
    requires:
      bins: ["gws"]
    cliHelp: "gws sheets spreadsheets values update --help"
---

# sheets values update

Write values into a specific range in a spreadsheet, overwriting existing content.

## Usage

```bash
gws sheets spreadsheets values update --params '{"spreadsheetId":"<ID>","range":"<RANGE>","values":[["<val>"]]}'
```

The `values` field is a 2D array: outer array = rows, inner array = columns.

## Examples

```bash
# Write a single cell
gws sheets spreadsheets values update --params '{"spreadsheetId":"1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms","range":"Sheet1!A1","values":[["Hello"]]}'

# Write a single row
gws sheets spreadsheets values update --params '{"spreadsheetId":"1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms","range":"Sheet1!A1","values":[["Name","Amount","Date"]]}'

# Write multiple rows starting at A2
gws sheets spreadsheets values update --params '{"spreadsheetId":"1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms","range":"Sheet1!A2","values":[["Alice","100","2026-03-01"],["Bob","200","2026-03-02"]]}'
```

## Tips

- The range only specifies the **top-left anchor** — the data array determines how far it extends.
- To **append** new rows without overwriting, use the `gws-sheets-append` skill instead.
- To **clear then rewrite**, chain a `values clear` followed by this command.

> [!CAUTION]
> This is a **write** command — confirm with the user before executing.

## See Also

- `gws-shared` skill — Global flags and auth
- `gws-sheets-append` skill — Append rows without overwriting
- `gws-sheets-clear` skill — Clear a range before rewriting
- `gws-sheets` skill — All spreadsheet commands
