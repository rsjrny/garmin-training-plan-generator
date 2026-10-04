# Dashboard Yearly Plan Visualization Plan

Created: 2026-10-04
Status: Planned; D1 implementation has not started.
Roadmap: [D1](IMPLEMENTATION_ROADMAP.md#d1---dashboard-yearly-plan-graphic-pending)
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
