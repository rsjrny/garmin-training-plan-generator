"""Matching properties, reviewed persistence, original identities and migration."""
from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta
import json
import sqlite3

import pytest

from garmin_data_hub.analytics.workout_compliance import (
    ALL, LEGACY, suggestions, prepare_compliance, classify, pair_evidence,
)
from garmin_data_hub.services import workout_compliance as service
from garmin_data_hub.db import migrate
from garmin_data_hub.db.sqlite import connect_sqlite
from garmin_data_hub.paths import schema_sql_path
from garmin_data_hub.plan_methodology.activity_workout_match import create_match, MatchPersistenceError
from garmin_data_hub.plan_methodology.revision_repository import load_revision
from garmin_data_hub.services.plan_persistence import get_active_plan_sha256
from revision_fixtures import _database, _approve, _fitzgerald_candidate

TODAY = date(2026,10,14)


def workout(day="2026-10-01",key="w",**changes):
    return dict(key=key,plan_id="p",date=day,title=key,sport="RUNNING",rest=False,
        legacy=False,duration_s=3600,distance_m=10000,duration_estimated=False,
        distance_estimated=True,activity_id=None,explicitly_completed=False,**changes)


def activity(day="2026-10-01",aid=1,**changes):
    return dict(id=aid,date=day,name="Run",sport="running",duration_s=3600,distance_m=10000,**changes)


def snapshot(ws=None,acts=None,matches=(),available=True):
    return dict(workouts=ws if ws is not None else [workout()],activities=acts if acts is not None else [activity()],
        matches=list(matches),activity_available=available)


def prepared(data,start="2026-10-01",end="2026-10-14",window=3,plan_id=ALL):
    return prepare_compliance(data,start=date.fromisoformat(start),end=date.fromisoformat(end),today=TODAY,window=window,plan_id=plan_id)


@pytest.mark.parametrize("delta",[-3,-1,0,1,3])
def test_date_window_finds_moved_sessions_without_counting_unconfirmed_completion(delta):
    a = activity(day=(date(2026,10,1)+timedelta(days=delta)).isoformat())
    data = snapshot(acts=[a])
    before = deepcopy(data)
    edges = suggestions(data,3)
    assert len(edges) == 1 and edges[0]["day_delta"] == delta
    assert prepared(data)["workouts"][0]["status"] == "Needs review"
    assert prepared(data)["totals"]["completed"] == 0
    assert data == before


@pytest.mark.parametrize("changes",[
    {"sport":"cycling"},{"duration_s":None,"distance_m":None},
    {"duration_s":100,"distance_m":100},{"date":"2026-10-05"},{"date":None},
])
def test_incompatible_unknown_or_outside_window_does_not_become_suggestion(changes):
    a = activity()
    a.update(changes)
    assert not suggestions(snapshot(acts=[a]),3)


def test_ambiguous_pairs_are_not_clear_batch_candidates():
    data = snapshot(ws=[workout(key="one"),workout(key="two")],acts=[activity(aid=1),activity(aid=2)])
    edges = suggestions(data,3)
    assert len(edges) == 4
    assert all(e["ambiguous"] and e["confidence"] != "HIGH" for e in edges)
    assert prepared(data)["totals"]["completed"] == 0


def test_one_activity_already_claimed_elsewhere_is_never_extra_or_suggested():
    m = dict(workout_key="other",activity_id=1,status="CONFIRMED")
    data = snapshot(matches=[m])
    assert suggestions(data,3) == []
    result = prepared(data)
    assert result["activities"][0]["status"] == "Matched elsewhere/outside view"
    assert result["totals"]["extra"] == 0


@pytest.mark.parametrize("ratio,expected",[(0,"Partial"),(.79,"Partial"),(.8,"Completed"),(1,"Completed"),(2,"Completed")])
def test_confirmed_amount_tolerance_and_moved_completion(ratio,expected):
    w = workout()
    w["activity_id"] = 1
    a = activity(day="2026-10-02")
    a.update(duration_s=3600*ratio,distance_m=10000*ratio)
    row = classify(w,a,today=TODAY,window=3,candidate_count=0,activity_available=True)
    assert row["status"] == "Moved" and row["completion"] == expected
    assert row["date"] == "2026-10-01" and row["actual_date"] == "2026-10-02"


