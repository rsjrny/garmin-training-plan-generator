"""Y5a acceptance safety on isolated databases, independent of UI caches."""
import asyncio
from dataclasses import replace
from datetime import date, datetime
import sqlite3
import threading

import pytest

from garmin_data_hub.services import season_generation as generation, season_plans as intent
from garmin_data_hub.services import yearly_workflow as workflow
from garmin_data_hub.services import season_workouts
from garmin_data_hub.services.season_schedule import GenerationSettings
from garmin_data_hub.services.plan_persistence import get_active_plan_sha256
from garmin_data_hub.plan_methodology.revision_repository import load_revision
from test_season_generation import setup_season, SETTINGS


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr(generation, "_local_today", lambda tz: date(2026, 10, 6))


def apply(db, s):
    p = generation.preview_season(db, s.season_id, SETTINGS)
    assert p.can_apply
    generation.apply_season_preview(db, p, approved_by="TEST", acknowledge_warnings=True)
    return intent.get_season(db, s.season_id), p


async def ready(manager, db, sid):
    await manager.ensure(db, sid)
    entry = manager.entries.get(manager._key(db, sid))
    if entry and entry.task:
        await entry.task
    return manager.state(db, sid)


def update(db, s, **changes):
    return intent.update_season(db, s.season_id,
        intent.SeasonDraft(s.name, s.start_date, s.end_date, s.timezone, replace(s.inputs, **changes)),
        expected_version=s.input_version)


@pytest.mark.parametrize("changes", [
    {"goal_intent": "PERFORMANCE", "target_seconds": 8000}, {"distance_code": "10M"},
    {"status": "skipped"}, {"status": "cancelled"}, {"status": "completed"},
    {"priority": "B"}, {"terrain": "Hilly"}, {"course_notes": "New course"},
    {"target_speed_mps": "3", "goal_intent": "PERFORMANCE"}, {"participation_seconds": 8000},
    {"taper_days": 12}, {"recovery_days": 10}, {"name": "Renamed"}, {"event_date": "2027-06-06"},
])
def test_every_event_input_remains_pending_even_with_same_marker(tmp_path, monkeypatch, changes):
    db, s = setup_season(tmp_path, [intent.EventDraft("Half", "2027-05-16")])
    s, p = apply(db, s)
    assert workflow.read_state(db, s.season_id).status == "current"
    e = intent.list_events(db, s.season_id)[0]
    before = get_active_plan_sha256(db)
    if changes.get("status") == "completed":
        class AfterEvent(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2027, 5, 17, tzinfo=tz)
        monkeypatch.setattr(intent, "datetime", AfterEvent)
        monkeypatch.setattr(generation, "_local_today", lambda tz: date(2027, 5, 17))
    intent.save_event(db, s.season_id, replace(e.draft, **changes), event_id=e.event_id, expected_version=s.input_version)
    state = workflow.read_state(db, s.season_id)
    assert state.status == "pending" and state.settings.lthr_confirmed
    assert get_active_plan_sha256(db) == before
    with pytest.raises(generation.StalePreviewError):
        generation.apply_season_preview(db, replace(p, preview_id="new-id"), approved_by="TEST", acknowledge_warnings=True)


@pytest.mark.parametrize("changes", [
    {"starting_duration_seconds": 12000}, {"run_days_per_week": 4},
    {"available_weekdays": (0, 1, 2, 3, 5, 6)}, {"long_run_day": "Sunday"}, {"hrmax": 190},
])
def test_yearly_settings_prepare_without_reconfirming_unchanged_threshold(tmp_path, changes):
    db, s = setup_season(tmp_path)
    s, _ = apply(db, s)
    update(db, s, **changes)
    m = workflow.ProposalCoordinator(0)
    state = asyncio.run(ready(m, db, s.season_id))
    assert state.preview is not None and state.preview.regeneration.mode == "AFFECTED"
    assert state.preview.regeneration.refresh_parameters is False
    assert state.status in {"pending", "conflict"}


