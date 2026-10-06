# Yearly Plan Workflow and Continuous Training Phases

Created: 2026-10-06 (America/New_York)
Status: Y5a implemented and locally verified (2026-10-06); Y5b pending.
Roadmap: Y5a/Y5b in [Implementation Roadmap](IMPLEMENTATION_ROADMAP.md).
Related: [Yearly scheduling](YEARLY_MULTI_EVENT_SCHEDULING_PLAN.md),
[Dashboard timeline](DASHBOARD_YEARLY_PLAN_VISUALIZATION_PLAN.md),
[Expanded race formats](EXPANDED_RACE_FORMATS_PLAN.md).

## User-approved behavior

The user wants to define a yearly plan first, add or remove individual events,
and have the plan adjust around the listed events with all applicable phases.
Two workflow decisions were confirmed on 2026-10-06:

- Event additions, edits and removals automatically prepare a proposed update.
  The active workout schedule changes when the user accepts that update.
- A year without races uses repeating Base and Build blocks with recovery periods,
  rather than Maintenance throughout.

The user also requested an **Always ready for** distance field on 2026-10-06,
with examples of a half marathon or 10 miler. Treat this as the yearly plan's
ongoing completion-distance goal, shaping baseline training between listed events.

## Review of the current implementation

| Surface | Current role | Gap relative to the requested workflow |
| --- | --- | --- |
| Seasons | Stores dates, athlete inputs, availability and A/B/C event intent; generates and applies one continuous schedule | Event edits save intent but require a separate manual preview action; the yearly setup is hard to discover from Plan |
| Plan | Opens with single-event offline/Codex generators and also displays the active workout calendar | The race-dependent generator appears to be the entry point for all planning; yearly and single-event workflows need explicit separation |
| Dashboard | Displays persisted phases, applied events and separate event intent | Should clearly expose whether the selected yearly plan has pending changes, needs settings, is being prepared, or has conflicts |

The underlying relationship is already suitable: a season stores editable settings
and events, references one canonical training plan, and that plan has an active
immutable revision containing the workouts. The same applied workouts feed Plan,
Dashboard and plan comparisons. Keep this relationship; do not add a second
competing schedule or generate a separate plan for each event.

Existing generation emits BASE, BUILD, EVENT_SPECIFIC, TAPER, EVENT, RECOVERY and
MAINTENANCE. Without a controlling event it selects MAINTENANCE. It does not yet
generate distinct PEAK or TRANSITION blocks. Dashboard can render those labels
when explicitly present; graphic support does not imply generator support.

Existing regeneration already calculates affected ranges from old/new event windows,
expands through neighboring influences, and validates a complete merged schedule.
History, completion, confirmed matches and protected manual/locked occurrences are
preserved. Linked event removal records cancellation, retaining event history;
completed events cannot be removed. Changes become active only through reviewed apply.

The starting-duration field is currently labeled optional, but the Seasons UI does
not supply completed-week history to the generator. Explicit starting weekly minutes
are therefore needed in that workflow. Correct the setup wording and validation;
automatic Garmin history coverage is a separate feature unless deliberately added.

Review anchors, under `src/garmin_data_hub/`:

- `ui_nicegui/pages.py::plan_page`: single-event generator and Seasons link.
- `ui_nicegui/seasons.py::season_editor`, `event_editor`, `remove_event`,
  `generation_editor`, `review_preview`: current manual lifecycle.
- `services/season_plans.py::save_event`, `remove_event`: versioned event intent.
- `services/season_schedule.py::_timeline`, `_baseline`, `generate_season_schedule`:
  phase assignment, starting load and continuous workout generation.
- `services/season_regeneration.py::affected_range`, `protection`, `compose`:
  safe replacement and complete revisions.
- `services/season_generation.py::preview_season`, `apply_season_preview`:
  frozen preview, stale checks and atomic apply.
- `services/yearly_plan_data.py`, `analytics/yearly_plan.py`,
  `ui_nicegui/yearly_plan.py`: read-only Dashboard timeline.

This review used current repository code. An attempted read-only live database open
was unavailable in this session, so no current live season/application state is
asserted here. No database, workout or application settings were changed.

