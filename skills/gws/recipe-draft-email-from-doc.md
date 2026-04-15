---
_upstream_sha: 993a2cfe3f4ec9f9bbdc6c0578e3540384c5e0ce
description: Read content from a Google Doc and use it as the body of a Gmail message.
name: recipe-draft-email-from-doc
version: 0.22.5
---

# Draft a Gmail Message from a Google Doc

> **PREREQUISITE:** Load the following skills to execute this recipe: `gws-docs`, `gws-gmail`

Read content from a Google Doc and use it as the body of a Gmail message.

## Steps

1. Get the document content: `gws docs documents get --params '{"documentId": "DOC_ID"}'`
2. Copy the text from the body content
3. Send the email: `gws gmail +send --to recipient@example.com --subject 'Newsletter Update' --body 'CONTENT_FROM_DOC'`
