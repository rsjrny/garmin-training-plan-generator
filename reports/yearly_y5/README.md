# Y5a yearly workflow acceptance evidence

Date: 2026-10-06 (America/New_York)
Status: Y5a implemented and locally verified; uncommitted on `ddc2435`.
Source: [Yearly Plan Workflow](../../YEARLY_PLAN_WORKFLOW_PLAN.md).
Y5b remains pending.

[Blocked approval follow-up](approval_followup/README.md) adds overlap ownership
review, explicit compatible canonical linking/separate dates, grouped dated warnings and sticky
approval controls. The reported user's three overlapping older single-event rows
still require a separate reviewed migration; this follow-up does not enable
year-only legacy replacement or bypass the overlap blocker. An explicit January 4
start can retain those three rows and prepare an applicable separate-date proposal;
no live yearly settings were changed.

The follow-up adds eight distinct cases: **392 total distinct passing checks** across
Y5a and this follow-up. Its verification union covers 137 distinct checks, including
14 browser scenarios; the clean completion recheck passed all 48 workflow/overlap
service and Y5a browser cases. Exact commands, the corrected timing assumption,
desktop/390px captures and the remaining full-calendar migration boundary are in
the follow-up evidence.

## Result and architecture

Plan leads with yearly planning without a race, a selected-season review and
explicit single-event choices. Seasons owns yearly settings/events. The shared
review opens the same canonical proposal on Plan and Seasons. Dashboard reads
applied phases and workflow status. Season URLs, selectors and navigation/detail
links carry selection through all three pages and reload; future seasons default
to their own year when a Dashboard year was not specified. Missing selections
are explicit. Plan's active workouts are filtered by the selected canonical plan;
unrelated or unlinked older schedules remain available without conversion.

`services/yearly_workflow.py` uses a read-only coherent transaction and verifies
the accepted audit snapshot hash and canonical revision content. It compares all
event fields, season inputs/name/bounds, settings and generation policy. Accepted
manual edits are traversed to the last actual yearly acceptance, so a single
prescription edit cannot consume pending intent. Confirmed native LTHR/MAF evidence
is reused only for unchanged prescribing inputs; default regeneration confirmation
flags cannot revoke original evidence. Changed thresholds/MAF age need confirmation.
An unaccepted confirmation also binds to its parent revision; acceptance by another
process supersedes the old remembered choice and uses the latest native evidence.

Successful event/settings saves and removal explicitly queue preparation. One
process-local coordinator per database/season coalesces changes, debounces generation
and runs it off the UI thread. The proposal cache is validated against full intent,
policy, local date, canonical/projected schedule, protection and match fingerprints.
Late/superseded results cannot publish. Affected-range mode remains the default;
advanced full-future/custom review remains available. Transient preparation errors
have a retry control. Dashboard status polling does not generate or write.

Current, no-schedule, preparing, pending, settings-required, archived and conflict
states are explicit. Closing review does not apply. Reload rediscovers pending
intent; accepted parameter evidence survives process restart via immutable data.
Unaccepted initial confirmations/proposals are process-local; a restart may require
confirmation again, never claim that an in-memory proposal was applied. Open dialogs
live outside refreshed cards and retain their optimistic editor versions.

Acceptance uses the existing Y3/Y4 service unchanged: warning acknowledgment,
composite stale checks, atomic apply, duplicate retry, cancellation/completed history,
protected prescriptions, immutable origins and match identities remain authoritative.
Initial review retains existing-workout overlap and cross-year recovery blockers.
Phase influence is described as preceding preservation; candidate session rows show
the actual original/proposed phases, and Dashboard shows only applied phase evidence.

Starting weekly minutes are required for UI preview; incomplete intent can still be
saved. Setup explicitly explains that covered Garmin history is not imported.
The **Always ready for** field is disabled and marked forthcoming. No distance goal
is saved or achieved readiness inferred. Functional selection/persistence, None/10
miler/half-marathon policies, baseline Base/Build/recovery cycles, Peak/Transition
and R1-compatible distance identity require Y5b. Existing policy v2 and event-free
Maintenance behavior are unchanged.

## Verification commands and results

All databases below were synthetic fixtures in separate `.tools/y5a-*` directories.
Each browser server received its fixture database path and an isolated loopback port.
No live database was opened, migrated or applied to during this implementation.