def test_race_optional_initial_confirmation_dismissal_restart_and_duplicate_acceptance(tmp_path):
    db, s = setup_season(tmp_path)
    assert workflow.read_state(db, s.season_id).status == "settings_required"
    m = workflow.ProposalCoordinator(0)
    p = generation.preview_season(db, s.season_id, SETTINGS)
    m.reviewed(db, p)
    state = asyncio.run(ready(m, db, s.season_id))
    assert state.preview is p and state.status == "pending"
    assert intent.get_season(db, s.season_id).plan_id is None
    # Closing review is no mutation. A fresh process cannot claim a cache was applied.
    assert workflow.ProposalCoordinator().state(db, s.season_id).status == "settings_required"
    first = generation.apply_season_preview(db, p, approved_by="TEST", acknowledge_warnings=True)
    assert generation.apply_season_preview(db, p, approved_by="TEST", acknowledge_warnings=True).status == "duplicate"
    assert workflow.ProposalCoordinator().state(db, s.season_id).status == "current"
    assert first.revision_id == intent.get_season(db, s.season_id).current_revision_id


def test_add_edit_remove_auto_proposal_apply_only_on_acceptance(tmp_path):
    db, s = setup_season(tmp_path)
    s, _ = apply(db, s)
    m = workflow.ProposalCoordinator(0)
    for action in ("add", "edit", "remove"):
        before = get_active_plan_sha256(db)
        if action == "add":
            intent.save_event(db, s.season_id, intent.EventDraft("5K", "2027-05-16", "5K", "C", participation_seconds=1800), expected_version=s.input_version)
        else:
            e = intent.list_events(db, s.season_id)[0]
            if action == "edit":
                intent.save_event(db, s.season_id, replace(e.draft, event_date="2027-06-06"), event_id=e.event_id, expected_version=s.input_version)
            else:
                intent.remove_event(db, s.season_id, e.event_id, expected_version=s.input_version)
        state = asyncio.run(ready(m, db, s.season_id))
        assert state.status == "pending" and state.preview.can_apply, state
        assert get_active_plan_sha256(db) == before
        generation.apply_season_preview(db, state.preview, approved_by="TEST", acknowledge_warnings=True)
        s = intent.get_season(db, s.season_id)
        assert workflow.read_state(db, s.season_id).status == "current"
    assert intent.list_events(db, s.season_id)[0].draft.status == "cancelled"
    assert len(generation.list_applications(db, s.season_id)) == 4


def test_rapid_edits_coalesce_and_concurrent_clients_share_proposal(tmp_path, monkeypatch):
    db, s = setup_season(tmp_path)
    s, _ = apply(db, s)
    count = []
    original = generation.preview_season
    def tracked(*args, **kwargs):
        count.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(generation, "preview_season", tracked)
    async def scenario():
        # Hold the burst boundary explicitly: SQLite fingerprinting can outlast
        # any short wall-clock debounce on a loaded machine. Generation stays
        # real, and every superseded task must still be cancelled/coalesced.
        m = workflow.ProposalCoordinator(0)
        burst_finished = asyncio.Event()
        prepare = m._prepare
        async def after_burst(*args):
            await burst_finished.wait()
            await prepare(*args)
        monkeypatch.setattr(m,"_prepare",after_burst)
        for n in range(5):
            fresh = intent.get_season(db, s.season_id)
            e = intent.list_events(db, s.season_id)
            intent.save_event(db, s.season_id, intent.EventDraft(f"Edit {n}", "2027-05-16", "5K", "C"),
                event_id=e[0].event_id if e else None, expected_version=fresh.input_version)
            states = await asyncio.gather(m.ensure(db, s.season_id), m.ensure(db, s.season_id))
            assert all(v.status == "preparing" for v in states)
        burst_finished.set()
        result = await ready(m, db, s.season_id)
        assert result.preview.events[0].draft.name == "Edit 4"
        assert len(count) == 1
    asyncio.run(scenario())


