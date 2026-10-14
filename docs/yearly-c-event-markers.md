# C events in yearly plans

As of October 14, 2026, C priority means **calendar marker only**. A and B retain
their existing preparation, race-day, taper, recovery and transition rules.

The yearly baseline goal and prescribed daily workout continue to control training.
For example, a C-priority 5K on a day with a 10-mile run keeps the 10-mile run;
the athlete can include the event within that session. Its event distance, goal,
estimated participation time and saved historical taper/recovery overrides do not
limit or add training. A marker can share a date with another marker or an A/B
event, and it adds no event-related availability, recovery or taper conflicts.
It also leaves a planned rest day as rest.

The editor calls C a Calendar marker and disables taper and recovery overrides.
Markers appear alongside daily workouts and on the yearly timeline, separately
from workout prescriptions and phase blocks. Event distances describe the marker,
not the day's total workout distance.

Saving still prepares a reviewed proposal. When only C marker intent changes on
the current policy, that proposal carries every accepted workout, original ID,
intensity parameter, measure and origin forward exactly. It adds/changes/removes
only marker intent and its immutable accepted snapshot; nutrition is retained.
Review shows zero workout changes. Stale-state checks, recomputation, origin
verification, duplicate handling and atomic application remain active.

Generator and load-policy v4 introduce this behavior. The goal snapshot records
`c_event_policy: calendar-marker.v1`; accepted C markers are read from that snapshot
without requiring an event workout. Older revisions are never relabeled. Their
eligible future C race prescriptions and recovery are replaced only through a
reviewed policy update; history, completed/matched workouts and protected sessions
retain their original prescriptions and event context. A priority change involving
A/B or a simultaneous settings/policy change uses normal reviewed regeneration.

No database migration or installer build is required. Restart the source app
process to load the new UI and policy, then review any pending plan update.
