# Workout matching and compliance v1

Defined October 14, 2026. This measures recorded session identity and prescribed
amounts, not physiological readiness or native intensity compliance.

## Matching and review

Read active verified canonical revisions and their immutable workout origins.
Read older unconverted active saved rows separately; no plan conversion or
regeneration is needed to review their matches. Preserve all existing confirmed
matches and manual completion flags. An activity can have only one confirmed
workout association across both stores.

Suggestions are read-only. Compare recorded local calendar date (existing UTC
fallback when local time is absent), compatible sport, whole-workout prescribed
duration/distance and recorded activity duration/distance. Default date window is
±3 days, adjustable from 1 to 14. Never infer a race-specific session from a C
calendar marker or match an activity to a rest day. Unknown sport or amounts do
not become zero or a confident suggestion.

Candidate amounts must have at least one positive comparable measure and all
comparable actual/planned ratios must be within 0.2–3.0. Similarity is 40 points
for date proximity plus 60 points for average amount similarity:
`40 × (1 - abs(date delta)/(window+1)) + 60 × mean(min(actual/planned, planned/actual))`.
This is a product ranking, not a calibrated probability. High similarity needs
score ≥85, date delta ≤1, all expected positive measures present, and ≥8-point
separation from alternatives at both the workout and activity endpoints. Otherwise
show medium/low similarity and explicit ambiguity. No greedy automatic confirmation
or activity reuse. Manual selection can identify a shorter partial session or a
legacy workout with missing sport; a reviewed legacy sport is recorded separately
without rewriting the saved prescription.

Confirm/reject individual pairs or an explicitly selected batch in one review.
Only confirmation creates completion evidence. Do not persist proposed candidates
merely by opening/refreshing Compliance, since stored candidates protect workouts
from regeneration. Existing stored candidates remain visible and reviewable.
Reject suppresses the exact pair; rejected legacy pairs are tied to the exact old
row snapshot, so a different future prescription is not silently rejected.

Freeze date/window/scope, active revision pointers, originals, source activity
measures, existing match decisions and completion state. Recheck the full snapshot
under a write lock before applying. Exact duplicate reviews are idempotent;
changed sources, intent, evidence, selection or local date require fresh review.
All decisions, original identities and immutable review receipts commit or roll
back together. Confirmation never edits a workout, activity or prescription.

## Results

- **Completed:** confirmed compatible activity has at least 80% of every positive
  known prescribed amount. More volume does not increase completed-session counts.
- **Partial:** at least one known amount is below 80%. This can be known even if
  another measure is unavailable; show every measured ratio and missing measure.
- **Moved:** confirmed activity date differs from planned date. Retain the original
  date and show whether the moved session was completed, partial or unverified.
- **Missed:** no confirmed/manual completion, no pending suggestion/candidate, and
  the entire matching window has ended before today. This means no reviewed
  completion in the recorded data; sync may still be incomplete.
- **Extra:** unlinked recorded activity in the selected period has no eligible
  suggestion/candidate. Activities already confirmed to another/outside-range
  workout are identified separately and never counted as extras.
- **Needs review / Awaiting activity / Today / Upcoming / Rest:** explicit states
  keep tentative matches, open matching windows and unstarted work out of missed
  or completed counts. Missing activity data or unknown required amounts remains
  unverified. A manual done flag establishes marked completion without inventing
  actual duration/distance. Existing confirmed sport substitutions remain explicit.

80% is a documented product tolerance, not a validated effort or training benefit
threshold. Authoritative and estimated prescribed amounts are labeled; missing
expected actual measures cannot establish full completion. Native methodology
evaluation remains separate and continues using its existing confirmed-match API.

## Summaries and history

Completed/partial counts include moved sessions; the moved count is an overlapping
subset. Completion is credited to the prescribed date. Training-day streaks require
all non-rest sessions on that planned date to be completed or explicitly marked
done; rest days do not break a streak. A pending latest training day makes the
current streak unsettled. Streaks describe the selected view, not lifetime history.

Weekly time includes all sports; distance currently includes running only.
Recorded amounts use actual activity dates and completed calendar days, while
scheduled volume uses original planned dates over the same clipped
period. Extras contribute to recorded volume; matching does not move actual load
between weeks. Show counts and missing-measure coverage. Variance requires
complete daily plan coverage and complete measures; partial known sums are labelled
and unavailable variance stays blank. No imported activity on a date means zero
recorded volume, not verified physical rest. No activity source means unavailable.

## Persistence and compatibility

Schema v17 adds an empty legacy match store and immutable batch review receipts.
Canonical matches continue using `activity_workout_match` and original identities.
Cross-store guards enforce one confirmed activity association. Confirmed legacy
matches preserve their original saved row and its content snapshot; restart and
older-workout retirement retain this completion evidence. Rejected snapshots can
outlive changed/deleted unconfirmed source rows. Reopening never relinks or changes
reviewed evidence. Legacy conversion does not invent canonical correspondence from
row position; previous legacy evidence remains in review history.

No live data is migrated/reviewed during implementation. On source-app restart the
normal additive migration creates storage; only explicit user reviews add matches.