def test_review_request_follows_superseded_work_instead_of_opening_old_proposal(tmp_path,monkeypatch):
    db,s = setup_season(tmp_path)
    s,_ = apply(db,s)
    plans = intent
    plans.save_event(db,s.season_id,plans.EventDraft("Old","2027-05-16","5K","C"),expected_version=s.input_version)
    async def scenario():
        m = workflow.ProposalCoordinator(0)
        started,release = asyncio.Event(),asyncio.Event()
        prepare = m._prepare
        calls = []
        async def gated(*args):
            calls.append(1)
            if len(calls)==1:
                started.set()
                await release.wait()
            await prepare(*args)
        monkeypatch.setattr(m,"_prepare",gated)
        waiting = asyncio.create_task(m.for_review(db,s.season_id))
        await started.wait()
        fresh = plans.get_season(db,s.season_id)
        event = plans.list_events(db,s.season_id)[0]
        plans.save_event(db,s.season_id,replace(event.draft,name="Latest"),event_id=event.event_id,expected_version=fresh.input_version)
        await m.ensure(db,s.season_id)
        release.set()
        reviewed = await waiting
        assert reviewed.preview.events[0].draft.name=="Latest"
        assert len(calls)==2
    asyncio.run(scenario())


def test_cancelled_review_request_leaves_shared_preparation_running(tmp_path,monkeypatch):
    db,s = setup_season(tmp_path)
    s,_ = apply(db,s)
    update(db,s,starting_duration_seconds=11400)
    async def scenario():
        m = workflow.ProposalCoordinator(0)
        started,release = asyncio.Event(),asyncio.Event()
        prepare = m._prepare
        async def gated(*args):
            started.set()
            await release.wait()
            await prepare(*args)
        monkeypatch.setattr(m,"_prepare",gated)
        waiting = asyncio.create_task(m.for_review(db,s.season_id))
        await started.wait()
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        entry = m.entries[m._key(db,s.season_id)]
        assert not entry.task.cancelled()
        release.set()
        reviewed = await m.for_review(db,s.season_id)
        assert reviewed.preview.can_apply
    asyncio.run(scenario())


def test_late_result_cannot_publish_after_newer_edit(tmp_path, monkeypatch):
    db, s = setup_season(tmp_path)
    s, _ = apply(db, s)
    intent.save_event(db, s.season_id, intent.EventDraft("Old", "2027-05-16", "5K", "C"), expected_version=s.input_version)
    original = generation.preview_season
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    calls = []
    def delayed(*args, **kwargs):
        p = original(*args, **kwargs)
        calls.append(p)
        if len(calls) == 1:
            started.set()
            assert release.wait(10)
            finished.set()
        return p
    monkeypatch.setattr(generation, "preview_season", delayed)
    async def scenario():
        m = workflow.ProposalCoordinator(0)
        await m.ensure(db, s.season_id)
        assert await asyncio.to_thread(started.wait, 10)
        try:
            fresh = intent.get_season(db, s.season_id)
            e = intent.list_events(db, s.season_id)[0]
            intent.save_event(db, s.season_id, replace(e.draft, name="Latest"), event_id=e.event_id, expected_version=fresh.input_version)
            result = await ready(m, db, s.season_id)
            assert result.preview.events[0].draft.name == "Latest"
            release.set()
            assert await asyncio.to_thread(finished.wait, 10)
            assert m.state(db, s.season_id).preview is result.preview
        finally:
            release.set()
    asyncio.run(scenario())


def test_reload_recreates_pending_from_snapshot_and_rejects_stale_apply(tmp_path):
    db, s = setup_season(tmp_path)
    s, _ = apply(db, s)
    update(db, s, starting_duration_seconds=12000)
    m = workflow.ProposalCoordinator(0)
    pending = asyncio.run(ready(m, db, s.season_id))
    recreated = asyncio.run(ready(workflow.ProposalCoordinator(0), db, s.season_id))
    assert recreated.status == "pending" and recreated.preview.preview_id != pending.preview.preview_id
    fresh = intent.get_season(db, s.season_id)
    update(db, fresh, starting_duration_seconds=11400)
    with pytest.raises(generation.StalePreviewError):
        generation.apply_season_preview(db, pending.preview, approved_by="TEST", acknowledge_warnings=True)
    assert workflow.read_state(db, s.season_id).status == "pending"


