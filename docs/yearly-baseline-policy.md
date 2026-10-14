# Yearly continuous training policy v3, with C marker follow-up v4

Defined before implementation on October 13, 2026. These are conservative product
scheduling rules, not a validated prediction of fitness or race completion.

## Baseline calendar and load

The anchor is the Monday of the week containing the saved season start. Each
56-day cycle has three Base weeks, four Build weeks, then one Recovery week.
The first/last partial week is clipped, never compressed; leap days and year
boundaries do not restart the anchor. Event edits do not move it.

Base starts at the entered/covered starting weekly running duration. Complete
normal weeks may grow 5%, capped at 125% of that starting duration (and 40 hours),
and never above 110% of the actual last complete normal running week.
Recovery resets the envelope to no more than the starting load/last normal load
and uses 60% of it for a baseline recovery week. Baseline recovery has easy runs,
rest and gentle mobility; it does not impose post-race three-day complete rest.
Return after recovery starts at the reset envelope. The existing age-dependent
75% weekly cutback remains separate: it reduces volume without changing the
phase label. No quality is added in Recovery, Transition, Taper or Peak.

## Optional completion-distance goal

Always ready for uses the existing distance codes and authoritative integer
metres from the shared catalog. None means general fitness. It is a background
completion goal without a race date, priority, finish target or readiness badge.
The optional code extends season-input.v1 additively; absent old fields decode as
None. Existing input_version and immutable accepted snapshots version changes.
No database migration or rewrite of old seasons/revisions is needed.

| Distance code | Long aerobic session planning ceiling (minutes) |
| --- | ---: |
| None | Existing double-weight long-run share |
| 5K | 30 |
| 10K | 60 |
| 10M | 90 |
| HM | 105 |
| 20M | 120 |
| MAR | 150 |
| 50K | 150 |
| 50M | 180 |
| 100K | 180 |
| 100M | 180 |

These ceilings specify time-based baseline development, not an estimated distance
or minimum sufficient preparation. Ultra goals retain conservative baseline
training and always warn that event-specific preparation is still required.
A selected goal prioritizes a three-weight long-run share during baseline Build
instead of the usual two-weight share. Cap it at the goal ceiling and at 110% of
the usual long-run share; redistribute no removed minutes. This prevents changing
a goal from abruptly adding volume or applying the event distance every week.
Base retains the usual share, capped at the same ceiling. Long sessions also grow
by at most 10% from the last complete normal long session; cutbacks/recovery do not
replace that development reference. A goal needs at least
three configured run days and a long-run budget able to reach its planning ceiling;
insufficient weekly load or time generates an explicit constraint warning.
Short seasons warn when no baseline Build opportunity is present. Volume never
jumps to satisfy the ceiling and a ceiling does not establish readiness.

## Event overlay

Existing preparation/taper/recovery lengths and A/B rules remain. Within the
existing preparation window, A events reserve the last seven days as Peak; B
reserve the last three. Peak exists only with at least fourteen preparation days.
It uses 90% of the running budget, easy native prescriptions and a capped long run;
it is distinct from both event-specific development and taper. Earlier preparation
still progresses Base → Build → Event-specific. Under the October 14 policy v4
follow-up, C is a calendar marker with no preparation, Peak, taper, race-day
reservation, recovery or transition. Its distance never replaces or caps the daily
workout. See [C markers](yearly-c-event-markers.md).

Seven days after event recovery form Transition: two days at 50%, two at 65%,
three at 80%, with easy short runs/rest and no quality or long-run flag. The underlying
season cycle reconnects after this window. If another event owns those dates,
its preparation/taper takes precedence; recovery always retains its full window.
Precedence: event-day reservation (conflicts still block), event Recovery,
A Taper, A preparation, supporting Taper/preparation, Transition, baseline cycle.
Multiple recoveries/transitions use the most conservative budget. Baseline
Recovery yields to explicit event preparation. Maintenance is retained only as
an explicit legacy phase; v3's supported running calendar uses baseline cycles.

Preparation before a season is reported as unavailable carry-in; no ownership
extends into the preceding year. Recovery overflow is reported and checked across
seasons. Stored original phases are never inferred or relabeled.

## Regeneration and provenance

Generator/policy v4 require reviewed full-future evaluation for older policies.
On the current policy, C-only marker edits preserve the accepted schedule exactly.
Event changes also evaluate all eligible future dates: overlay changes and preserved
weekly load can propagate beyond the event window, so a bounded dependency range
cannot yet be proved safe. Custom ranges remain subject to complete merged validation;
they cannot accept a policy/settings/event change while omitting the recommended
future range. History, confirmed/candidate matches, manual locks and original
identities remain protected. Save prepares intent; only reviewed Apply activates it.

Every new workout stores its actual phase, source (BASELINE_CYCLE,
EVENT_PREPARATION, EVENT_TAPER, EVENT_DAY, EVENT_RECOVERY, EVENT_RECONNECTION),
cycle anchor/index/week and controlling/influencing events. Revision snapshots
record baseline goal identity, cycle policy and per-day phase evidence. Preserved
workouts retain their original metadata. The timeline continues reading original
workouts, not overlay controls or current intent.
