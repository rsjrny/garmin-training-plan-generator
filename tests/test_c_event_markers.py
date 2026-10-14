"""C markers never prescribe, replace, restrict or add training load."""
from dataclasses import replace
from datetime import date
import sqlite3
import json

import pytest

from garmin_data_hub.services import season_plans as intent, season_generation as generation
from garmin_data_hub.services.season_schedule import GenerationSettings
from garmin_data_hub.services.season_regeneration import RegenerationRequest
from garmin_data_hub.services.yearly_plan_data import yearly_plan_snapshot
from garmin_data_hub.analytics.yearly_plan import prepare_yearly_timeline
from garmin_data_hub.plan_methodology.revision_repository import load_revision
from garmin_data_hub.plan_methodology.workout_origin import prescribed_content
from test_season_baseline import pure
from test_season_generation import setup_season, SETTINGS, TODAY
from test_season_regeneration import apply
from test_season_plans import snapshot


@pytest.mark.parametrize("method", ["eighty_twenty", "maffetone"])
@pytest.mark.parametrize("day", ["2027-01-01", "2027-02-20", "2027-05-16", "2027-10-10", "2027-10-17", "2027-10-20", "2027-12-31"])
@pytest.mark.parametrize("goal", [None, "HM"])
def test_marker_is_identical_to_no_event_in_every_phase(method, day, goal):
    a = intent.EventDraft("Primary marathon", "2027-10-17", "MAR")
    _, before = pure(goal=goal, method=method, events=(a,))
    marker = intent.EventDraft("5K marker", day, "5K", "C", taper_days=28, recovery_days=42)
    _, after = pure(goal=goal, method=method, events=(a, marker))
    assert not before.errors and not after.errors
    assert after.candidate.workouts == before.candidate.workouts
    assert after.controls == before.controls
    assert after.weeks == before.weeks
    assert after.windows == before.windows
    assert after.issues == before.issues
    assert after.candidate.goal_snapshot["baseline_goal"] == before.candidate.goal_snapshot["baseline_goal"]
    assert len(after.candidate.goal_snapshot["events"]) == 2


@pytest.mark.parametrize("changes", [
    {}, {"participation_seconds": 604800}, {"distance_code": "100M"},
    {"goal_intent": "PERFORMANCE", "target_seconds": 600},
    {"status": "cancelled"}, {"status": "skipped"},
])
def test_marker_details_do_not_change_workout_targets_or_load(changes):
    marker = replace(intent.EventDraft("Marker", "2027-02-20", "5K", "C"), **changes)
    _, before = pure(goal="HM")
    _, after = pure(goal="HM", events=(marker,))
    assert after.candidate.workouts == before.candidate.workouts
    assert after.weeks == before.weeks
    assert not any(w.event_flag for w in after.candidate.workouts)


def test_two_same_day_markers_are_allowed_without_creating_sessions():
    _, before = pure()
    _, after = pure(events=(intent.EventDraft("One", "2027-05-16", "5K", "C"),
        intent.EventDraft("Two", "2027-05-16", "10K", "C")))
    assert not after.errors
    assert after.candidate.workouts == before.candidate.workouts


def test_completed_marker_never_adds_recovery():
    _, before = pure(start="2020-01-01", end="2020-12-31")
    _, after = pure(start="2020-01-01", end="2020-12-31", events=(
        intent.EventDraft("Completed 5K", "2020-02-20", "5K", "C", status="completed"),))
    assert after.candidate.workouts == before.candidate.workouts
    assert after.controls == before.controls


@pytest.fixture
def clock(monkeypatch):
    monkeypatch.setattr(generation, "_local_today", lambda _: TODAY)


