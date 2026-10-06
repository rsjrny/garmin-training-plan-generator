# Reviewed older-workout removal verification

Date: 2026-10-06. Source remains uncommitted on ddc2435. All acceptance and
migration tests used isolated synthetic databases and loopback fixture servers.
No live migration, schedule/settings change, commit, push, deployment or package
rebuild. Existing D1 work and givemydata acceptance evidence were preserved.

## Behavior and preservation

**Plan → Remove older workouts** and overlap review offer the same exact-ID
selection, initially empty. A selected year limits dates to that season; without
one, editable future bounds are offered. Preview/dismissal make no writes.
Acceptance requires the separate review acknowledgement. Structured plans retain
their existing reviewed yearly workflow. History, today, protected metadata,
recorded-activity dates, converted source rows and owned yearly dates are blocked.

Schema v16 adds empty immutable removal audit/membership tables and updates the
active-workout view. Acceptance records retirement membership rather than deleting
original planned rows. Those originals remain immutable and available under
**Removed older workouts — saved originals**, across reloads and later legacy
calendar replacement/conversion. Canonical revisions, origin/prescription identity,
completed/history and confirmed matches are unchanged. Selected future nutrition
cache dates are cleared; the original cache is retained in the removal audit.

Acceptance atomically verifies exact reviewed rows, full schedule/protection and
activity state, selected season/events, local day, policy and cache. Stale reviews
fail without changes; concurrent duplicate acceptance is idempotent. Faults after
audit or membership insertion roll back cache and schedule changes together.
Migration/replay leaves all existing active workouts intact. Injected v16 failure
restores the old view and migration version.

After accepted removal the selected year's fresh proposal prepares automatically;
yearly apply still needs separate review and acceptance. Review opening waits for
the newest worker across superseding edits. Canceling a review caller does not
cancel shared preparation. Initial overlap checks remain enforced.

Read-only installed-database diagnostics found three older workouts overlapping
January 1–3, 2027. At inspection they were future, unowned and had no protected
metadata or recorded activity dates. No removals or migration ran on that database;
the actual review must recheck its current state. Saved weekly time was already
270 minutes; MAF adjustment confirmation remains a separate requirement.

Partial canonical legacy adoption remains unsupported. Functional Always ready
for goals, baseline cycles and distinct Peak/Transition phases remain pending Y5b.

## Verification

**432 distinct checks passed** across these runs (417 service/UI-data cases and
15 browser scenarios); the gate collection confirms the union. Reruns are counted
once. The final saved-original visibility capture is an additional rerun of the
existing removal browser scenario.

- Schema/conversion/revision/match compatibility: **91 passed**, 25.59s.
- Removal/persistence/generation/regeneration/workflow/yearly-reader regression:
  **216 passed**, 244.87s.
- Final removal and workflow service recheck: **72 passed**, 126.09s, including
  33 removal and 39 workflow cases. This adds three cases beyond the preceding
  regression, with all other reruns counted once.
- Final offline/UI-data/season-intent/refinement recheck: **107 passed**, 37.04s.
- Existing generation/regeneration/refinement/season/D1 browsers: **9 passed**,
  162.81s.
- Final removal plus yearly-workflow browsers: **6 passed**, 133.61s.

The browser removal scenario dismisses a selected review unchanged, rejects stale
concurrent description changes, requires acknowledgement, accepts the three
January removals, rejects an old yearly preview, then separately accepts the full
365-day January–December proposal. Original rows are compared byte-for-byte before
and after removal, yearly apply and reload. Application/browser errors are checked;
the known Windows Proactor shutdown-only traceback is filtered by the shared helper.

Corrected failures: raw SQLite REAL metrics require stable raw JSON serialization,
rather than native domain serialization; asynchronous dialog fade needs a locator
for the new review; review opening must wait for newest preparation. The stale
proposal browser test now waits until its review actually opens before making
external edits. Existing v15 migration tests were updated for v16 completion and
their repair fixture records current version so rollback tests isolate repair from
a separately committed newer migration. Full corrective rechecks passed.

Commands use `.venv/Scripts/python.exe -m pytest`, `-q -p no:cacheprovider`,
unique `--basetemp .tools/legacy-removal-*` directories, and
`GARMIN_TEST_ARTIFACTS=reports/workout_removal` for headless Playwright captures.
[Collected gate cases](gate-collection.log) and passing output logs are retained:
[compatibility](compatibility.log), [regression](regression.log),
[final services](services-final.log), [UI/data](ui-data-final.log),
[existing browsers](ui-compatibility.log), [final browsers](browsers-final.log).

## Desktop and 390px inspection

Dialogs fit the viewport with vertical scrolling; selected chips have bounded
height. Wide exact-row tables scroll horizontally within cards. Selection,
acknowledgement, stale errors and accept/keep controls remain reachable. The
full-year unblocked preview keeps sticky review actions and grouped warnings.

- [Desktop selection](test_reviewed_older_removals_unblock_full_year_without_losing_originals-a6e2447a64/selection_desktop.png)
- [390px selection](test_reviewed_older_removals_unblock_full_year_without_losing_originals-a6e2447a64/selection_390.png)
- [Desktop selected review](test_reviewed_older_removals_unblock_full_year_without_losing_originals-a6e2447a64/selected_removal_desktop.png)
- [390px selected review](test_reviewed_older_removals_unblock_full_year_without_losing_originals-a6e2447a64/selected_removal_390.png)
- [390px stale rejection](test_reviewed_older_removals_unblock_full_year_without_losing_originals-a6e2447a64/stale_removal_390.png)
- [390px full-year proposal](test_reviewed_older_removals_unblock_full_year_without_losing_originals-a6e2447a64/full_year_unblocked_390.png)
- [390px saved originals after reload](test_reviewed_older_removals_unblock_full_year_without_losing_originals-a6e2447a64/saved_originals_390.png)

Screenshots and raw browser logs use synthetic data. Earlier
[Y5a evidence](../yearly_y5/README.md) and
[overlap/time clarification](../yearly_y5/approval_followup/README.md) remain intact.
