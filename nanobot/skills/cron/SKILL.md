---
name: cron
description: Schedule reminders and recurring tasks.
---

# Cron

Use the `cron` tool to schedule reminders or recurring tasks.

## Three Modes

1. **Reminder** - message is sent directly to user
2. **Task** - message is a task description, agent executes and sends result
3. **One-time** - runs once at a specific time, then auto-deletes

## Examples

Fixed reminder:
```
cron(action="add", message="Time to take a break!", every_seconds=1200)
```

Dynamic task (agent executes each time):
```
cron(action="add", message="Check HKUDS/nanobot GitHub stars and report", every_seconds=600)
```

One-time scheduled task (compute ISO datetime from current time):
```
cron(action="add", message="Remind me about the meeting", at="<ISO datetime>")
```

Timezone-aware cron:
```
cron(action="add", message="Morning standup", cron_expr="0 9 * * 1-5", tz="America/Vancouver")
```

**Time-bounded recurring task** (auto-stops at end time):
```
cron(action="add", message="Report market data", every_seconds=1800, end_at="2026-03-05T15:00:00")
```

List/remove:
```
cron(action="list")
cron(action="remove", job_id="abc123")
```

## Time Expressions

| User says | Parameters |
|-----------|------------|
| every 20 minutes | every_seconds: 1200 |
| every hour | every_seconds: 3600 |
| every day at 8am | cron_expr: "0 8 * * *" |
| weekdays at 5pm | cron_expr: "0 17 * * 1-5" |
| 9am Vancouver time daily | cron_expr: "0 9 * * *", tz: "America/Vancouver" |
| at a specific time | at: ISO datetime string (compute from current time) |
| 9:30 to 15:00 every 30 min | every_seconds: 1800, end_at: ISO datetime for 15:00 today |
| from now until 5pm every hour | every_seconds: 3600, end_at: ISO datetime for 17:00 today |

## End Time (end_at)

Use `end_at` with `every_seconds` or `cron_expr` to automatically stop a recurring job at a specific time. The job will be deleted after the end time is reached.

**IMPORTANT**: When the user specifies a time range (e.g. "9:30 to 3pm", "from now until 5pm"), you MUST compute the `end_at` ISO datetime and include it. Otherwise the job will run forever.

## Timezone

Use `tz` with `cron_expr` to schedule in a specific IANA timezone. Without `tz`, the server's local timezone is used.
