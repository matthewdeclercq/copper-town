# Google Workspace — Safety Rules

Before making any modification to a Google Sheets spreadsheet, Google Doc, or Google Slides presentation, **save a named version first** so the change can be rolled back.

- For Sheets/Docs/Slides: create a named version (e.g. "Before expense row addition — 2026-03-09") via the API or `gws` CLI before writing.
- The version name should briefly describe the upcoming change and include the current date.
- If the version save fails, stop and inform the user before proceeding with the edit.
