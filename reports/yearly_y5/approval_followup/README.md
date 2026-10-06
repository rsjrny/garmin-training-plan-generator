# Y5a blocked approval follow-up

The original overlap limitation documented below is superseded by a separate
explicit future-legacy removal review. Original rows are retained; partial
canonical adoption remains unsupported. See the
[current removal verification](../../workout_removal/README.md).

Date: 2026-10-06. No live schedule writes, commits, push, deployment or packaging.

The reported initial preview was correctly blocked by overlapping workouts but
offered no usable ownership review, and hundreds of repeated Maffetone warnings
buried the acknowledgement/apply controls. This follow-up fixes that presentation
and adds the existing canonical-plan linking path directly to the blocked preview.
It does **not** claim to enable year-only replacement of older flat schedules.

## Implemented and preserved boundaries

- A read-only, coherent ownership diagnostic lists the overlapping active workouts
  and unowned canonical plans. It explains differing methodology, prior history
  outside yearly dates, other overlapping owners and archived-year constraints.
- The preview opens an explicit overlap review. Compatible canonical plans can be
  linked only after acknowledgement, using the existing optimistic-version,
  revision/content/projection checks. Linking retains all workout rows; a separate
  newly reviewed replacement proposal is still required to change prescriptions.
- An explicit separate-start choice keeps every existing workout and moves yearly
  intent to the day after the last overlap, never earlier than local today. It is
  unavailable if it would exclude a saved event or exceed the year's end. It
  rechecks ownership/intent before optimistic save, prepares a fresh proposal,
  and never applies automatically. Concurrent edits require reopening review.
- Older single-event schedules are explicitly unavailable for direct linking or
  year-only replacement. The source architecture defines entire-rowset legacy
  conversion and does not support partial adoption. No conversion, deletion,
  schedule bypass or new storage/migration was introduced.
- Warnings are grouped by code, message and event identity. Every occurrence and
  dated resolution note remains available. Conflicts are never condensed. The
  existing warning acknowledgement and apply safeguards remain authoritative.
- A sticky acknowledgement/action area remains accessible when scrolling long
  yearly previews. Disabled apply states explain the blocker.

A strictly read-only diagnostic of the user's existing 2027 yearly bounds found
an unlinked year and **three overlapping older single-event workouts**, with no
overlapping canonical owner. SQLite was opened with `mode=ro`, `query_only=ON` and
a read transaction; no live migrations or scheduling operations ran. Consequently
the user's particular year still requires an explicitly reviewed legacy migration
before replacement can be enabled. This is a remaining capability boundary, not
a warning-acknowledgement problem. The entire unconverted older schedule contains
364 rows from 2026-01-05 through 2027-01-03. Keeping the three 2027 rows and choosing
**2027-01-04** as the new yearly start is a supported alternative: it avoids partial
migration and leaves the older calendar intact. This was implemented/tested on
synthetic data; the user's live start remains unchanged.

## Verification

All browser servers and service tests use synthetic, isolated test databases.
The reproduction uses a 270-minute Maffetone year: 215 warnings condense into four
groups while apply remains blocked by the existing flat workout. Desktop and
390px previews, scrolled sticky actions, legacy ownership review, canonical
link review and the subsequent replacement review were rendered and inspected.
The separate-start path also rejects concurrent intent changes, then saves revised
dates without changing the active schedule. The subsequent accepted proposal is
applicable and leaves the original flat workout byte-for-byte unchanged. Two
additional service cases cover saved-event exclusion and no dates remaining.

Initial targeted checks: `test_season_overlap.py`: **4 passed** (0.92s);
the two new browser scenarios: **2 passed** (17.85s). The first browser attempts
corrected a Python Playwright `first` property typo and selected explicit current
intensity refresh when replacing a canonical fixture with older pace parameters.

The combined regression's rapid-edit check exposed a wall-clock assumption:
SQLite fingerprint reads can outlast a one-second debounce on a loaded machine.
The test now holds the edit-burst boundary with an asyncio event, keeps real
generation, and requires all superseded tasks to coalesce/cancel. The corrected
case passed independently (**1 passed**, 6.10s). The production coordinator and
debounce behavior were not changed.

Combined regression: **134 passed, one timing-sensitive test failed** (384.66s).
The corrected rapid-edit case passed independently; all 135 distinct cases passed
across those runs. Final separate-date checks: **8 passed, 3 deselected** (24.70s).
Seven targeted service checks and two browser rechecks also passed (7.37s / 17.87s).
Completion recheck: **48 passed** (212.62s), covering all 37 workflow service
cases, all six overlap/grouping service cases and all five Y5a browser scenarios.
The follow-up verification union contains **137 distinct passing checks**, including
all 14 yearly/Seasons browser scenarios; reruns are not counted again. The combined
Y5a and follow-up union contains **392 distinct passing checks** (384 + six new
service cases + two new browser scenarios).
The final desktop date-choice capture recheck passed (**1 passed**, 11.87s);
both desktop and 390px choices were visually inspected. `git diff --check` passed.
Command:

