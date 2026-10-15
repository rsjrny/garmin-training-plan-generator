# Training app backlog

Last audited against the repository on 2026-10-01. Completed migration notes and other historical implementation logs have been removed; Git history remains the source for that detail.

## Recently completed

- [x] Navigation starts visible beside desktop pages, with a labeled Menu toggle and close arrow; smaller screens start closed and open navigation over the page. Accessible state and desktop/phone layouts verified in [verification](reports/navigation/README.md).
- [x] Workout heart-rate ranges from saved 80/20 LTHR or Maffetone age/adjustment prescriptions, with per-section targets, secondary-HR labels and preserved original ranges. Visible in Plan, Dashboard, proposal summaries and Compliance; older workouts without numeric prescriptions remain unavailable. See [verification](reports/workout_heart_rate/README.md).
- [x] Browse races page: Running in the USA starter bookmarks, user-selected in-app website viewing, regular-browser fallback, locally saved race-site bookmarks and selected-year Events link. Running in the USA's confirmed framing restriction now routes its buttons directly to the browser, with no failed iframe. Public website address validation and desktop/phone checks are recorded in [verification](reports/race_browse/README.md).
- [x] Add common race-finder tiles (RunSignup, UltraSignup, FindMyMarathon and ACTIVE) plus a standalone Add your own site dialog. URL-only additions use the hostname as the tile name; saved tiles persist and can be removed without altering the common directory or existing bookmarks.
- [x] Plan week calendar with a direct workout-table switch, saved hard/long/strength/rest/event labels, weekly density and covered-volume summaries, cross-week consecutive-hard-day indicators, date jump and responsive phone agenda. C markers preserve the existing workout. See [verification](reports/plan_calendar/README.md).
- [x] Dashboard Today / next 7 days overview: selected-plan sessions, current dated recovery, C-event markers and the previous seven days' reviewed completion, with refresh and scoped Plan/Compliance/Recovery links. Desktop/phone and read-only snapshot checks are recorded in [verification](reports/dashboard_focus/README.md).
- [x] Workout matching and compliance v1: reviewed one-to-one Garmin associations, moved/partial results, missed/extra sessions, training-day streaks and weekly recorded volume/variance. Supports canonical and older saved workouts; preserves originals and confirmed evidence during yearly regeneration/redo. See [policy](docs/workout-compliance-policy.md) and [verification](reports/workout_compliance/README.md).
- [x] Treat yearly C events as calendar markers that preserve the baseline goal and daily workout. Marker-only updates keep all accepted prescriptions and origins unchanged; editor, weekly view and timeline explain the behavior. See `docs/yearly-c-event-markers.md`.
- [x] Data Query renders MCP list-of-object responses as structured, bounded tables, with charts for dated numeric data and raw JSON/text fallbacks for nested or non-tabular payloads. Regression coverage is in `tests/test_mcp_results.py`.
- [x] Windows installer code signing is available through `packaging/build.ps1`, with SignTool discovery, certificate selection by thumbprint/subject/PFX, documented invocation, and packaging regression coverage.

## Current priorities

### Deferred validated architecture work

- [ ] Phase 3G metric-refresh performance: deferred because the single-user
  targeted refresh has no demonstrated production performance problem.
- [ ] In-app version/commit display: release artifacts currently carry
  provenance in `SOURCE-COMMIT.txt`; UI display is deferred.
- [ ] Phase 3F legacy callable surfaces: keep quarantined and revisit only with
  evidence.
- [ ] Phase 3I DB/UI seam refactor: deferred because there is no demonstrated
  correctness need.

### Data Query

- [ ] Add saved query/tool presets for common athlete questions: recent long runs, weekly load, missing metrics, recovery trends, and upcoming workouts.
- [ ] Show MCP execution details beside the Run button: timeout, retry count, and the latest error. Basic connected/unavailable status already exists.

### Dashboard

- [ ] Turn diagnostics into action cards: one-click repair for missing derived metrics, Plan for no upcoming schedule, and Garmin Sync for stale data. The current missing-metrics card only links to Sync.
- [x] Add a compact Today / next 7 days view combining planned sessions, recent compliance, and recovery signals. Rolling seven-day overview and recent reviewed completion now appear together on Dashboard; existing week navigation and activity grids remain available.

### Plan and Codex Coach

- [x] Add a simple “Redo this year / start over” workflow for yearly training plans. The user is stuck on conflicts and older workouts, and the current resolution flow is not working for them.
  Let the user choose the year and restart date, keep or edit its settings/events, and review one fresh replacement plan. Include superseding all eligible unfinished future workouts in that year—older single-event/legacy rows, canonical yearly workouts, and explicitly selected locked/manual workouts—in the same review and acceptance. Archive the superseded schedule and retain original revisions, completed activities, matches and past training history. Do not require separate linking, older-workout removal or individual ownership-conflict resolution before restarting; obsolete schedule overlaps should be handled by the reset itself. Clearly show what will be replaced and retained, distinguish real event/calendar constraints from obsolete-workout conflicts, and provide actionable guidance for any remaining blocker. Apply retirement/replacement atomically with stale-state checks and rollback on failure; leave other years untouched. Verify legacy/canonical overlaps, locked/manual selection, completed history, cancelled events, stale proposals, failure rollback and desktop/phone usability.
