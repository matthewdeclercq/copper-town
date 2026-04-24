---
name: expense-receipts
description: Processes expense receipts for Copper-Town: upload to Google Drive, extract details, add to expense spreadsheet, rename with receipt number.
---

# Expense receipt processing (Copper-Town)

When given a receipt file (e.g. from Downloads or Desktop), follow this workflow.

## IDs

Check memory for `expense_spreadsheet_id`, `expense_drive_folder_id`, and `expense_company_name`. If not found, search Google Drive for the expense spreadsheet and folder by name, then `remember()` the IDs with `pin=True` for future use. If `expense_company_name` is not in memory, ask the user for it and remember it with `pin=True`.

- **Sheet/tab name:** `Expenses (2026)` — always specify this tab explicitly in every read and write operation.

## Workflow

1. **Read the receipt file** – Extract every line item: date, item, vendor, amount, description.

2. **Confirm items** – If the receipt contains more than one line item, list them all and ask the user which ones to add. Wait for confirmation before proceeding.

3. **Get the next receipt number**
   - Read from the `Expenses (2026)` tab specifically. Check the first column for existing receipt numbers; use the next available.

4. **Preview** – Show the user a formatted preview of the row(s) that will be added:
   - Receipt Number, Date, Item, Vendor, Total Cost, State Sales Tax Paid (Yes/No/N/A), Type.
   - Wait for user approval before writing anything.

5. **Upload to Google Drive**
   - Naming: `##-<expense_company_name>-Expense-<YEAR>` (## = receipt number, YEAR = year from receipt date).

6. **Add to spreadsheet**
   - Write only to the `Expenses (2026)` tab. Append the approved row(s).
   - Match existing column formatting.

7. **Confirm** – Tell the user the receipt number(s) and that the file was uploaded.

## Notes

- Determine next receipt number from the spreadsheet before uploading.
- If data is missing from the receipt, ask the user.
- Never write to the spreadsheet or upload until the user has approved the preview.
- Verify upload and row creation.
