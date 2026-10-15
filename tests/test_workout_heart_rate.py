"""Targets come from immutable prescriptions, never current settings or names."""
from dataclasses import replace
from decimal import Decimal
import sqlite3

import pytest

from garmin_data_hub.plan_methodology.domain import Metric, Sport, SegmentKind, LoadMode, MeasureRole
from garmin_data_hub.plan_methodology.prescriptions import MetricRange, MetricCeiling
from garmin_data_hub.plan_methodology.segments import WorkoutSegment
from garmin_data_hub.services.workout_heart_rate import range_text, workout_heart_rate
from garmin_data_hub.services.plan_calendar import calendar_schedule
from garmin_data_hub.services.chart_plan_data import active_chart_plan_data
from garmin_data_hub.ui_nicegui.data import plan_rows
from garmin_data_hub.ui_nicegui.planning_presenter import describe_workout
from revision_fixtures import _approve, _fitzgerald_candidate, _maffetone_candidate
from test_workout_compliance import database


@pytest.mark.parametrize("lo,hi,li,ui,expected",[
    ("137.7","153",True,False,"138–152 bpm"),
    ("125","135",True,True,"125–135 bpm"),
    ("125","135",False,False,"126–134 bpm"),
    (None,"135.1",False,False,"≤ 135 bpm"),
    ("153",None,True,False,"≥ 153 bpm"),
    ("135.1","135.9",True,True,"No whole-bpm target within saved bounds"),
    ("135","136",True,False,"135 bpm"),
])
def test_whole_bpm_ranges_respect_exact_bounds(lo,hi,li,ui,expected):
    target = MetricRange(Metric.HEART_RATE,"bpm",lo,hi,li,ui)
    assert range_text(target) == expected


def test_separate_ceiling_is_always_respected():
    target = MetricRange(Metric.HEART_RATE,"bpm","125","145",True,True)
    assert range_text(target,MetricCeiling(Decimal("135"),False)) == "125–134 bpm"


def test_secondary_hr_and_missing_sections_do_not_form_one_broad_range():
    original = _fitzgerald_candidate().workouts[0]
    hard_rx = replace(original.segments[1].prescription,
                      secondary=MetricRange(Metric.HEART_RATE,"bpm","160","170",True,False))
    workout = replace(original,segments=(original.segments[0],
        replace(original.segments[1],prescription=hard_rx,repeat_group="intervals",repeat_iteration=1),
        replace(original.segments[2],prescription=None)))
    result = workout_heart_rate(workout)
    assert "138–152 bpm" in result["heart_rate"] and "160–169 bpm" in result["heart_rate"]
    assert "138–169" not in result["heart_rate"]
    assert "secondary; speed primary" in result["heart_rate"]
    assert "2. Work · repeat 1 · 30 min" in result["heart_rate_details"]
    assert "3. Cool-down · 10 min · HR unavailable" in result["heart_rate_details"]
    assert result["heart_rate"] in describe_workout(workout)


def test_missing_hr_auxiliary_and_rest_are_not_invented():
    original = _fitzgerald_candidate().workouts[0]
    no_hr = replace(original,segments=tuple(replace(s,prescription=replace(s.prescription,secondary=None))
                                           for s in original.segments))
    assert workout_heart_rate(no_hr)["heart_rate"] == "Unavailable"
    for sport in (Sport.STRENGTH,Sport.MOBILITY,Sport.REST):
        workout = replace(original,sport=sport,family=sport.value,
                          segments=((WorkoutSegment(SegmentKind.NON_TRAINING,LoadMode.OPEN),) if sport is Sport.REST else
                                    (WorkoutSegment(SegmentKind.WORK,LoadMode.DURATION,600,duration_role=MeasureRole.AUTHORITATIVE),)))
        assert workout_heart_rate(workout)["heart_rate"] == "Not prescribed"


@pytest.mark.parametrize("candidate,expected",[
    (_fitzgerald_candidate(),"138–152 bpm"),(_maffetone_candidate(),"125–135 bpm")])
def test_all_sources_agree_and_ignore_projection_or_current_values(tmp_path,candidate,expected):
    db = database(tmp_path,native=False)
    _approve(db,candidate)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE planned_workout SET structure_json='{}' WHERE source_plan_id IS NOT NULL")
        conn.execute("UPDATE athlete_profile SET lthr_override=190 WHERE profile_id=1")
        before = tuple(conn.iterdump())
    chart = active_chart_plan_data(db)["workouts"][0]
    calendar = next(r for r in calendar_schedule(db)["rows"] if r["date"] == chart["date"] and r["workout"] == chart["title"])
    table = plan_rows(db,plan_id=candidate.plan_id)[0]
    assert expected in chart["heart_rate"] == calendar["heart_rate"] == table["heart_rate"]
    with sqlite3.connect(db) as conn:
        assert tuple(conn.iterdump()) == before


def test_generated_targets_use_selected_values_and_method(tmp_path):
    from test_season_generation import setup_season, TODAY
    from garmin_data_hub.services.season_schedule import generate_season_schedule, GenerationSettings
    from garmin_data_hub.services.season_plans import SeasonInputs
    for method,inputs,settings,expected in (
        ("80/20",SeasonInputs(starting_duration_seconds=10800,lthr=170),GenerationSettings(lthr_confirmed=True),"138–152 bpm"),
        ("Maffetone",SeasonInputs(starting_duration_seconds=10800,training_method="maffetone",age=40),
         GenerationSettings(maf_adjustment=-5,maf_confirmed=True),"125–135 bpm"),
    ):
        db,season = setup_season(tmp_path/method.replace("/",""),inputs=inputs)
        schedule = generate_season_schedule(season,(),settings,today=TODAY,plan_id="plan",revision_id="rev")
        running = next(w for w in schedule.candidate.workouts if w.sport is Sport.RUNNING)
        assert expected in workout_heart_rate(running)["heart_rate"]


def test_older_untyped_workouts_never_get_ranges_from_names(tmp_path):
    db = database(tmp_path,native=False)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE planned_workout SET workout_name='Zone 2 140-150 bpm',structure_json='{}'")
    assert plan_rows(db)[0]["heart_rate"] == "Unavailable"
    assert calendar_schedule(db)["rows"][0]["heart_rate"] == "Unavailable"
