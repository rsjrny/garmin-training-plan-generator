# Workout matching and compliance v1 verification — October 14, 2026

Implemented the [matching and completion policy](../../docs/workout-compliance-policy.md).
No installer build, live-user database migration or match review, commit, push or
deployment was performed. All migration, mutation and browser scenarios used
isolated synthetic databases.

## Behavior and persistence

The Compliance page replaces daily-total comparison with session identity review.
Read-only suggestions compare recorded local day, sport, duration and distance
within an adjustable date window. Ranking exposes competing alternatives; only
explicit confirmation establishes completion evidence. Clear suggestions can
be selected and reviewed together. Existing stored candidates remain pending
until reviewed; opening the page creates neither matches nor candidates.

Canonical confirmation uses the existing immutable match repository and original
workout identity. Additive schema v17 introduces separate older-workout matches
and immutable review receipts. Cross-store constraints reserve each confirmed
activity for one workout. Confirmation freezes and rechecks the entire displayed
source snapshot under a write lock; all decisions and receipts commit together
or roll back. Duplicate requests are idempotent.

Older saved workouts can be reviewed without conversion. Unknown sport requires
an explicit interpretation from a compatible recorded activity, stored separately
from the prescription. Confirmed legacy originals cannot be changed, deleted or
retired. Redo/removal retain this evidence even for early/moved completion.
Canonical confirmations survive yearly revision carry-forward under their
unchanged original identities. Activity and prescription content is never edited
by matching.

Completed/partial uses known prescribed amounts and the documented 80% product
tolerance. Moved retains its planned date and completion detail. Grace windows,
tentative matches, unavailable evidence, rest and upcoming sessions are explicit.
Existing manual completion flags do not invent an activity or measured volume;
flags belonging to another occurrence or archived/full-plan containers are ignored.
Training-day streaks describe the selected view. Weekly time covers all sports,
while distance currently covers running. Recorded load follows actual dates;
completion follows prescribed dates. Missing measures and incomplete daily plan
coverage leave variance unavailable; partial known totals are labeled.

Native methodology/intensity compliance remains separate. The old daily-total
data helper remains available for compatibility; the page uses the new service.

## Read-only configured-data audit

Configured schema v16 loaded successfully in approximately 0.45 seconds:
726 active occurrences, 30 displayed sessions in the default period, and 70
suggested pairs. Results were 22 sessions needing review, seven known rest days
and one missed session. Suggestions did not establish completion. These are
aggregate counts only; no names, activity measurements or raw personal payloads
are saved in the report or screenshots.

The audit opened the database in SQLite read-only mode. Review storage was absent
as expected before the user's next source-app restart. Normal startup initializes
empty v17 storage; only explicit reviews add associations.

## Verification

326 distinct cases passed, excluding overlapping reruns:

- 58 new matching, classification, review, migration and protection cases.
- 265 existing identity, conversion, persistence, removal, intensity compliance,
  yearly refinement/reset, chart comparison, UI-data/workspace, Help, Dashboard
  copy and calendar-day cases.
- Three browser cases covering desktop 1440px, phone 390px and a stale open review.

The combined regression command below passed 323 cases in 129.41 seconds; its
output is saved in regression.txt.

    .\.venv\Scripts\python.exe -m pytest tests/test_workout_compliance.py tests/test_activity_workout_match.py tests/test_legacy_plan_conversion.py tests/test_plan_revision_persistence.py tests/test_legacy_workout_removal.py tests/test_runtime_methodology_compliance.py tests/test_season_refinement.py tests/test_yearly_reset.py tests/test_chart_plan_comparison.py tests/test_nicegui_data.py tests/test_nicegui_workspace.py tests/test_help_about_ui.py tests/test_dashboard_plan_copy.py tests/test_activity_calendar_days.py -q -p no:cacheprovider --tb=short

Final chronological ordering and partial-total labeling were followed by a clean
58-case focused rerun (16.14 seconds) and the browser run below (47.23 seconds).
These overlapping cases are counted once.

    $env:GARMIN_TEST_ARTIFACTS = 'reports/workout_compliance/evidence'
    .\.venv\Scripts\python.exe -m pytest tests/test_workout_compliance_browser.py -q -p no:cacheprovider --tb=short

Checks cover ambiguity, wrong sport, missing amounts, date-window boundaries,
manual completion, exact 80% classification, global activity claims, rest/future/
today/grace states, streaks and actual-date weekly volume. Persistence cases cover
confirmed immutability, rejection/reconsideration, stale date/activity/workout/
document state, mixed-batch rollback, duplicate requests, competing stored
candidates, cross-store uniqueness, transactionally failing v16-to-v17 migration,
redo/retirement protection and exact original survival after a C-marker revision.

Browser flows review a clear canonical match, explicitly identify a moved
half-length legacy run, check completed/partial/moved/missed/extra counters,
reload preserved associations and inspect weekly evidence. A changed recorded
activity blocks an already-open review without saving any receipt or match.
Active prescription hashes remain unchanged. Page-error and unexpected
application-traceback checks pass.

Desktop summary, phone review dialog and phone weekly/activities views in
[evidence](evidence) were visually inspected. Controls wrap, dialogs scroll and
tables contain their own horizontal scrolling; the page does not overflow.
Compilation and whitespace checks pass.

Corrections during verification: schema-version expectations and downgrade
fixtures were updated to v17; an injected v15-repair fixture also needed the v17
marker to isolate the repair transaction. A synthetic retirement insert was
missing required receipt fields, and a yearly-revision fixture tried adding an
existing activity column; corrected both fixtures. NiceGUI checkbox tests now
wait for the server-backed acknowledgement after clicking. Failed attempts are
excluded from the final count.

Suggestions are product rankings, not calibrated probabilities. Completion
describes recorded amounts, not effort quality; Garmin sync may still be
incomplete. No outcome or native methodology conformance is inferred from an
amount-only completion label.
