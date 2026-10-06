from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
import json
import sqlite3

import pytest

from garmin_data_hub.db import migrate
from garmin_data_hub.paths import schema_sql_path
from garmin_data_hub.plan_methodology.legacy import resolve_legacy_plan
from garmin_data_hub.services import legacy_workout_removal as removal, season_generation as generation, season_plans as plans
from garmin_data_hub.services.plan_persistence import get_active_plan_sha256, save_generated_plan
from garmin_data_hub.exports.forever.calendar_builder import DayPlan
from test_season_generation import setup_season
from test_plan_revision_persistence import _fitzgerald_candidate, _approve
from test_plan_persistence import _make_imported_plan
from garmin_data_hub.db.sqlite import connect_sqlite
from garmin_data_hub.plan_methodology.activity_workout_match import create_match
from garmin_data_hub.db.queries import delete_planned_workouts_in_range


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr(generation,"_local_today",lambda tz:date(2026,10,6))


def add(db,day="2027-01-02",structure=None,name="Original easy run"):
    with sqlite3.connect(db) as conn:
        if "start_time_gmt" not in {r[1] for r in conn.execute("PRAGMA table_info(activity)")}:
            conn.execute("ALTER TABLE activity ADD COLUMN start_time_gmt TEXT")
        cursor = conn.execute("""INSERT INTO planned_workout(scheduled_date,workout_name,description,
            planned_duration_s,planned_distance_m,planned_tss,structure_json) VALUES (?,?,'Original prescription',1800,5000,42,?)""",
            (day,name,json.dumps(structure or {})))
        return cursor.lastrowid


def snapshot(db):
    with sqlite3.connect(db) as conn:
        return {table:conn.execute(f'SELECT * FROM {table} ORDER BY 1').fetchall() for table in
            ("planned_workout","activity","activity_workout_match","season_plan","season_event","training_plan",
             "plan_revision","plan_revision_workout_origin","season_workout_state","app_settings","legacy_workout_removal","legacy_workout_removal_item")}


def test_preview_dismiss_apply_reload_duplicate_preserves_originals_history_and_unselected(tmp_path):
    db,s = setup_season(tmp_path)
    ids = [add(db,"2026-10-05"),add(db),add(db,"2027-01-03")]
    original = snapshot(db)
    reviewed = removal.preview_removal(db,[ids[1]],season_id=s.season_id)
    assert reviewed.can_apply
    assert snapshot(db) == original
    with pytest.raises(plans.SeasonError,match="acknowledgement"):
        removal.apply_removal(db,reviewed,approved_by="TEST")
    assert snapshot(db) == original
    assert removal.apply_removal(db,reviewed,approved_by="TEST",acknowledged=True) == "applied"
    with sqlite3.connect(db) as conn:
        assert {r[0] for r in conn.execute("SELECT planned_workout_id FROM active_planned_workout")} == {ids[0],ids[2]}
    after = snapshot(db)
    for key in original:
        if key not in {"legacy_workout_removal","legacy_workout_removal_item"}:
            assert after[key] == original[key]
    reloaded = replace(reviewed)
    assert removal.apply_removal(db,reloaded,approved_by="TEST",acknowledged=True) == "duplicate"
    assert snapshot(db) == after
    assert json.loads(removal.list_removals(db)[0]["review_json"])["workouts"][0]["planned_duration_s"] == 1800
    assert ids[1] not in resolve_legacy_plan(db).planned_workout_ids


