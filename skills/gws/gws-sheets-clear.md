---
name: gws-sheets-clear
version: 1.0.0
description: "Google Sheets: Clear values from a range in a spreadsheet."
metadata:
  openclaw:
    category: "productivity"
    requires:
      bins: ["gws"]
    cliHelp: "gws sheets spreadsheets values clear --help"
---

# sheets values clear

Clear values from a range in a spreadsheet. Clears data only — preserves formatting and structure.

## Usage

```bash
gws sheets spreadsheets values clear --params '{"spreadsheetId":"<ID>","range":"<RANGE>"}'
```

## Examples

```bash
# Clear a specific range
gws sheets spreadsheets values clear --params '{"spreadsheetId":"1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms","range":"Sheet1!A1:D10"}'

# Clear an entire column
gws sheets spreadsheets values clear --params '{"spreadsheetId":"1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms","range":"Sheet1!A:A"}'

# Clear an entire sheet (all data)
gws sheets spreadsheets values clear --params '{"spreadsheetId":"1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms","range":"Sheet1"}'
```

## Tips

- Range format: `SheetName!A1:B2`, `SheetName!A:A`, or just `SheetName` for the whole sheet.
- This does **not** delete rows/columns — it only empties cell values.
- There is no `batchClear` shorthand; clear multiple ranges by calling this command once per range.

> [!CAUTION]
> This is a **write** command — confirm with the user before executing.

## See Also

- `gws-shared` skill — Global flags and auth
- `gws-sheets` skill — All spreadsheet commands
