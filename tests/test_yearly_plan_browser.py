from dataclasses import replace
import sqlite3
import json

import pytest
from playwright.sync_api import expect, sync_playwright

from browser_test_support import wait_for_layout
from season_browser_logs import application_logs
from test_activity_grid_browser import _start_server, _stop_server, _free_loopback_port
from test_yearly_plan import active
from garmin_data_hub.services import season_plans as intent, season_generation as generation
from test_season_generation import SETTINGS
from garmin_data_hub.db.queries import set_setting
from revision_fixtures import _database


def select(page, label, option):
    page.get_by_label(label, exact=True).click()
    page.get_by_role("option", name=option, exact=True).click()


def close_drawer(page):
    backdrop = page.locator(".q-drawer__backdrop")
    if backdrop.count() and backdrop.first.is_visible():
        backdrop.first.click(position=dict(x=350, y=400), force=True)


@pytest.mark.browser
def test_yearly_timeline_details_refresh_navigation_and_responsive(tmp_path, monkeypatch, browser_artifacts):
    db, s = active(tmp_path, monkeypatch, [intent.EventDraft("Spring half", "2027-05-16"),
        intent.EventDraft("Practice 5K", "2027-09-05", "5K", "C"), intent.EventDraft("Fall half", "2027-10-17", "HM", "B")])
    process = _start_server(db, port := _free_loopback_port())
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport=dict(width=1440, height=1000))
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle")
            page.get_by_text("Yearly training plan", exact=True).wait_for()
            select(page, "Timeline year", "2026")
            expect(page.locator(".d1-today")).to_have_count(1)
            select(page, "Timeline year", "2027")
            taper = page.get_by_role("button", name="Taper · 2027-05-06 to 2027-05-15", exact=True)
            taper.click()
            dialog = page.get_by_role("dialog")
            dialog.get_by_text("2027-05-06 to 2027-05-15 · inclusive dates", exact=True).wait_for()
            dialog.get_by_text("A · Spring half · 2027-05-16 (original applied context)", exact=True).wait_for()
            dialog.get_by_text("Unknown", exact=False).first.wait_for()
            wait_for_layout(page)
            page.screenshot(path=str(browser_artifacts / "details_desktop.png"))
            dialog.get_by_role("button", name="Close timeline details", exact=True).click()
            select(page, "Inspect timeline block or event", "Event · 2027-05-16 to 2027-05-16")
            page.get_by_role("button", name="Show timeline details", exact=True).focus()
            page.keyboard.press("Enter")
            dialog.get_by_text("2027-05-16 to 2027-05-16 · inclusive dates", exact=True).wait_for()
            dialog.get_by_role("link", name="Edit yearly settings", exact=True).click()
            page.get_by_text("Manage your training settings and optional events.", exact=True).wait_for()
            page.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle")
            select(page, "Timeline year", "2027")
            # Event intent changes trigger a cheap-pointer poll and coherent reread.
            e = intent.list_events(db, s.season_id)[0]
            intent.save_event(db, s.season_id, replace(e.draft, event_date="2027-06-06"),
                              event_id=e.event_id, expected_version=s.input_version)
            page.get_by_role("button", name="A · Spring half · 2027-06-06 · Event intent · not applied", exact=True).wait_for(timeout=12000)
            expect(page.get_by_role("button", name="A · Spring half · 2027-05-16 · Applied schedule", exact=True)).to_be_visible()
            page.get_by_text("Phase and event table", exact=True).click()
            page.locator(".d1-table").get_by_role("button", name="Base", exact=True).first.click()
            dialog.get_by_text("Base", exact=True).wait_for()
            dialog.get_by_role("button", name="Close timeline details", exact=True).click()
            page.get_by_text("Phase and event table", exact=True).click()
            page.evaluate("window.scrollTo(0,0)")
            wait_for_layout(page)
            page.screenshot(path=str(browser_artifacts / "desktop.png"))
            page.set_viewport_size(dict(width=390, height=844))
            close_drawer(page)
            wait_for_layout(page)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert page.locator(".d1-scroll").evaluate("el => el.scrollWidth > el.clientWidth")
            page.evaluate("window.scrollTo(0,0)")
            wait_for_layout(page)
            page.locator(".d1-scroll").scroll_into_view_if_needed()
            wait_for_layout(page)
            page.screenshot(path=str(browser_artifacts / "narrow.png"))
            select(page, "Inspect timeline block or event", "A · Spring half · 2027-06-06 · Event intent · not applied")
            page.get_by_role("button", name="Show timeline details", exact=True).click()
            dialog.get_by_text("2027-06-06 · A priority · Event intent · not applied", exact=True).wait_for()
            dialog.get_by_text("Distance: 13.11 mi", exact=True).wait_for()
            wait_for_layout(page)
            page.screenshot(path=str(browser_artifacts / "details_narrow.png"))
            dialog.get_by_role("button", name="Close timeline details", exact=True).click()
            page.get_by_role("button", name="Refresh yearly plan", exact=True).click()
            page.get_by_role("button", name="A · Spring half · 2027-06-06 · Event intent · not applied", exact=True).wait_for()
            with sqlite3.connect(db) as conn:
                set_setting(conn, "unit_system", "Metric")
            page.reload(wait_until="networkidle")
            close_drawer(page)
            select(page, "Timeline year", "2027")
            select(page, "Inspect timeline block or event", "A · Spring half · 2027-06-06 · Event intent · not applied")
            page.get_by_role("button", name="Show timeline details", exact=True).click()
            dialog.get_by_text("Distance: 21.10 km", exact=True).wait_for()
            dialog.get_by_role("button", name="Close timeline details", exact=True).click()
            preview = generation.preview_season(db, s.season_id, SETTINGS)
            assert preview.can_apply, preview.schedule.errors
            generation.apply_season_preview(db, preview, approved_by="test", acknowledge_warnings=True)
            page.get_by_role("button", name="A · Spring half · 2027-06-06 · Applied schedule", exact=True).wait_for(timeout=12000)
            expect(page.get_by_role("button", name="A · Spring half · 2027-05-16 · Applied schedule", exact=True)).to_have_count(0)
            expect(page.get_by_role("button", name="A · Spring half · 2027-06-06 · Event intent · not applied", exact=True)).to_have_count(0)
            page.evaluate("window.socket?.disconnect()")
            browser.close()
    finally:
        server = _stop_server(process)
        (browser_artifacts / "browser-server.txt").write_text(server, encoding="utf-8")
    assert not errors, errors
    assert "Traceback" not in application_logs(server) and "ERROR:" not in application_logs(server), server


