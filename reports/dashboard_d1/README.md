# D1 Dashboard yearly-plan graphic evidence

Date: 2026-10-05
Status: Implemented and locally verified on baseline `ddc2435`; changes uncommitted.

## Behavior and architecture

The Dashboard adds a month-labeled annual phase timeline, race markers with A/B/C
priorities, year/season selectors, today marker, legend and accessible details/table.
Phase details show full inclusive dates, original controlling events, supported
weekly targets, cutback indicators and Plan/Seasons links. Estimates remain labeled;
unknown measurements stay unknown. Cross-year blocks retain their full detail dates.

`services/yearly_plan_data.py` reads a coherent SQLite snapshot in read-only mode.
It verifies active projection membership and loads hashed canonical revisions with
origin verification. `PlannedWorkout.phase` supplies the phase. Original event
snapshots resolve carried context; current intent never reconstructs applied phases.
Older saved workouts are selectable independently of unlinked season intent, using
explicit row phase metadata with unavailable labels where it is absent. Intent-only
and archived seasons are explicit.
No migrations or activity/track reads are introduced. Invalid content is unavailable.

`analytics/yearly_plan.py` groups consecutive dates and clips the graphic to one year.
Missing/conflicting phase metadata and unplanned gaps remain visible. Event workouts
produce solid applied markers; changed/unapplied intent produces dashed markers.
Cancelled intent cannot silently remove a retained applied event. Weekly measures
require every leaf's authoritative/estimated measure; rest is zero.

`ui_nicegui/yearly_plan.py` renders contained horizontal scrolling, large keyboard
selectors, clickable table/details and explicit refresh. A five-second lightweight
plan-pointer/season-input-version/legacy-row-signature poll detects revision, intent
and saved-workout changes. Returning
to Dashboard rereads facts. The year/season selection survives card refresh while
the page lives; page navigation/reload returns to the default current-year selection.
Existing Dashboard cards were allowed to shrink below their old 420px minimum.

