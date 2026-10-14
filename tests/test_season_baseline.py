"""Y5b calendar and goal policy contracts, using isolated intent and prescriptions."""
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
import json
import sqlite3

import pytest

from garmin_data_hub.services import season_plans as intent, season_generation as service
from garmin_data_hub.services.season_schedule import GenerationSettings, generate_season_schedule
from garmin_data_hub.services.season_regeneration import RegenerationRequest
from garmin_data_hub.services import yearly_workflow as workflow
from garmin_data_hub.services.season_baseline import LONG_RUN_MINUTES
from garmin_data_hub.services.season_workouts import set_workout_protection
from garmin_data_hub.services.yearly_plan_data import yearly_plan_snapshot
from garmin_data_hub.analytics.yearly_plan import prepare_yearly_timeline
from garmin_data_hub.plan_methodology.revision_repository import load_revision
from garmin_data_hub.plan_methodology.workout_origin import prescribed_content
from garmin_data_hub.plan_methodology.domain import Sport
from test_season_generation import setup_season, SETTINGS, TODAY
from test_season_plans import snapshot


def pure(start="2027-01-01", end="2027-12-31", goal=None, method="eighty_twenty", run_days=5, duration=10800, events=()):
    s = intent.Season("season", "Year", start, end, "America/New_York", "draft",
        intent.SeasonInputs(training_method=method, run_days_per_week=run_days,
            starting_duration_seconds=duration, lthr=170, baseline_distance_code=goal), 1, None, None)
    es = tuple(intent.SeasonEvent(str(i), s.season_id, e, intent.DISTANCES[e.distance_code]) for i,e in enumerate(events))
    settings = SETTINGS if method == "eighty_twenty" else GenerationSettings(maf_adjustment=0, maf_confirmed=True)
    return s, generate_season_schedule(s,es,settings,today=TODAY,plan_id="plan",revision_id="revision")


@pytest.mark.parametrize("start,end,count", [("2027-01-01","2027-12-31",365),
    ("2028-01-01","2028-12-31",366),("2027-04-14","2027-07-03",81),
    ("2027-12-01","2028-02-20",82)])
def test_calendar_cycles_are_clipped_deterministic_and_bounded(start,end,count):
    s,p = pure(start,end)
    assert not p.errors, p.errors
    assert len(p.candidate.workouts) == count
    assert {c.phase for c in p.controls} == {"BASE","BUILD","RECOVERY"}
    anchor = date.fromisoformat(start)-timedelta(days=date.fromisoformat(start).weekday())
    by_date = {c.day:c for c in p.controls}
    for offset,phase in [(0,"BASE"),(20,"BASE"),(21,"BUILD"),(48,"BUILD"),(49,"RECOVERY"),(55,"RECOVERY"),(56,"BASE")]:
        day=anchor+timedelta(days=offset)
        if date.fromisoformat(start) <= day <= date.fromisoformat(end):
            assert by_date[day].phase == phase
    assert max(w.envelope_seconds for w in p.weeks) <= 10800*125//100
    assert all(w.training_seconds <= w.envelope_seconds for w in p.weeks)
    assert all(w.metadata["phase_source"] == "BASELINE_CYCLE" for w in p.candidate.workouts)
    assert all(w.metadata["baseline_cycle"]["anchor"] == anchor.isoformat() for w in p.candidate.workouts)
    assert p.candidate.content_hash == pure(start,end)[1].candidate.content_hash
    assert any(w.metadata["cutback"] and w.phase != "RECOVERY" for w in p.candidate.workouts)
    assert not any(w.quality_flag for w in p.candidate.workouts if w.phase == "RECOVERY")


@pytest.mark.parametrize("goal", [None,*LONG_RUN_MINUTES])
@pytest.mark.parametrize("method", ["eighty_twenty","maffetone"])
def test_goals_keep_native_method_and_no_fabricated_race_distance(goal,method):
    s,p=pure(goal=goal,method=method)
    assert not p.errors, p.errors
    assert not any(w.event_flag for w in p.candidate.workouts)
    assert all(seg.distance_metres is None for w in p.candidate.workouts for seg in w.segments)
    if goal:
        assert p.candidate.goal_snapshot["baseline_goal"]["distance_metres"] == intent.DISTANCES[goal]
        assert all(sum(seg.duration_seconds or 0 for seg in w.segments) <= LONG_RUN_MINUTES[goal]*60
            for w in p.candidate.workouts if w.long_run_flag)
    if method == "maffetone":
        assert not any(w.quality_flag for w in p.candidate.workouts)
        assert all(seg.prescription.primary.upper == 140 for w in p.candidate.workouts
            if w.sport is Sport.RUNNING for seg in w.segments)


