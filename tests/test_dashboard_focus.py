"""Rolling dates, scoped originals, reviewed outcomes and coherent evidence."""
from datetime import date, datetime, timezone
from dataclasses import replace
import json
import sqlite3

import pytest

from garmin_data_hub.services import dashboard_focus as focus, workout_compliance as matches
from garmin_data_hub.services import season_plans as intent
from garmin_data_hub.services.recovery_readiness import SETTING_KEY
from revision_fixtures import _approve, _fitzgerald_candidate
from test_workout_compliance import database, TODAY, decide


def fixture(tmp_path):
    db = database(tmp_path,native=False)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE planned_workout SET scheduled_date='2026-10-12'")
        conn.execute("UPDATE activity SET start_time_local='2026-10-13T23:30:00-04:00'")
        for day,title,sport,seconds in [
            ("2026-10-14","Today's long run","run",6000),
            ("2026-10-15","Saved rest","rest",0),
            ("2026-10-20","Final day run","run",2400),
            ("2026-10-21","Outside window","run",2400)]:
            conn.execute("INSERT INTO planned_workout(scheduled_date,workout_name,planned_duration_s,structure_json) VALUES(?,?,?,?)",
                (day,title,seconds,json.dumps({"workout":{"sport":sport}})))
    return db


def test_rolling_seven_days_includes_empty_days_rest_and_exact_end_without_writes(tmp_path):
    db = fixture(tmp_path)
    with sqlite3.connect(db) as conn:
        before = tuple(conn.iterdump())
    result = focus.dashboard_focus(db,today=TODAY)
    assert [d["date"] for d in result["days"]] == [f"2026-10-{i}" for i in range(14,21)]
    assert result["days"][0]["sessions"][0]["status"] == "Needs review"
    assert result["days"][0]["sessions"][0]["completion"] is None
    assert result["days"][1]["sessions"][0]["status"] == "Rest"
    assert result["days"][2]["sessions"] == []
    assert result["days"][-1]["sessions"][0]["title"] == "Final day run"
    assert result["recent"]["completed"] == 0 and result["recent"]["needs_review"] == 1
    with sqlite3.connect(db) as conn:
        assert tuple(conn.iterdump()) == before


@pytest.mark.parametrize("seconds,completion",[(3000,"Completed"),(1500,"Partial")])
def test_recent_moved_counts_only_explicit_review_and_keeps_planned_date(tmp_path,monkeypatch,seconds,completion):
    db = fixture(tmp_path)
    monkeypatch.setattr(matches,"_today",lambda:TODAY)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE activity SET duration_seconds=?",(seconds,))
    view = matches.compliance_view(db,start="2026-10-07",end="2026-10-14")
    key = next(w["key"] for w in view["data"]["workouts"] if w["date"] == "2026-10-12")
    decide(db,view,key=key)
    recent = focus.dashboard_focus(db,today=TODAY)["recent"]
    assert recent["moved"] == 1
    assert recent["completed" if completion == "Completed" else "partial"] == 1
    row = next(r for r in recent["sessions"] if r["date"] == "2026-10-12")
    assert row["actual_date"] == "2026-10-13" and row["completion"] == completion


def season(db):
    return intent.create_season(db,intent.SeasonDraft("Selected year","2026-01-01","2026-12-31","America/New_York"))


def test_unapplied_selected_year_does_not_leak_other_saved_workouts(tmp_path):
    db = fixture(tmp_path)
    s = season(db)
    result = focus.dashboard_focus(db,season_id=s.season_id,today=TODAY)
    assert result["no_applied_plan"] and all(not d["sessions"] for d in result["days"])
    assert result["recent"]["sessions"] == []
    assert result["recent"]["activity_count"] == 1  # athlete-wide scope is explicit