def test_missing_required_amount_never_establishes_full_completion():
    w = workout()
    w["activity_id"] = 1
    a = activity()
    a["distance_m"] = None
    row = classify(w,a,today=TODAY,window=3,candidate_count=0,activity_available=True)
    assert row["completion"] == "Unverified amounts"
    a["duration_s"] = 1200
    assert classify(w,a,today=TODAY,window=3,candidate_count=0,activity_available=True)["completion"] == "Partial"


@pytest.mark.parametrize("day,expected",[
    ("2026-10-15","Upcoming"),("2026-10-14","Today"),("2026-10-12","Awaiting activity"),("2026-10-10","Missed"),
])
def test_unstarted_sessions_are_missed_only_after_entire_window_closes(day,expected):
    row = classify(workout(day),None,today=TODAY,window=3,candidate_count=0,activity_available=True)
    assert row["status"] == expected


def test_rest_and_absent_activity_source_have_no_false_completion_or_miss():
    w = workout()
    w.update(rest=True,sport="REST",duration_s=0,distance_m=0)
    assert not suggestions(snapshot(ws=[w]),3)
    assert classify(w,None,today=TODAY,window=3,candidate_count=0,activity_available=True)["status"] == "Rest"
    assert classify(workout(),None,today=TODAY,window=3,candidate_count=0,activity_available=False)["status"] == "Evidence unavailable"


def test_legacy_unknown_sport_requires_explicit_manual_association():
    w = workout()
    w.update(legacy=True,sport="UNKNOWN")
    assert pair_evidence(w,activity(),3) is None
    assert pair_evidence(w,activity(),3,manual=True)["reviewed_sport"] == "RUNNING"


def test_streaks_ignore_rest_and_pending_last_day_makes_current_unsettled():
    ws = [workout("2026-10-01","one"),workout("2026-10-02","rest"),workout("2026-10-03","two")]
    ws[0]["explicitly_completed"] = True
    ws[1].update(rest=True,sport="REST")
    ws[2]["explicitly_completed"] = True
    result = prepared(snapshot(ws=ws,acts=[]))
    assert result["totals"]["longest_streak"] == result["totals"]["current_streak"] == 2
    ws.append(workout("2026-10-13","pending"))
    result = prepared(snapshot(ws=ws,acts=[]))
    assert result["totals"]["current_streak"] is None
    assert result["totals"]["longest_streak"] == 2


def test_weekly_recorded_volume_uses_actual_dates_and_unknowns_disable_variance():
    ws = [workout((date(2026,10,5)+timedelta(days=i)).isoformat(),str(i)) for i in range(7)]
    a = activity("2026-10-12")
    ws[0]["activity_id"] = 1
    result = prepared(snapshot(ws=ws,acts=[a],matches=[dict(workout_key="0",activity_id=1,status="CONFIRMED")]),start="2026-10-05",end="2026-10-13")
    first,second = result["weekly"]
    assert first["recorded_duration_s"] == 0
    assert second["recorded_duration_s"] == 3600
    assert first["duration_s_variance"] == -7*3600
    assert second["duration_s_variance"] is None  # no complete plan-day coverage
    ws[1]["duration_s"] = None
    first = prepared(snapshot(ws=ws,acts=[a]),start="2026-10-05")["weekly"][0]
    assert first["planned_duration_s"] == 6*3600
    assert first["duration_s_variance"] is None


@pytest.fixture
def clock(monkeypatch):
    monkeypatch.setattr(service,"_today",lambda:TODAY)


def database(tmp_path,native=True):
    path = _database(tmp_path)
    with sqlite3.connect(path) as conn:
        for col in ("start_time_local TEXT","start_time_gmt TEXT","duration_seconds REAL","moving_duration_seconds REAL","elapsed_duration_seconds REAL","distance_meters REAL","activity_name TEXT"):
            conn.execute("ALTER TABLE activity ADD COLUMN " + col)
        conn.execute("INSERT INTO activity(activity_id,activity_type,start_time_local,duration_seconds,elapsed_duration_seconds,distance_meters,activity_name) VALUES(1,'running','2026-10-02T23:30:00-04:00',3000,3600,8000,'Recorded run')")
    if native:
        _approve(path,_fitzgerald_candidate())
    else:
        with sqlite3.connect(path) as conn:
            conn.execute("INSERT INTO planned_workout(scheduled_date,workout_name,planned_duration_s,planned_distance_m,structure_json) VALUES('2026-10-01','Saved long run',3000,8000,?)",
                (json.dumps(dict(workout=dict(sport="run"))),))
    return path