@pytest.mark.browser
def test_empty_intent_legacy_and_corrupt_timeline_states(tmp_path, browser_artifacts):
    db = _database(tmp_path)
    process = _start_server(db, port := _free_loopback_port())
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport=dict(width=390, height=844))
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle")
            close_drawer(page)
            page.get_by_text("No yearly plan is available.", exact=False).wait_for()
            season = intent.create_season(db, intent.SeasonDraft("Intent only", "2028-01-01", "2028-12-31", "America/New_York", intent.SeasonInputs()))
            intent.save_event(db, season.season_id, intent.EventDraft("Leap race", "2028-02-29"), expected_version=season.input_version)
            page.get_by_text("Settings saved · no active training schedule.", exact=False).wait_for(timeout=12000)
            select(page, "Timeline year", "2028")
            page.get_by_role("button", name="A · Leap race · 2028-02-29 · Event intent · not applied", exact=True).wait_for()
            page.get_by_role("button", name="Show timeline details", exact=True).click()
            page.get_by_role("dialog").get_by_text("No applied workouts on these dates.", exact=False).wait_for()
            page.get_by_role("button", name="Close timeline details", exact=True).click()
            with sqlite3.connect(db) as conn:
                conn.execute("INSERT INTO planned_workout(scheduled_date,workout_name) VALUES('2028-01-01','Legacy')")
            page.get_by_role("button", name="Refresh yearly plan", exact=True).click()
            page.get_by_text("1 legacy/unmanaged schedule rows", exact=False).wait_for()
            wait_for_layout(page)
            page.locator(".d1-scroll").scroll_into_view_if_needed()
            wait_for_layout(page)
            page.screenshot(path=str(browser_artifacts / "intent_narrow.png"))
            # Broken active pointer cannot produce a plausible phase timeline.
            with sqlite3.connect(db) as conn:
                conn.execute("INSERT INTO training_plan(plan_id,current_revision_id,created_at_utc) VALUES('broken','missing','2026-10-05T00:00:00Z')")
            page.get_by_role("button", name="Refresh yearly plan", exact=True).click()
            page.get_by_text("Yearly plan unavailable:", exact=False).wait_for()
            expect(page.locator(".d1-timeline")).to_have_count(0)
            page.evaluate("window.socket?.disconnect()")
            browser.close()
    finally:
        server = _stop_server(process)
        (browser_artifacts / "browser-server.txt").write_text(server, encoding="utf-8")
    assert not errors, errors
    assert "Traceback" not in application_logs(server) and "ERROR:" not in application_logs(server), server