def test_linked_year_only_uses_its_verified_canonical_workouts_and_c_is_marker(tmp_path):
    db = fixture(tmp_path)
    candidate = _fitzgerald_candidate()
    _approve(db,replace(candidate,workouts=(replace(candidate.workouts[0],scheduled_date=TODAY,title="Canonical long run"),)))
    s = season(db)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE season_plan SET plan_id=?,status='active' WHERE season_id=?",(candidate.plan_id,s.season_id))
    intent.save_event(db,s.season_id,intent.EventDraft("Fun 5K","2026-10-14","5K","C"),expected_version=s.input_version)
    current = intent.get_season(db,s.season_id)
    intent.save_event(db,s.season_id,intent.EventDraft("Cancelled race","2026-10-15","5K","C",status="cancelled"),expected_version=current.input_version)
    result = focus.dashboard_focus(db,season_id=s.season_id,today=TODAY)
    day = result["days"][0]
    assert [r["title"] for r in day["sessions"]] == ["Canonical long run"]
    assert day["sessions"][0]["duration_s"] == 3000
    assert day["events"][0]["priority"] == "C" and day["events"][0]["name"] == "Fun 5K"
    assert result["days"][1]["events"] == []
    assert result["recent"]["sessions"] == []


def test_invalid_year_never_falls_back_to_all_plans(tmp_path):
    with pytest.raises(intent.SeasonError,match="no longer"):
        focus.dashboard_focus(fixture(tmp_path),season_id="deleted",today=TODAY)


def test_missing_and_stale_health_do_not_supply_current_favorable_readiness(tmp_path):
    db = fixture(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE sleep(calendar_date TEXT,sleep_time_seconds REAL)")
        conn.execute("INSERT INTO sleep VALUES('2026-10-12',28800)")
    result = focus.dashboard_focus(db,today=TODAY)
    recovery = result["recovery"]
    assert recovery["assessment_date"] == TODAY.isoformat()
    assert recovery["latest_signal_date"] == "2026-10-12"
    assert all(s["score"] is None for s in recovery["assessment"]["scores"].values())
    assert result["days"][0]["sessions"][0]["duration_s"] == 6000


def test_invalid_recovery_preference_does_not_hide_today_schedule(tmp_path):
    db = fixture(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO app_settings(key,value) VALUES(?,'bad')",(SETTING_KEY,))
    result = focus.dashboard_focus(db,today=TODAY)
    assert result["recovery"] is None and "invalid" in result["recovery_error"]
    assert result["days"][0]["sessions"][0]["title"] == "Today's long run"


def test_schedule_and_recovery_preferences_share_snapshot_during_concurrent_write(tmp_path,monkeypatch):
    db = fixture(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("INSERT INTO app_settings(key,value) VALUES(?,'8')",(SETTING_KEY,))
    real = focus.recovery_assessment
    def concurrent(*args,**kwargs):
        with sqlite3.connect(db) as writer:
            writer.execute("UPDATE app_settings SET value='9' WHERE key=?",(SETTING_KEY,))
            writer.execute("UPDATE planned_workout SET workout_name='New title' WHERE scheduled_date='2026-10-14'")
        return real(*args,**kwargs)
    monkeypatch.setattr(focus,"recovery_assessment",concurrent)
    result = focus.dashboard_focus(db,today=TODAY)
    assert result["days"][0]["sessions"][0]["title"] == "Today's long run"
    assert result["recovery"]["sleep_target_hours"] == 8
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT value FROM app_settings WHERE key=?",(SETTING_KEY,)).fetchone()[0] == "9"


def test_year_timezone_defines_today_at_utc_midnight(tmp_path,monkeypatch):
    db = fixture(tmp_path)
    s = season(db)
    class FixedClock:
        @staticmethod
        def now(zone):
            return datetime(2026,10,14,1,tzinfo=timezone.utc).astimezone(zone)
    monkeypatch.setattr(focus,"datetime",FixedClock)
    result = focus.dashboard_focus(db,season_id=s.season_id)
    assert result["today"] == "2026-10-13" and result["end"] == "2026-10-19"