## Proposed user workflow

1. Create or select a yearly plan, such as 2027. Set its dates, methodology,
   availability, long-run day, starting weekly minutes and optional **Always ready
   for** distance without requiring a race.
2. Review and accept an initial schedule, including a race-free schedule when desired.
3. Add, edit, move or remove events in that plan's event calendar.
4. Once valid settings are available, automatically prepare an updated schedule and
   show which phase dates and future workouts would change, with warnings/conflicts.
5. Accept the update to activate it. Dismissal retains the applied schedule and
   clearly indicates that the event list still has unapplied changes.
6. Review the same yearly plan and workouts from Plan and Dashboard.

Expose yearly planning prominently on Plan, with an explicit single-event planning
choice. Keep Seasons as the editor for yearly settings/events and Plan as the detailed
calendar/review surface. Carry the selected season/plan through navigation using the
existing identifiers. Multiple non-overlapping years can coexist; do not introduce
a new global active-plan database pointer.

## Y5a: Yearly workflow and automatic proposed updates

- Make yearly versus single-event planning explicit. Reuse existing season editors,
  generation/review services and canonical storage rather than duplicate them.
- Show clear states: no applied schedule, up to date, changes awaiting review,
  preparing update, settings required, and update blocked by conflicts.
- Derive whether a schedule is current from its applied input/settings/policy
  snapshot, not merely matching event marker names and dates. Goal, distance,
  status, priorities, availability and season-bound changes also matter.
- After a successful event save/removal, debounce or coalesce changes and prepare
  one update for the latest input version. Avoid blocking the UI with generation.
  Reuse the affected-range mode as the default; retain full-future/custom review.
- Reuse already confirmed, unchanged methodology parameters for automatic previews.
  If required inputs or confirmations are missing, show Settings required rather
  than silently invent them or repeatedly prompt after every event edit.
- Discard results for older input versions. Reload/navigation must rediscover
  unapplied intent; an in-memory candidate must not be mistaken for an applied plan.
- Preserve existing stale-preview checks, warning acknowledgments, atomic apply,
  duplicate-apply behavior, protection, immutable origins and match identities.
- Explain what a removed event does: its future preparation/taper/event/recovery
  influence is recalculated, neighboring phases reconnect, and completed/protected
  history remains. Cancellation history stays available without treating it as a
  future planned event.
- Make starting weekly minutes and methodology confirmation clear during setup.
  Include the optional Always ready for distance in yearly settings and plan summaries.
  Initial previews must show existing-workout overlap and cross-year conflicts.
  Older schedules stay readable; do not automatically convert, link or delete them.

## Y5b: Continuous baseline cycles and full applicable phases

Generate a coherent year before any races are listed. Use a deterministic baseline
cycle anchored to the season, with Base and Build blocks and recovery periods.
Document cycle lengths, workload progression/reset rules and the distinction between
weekly cutbacks and a recovery phase before implementing the policy. Keep native
methodology prescriptions and existing workload checks; a phase name does not
authorize incompatible intensity or make a readiness prediction.

### Always ready for: baseline distance goal

- Add a distance selector to yearly-plan settings, including **None / general fitness**,
  10 miler and half marathon, using the existing supported distance catalog. R1 can
  extend the shared catalog and custom-distance handling later. This is a background
  goal, not an event with a date, A/B/C priority, finish time or race-day marker.
- Interpret the selection as maintaining training toward completing that distance,
  not continuously racing at peak performance. Describe it as a goal in the UI;
  a saved setting or generated schedule does not establish achieved readiness.
- Use it to shape baseline long-run development, weekly structure and the
  Base/Build/recovery cycle. Define supported distance-specific policies alongside
  cycle/load rules before implementation; do not invent distance from an HR target,
  apply race-day distance as a recurring workout, or substitute an arbitrary race date.
- Honor starting load, availability, methodology and progression limits. If the goal
  cannot be supported by the available inputs/calendar, explain the constraint in
  preview rather than abruptly raise volume or label the athlete ready.
