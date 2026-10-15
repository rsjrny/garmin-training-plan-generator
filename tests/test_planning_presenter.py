from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from dataclasses import replace
from revision_fixtures import _fitzgerald_candidate

from garmin_data_hub.ui_nicegui.planning_presenter import calendar_dates, change_counts, change_rows, pace_speed, pace_text, week_start, workout_counts


def test_replacements_are_counted_once_and_unchanged_rows_are_separate():
    workout = replace(_fitzgerald_candidate().workouts[0],workout_id="new",scheduled_date=date(2027,2,1),title="Easy run")
    diff = dict(changed=[dict(old_workout_id="old",new_workout_id="new",date="2027-02-01")],
                added_workout_ids=["new"],removed_workout_ids=["old"],preserved_workout_ids=["keep"],
                removed=[dict(workout_id="old",date="2027-02-01",title="Long run")],
                preserved=[dict(workout_id="keep",date="2027-01-01",title="Rest",reasons=["outside_range"])])
    assert change_counts(diff) == dict(changed=1,added=0,removed=0,unchanged=1)
    changed, unchanged = change_rows(diff,[workout])
    assert len(changed) == 1 and changed[0]["action"] == "Changed"
    assert changed[0]["before"] == "Long run"
    assert unchanged[0]["reason"] == "Outside the affected dates"


def test_pace_units_use_exact_mile_conversion():
    assert pace_speed(600,"Imperial") == "2.68224"
    assert pace_text(Decimal("2.68224"),"Imperial") == "10:00"
    assert pace_speed(360,"Metric") == "2.777777777777777777777777778"


def test_calendar_year_and_custom_week_defaults_do_not_exclude_leap_day():
    today = date(2026,10,7)
    assert calendar_dates(2028,today=today) == ("2028-01-01","2028-12-31")
    assert calendar_dates(2026,today=today,mode="Start today") == ("2026-10-07","2026-12-31")
    assert week_start(today,[dict(date="2027-01-01")]) == date(2026,12,28)
    assert week_start(today,[]) == date(2026,10,5)


def test_rest_rows_are_not_counted_as_training_sessions():
    assert workout_counts([dict(sport="RUNNING"),dict(sport="STRENGTH"),dict(sport="REST"),dict(workout="Rest"),dict(workout="Legacy session")]) == dict(running=1,strength=1,rest=2,other=1)


def test_default_year_is_consistent_across_entry_points():
    from garmin_data_hub.ui_nicegui.planning_presenter import default_yearly_plan
    def year(y,status="active"):
        return SimpleNamespace(start_date=f"{y}-01-01",end_date=f"{y}-12-31",status=status)
    future, nearest, archived = year(2028), year(2027), year(2026,"archived")
    assert default_yearly_plan([future,nearest,archived],today=date(2026,10,7)) is nearest
    assert default_yearly_plan([future,nearest,archived],today=date(2027,6,1)) is nearest
    assert default_yearly_plan([future,nearest],today=date(2029,1,1)) is future
    assert default_yearly_plan([],today=date(2026,10,7)) is None
