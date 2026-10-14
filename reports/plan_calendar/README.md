# Plan week calendar verification — October 14, 2026

Plan → Workouts adds a Week calendar / Workout table switch. No installer build,
live-user database migration/write, commit, push or deployment was performed.
All persistence and browser scenarios used isolated synthetic databases.

## Behavior and evidence

Seven saved calendar days appear side by side on wide screens, with contained
horizontal scrolling where needed. At 700px and narrower they become a stacked
agenda. Previous/next week, Today and a date-based week jump work without changing
the schedule. Switching to the table and back retains the chosen week. Existing
event proposal refresh and week-copy/navigation remain compatible.

Saved flags identify hard sessions, long runs, strength, mobility, explicit rest
and applied race sessions. Weekly summaries show training days/session counts,
multiple sessions on a day, known all-session time and running distance with
missing-measure counts. Unknown sport is excluded from confident training/run
counts; its known time still contributes to known all-session time.
Consecutive flagged hard days include adjacent Sunday/Monday boundaries.
These are descriptive saved labels, not an effort assessment or automatic
replanning rule.

Canonical calendar facts come from verified immutable revisions rather than
mutable projection totals/names. Active membership must agree with the canonical
pointer. Amounts, phase, targets, flags, notes, locks, manual done state, confirmed
matches and carried-original labels are read in one SQLite snapshot. Old rows use
explicit per-occurrence metadata; missing labels and invalid dates are not inferred
from a workout name or stale full-plan metadata.

Saved event intent is shown separately and may await review. Cancelled/skipped
events are excluded. C markers accompany the existing workout, including a
longer prescribed run. Original prescriptions, activity matches and phase/event
history remain unchanged. The calendar uses no calculation cache, migration,
write, plan regeneration or automatic match operation.

## Verification

193 distinct cases passed, excluding overlapping reruns:

- 15 new calendar summary/source cases.
- 171 existing presenter, generation/regeneration, dashboard-copy/focus, UI-data,
  baseline builder and offline-generation cases.
- Seven browser cases: two new calendar scenarios, two existing C-marker
  scenarios, yearly setup/event review/apply/week navigation, and two Dashboard
  focus scenarios.

The initial combined regression command below passed 181 cases, with three
single-event UI cases failing because their old route opened the default yearly
screen. The route fixtures were corrected, and the two newly added protection
cases plus the source/offline module rerun passed all 20 cases in 9.67 seconds.
The resulting distinct regression count is 186; failed attempts are not counted.

    .\.venv\Scripts\python.exe -m pytest tests/test_plan_calendar.py tests/test_planning_presenter.py tests/test_season_generation.py tests/test_season_regeneration.py tests/test_dashboard_plan_copy.py tests/test_dashboard_focus.py tests/test_nicegui_data.py tests/test_baseline_plan_builder.py tests/test_plan_offline_ui.py -q -p no:cacheprovider --tb=short

Final source/offline recheck:

    .\.venv\Scripts\python.exe -m pytest tests/test_plan_calendar.py tests/test_plan_offline_ui.py -q -p no:cacheprovider --tb=short
    # 20 passed in 9.67s

Browser commands used the same flags and GARMIN_TEST_ARTIFACTS set to
reports/plan_calendar/evidence:

    tests/test_plan_calendar_browser.py tests/test_c_event_markers_browser.py
        4 passed in 74.35s
    tests/test_usability_browser.py::test_year_setup_apply_event_review_later_and_week_navigation
    tests/test_dashboard_focus_browser.py
        3 passed in 66.84s

Coverage includes leap-day weeks and exact endpoints, double sessions, partial
volume, invalid/sentinel amounts, cross-week spacing, missing legacy labels,
metadata from another occurrence, invalid saved dates, draft/deleted-year scope,
canonical amounts despite modified projection metadata, invalid canonical
membership, confirmed older matches, carried locked/done original phase, C
marker-only intent and unchanged active-plan hashes.

Browser scenarios exercise wide/phone calendar layouts, saved badges, strength,
rest and race days, an unchanged 100-minute/10-mile run alongside a C 5K marker,
next/previous/date/Today navigation, table switching, retained selected week,
existing applied C-marker reload and proposal flows. Page-level overflow checks,
page-error checks and unexpected application-traceback checks pass.
Representative desktop calendar and phone long-run/C-marker/table screenshots in
[evidence](evidence) were visually inspected. Compilation and whitespace checks pass.

Configured selected-year data loaded in about 0.42 seconds in SQLite read-only
mode: 86 saved sessions, one saved event marker and no date warnings. Only aggregate
counts are reported. No personal measurements, names or raw source payloads are
included; all screenshots use synthetic data.

No failing application behavior remained. The offline UI test correction
explicitly selects workflow=single, matching its intended generation surface
after the earlier yearly-workflow default change.