- Listed events temporarily shape preparation, Peak, Taper, Event and Recovery.
  Recovery/protection takes precedence over the background distance goal. Reconnect
  to its baseline training after recovery; removing all events retains this goal.
- Save the optional value with versioned season inputs and revision snapshots.
  Preserve old seasons with None; do not infer their goal from race names or cached
  plans. Define an unambiguous distance identity compatible with R1 canonical units.
- A changed/cleared distance prepares a proposed future update for accepted apply,
  using the same pending/stale/concurrency behavior as other yearly settings.
  Historical and protected workouts retain their original inputs and prescriptions.
- Show **Baseline goal: half marathon** (for example) in yearly summaries and preview
  rationale. Keep this separate from phase labels and event-specific objectives;
  do not render an inferred Ready badge or replace actual phase provenance.

### Event-driven phase progression

For primary events, provide the applicable progression:

Base → Build → Event-specific preparation → Peak → Taper → Event → Recovery
→ Transition/reconnection → baseline training or Maintenance.

- Define a distinct Peak preparation block and Transition/reconnection behavior;
  specify their durations, eligibility and target/load behavior. Do not simply
  rename EVENT_SPECIFIC to PEAK or reinterpret older revisions.
- B events may have shorter/shared preparation. C events replace training within
  the main progression. Every event does not require an independent full cycle.
- Without events, do not invent Event-specific, Peak, Taper or Event blocks. Render
  the baseline Base/Build/recovery cycles. Define when Maintenance is appropriate.
- Apply event windows to the underlying continuous plan with documented precedence.
  Recovery and conflict checks must still hold when events are close together.
- Removing the final event returns eligible future dates to baseline cycles.
  Adding an event must not reset all cycle anchors or erase unrelated history.
- Account for changed cycle/load dependencies when calculating affected ranges.
  Expand through cycle boundaries and neighboring events until reconnection is valid;
  use full future evaluation if dependencies cannot be contained safely.
- Persist each workout's actual phase and its source/reason: baseline cycle, event
  preparation, event recovery, or reconnection. Preserved workouts retain their
  original phase and origin. Missing legacy metadata remains unavailable.
- Treat year boundaries explicitly. An early-January race may require preparation
  from the preceding year; show available carry-in context and missing preparation.
  Do not squeeze it into January, silently extend ownership, or overwrite a previous
  season. The yearly graphic clips full blocks while preserving actual detail dates.
- Version the generation policy, record inputs/rationale in applied revisions,
  and require reviewed full-future evaluation when moving an older plan to the new
  policy. Existing immutable revisions and old applied schedules remain readable.
- Show phase/date changes and honest weekly targets on the preview, detailed calendar
  and Dashboard. New distances/timed events remain coordinated with R1.

## Completion gates

Y5a:

- Trace create → initial preview → apply → event add/edit/remove → automatic proposal
  → reviewed apply across Seasons, Plan and Dashboard using the same selected plan.
- Verify pending state for every relevant input change, including goal/distance/status
  changes that do not move an event marker.
- Exercise rapid edits, concurrent tabs, late background results, missing settings,
  reload/navigation, dismissed proposals, stale apply and repeated acceptance.
- Retain preserved prescriptions/matches, completed/cancelled history and unrelated
  schedules; verify removal does not rewrite the active schedule before acceptance.
- Inspect desktop and 390px setup, event editing, proposal details and navigation.

Y5b:

- Verify a full event-free year, partial year and leap year; explicit stored Base,
  Build and recovery blocks, deterministic cycle boundaries and workload checks.
- Verify None, 10 miler and half-marathon baseline goals, insufficient inputs/load,
  changed/cleared goals, persistence and old-season defaults. Baseline goal training
  must coexist with event taper/recovery and remain after the final event is removed.
- Add an A event to a baseline year, add nearby B/C events, move an event, and remove
  one/all events; verify every resulting applicable phase and boundary.
- Verify distinct Peak/Transition policy behavior, close-event precedence, calendar
  conflicts, year-boundary carry-in and no false fitness/readiness claims.
- Verify affected-range reconnection against a complete independently prepared
  timeline, without relying on tests that merely repeat the implementation.
