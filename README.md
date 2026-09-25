# PAM Requirements v0 1

## Purpose

PAM is a small, private personal assistant being designed as a practical project for learning agent harness engineering. The immediate product goal is a read-only Google Calendar assistant that gives Ayush a clear weekly view of availability.

This document records only decisions made during the initial ideation. Technical architecture, integrations, deployment, and implementation are deliberately not decided yet.

## First Capability

PAM provides a calendar-only, read-only weekly availability summary for the exact date range requested by the user.

It must not create, edit, delete, or otherwise change calendar events. It must not send messages or reminders as part of this first capability.

## Required Output

For each day in the requested week, PAM shows:

1. The weekday and date.
2. The total time that is busy for that day.
3. The day’s events, with their time ranges and titles.
4. `Free day` if there are no events.

### Example

```text
Your next week: 28 Sep–4 Oct

Mon, 28 Sep — 2 hours busy
• 10:00–11:00 — Team meeting
• 16:00–17:00 — Assignment discussion

Tue, 29 Sep — 0 hours busy — Free day
• No events

Wed, 30 Sep — 1 hour busy
• 14:00–15:00 — Interview preparation
```

## Business Rules

- Use only the exact calendar date range asked for.
- When a day has no events, show `0 hours busy — Free day` rather than only `No events`.
- Display total busy hours for every day, including free days.
- Do not double-count overlapping events. Calculate busy time as the union of occupied time blocks.
- Example: events from 10:00–11:00 and 10:30–12:00 equal 2 hours busy, not 2.5 hours.
- The first PAM capability remains calendar-only and read-only.

## Learning Objective

This feature is intentionally small but useful. It will teach the core parts of an agent harness:

- connecting an agent to a bounded tool;
- interpreting user date requests safely;
- retrieving only relevant data;
- doing deterministic time calculations correctly;
- presenting reliable results without taking uncontrolled actions.

## Deferred Decisions

The following are intentionally deferred until further ideation:

- Gmail capability and exact email features;
- Telegram or WhatsApp as the user interface;
- model provider and model-selection policy;
- MCP server choice and tool contracts;
- database, deployment, authentication, and token storage;
- notifications, reminders, and any write actions.