def test_goal_changes_long_run_structure_without_load_jump():
    _,general=pure()
    _,half=pure(goal="HM")
    by_date={w.scheduled_date:w for w in general.candidate.workouts}
    longer=[]
    for w in half.candidate.workouts:
        if w.long_run_flag and w.phase == "BUILD":
            a=sum(s.duration_seconds or 0 for s in by_date[w.scheduled_date].segments)
            b=sum(s.duration_seconds or 0 for s in w.segments)
            assert b <= a*110//100
            longer.append(b > a)
    assert any(longer)


def test_insufficient_load_days_and_short_calendar_are_explained():
    _,p=pure(end="2027-01-14",goal="HM",run_days=2,duration=3600)
    assert {"BASELINE_GOAL_CONSTRAINED","BASELINE_BUILD_UNAVAILABLE"} <= {i.code for i in p.warnings}
    assert not p.errors
    _,missing=pure(goal="HM",duration=None)
    assert "STARTING_LOAD_REQUIRED" in {i.code for i in missing.errors}


def test_event_peak_transition_and_baseline_recovery_are_distinct():
    _,p=pure(goal="HM",events=(intent.EventDraft("Half","2027-05-16"),))
    assert not p.errors, p.errors
    controls={c.day.isoformat():c for c in p.controls}
    for day,phase in [("2027-04-28","EVENT_SPECIFIC"),("2027-04-29","PEAK"),("2027-05-05","PEAK"),
        ("2027-05-06","TAPER"),("2027-05-16","EVENT"),("2027-05-23","RECOVERY"),
        ("2027-05-24","TRANSITION"),("2027-05-30","TRANSITION")]:
        assert controls[day].phase==phase
    assert controls["2027-05-17"].load_fraction==0
    assert controls["2027-05-24"].load_fraction==Decimal("0.5")
    assert controls["2027-05-31"].phase_source=="BASELINE_CYCLE"
    assert not any(w.quality_flag for w in p.candidate.workouts if w.phase in {"PEAK","TRANSITION","RECOVERY","TAPER"})
    assert any(c.phase=="RECOVERY" and c.phase_source=="BASELINE_CYCLE" and c.load_fraction==Decimal("0.6") for c in p.controls)


def test_b_peak_c_no_peak_and_recovery_precedence():
    _,b=pure(events=(intent.EventDraft("B","2027-05-16","HM","B"),))
    assert sum(c.phase=="PEAK" for c in b.controls)==3
    _,c=pure(events=(intent.EventDraft("C","2027-05-16","5K","C"),))
    assert not any(x.phase=="PEAK" for x in c.controls)
    _,close=pure(events=(intent.EventDraft("A","2027-05-16"),intent.EventDraft("C","2027-05-20","5K","C")))
    assert "EVENT_IN_RECOVERY" not in {i.code for i in close.errors}
    assert next(x for x in close.controls if x.day==date(2027,5,19)).phase_source=="EVENT_RECOVERY"


def test_carry_in_and_overflow_do_not_claim_previous_year_ownership():
    _,p=pure(events=(intent.EventDraft("January","2027-01-03","MAR"),intent.EventDraft("December","2027-12-26","HM")))
    assert {"INSUFFICIENT_PREPARATION","RECOVERY_OVERFLOW"} <= {i.code for i in p.warnings}
    assert p.windows[0].preparation_start < date(2027,1,1)
    assert all(date(2027,1,1) <= w.scheduled_date <= date(2027,12,31) for w in p.candidate.workouts)


@pytest.fixture
def clock(monkeypatch):
    monkeypatch.setattr(service,"_local_today",lambda tz:TODAY)


def accept(db,p):
    assert p.can_apply, p.schedule.errors
    return service.apply_season_preview(db,p,approved_by="y5b-test",acknowledge_warnings=True)


