---
_upstream_sha: 5cba51261e21f397b443e0be5d16e520b4ce45a0
description: Create a new Google Slides presentation and add initial slides.
name: recipe-create-presentation
version: 0.22.5
---

# Create a Google Slides Presentation

> **PREREQUISITE:** Load the following skills to execute this recipe: `gws-slides`

Create a new Google Slides presentation and add initial slides.

## Steps

1. Create presentation: `gws slides presentations create --json '{"title": "Quarterly Review Q2"}'`
2. Get the presentation ID from the response
3. Share with team: `gws drive permissions create --params '{"fileId": "PRESENTATION_ID"}' --json '{"role": "writer", "type": "user", "emailAddress": "team@company.com"}'`