def decide(path,view,aid=1,status="CONFIRMED",key=None,hook=None):
    key = key or view["data"]["workouts"][0]["key"]
    return service.review_pairs(path,view,[dict(workout_key=key,activity_id=aid,status=status)],reviewer="tester",reason="Reviewed session identity",failure_hook=hook)


@pytest.mark.parametrize("native",[True,False])
def test_read_only_suggestions_review_and_duplicate_preserve_schedule(tmp_path,clock,native):
    path = database(tmp_path,native)
    before = get_active_plan_sha256(path)
    with sqlite3.connect(path) as conn:
        original = tuple(conn.iterdump())
    view = service.compliance_view(path)
    with sqlite3.connect(path) as conn:
        assert tuple(conn.iterdump()) == original
    assert view["data"]["totals"]["completed"] == 0
    assert view["data"]["workouts"][0]["status"] == "Needs review"
    assert decide(path,view)["status"] == "applied"
    assert decide(path,view)["status"] == "duplicate"
    after = service.compliance_view(path)
    assert after["data"]["workouts"][0]["status"] == "Moved"
    assert after["data"]["workouts"][0]["completion"] == "Completed"
    assert after["data"]["totals"]["completed"] == after["data"]["totals"]["moved"] == 1
    assert not after["data"]["suggestions"]
    assert get_active_plan_sha256(path) == before


@pytest.mark.parametrize("native",[True,False])
def test_rejected_pair_suppressed_and_explicit_reconsideration_allowed(tmp_path,clock,native):
    path = database(tmp_path,native)
    view = service.compliance_view(path)
    decide(path,view,status="REJECTED")
    refreshed = service.compliance_view(path)
    assert not refreshed["data"]["suggestions"]
    assert refreshed["data"]["totals"]["completed"] == 0
    decide(path,refreshed)
    assert service.compliance_view(path)["data"]["totals"]["completed"] == 1


def test_untyped_legacy_review_supplies_sport_without_rewriting_original(tmp_path,clock):
    path = database(tmp_path,False)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE planned_workout SET structure_json=NULL")
    view = service.compliance_view(path)
    assert not view["data"]["suggestions"]
    before = get_active_plan_sha256(path)
    decide(path,view)
    row = service.compliance_view(path)["data"]["workouts"][0]
    assert row["sport_from_review"] and row["completion"] == "Completed"
    assert get_active_plan_sha256(path) == before


@pytest.mark.parametrize("kind",["activity","workout","date","tamper"])
def test_stale_or_tampered_review_has_no_partial_writes(tmp_path,clock,monkeypatch,kind):
    path = database(tmp_path,False)
    view = service.compliance_view(path)
    if kind == "activity":
        with sqlite3.connect(path) as conn:
            conn.execute("UPDATE activity SET duration_seconds=1200")
    elif kind == "workout":
        with sqlite3.connect(path) as conn:
            conn.execute("UPDATE planned_workout SET planned_duration_s=3600")
    elif kind == "date":
        monkeypatch.setattr(service,"_today",lambda:TODAY+timedelta(days=1))
    else:
        view["data"]["workouts"][0]["duration_s"] = 1
    with pytest.raises(service.StaleMatchReviewError):
        decide(path,view)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM workout_compliance_review").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM legacy_activity_workout_match").fetchone()[0] == 0


@pytest.mark.parametrize("stage",["after_receipt","after_decision"])
def test_review_failure_rolls_back_receipt_and_match(tmp_path,clock,stage):
    path = database(tmp_path,False)
    view = service.compliance_view(path)
    def fail(name,conn):
        if name == stage:
            raise RuntimeError("Injected match failure")
    with pytest.raises(RuntimeError,match="Injected"):
        decide(path,view,hook=fail)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM workout_compliance_review").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM legacy_activity_workout_match").fetchone()[0] == 0
    decide(path,view)


