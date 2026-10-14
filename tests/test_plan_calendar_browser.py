"""Calendar/table navigation and saved density labels on desktop and phone."""
from dataclasses import replace
from datetime import date
import sqlite3

import pytest
from playwright.sync_api import expect, sync_playwright

from test_activity_grid_browser import _test_database, _start_server, _stop_server, _free_loopback_port
from test_usability_browser import capture
from season_browser_logs import application_logs
from revision_fixtures import _approve, _fitzgerald_candidate
from garmin_data_hub.plan_methodology.domain import Sport, SegmentKind, LoadMode, MeasureRole
from garmin_data_hub.plan_methodology.segments import WorkoutSegment
from garmin_data_hub.services import season_plans as intent
from garmin_data_hub.services.plan_persistence import get_active_plan_sha256


def calendar_database(tmp_path):
    db = _test_database(tmp_path)
    base = _fitzgerald_candidate()
    original = base.workouts[0]
    specs = [
        ("2028-02-28","Controlled session",{"quality_flag":True}),
        ("2028-02-29","Second quality session",{"quality_flag":True}),
        ("2028-03-01","Strength maintenance",{"sport":Sport.STRENGTH,"family":"STRENGTH","segments":(WorkoutSegment(SegmentKind.WORK,LoadMode.DURATION,1800,duration_role=MeasureRole.AUTHORITATIVE),)}),
        ("2028-03-02","Rest",{"sport":Sport.REST,"family":"REST","segments":(WorkoutSegment(SegmentKind.NON_TRAINING,LoadMode.OPEN),)}),
        ("2028-03-03","Easy aerobic run",{}),
        ("2028-03-04","Long aerobic run",{"long_run_flag":True,"segments":(replace(original.segments[1],duration_seconds=6000,distance_metres=16093,distance_role=MeasureRole.ESTIMATED),)}),
        ("2028-03-04","Strength after run",{"sport":Sport.STRENGTH,"family":"STRENGTH","segments":(WorkoutSegment(SegmentKind.WORK,LoadMode.DURATION,1200,duration_role=MeasureRole.AUTHORITATIVE),)}),
        ("2028-03-05","Applied race session",{"event_flag":True}),
    ]
    workouts = tuple(replace(original,workout_id=f"calendar-{i}",ordinal=i,scheduled_date=date.fromisoformat(day),title=title,phase="BUILD",**kwargs) for i,(day,title,kwargs) in enumerate(specs))
    _approve(db,replace(base,workouts=workouts))
    s = intent.create_season(db,intent.SeasonDraft("Calendar year","2028-01-01","2028-12-31","America/New_York"))
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE season_plan SET plan_id=?,status='active' WHERE season_id=?",(base.plan_id,s.season_id))
    intent.save_event(db,s.season_id,intent.EventDraft("Fun 5K","2028-03-04","5K","C"),expected_version=s.input_version)
    current = intent.get_season(db,s.season_id)
    intent.save_event(db,s.season_id,intent.EventDraft("Big race","2028-03-05","HM","A"),expected_version=current.input_version)
    return db,s


@pytest.mark.browser
@pytest.mark.parametrize("width,height",[(1440,1000),(390,844)])
def test_calendar_labels_leap_week_navigation_table_and_c_marker_preserve_schedule(tmp_path,browser_artifacts,width,height):
    db,s = calendar_database(tmp_path)
    before = get_active_plan_sha256(db)
    server = _start_server(db,port:=_free_loopback_port())
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport=dict(width=width,height=height))
            page.on("pageerror",lambda e:errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/plan?season_id={s.season_id}&view=workouts",wait_until="networkidle")
            calendar = page.get_by_test_id("plan-calendar")
            expect(calendar).to_be_visible()
            expect(page.get_by_test_id("workout-week")).to_have_text("Feb 28 – Mar 05, 2028")
            expect(page.get_by_test_id("calendar-week-summary")).to_contain_text("6 training days · 7 sessions · 1 saved rest days")
            expect(page.get_by_test_id("calendar-spacing")).to_contain_text("Mon Feb 28 → Tue Feb 29")
            expect(page.get_by_test_id("calendar-day-2028-03-01").get_by_text("Strength",exact=True)).to_be_visible()
            long = page.get_by_test_id("calendar-day-2028-03-04")
            expect(long.get_by_text("Long run",exact=True)).to_be_visible()
            expect(long.get_by_text("C · Fun 5K · Calendar marker",exact=True)).to_be_visible()
            expect(long.get_by_text("100 min · 10 mi",exact=False)).to_be_visible()
            expect(page.get_by_test_id("calendar-day-2028-03-05")).to_contain_text("A · Big race · Saved event")
            calendar.scroll_into_view_if_needed()
            capture(page,browser_artifacts/"calendar.png")
            long.scroll_into_view_if_needed()
            capture(page,browser_artifacts/"long_c_marker.png")
            page.get_by_role("button",name="Next week",exact=True).click()
            expect(page.get_by_test_id("workout-week")).to_have_text("Mar 06 – Mar 12, 2028")
            expect(calendar).to_contain_text("No workout scheduled")
            page.get_by_role("button",name="Previous week",exact=True).click()
            expect(page.get_by_test_id("workout-week")).to_have_text("Feb 28 – Mar 05, 2028")
            page.get_by_role("radio",name="Workout table",exact=True).click()
            expect(calendar).to_have_count(0)
            expect(page.get_by_text("Detailed schedule",exact=True)).to_be_visible()
            capture(page,browser_artifacts/"table.png")
            page.get_by_role("radio",name="Week calendar",exact=True).click()
            expect(page.get_by_test_id("workout-week")).to_have_text("Feb 28 – Mar 05, 2028")
            page.get_by_label("Week containing",exact=True).fill("2028-03-19")
            page.get_by_role("button",name="Go to week",exact=True).click()
            expect(page.get_by_test_id("workout-week")).to_have_text("Mar 13 – Mar 19, 2028")
            page.get_by_role("button",name="Jump to today",exact=True).click()
            from datetime import timedelta
            monday = date.today()-timedelta(days=date.today().weekday())
            expect(page.get_by_test_id("workout-week")).to_have_text(f"{monday:%b %d} – {monday+timedelta(days=6):%b %d, %Y}")
            assert get_active_plan_sha256(db) == before
            browser.close()
    finally:
        logs = _stop_server(server)
        (browser_artifacts/"browser.log").write_text(logs,encoding="utf8")
    assert not errors
    assert "Traceback" not in application_logs(logs)
