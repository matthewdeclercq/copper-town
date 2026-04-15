---
_upstream_sha: 27610996b244d4774f0c3658b717b359183b3f79
description: Identify large Google Drive files consuming storage quota.
name: recipe-find-large-files
version: 0.22.5
---

# Find Largest Files in Drive

> **PREREQUISITE:** Load the following skills to execute this recipe: `gws-drive`

Identify large Google Drive files consuming storage quota.

## Steps

1. List files sorted by size: `gws drive files list --params '{"orderBy": "quotaBytesUsed desc", "pageSize": 20, "fields": "files(id,name,size,mimeType,owners)"}' --format table`
2. Review the output and identify files to archive or move