def test_old_inputs_default_none_and_goal_round_trip(clock,tmp_path):
    db,s=setup_season(tmp_path)
    with sqlite3.connect(db) as conn:
        value=json.loads(conn.execute("SELECT inputs_json FROM season_plan").fetchone()[0])
        value.pop("baseline_distance_code")
        conn.execute("UPDATE season_plan SET inputs_json=?",(json.dumps(value),))
    s=intent.get_season(db,s.season_id)
    assert s.inputs.baseline_distance_code is None
    for code in ("10M","HM",None):
        s=intent.update_season(db,s.season_id,intent.SeasonDraft(s.name,s.start_date,s.end_date,s.timezone,
            replace(s.inputs,baseline_distance_code=code)),expected_version=s.input_version)
        assert intent.get_season(db,s.season_id).inputs.baseline_distance_code==code
    before=snapshot(db)
    for invalid in ("timed:8h",16093,True,{},"10m"):
        with pytest.raises(intent.SeasonError):
            intent.update_season(db,s.season_id,intent.SeasonDraft(s.name,s.start_date,s.end_date,s.timezone,
                replace(s.inputs,baseline_distance_code=invalid)),expected_version=s.input_version)
        assert snapshot(db)==before


def test_goal_pending_stale_apply_protected_origins_and_applied_dashboard(clock,tmp_path,monkeypatch):
    db,s=setup_season(tmp_path)
    initial=service.preview_season(db,s.season_id,SETTINGS)
    accept(db,initial)
    parent=initial.schedule.candidate
    s=intent.get_season(db,s.season_id)
    monkeypatch.setattr(service,"_local_today",lambda tz:date(2027,2,10))
    lock=next(w for w in parent.workouts if w.scheduled_date==date(2027,3,6))
    set_workout_protection(db,s.season_id,lock.workout_id,expected_version=0,locked=True,editor="t",reason="retain")
    old_hash=load_revision(db,parent.revision_id).content_hash
    s=intent.update_season(db,s.season_id,intent.SeasonDraft(s.name,s.start_date,s.end_date,s.timezone,
        replace(s.inputs,baseline_distance_code="HM")),expected_version=s.input_version)
    assert workflow.read_state(db,s.season_id).status=="pending"
    pending=service.preview_season(db,s.season_id,SETTINGS)
    assert next(w for w in pending.schedule.candidate.workouts if w.workout_id==lock.workout_id).phase==lock.phase
    selection=yearly_plan_snapshot(db)["selections"][0]
    assert selection["baseline_goal"]["distance_code"] is None
    accept(db,pending)
    assert workflow.read_state(db,s.season_id).status=="current"
    assert load_revision(db,parent.revision_id).content_hash==old_hash
    selection=yearly_plan_snapshot(db)["selections"][0]
    assert selection["baseline_goal"]["distance_code"]=="HM"
    preserved=next(w for w in selection["workouts"] if w["id"]==lock.workout_id)
    assert preserved["baseline_goal"]["distance_code"] is None
    assert preserved["phase_source"]=="BASELINE_CYCLE"
    s=intent.get_season(db,s.season_id)
    s=intent.update_season(db,s.season_id,intent.SeasonDraft(s.name,s.start_date,s.end_date,s.timezone,
        replace(s.inputs,baseline_distance_code=None)),expected_version=s.input_version)
    fresh=service.preview_season(db,s.season_id,SETTINGS)
    s=intent.update_season(db,s.season_id,intent.SeasonDraft(s.name,s.start_date,s.end_date,s.timezone,
        replace(s.inputs,baseline_distance_code="10M")),expected_version=s.input_version)
    with pytest.raises(intent.SeasonError):
        service.apply_season_preview(db,fresh,approved_by="t",acknowledge_warnings=True)
    s=intent.update_season(db,s.season_id,intent.SeasonDraft(s.name,s.start_date,s.end_date,s.timezone,
        replace(s.inputs,baseline_distance_code=None)),expected_version=s.input_version)
    cleared=service.preview_season(db,s.season_id,SETTINGS)
    accept(db,cleared)
    assert load_revision(db,cleared.schedule.candidate.revision_id).candidate.goal_snapshot["baseline_goal"]["distance_code"] is None
    assert all(prescribed_content(w)==prescribed_content(next(x for x in parent.workouts if x.workout_id==w.workout_id))
        for w in cleared.schedule.candidate.workouts if w.scheduled_date < date(2027,2,10))