## Commands and results

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_yearly_plan.py tests/test_yearly_plan_browser.py tests/test_dashboard_plan_copy.py tests/test_season_generation.py tests/test_season_regeneration.py tests/test_season_refinement.py tests/test_chart_plan_comparison.py -q -p no:cacheprovider --basetemp .tools/d1-combined
.\.venv\Scripts\python.exe -m pytest tests/test_yearly_plan.py tests/test_yearly_plan_browser.py tests/test_nicegui_data.py tests/test_season_browser_logs.py -q -p no:cacheprovider --basetemp .tools/d1-final-gate
.\.venv\Scripts\python.exe -m pytest tests/test_yearly_plan_browser.py -q -p no:cacheprovider --basetemp .tools/d1-visual-final
.\.venv\Scripts\python.exe -m pytest tests/test_yearly_plan_browser.py::test_yearly_timeline_details_refresh_navigation_and_responsive -q -p no:cacheprovider --basetemp .tools/d1-revision-refresh
.\.venv\Scripts\python.exe -m pytest tests/test_yearly_plan.py tests/test_yearly_plan_browser.py tests/test_dashboard_plan_copy.py tests/test_chart_plan_comparison.py -q -p no:cacheprovider --basetemp .tools/d1-legacy-regression
.\.venv\Scripts\python.exe -m pytest tests/test_yearly_plan.py tests/test_yearly_plan_browser.py -q -p no:cacheprovider --basetemp .tools/d1-legacy-final
```

- Combined regression: **177 passed** in 165.40s.
- Final targeted/shared gate: **55 passed** in 38.20s, including four additional
  reader/policy cases and shared data/log tests. The union is **207 distinct checks**;
  reruns are not added to the count.
- Visual recheck: **2 passed** in 26.48s. Used viewport captures to avoid full-page
  screenshot artifacts moving the fixed header into the middle of the image.
- Actual applied-revision refresh recheck: **1 passed** in 22.33s. It applies a moved
  event on the synthetic database, then verifies the old applied marker and pending
  intent marker disappear and the new applied marker appears automatically.
- Existing saved-plan compatibility regression: **58 passed** in 58.70s, including
  two added reader cases and one added browser case. The complete union is now
  **210 distinct checks**; the original 207 and these three additions are not reruns.
- Final reader/browser gate: **32 passed** in 52.63s, including legacy race distance
  estimate labels and clean screenshots after waiting for the details dialog to close.
- `git diff --check` passed. Raw test logs remain in `.tools/d1-*.log`.

Pure tests cover leap/cross-year clipping, all phase names (including peak,
transition and custom), single-day blocks, gaps/mixed/missing metadata, estimates,
rest, original context after regeneration, event priorities/taper/recovery windows,
archived/standalone/legacy/intent-only data, cancelled intent, corrupt projections
and hashed phases, authorizer-enforced read-only/no-track behavior and a five-second
full-year preparation bound. A database dump is identical before/after the reader.

Browsers exercise actual phase buttons, one-day selection by keyboard, table buttons,
correct Seasons navigation, today marker, intent polling, explicit refresh, applied
revision polling, imperial/metric event labels, empty/legacy/corrupt explanations,
390px page overflow and contained timeline scrolling. Browser errors and application
tracebacks fail checks; the existing tested Windows close-event classifier is used.

Early fixture corrections: duplicate-row injection required dropping a synthetic
unique index, a fixture's existing phase had to be cleared for the missing-phase
case, an empty pointer fixture required its created timestamp, and the phase table
uses scheduled dates rather than an `ordinal` column. Browser fixtures use the
existing mobile drawer backdrop and actual Seasons heading. Visual inspection
caught NiceGUI's default primary button color overriding phase colors; explicit
uncolored buttons fixed it. All final gates passed.

## User-reported saved-plan correction

The initial implementation excluded unmanaged schedules. A screenshot from the
user showed a full Unplanned year despite an existing 2026 plan. Read-only inspection
of the user's database confirmed 364 saved workouts from 2026-01-05 to 2027-01-03:
182 without phase metadata, plus 63 Base, 56 Build, 42 Peak, 20 Taper and one Race.
No canonical plan or linked season was present. The saved Race phase occurs on
2027-01-03, independently of the unlinked season's 2026-10-10 event intent.

The correction reads nested `structure_json.workout.phase` from the actual saved
workout row and displays the schedule under **Saved workout schedule**. It prefers
actual workouts over intent-only seasons on initial load. Missing/invalid metadata
or metadata for another date becomes **Phase Unavailable**; no cached generated
plan or current event intent supplies missing phases. Saved Race/Event markers have
unknown priority and no claimed season association. Flat older targets are estimates.
A legacy-row signature catches metadata changes in the existing five-second poll.
No conversion, regeneration, linking or live schedule modification was performed.

Synthetic reader/browser tests verify these behaviors, identical database dumps,
ignored stale cache content, saved-row dates, explicit intent selection, automatic
metadata refresh, accessible details and desktop/390px layout. Read-only preparation
against the user's actual database now selects all 364 saved workouts with the phase
counts above. Browser screenshots use synthetic databases.

## Inspected screenshots

- [Desktop timeline](test_yearly_timeline_details_refresh_navigation_and_responsive-9bc759d6a3/desktop.png)
- [390px timeline](test_yearly_timeline_details_refresh_navigation_and_responsive-9bc759d6a3/narrow.png)
- [Desktop phase details](test_yearly_timeline_details_refresh_navigation_and_responsive-9bc759d6a3/details_desktop.png)
- [390px event details](test_yearly_timeline_details_refresh_navigation_and_responsive-9bc759d6a3/details_narrow.png)
- [390px intent-only season](test_empty_intent_legacy_and_corrupt_timeline_states-824d42a43f/intent_narrow.png)
- [Desktop older saved schedule](test_existing_saved_schedule_shows_phases_and_unavailable_metadata-c69c3bb76c/legacy_desktop.png)
- [Desktop unavailable-phase details](test_existing_saved_schedule_shows_phases_and_unavailable_metadata-c69c3bb76c/legacy_details_desktop.png)
- [390px saved Race marker](test_existing_saved_schedule_shows_phases_and_unavailable_metadata-c69c3bb76c/legacy_narrow.png)

## Scope and limits

No live database/schedule change, migration, commit, push, package rebuild or
deployment. Real-history field use, packaged executable, future theme support and
screen-reader software were not verified. Keyboard/table access and light-theme
desktop/390px layout were verified. Timed/multi-day event formats remain R1 scope.
Client settings unchanged; attributable usage/credits unavailable. The pre-existing
givemydata manual-acceptance report edit was preserved.