def test_cross_store_activity_uniqueness_and_matched_original_guards(tmp_path,clock):
    path = database(tmp_path,True)
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO planned_workout(scheduled_date,workout_name,planned_duration_s,structure_json) VALUES('2026-10-01','Older run',3000,?)",
            (json.dumps(dict(workout=dict(sport="run"))),))
    view = service.compliance_view(path,plan_id=LEGACY)
    decide(path,view)
    conn = connect_sqlite(path)
    try:
        with pytest.raises(MatchPersistenceError,match="older workout"):
            create_match(conn,revision_id="rev-a",workout_id="workout-1",activity_id=1,status="CONFIRMED",
                source="MANUAL",confidence="HIGH",reviewer="r",reason="attempt duplicate")
        with pytest.raises(sqlite3.IntegrityError,match="immutable"):
            conn.execute("UPDATE planned_workout SET planned_duration_s=1 WHERE source_plan_id IS NULL")
        with pytest.raises(sqlite3.IntegrityError,match="cannot be deleted"):
            conn.execute("DELETE FROM planned_workout WHERE source_plan_id IS NULL")
    finally:
        conn.close()
    assert service.compliance_view(path)["data"]["totals"]["completed"] == 1


def test_confirm_rejects_competing_existing_candidates_and_keeps_confirmed_records(tmp_path,clock):
    path = database(tmp_path)
    conn = connect_sqlite(path)
    candidate = create_match(conn,revision_id="rev-a",workout_id="workout-1",activity_id=1,status="CANDIDATE",source="RECONCILIATION",confidence="UNKNOWN")
    conn.commit()
    conn.close()
    view = service.compliance_view(path)
    decide(path,view)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT status FROM activity_workout_match WHERE activity_workout_match_id=?",(candidate.activity_workout_match_id,)).fetchone()[0] == "CONFIRMED"
    confirmed = service.compliance_view(path)
    with pytest.raises(service.MatchReviewError,match="immutable"):
        decide(path,confirmed,status="REJECTED")


@pytest.mark.parametrize("window",[0,15,True,1.5])
def test_invalid_date_window_is_explicit_error_before_any_db_creation(tmp_path,clock,window):
    missing = tmp_path/"missing.db"
    with pytest.raises(service.MatchReviewError,match="date window"):
        service.compliance_view(missing,window=window)
    assert not missing.exists()


def v16_database(tmp_path):
    path = tmp_path/"v16.db"
    sql = schema_sql_path().read_text(encoding="utf8")
    first = sql.index("--  A4C) REVIEWED WORKOUT COMPLIANCE")
    last = sql.index("--  A5) EDITABLE SEASON PLANNING INTENT",first)
    old = sql[:first] + sql[last:]
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE activity(activity_id INTEGER PRIMARY KEY)")
        conn.executescript(old)
        conn.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,name TEXT,applied_at_utc TEXT)")
        conn.execute("INSERT INTO schema_migrations VALUES(16,'previous schema','2026-10-01')")
        conn.execute("INSERT INTO planned_workout(scheduled_date,workout_name,planned_duration_s) VALUES('2026-10-01','Original',3000)")
    return path


def test_v17_upgrade_and_repair_are_additive_and_idempotent(tmp_path):
    path = v16_database(tmp_path)
    before = get_active_plan_sha256(path)
    with sqlite3.connect(path) as conn:
        migrate.apply_schema(conn,schema_sql_path())
        migrate.apply_schema(conn,schema_sql_path())
        assert migrate.get_current_schema_version(conn) == 17
        assert conn.execute("SELECT COUNT(*) FROM workout_compliance_review").fetchone()[0] == 0
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert get_active_plan_sha256(path) == before


def test_v17_ddl_and_version_rollback_together(tmp_path,monkeypatch):
    path = v16_database(tmp_path)
    real = migrate._migration_17_add_workout_compliance
    def fail(conn,sql):
        real(conn,sql)
        raise sqlite3.OperationalError("Injected v17 failure")
    monkeypatch.setattr(migrate,"_migration_17_add_workout_compliance",fail)
    with sqlite3.connect(path) as conn:
        with pytest.raises(sqlite3.OperationalError,match="Injected"):
            migrate.apply_schema(conn,schema_sql_path())
        assert migrate.get_current_schema_version(conn) == 16
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='legacy_activity_workout_match'").fetchone()