```powershell
.venv/Scripts/python.exe -m pytest tests/test_season_generation.py tests/test_season_regeneration.py tests/test_season_refinement.py tests/test_yearly_plan.py tests/test_plan_offline_ui.py -q -p no:cacheprovider --basetemp .tools/y5a-initial

.venv/Scripts/python.exe -m pytest tests/test_yearly_workflow.py tests/test_season_generation.py tests/test_season_regeneration.py tests/test_season_refinement.py tests/test_season_plans.py tests/test_season_migrations.py tests/test_yearly_plan.py tests/test_plan_offline_ui.py tests/test_chart_plan_comparison.py tests/test_nicegui_data.py tests/test_plan_revision_persistence.py tests/test_plan_persistence.py tests/test_dashboard_plan_copy.py tests/test_season_browser_logs.py tests/test_nicegui_app_security.py -q -p no:cacheprovider --basetemp .tools/y5a-regression

.venv/Scripts/python.exe -m pytest tests/test_yearly_workflow.py tests/test_plan_offline_ui.py tests/test_nicegui_data.py -q -p no:cacheprovider --basetemp .tools/y5a-final-services

$env:GARMIN_TEST_ARTIFACTS='reports/yearly_y5/y5a'
.venv/Scripts/python.exe -m pytest tests/test_yearly_workflow_browser.py tests/test_season_generation_browser.py tests/test_season_regeneration_browser.py tests/test_season_refinement_browser.py tests/test_seasons_browser.py tests/test_yearly_plan_browser.py -q -p no:cacheprovider --basetemp .tools/y5a-final-browsers

.venv/Scripts/python.exe -m pytest tests/test_yearly_workflow_browser.py::test_year_selection_navigation_reload_and_invalid_context -q -p no:cacheprovider --basetemp .tools/y5a-context-final
.venv/Scripts/python.exe -m pytest tests/test_yearly_workflow_browser.py::test_year_selection_navigation_reload_and_invalid_context -q -p no:cacheprovider --basetemp .tools/y5a-context-visual

.venv/Scripts/python.exe -m pytest tests/test_yearly_workflow.py -q -p no:cacheprovider --basetemp .tools/y5a-concurrency-final
.venv/Scripts/python.exe -m pytest tests/test_yearly_workflow_browser.py -q -p no:cacheprovider --basetemp .tools/y5a-concurrency-browser

git diff --check
```

| Check | Result |
| --- | --- |
| Initial existing regression | 160 passed in 134.96 s |
| Broad shared/workflow regression | 364 passed in 274.69 s |
| Final service/UI-data gate | 66 passed in 110.62 s |
| Final browser suite | 11 passed; invalid-context case failed before selector fix, in 272.35 s |
| Corrected context acceptance | 1 passed in 6.43 s; clean browser/application logs |
| Context visual recheck | 1 passed in 6.40 s |
| Final confirmation/concurrency recheck | All 37 workflow cases passed in 112.37 s; all 3 new browser scenarios passed in 80.65 s |
| Complete union | **384 distinct passed checks**, reruns excluded; final gate covers 67 distinct service/UI-data + 12 browser scenarios |

The current union was collected explicitly from the broad regression files plus
the six browser modules: 384 tests. The broad run included the first 29 Y5a service
cases; the final concurrency recheck includes all 37. The completed service/UI-data gate covers 67 distinct cases across the final runs. Raw final logs are in
`.tools/y5a-final-services.log`, `.tools/y5a-final-browsers.log`,
`.tools/y5a-context-final.log` and `.tools/y5a-context-visual.log`.
Final concurrency logs are `.tools/y5a-concurrency-final.log` and
`.tools/y5a-concurrency-browser.log`.

Service cases cover every saved event field (including goal/distance/status with
unchanged markers), yearly settings/bounds, race-free creation, unchanged native
confirmations, changed thresholds/MAF age, dismissal/restart, rapid coalescence,
shared concurrent preparation, deliberately delayed results, reload, stale/duplicate
acceptance, runtime/date changes, conflicts, read-only state and corrupt accepted
snapshots. Automatic acceptance retains history, locks, original prescriptions and
confirmed match identities; a separate applied leap-year schedule is unchanged.
Initial overlap and following-year recovery blockers are also exercised.