@pytest.mark.browser
def test_existing_saved_schedule_shows_phases_and_unavailable_metadata(tmp_path, browser_artifacts):
    db = _database(tmp_path)
    intent.create_season(db, intent.SeasonDraft("2026 season", "2026-01-01", "2026-12-31", "America/New_York"))
    with sqlite3.connect(db) as conn:
        conn.executemany("INSERT INTO planned_workout(scheduled_date,workout_name,structure_json) VALUES(?,?,?)", [
            ("2026-01-05", "Old workout", None),
            ("2026-07-06", "Easy run", json.dumps({"workout":{"phase":"Base"}})),
            ("2026-07-07", "Build run", json.dumps({"workout":{"phase":"Build"}})),
            ("2027-01-03", "Saved race", json.dumps({"workout":{"phase":"Race"}}))])
        conn.execute("UPDATE planned_workout SET planned_distance_m=5000 WHERE scheduled_date='2027-01-03'")
    process = _start_server(db, port := _free_loopback_port())
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport=dict(width=1440, height=1000))
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle")
            page.get_by_label("Selected yearly plan",exact=True).click()
            page.get_by_role("option",name="Saved workout schedule",exact=False).click()
            page.get_by_text("Existing saved workout schedule · older format.", exact=False).wait_for()
            select(page, "Timeline year", "2026")
            page.get_by_role("button", name="Base · 2026-07-06 to 2026-07-06", exact=True).wait_for()
            page.get_by_role("button", name="Phase Unavailable · 2026-01-05 to 2026-01-05", exact=True).wait_for()
            select(page, "Inspect timeline block or event", "Phase Unavailable · 2026-01-05 to 2026-01-05")
            page.get_by_role("button", name="Show timeline details", exact=True).click()
            page.get_by_role("dialog").get_by_text("Stored workouts do not supply one consistent phase", exact=False).wait_for()
            page.get_by_role("dialog").get_by_text("Saved older-format targets", exact=False).wait_for()
            wait_for_layout(page)
            page.screenshot(path=str(browser_artifacts / "legacy_details_desktop.png"))
            page.get_by_role("button", name="Close timeline details", exact=True).click()
            expect(page.get_by_role("dialog")).not_to_be_visible()
            page.evaluate("window.scrollTo(0,0)")
            wait_for_layout(page)
            page.screenshot(path=str(browser_artifacts / "legacy_desktop.png"))
            with sqlite3.connect(db) as conn:
                conn.execute("UPDATE planned_workout SET structure_json=? WHERE scheduled_date='2026-07-06'", (json.dumps({"workout":{"phase":"Peak"}}),))
            page.get_by_role("button", name="Peak · 2026-07-06 to 2026-07-06", exact=True).wait_for(timeout=12000)
            select(page, "Timeline year", "2027")
            page.get_by_role("button", name="? · Saved race · 2027-01-03 · Saved legacy schedule", exact=True).click()
            page.get_by_role("dialog").get_by_text("Distance: 3.11 mi (estimated)", exact=True).wait_for()
            page.get_by_role("button", name="Close timeline details", exact=True).click()
            expect(page.get_by_role("dialog")).not_to_be_visible()
            page.set_viewport_size(dict(width=390, height=844))
            close_drawer(page)
            wait_for_layout(page)
            page.locator(".d1-scroll").scroll_into_view_if_needed()
            page.screenshot(path=str(browser_artifacts / "legacy_narrow.png"))
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.evaluate("window.socket?.disconnect()")
            browser.close()
    finally:
        server = _stop_server(process)
        (browser_artifacts / "browser-server.txt").write_text(server, encoding="utf-8")
    assert not errors, errors
    assert "Traceback" not in application_logs(server) and "ERROR:" not in application_logs(server), server