```powershell
$env:GARMIN_TEST_ARTIFACTS='reports/yearly_y5/approval_followup'
.venv/Scripts/python.exe -m pytest tests/test_yearly_workflow.py tests/test_season_overlap.py tests/test_season_plans.py tests/test_plan_offline_ui.py tests/test_nicegui_data.py tests/test_yearly_workflow_browser.py tests/test_season_generation_browser.py tests/test_season_regeneration_browser.py tests/test_season_refinement_browser.py tests/test_seasons_browser.py tests/test_yearly_plan_browser.py -q -p no:cacheprovider --basetemp .tools/y5a-approval-final
```

Final completion command (output in `.tools/y5a-approval-completion.log`):

```powershell
.venv/Scripts/python.exe -m pytest tests/test_yearly_workflow.py tests/test_season_overlap.py tests/test_yearly_workflow_browser.py -q -p no:cacheprovider --basetemp .tools/y5a-approval-completion
```

## Screenshots

- [Desktop grouped preview](test_blocked_legacy_preview_has_reachable_actions_grouped_warnings_and_honest_resolution-25e7ed4c70/overlap_warnings_desktop.png)
- [390px grouped preview](test_blocked_legacy_preview_has_reachable_actions_grouped_warnings_and_honest_resolution-25e7ed4c70/overlap_warnings_390.png)
- [390px scrolled actions](test_blocked_legacy_preview_has_reachable_actions_grouped_warnings_and_honest_resolution-25e7ed4c70/reachable_blocked_actions_390.png)
- [Desktop older-schedule review](test_blocked_legacy_preview_has_reachable_actions_grouped_warnings_and_honest_resolution-25e7ed4c70/legacy_overlap_desktop.png)
- [390px older-schedule review](test_blocked_legacy_preview_has_reachable_actions_grouped_warnings_and_honest_resolution-25e7ed4c70/legacy_overlap_390.png)
- [390px explicit canonical linking](test_overlap_can_explicitly_link_canonical_plan_then_review_separate_replacement-4f50fda253/canonical_overlap_390.png)
- [390px separate replacement preview](test_overlap_can_explicitly_link_canonical_plan_then_review_separate_replacement-4f50fda253/linked_replacement_390.png)
- [390px retained-workout date choice](test_blocked_legacy_preview_has_reachable_actions_grouped_warnings_and_honest_resolution-25e7ed4c70/separate_dates_choice_390.png)
- [Desktop retained-workout date choice](test_blocked_legacy_preview_has_reachable_actions_grouped_warnings_and_honest_resolution-25e7ed4c70/separate_dates_choice_desktop.png)
- [390px applicable separate-date proposal](test_blocked_legacy_preview_has_reachable_actions_grouped_warnings_and_honest_resolution-25e7ed4c70/separate_dates_applicable_390.png)

Raw browser logs remain beside each scenario's screenshots. Existing D1 and
givemydata acceptance evidence is retained.

## Entered weekly time clarification

The reported season editor showed 270 weekly minutes alongside an unconditional
"Enter your current weekly running minutes" helper. A read-only check confirmed
**270 minutes are saved in both 2026 and 2027**; no weekly-time requirement was
missing. The editor now displays the entered amount, updates guidance with the
field, and states the selected method's separate confirmation requirement.
Maffetone settings-required messages request its adjustment without mentioning
unneeded LTHR. No validation, scheduling policy or live settings changed.

Targeted service recheck: **3 passed** (8.88s), covering missing starting load,
MAF confirmation reuse/change and initial confirmation/restart. The updated MAF
browser lifecycle passed (**1 passed**, 12.17s); desktop and 390px were inspected.
These are reruns of existing cases, not additions to the 392-check union.
The final 390px guidance capture recheck also passed (**1 passed**, 12.16s).
Evidence links and `git diff --check` passed.

- [Desktop entered weekly time](test_blocked_legacy_preview_has_reachable_actions_grouped_warnings_and_honest_resolution-25e7ed4c70/entered_weekly_time_desktop.png)
- [390px entered weekly time](test_blocked_legacy_preview_has_reachable_actions_grouped_warnings_and_honest_resolution-25e7ed4c70/entered_weekly_time_390.png)
- [390px method and time guidance](test_blocked_legacy_preview_has_reachable_actions_grouped_warnings_and_honest_resolution-25e7ed4c70/entered_weekly_time_guidance_390.png)
