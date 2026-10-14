# Y5b continuous yearly training

Implemented October 13, 2026, starting from commit 83855b4 with the existing
October 7 usability work and Recovery & Readiness backlog entry preserved.

## Delivered behavior

- Race-free calendars repeat three Base weeks, four Build weeks and one Recovery
  week, anchored to the Monday containing the saved season start.
- Always ready for persists an optional completion-distance goal from the existing
  catalog, including 10 miler and half marathon. Old seasons default to None.
- Goal-based long sessions, weekly progression and recovery stay bounded by
  starting load, actual prior normal training and documented duration ceilings.
  Constraints are explained; a goal never establishes achieved readiness.
- A/B preparation has distinct Peak blocks; post-event recovery reconnects through
  seven Transition days. C events retain shared training/event replacement rules.
- Event/settings/policy changes require full future review because bounded cycle
  and weekly-load dependencies cannot yet be proved safe. Custom regeneration still
  works when those dependencies are unchanged.
- New workouts store actual phase source, cycle anchor/index/week and goal identity;
  old/preserved workouts keep their original labels, prescriptions and origins.
- Plan/settings/review describe cycles and goals. Dashboard reads the accepted goal
  and original phase/cycle provenance, with keyboard-accessible details.

The product rules were defined before implementation in
[the v3 policy](../../../docs/yearly-baseline-policy.md). Generator and load/window
policy are v3. The optional input is an additive season-input.v1 field versioned by
input_version and immutable accepted snapshots; no database migration is needed.
Existing production databases and schedules were not opened or changed.

## Verification

**346 distinct checks passed: 331 service/data/UI checks and 15 browser scenarios.**
Reruns are not added to this count. The broad scheduling run passed 213 cases with
two safe-participation fixture failures; both passed in the corrected 137-case
gate. The final 48-case baseline suite passed 47 cases, then its stored-v2 fixture
passed the focused recheck. The existing browser run passed 11 cases; its loaded
old 10-minute fixture passed the corrected 8-minute focused recheck. Three new
Y5b browser scenarios passed across their corrected runs.

All new Y5b browser scenarios have passed, including desktop and 390px layout,
setup, goal change/clear, pending reload, reviewed apply, Peak/Transition details,
MAF constraints, keyboard inspection and read-only race-free Dashboard.

The service gate covers deterministic full/partial/leap/cross-year calendars,
all existing distance identities under both methods, missing/constrained inputs,
actual-load and long-session growth, event priority/phase precedence, add/move/
remove-all reconnection compared with a separately generated complete schedule,
persistence/defaults, stale apply, protected origins and stored-v2 policy upgrade.
Python compilation and git diff whitespace checks passed.

Attempts are retained under [attempts](attempts/). Initial failures were resolved:
actual previous load now bounds goal-to-event progression; unchanged custom ranges
remain supported; empty Plan handles absent selection. The stricter v3 taper
budget blocks the old 10-minute participation fixture; an 8-minute fixture fits,
with a separate test proving the 10-minute case still blocks. Browser tests were
corrected to avoid toggling an already-checked warning acknowledgment and reopening
setup=1 while checking pending reload. A stored-v2 fixture restores existing yearly
ownership instead of invoking the separate all-running adoption UI. One initial
browser collection hit an unavailable latest_logs path; explicit test-file
collection succeeded without changing that path.

## Visual evidence

Screenshots were visually inspected; all browser captures assert no page-width
overflow and usable content width. The annual timeline and detail tables scroll
within their containers on narrow screens.

- [Goal setup desktop](evidence/test_goal_setup_change_clear_and_applied_phase_details-deb54e5604/goal_setup_desktop.png)
- [Goal setup phone](evidence/test_goal_setup_change_clear_and_applied_phase_details-deb54e5604/goal_setup_mobile.png)
- [Peak detail phone](evidence/test_goal_setup_change_clear_and_applied_phase_details-deb54e5604/peak_detail_mobile.png)
- [Transition detail desktop](evidence/test_goal_setup_change_clear_and_applied_phase_details-deb54e5604/transition_detail_desktop.png)

The race-free full-year timeline, recovery detail, MAF constraint view and existing
planning walkthrough evidence are also in evidence/ and workflow_evidence/.

Reproduction: use .venv/Scripts/python.exe -m pytest with the test-file lists
recorded in attempts/schedule2.txt and attempts/gate.txt, plus
tests/test_season_baseline.py and tests/test_season_baseline_browser.py.
The existing browser list is in attempts/workflowBrowser2.txt. Set
GARMIN_TEST_ARTIFACTS to an isolated directory to retain captures.

## Handoff and limits

Changes remain uncommitted. No live schedule apply, migration, commit, push,
deployment or package rebuild occurred. Existing usability and version changes
remain intact. This gate uses synthetic/isolated databases; real-history field
use, the installed executable and screen-reader software remain unverified.
R1 expanded/timed events, U1/U2 preferences, and physiological readiness prediction
remain separate work. Recovery & Readiness remains a backlog item.
