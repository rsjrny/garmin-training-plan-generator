from dataclasses import replace
from datetime import date
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from garmin_data_hub.services import yearly_reset as reset, season_plans as plans, season_generation as generation
from garmin_data_hub.services.season_workouts import set_workout_protection
from garmin_data_hub.services.yearly_workflow import read_state
from garmin_data_hub.plan_methodology.revision_repository import load_revision, fail_at, InjectedApprovalFailure
from garmin_data_hub.plan_methodology.workout_origin import prescribed_content
from test_season_generation import setup_season, SETTINGS
from test_season_plans import snapshot

TODAY=date(2027,6,1)
START="2027-06-02"

@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr(generation,"_local_today",lambda tz:TODAY)


def legacy(db,day="2027-06-10",metadata=None):
    with sqlite3.connect(db) as conn:
        if "start_time_gmt" not in {r[1] for r in conn.execute("PRAGMA table_info(activity)")}:
            conn.execute("ALTER TABLE activity ADD COLUMN start_time_gmt TEXT")
        return conn.execute("INSERT INTO planned_workout(scheduled_date,workout_name,planned_duration_s,structure_json) VALUES(?,'Old workout',1800,?)",
            (day,json.dumps(metadata or {}))).lastrowid


def accept(db,p,**kwargs):
    assert p.can_apply, (p.blockers,p.schedule.errors)
    return reset.apply_reset(db,p,approved_by="TEST",acknowledged=True,**kwargs)


def test_future_only_initial_restart_retires_old_rows_in_one_acceptance(tmp_path):
    db,s=setup_season(tmp_path)
    past=legacy(db,"2027-01-02")
    today=legacy(db,"2027-06-01")
    old=legacy(db)
    outside=legacy(db,"2028-01-02")
    before=snapshot(db)
    p=reset.preview_reset(db,s.season_id,SETTINGS,restart_date=START)
    assert snapshot(db)==before and p.can_apply
    assert min(w.scheduled_date for w in p.schedule.candidate.workouts)==date.fromisoformat(START)
    runs=[w for w in p.schedule.candidate.workouts if w.sport.value=="RUNNING"]
    assert runs and sum(s.duration_seconds or 0 for w in runs for s in w.segments)>0
    assert p.schedule.weeks[0].partial
    result=accept(db,p)
    assert result.status=="applied"
    assert reset.apply_reset(db,p,approved_by="TEST",acknowledged=True).status=="duplicate"
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM planned_workout WHERE planned_workout_id=?",(old,)).fetchone()[0]==1
        active={r[0] for r in conn.execute("SELECT planned_workout_id FROM active_planned_workout")}
        assert {past,today,outside} <= active and old not in active
    assert read_state(db,s.season_id).status=="current"
    assert load_revision(db,result.revision_id).content_hash==p.schedule.candidate.content_hash


def applied_year(tmp_path,monkeypatch):
    monkeypatch.setattr(generation,"_local_today",lambda tz:date(2026,10,13))
    db,s=setup_season(tmp_path)
    p=generation.preview_season(db,s.season_id,SETTINGS)
    generation.apply_season_preview(db,p,approved_by="TEST",acknowledge_warnings=True)
    monkeypatch.setattr(generation,"_local_today",lambda tz:TODAY)
    return db,plans.get_season(db,s.season_id),p.schedule.candidate


def test_owned_history_locks_and_completion_are_reviewed_together(tmp_path,monkeypatch):
    db,s,parent=applied_year(tmp_path,monkeypatch)
    locked=next(w for w in parent.workouts if w.scheduled_date==date(2027,6,10))
    done=next(w for w in parent.workouts if w.scheduled_date==date(2027,6,12))
    set_workout_protection(db,s.season_id,locked.workout_id,expected_version=0,locked=True,editor="T",reason="keep")
    set_workout_protection(db,s.season_id,done.workout_id,expected_version=0,explicitly_completed=True,editor="T",reason="done")
    old=legacy(db)
    p=reset.preview_reset(db,s.season_id,SETTINGS,restart_date=START,replace_protected=True)
    assert locked.workout_id in p.schedule.candidate.change_summary["removed_workout_ids"]
    assert done.workout_id in p.schedule.candidate.change_summary["preserved_workout_ids"]
    assert old in p.schedule.candidate.change_summary["yearly_reset"]["legacy_removed"]
    accept(db,p)
    assert load_revision(db,parent.revision_id).content_hash==parent.content_hash
    old_by_id={w.workout_id:w for w in parent.workouts}
    for w in p.schedule.candidate.workouts:
        if w.scheduled_date<date.fromisoformat(START) or w.workout_id==done.workout_id:
            assert prescribed_content(w)==prescribed_content(old_by_id[w.workout_id])


