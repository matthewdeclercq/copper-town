---
_upstream_sha: 1172e0187edd9c0183ede2624609e65f681430b1
description: Share a Google Drive folder and all its contents with a list of collaborators.
name: recipe-share-folder-with-team
version: 0.22.3
---

# Share a Google Drive Folder with a Team

> **PREREQUISITE:** Load the following skills to execute this recipe: `gws-drive`

Share a Google Drive folder and all its contents with a list of collaborators.

## Steps

1. Find the folder: `gws drive files list --params '{"q": "name = '\''Project X'\'' and mimeType = '\''application/vnd.google-apps.folder'\''"}'`
2. Share as editor: `gws drive permissions create --params '{"fileId": "FOLDER_ID"}' --json '{"role": "writer", "type": "user", "emailAddress": "colleague@company.com"}'`
3. Share as viewer: `gws drive permissions create --params '{"fileId": "FOLDER_ID"}' --json '{"role": "reader", "type": "user", "emailAddress": "stakeholder@company.com"}'`
4. Verify permissions: `gws drive permissions list --params '{"fileId": "FOLDER_ID"}' --format table`