@pytest.mark.parametrize("method", ["eighty_twenty", "maffetone"])
def test_marker_crud_keeps_every_identity_origin_and_prescription(tmp_path, clock, method):
    db, season = setup_season(tmp_path, inputs=intent.SeasonInputs(training_method=method,
        starting_duration_seconds=10800, lthr=170, baseline_distance_code="HM"))
    settings = SETTINGS if method == "eighty_twenty" else GenerationSettings(maf_adjustment=0, maf_confirmed=True)
    initial = generation.preview_season(db, season.season_id, settings)
    apply(db, initial)
    original = load_revision(db, initial.schedule.candidate.revision_id)
    before_graph = prepare_yearly_timeline(yearly_plan_snapshot(db), 2027)
    current = intent.get_season(db, season.season_id)
    marker = intent.save_event(db, season.season_id, intent.EventDraft("5K inside long run", "2027-02-20", "5K", "C"), expected_version=current.input_version)
    for action in ("add", "move", "remove"):
        if action == "move":
            current = intent.get_season(db, season.season_id)
            marker = intent.save_event(db, season.season_id, replace(marker.draft, event_date="2027-02-21", distance_code="10K"),
                event_id=marker.event_id, expected_version=current.input_version)
        elif action == "remove":
            current = intent.get_season(db, season.season_id)
            intent.remove_event(db, season.season_id, marker.event_id, expected_version=current.input_version)
        before = snapshot(db)
        preview = generation.preview_season(db, season.season_id, settings)
        assert snapshot(db) == before
        assert preview.can_apply, preview.schedule.errors
        diff = preview.schedule.candidate.change_summary
        assert diff["marker_only"]
        assert not diff["changed"] and not diff["added_workout_ids"] and not diff["removed_workout_ids"]
        assert preview.schedule.candidate.workouts == original.candidate.workouts
        assert all(o["origin_revision_id"] == original.candidate.revision_id for o in diff["origins"])
        apply(db, preview)
        assert apply(db, preview).status == "duplicate"
        graph = prepare_yearly_timeline(yearly_plan_snapshot(db), 2027)
        # Preservation changes display context, never the phase/duration/distance.
        assert [(b["start"], b["end"], b["phase"], b["duration_s"], b["distance_m"]) for b in graph["blocks"]] == [
            (b["start"], b["end"], b["phase"], b["duration_s"], b["distance_m"]) for b in before_graph["blocks"]]
        markers = [e for e in graph["events"] if e["priority"] == "C"]
        assert len(markers) == (0 if action == "remove" else 1)
        if markers:
            assert markers[0]["marker_only"] and markers[0]["source"] == "Applied calendar marker"
            assert markers[0]["date"] == marker.draft.event_date
        assert load_revision(db, original.candidate.revision_id).content_hash == original.content_hash


def test_marker_on_protected_ten_mile_workout_preserves_exact_session(tmp_path, clock):
    db, season = setup_season(tmp_path, inputs=intent.SeasonInputs(starting_duration_seconds=18000,
        lthr=170, baseline_distance_code="HM"))
    initial = generation.preview_season(db, season.season_id, SETTINGS)
    apply(db, initial)
    parent = initial.schedule.candidate
    # Make an explicit ten-mile occurrence through the normal manual-edit path.
    original = next(w for w in parent.workouts if w.scheduled_date == date(2027,2,20))
    from garmin_data_hub.plan_methodology.domain import MeasureRole
    edited = replace(original, workout_id="ten-mile-run", title="10 mile long run", segments=tuple(
        replace(s, distance_metres=16093-2000*(len(original.segments)-1) if i == 0 else 2000,
            distance_role=MeasureRole.ESTIMATED) for i, s in enumerate(original.segments)))
    manual = generation.preview_season(db, season.season_id, SETTINGS,
        RegenerationRequest("MANUAL_EDIT", manual_workout=edited, replaces_workout_id=original.workout_id))
    assert manual.can_apply, manual.schedule.errors
    apply(db, manual)
    current = intent.get_season(db, season.season_id)
    from garmin_data_hub.services.season_workouts import set_workout_protection
    set_workout_protection(db, current.season_id, edited.workout_id, expected_version=1,
        editor="r", reason="Keep long run", locked=True)
    intent.save_event(db, current.season_id, intent.EventDraft("Local 5K", "2027-02-20", "5K", "C"), expected_version=current.input_version)
    preview = generation.preview_season(db, current.season_id, SETTINGS)
    assert preview.can_apply, preview.schedule.errors
    assert preview.schedule.candidate.change_summary["marker_only"]
    retained = next(w for w in preview.schedule.candidate.workouts if w.workout_id == edited.workout_id)
    assert prescribed_content(retained) == prescribed_content(edited)
    assert sum(s.distance_metres for s in retained.segments) == 16093
    assert not retained.event_flag
    apply(db, preview)


def test_priority_change_to_b_still_regenerates_training(tmp_path, clock):
    db, season = setup_season(tmp_path, [intent.EventDraft("Marker", "2027-05-16", "5K", "C")])
    initial = generation.preview_season(db, season.season_id, SETTINGS)
    apply(db, initial)
    event = intent.list_events(db, season.season_id)[0]
    current = intent.get_season(db, season.season_id)
    intent.save_event(db, season.season_id, replace(event.draft, priority="B"),
        event_id=event.event_id, expected_version=current.input_version)
    preview = generation.preview_season(db, season.season_id, SETTINGS)
    assert preview.can_apply, preview.schedule.errors
    assert not preview.schedule.candidate.change_summary.get("marker_only")
    assert any(w.event_flag and w.scheduled_date == date(2027,5,16) for w in preview.schedule.candidate.workouts)
    assert preview.schedule.candidate.change_summary["changed"]


