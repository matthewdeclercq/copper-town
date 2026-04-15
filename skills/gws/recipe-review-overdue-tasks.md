---
_upstream_sha: 396ca928fe7abe2831e4a8bb13f142beb96e43f3
description: Find Google Tasks that are past due and need attention.
name: recipe-review-overdue-tasks
version: 0.22.5
---

# Review Overdue Tasks

> **PREREQUISITE:** Load the following skills to execute this recipe: `gws-tasks`

Find Google Tasks that are past due and need attention.

## Steps

1. List task lists: `gws tasks tasklists list --format table`
2. List tasks with status: `gws tasks tasks list --params '{"tasklist": "TASKLIST_ID", "showCompleted": false}' --format table`
3. Review due dates and prioritize overdue items
