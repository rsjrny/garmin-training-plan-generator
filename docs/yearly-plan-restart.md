# Redo this year

Plan and yearly settings expose Redo this year directly. Choose the selected year's
future restart date, review one fresh plan, then accept Apply yearly restart.
The default is tomorrow or the year's start, whichever is later. Today's workouts,
past history, completed workouts and activity matches stay in place.

The same review retires eligible older legacy rows, replaces the selected year's
eligible canonical workouts and supersedes overlapping unowned older structured
plans. A single checkbox includes unfinished locked/manual workouts; another
cancels upcoming events and rebuilds race-free training. Current yearly settings,
methodology and baseline distance goal are retained. Cancel/dismiss does not save
an event cancellation, retire a workout or change an active revision.

Native originals remain immutable, with original match/origin identities for
carried sessions. Legacy originals remain in the removal-history ledger. Unowned
structured plans receive an exact retained-subset revision, or an audited empty
active pointer when no eligible membership remains. Other-year ownership is never
superseded. Calendar/recovery boundaries remain real constraints; obsolete
ownership overlaps and initial-past-year restrictions are handled by the restart.

Completed or otherwise retained workouts from older/other schedules reserve their
whole local week from new training because their load is unverified. Those weeks
are unavailable evidence, not zero training. An initial midyear plan skips omitted
historical weeks and uses the entered starting load; its first partial week is
clipped without compression. Protected native sessions retain their exact original
prescriptions and phases.

One write transaction rechecks the frozen intent, local date, policy, schedule,
protection, activity dates and cache; it applies legacy retirement, other-plan
retained revisions/archive, optional future-event cancellation, the new yearly
revision, origins, nutrition invalidation and immutable application audit together.
Failure rolls back all parts. Duplicate acceptance is idempotent; stale or altered
reviews require a new preview. Existing normal preview/removal safeguards remain
in place. Linked future proposals ignore historical overlaps they do not modify,
so retained past rows do not block the next event/settings edit. No database schema
migration is needed.

Verification and desktop/phone evidence: [restart report](../reports/yearly_reset/README.md).