- Verify old-policy regeneration, preserved-origin phase labels, malformed/missing
  metadata, unchanged immutable history and read-only graphic behavior.
- Inspect full-year and phase-detail desktop/390px views; record evidence under
  `reports/yearly_y5/`. Update source plans/roadmap only after each gate passes.

## Delivery and scope

Implement Y5a first to make the existing yearly lifecycle understandable and event
updates easy to review. Implement Y5b next to supply the requested race-free cycles,
Always ready for baseline goal and additional phases. Both are required for this
request's complete product outcome.

This is an extension of Y0–Y4 and D1, not a replacement of their storage or protection
design. Automatic application without acceptance, mixed sports/methodologies,
physiological peak prediction, automatic history coverage, expanded formats,
rollback, and deployment remain outside this phase. No implementation, migration,
live schedule apply, package rebuild, commit or push was performed for this review.

## Y5a implementation and completion gate - 2026-10-06

Y5a is locally verified. Plan now leads with a race-optional yearly workflow and an
explicit single-event choice. Seasons owns settings/events; the shared proposal
review is available on Seasons and Plan; Dashboard remains an applied-phase reader.
Selection travels through `season_id` URLs, selectors and shell/detail links, and
survives reload. Plan filters workouts by the selected season's canonical plan;
missing selections are explicit rather than silently displaying another schedule.
No global active-plan pointer or competing schedule was added.

`services/yearly_workflow.py` compares verified accepted input snapshots and policy
versions, including all event fields, athlete inputs, availability and bounds.
It follows accepted revision lineage past manual prescription edits: accepting one
manual workout cannot accept pending yearly intent. Original native parameter
evidence supplies unchanged LTHR/MAF confirmations; default regeneration flags do
not revoke them. Changed prescribing inputs require explicit confirmation.
Unaccepted confirmations bind to their parent revision so a newer acceptance in
another process supersedes remembered settings rather than proposing an old choice.

Successful event/settings saves and removal queue preparation directly. A shared
process-local coordinator coalesces changes, performs generation off the UI thread,
and publishes only results matching the latest coherent intent/runtime/date/policy
fingerprint. It retains affected-range defaults and the existing full-future/custom
review. Current, no-schedule, pending, preparing, settings-required, archived and
conflict states are visible. Recoverable preparation failures can be retried.
Dashboard reads these states without initiating generation or writes.

Proposals are disposable, not active revisions. Closing review retains pending
intent. Reload rediscovers it; after a process restart, accepted confirmations come
from immutable prescriptions/audits and pending proposals can be regenerated.
An initial confirmation not yet accepted is process-local; a restart honestly asks
for settings again. Existing Y3/Y4 warning acknowledgment, stale checks, atomic
apply, duplicate acceptance, history/protection and origin/match identities remain
the apply contract. Editors/dialogs live outside refreshed cards so concurrent-tab
updates cannot close an open editor or discard its captured version.

Starting weekly minutes are explicitly required for UI previews, while incomplete
intent can still be saved. The UI explains that covered Garmin history is not
imported here. Initial review retains existing-workout and cross-year recovery
blockers. Preview phase influence is labeled as preceding preservation; the actual
retained/proposed session phases remain in the candidate session table.

**Always ready for delivery decision:** this Y5a UI exposes a disabled forthcoming
field and general-fitness summaries, without saving an unsupported distance goal
or claiming readiness. The Delivery section places functional goal delivery in
Y5b. That milestone must supply versioned persistence/snapshots, None/10 miler/half
marathon selection, distance policies, baseline cycles, change/clear proposals and
R1-compatible identity. This reconciles the earlier Y5a field mention with its
documented delivery dependencies; Y5b remains unimplemented.