@pytest.mark.parametrize("kind",("history","today","locked","completed","manual","invalid","activity","owned","canonical"))
def test_protected_or_nonlegacy_selection_cannot_be_removed(tmp_path,kind):
    db,s = setup_season(tmp_path)
    wid = add(db,"2026-10-05" if kind=="history" else "2026-10-06" if kind=="today" else "2027-01-02",
              {"locked":True} if kind=="locked" else {"status":"completed"} if kind=="completed" else {"flags":["MANUALLY_EDITED"]} if kind=="manual" else {})
    with sqlite3.connect(db) as conn:
        if kind=="invalid":
            conn.execute("UPDATE planned_workout SET structure_json='broken' WHERE planned_workout_id=?",(wid,))
        if kind=="activity":
            conn.execute("INSERT INTO activity(activity_id,start_time_gmt) VALUES (901,'2027-01-03T03:00:00Z')")
    if kind in {"owned","canonical"}:
        candidate = _fitzgerald_candidate()
        candidate = replace(candidate,workouts=tuple(replace(w,scheduled_date=date(2027,1,2)) for w in candidate.workouts))
        _approve(db,candidate)
        if kind=="canonical":
            with sqlite3.connect(db) as conn:
                wid = conn.execute("SELECT planned_workout_id FROM planned_workout WHERE source_plan_id=?",(candidate.plan_id,)).fetchone()[0]
        else:
            with sqlite3.connect(db) as conn:
                conn.execute("UPDATE season_plan SET plan_id=? WHERE season_id=?",(candidate.plan_id,s.season_id))
    before = snapshot(db)
    p = removal.preview_removal(db,[wid])
    assert not p.can_apply and p.blockers
    with pytest.raises(plans.SeasonError):
        removal.apply_removal(db,p,approved_by="TEST",acknowledged=True)
    assert snapshot(db) == before


@pytest.mark.parametrize("change",("prescription","activity","intent","date","policy","cache"))
def test_stale_removal_requires_new_review_and_does_not_write(tmp_path,monkeypatch,change):
    db,s = setup_season(tmp_path)
    wid = add(db)
    p = removal.preview_removal(db,[wid],season_id=s.season_id)
    with sqlite3.connect(db) as conn:
        if change=="prescription":
            conn.execute("UPDATE planned_workout SET planned_duration_s=2100 WHERE planned_workout_id=?",(wid,))
        if change=="activity":
            conn.execute("INSERT INTO activity(activity_id,start_time_gmt) VALUES (901,'2027-01-03T03:00:00Z')")
        if change=="cache":
            conn.execute("INSERT INTO app_settings(key,value) VALUES ('last_generated_plan',?)",(json.dumps({"day_plans":[]}),))
    if change=="intent":
        plans.save_event(db,s.season_id,plans.EventDraft("New event","2027-05-16"),expected_version=s.input_version)
    if change=="date":
        monkeypatch.setattr(generation,"_local_today",lambda tz:date(2026,10,7))
    if change=="policy":
        monkeypatch.setattr(removal,"POLICY_VERSION","changed-policy")
    before = snapshot(db)
    with pytest.raises(generation.StalePreviewError):
        removal.apply_removal(db,p,approved_by="TEST",acknowledged=True)
    assert snapshot(db) == before


@pytest.mark.parametrize("stage",("after_removal_header","after_removal_items"))
def test_apply_failure_rolls_back_retirement_and_nutrition(tmp_path,stage):
    db,s = setup_season(tmp_path)
    wid = add(db)
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO app_settings(key,value) VALUES ('last_generated_plan',?)",(json.dumps({"day_plans":[{"iso_date":"2027-01-02","nutrition":{"test":True}}]}),))
    p = removal.preview_removal(db,[wid])
    before = snapshot(db)
    def fail(here,conn):
        if here==stage:
            raise RuntimeError("Injected removal failure")
    with pytest.raises(RuntimeError,match="Injected"):
        removal.apply_removal(db,p,approved_by="TEST",acknowledged=True,failure_hook=fail)
    assert snapshot(db) == before


@pytest.mark.parametrize("statement",(
    "UPDATE legacy_workout_removal SET approved_by='changed'",
    "DELETE FROM legacy_workout_removal",
    "UPDATE legacy_workout_removal_item SET removal_id='changed'",
    "DELETE FROM legacy_workout_removal_item",
    "UPDATE planned_workout SET description='changed' WHERE planned_workout_id={wid}",
    "DELETE FROM planned_workout WHERE planned_workout_id={wid}",
))
def test_retirement_audit_and_saved_originals_are_immutable(tmp_path,statement):
    db,s = setup_season(tmp_path)
    wid = add(db)
    removal.apply_removal(db,removal.preview_removal(db,[wid]),approved_by="TEST",acknowledged=True)
    with sqlite3.connect(db) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(statement.format(wid=wid))