def test_missing_start_load_and_changed_threshold_require_settings(tmp_path):
    db, s = setup_season(tmp_path)
    s, _ = apply(db, s)
    s = update(db, s, starting_duration_seconds=None)
    assert "starting weekly minutes" in workflow.read_state(db, s.season_id).message
    s = update(db, s, starting_duration_seconds=10800, lthr=175)
    assert workflow.read_state(db, s.season_id).status == "settings_required"
    m = workflow.ProposalCoordinator(0)
    assert asyncio.run(m.ensure(db, s.season_id)).status == "settings_required"
    assert not m.entries
    from garmin_data_hub.services.season_regeneration import RegenerationRequest
    p = generation.preview_season(db, s.season_id, SETTINGS, RegenerationRequest(refresh_parameters=True))
    m.reviewed(db, p)
    assert m.state(db, s.season_id).preview is p
    generation.apply_season_preview(db, p, approved_by="TEST", acknowledge_warnings=True)
    assert workflow.read_state(db, s.season_id).status == "current"


def test_conflicts_are_visible_and_active_schedule_is_unchanged(tmp_path):
    db, s = setup_season(tmp_path)
    s, _ = apply(db, s)
    before = get_active_plan_sha256(db)
    for d in ("2027-05-16", "2027-05-17"):
        fresh = intent.get_season(db, s.season_id)
        intent.save_event(db, s.season_id, intent.EventDraft("Close half " + d, d), expected_version=fresh.input_version)
    result = asyncio.run(ready(workflow.ProposalCoordinator(0), db, s.season_id))
    assert result.status == "conflict" and not result.preview.can_apply
    assert get_active_plan_sha256(db) == before


def test_runtime_protection_and_local_date_invalidate_proposal(tmp_path, monkeypatch):
    db, s = setup_season(tmp_path)
    s, _ = apply(db, s)
    update(db, s, starting_duration_seconds=11400)
    m = workflow.ProposalCoordinator(0)
    first = asyncio.run(ready(m, db, s.season_id))
    original_wid = load_revision(db, s.current_revision_id).candidate.workouts[0].workout_id
    season_workouts.set_workout_protection(db, s.season_id, original_wid, expected_version=0, editor="TEST", reason="Keep", locked=True)
    assert m.state(db, s.season_id).preview is None
    second = asyncio.run(ready(m, db, s.season_id))
    assert second.fingerprint != first.fingerprint
    monkeypatch.setattr(generation, "_local_today", lambda tz: date(2026, 10, 7))
    assert m.state(db, s.season_id).preview is None


def test_read_state_is_read_only_and_policy_changes_are_pending(tmp_path, monkeypatch):
    db, s = setup_season(tmp_path)
    s, _ = apply(db, s)
    with sqlite3.connect(db) as conn:
        before = list(conn.iterdump())
    workflow.read_state(db, s.season_id)
    with sqlite3.connect(db) as conn:
        assert list(conn.iterdump()) == before
    monkeypatch.setattr(workflow, "POLICY_VERSION", "next-policy")
    assert workflow.read_state(db, s.season_id).status == "pending"


def test_bounds_and_name_changes_are_pending_and_reverting_inputs_is_current(tmp_path):
    db, s = setup_season(tmp_path)
    s, _ = apply(db, s)
    changed = intent.update_season(db, s.season_id, intent.SeasonDraft("Renamed", s.start_date, "2028-01-01", s.timezone, s.inputs), expected_version=s.input_version)
    assert workflow.read_state(db, s.season_id).status == "pending"
    intent.update_season(db, s.season_id, intent.SeasonDraft(s.name, s.start_date, s.end_date, s.timezone, s.inputs), expected_version=changed.input_version)
    assert workflow.read_state(db, s.season_id).status == "current"


def test_default_regeneration_flags_do_not_revoke_original_confirmation(tmp_path):
    db, s = setup_season(tmp_path)
    s, _ = apply(db, s)
    update(db, s, starting_duration_seconds=11400)
    p = generation.preview_season(db, s.season_id, GenerationSettings())
    generation.apply_season_preview(db, p, approved_by="TEST", acknowledge_warnings=True)
    assert workflow.read_state(db, s.season_id).status == "current"
    fresh = intent.get_season(db, s.season_id)
    intent.save_event(db, s.season_id, intent.EventDraft("New event", "2027-06-06", "5K", "C"), expected_version=fresh.input_version)
    result = asyncio.run(ready(workflow.ProposalCoordinator(0), db, s.season_id))
    assert result.preview is not None and result.preview.settings.lthr_confirmed


