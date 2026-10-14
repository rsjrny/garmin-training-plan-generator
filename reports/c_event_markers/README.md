# C calendar-marker verification — October 14, 2026

Implemented [C marker policy](../../docs/yearly-c-event-markers.md) in the source
app. No installer build, live user database/schedule change, migration, commit,
push or deployment was performed.

**346 distinct checks passed**. Overlapping reruns are not added to that count:

- 230 scheduling/refinement/baseline/regeneration/timeline/reset cases.
- 70 additional workflow, presentation and NiceGUI data cases.
- 42 C-marker cases, including both methodologies, HM/general baseline, all event
  phases, event/rest/unavailable dates, same-day markers, distance/participation/
  target changes, completed markers, exact CRUD carry-forward, manual locked
  10-mile workout plus 5K, priority changes, nutrition preservation, stale/tampered
  reviews and v3 historical/protected/eligible-future upgrade behavior.
- Four browser cases: the new desktop and 390px marker workflow plus existing
  priority/pace and completion-editor coverage adapted to the new behavior.

Commands used `.venv/Scripts/python.exe -m pytest`, `-q -p no:cacheprovider
--tb=short`:

```text
tests/test_season_generation.py tests/test_season_refinement.py
tests/test_season_baseline.py tests/test_season_regeneration.py
tests/test_yearly_plan.py tests/test_yearly_reset.py
  230 passed in 233.84s

tests/test_c_event_markers.py tests/test_yearly_workflow.py
tests/test_planning_presenter.py tests/test_nicegui_data.py
  109 passed in 187.35s (39 marker + 70 other cases at collection)

tests/test_c_event_markers.py (final full file, including three later cases)
  42 passed in 48.03s

tests/test_c_event_markers_browser.py
  2 passed in 48.45s
tests/test_usability_browser.py::test_event_pace_uses_miles_and_c_priority_disables_taper
tests/test_season_refinement_browser.py::test_completion_duration_editor_keeps_c_as_calendar_marker
  2 passed in the first browser batch
```

Browser artifacts were directed to `reports/c_event_markers/evidence` through
`GARMIN_TEST_ARTIFACTS`. Both new browser cases verify zero added/changed/removed
workouts, 365 retained identities, the marker beside the prescribed long run,
reload persistence, accepted timeline markers and disabled taper/recovery inputs.
Page-error and application-traceback checks pass; no horizontal overflow at either
viewport. Desktop review, phone daily workout and phone timeline-details screenshots
were inspected. Compilation and `git diff --check` pass.

Corrections during verification: the initial 10-mile test used protection version
zero after a manual edit had already created version one; it also assigned ten
miles to every segment rather than to the whole session. Both fixture errors were
corrected. The first new browser run selected `5 km` while the catalog label is
`5K`; corrected and rerun. ASCII-only shell text replacement also produced question
marks in one browser expectation; the literal was corrected using apply_patch.
These failed attempts are excluded from the final pass count.
