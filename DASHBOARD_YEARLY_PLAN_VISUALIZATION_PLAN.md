# Dashboard Yearly Plan Visualization Plan

Y5a approval follow-up: initial overlap review and grouped warnings live in the
shared Plan/Seasons proposal UI. An explicit separate-start choice retains old rows
and prepares a new proposal without applying. Canonical linking retains applied prescriptions;
Dashboard continues reading applied phases only. Older single-event schedules
are not inferred, converted or replaced by this ownership review. A subsequent
separate **Remove older workouts** review retires only accepted eligible future
legacy rows while retaining original prescriptions. Dashboard's active calendar
omits retired rows through the shared view; applied yearly phases remain based
on accepted revisions. D1 analytics/reader/tests and existing evidence remain
unchanged. See [removal evidence](reports/workout_removal/README.md) and
[follow-up evidence](reports/yearly_y5/approval_followup/README.md).
The follow-up passed 137 distinct checks across corrected runs and a clean 48-case
completion recheck; Y5a/follow-up total is 392 distinct checks. Desktop/390px layouts
were inspected on isolated databases.

Created: 2026-10-04
Status: D1 implemented and locally verified (2026-10-05).
Roadmap: [D1](IMPLEMENTATION_ROADMAP.md#d1---dashboard-yearly-plan-graphic-locally-verified)
Related: [Yearly scheduling](YEARLY_MULTI_EVENT_SCHEDULING_PLAN.md),
[Expanded race formats](EXPANDED_RACE_FORMATS_PLAN.md).

## Objective

Show the full yearly training progression on the Dashboard, including all build,
taper and recovery blocks and their relationship to races. The athlete should
be able to see where they are now and what comes next without opening each week.

## Product scope

- A month-labeled annual timeline, with a selected year and season where needed.
- Contiguous phase blocks for base, build, event-specific, taper, event, recovery
  and maintenance. Show peak/transition when explicitly present in the plan;
  preserve authoritative phase names rather than inventing labels.
- Event markers with names, dates and A/B/C priorities; a today marker and legend.
- Clearly labeled gaps, unplanned dates and unavailable phase information.
- Block selection with exact start/end dates, phase and associated event where
  known. Show supported planned weekly duration/distance and links to Plan/Seasons.
- A compact accessible date/phase table with the same information as the graphic.

The default year should contain today. A season outside that year must be reachable
through the selector. Clip blocks visually at year boundaries but retain full dates
in details. If several applicable seasons exist, show distinct labeled rows or an
explicit season selection; never silently merge unrelated plans.

## Data and discovery contract

Before implementation, trace Dashboard loading, season ownership, active canonical
revisions, generated phase metadata, regeneration lineage and event readers.
Record exact source fields and whether phase metadata survives apply/regeneration.

The applied schedule is authoritative for training blocks. Season/event intent
may supply separately identified event markers, but must not imply an applied
training schedule. Never reconstruct phases solely from intensity or proximity
to races. Historical preserved workouts must not acquire false new phase labels.
If metadata is insufficient, explain the limitation; any new phase persistence
requires a documented compatibility design before implementation.

Read a coherent snapshot and refresh after active revision changes or explicit
Dashboard refresh. Do not generate, apply, convert, migrate or match schedules
as a side effect of rendering. Distinguish corrupt/unavailable data from no plan.
Totals inherit canonical measurement and estimate semantics; missing is not zero.

## Presentation and interaction

Use consistent phase colors plus text/patterns. Keep short tapers and event days
selectable even when their blocks are narrow. Resolve selection using stable
server-owned block/event identities. Keyboard controls and the table must provide
the same details and navigation as pointer interactions.

Use a contained scrolling timeline or compact month rows at 390px. Prevent page
overflow and overlapping labels. Do not crowd the existing Dashboard summary.
No-plan state should explain how to create/link a season; an intent-only season
should link to schedule preview rather than show fabricated training blocks.

R1 integration must support duration labels and overnight/multi-day event spans.
D1 can ship first using the existing event contract, with the label/span reader
extended when R1 becomes available.

## Implementation sequence

1. Document authoritative data and missing-metadata behavior with sample cases.
2. Build pure timeline preparation and a read-only data adapter.
3. Add Dashboard graphic, selectors, block details and accessible table.
4. Verify revision refresh, navigation and responsive rendering.
5. Update source plan/roadmap with decisions, evidence, changed files and handoff.

## Completion gate

- Exact inclusive phase dates, single-day blocks, all stored phase types and gaps.
- Multiple A/B/C events, close taper/recovery windows and resolved precedence.
- Leap years, cross-year clipping, archived/no/intent-only seasons and legacy data.
- Missing/corrupt metadata and preserved workouts after regeneration.
- Unknown/estimated totals and metric/imperial labels without invented values.
- Revision refresh, correct detail/navigation identities and read-only behavior.
- Desktop and 390px screenshots inspected; keyboard/table alternatives exercised.
- Representative full-year preparation remains bounded without loading track data.

Record commands/results and visual evidence under `reports/dashboard_d1/`.
Do not mark complete with required checks unavailable; record limitations plainly.

## Outside this phase

New generation policies, coaching predictions, automatic plan application, schedule
editing from the timeline, and release/deployment are separately scoped.

## D1 discovery and implementation decisions - 2026-10-05

- Canonical `PlannedWorkout.phase` is persisted in immutable revision content.
  Generated days have BASE/BUILD/EVENT_SPECIFIC/TAPER/EVENT/RECOVERY/MAINTENANCE.
  No phase schema change is required. Peak/transition/custom names render when
  explicitly stored; cutback is a stored weekly indicator rather than a new phase.
- `metadata.event_id` identifies the controlling event. Resolve it against the
  original revision's `goal_snapshot.events`, following verified immutable origin
  lineage for carried workouts. Do not rerun `day_controls` from current intent.
- `training_plan.current_revision_id` and `active_planned_workout` must agree on
  complete membership, dates and plan/workout identities. `load_revision` verifies
  hashes, relational content and origins. Missing/duplicate/moved projection rows
  make the graphic unavailable rather than plausible but incomplete.
- Read season/event intent and active revisions in one read-only transaction.
  No activity or trackpoint queries, migrations, generation or matching are invoked.
  Linked seasons (including archived) and standalone canonical plans are selectable;
  older saved workouts are selectable independently of unlinked season intent.
  Intent-only seasons show events and unplanned dates.
- Phase blocks group consecutive applied dates by phase, original controlling
  event context and preserved status. Gaps are Unplanned; missing or inconsistent
  phases are explained. Full blocks are prepared before year clipping so detail
  dates/weekly totals retain their actual extent, including cross-year blocks.
- Event-day workouts produce solid applied markers. Changed/unapplied event intent
  produces separate dashed markers; cancelled intent does not remove an applied
  event. Targets use whole-workout authoritative/estimated measures, with rest zero
  and incomplete measures Unknown. No pace-to-duration or load targets are invented.
- A five-second pointer/input-version/legacy-row-signature poll refreshes the coherent
  snapshot after revision/intent or saved-workout edits. Explicit Refresh yearly plan and returning
  to Dashboard also reread it; year/season changes use cached facts.
- The timeline scrolls inside its card at narrow widths. Keyboard selectors and
  table buttons expose the same details as one-day phase/event buttons. Dashboard
  upcoming/recent cards now allow widths below their former 420px minimum.

Implementation: `services/yearly_plan_data.py`, `analytics/yearly_plan.py`,
`ui_nicegui/yearly_plan.py`, and Dashboard integration in `ui_nicegui/pages.py`.
Verification: **210 distinct checks passed** across the combined regression suite
and final targeted gate, with subsequent browser rechecks confirming screenshots
and actual applied-revision refresh. Desktop/390px screenshots were inspected.
See [D1 evidence](reports/dashboard_d1/README.md) for commands, results, initial
fixture/visual corrections and remaining limits. No live database/schedule changes,
migration, commit or packaging rebuild. R1 and U1/U2 remain separately scoped.

## Existing saved-plan compatibility correction - 2026-10-05

The first implementation excluded older unmanaged workouts. The user's 2026
Dashboard consequently showed a full Unplanned year despite an existing schedule.
Read-only inspection found 364 saved workouts: 182 with explicit nested
`structure_json.workout.phase` labels and 182 without phase metadata. The saved
schedule is independent of the unlinked 2026 season's event intent.

The reader now exposes **Saved workout schedule**, preferring a schedule with
workouts over an intent-only season by default. It reads explicit phases from
each actual scheduled row, never from cached generated plans or inferred race
windows. Missing or mismatched-date metadata becomes **Phase Unavailable**;
dates without workouts remain **Unplanned**. Saved Race/Event phases produce
solid markers with unknown priority and no claimed season association. Older
flat targets are conservatively estimates. No workouts are converted or changed.

Two additional reader cases and a browser case cover this format, metadata edits,
stale caches, actual row dates, default selection, details and desktop/390px layouts.
The compatibility regression passed **58 checks**; see the evidence report.

## Y5 workflow integration - 2026-10-06

[Yearly Plan Workflow and Continuous Phases](YEARLY_PLAN_WORKFLOW_PLAN.md) defines Y5a
workflow integration (locally verified 2026-10-06) and pending Y5b policies. Dashboard shares the selected yearly plan with Seasons
and Plan and exposes whether event/settings edits await review, require missing inputs,
are being prepared, or conflict. Current intent remains distinct from applied workouts.
Y5b will persist continuous baseline cycles and distinct Peak/Transition phases; D1
must display their actual stored dates/provenance after accepted apply. No phase is
inferred from an unapplied proposal, current intent or missing legacy metadata.
Existing D1 verification remains its current gate; Y5 changes need their own checks.

Y5a adds read-only accepted-input/policy status and shared season links to the
existing graphic. Dashboard does not initiate proposals, apply, migrate, match or
alter workouts. Seasons event/settings writes explicitly queue background proposals;
Plan/Seasons can rediscover and prepare pending intent. The graphic still comes
solely from verified applied revisions/origins, including all older saved-plan cases.
Explicit season selection and year links survive reload/navigation; invalid selected
contexts are explained. Future selected seasons default to their own year when no
year is supplied. New workflow status distinguishes same-marker goal/distance/status
changes that the graphic's event-marker comparison alone cannot detect.

Y5a completed **384 distinct checks**, including all three existing D1 browser
scenarios, the D1 reader/regeneration/Charts regressions and three new workflow
browser scenarios. Desktop/390px setup, proposal, selected Plan/Dashboard navigation,
keyboard/table alternatives and applied-revision refresh were verified. See
[Y5a evidence](reports/yearly_y5/README.md). Original D1 evidence is retained.
No generation policy or live schedule changes. Y5b's distance goals and new stored
phase policies remain pending; no phases or achieved readiness are inferred here.