@pytest.mark.parametrize("include",[False,True])
def test_legacy_locks_are_optional_but_completed_metadata_is_retained(tmp_path,include):
    db,s=setup_season(tmp_path)
    locked=legacy(db,metadata={"locked":True})
    done=legacy(db,"2027-06-20",{"flags":["COMPLETED","MANUAL"]})
    p=reset.preview_reset(db,s.season_id,SETTINGS,restart_date=START,replace_protected=include)
    removed=p.schedule.candidate.change_summary["yearly_reset"]["legacy_removed"]
    assert (locked in removed)==include and done not in removed
    assert not any(date(2027,6,14)<=w.scheduled_date<=date(2027,6,20) for w in p.schedule.candidate.workouts)
    accept(db,p)


def test_clear_upcoming_conflicting_events_is_part_of_same_review(tmp_path):
    db,s=setup_season(tmp_path,events=(plans.EventDraft("A","2027-06-20","MAR"),plans.EventDraft("B","2027-06-21","MAR")))
    keep=reset.preview_reset(db,s.season_id,SETTINGS,restart_date=START)
    assert not keep.can_apply
    before=snapshot(db)
    clean=reset.preview_reset(db,s.season_id,SETTINGS,restart_date=START,clear_events=True)
    assert snapshot(db)==before
    assert clean.can_apply, clean.schedule.errors
    accept(db,clean)
    assert {e.draft.status for e in plans.list_events(db,s.season_id)}=={"cancelled"}
    assert not any(w.event_flag for w in clean.schedule.candidate.workouts)
    assert read_state(db,s.season_id).status=="current"


@pytest.mark.parametrize("stage",["after_reset_recheck","after_reset_legacy","after_reset_foreign","after_reset_schedule","before_reset_commit"])
def test_whole_restart_rolls_back_on_failure(tmp_path,stage):
    db,s=setup_season(tmp_path)
    legacy(db)
    p=reset.preview_reset(db,s.season_id,SETTINGS,restart_date=START)
    before=snapshot(db)
    with pytest.raises(InjectedApprovalFailure):
        accept(db,p,failure_hook=fail_at(stage))
    assert snapshot(db)==before


@pytest.mark.parametrize("change",["event","workout","activity","settings","day"])
def test_stale_review_leaves_schedule_unchanged(tmp_path,monkeypatch,change):
    db,s=setup_season(tmp_path)
    old=legacy(db)
    p=reset.preview_reset(db,s.season_id,SETTINGS,restart_date=START)
    if change=="event":
        plans.save_event(db,s.season_id,plans.EventDraft("New","2027-08-01","5K"),expected_version=s.input_version)
    elif change=="workout":
        with sqlite3.connect(db) as conn:
            conn.execute("UPDATE planned_workout SET workout_name='Changed' WHERE planned_workout_id=?",(old,))
    elif change=="activity":
        with sqlite3.connect(db) as conn:
            conn.execute("INSERT INTO activity(activity_id,start_time_gmt) VALUES(987,'2027-06-10T12:00:00Z')")
    elif change=="settings":
        plans.update_season(db,s.season_id,plans.SeasonDraft(s.name,s.start_date,s.end_date,s.timezone,replace(s.inputs,baseline_distance_code="HM")),expected_version=s.input_version)
    else:
        monkeypatch.setattr(generation,"_local_today",lambda tz:date(2027,6,2))
    before=snapshot(db)
    with pytest.raises(generation.StalePreviewError):
        reset.apply_reset(db,p,approved_by="TEST",acknowledged=True)
    assert snapshot(db)==before


