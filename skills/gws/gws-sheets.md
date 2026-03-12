---
name: gws-sheets
version: 1.0.0
description: "Google Sheets: Read and write spreadsheets."
metadata:
  openclaw:
    category: "productivity"
    requires:
      bins: ["gws"]
    cliHelp: "gws sheets --help"
---

# sheets (v4)

```bash
gws sheets <resource> <method> [flags]
```

## Helper Commands

| Command | Description |
|---------|-------------|
| `gws-sheets-read` skill | Read values from a spreadsheet |
| `gws-sheets-append` skill | Append rows to a spreadsheet |
| `gws-sheets-update` skill | Write/overwrite values in a range |
| `gws-sheets-clear` skill | Clear values from a range |

## API Resources

### spreadsheets

  - `batchUpdate` — Applies one or more updates to the spreadsheet. Each request is validated before being applied. If any request is not valid then the entire request will fail and nothing will be applied. Some requests have replies to give you some information about how they are applied. The replies will mirror the requests. For example, if you applied 4 updates and the 3rd one had a reply, then the response will have 2 empty replies, the actual reply, and another empty reply, in that order.
  - `create` — Creates a spreadsheet, returning the newly created spreadsheet.
  - `get` — Returns the spreadsheet at the given ID. The caller must specify the spreadsheet ID. By default, data within grids is not returned. You can include grid data in one of 2 ways: * Specify a [field mask](https://developers.google.com/workspace/sheets/api/guides/field-masks) listing your desired fields using the `fields` URL parameter in HTTP * Set the includeGridData URL parameter to true.
  - `getByDataFilter` — Returns the spreadsheet at the given ID. The caller must specify the spreadsheet ID. For more information, see [Read, write, and search metadata](https://developers.google.com/workspace/sheets/api/guides/metadata). This method differs from GetSpreadsheet in that it allows selecting which subsets of spreadsheet data to return by specifying a dataFilters parameter. Multiple DataFilters can be specified.
  - `developerMetadata` — Operations on the 'developerMetadata' resource
  - `sheets` — Operations on the 'sheets' resource
  - `values` — Operations on the 'values' resource

## Discovering Commands

Before calling any API method, inspect it:

```bash
# Browse resources and methods
gws sheets --help

# Inspect a method's required params, types, and defaults
gws schema sheets.<resource>.<method>
```

Use `gws schema` output to build your `--params` and `--json` flags.

## Common Patterns

```bash
# Read a range
gws sheets spreadsheets values get --params '{"spreadsheetId":"ID","range":"Sheet1!A1:D10"}'

# Read full sheet with grid data
gws sheets spreadsheets get --params '{"spreadsheetId":"ID","includeGridData":true,"ranges":["Sheet1!A1:D10"]}'

# Write values (2D array: rows of columns)
gws sheets spreadsheets values update --params '{"spreadsheetId":"ID","range":"Sheet1!A1","values":[["Name","Score"],["Alice","100"]]}'

# Append rows
gws sheets spreadsheets values append --params '{"spreadsheetId":"ID","range":"Sheet1!A:A","values":[["New Row","Value"]]}'

# Clear a range
gws sheets spreadsheets values clear --params '{"spreadsheetId":"ID","range":"Sheet1!A1:D10"}'

# Create a new spreadsheet
gws sheets spreadsheets create --json '{"properties":{"title":"My Sheet"}}'
```

> **Prefer the helper skills** (`gws-sheets-read`, `gws-sheets-append`, `gws-sheets-update`, `gws-sheets-clear`) for the most common operations — they document flags, examples, and cautions. Fall back to raw API calls for advanced use cases.
