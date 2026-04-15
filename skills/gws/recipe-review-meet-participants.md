---
_upstream_sha: ae54f63016f25b1b7480bd92517a971b9c80a296
description: Review who attended a Google Meet conference and for how long.
name: recipe-review-meet-participants
version: 0.22.5
---

# Review Google Meet Attendance

> **PREREQUISITE:** Load the following skills to execute this recipe: `gws-meet`

Review who attended a Google Meet conference and for how long.

## Steps

1. List recent conferences: `gws meet conferenceRecords list --format table`
2. List participants: `gws meet conferenceRecords participants list --params '{"parent": "conferenceRecords/CONFERENCE_ID"}' --format table`
3. Get session details: `gws meet conferenceRecords participants participantSessions list --params '{"parent": "conferenceRecords/CONFERENCE_ID/participants/PARTICIPANT_ID"}' --format table`