**384 distinct checks passed** across the broad regression and completed final gate;
reruns are not counted again. The completed gate covers 67 distinct service/UI-data checks
and 12 browser scenarios (the corrected invalid-context case passed separately).
The final concurrency recheck passed all 37 workflow cases and all three new browser
scenarios after the parent-confirmation correction.
Create → race-free initial preview/apply → event add/edit/remove → automatic proposal
→ accepted apply was traced across all three pages on synthetic databases.
Rapid/concurrent edits, late results, same-marker changes, dismissal, reload,
missing settings, stale/duplicate apply, corrupt accepted snapshots, overlap and
cross-year blockers, history, locks, original prescriptions/matches and unrelated
years were exercised. Desktop and 390px setup, event dialogs, proposals, acceptance
and navigation were inspected. [Evidence](reports/yearly_y5/README.md) records
commands, corrected failures, screenshots and limits.

Changes remain uncommitted on `ddc2435`. Pre-existing D1 work and the givemydata
acceptance report were preserved. No live database/schedule changes, migration,
commit, push, deployment or package rebuild. Stop at Y5a; Y5b is the next milestone.

### Initial approval overlap follow-up

A reported blocked initial preview exposed a missing ownership-resolution entry
point and excessive repeated-warning rows. The preview now offers read-only
overlap review, explicit linking of compatible canonical plans through the existing
service, grouped warnings retaining all dates, and sticky acknowledgement/actions.
Linking retains the existing workouts; replacement remains a separate accepted
proposal. Overlap review also offers an explicit start after the overlapping rows
when all saved events still fit: it saves intent only, prepares a fresh proposal,
and retains every existing row. Stale ownership/intent is rejected, and generation
and apply repeat the schedule checks. [Follow-up evidence](reports/yearly_y5/approval_followup/README.md).

**Boundary at this follow-up (superseded by reviewed removal below):** the user's 2027 range has three overlapping
older single-event workouts and no compatible canonical owner. This follow-up
does not enable approval over them. Keeping those rows and starting on January 4
is an available separate-dates alternative; no live settings were changed.
Entire-rowset legacy conversion is the current
architecture; year-only adoption/replacement needs a separately reviewed migration
design preserving history, protected workouts, prescriptions and match identities.
Do not delete those rows or bypass initial-apply overlap checks. Functional Y5b
cycles/Always ready for goals are independent of this migration limitation.

Follow-up verification: 137 distinct checks passed across the regression and
corrected rechecks; the clean 48-case completion run passed. There are now 392
distinct passing Y5a/follow-up cases. Desktop/390px ownership, grouped warnings,
reachable controls and the separate-date accepted lifecycle were inspected.

Entered-time clarification: season guidance now acknowledges the numeric weekly
load rather than asking for it unconditionally, and preview-setting messages
name only the selected method's missing confirmation. A read-only check found
270 minutes saved for both user years. Three service and one MAF browser rechecks
passed; desktop/390px inspected. No live settings changed.

### Reviewed older-workout removal follow-up

Plan and overlap review now expose **Remove older workouts**. Selection starts
empty and acceptance applies only the exact reviewed future legacy IDs. Schema
v16 adds immutable audit/membership tables and excludes accepted removals from the
active calendar. Original planned rows remain immutable, visible in saved-original
history, and excluded from later legacy replacement/conversion. Migration itself
adds empty tables and does not retire any rows. Completed/history, today, protected
metadata, recorded-activity dates, converted sources and structured-plan dates are
blocked. Activity matches, canonical prescriptions and origins remain intact.

Preview/dismissal are read-only. Acceptance rechecks intent, events, local date,
policy, full schedule/protection/activity state and nutrition cache atomically;
concurrent acceptance is idempotent. Only selected future-date cache entries are
cleared, with the original cache retained in the audit. Removing the user's three
January overlaps is therefore an explicit reviewed alternative to a January 4
start, without partial canonical adoption or bypassing initial-apply safeguards.
The selected year's updated proposal prepares automatically and needs its own
acceptance. Review opening now waits for the newest valid worker, including when
rapid edits cancel an older worker; canceling a caller does not cancel shared work.

Isolated migration, protection, rollback, stale/concurrent/reload, older writer,
original/match and desktop/390px browser evidence is recorded in
[reviewed removal verification](reports/workout_removal/README.md). The follow-up
gate passed 432 distinct cases, including 15 browser scenarios. No live database
was migrated, no live workouts were removed, and no commit, push, deploy or package
build occurred. D1 and givemydata evidence remain preserved. Y5b remains pending.