@pytest.mark.parametrize("native",[True,False])
def test_two_decision_batch_is_atomic_and_prevents_activity_reuse(tmp_path,clock,native):
    path = database(tmp_path,native)
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO planned_workout(scheduled_date,workout_name,planned_duration_s,structure_json) VALUES('2026-10-04','Second saved run',3000,?)",
            (json.dumps(dict(workout=dict(sport="run"))),))
        conn.execute("INSERT INTO activity(activity_id,activity_type,start_time_local,duration_seconds) VALUES(2,'running','2026-10-04T10:00:00',3000)")
    view = service.compliance_view(path)
    pairs = [dict(workout_key=w["key"],activity_id=1 if w["date"] == "2026-10-01" else 2,status="CONFIRMED") for w in view["data"]["workouts"]]
    bad = [dict(p,activity_id=1) for p in pairs]
    with pytest.raises(service.MatchReviewError,match="only one"):
        service.review_pairs(path,view,bad,reviewer="r",reason="bad duplication")
    counter = {"n":0}
    def fail(stage,conn):
        if stage == "after_decision":
            counter["n"] += 1
            if counter["n"] == 2:
                raise RuntimeError("second decision failure")
    with pytest.raises(RuntimeError,match="second decision"):
        service.review_pairs(path,view,pairs,reviewer="r",reason="both reviewed",failure_hook=fail)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM workout_compliance_review").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM activity_workout_match").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM legacy_activity_workout_match").fetchone()[0] == 0
    service.review_pairs(path,view,pairs,reviewer="r",reason="both reviewed")
    assert service.compliance_view(path)["data"]["totals"]["completed"] == 2


def test_confirmation_rejects_other_stored_candidates_for_same_workout(tmp_path,clock):
    path = database(tmp_path)
    conn = connect_sqlite(path)
    conn.execute("INSERT INTO activity(activity_id,activity_type,start_time_local,duration_seconds) VALUES(2,'running','2026-10-01T10:00:00',1000)")
    alternative = create_match(conn,revision_id="rev-a",workout_id="workout-1",activity_id=2,status="CANDIDATE",source="RECONCILIATION",confidence="LOW")
    conn.commit()
    conn.close()
    decide(path,service.compliance_view(path))
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT status FROM activity_workout_match WHERE activity_workout_match_id=?",(alternative.activity_workout_match_id,)).fetchone()[0] == "REJECTED"


def test_canonical_confirmation_blocks_legacy_double_claim_at_sql_boundary(tmp_path,clock):
    path = database(tmp_path)
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO planned_workout(scheduled_date,workout_name,planned_duration_s,structure_json) VALUES('2026-10-01','Other run',3000,?)",(json.dumps(dict(workout=dict(sport="run"))),))
    view = service.compliance_view(path,plan_id="plan-1")
    decide(path,view)
    legacy = next(w for w in service.compliance_view(path)["snapshot"]["workouts"] if w["legacy"])
    conn = connect_sqlite(path)
    try:
        with pytest.raises(sqlite3.IntegrityError,match="structured workout"):
            conn.execute("INSERT INTO legacy_activity_workout_match(planned_workout_id,workout_sha256,workout_snapshot_json,activity_id,reviewed_sport,status,review_id,reviewer,reason) VALUES(?,?,?,1,'RUNNING','CONFIRMED',?,'r','duplicate')",
                (legacy["legacy_id"],legacy["workout_sha256"],service._json(legacy["source_snapshot"]),view["review_id"]))
    finally:
        conn.close()


@pytest.mark.parametrize("flag",[True,1,"true","completed"])
def test_nested_explicit_completion_is_retained_without_inventing_actuals(tmp_path,clock,flag):
    path = database(tmp_path,False)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE planned_workout SET structure_json=?",(json.dumps(dict(workout=dict(sport="run",metadata=dict(explicitly_completed=flag)))),))
    view = service.compliance_view(path)
    row = view["data"]["workouts"][0]
    assert row["completion"] == "Completed" and row["actual_duration_s"] is None
    assert not view["data"]["suggestions"]
    assert view["data"]["activities"][0]["status"] == "Extra"  # no identity inferred from a done flag


