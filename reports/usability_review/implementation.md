# Yearly-planning usability changes

Implemented October 7, 2026, from [the usability review](2026-10-07.md).

## What changed

| Review finding | Implemented interface behavior |
| --- | --- |
| 1. Fragmented planning destinations | Plan is the primary destination, with Overview, Events, Settings, and Workouts for the selected year. Single-event planning has a separate mode. Plan, Events, and Dashboard choose the same default year. |
| 2. Split or conflicting setup | One numbered settings form includes dates, available days, starting weekly running time, and the selected method's intensity inputs and confirmations. Finish setup opens those fields. Save draft supports incomplete settings; Save and review plan validates required fields. |
| 3. Confusing change summaries | Replacements count once as Changed. Before/after prescriptions appear first; unchanged rows and technical details are separate. Phones use paginated comparison cards. Affected dates and weekly time changes are shown. Apply changes and Review later remain reachable. |
| 4. Mixed plan context | Dashboard schedule counts, week cards, and thresholds use the selected year. Unpublished years show an empty schedule. Global history is labeled. Single-event Coach states its scope and displays its own dates and distance before generation. |
| 5. Outdated Help | Help explains yearly setup, optional events, reviewed apply, and subsequent event edits. A separate single-event guide links to that mode and Coach. |
| 6. Competing actions | Workflow state chooses Finish setup, Review initial plan, Review changes, Resolve conflicts, or View this week. Advanced generation, protection, archive, and older-workout tools are secondary options. |
| 7. Unavailable race-free goals | The disabled future-goal selector is removed. Current event-free output is described as general-fitness maintenance training. |
| 8. Rolling dates | New plans default to a calendar year with automatic naming and Jan 1–Dec 31 dates. Start today and Custom dates remain available. Timezones are searchable and the browser's timezone is detected for new plans. |
| 9. Crowded event forms | Basic event fields come first. Finish comfortably and Aim for a time reveal relevant inputs; performance targets choose Time or Pace. Advanced overrides are collapsed, C-event taper is disabled, and pace follows miles/kilometres preferences while preserving canonical speed. |
| 10. Daily workouts buried | Workouts has a compact header and a readable seven-day list, previous/next week controls, and Jump to today. The detailed table and totals are collapsed. Runs, strength workouts, and rest days are counted separately. Copy week follows the displayed week. Phase/intensity labels use readable wording. |

The browser regressions also exposed a navigation drawer that could reserve 300 pixels after resizing to a 390-pixel viewport. The drawer now overlays the content. Browser captures check both horizontal overflow and usable content width.

## Preserved behavior

Saving an event or draft does not apply workouts. Review later retains pending intent; Apply changes requires explicit acknowledgement. Service-level stale-review checks, overlap ownership, completion/history protection, manual locks, and stored-original preservation remain in place. Confirmation-only reviews preserve the draft version and still reject concurrent edits.

## Separate feature work

Functional baseline Base/Build/recovery cycles and background distance goals remain the Y5b feature milestone identified by the review. This change implements the interface recommendations and clarifies the current maintenance behavior; it does not add that scheduling capability.

## Validation

- 287 planning service/data regression tests passed. [Service test output](evidence/planning-service-tests.txt).
- 58 combined interface, data, security, and browser regression checks passed. [Combined output](evidence/interface-regression-tests.txt).
- Three additional browser navigation scenarios passed: event CRUD/link/archive, conflict tuning, and the full yearly create/add/move/remove lifecycle. [Navigation output](evidence/navigation-regression-tests.txt).
- Six final targeted checks passed after compacting Workouts and preserving its selected week during proposal-status refreshes. [Week persistence output](evidence/week-persistence-tests.txt).
- Python compilation and git diff whitespace checks passed.

The browser scenarios exercise desktop and 390-pixel layouts, both training methods, incomplete drafts, initial and changed proposals, Review later plus reload, calendar navigation, imperial pace conversion, selected-year scope, Help, Coach context, stale approvals, overlap linking, protected/manual workouts, and reviewed older-workout removal. Synthetic fixture activities were extended with power columns when opening Coach; no Coach generation was initiated.

## Browser evidence

All captured walkthroughs use synthetic databases.

- [Desktop setup](evidence/setup_desktop.png) and [phone setup](evidence/setup_mobile.png)
- [Desktop change review](evidence/changes_desktop.png) and [phone change review](evidence/changes_mobile.png)
- [Phone weekly workouts](evidence/workouts_mobile.png)
- [Maffetone setup](evidence/maf_setup_mobile.png)
- [Selected-year Dashboard](evidence/dashboard_year_mobile.png)
- [Single-event Coach context](evidence/coach_context_mobile.png)

## Local preview

The updated application is served at http://127.0.0.1:8097 using the existing review snapshot at .tools/usability-review-20261007/garmin-preview.db. The page displays SANDBOX. Browser regression tests use separate temporary databases. This implementation did not apply a proposal to the live database.