def test_concurrent_acceptance_is_atomic_and_idempotent(tmp_path):
    db,s=setup_season(tmp_path)
    legacy(db)
    p=reset.preview_reset(db,s.season_id,SETTINGS,restart_date=START)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:reset.apply_reset(db,p,approved_by="TEST",acknowledged=True).status,range(2)))
    assert sorted(results)==["applied","duplicate"]


@pytest.mark.parametrize("keep_history",[False,True])
def test_unowned_structured_older_plan_is_superseded_without_relinking(tmp_path,keep_history):
    from test_plan_revision_persistence import _fitzgerald_candidate, _approve
    from garmin_data_hub.plan_methodology.domain import Sport
    db,s=setup_season(tmp_path)
    old=_fitzgerald_candidate()
    base=old.workouts[0]
    rows=[replace(base,scheduled_date=date(2027,6,10),workout_id="old-future",ordinal=0)]
    if keep_history:
        rows.insert(0,replace(base,scheduled_date=date(2027,1,10),workout_id="old-history",ordinal=0))
        rows[-1]=replace(rows[-1],ordinal=1)
    old=replace(old,workouts=tuple(rows))
    _approve(db,old)
    original=load_revision(db,old.revision_id).content_hash
    p=reset.preview_reset(db,s.season_id,SETTINGS,restart_date=START)
    assert p.can_apply,(p.blockers,p.schedule.errors)
    accept(db,p)
    assert load_revision(db,old.revision_id).content_hash==original
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM active_planned_workout WHERE source_workout_id='old-future'").fetchone()[0]==0
        pointer=conn.execute("SELECT current_revision_id FROM training_plan WHERE plan_id=?",(old.plan_id,)).fetchone()[0]
    if keep_history:
        retained=load_revision(db,pointer).candidate
        assert len(retained.workouts)==1 and retained.workouts[0].workout_id=="old-history"
        assert prescribed_content(retained.workouts[0])==prescribed_content(old.workouts[0])
    else:
        assert pointer is None


def test_completed_match_keeps_its_original_identity_after_restart(tmp_path,monkeypatch):
    from garmin_data_hub.plan_methodology.activity_workout_match import create_match, load_confirmed_match
    from garmin_data_hub.db.sqlite import connect_sqlite
    db,s,parent=applied_year(tmp_path,monkeypatch)
    w=next(w for w in parent.workouts if w.scheduled_date==date(2027,6,10))
    conn=connect_sqlite(db)
    conn.execute("INSERT INTO activity(activity_id) VALUES(991)")
    create_match(conn,revision_id=parent.revision_id,workout_id=w.workout_id,activity_id=991,status="CONFIRMED",source="MANUAL",confidence="HIGH",reviewer="T",reason="done")
    conn.commit();conn.close()
    p=reset.preview_reset(db,s.season_id,SETTINGS,restart_date=START,replace_protected=True)
    assert w.workout_id in p.schedule.candidate.change_summary["preserved_workout_ids"]
    accept(db,p)
    conn=connect_sqlite(db)
    assert load_confirmed_match(conn,activity_id=991).workout_id==w.workout_id
    conn.close()


@pytest.mark.parametrize("field,value",[("replace_protected",True),("clear_events",True),("restart_date","2027-06-03")])
def test_tampered_preview_is_rejected_before_and_after_acceptance(tmp_path,field,value):
    db,s=setup_season(tmp_path)
    legacy(db)
    p=reset.preview_reset(db,s.season_id,SETTINGS,restart_date=START)
    altered=replace(p,**{field:value})
    with pytest.raises(generation.StalePreviewError):
        reset.apply_reset(db,altered,approved_by="T",acknowledged=True)
    accept(db,p)
    with pytest.raises(generation.StalePreviewError):
        reset.apply_reset(db,altered,approved_by="T",acknowledged=True)