def test_add_move_remove_events_matches_full_future_reconnection(clock,tmp_path):
    db,s=setup_season(tmp_path,inputs=intent.SeasonInputs(starting_duration_seconds=10800,lthr=170,baseline_distance_code="10M"))
    accept(db,service.preview_season(db,s.season_id,SETTINGS))
    s=intent.get_season(db,s.season_id)
    a=intent.save_event(db,s.season_id,intent.EventDraft("A","2027-05-16"),expected_version=s.input_version)
    s=intent.get_season(db,s.season_id)
    b=intent.save_event(db,s.season_id,intent.EventDraft("B","2027-04-18","5K","B"),expected_version=s.input_version)
    for operation in ("add","move","remove_b","remove_all"):
        s=intent.get_season(db,s.season_id)
        if operation=="move":
            intent.save_event(db,s.season_id,replace(a.draft,event_date="2027-06-06"),event_id=a.event_id,expected_version=s.input_version)
        elif operation=="remove_b":
            intent.remove_event(db,s.season_id,b.event_id,expected_version=s.input_version)
        elif operation=="remove_all":
            intent.remove_event(db,s.season_id,a.event_id,expected_version=s.input_version)
        before=snapshot(db)
        affected=service.preview_season(db,s.season_id,SETTINGS)
        full=service.preview_season(db,s.season_id,SETTINGS,RegenerationRequest("FROM_TODAY"))
        assert snapshot(db)==before
        def prescriptions(p):
            return [prescribed_content(replace(w,workout_id="same")) for w in p.schedule.candidate.workouts]
        assert prescriptions(affected)==prescriptions(full)
        current=intent.get_season(db,s.season_id)
        fresh=generate_season_schedule(current,intent.list_events(db,s.season_id),SETTINGS,today=TODAY,
            plan_id=current.plan_id,revision_id="independent")
        assert [prescribed_content(replace(w,workout_id="same")) for w in fresh.candidate.workouts] == prescriptions(affected)
        assert affected.schedule.candidate.change_summary["range_end"]=="2027-12-31"
        accept(db,affected)
    final=affected.schedule.candidate
    assert {w.phase for w in final.workouts}=={"BASE","BUILD","RECOVERY"}
    assert not any(w.event_flag for w in final.workouts)
    assert final.goal_snapshot["baseline_goal"]["distance_code"]=="10M"


def test_old_policy_and_short_custom_range_require_full_review(clock,tmp_path):
    db,s=setup_season(tmp_path)
    p=service.preview_season(db,s.season_id,SETTINGS)
    accept(db,p)
    old=replace(p.schedule.candidate,provenance={"generator":"season-generator.v2","policy":"season-windows-load.v2"})
    from garmin_data_hub.services.season_regeneration import affected_range
    selected,recommended,reasons,_=affected_range(s,(),old,TODAY,RegenerationRequest(),SETTINGS)
    assert selected==(date(2027,1,1),date(2027,12,31))
    assert any("policy changed" in r for r in reasons)
    s=intent.get_season(db,s.season_id)
    intent.save_event(db,s.season_id,intent.EventDraft("A","2027-05-16"),expected_version=s.input_version)
    custom=service.preview_season(db,s.season_id,SETTINGS,RegenerationRequest("CUSTOM","2027-02-01","2027-06-30"))
    assert not custom.can_apply
    assert "CONTINUOUS_RANGE_REQUIRED" in {i.code for i in custom.schedule.errors}


@pytest.mark.parametrize("cycle", [None, "invalid", {}, {"schema_version":"baseline-cycle.v1","anchor":"bad","index":0,"start":"bad","end":"bad"},
    {"schema_version":"baseline-cycle.v1","anchor":"2026-12-28","index":True,"start":"2026-12-28","end":"2027-02-21"}])
def test_malformed_cycle_metadata_stays_unavailable(cycle):
    from garmin_data_hub.analytics.yearly_plan import _cycle_context
    assert _cycle_context([{"baseline_cycle":cycle}])==()