def test_automatic_acceptance_preserves_history_locks_prescriptions_matches_and_other_year(tmp_path, monkeypatch):
    from garmin_data_hub.db.sqlite import connect_sqlite
    from garmin_data_hub.plan_methodology.activity_workout_match import create_match, load_confirmed_match
    from garmin_data_hub.plan_methodology.workout_origin import prescribed_content
    from garmin_data_hub.services.season_schedule import GenerationSettings
    db, s = setup_season(tmp_path)
    s, p = apply(db, s)
    other = intent.create_season(db,intent.SeasonDraft("2028", "2028-01-01", "2028-12-31",s.timezone,s.inputs))
    q = generation.preview_season(db,other.season_id,SETTINGS)
    generation.apply_season_preview(db,q,approved_by="TEST",acknowledge_warnings=True)
    other_before = load_revision(db,q.schedule.candidate.revision_id).candidate
    parent = p.schedule.candidate
    done = next(w for w in parent.workouts if w.scheduled_date == date(2027,2,13))
    locked = next(w for w in parent.workouts if w.scheduled_date == date(2027,2,12))
    with connect_sqlite(db) as conn:
        conn.execute("INSERT INTO activity(activity_id) VALUES(999)")
        match = create_match(conn,revision_id=parent.revision_id,workout_id=done.workout_id,activity_id=999,
            status="CONFIRMED",source="MANUAL",confidence="HIGH",reviewer="TEST",reason="Reviewed")
        matches = [tuple(r) for r in conn.execute("SELECT * FROM activity_workout_match")]
    season_workouts.set_workout_protection(db,s.season_id,locked.workout_id,expected_version=0,editor="TEST",reason="Keep",locked=True)
    monkeypatch.setattr(generation,"_local_today",lambda tz:date(2027,2,10))
    s = intent.get_season(db,s.season_id)
    intent.save_event(db,s.season_id,intent.EventDraft("Future 5K","2027-05-16","5K","C"),expected_version=s.input_version)
    before = get_active_plan_sha256(db)
    result = asyncio.run(ready(workflow.ProposalCoordinator(0), db, s.season_id))
    assert result.preview.can_apply, result.preview.schedule.errors
    assert get_active_plan_sha256(db) == before
    generation.apply_season_preview(db,result.preview,approved_by="TEST",acknowledge_warnings=True)
    applied = load_revision(db,result.preview.schedule.candidate.revision_id).candidate
    old = {w.workout_id:w for w in parent.workouts}
    retained = {w.workout_id:w for w in applied.workouts}
    assert {done.workout_id,locked.workout_id} <= retained.keys()
    assert all(w.workout_id in retained for w in parent.workouts if w.scheduled_date < date(2027,2,10))
    for wid in old.keys() & retained.keys():
        assert prescribed_content(old[wid]) == prescribed_content(retained[wid])
    with connect_sqlite(db) as conn:
        assert [tuple(r) for r in conn.execute("SELECT * FROM activity_workout_match")] == matches
        loaded = load_confirmed_match(conn,revision_id=parent.revision_id,workout_id=done.workout_id)
        assert loaded == match
        assert loaded.revision_id == parent.revision_id and loaded.workout_id == done.workout_id
    assert intent.get_season(db,other.season_id).current_revision_id == q.schedule.candidate.revision_id
    assert load_revision(db,q.schedule.candidate.revision_id).candidate == other_before


def test_manual_prescription_acceptance_does_not_accept_pending_yearly_intent(tmp_path):
    from garmin_data_hub.services.season_regeneration import RegenerationRequest
    from garmin_data_hub.services.season_schedule import GenerationSettings
    db, s = setup_season(tmp_path)
    s, p = apply(db, s)
    update(db, s, starting_duration_seconds=11400)
    w = next(w for w in p.schedule.candidate.workouts if w.sport.value == "RUNNING")
    edited = replace(w,workout_id="manual-new",title="Reviewed manual session")
    preview = generation.preview_season(db,s.season_id,GenerationSettings(),
        RegenerationRequest("MANUAL_EDIT",manual_workout=edited,replaces_workout_id=w.workout_id))
    assert preview.can_apply, preview.schedule.errors
    generation.apply_season_preview(db,preview,approved_by="TEST",acknowledge_warnings=True)
    assert workflow.read_state(db,s.season_id).status == "pending"