def test_historical_legacy_overlap_does_not_block_owned_restart(tmp_path,monkeypatch):
    db,s,parent=applied_year(tmp_path,monkeypatch)
    old=legacy(db,"2027-01-02")
    legacy(db,"2027-06-10")
    normal=generation.preview_season(db,s.season_id,SETTINGS)
    assert not normal.can_apply and any("Existing workouts overlap" in x for x in normal.apply_blockers)
    fresh=reset.preview_reset(db,s.season_id,SETTINGS,restart_date=START)
    accept(db,fresh)
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM active_planned_workout WHERE planned_workout_id=?",(old,)).fetchone()[0]==1
    assert read_state(db,s.season_id).status=="current"
    current=plans.get_season(db,s.season_id)
    plans.save_event(db,s.season_id,plans.EventDraft("New event","2027-10-10","5K"),expected_version=current.input_version)
    followup=generation.preview_season(db,s.season_id,SETTINGS)
    assert followup.can_apply,(followup.apply_blockers,followup.schedule.errors)


def test_other_year_is_unchanged_and_foreign_retirement_rolls_back(tmp_path):
    from test_plan_revision_persistence import _fitzgerald_candidate, _approve
    db,s=setup_season(tmp_path)
    base=_fitzgerald_candidate()
    old=replace(base,workouts=(replace(base.workouts[0],scheduled_date=date(2027,6,10),ordinal=0),))
    _approve(db,old)
    other=plans.create_season(db,plans.SeasonDraft("Other year","2028-01-01","2028-12-31",s.timezone,s.inputs))
    untouched=legacy(db,"2028-01-02")
    p=reset.preview_reset(db,s.season_id,SETTINGS,restart_date=START)
    before=snapshot(db)
    with pytest.raises(InjectedApprovalFailure):
        accept(db,p,failure_hook=fail_at("after_reset_foreign"))
    assert snapshot(db)==before
    accept(db,p)
    assert plans.get_season(db,other.season_id)==other
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM active_planned_workout WHERE planned_workout_id=?",(untouched,)).fetchone()[0]==1


def test_maffetone_restart_uses_confirmed_native_ceiling(tmp_path):
    from garmin_data_hub.services.season_schedule import GenerationSettings
    from garmin_data_hub.plan_methodology.domain import Sport
    db,s=setup_season(tmp_path,inputs=plans.SeasonInputs(training_method="maffetone",starting_duration_seconds=10800,baseline_distance_code="HM"))
    legacy(db)
    settings=GenerationSettings(maf_adjustment=0,maf_confirmed=True)
    p=reset.preview_reset(db,s.season_id,settings,restart_date=START)
    accept(db,p)
    assert any(w.sport is Sport.RUNNING for w in p.schedule.candidate.workouts)
    assert not any(w.quality_flag for w in p.schedule.candidate.workouts)
    assert all(seg.prescription.primary.upper==140 for w in p.schedule.candidate.workouts if w.sport is Sport.RUNNING for seg in w.segments)
    assert read_state(db,s.season_id).status=="current"


def test_real_recovery_boundary_is_kept_and_clear_events_can_resolve_it(tmp_path):
    db,s=setup_season(tmp_path,events=(plans.EventDraft("Year-end marathon","2027-12-26","MAR"),))
    other=plans.create_season(db,plans.SeasonDraft("Next year","2028-01-01","2028-12-31",s.timezone,s.inputs))
    legacy(db,"2028-01-02")
    p=reset.preview_reset(db,s.season_id,SETTINGS,restart_date=START)
    assert not p.can_apply and any("following-year" in b for b in p.blockers)
    clean=reset.preview_reset(db,s.season_id,SETTINGS,restart_date=START,clear_events=True)
    accept(db,clean)
    assert plans.get_season(db,other.season_id)==other


def test_private_initial_restart_requires_its_reviewed_receipt(tmp_path):
    from garmin_data_hub.services import legacy_workout_removal
    db,s=setup_season(tmp_path)
    p=reset.preview_reset(db,s.season_id,SETTINGS,restart_date=START)
    altered=replace(p.schedule.candidate,change_summary={})
    conn=legacy_workout_removal._read_connection(db)
    try:
        with pytest.raises(plans.SeasonError):
            reset.validate_initial_restart(conn,altered,{"season_id":s.season_id},START)
    finally:
        conn.close()