Browsers trace create → race-free initial preview/apply → event add/edit/remove →
automatic proposal → reviewed apply across Seasons, Plan and Dashboard. They exercise
stale concurrent editors, rapid edits, stale apply, missing settings, disabled conflict
acceptance, dismissal/reload, selected-year navigation, invalid context, keyboard/table
details, older saved schedules and actual applied-revision refresh. Page errors and
application tracebacks fail checks. The existing narrowly tested Windows Proactor
WinError 10054 close-event classifier remains in use; one final lifecycle raw log
contains that exact stdlib socket-close trace, retained in evidence, with no
application failure after classification.

Corrections during verification: fixture completion was advanced past its event
rather than marking a future event completed; bounds were extended rather than
shrunk across immutable history. Concurrent card refresh initially destroyed an open
editor, fixed with a stable dialog layer. Narrow navigation now starts collapsed.
Old copy/backdrop assertions were updated to that behavior, including all three
backdrop sites. The burst test uses an explicit one-second coalescing interval to
keep database-read contention inside the tested burst; cancellation/publication
still exercise real generation. Invalid Plan selections now use an empty selector
and explicit error instead of a NiceGUI invalid-value exception. Evidence capture
waits for dialog opacity/animation completion rather than recording a fade frame.
All failed cases have passing corrected checks above.
Final code review also found an old unaccepted MAF choice could override the status
of a newer revision accepted outside this process. Binding the confirmation to its
parent revision fixed this; the added concurrent-acceptance case and all workflow
cases/browser scenarios passed after correction.

## Visual evidence

Desktop (1440×1000) and narrow (390×844) screenshots were inspected for setup,
starting load, event editing, proposal differences, scrollable tables, warning
acknowledgment/acceptance and Plan/Dashboard navigation. Page overflow assertions
pass; tables/timelines scroll inside their containers and narrow drawers start closed.
Form inputs, warning text and apply controls remain reachable by scrolling.

Representative inspected artifacts:

- [Desktop setup](y5a/test_create_race_free_year_event_crud_auto_review_and_shared_context-824532737b/setup_desktop.png)
- [390px starting load](y5a/test_create_race_free_year_event_crud_auto_review_and_shared_context-824532737b/setup_load_390.png)
- [390px event editor](y5a/test_create_race_free_year_event_crud_auto_review_and_shared_context-824532737b/event_390.png)
- [Desktop proposal](y5a/test_create_race_free_year_event_crud_auto_review_and_shared_context-824532737b/proposal_desktop.png)
- [390px proposal](y5a/test_create_race_free_year_event_crud_auto_review_and_shared_context-824532737b/proposal_390.png)
- [390px acceptance](y5a/test_create_race_free_year_event_crud_auto_review_and_shared_context-824532737b/acceptance_390.png)
- [Desktop Plan](y5a/test_create_race_free_year_event_crud_auto_review_and_shared_context-824532737b/plan_desktop.png)
- [390px Plan](y5a/test_create_race_free_year_event_crud_auto_review_and_shared_context-824532737b/plan_390.png)
- [390px settings state](y5a/test_concurrent_edit_stale_review_and_conflict_settings_states-9f5ef2cb92/settings_required_390.png)
- [390px year selection](y5a/test_year_selection_navigation_reload_and_invalid_context-c1be553c3f/selection_390.png)
- [390px invalid context](y5a/test_year_selection_navigation_reload_and_invalid_context-c1be553c3f/invalid_context_390.png)

Existing Seasons regeneration/refinement and D1 desktop/390px screenshots and raw
server logs from this regression are retained alongside those new workflow artifacts.

## Scope and preservation

No applicable ancestor/workspace `AGENTS.md` was found. The roadmap and all three
requested source plans were read before implementation. Startup git status already
contained D1 Dashboard/data/analytics/UI/tests/reports, yearly review documents,
README edits and the givemydata acceptance report edit. They were preserved; the
givemydata report, D1 analytics/data reader/tests and original reports were not edited
by Y5a. Changes to D1 UI/page integration extend that work rather than replacing it.

New Y5a modules are `services/yearly_workflow.py`, `ui_nicegui/yearly_workflow.py`
and `ui_nicegui/season_review.py`; two new test modules cover the service/browser
workflow. Seasons, Plan/Dashboard, navigation, filtered Plan data, two existing
browser test modules and documentation were updated. No schema, generator policy,
package dependencies or canonical apply-service changes were introduced.

No live schedule/settings changes, commit, push, deployment or packaged rebuild.
Y5b, expanded formats, automatic covered-history input, real-history field use,
packaged executable and screen-reader software remain outside this local gate.
