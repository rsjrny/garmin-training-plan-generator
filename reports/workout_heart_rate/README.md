# Workout heart-rate targets — 2026-10-14

Plan calendar cards, the detailed workout table, Dashboard sessions, proposal
summaries and Compliance session details now display saved heart-rate targets.
Expandable sections preserve warm-up/work/recovery/cool-down order and repeat
iteration labels rather than merging intervals into one misleading wide range.

Yearly generation already derives 80/20 prescriptions from confirmed running
LTHR and Maffetone prescriptions from age and the confirmed adjustment. This
change exposes those accepted values without recalculating workouts from current
settings. HR may be primary or explicitly labeled secondary to pace/power.
Preserved workouts retain their original prescriptions. No methodology policy,
revision hashes, projections, matches or live user records were changed.

Whole-bpm bounds are rounded inward: inclusive lower uses ceil, exclusive lower
uses floor plus one, inclusive upper uses floor, exclusive upper uses ceil minus
one. An additional saved ceiling is respected. Open-ended bounds remain
one-sided; an interval containing no whole bpm is reported explicitly.
Missing HR sections stay unavailable. Rest, strength and mobility report
Not prescribed. Older untyped workouts do not acquire ranges from titles or
current athlete settings; the UI directs users to Settings and reviewed
regeneration for missing prescriptions.

## Verification

264 distinct tests verified across the final scope: 256 service/data/UI cases
and 8 desktop/390px browser cases. The broad source run passed 232 cases and
found a test-fixture import removed during modernization; restoring the import
passed all five presenter cases in the subsequent 22-case focused run.
The separate chart/browser scope passed all 31 cases. Final focused HR browser
checks also pass. Earlier unsuccessful test commands using nonexistent test
filenames did not run any cases.

Coverage includes exact boundaries, MAF ceiling, secondary HR, section/repeat
ordering, missing sections, non-running sessions, real generator settings for
both methods, ignored mutable projections/current athlete values, unchanged
database snapshots, preserved workout targets during regeneration, plan
generation/application, reviewed matching and Dashboard refresh.

Desktop and phone evidence under [evidence](evidence/) was inspected for
calendar sections, table targets and Dashboard targets. Browser checks require
no page errors, no application tracebacks and unchanged active schedule hashes.
The table retains its existing horizontal scrolling on narrow screens.

The source app must be stopped and restarted with the user's existing command:

    .\.venv\Scripts\python.exe -m garmin_data_hub.ui_nicegui.app --port 8091

No installer build, live database write/migration, commit, push or deployment.