- [x] Add a calendar/week view alongside the plan grid so training density, hard-day spacing, long-run placement, strength sessions, and race week are easy to inspect. Plan → Workouts offers Week calendar / Workout table, saved labels and weekly summaries; navigation retains the chosen week when switching views.
- [ ] Add import-history review and restore controls using the existing `plan_import_history` archive.
- [ ] Show the privacy-minimized coaching packet as a friendly summary before generation, with expandable raw packet JSON.
- [ ] Add “regenerate with feedback” controls that append athlete notes while preserving locked hashes, policy checks, and explicit approval.

### Compliance and activities

- [x] Match planned workouts to completed activities using date window, sport, duration, and distance so moved workouts are recognized. Explicit review, ambiguity and immutable activity ownership are enforced.
- [x] Classify sessions as completed, partial, missed, extra, or moved; summarize streaks and weekly distance/duration variance. Missing evidence and open matching windows remain explicit; distance summaries currently cover running.
- [ ] Add best-effort personal-record and benchmark badges for longest recent run, fastest common distances, highest TSS, and highest elevation gain.
- [ ] Add route/trackpoint quality indicators for missing FIT trackpoints, sparse GPS, and map-render gaps.

### Analysis and settings

- [x] Add synchronized chart filters and an “explain this point/week” drill-down to source activities. C2 includes Explorer and tab-session state; see the Charts plan handoff.
- [x] Promote Sleep & Recovery from a Data Query tab to a first-class Recovery page or dashboard panel. Recovery now has its own page and Dashboard summary; the existing Data Query trend analysis remains available.
- [x] Build a Recovery & Readiness Engine with Welltory-style explanations and independent daily recovery, readiness, and energy scores, with Garmin scores available for comparison. Experimental v1 implemented October 14, 2026; see `docs/recovery-readiness-policy.md` and `reports/recovery_readiness/README.md`. Implementation validation is complete; outcome calibration remains below.
  Start by auditing the SQLite schema, Garmin/FIT ingestion, and existing derived-metrics infrastructure; reuse the current calculation pipeline. Combine personal HRV and resting-HR baselines, sleep debt, stress, recent training load, and accumulated fatigue into an explainable daily assessment and training recommendation. Identify missing inputs and whether beat-to-beat RR intervals are available for detailed HRV analysis. Show data coverage, confidence, and score drivers; validate calculations and recommendations before connecting them to coach guidance or proposed workout adjustments.
- [ ] Calibrate recovery/readiness/energy estimates against prospective training outcomes and athlete feedback before using them to adjust workouts or making validated recovery claims. Current v1 is advisory, exposes missing/partial/stale evidence, and leaves workouts unchanged.
- [ ] Add database-health tools for backup location, database size, last successful sync, last derived-metrics refresh, and quick export.

### Quality and reliability

- [ ] Reduce card nesting and tighten card radius; reserve large headings for page-level context.
- [ ] Verify narrow-window layouts for the dashboard, plan, coach review, and query results so grids and controls do not overflow.
- [ ] Replace broad silent exception fallbacks in data, query, and ingest paths with logged warnings and user-visible data-quality messages when missing data changes conclusions.
- [ ] Add regression tests for plan restore. Compliance matching/classification, Recovery/Dashboard integration and Data Query tabular rendering are covered.

## Longer-term ideas

- [ ] Adaptive replanning: after each sync, compare completed load, missed workouts, recovery trends, and event timeline, then suggest a conservative plan adjustment for approval.
- [ ] Readiness-aware coaching: combine sleep, HRV, resting HR, stress, recent load, and athlete notes into daily guidance without automatically changing the plan.
- [ ] Subjective wellness log: add quick local check-ins for soreness, mood, sleep quality, illness, pain, and perceived exertion.
- [ ] Workout library: build reusable structured workouts with intent, target zones, progression rules, and export-friendly structure.
- [ ] Periodization templates: support base rebuild, maintenance, race-specific build, return from injury, and post-race recovery.
- [ ] Route and terrain intelligence: summarize climb distribution, available surface hints, weather context, and course-specific preparation needs.
- [ ] Goal forecasting: estimate whether current trends support the event date, flag schedule risk, and show what would need to change.
- [ ] Fueling planner: turn stored macro ranges and sodium settings into workout-duration-specific reminders while keeping medical and diet claims out of scope.
- [ ] Plan explainability: show the evidence behind each major plan change, including recent load, long-run history, recovery signals, and policy constraints.
- [ ] Scenario planning: compare conservative, standard, and ambitious proposals before accepting one.
- [ ] Multi-sport planning and compliance for cycling, triathlon, hiking/ultra, and strength-focused blocks.
- [ ] Calendar and structured-workout exports for the accepted active plan.
- [ ] Data provenance view: expose source tables, formulas, refresh timestamps, and confidence/coverage scores.
- [ ] Automated packaged-app smoke tests that launch the frozen app, visit every route, and verify key panels are populated.
- [ ] Dedicated privacy/export screen showing what is sent to Codex, what stays local, and how to delete credentials, logs, and browser sessions.
- [ ] First-run onboarding for sync, metric refresh, plan setup, baseline generation, and optional Codex sign-in.