@pytest.mark.parametrize("metadata",[
    {"workout":{"sport":"run","date":"2026-10-12","completed":True}},
    {"history":[{"completed":True}]},
    [{"completed":True}],
])
def test_other_occurrences_completion_metadata_is_not_applied_to_saved_row(tmp_path,clock,metadata):
    path = database(tmp_path,False)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE planned_workout SET structure_json=?",(json.dumps(metadata),))
    assert not service.compliance_view(path)["data"]["workouts"][0]["explicitly_completed"]


def test_confirmed_older_moved_completion_is_protected_from_redo_and_retirement(tmp_path,clock):
    from garmin_data_hub.services import legacy_workout_removal as removal, yearly_reset
    path = database(tmp_path,False)
    # Early completion: planned later than today, actual today, within the window.
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE planned_workout SET scheduled_date='2026-10-16'")
        conn.execute("UPDATE activity SET start_time_local='2026-10-14T10:00:00'")
    view = service.compliance_view(path,start="2026-10-14",end="2026-10-17")
    decide(path,view)
    conn = connect_sqlite(path)
    try:
        row = conn.execute("SELECT * FROM planned_workout WHERE source_plan_id IS NULL").fetchone()
        assert "Confirmed activity/workout completion" in removal._reasons(conn,row,TODAY.isoformat(),set())[0]
        assert yearly_reset._legacy_reason(conn,row,dict(activity_dates=[],replace_protected=True)) == "Confirmed activity/workout completion"
        with pytest.raises(sqlite3.IntegrityError,match="retained"):
            conn.execute("INSERT INTO legacy_workout_removal(removal_id,preview_id,review_sha256,review_json,timezone,local_today,approved_by,approved_at_utc) VALUES('r','p',?,'{}','America/New_York','2026-10-14','r','2026-10-14T10:00:00Z')",("a"*64,))
            conn.execute("INSERT INTO legacy_workout_removal_item(removal_id,planned_workout_id) VALUES('r',?)",(row["planned_workout_id"],))
    finally:
        conn.close()


def test_match_identity_survives_yearly_c_marker_revision_with_exact_original(tmp_path,monkeypatch):
    from test_season_regeneration import active, apply
    from test_season_generation import SETTINGS
    from garmin_data_hub.services import season_generation as generation, season_plans as intent
    db,season,parent = active(tmp_path)
    today = date(2027,2,20)
    monkeypatch.setattr(service,"_today",lambda:today)
    monkeypatch.setattr(generation,"_local_today",lambda tz:today)
    w = next(w for w in parent.workouts if w.scheduled_date == date(2027,2,18))
    duration = sum(s.duration_seconds or 0 for s in w.segments)
    with sqlite3.connect(db) as conn:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(activity)")}
        for column in ("activity_type","start_time_local","duration_seconds"):
            if column not in columns:
                conn.execute("ALTER TABLE activity ADD COLUMN " + column + (" REAL" if column == "duration_seconds" else " TEXT"))
        conn.execute("INSERT INTO activity(activity_id,activity_type,start_time_local,duration_seconds) VALUES(77,'running','2027-02-19T10:00:00',?)",(duration,))
    view = service.compliance_view(db,start="2027-02-18",end="2027-02-20")
    key = next(r["key"] for r in view["data"]["workouts"] if r["workout_id"] == w.workout_id)
    decide(db,view,aid=77,key=key)
    intent.save_event(db,season.season_id,intent.EventDraft("C marker","2027-05-16","5K","C"),expected_version=season.input_version)
    preview = generation.preview_season(db,season.season_id,SETTINGS)
    assert preview.can_apply
    apply(db,preview)
    after = service.compliance_view(db,start="2027-02-18",end="2027-02-20")
    matched = next(r for r in after["data"]["workouts"] if r["key"] == key)
    assert matched["activity_id"] == 77 and matched["status"] == "Moved"
    assert matched["origin_revision_id"] == parent.revision_id
    assert load_revision(db,parent.revision_id).content_hash == parent.content_hash
