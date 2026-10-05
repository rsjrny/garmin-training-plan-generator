# garmin-givemydata 0.1.13 compatibility review

Date: 2026-10-05
Status: Offline compatibility reviewed and source environment upgraded; regression checks verified.

## Candidate and scope

Downloaded the exact PyPI 0.1.13 wheel into a disposable environment before
upgrading the application environment. Runtime requirements match 0.1.12.
Reviewed [upstream release notes](https://github.com/nrvim/garmin-givemydata/releases/tag/v0.1.13)
and installed source differences. The release adds nutrition ingestion, filters
empty daily records, repairs health-status queries, changes FIT backfill and fixes
export credential lookup. Existing source transaction risks remain covered by
the application's privacy/quarantine/archive tests; upgrading does not eliminate
those upstream defects.

## Real database-copy audit

Command:

```powershell
.\.venv\Scripts\python.exe scripts\check_givemydata_upgrade.py --db "<live database>" --candidate-python ".tools\givemydata-013\Scripts\python.exe"
```

Source was opened read-only; an online backup and disposable copies were created.
Private evidence is in `reports/givemydata-upgrades/givemydata-upgrade-nt5ijlky/`.
This directory is ignored by Git because backups/reports contain personal data.

The automated status is `failed` because fresh-schema comparison conservatively
flags changed CREATE TABLE SQL for manual constraint review. All 18 flagged tables
have identical column declarations after ignoring whitespace/order, identical
column attributes and no removed/changed column definitions. The live database
has columns appended by prior migrations; fresh initialization declares them
inline in a different order. This comparison is a review finding, not a reason
to weaken the checker's constraint detection.

Candidate initialization on the existing copy changed no schema objects. The
source already contains the release's nutrition and FIT-file tables. App-owned
row fingerprints remained identical and no activity identities were removed.
Integrity/foreign-key checks produced no other problems. Eight app checks passed:
migrations, required activity columns, ten sampled metric refreshes, Dashboard,
activity list/details, chart queries/figures, planning rows and compliance.

## Source and runtime review

`--no-trackpoints` still gates the new automatic FIT backfill. Canonical app sync
continues to pass this flag and owns archive ingestion/reconciliation. The package
pin, runtime enforcement, packaging defaults/license version checks and current
documentation were moved to 0.1.13. Version-mismatch fixtures now reject 0.1.14.

Installed 0.1.13 in `.venv` and refreshed the project's editable metadata.
`pip check` passes. Isolated runtime validation and the bundled-runtime diagnostic
both accept exactly 0.1.13. Global Python already contained 0.1.13 before this work.

## Regression evidence

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q -m "not browser" -p no:cacheprovider --basetemp .tools/upgrade-013-regression
.\.venv\Scripts\python.exe -m pytest tests/test_givemydata_upgrade_check.py -q -p no:cacheprovider --basetemp .tools/upgrade-013-checker-final
```

Broad run: 1,492 passed, one failure, 18 browser-marked tests deselected in 237.81s.
The failure was the simulated-upgrade fixture using 0.1.13, now the supported
version, while asserting `version_changed`. Updated that fixture to 0.1.14.
Final upgrade-checker run: all 13 passed in 12.99s. Thus all 1,493 distinct checks
are verified across the broad run and focused recheck; reruns are not added to the
count. This includes real upstream transaction and `--no-trackpoints` behavior,
runtime mismatch, privacy/quarantine, archive reconciliation, MCP, UI data,
packaging contracts and scheduling regressions. Logs remain in `.tools/`.

`pip check`, isolated supported-version validation, bundled-runtime diagnostic
and `git diff --check` passed. Existing frozen binaries were not smoke-tested.

## Remaining limits

No real Garmin login/API/download was performed. No live database migration or
schedule application occurred. Packaged executables were not rebuilt; changing
the source environment does not upgrade an already installed frozen application.
The audit samples metrics and reads rather than inspecting every historical row
or rendering every UI page. Release/packaging validation remains separate.
