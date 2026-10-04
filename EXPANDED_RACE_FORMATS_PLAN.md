# Expanded Race Formats Plan

Created: 2026-10-04
Status: Planned; R1 implementation has not started.
Roadmap: [R1](IMPLEMENTATION_ROADMAP.md#r1---expanded-race-distances-and-timed-events-pending)
Related: [Yearly scheduling](YEARLY_MULTI_EVENT_SCHEDULING_PLAN.md),
[Dashboard yearly graphic](DASHBOARD_YEARLY_PLAN_VISUALIZATION_PLAN.md).

## Objective

Support more fixed race distances and fixed-duration races in single-event planning
and Seasons, including 1-hour, 8-hour and 24-hour events, with coherent preparation,
taper, recovery and protected regeneration.

## Event formats and presets

Keep course type (road/trail) independent of format (fixed distance/fixed duration).
Preserve existing distance options and add these initial presets where absent:

| Fixed distance | Fixed duration |
| --- | --- |
| 1 mile, 5 km, 5 miles, 10 km, 10 miles | 1, 6, 8 hours |
| Half marathon, marathon | 12, 24, 48 hours |
| 50 km, 50 miles, 100 km, 100 miles | Custom hours/minutes |
| Custom positive km/mile distance | |

Store exact canonical quantities with unit-aware display. Named half/full marathon
presets retain their standard exact lengths. Avoid repeated conversion rounding.
Reject nonfinite, zero, negative and malformed values. Discover existing limits
and document supported custom bounds separately from generation policy limits.

## Goal semantics

For fixed-distance races, retain completion, finish-time and pace goals. Estimated
participation duration remains an estimate rather than the defining race format.

For timed races, the fixed duration defines the race; distance is optional and may
be a performance target. Support participation/completion without requiring a
distance target. Keep allotted duration, planned participation, target distance
and recorded result separate. Define shorter participation explicitly if supported;
do not silently shorten the race or reinterpret duration as predicted finish time.

Switching formats must clear incompatible inputs or require an explicit resolution
in the editor. Format-specific controls and summaries should make units obvious.
Do not manufacture pace, target distance or guaranteed performance from duration.

## Discovery and persistence

Trace the distance catalog, single-event builders, season event validation/storage,
canonical event workouts, revisions/origin mappings, preview/apply/regeneration,
matching, exports and all UI consumers before editing the schema.

Existing season code distinguishes road/trail and has participation-duration
semantics; a timed format must not overload either field. Record a schema contract
for format, authoritative distance/duration, optional goals, date/time semantics
and result fields. Use existing result storage where suitable rather than adding
an unrelated results system.

Migrate existing events as fixed-distance without rewriting immutable revisions.
Preserve legacy readers or fail explicitly on unsupported new formats. Include
format/goal changes in stale-preview checks and transactional apply. Existing
completed/manual/locked workouts and confirmed match lineage remain protected.

## Scheduling policy

Create an explicit policy table for supported fixed-distance and timed categories,
including preparation emphasis, taper/recovery windows, event workload and reasons.
Policies must reflect existing methodology and athlete inputs; do not silently map
timed races to an arbitrary distance or extrapolate training volume without bounds.
Document which policies are product assumptions and which require further review.

Resolve overnight and multi-day occupancy in athlete-local dates. Discover whether
event start time/timezone is needed; when absent, state conservative date coverage
instead of inventing an exact finish timestamp. Separate wall-clock duration from
training totals and avoid double-counting event workload across occupied days.

Exercise A/B/C priorities, close events, taper/recovery precedence, unavailable
dates and year/season boundaries. Explain unsupported or unsafe generation cases
in preview; accepting an event record does not imply every case can be generated.
Unknown distance/load stays unknown. Preserve atomic apply and stale-preview guards.

## UI and integration

Expose format selection, presets and custom quantities in single-event and Seasons
editors. Use shared labels/validation so the same event has the same meaning across
Plan, Seasons, previews, exports and D1. Timed labels read, for example, "8-hour race".
Show multi-day spans where known and optional target distance with its goal label.
Keep editors usable by keyboard and at 390px with clear inline validation.

## Implementation sequence

1. Inventory consumers and document format/storage and scheduling policy decisions.
2. Add compatible domain validation/persistence and migration verification.
3. Extend canonical generation, preview, apply and protected regeneration.
4. Update editors, labels, exports and Dashboard integration.
5. Run acceptance checks and record source-plan/roadmap handoffs.

## Completion gate

- Presets/custom values, exact conversions, valid bounds and format/goal switching.
- Existing single-event behavior, legacy migration and unchanged immutable history.
- Representative short-distance, marathon, ultra and 1/8/24-hour plans; 48-hour
  occupancy and explicit unsupported-policy behavior where applicable.
- Overnight, multi-day, leap/year boundaries and overlapping A/B/C events.
- Taper/recovery/workload policy explanations and no fabricated target measures.
- Stale previews, failed-apply rollback and protected regeneration/match lineage.
- Consistent labels/exports, desktop/390px editor evidence and keyboard workflows.
- Shared scheduling and matching regression checks proportionate to the changes.

Record commands/results, migration cases, policy decisions and screenshots under
`reports/race_formats_r1/`. Required unavailable checks must remain open.

## Outside this phase

Automatic activity confirmation, new sports, lap-based race scoring, race prediction,
nutrition/fueling strategy, deployment and live schedule application are separate.
