---
_upstream_sha: 8adc1d00a46d760b7bba437b33db7efb346701c8
description: Export a Google Sheets spreadsheet as a CSV file for local backup or
  processing.
name: recipe-backup-sheet-as-csv
version: 0.22.5
---

# Export a Google Sheet as CSV

> **PREREQUISITE:** Load the following skills to execute this recipe: `gws-sheets`, `gws-drive`

Export a Google Sheets spreadsheet as a CSV file for local backup or processing.

## Steps

1. Get spreadsheet details: `gws sheets spreadsheets get --params '{"spreadsheetId": "SHEET_ID"}'`
2. Export as CSV: `gws drive files export --params '{"fileId": "SHEET_ID", "mimeType": "text/csv"}'`
3. Or read values directly: `gws sheets +read --spreadsheet SHEET_ID --range 'Sheet1' --format csv`
