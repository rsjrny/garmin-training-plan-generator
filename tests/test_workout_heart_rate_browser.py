"""Visible target sections and readable schedule columns on desktop and phone."""
import pytest
from playwright.sync_api import expect, sync_playwright

from test_plan_calendar_browser import calendar_database
from test_activity_grid_browser import _start_server, _stop_server, _free_loopback_port
from test_usability_browser import capture
from season_browser_logs import application_logs
from garmin_data_hub.services.plan_persistence import get_active_plan_sha256


@pytest.mark.browser
@pytest.mark.parametrize("width,height",[(1440,1000),(390,844)])
def test_heart_rate_in_calendar_sections_and_table(tmp_path,browser_artifacts,width,height):
    db,season = calendar_database(tmp_path)
    before = get_active_plan_sha256(db)
    server = _start_server(db,port:=_free_loopback_port())
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport=dict(width=width,height=height))
            page.on("pageerror",lambda e:errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/plan?season_id={season.season_id}&view=workouts",wait_until="networkidle")
            day = page.get_by_test_id("calendar-day-2028-02-28")
            expect(day.get_by_test_id("workout-heart-rate")).to_contain_text("80/20 zone 2: 138–152 bpm (secondary; speed primary)")
            day.get_by_text("Heart-rate sections",exact=True).click()
            expect(day).to_contain_text("1. Warm-up · 10 min · 80/20 zone 2: 138–152 bpm")
            expect(day).to_contain_text("2. Work · 30 min")
            expect(day).to_contain_text("3. Cool-down · 10 min")
            day.scroll_into_view_if_needed()
            capture(page,browser_artifacts/"heart_rate_sections.png")
            expect(page.get_by_test_id("calendar-day-2028-03-02").get_by_test_id("workout-heart-rate")).to_have_text("Heart rate: Not prescribed")
            page.get_by_role("radio",name="Workout table",exact=True).click()
            expect(page.get_by_role("columnheader",name="Heart Rate",exact=True)).to_have_count(1)
            cell = page.locator('.ag-cell[col-id="heart_rate"]').first
            cell.scroll_into_view_if_needed()
            expect(cell).to_be_in_viewport()
            expect(page.get_by_text("80/20 zone 2: 138–152 bpm (secondary; speed primary)",exact=True).first).to_be_visible()
            page.mouse.wheel(0,250)
            capture(page,browser_artifacts/"heart_rate_table.png")
            assert get_active_plan_sha256(db) == before
            browser.close()
    finally:
        logs = _stop_server(server)
        (browser_artifacts/"browser.log").write_text(logs,encoding="utf8")
    assert not errors
    assert "Traceback" not in application_logs(logs)
