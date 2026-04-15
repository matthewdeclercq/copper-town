---
_upstream_sha: 5162a63de6fc1cc7e8fbc8a7caa6e40045f03049
description: Find Gmail messages with a specific label and forward them to another
  address.
name: recipe-forward-labeled-emails
version: 0.22.5
---

# Forward Labeled Gmail Messages

> **PREREQUISITE:** Load the following skills to execute this recipe: `gws-gmail`

Find Gmail messages with a specific label and forward them to another address.

## Steps

1. Find labeled messages: `gws gmail users messages list --params '{"userId": "me", "q": "label:needs-review"}' --format table`
2. Get message content: `gws gmail users messages get --params '{"userId": "me", "id": "MSG_ID"}'`
3. Forward via new email: `gws gmail +send --to manager@company.com --subject 'FW: [Original Subject]' --body 'Forwarding for your review:

[Original Message Body]'`