def test_maf_adjustment_reuse_and_changed_age_require_confirmation(tmp_path):
    from garmin_data_hub.services.season_schedule import GenerationSettings
    db, s = setup_season(tmp_path, inputs=intent.SeasonInputs(training_method="maffetone",starting_duration_seconds=10800))
    maf = GenerationSettings(maf_adjustment=-5,maf_confirmed=True)
    p = generation.preview_season(db,s.season_id,maf)
    generation.apply_season_preview(db,p,approved_by="TEST",acknowledge_warnings=True)
    fresh = intent.get_season(db,s.season_id)
    update(db,fresh,starting_duration_seconds=11400)
    result = asyncio.run(ready(workflow.ProposalCoordinator(0),db,s.season_id))
    assert result.preview.settings == maf and not result.preview.regeneration.refresh_parameters
    fresh = intent.get_season(db,s.season_id)
    update(db,fresh,age=41)
    assert workflow.read_state(db,s.season_id).status == "settings_required"


@pytest.mark.parametrize("following", [False, True])
def test_initial_proposal_exposes_existing_overlap_and_cross_year_recovery(tmp_path, following):
    events = [intent.EventDraft("Year end half", "2027-12-31")] if following else []
    db, s = setup_season(tmp_path,events)
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO planned_workout(scheduled_date,workout_name) VALUES(?, 'Existing unrelated session')",
            ("2028-01-01" if following else "2027-01-01",))
    before = get_active_plan_sha256(db)
    p = generation.preview_season(db,s.season_id,SETTINGS)
    m = workflow.ProposalCoordinator(0)
    m.reviewed(db,p)
    state = m.state(db,s.season_id)
    assert state.status == "conflict" and not state.preview.can_apply
    assert any(("following workouts" if following else "Existing workouts overlap") in b for b in p.apply_blockers)
    assert get_active_plan_sha256(db) == before


def test_corrupt_accepted_snapshot_cannot_claim_current_or_prepare(tmp_path):
    db, s = setup_season(tmp_path)
    s, _ = apply(db,s)
    before = get_active_plan_sha256(db)
    with sqlite3.connect(db) as conn:
        # Deliberately damage only this synthetic fixture, bypassing the normal
        # immutable-audit trigger to exercise corrupt storage handling.
        conn.execute("DROP TRIGGER trg_season_application_no_update")
        conn.execute("UPDATE season_revision_application SET snapshot_json='{}'")
    with pytest.raises(intent.SeasonError,match="snapshot could not be verified"):
        workflow.read_state(db,s.season_id)
    assert get_active_plan_sha256(db) == before


def test_concurrent_acceptance_supersedes_remembered_unaccepted_parameters(tmp_path):
    from garmin_data_hub.services.season_regeneration import RegenerationRequest
    db, s = setup_season(tmp_path,inputs=intent.SeasonInputs(training_method="maffetone",starting_duration_seconds=10800))
    initial = generation.preview_season(db,s.season_id,GenerationSettings(maf_adjustment=-5,maf_confirmed=True))
    m = workflow.ProposalCoordinator(0)
    m.reviewed(db,initial)
    generation.apply_season_preview(db,initial,approved_by="TEST",acknowledge_warnings=True)
    # Simulate a different process accepting an explicitly confirmed parameter
    # refresh without access to this process's proposal/confirmation cache.
    newer = generation.preview_season(db,s.season_id,GenerationSettings(maf_adjustment=5,maf_confirmed=True),
        RegenerationRequest(refresh_parameters=True))
    generation.apply_season_preview(db,newer,approved_by="OTHER_PROCESS",acknowledge_warnings=True)
    state = m.state(db,s.season_id)
    assert state.status == "current" and state.settings.maf_adjustment == 5
    assert asyncio.run(m.ensure(db,s.season_id)).status == "current"
    assert not m.entries
