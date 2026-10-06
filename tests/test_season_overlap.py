from dataclasses import replace
from datetime import date
import sqlite3
import pytest

from garmin_data_hub.services import season_overlap, season_plans as plans
from garmin_data_hub.services.plan_persistence import get_active_plan_sha256
from garmin_data_hub.services.season_schedule import ScheduleIssue
from garmin_data_hub.ui_nicegui.season_review import warning_groups
from test_season_generation import setup_season
from test_plan_revision_persistence import _fitzgerald_candidate, _approve


def test_legacy_overlap_diagnostic_is_read_only_and_scoped(tmp_path):
    db, season = setup_season(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.executemany("INSERT INTO planned_workout(scheduled_date,workout_name,structure_json) VALUES (?,?,'{}')",
                         [("2026-12-31","History"),("2027-05-01","Older prescription"),("2028-01-01","Next year")])
    before = get_active_plan_sha256(db)
    review = season_overlap.review_overlap(db, season.season_id)
    assert review.legacy_count == 1
    assert review.workouts[0]["workout_name"] == "Older prescription"
    assert not review.candidates
    assert review.separate_start == "2027-05-02"
    assert get_active_plan_sha256(db) == before
    assert plans.get_season(db, season.season_id) == season


def test_canonical_overlap_can_use_explicit_existing_link_without_replacing_workouts(tmp_path):
    db, season = setup_season(tmp_path)
    candidate = _fitzgerald_candidate()
    candidate = replace(candidate,workouts=tuple(replace(w,scheduled_date=date(2027,4,1)) for w in candidate.workouts))
    _approve(db,candidate)
    before = get_active_plan_sha256(db)
    review = season_overlap.review_overlap(db,season.season_id)
    assert not review.legacy_count
    selected, = review.candidates
    assert not selected["reasons"]
    assert plans.get_season(db,season.season_id).plan_id is None
    plans.link_plan(db,season.season_id,selected["plan_id"],expected_version=review.season.input_version,
                    expected_revision_id=selected["current_revision_id"],expected_content_hash=selected["content_sha256"])
    assert get_active_plan_sha256(db) == before
    assert not season_overlap.review_overlap(db,season.season_id).workouts


def test_link_diagnostic_reports_method_history_and_other_overlap(tmp_path):
    db, season = setup_season(tmp_path)
    candidate = _fitzgerald_candidate()
    candidate = replace(candidate,workouts=(candidate.workouts[0],replace(candidate.workouts[0],
        scheduled_date=date(2027,4,1),workout_id="future",ordinal=1)))
    _approve(db,candidate)
    season = plans.update_season(db,season.season_id,plans.SeasonDraft(season.name,season.start_date,season.end_date,
        season.timezone,replace(season.inputs,training_method="maffetone")),expected_version=season.input_version)
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO planned_workout(scheduled_date,workout_name,structure_json) VALUES ('2027-05-01','Other','{}')")
    review = season_overlap.review_overlap(db,season.season_id)
    assert len(review.candidates[0]["reasons"]) == 3
    assert review.legacy_count == 1
    assert not plans.get_season(db,season.season_id).plan_id


@pytest.mark.parametrize("blocked_by",("event","end"))
def test_separate_dates_do_not_exclude_events_or_exceed_year(tmp_path,blocked_by):
    events = [plans.EventDraft("Early event","2027-01-04")] if blocked_by == "event" else []
    db, season = setup_season(tmp_path,events)
    when = "2027-01-05" if blocked_by == "event" else "2027-12-31"
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO planned_workout(scheduled_date,workout_name,structure_json) VALUES (?,'Keep','{}')",(when,))
    review = season_overlap.review_overlap(db,season.season_id)
    assert not review.separate_start
    assert "event" in review.separate_reason if blocked_by == "event" else "no separate dates" in review.separate_reason


def test_grouping_retains_every_warning_and_does_not_merge_distinct_events():
    warnings = (ScheduleIssue("MAF","warning","Warm up","2027-01-01"),
                ScheduleIssue("MAF","warning","Warm up","2027-01-02"),
                ScheduleIssue("EVENT","warning","Unknown load","2027-01-03",("event-a",)),
                ScheduleIssue("EVENT","warning","Unknown load","2027-01-03",("event-b",)))
    groups = warning_groups(warnings)
    assert len(groups) == 3
    assert groups[0] == warnings[:2]
    assert tuple(w for group in groups for w in group) == warnings
