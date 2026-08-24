---
name: feedback_no_slack_announcements
description: Do not post PR announcements to #nasuni-int Slack — this is not a Nasuni project
metadata:
  type: feedback
---

Do not post PR ready-for-review announcements to #nasuni-int Slack for this repository.

**Why:** `opensearch2026-agentic-search` (kmwtechnology) is not a Nasuni project. The #nasuni-int channel is for Nasuni/Hyrule work only. The `/workflow-check` skill's step 5b Slack requirement does not apply here.

**How to apply:** Skip the Slack announcement step entirely for any PR in this repo. The workflow-check verdict should not flag a missing Slack note as a gap.
