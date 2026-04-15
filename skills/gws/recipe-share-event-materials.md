---
_upstream_sha: ff730a54a41563c0c57c6e7a663d2a3342efff49
description: Share Google Drive files with all attendees of a Google Calendar event.
name: recipe-share-event-materials
version: 0.22.5
---

# Share Files with Meeting Attendees

> **PREREQUISITE:** Load the following skills to execute this recipe: `gws-calendar`, `gws-drive`

Share Google Drive files with all attendees of a Google Calendar event.

## Steps

1. Get event attendees: `gws calendar events get --params '{"calendarId": "primary", "eventId": "EVENT_ID"}'`
2. Share file with each attendee: `gws drive permissions create --params '{"fileId": "FILE_ID"}' --json '{"role": "reader", "type": "user", "emailAddress": "attendee@company.com"}'`
3. Verify sharing: `gws drive permissions list --params '{"fileId": "FILE_ID"}' --format table`
