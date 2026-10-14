"""Marker editor, unchanged proposal, accepted timeline and daily workout UI."""
import pytest
from playwright.sync_api import expect, sync_playwright

from test_activity_grid_browser import _test_database, _start_server, _stop_server, _free_loopback_port
from test_usability_browser import select, capture, apply
from season_browser_logs import application_logs
from garmin_data_hub.services import season_plans as intent, season_generation as generation
from garmin_data_hub.services.season_schedule import GenerationSettings
from garmin_data_hub.plan_methodology.revision_repository import load_revision
from garmin_data_hub.services.yearly_plan_data import yearly_plan_snapshot


@pytest.mark.browser
@pytest.mark.parametrize("width,height", [(1440,1000), (390,844)])
def test_c_marker_keeps_half_marathon_workout_and_survives_reload(tmp_path, browser_artifacts, width, height):
    db = _test_database(tmp_path)
    season = intent.create_season(db, intent.SeasonDraft("Half marathon year", "2027-01-01", "2027-12-31", "America/New_York",
        intent.SeasonInputs(starting_duration_seconds=10800, lthr=170, baseline_distance_code="HM")))
    initial = generation.preview_season(db, season.season_id, GenerationSettings(lthr_confirmed=True))
    generation.apply_season_preview(db, initial, approved_by="test", acknowledge_warnings=True)
    server = _start_server(db, port := _free_loopback_port())
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport=dict(width=width, height=height))
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/seasons?season_id={season.season_id}&section=events", wait_until="networkidle")
            page.get_by_role("button", name="Add event", exact=True).click()
            dialog = page.get_by_role("dialog")
            dialog.get_by_label("Event name", exact=True).fill("Local 5K")
            dialog.get_by_label("Event date", exact=True).fill("2027-01-02")
            select(page, dialog, "Event distance", "5K")
            select(page, dialog, "Event priority", "C · Calendar marker")
            expect(dialog.get_by_text("C events are calendar markers only.", exact=False)).to_be_visible()
            dialog.get_by_text("Advanced event options", exact=True).click()
            expect(dialog.get_by_label("Taper days (optional)", exact=True)).to_be_disabled()
            expect(dialog.get_by_label("Recovery days (optional)", exact=True)).to_be_disabled()
            capture(page, browser_artifacts / "editor.png")
            dialog.get_by_role("button", name="Save event", exact=True).click()
            page.get_by_text("Event saved.", exact=True).wait_for()
            page.get_by_role("button", name="Review changes", exact=True).click()
            dialog = page.get_by_role("dialog")
            expect(dialog.get_by_test_id("change-counts")).to_have_text("0 changed · 0 added · 0 removed · 365 unchanged workouts")
            expect(dialog.get_by_text("C · Local 5K · 2027-01-02 · Calendar marker", exact=True)).to_be_visible()
            capture(page, browser_artifacts / "review.png")
            apply(page)
            current = intent.get_season(db, season.season_id)
            accepted = load_revision(db, current.current_revision_id).candidate
            assert accepted.workouts == initial.schedule.candidate.workouts
            assert yearly_plan_snapshot(db)["selections"][0]["applied_events"][0]["marker_only"]
            page.goto(f"http://127.0.0.1:{port}/plan?season_id={season.season_id}&view=workouts", wait_until="networkidle")
            marker = page.get_by_text("C · Local 5K · Calendar marker", exact=True)
            expect(marker).to_be_visible()
            card = marker.locator("..")
            expected = next(w for w in accepted.workouts if w.scheduled_date.isoformat() == "2027-01-02")
            expect(card.get_by_text(expected.title, exact=True)).to_be_visible()
            marker.scroll_into_view_if_needed()
            capture(page, browser_artifacts / "workout.png")
            page.reload(wait_until="networkidle")
            expect(page.get_by_text("C · Local 5K · Calendar marker", exact=True)).to_be_visible()
            page.goto(f"http://127.0.0.1:{port}/plan?season_id={season.season_id}", wait_until="networkidle")
            page.get_by_role("button", name="C · Local 5K · 2027-01-02 · Applied calendar marker", exact=True).click()
            expect(page.get_by_role("dialog").get_by_text("Calendar marker only.", exact=False)).to_be_visible()
            capture(page, browser_artifacts / "timeline.png")
            browser.close()
    finally:
        logs = _stop_server(server)
        (browser_artifacts / "browser.log").write_text(logs, encoding="utf8")
    assert not errors
    assert "Traceback" not in application_logs(logs)
