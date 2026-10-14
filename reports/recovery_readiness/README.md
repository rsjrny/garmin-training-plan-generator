# Recovery & Readiness v1 verification — October 14, 2026

Implemented the requested [experimental scoring policy](../../docs/recovery-readiness-policy.md).
No installer build, schema migration, live-user database/schedule write, external
health-data transmission, commit, push or deployment was performed. Preference
saves and all server/browser scenarios used synthetic isolated databases.

## Audit and design

Read-only schema inspection confirmed the configured database has all five health
summary tables, activities and app-owned derived activity metrics. The installed
upstream runtime is garmin-givemydata 0.1.13. Its HRV timeline is aggregated JSON;
the supported pipeline has no RR extraction and quality-control path. Do not infer
RMSSD/SDNN/frequency-domain HRV from nightly averages. No new RR capability is claimed.

Reuse `sleep_recovery`'s table reader, shared calendar-day SQL, current-provenance
TSS access and the existing CTL/ATL/TSB EWM function. Device TSS is preferred;
valid current derived TSS fills gaps; a whole-window duration proxy is explicit.
Garmin exercise-load units are never mixed with TSS or hours. Reading current
device TSS skips unnecessary derived lookups. Assessments and preferences are read
in one transaction; no parallel derived table/cache or post-sync migration is needed.

Scores exclude current/future training and current-day incomplete stress; personal
baselines exclude the assessed day. Unknown/stale signals, immature baselines,
invalid values, partial recent sleep and undated activities stay explicit.
Weighted data coverage propagates through the Recovery subscore into Readiness.
Historical views show their date and age and provide data-check guidance instead
of current training clearance. Latest-available navigation is available on Recovery
and Dashboard. Preference changes do not write to health/plan data.

Configured-database assessment was checked read-only: a 30-day analysis completed
in about 0.08 s. Latest usable health signals were two days old; today's scores
were correctly unavailable, while the latest dated assessment could calculate
all three scores with incomplete load evidence identified. No personal readings,
scores or raw health payloads are saved in this report or browser evidence.

## Tests and visual evidence

121 distinct checks passed; overlapping reruns are not added:

- 61 new score/data/integration cases.
- Two real NiceGUI callback cases: invalid-preference repair and rejecting a late
  worker result after the user changes the selected date.
- 54 existing sleep-analysis, calendar-day, metric-refresh, Coach/privacy,
  local-app-security, Help and Dashboard-copy cases.
- Four browser cases: new desktop and 390px score/date/preference/process-restart
  workflows, stale/partial source handling with latest-day navigation, and the
  existing Dashboard/year-scope/Coach/Help flow.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_recovery_readiness.py tests/test_recovery_readiness_ui.py tests/test_sleep_recovery_analysis.py tests/test_activity_calendar_days.py tests/test_metrics_refresh.py tests/test_coach_chat.py tests/test_nicegui_app_security.py tests/test_help_about_ui.py tests/test_dashboard_plan_copy.py -q -p no:cacheprovider --tb=short
# 117 passed in 4.92s
```

Browser tests used the same pytest flags with `GARMIN_TEST_ARTIFACTS` set to
`reports/recovery_readiness/evidence`:

```text
tests/test_recovery_readiness_browser.py
tests/test_usability_browser.py::test_dashboard_year_scope_coach_context_and_help
  4 passed in 43.86s
```

Checks include independence from Garmin composite scores, bounded estimates,
unusually high HRV, sleep-target shortfall, multiple unfavorable signals, load
spikes, partial/empty tables, invalid/sentinel values, no missing-date imputation,
local midnight, current versus stale derived-TSS provenance, undated activities,
coherent reads during a concurrent WAL write, deterministic input identity,
saved-target repair/persistence, and unchanged active-workout fingerprints.

Browser scenarios check no horizontal overflow, score/driver/Garmin/date labels,
invalid future-date handling, visible historical status, saved-target persistence
after a full process restart, Dashboard links, missing current data and unsupported
RR messaging. Page-error and unexpected-application-traceback checks pass.
Desktop/390px scores, comparisons, preferences, Dashboard and stale-source screenshots
are in `evidence`; representative views were visually inspected. Compilation and
whitespace checks pass.

Corrections during verification: one synthetic settings insert omitted the schema's
third defaulted column; fixed to name key/value columns. Expected validation errors
initially logged tracebacks; changed to informational validation logs while real
database failures remain logged. A phone test kept an old websocket open while
restarting the isolated server, causing an aborted navigation; close/reopen its
page across restart. Corrected cases were rerun successfully; failed attempts are
excluded from the pass count.

Implementation/property tests do not clinically validate score weights or guidance.
Prospective calibration is recorded as an open backlog item. The engine remains
experimental, local and advisory and does not update workouts or Coach payloads.
