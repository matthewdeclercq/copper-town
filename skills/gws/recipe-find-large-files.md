---
_upstream_sha: 0bd5bd1faec410e365dfc2cea75cbad3f8404d17
description: Identify large Google Drive files consuming storage quota.
name: recipe-find-large-files
version: 0.22.3
---

# Find Largest Files in Drive

> **PREREQUISITE:** Load the following skills to execute this recipe: `gws-drive`

Identify large Google Drive files consuming storage quota.

## Steps

1. List files sorted by size: `gws drive files list --params '{"orderBy": "quotaBytesUsed desc", "pageSize": 20, "fields": "files(id,name,size,mimeType,owners)"}' --format table`
2. Review the output and identify files to archive or move
