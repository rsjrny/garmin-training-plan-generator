"""Desktop/phone overview, scoped markers, reviewed completion and refresh."""
from dataclasses import replace
from datetime import date, timedelta
import sqlite3

import pytest
from playwright.sync_api import expect, sync_playwright

from test_activity_grid_browser import _test_database, _start_server, _stop_server, _free_loopback_port
from test_usability_browser import capture
from season_browser_logs import application_logs
from revision_fixtures import _approve, _fitzgerald_candidate
from garmin_data_hub.services import season_plans as intent
from garmin_data_hub.services.workout_compliance import compliance_view, review_pairs
from garmin_data_hub.services.plan_persistence import get_active_plan_sha256


def dashboard_database(tmp_path):
    db = _test_database(tmp_path)
    today = date.today()
    base = _fitzgerald_candidate()
    original = base.workouts[0]
    candidate = replace(base,workouts=(
        replace(original,workout_id="past-run",ordinal=0,scheduled_date=today-timedelta(days=2),title="Reviewed moved run"),
        replace(original,workout_id="today-run",ordinal=1,scheduled_date=today,title="Today's big picture long run"),
        replace(original,workout_id="future-run",ordinal=2,scheduled_date=today+timedelta(days=6),title="Final rolling day run")))
    _approve(db,candidate)
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM activity")
        conn.execute("INSERT INTO activity(activity_id,activity_type,start_time_gmt,elapsed_duration_seconds,distance_meters) VALUES(1,'running',?,3000,8000)",
            ((today-timedelta(days=1)).isoformat()+"T10:00:00Z",))
        conn.execute("CREATE TABLE sleep(calendar_date TEXT,sleep_time_seconds REAL)")
        conn.execute("INSERT INTO sleep VALUES(?,28800)",((today-timedelta(days=2)).isoformat(),))
    s = intent.create_season(db,intent.SeasonDraft("Dashboard year",f"{today.year}-01-01",f"{today.year}-12-31","America/New_York"))
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE season_plan SET plan_id=?,status='active' WHERE season_id=?",(candidate.plan_id,s.season_id))
    intent.save_event(db,s.season_id,intent.EventDraft("Fun local 5K",today.isoformat(),"5K","C"),expected_version=s.input_version)
    view = compliance_view(db,start=(today-timedelta(days=7)).isoformat(),end=today.isoformat(),plan_id=candidate.plan_id)
    key = next(w["key"] for w in view["data"]["workouts"] if w["workout_id"] == "past-run")
    review_pairs(db,view,[dict(workout_key=key,activity_id=1,status="CONFIRMED")],reviewer="TEST",reason="Reviewed moved run")
    return db,intent.get_season(db,s.season_id)


@pytest.mark.browser
@pytest.mark.parametrize("width,height",[(1440,1000),(390,844)])
def test_overview_scopes_dates_matches_markers_refresh_and_links(tmp_path,browser_artifacts,width,height):
    db,s = dashboard_database(tmp_path)
    before = get_active_plan_sha256(db)
    server = _start_server(db,port:=_free_loopback_port())
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport=dict(width=width,height=height))
            page.on("pageerror",lambda e:errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?season_id={s.season_id}",wait_until="networkidle")
            focus = page.get_by_test_id("dashboard-focus")
            expect(focus.get_by_text("Today / next 7 days",exact=True)).to_be_visible()
            expect(focus.get_by_text("Dashboard year ·",exact=False)).to_be_visible()
            today = page.get_by_test_id("focus-today")
            expect(today.get_by_text("Today's big picture long run",exact=True)).to_be_visible()
            expect(today.get_by_text("Today · 50 min",exact=True)).to_be_visible()
            expect(today.get_by_test_id("workout-heart-rate")).to_contain_text("138–152 bpm")
            today.get_by_text("Heart-rate sections",exact=True).click()
            expect(today).to_contain_text("1. Warm-up · 10 min")
            expect(today.get_by_text("C · marker only: Fun local 5K (5K)",exact=True)).to_be_visible()
            expect(today.get_by_role("link",name="Review today's matches",exact=True)).to_have_attribute("href",
                f'/compliance?start={date.today().isoformat()}&end={date.today().isoformat()}&season_id={s.season_id}')
            expect(focus.get_by_test_id("score-readiness")).to_have_text("Unavailable")
            expect(focus.get_by_text("No current sleep/HRV/resting-HR record.",exact=False)).to_be_visible()
            expect(page.get_by_test_id("focus-recent")).to_contain_text("1 completed · 0 partial · 1 moved")
            last = page.get_by_test_id("focus-day-"+(date.today()+timedelta(days=6)).isoformat())
            expect(last).to_contain_text("Final rolling day run")
            capture(page,browser_artifacts/"overview.png")
            focus.get_by_text("Recent session details",exact=True).click()
            expect(focus.get_by_text("Reviewed moved run",exact=True)).to_be_visible()
            expect(focus.get_by_text("Moved · completed · 50 min",exact=True)).to_be_visible()
            capture(page,browser_artifacts/"recent.png")
            last.scroll_into_view_if_needed()
            capture(page,browser_artifacts/"coming_days.png")
            # A synthetic source change becomes visible only after refreshing.
            with sqlite3.connect(db) as conn:
                conn.execute("""INSERT INTO season_workout_state(season_id,plan_id,workout_id,origin_revision_id,origin_workout_id,
                    explicitly_completed,version,editor,reason,updated_at_utc)
                    VALUES(?,?,'today-run',?,'today-run',1,1,'TEST','Marked done','2026-10-14T12:00:00Z')""",
                    (s.season_id,s.plan_id,s.current_revision_id))
            focus.get_by_role("button",name="Refresh training overview",exact=True).click()
            expect(today.get_by_text("Completed · 50 min",exact=True)).to_be_visible()
            assert get_active_plan_sha256(db) == before
            capture(page,browser_artifacts/"refreshed.png")
            focus.get_by_role("link",name="Review recent matches",exact=True).click()
            expect(page.get_by_label("Compliance start",exact=True)).to_have_value((date.today()-timedelta(days=7)).isoformat())
            expect(page.get_by_label("Compliance end",exact=True)).to_have_value((date.today()-timedelta(days=1)).isoformat())
            expect(page.get_by_label("Compliance schedule",exact=True)).to_have_value("Dashboard year")
            expect(page.get_by_test_id("compliance-count-moved")).to_contain_text("1")
            capture(page,browser_artifacts/"matching_link.png")
            browser.close()
    finally:
        logs = _stop_server(server)
        (browser_artifacts/"browser.log").write_text(logs,encoding="utf8")
    assert not errors
    assert "Traceback" not in application_logs(logs)
