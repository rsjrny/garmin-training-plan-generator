# Redo this year - reviewed restart

Implemented October 13, 2026 after the user showed a current-year conflict screen
and asked for a usable way to redo the year. Y5b was already complete; this adds
the separate restart workflow requested in the backlog.

## What changed

Plan and yearly settings now show Redo this year directly. Choose a future restart
date, optionally include unfinished locked/manual workouts and optionally clear
upcoming events, review the exact replacements and refreshed schedule, then accept
Apply yearly restart. Dismissing either dialog leaves the database unchanged.

The same transaction retires older legacy rows, supersedes eligible unowned older
structured plans and activates the selected year's fresh revision. Original legacy
rows and canonical revisions remain available; past/today/completed workouts,
confirmed/candidate match identities and other years are preserved. Old historical
ownership overlap and the initial-past-year gate do not block this reviewed path.
Actual event/recovery boundaries and unverifiable source/protection data retain
specific explanations, with event clearing available in the same restart review.

Only the private restart path supports future-only initial ownership or an exact
retained-subset revision of an unowned older plan. Normal preview/removal/approval
initial/future ownership, provenance and approval safeguards stay in place. Linked
future proposals now ignore historical overlaps they do not modify, so later
event/settings edits remain usable after a restart. No schema migration is needed. The full
contract is in [yearly-plan-restart.md](../../docs/yearly-plan-restart.md).

## Validation

**341 distinct checks passed: 337 service/data/UI cases and four browser scenarios.**
Reruns are not added to that count.

The shared regression run passed 219 scheduling, regeneration, legacy-removal,
baseline and workflow checks. The service/UI-data gate passed 63 checks. Canonical
persistence and match checks passed 53 cases. The corrected load gate passed 75
cases, including all restart service cases and baseline contracts. A final 96-case
restart/generation run also verified that subsequent event edits work with retained
historical rows. Repeated cases
are not added to the distinct total. Desktop/phone and current-year browser
scenarios passed three cases; the Maffetone/event-clearing browser case also passed.

The tests cover future-only and already-owned restarts, the screenshot's historical
legacy overlap, exact original history, optional locks, completed metadata and
matches, old unowned structured-plan retained subsets/archive, other years,
concurrent/duplicate acceptance, tampered and stale proposals, local-day changes,
rollback at each transaction stage, real recovery boundaries, cancelled-event
intent and native Maffetone targets.

Browser tests use synthetic isolated databases. They exercise desktop/390px Plan
button discovery, restart options, dismissal, one acceptance, retained-original
history, reload, the current-year conflict screen, and clearing upcoming events.
Screenshots were inspected and captures assert no page-width overflow. Compilation
and git diff whitespace checks passed.

Initial failures/corrections are retained in attempts/: explicit checkbox labels
were added for accessibility, date/activity fixtures were corrected, future-only
restarts stopped treating omitted history as zero training, and progression no
longer consumes its recovery-return state on withheld weeks. Tests now explicitly
require actual running workouts rather than only checking calendar entry counts.
A repository test invocation named a nonexistent optional origin test; the actual
persistence/match files were subsequently run successfully.

## Evidence and running from source

Evidence directories contain button, options, review and accepted-plan screenshots
for desktop/phone and the current-year reproduction. The source app uses the user's
existing command:

    .\.venv\Scripts\python.exe -m garmin_data_hub.ui_nicegui.app --port 8091

Stop the current process and rerun it to load the changed page definitions. No
installer build is required. Changes remain uncommitted; no live user database,
schedule, installer, commit, push or deployment was changed by this implementation.
Only isolated test databases were written. Real-history field use remains to be
checked by the user from their source launcher.