@pytest.mark.parametrize("double",(False,True))
def test_cache_pruning_preserves_other_dates_and_archives_original_cache(tmp_path,double):
    db,s = setup_season(tmp_path)
    wid = add(db)
    blob = {"day_plans":[{"iso_date":"2026-10-05","nutrition":{"keep":"history"}},
                         {"iso_date":"2027-01-02","nutrition":{"remove":"stale"}},
                         {"iso_date":"2027-01-03","nutrition":{"keep":"other"}}]}
    raw = json.dumps(json.dumps(blob)) if double else json.dumps(blob)
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO app_settings(key,value) VALUES ('last_generated_plan',?)",(raw,))
    p = removal.preview_removal(db,[wid])
    removal.apply_removal(db,p,approved_by="TEST",acknowledged=True)
    with sqlite3.connect(db) as conn:
        value = json.loads(conn.execute("SELECT value FROM app_settings WHERE key='last_generated_plan'").fetchone()[0])
    if double:
        value = json.loads(value)
    assert value["day_plans"] == [blob["day_plans"][0],blob["day_plans"][2]]
    assert json.loads(removal.list_removals(db)[0]["review_json"])["previous_generated_plan_cache"] == raw


def test_unreadable_cache_blocks_preview_and_apply(tmp_path):
    db,s = setup_season(tmp_path)
    wid = add(db)
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO app_settings(key,value) VALUES ('last_generated_plan','invalid')")
    p = removal.preview_removal(db,[wid])
    assert not p.can_apply and "cache" in p.blockers[0]
    before = snapshot(db)
    with pytest.raises(plans.SeasonError):
        removal.apply_removal(db,p,approved_by="TEST",acknowledged=True)
    assert snapshot(db)==before


def test_concurrent_acceptance_is_idempotent(tmp_path):
    db,s = setup_season(tmp_path)
    p = removal.preview_removal(db,[add(db)])
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _:removal.apply_removal(db,p,approved_by="TEST",acknowledged=True),range(2)))
    assert sorted(results)==["applied","duplicate"]
    assert len(removal.list_removals(db))==1


def test_legacy_writer_can_replace_retired_date_without_destroying_original(tmp_path):
    db,s = setup_season(tmp_path)
    wid = add(db)
    removal.apply_removal(db,removal.preview_removal(db,[wid]),approved_by="TEST",acknowledged=True)
    with sqlite3.connect(db) as conn:
        original = conn.execute("SELECT * FROM planned_workout WHERE planned_workout_id=?",(wid,)).fetchone()
    dp = DayPlan(iso_date="2027-01-02",day="Saturday",week=1,phase="Base",flags="",workout="New easy run 45 min",notes="")
    plan = _make_imported_plan(get_active_plan_sha256(db))
    save_generated_plan(db,plan.inputs,plan.analysis,[dp],[])
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT * FROM planned_workout WHERE planned_workout_id=?",(wid,)).fetchone()==original
        assert conn.execute("SELECT workout_name FROM active_planned_workout WHERE scheduled_date='2027-01-02'").fetchone()[0]=="New easy run 45 min"


def test_removal_preserves_confirmed_match_identity_and_rejects_new_evidence(tmp_path):
    db,s = setup_season(tmp_path)
    _approve(db,_fitzgerald_candidate())
    wid = add(db)
    old = removal.preview_removal(db,[wid])
    with connect_sqlite(db) as conn:
        conn.execute("INSERT INTO activity(activity_id) VALUES (999)")
        create_match(conn,revision_id="rev-a",workout_id="workout-1",activity_id=999,
            status="CONFIRMED",source="MANUAL",confidence="HIGH",reviewer="TEST",reason="Reviewed")
    with pytest.raises(generation.StalePreviewError):
        removal.apply_removal(db,old,approved_by="TEST",acknowledged=True)
    before = snapshot(db)
    reviewed = removal.preview_removal(db,[wid])
    removal.apply_removal(db,reviewed,approved_by="TEST",acknowledged=True)
    after = snapshot(db)
    for table in before:
        if table not in {"legacy_workout_removal","legacy_workout_removal_item"}:
            assert before[table] == after[table]


