# Dashboard Today / next 7 days verification — October 14, 2026

One read-only panel combines the active schedule, current recovery evidence and
recent reviewed completion. No installer build, live-user database migration or
write, commit, push or deployment was performed. Browser and mutation scenarios
used isolated synthetic databases.

## Display and evidence contract

The rolling period includes today and six following calendar days. Each date
retains all selected active occurrences, including explicit rest and missing
amounts. An empty date means no saved session, not verified rest. Selected yearly
plan scope and timezone are used; a draft/unapplied year never falls back to
another schedule. Canonical facts come from verified immutable revisions and
workout origins; unscoped views can also show older active saved workouts.

Saved planned/completed events accompany the workout. Cancelled/skipped events
are excluded; C events remain markers and do not shorten a workout. Saved intent
can still await plan review and is labeled accordingly.

Recent completion covers the previous seven completed calendar days. Only
confirmed associations or explicit done flags establish completion. Moved is an
overlapping subset of completed/partial/unverified results and keeps its prescribed
date. Suggestions, grace windows and unavailable evidence remain pending. Session
counts follow the selected plan; activity and extra counts are explicitly
athlete-wide in this recorded period.

Recovery uses the existing engine and saved target on the current local date,
with no changed weights or recommendations. Stale health evidence is dated and
cannot supply favorable current readiness. Latest-data navigation remains
available. There is no future recovery forecast, automatic matching or adjustment.
Invalid recovery preferences do not hide the applied schedule.

One read-only SQLite transaction covers season scope, verified workouts,
activity associations, event intent, health sources and recovery preferences.
The recovery service accepts an internal shared read connection while retaining
its standalone API. No calculation cache or extra schema change is introduced.
Dashboard refresh loads outside the event loop, clears obsolete output and
supports retry after a visible error.

Plan and matching links retain the selected year. Today's and recent matching
links prepopulate the exact displayed Compliance dates. Reviewed session details
link to the recorded activity. Existing navigable week, copy controls, activity
grid, timeline and recovery-page flows remain available.

## Verification

175 distinct checks passed; overlapping reruns are counted once:

- 10 new read/scope/classification/snapshot cases.
- One real asynchronous callback case: failed overview, visible error, successful
  refresh with obsolete content removed.
- 155 existing dashboard-copy, recovery, UI-data, matching, recovery-callback and
  Help cases.
- Nine browser cases: two new desktop/390px focus scenarios, three existing
  recovery scenarios, the Dashboard/year-scope/Coach/Help scenario and three
  existing matching scenarios.

Final regression output is in regression.txt. The command was:

    .\.venv\Scripts\python.exe -m pytest tests/test_dashboard_focus.py tests/test_dashboard_focus_ui.py tests/test_dashboard_plan_copy.py tests/test_recovery_readiness.py tests/test_nicegui_data.py tests/test_workout_compliance.py tests/test_recovery_readiness_ui.py tests/test_help_about_ui.py -q -p no:cacheprovider --tb=short

Browser commands used the same flags and GARMIN_TEST_ARTIFACTS set to
reports/dashboard_focus/evidence:

    tests/test_dashboard_focus_browser.py
    tests/test_workout_compliance_browser.py
        5 passed in 58.43s
    tests/test_recovery_readiness_browser.py
    tests/test_usability_browser.py::test_dashboard_year_scope_coach_context_and_help
        4 passed within the earlier combined run

The final focus-only rerun also validates the Today matching link and adds coming
days screenshots; these two cases are counted once. See browser-results.txt.

Service checks include exact rolling endpoints, unscheduled/rest days, suggestion
versus reviewed completion, moved/partial outcomes, unapplied and deleted-year
scope, C markers and cancelled-event exclusion, invalid recovery preferences,
stale health, local date across UTC midnight, and coherent schedule/target reads
during a concurrent WAL write. Normal reads leave the full database dump unchanged.

Browser flows check today and coming-day prescriptions, stale current scores,
C-marker wording, reviewed moved completion, refresh after a synthetic done flag,
retained prescription hashes, exact Compliance date/year links and persisted
matching behavior. Page-error and unexpected application-traceback checks pass.
Desktop overview, phone overview/recent/coming-day views and matching links in
[evidence](evidence) were visually inspected. Page-level overflow checks pass.
Compilation and whitespace checks pass.

The configured database was read in SQLite read-only mode: seven day entries,
one current and six upcoming sessions loaded with readable recovery in roughly
0.49 seconds. No migration, review or health/plan write occurred. Only aggregate
counts are reported; personal names, values and raw source payloads are absent
from this report and all screenshots use synthetic data.

Corrections during verification: today's unconfirmed row legitimately also fit
a nearby activity, so its expected status was corrected to Needs review. A
synthetic multi-workout revision needed unique ordinals; the refresh fixture
needed full completion-state provenance. A Quasar select assertion now checks
the input value. The callback test explicitly opens its registered route after
the UI fixture initializes, matching the established test harness pattern.
Corrected cases passed; failed attempts are excluded from final counts.
