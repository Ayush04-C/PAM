# Availability presentation

Phase 10 improves how PAM presents Calendar facts without changing how Calendar
truth is obtained. The Calendar domain remains the sole source of event timing,
busy totals, free windows, requested-time availability, and duration-qualified
candidate windows.

## Deterministic facts and model wording

`AvailabilityService` obtains one `WeeklyAvailability` value from the Calendar
reader. The MCP response preserves its established `availability` text and adds
a `presentation` object derived from that same value. It contains per-day events,
busy minutes, free windows, duration-qualified candidates, and weekly free,
busiest, and openest day sets.

BharatCode may interpret the user request and phrase those facts naturally. It
must not calculate duration, intervals, conflicts, date boundaries, event order,
or scheduling candidates. It must not override live Calendar data.

## Free-window semantics

Timed Calendar events are normalized to Asia/Kolkata, clipped to the requested
range, split at local day boundaries, and merged when overlapping or touching.
Free windows are the remaining gaps inside each local calendar day:

- before the first event;
- between merged busy intervals; and
- after the last event.

PAM does not impose permanent working hours. A day with no events has a
calendar-day free window. An all-day commitment makes that day unavailable.

## Response depth

The system policy asks the model to use the structured result with the response
depth appropriate to the question:

- **Quick:** answer a specific-time question first without a weekly dump.
- **Standard:** a short daily summary, relevant events, and useful free windows.
- **Weekly:** compact per-day totals, free days, and truthful busiest/openest ties.

Responses use plain-text headings, blank lines, and restrained bullets. This is
safe for Telegram event titles without enabling a parse mode and remains readable
in the CLI.

## Scheduling suggestions and memory

When the model supplies `minimum_duration_minutes`, the deterministic layer
returns `candidate_slots` only for bounded within-day free intervals. Each slot
starts at the deterministic free-window start and ends exactly after the
requested duration. Open-ended human-facing windows such as "before 09:30" and
"after 12:30" remain descriptive availability, not permission for the model to
invent an exact start/end pair. A single-day `requested_time` returns
deterministic availability for that exact time.

Supermemory preferences are advisory only. They may help rank Calendar-qualified
candidates, but live Calendar facts always win. Calendar results and derived
availability are not stored as durable memory.