def test_timeline_uses_actual_preserved_phases_and_cycle_boundaries(clock,tmp_path):
    db,s=setup_season(tmp_path)
    p=service.preview_season(db,s.season_id,SETTINGS)
    accept(db,p)
    before=snapshot(db)
    facts=yearly_plan_snapshot(db)
    data=prepare_yearly_timeline(facts,2027,"season:"+s.season_id,today=TODAY)
    assert snapshot(db)==before
    blocks=data["blocks"]
    assert {b["phase"] for b in blocks}=={"BASE","BUILD","RECOVERY"}
    assert next(b for b in blocks if b["start"]=="2027-01-18")["end"]=="2027-02-14"
    assert next(b for b in blocks if b["start"]=="2027-02-15")["end"]=="2027-02-21"
    assert all(b["sources"]==("BASELINE_CYCLE",) for b in blocks)
    assert all(b["cycles"] for b in blocks)


def test_bounded_taper_budget_does_not_force_supporting_completion():
    _,too_long=pure(events=(intent.EventDraft("A","2027-10-17","MAR"),
        intent.EventDraft("B","2027-10-10","5K","B",participation_seconds=600)))
    assert "EVENT_EXCEEDS_A_TAPER" in {i.code for i in too_long.errors}
    _,fits=pure(events=(intent.EventDraft("A","2027-10-17","MAR"),
        intent.EventDraft("B","2027-10-10","5K","B",participation_seconds=480)))
    assert not fits.errors, fits.errors
    assert "EASY_EVENT_IN_A_TAPER" in {i.code for i in fits.warnings}


@pytest.mark.parametrize("code", [{},[],True,123,"unknown"])
def test_unknown_goal_label_is_unavailable(code):
    from garmin_data_hub.services.season_baseline import goal_label
    assert goal_label(code)=="Unavailable"


def test_stored_v2_policy_upgrade_preserves_immutable_history_and_labels(clock,tmp_path,monkeypatch):
    from garmin_data_hub.plan_methodology.canonical import canonical_value
    from test_plan_revision_persistence import _approve
    db,s=setup_season(tmp_path)
    p=service.preview_season(db,s.season_id,SETTINGS)
    constraints=canonical_value(p.schedule.candidate.constraints)
    constraints["inputs"].pop("baseline_distance_code")
    constraints.pop("baseline_policy")
    constraints.pop("phase_evidence")
    goal=canonical_value(p.schedule.candidate.goal_snapshot)
    goal.pop("baseline_goal")
    workouts=[]
    for w in p.schedule.candidate.workouts:
        meta=canonical_value(w.metadata)
        for field in ("phase_source","phase_reason","baseline_cycle","baseline_goal"):
            meta.pop(field)
        meta.update(generator_version="season-generator.v2",policy_version="season-windows-load.v2")
        workouts.append(replace(w,phase="MAINTENANCE",metadata=meta))
    old=replace(p.schedule.candidate,workouts=tuple(workouts),constraints=constraints,goal_snapshot=goal,
        provenance={"generator":"season-generator.v2","policy":"season-windows-load.v2"})
    _approve(db,old)
    # Restore the ownership already present in an older yearly database fixture.
    # The separate adoption UI only accepts all-running single-event plans.
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE season_plan SET plan_id=?,status='active' WHERE season_id=?",(old.plan_id,s.season_id))
    monkeypatch.setattr(service,"_local_today",lambda tz:date(2027,2,10))
    fresh=service.preview_season(db,s.season_id,SETTINGS)
    assert fresh.schedule.candidate.change_summary["range_start"]=="2027-02-10"
    assert fresh.schedule.candidate.change_summary["range_end"]=="2027-12-31"
    assert any("policy changed" in r for r in fresh.schedule.candidate.change_summary["range_reasons"])
    accept(db,fresh)
    assert load_revision(db,old.revision_id).content_hash==old.content_hash
    facts=yearly_plan_snapshot(db)["selections"][0]
    assert all(w["phase"]=="MAINTENANCE" and w["phase_source"] is None for w in facts["workouts"] if w["date"]<"2027-02-10")
    assert any(w["phase"]=="BUILD" and w["phase_source"]=="BASELINE_CYCLE" for w in facts["workouts"] if w["date"]>="2027-02-10")
