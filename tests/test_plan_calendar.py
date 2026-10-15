"""Saved-label calendar summaries, verified sources and preserved scope."""
from dataclasses import replace
from datetime import date
import json
import sqlite3

import pytest

from garmin_data_hub.analytics.plan_calendar import calendar_week
from garmin_data_hub.services.plan_calendar import calendar_schedule
from garmin_data_hub.services import season_plans as intent
from garmin_data_hub.plan_methodology.revision_repository import CorruptRevisionError
from revision_fixtures import _approve, _fitzgerald_candidate
from test_workout_compliance import database


def row(day,kind="RUNNING",**metadata):
    return dict(date=day,sport=kind,workout="Session",duration_min=30,distance_km=5,
                calendar=metadata)


def test_calendar_counts_density_strength_rest_and_missing_measures():
    rows = [row("2028-02-28",hard=True),row("2028-02-28","STRENGTH"),
            row("2028-02-29","REST"),row("2028-03-01",long=True),row("2028-03-02","UNKNOWN")]
    rows[3]["duration_min"] = None
    summary = calendar_week(rows,date(2028,2,28))
    assert summary["training_days"] == 2 and summary["sessions"] == 3
    assert summary["rest_days"] == summary["unclassified"] == 1
    assert summary["multiple"] == ["2028-02-28"]
    assert summary["strength"] == ["2028-02-28"] and summary["long"] == ["2028-03-01"]
    assert summary["amounts"]["duration_min"] == dict(value=90,missing=1,count=4)
    assert summary["amounts"]["distance_km"]["value"] == 10


def test_adjacent_hard_days_include_sunday_monday_boundaries_but_never_c_markers():
    rows = [row("2026-10-11",hard=True),row("2026-10-12",hard=True),
            row("2026-10-18",hard=True),row("2026-10-19",hard=True),
            row("2026-10-14",hard=False),row("2026-10-15",hard=False)]
    summary = calendar_week(rows,date(2026,10,12))
    assert summary["adjacent"] == [("2026-10-11","2026-10-12"),("2026-10-18","2026-10-19")]
    assert summary["hard"] == ["2026-10-12","2026-10-18"]


@pytest.mark.parametrize("value",[None,-1,True,float("nan"),float("inf"),"invalid"])
def test_unknown_invalid_amounts_never_become_zero(value):
    item = row("2026-10-12")
    item["duration_min"] = value
    summary = calendar_week([item],date(2026,10,12))
    assert summary["amounts"]["duration_min"] == dict(value=None,missing=1,count=1)


def test_calendar_legacy_metadata_does_not_infer_hard_or_long_from_title(tmp_path):
    db = database(tmp_path,native=False)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE planned_workout SET workout_name='Hard long race run',structure_json='{}'")
        before = tuple(conn.iterdump())
    item = calendar_schedule(db)["rows"][0]
    assert item["sport"] == "UNKNOWN"
    assert item["calendar"]["hard"] is None and item["calendar"]["long"] is None
    with sqlite3.connect(db) as conn:
        assert tuple(conn.iterdump()) == before


def test_saved_other_occurrence_metadata_and_invalid_date_are_not_presented(tmp_path):
    db = database(tmp_path,native=False)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE planned_workout SET structure_json=?",(json.dumps(dict(workout=dict(date="2026-10-02",sport="run",quality_flag=True,long_run_flag=True))),))
    assert calendar_schedule(db)["rows"][0]["sport"] == "UNKNOWN"
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE planned_workout SET scheduled_date='not-a-date'")
    result = calendar_schedule(db)
    assert result["rows"] == [] and result["warnings"]


def test_canonical_amounts_and_labels_ignore_mutable_projection_metadata(tmp_path):
    db = database(tmp_path,native=False)
    base = _fitzgerald_candidate()
    candidate = replace(base,workouts=(replace(base.workouts[0],title="Original long run",long_run_flag=True,phase="BUILD"),))
    _approve(db,candidate)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE planned_workout SET workout_name='Projection title',planned_duration_s=99,structure_json='{}' WHERE source_plan_id IS NOT NULL")
    canonical = next(r for r in calendar_schedule(db)["rows"] if r["calendar"].get("long") is True)
    assert canonical["workout"] == "Original long run" and canonical["duration_min"] == 50
    assert canonical["phase"] == "BUILD"


def test_selected_unapplied_year_is_empty_and_events_do_not_create_workouts(tmp_path):
    db = database(tmp_path,native=False)
    s = intent.create_season(db,intent.SeasonDraft("Year","2026-01-01","2026-12-31","America/New_York"))
    intent.save_event(db,s.season_id,intent.EventDraft("C 5K","2026-10-01","5K","C"),expected_version=s.input_version)
    result = calendar_schedule(db,season_id=s.season_id)
    assert result["rows"] == []
    assert result["markers"][0]["priority"] == "C"
    with pytest.raises(intent.SeasonError):
        calendar_schedule(db,season_id="missing")


def test_invalid_canonical_projection_identity_blocks_calendar(tmp_path):
    db = database(tmp_path,native=True)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE planned_workout SET scheduled_date='2026-10-05' WHERE source_plan_id IS NOT NULL")
    with pytest.raises(CorruptRevisionError):
        calendar_schedule(db)


def test_confirmed_legacy_protection_label_is_retained(tmp_path,monkeypatch):
    from garmin_data_hub.services import workout_compliance as matches
    from test_workout_compliance import TODAY, decide
    db = database(tmp_path,native=False)
    monkeypatch.setattr(matches,"_today",lambda:TODAY)
    decide(db,matches.compliance_view(db))
    assert "Match confirmed" in calendar_schedule(db)["rows"][0]["protection"]


def test_carried_locked_marked_done_workout_retains_labels_and_original_phase(tmp_path,monkeypatch):
    from test_season_regeneration import active, lock, apply
    from test_season_generation import SETTINGS
    from garmin_data_hub.services import season_generation as generation
    db,s,parent = active(tmp_path)
    original = parent.workouts[0]
    lock(db,s,original,locked=True,explicitly_completed=True)
    intent.save_event(db,s.season_id,intent.EventDraft("C marker","2027-05-16","5K","C"),expected_version=s.input_version)
    apply(db,generation.preview_season(db,s.season_id,SETTINGS))
    row = next(r for r in calendar_schedule(db,season_id=s.season_id)["rows"] if r["date"] == original.scheduled_date.isoformat())
    assert row["phase"] == original.phase
    from garmin_data_hub.services.workout_heart_rate import workout_heart_rate
    assert row["heart_rate"] == workout_heart_rate(original)["heart_rate"]
    assert all(label in row["protection"] for label in ("Locked","Marked done","Preserved"))