def test_marker_apply_keeps_nutrition_and_checks_stale_and_tampered_review(tmp_path, clock):
    db, season = setup_season(tmp_path)
    initial = generation.preview_season(db, season.season_id, SETTINGS)
    apply(db, initial)
    cache = json.dumps(dict(day_plans=[dict(iso_date="2027-02-20", nutrition=dict(carbs=300))]))
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT OR REPLACE INTO app_settings(key,value) VALUES('last_generated_plan',?)", (cache,))
    current = intent.get_season(db, season.season_id)
    marker = intent.save_event(db, season.season_id, intent.EventDraft("Marker", "2027-02-20", "5K", "C"), expected_version=current.input_version)
    stale = generation.preview_season(db, season.season_id, SETTINGS)
    current = intent.get_season(db, season.season_id)
    intent.save_event(db, season.season_id, replace(marker.draft, name="Updated marker"),
        event_id=marker.event_id, expected_version=current.input_version)
    before = snapshot(db)
    with pytest.raises(generation.StalePreviewError):
        apply(db, stale)
    assert snapshot(db) == before
    valid = generation.preview_season(db, season.season_id, SETTINGS)
    candidate = valid.schedule.candidate
    tampered = replace(valid, schedule=replace(valid.schedule, candidate=replace(candidate,
        workouts=(replace(candidate.workouts[0], title="Changed without review"),) + candidate.workouts[1:])))
    with pytest.raises(generation.StalePreviewError):
        apply(db, tampered)
    assert snapshot(db) == before
    apply(db, valid)
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT value FROM app_settings WHERE key='last_generated_plan'").fetchone()[0] == cache


def test_v3_c_races_upgrade_only_eligible_future_and_retain_old_origins(tmp_path, monkeypatch, clock):
    from datetime import timedelta
    from garmin_data_hub.services import season_schedule as scheduler
    from garmin_data_hub.services.season_workouts import set_workout_protection
    db, season = setup_season(tmp_path, [intent.EventDraft("Historical C", "2027-02-20", "5K", "C"),
        intent.EventDraft("Locked C", "2027-05-16", "5K", "C"), intent.EventDraft("Future C", "2027-09-05", "5K", "C")])
    normal_windows = scheduler.event_windows
    normal_validate = scheduler.validate_season_workload
    normal_generate = scheduler.generate_season_schedule
    def v3_windows(s, events):
        windows = list(normal_windows(s, events))
        for e in events:
            if e.draft.priority == "C" and e.draft.status in {"planned", "completed"}:
                day = date.fromisoformat(e.draft.event_date)
                recovery = intent.RECOVERY_DAYS[e.draft.distance_code]
                windows.append(scheduler.EventWindow(e, 0, 0, recovery, day, day, day, day + timedelta(days=recovery)))
        return tuple(sorted(windows, key=lambda w: (w.event_date, w.event.event_id)))
    def v3_validate(s, events, *args, **kwargs):
        return normal_validate(s, tuple(replace(e, draft=replace(e.draft, priority="B")) if e.draft.priority == "C" else e
            for e in events), *args, **kwargs)
    def v3_generate(*args, **kwargs):
        result = normal_generate(*args, **kwargs)
        goal = dict(result.candidate.goal_snapshot)
        goal.pop("c_event_policy")
        return replace(result, candidate=replace(result.candidate, goal_snapshot=goal))
    with monkeypatch.context() as vintage:
        vintage.setattr(scheduler, "event_windows", v3_windows)
        vintage.setattr(scheduler, "validate_season_workload", v3_validate)
        vintage.setattr(generation, "generate_season_schedule", v3_generate)
        for module in (scheduler, generation):
            vintage.setattr(module, "GENERATOR_VERSION", "season-generator.v3")
            vintage.setattr(module, "POLICY_VERSION", "season-windows-load.v3")
        old = replace(generation.preview_season(db, season.season_id, SETTINGS),
            generator_version="season-generator.v3", policy_version="season-windows-load.v3")
        assert old.can_apply, old.schedule.errors
        apply(db, old)
    parent = load_revision(db, old.schedule.candidate.revision_id)
    old_events = {w.title: w for w in parent.candidate.workouts if w.event_flag}
    assert len(old_events) == 3
    current = intent.get_season(db, season.season_id)
    set_workout_protection(db, current.season_id, old_events["Locked C"].workout_id,
        expected_version=0, editor="r", reason="Preserve old session", locked=True)
    monkeypatch.setattr(generation, "_local_today", lambda _: date(2027,3,1))
    preview = generation.preview_season(db, season.season_id, SETTINGS)
    assert preview.can_apply, preview.schedule.errors
    assert not preview.schedule.candidate.change_summary.get("marker_only")
    rows = {w.workout_id: w for w in preview.schedule.candidate.workouts}
    for name in ("Historical C", "Locked C"):
        assert prescribed_content(rows[old_events[name].workout_id]) == prescribed_content(old_events[name])
    assert old_events["Future C"].workout_id not in rows
    assert not any(w.event_flag for w in rows.values() if w.scheduled_date == date(2027,9,5))
    apply(db, preview)
    graph = prepare_yearly_timeline(yearly_plan_snapshot(db), 2027)
    markers = [e for e in graph["events"] if e.get("marker_only")]
    assert len(markers) == 1 and markers[0]["name"] == "Future C"
    assert load_revision(db, parent.candidate.revision_id).content_hash == parent.content_hash