def test_legacy_range_clear_retains_archived_originals(tmp_path):
    db,s = setup_season(tmp_path)
    wid = add(db)
    other = add(db,name="Other future workout")
    removal.apply_removal(db,removal.preview_removal(db,[wid]),approved_by="TEST",acknowledged=True)
    with connect_sqlite(db) as conn:
        original = tuple(conn.execute("SELECT * FROM planned_workout WHERE planned_workout_id=?",(wid,)).fetchone())
        delete_planned_workouts_in_range(conn,"2027-01-02","2027-01-02")
        assert tuple(conn.execute("SELECT * FROM planned_workout WHERE planned_workout_id=?",(wid,)).fetchone())==original
        assert not conn.execute("SELECT 1 FROM planned_workout WHERE planned_workout_id=?",(other,)).fetchone()


def old_v15(db):
    with sqlite3.connect(db) as conn:
        conn.execute("DROP VIEW active_planned_workout")
        for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND (name LIKE 'trg_legacy_removal_%' OR name LIKE 'trg_retired_legacy_%')").fetchall():
            conn.execute(f'DROP TRIGGER "{name}"')
        conn.execute("DROP TABLE legacy_workout_removal_item")
        conn.execute("DROP TABLE legacy_workout_removal")
        conn.execute("DELETE FROM schema_migrations WHERE version=16")
        conn.execute("""CREATE VIEW active_planned_workout AS SELECT pw.* FROM planned_workout pw WHERE
            (source_plan_id IS NULL AND source_revision_id IS NULL AND source_workout_id IS NULL AND
             NOT EXISTS(SELECT 1 FROM legacy_plan_conversion_source_workout m WHERE m.planned_workout_id=pw.planned_workout_id)) OR
            (source_plan_id IS NOT NULL AND source_revision_id IS NOT NULL AND source_workout_id IS NOT NULL AND
             EXISTS(SELECT 1 FROM training_plan p WHERE p.plan_id=pw.source_plan_id AND p.current_revision_id=pw.source_revision_id))""")


def test_v16_upgrade_and_repair_preserve_schedule_and_existing_evidence(tmp_path):
    db,s = setup_season(tmp_path)
    add(db)
    _approve(db,_fitzgerald_candidate())
    old_v15(db)
    before = get_active_plan_sha256(db)
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT * FROM planned_workout ORDER BY planned_workout_id").fetchall()
        migrate.apply_schema(conn,schema_sql_path())
        migrate.apply_schema(conn,schema_sql_path())
        assert migrate.get_current_schema_version(conn)==16
        assert conn.execute("SELECT * FROM planned_workout ORDER BY planned_workout_id").fetchall()==rows
        assert conn.execute("SELECT COUNT(*) FROM legacy_workout_removal_item").fetchone()[0]==0
        assert conn.execute("PRAGMA foreign_key_check").fetchall()==[]
    assert get_active_plan_sha256(db)==before


def test_v16_upgrade_failure_restores_previous_view_and_version(tmp_path,monkeypatch):
    db,s = setup_season(tmp_path)
    add(db)
    old_v15(db)
    before = get_active_plan_sha256(db)
    original = migrate._migration_16_add_workout_removal
    def fail(conn,sql):
        original(conn,sql)
        raise sqlite3.OperationalError("Injected v16 failure")
    monkeypatch.setattr(migrate,"_migration_16_add_workout_removal",fail)
    with sqlite3.connect(db) as conn:
        with pytest.raises(sqlite3.OperationalError,match="Injected v16"):
            migrate.apply_schema(conn,schema_sql_path())
        assert migrate.get_current_schema_version(conn)==15
        assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='legacy_workout_removal_item'").fetchone()[0]==0
    assert get_active_plan_sha256(db)==before
