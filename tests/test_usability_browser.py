"""Exercise the redesigned planning flows on synthetic local databases."""
from dataclasses import replace
from datetime import date, timedelta
import sqlite3

import pytest
from playwright.sync_api import expect, sync_playwright
from browser_test_support import wait_for_layout
from season_browser_logs import application_logs
from test_activity_grid_browser import _test_database, _start_server, _stop_server, _free_loopback_port
from garmin_data_hub.services import season_plans as intent, season_generation as generation
from garmin_data_hub.services.season_schedule import GenerationSettings
from garmin_data_hub.services.plan_persistence import get_active_plan_sha256


def select(page, scope, label, option):
    scope.get_by_label(label,exact=True).click()
    page.get_by_role("option",name=option,exact=True).click()


def capture(page, path):
    expect(page.locator(".q-notification")).to_have_count(0,timeout=15000)
    wait_for_layout(page)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    available_width = page.locator(".q-page-container").evaluate(
        "(element) => element.clientWidth - parseFloat(getComputedStyle(element).paddingLeft) - parseFloat(getComputedStyle(element).paddingRight)"
    )
    assert page.locator(".nicegui-content").bounding_box()["width"] >= available_width-48
    page.screenshot(path=str(path))


def apply(page):
    dialog=page.get_by_role("dialog")
    dialog.get_by_label("I reviewed the schedule and acknowledge all warnings.",exact=True).click()
    dialog.get_by_role("button",name="Apply changes",exact=True).click()
    page.get_by_text("Yearly plan applied.",exact=True).wait_for()


@pytest.mark.browser
def test_year_setup_apply_event_review_later_and_week_navigation(tmp_path,browser_artifacts):
    db=_test_database(tmp_path)
    server=_start_server(db,port:=_free_loopback_port())
    errors=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            page=browser.new_page(viewport=dict(width=1440,height=1000))
            page.on("pageerror",lambda e:errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/plan",wait_until="networkidle")
            page.get_by_role("link",name="New yearly plan",exact=True).click()
            dialog=page.get_by_role("dialog")
            select(page,dialog,"Plan dates","Calendar year")
            dialog.get_by_label("Planning year",exact=True).fill("2027")
            expect(dialog.get_by_label("Plan start",exact=True)).to_have_value("2027-01-01")
            expect(dialog.get_by_label("Plan end",exact=True)).to_have_value("2027-12-31")
            dialog.get_by_label("Starting weekly minutes (required for preview)",exact=True).fill("180")
            dialog.get_by_label("Measured running LTHR (required for 80/20)",exact=True).fill("170")
            dialog.get_by_role("button",name="Save and review plan",exact=True).click()
            dialog.get_by_text("Enter and confirm your measured running LTHR, or save a draft.",exact=True).wait_for()
            dialog.get_by_label("I confirm this LTHR is a measured running threshold.",exact=True).click()
            capture(page,browser_artifacts/"setup_desktop.png")
            page.set_viewport_size(dict(width=390,height=844))
            capture(page,browser_artifacts/"setup_mobile.png")
            dialog.get_by_role("button",name="Save and review plan",exact=True).click()
            page.get_by_role("dialog").get_by_text("Review yearly plan",exact=True).wait_for(timeout=20000)
            capture(page,browser_artifacts/"initial_review_mobile.png")
            apply(page)
            s=intent.list_seasons(db)[0]
            before=get_active_plan_sha256(db)
            page.get_by_role("button",name="Add event",exact=True).click()
            dialog=page.get_by_role("dialog")
            dialog.get_by_label("Event name",exact=True).fill("Spring half")
            dialog.get_by_label("Event date",exact=True).fill("2027-05-16")
            expect(dialog.get_by_label("Target finish time (HH:MM:SS)",exact=True)).not_to_be_visible()
            capture(page,browser_artifacts/"event_mobile.png")
            dialog.get_by_role("button",name="Save event",exact=True).click()
            page.get_by_role("button",name="Review changes",exact=True).wait_for(timeout=20000)
            page.get_by_role("button",name="Review changes",exact=True).click()
            dialog=page.get_by_role("dialog")
            expect(dialog.get_by_text("Before:",exact=True).first).to_be_visible()
            expect(dialog.get_by_text("After:",exact=True).first).to_be_visible()
            capture(page,browser_artifacts/"changes_mobile.png")
            page.set_viewport_size(dict(width=1440,height=1000))
            changed_table = dialog.get_by_role("table").filter(has=page.get_by_role("columnheader",name="Before",exact=True))
            expect(changed_table).to_contain_text("Changed")
            expect(changed_table).not_to_contain_text("outside_range")
            capture(page,browser_artifacts/"changes_desktop.png")
            dialog.get_by_role("button",name="Review later",exact=True).click()
            page.reload(wait_until="networkidle")
            assert get_active_plan_sha256(db)==before
            page.get_by_role("button",name="Review changes",exact=True).click()
            apply(page)
            assert get_active_plan_sha256(db)!=before
            page.goto(f"http://127.0.0.1:{port}/plan?season_id={s.season_id}&view=workouts",wait_until="networkidle")
            expect(page.get_by_text("This week",exact=True)).to_be_visible()
            first=page.locator('[data-testid="workout-week"]').inner_text()
            page.get_by_role("button",name="Next week",exact=True).click()
            expect(page.locator('[data-testid="workout-week"]')).not_to_have_text(first)
            page.get_by_role("button",name="Previous week",exact=True).click()
            expect(page.locator('[data-testid="workout-week"]')).to_have_text(first)
            page.locator('[data-testid="yearly-workflow-status"]').get_by_text("Up to date",exact=False).wait_for()
            page.get_by_role("button",name="Jump to today",exact=True).click()
            monday = date.today()-timedelta(days=date.today().weekday())
            sunday = monday+timedelta(days=6)
            expect(page.locator('[data-testid="workout-week"]')).to_have_text(f"{monday:%b %d} – {sunday:%b %d, %Y}")
            chosen_week = page.locator('[data-testid="workout-week"]').inner_text()
            fresh = intent.get_season(db,s.season_id)
            event = intent.list_events(db,s.season_id)[0]
            intent.save_event(db,s.season_id,replace(event.draft,name="Renamed spring half"),event_id=event.event_id,expected_version=fresh.input_version)
            page.get_by_role("button",name="Review changes",exact=True).wait_for(timeout=20000)
            expect(page.locator('[data-testid="workout-week"]')).to_have_text(chosen_week)
            page.set_viewport_size(dict(width=390,height=844))
            capture(page,browser_artifacts/"workouts_mobile.png")
            browser.close()
    finally:
        logs=_stop_server(server)
        (browser_artifacts/"browser.log").write_text(logs,encoding="utf8")
    assert not errors
    assert "Traceback" not in application_logs(logs)


@pytest.mark.browser
def test_finish_setup_contains_missing_load_and_maf_confirmation(tmp_path,browser_artifacts):
    db=_test_database(tmp_path)
    s=intent.create_season(db,intent.SeasonDraft("MAF year","2027-01-01","2027-12-31","America/New_York",intent.SeasonInputs(training_method="maffetone")))
    before=get_active_plan_sha256(db)
    server=_start_server(db,port:=_free_loopback_port())
    errors=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            page=browser.new_page(viewport=dict(width=390,height=844))
            page.on("pageerror",lambda e:errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/plan?season_id={s.season_id}",wait_until="networkidle")
            page.get_by_role("link",name="Finish setup",exact=True).click()
            dialog=page.get_by_role("dialog")
            expect(dialog.get_by_label("Starting weekly minutes (required for preview)",exact=True)).to_be_visible()
            expect(dialog.get_by_label("Running LTHR (optional for Maffetone)",exact=True)).not_to_be_visible()
            dialog.get_by_label("Starting weekly minutes (required for preview)",exact=True).fill("180")
            select(page,dialog,"MAF adjustment","0 bpm")
            dialog.get_by_label("I confirm the selected MAF adjustment.",exact=True).click()
            capture(page,browser_artifacts/"maf_setup_mobile.png")
            dialog.get_by_role("button",name="Save and review plan",exact=True).click()
            page.get_by_role("dialog").get_by_text("Review yearly plan",exact=True).wait_for(timeout=20000)
            assert get_active_plan_sha256(db)==before
            assert intent.get_season(db,s.season_id).inputs.starting_duration_seconds==10800
            apply(page)
            browser.close()
    finally:
        logs=_stop_server(server)
        (browser_artifacts/"browser.log").write_text(logs,encoding="utf8")
    assert not errors
    assert "Traceback" not in application_logs(logs)


@pytest.mark.browser
def test_event_pace_uses_miles_and_c_priority_disables_taper(tmp_path,browser_artifacts):
    from garmin_data_hub.ui_nicegui.data import save_interface_settings
    db=_test_database(tmp_path)
    s=intent.create_season(db,intent.SeasonDraft("2027 year","2027-01-01","2027-12-31","America/New_York"))
    save_interface_settings(db,{"unit_system":"Imperial"})
    server=_start_server(db,port:=_free_loopback_port())
    errors=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            page=browser.new_page(viewport=dict(width=1440,height=1000))
            page.on("pageerror",lambda e:errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/seasons?season_id={s.season_id}",wait_until="networkidle")
            page.get_by_role("button",name="Add event",exact=True).click()
            dialog=page.get_by_role("dialog")
            dialog.get_by_label("Event name",exact=True).fill("Training half")
            dialog.get_by_label("Event date",exact=True).fill("2027-05-16")
            select(page,dialog,"Event goal","Aim for a time")
            dialog.get_by_role("radio",name="Pace",exact=True).click()
            dialog.get_by_label("Target pace (MM:SS per mi)",exact=True).fill("10:00")
            select(page,dialog,"Event priority","C · Calendar marker")
            dialog.get_by_text("Advanced event options",exact=True).click()
            expect(dialog.get_by_label("Taper days (optional)",exact=True)).to_be_disabled()
            expect(dialog.get_by_label("Recovery days (optional)",exact=True)).to_be_disabled()
            dialog.get_by_role("button",name="Save event",exact=True).click()
            page.get_by_text("Event saved.",exact=True).wait_for()
            e=intent.list_events(db,s.season_id)[0]
            assert e.draft.target_speed_mps=="2.68224"
            assert e.draft.taper_days is None
            page.get_by_role("button",name=f"Edit event {e.event_id}",exact=True).click()
            dialog=page.get_by_role("dialog")
            expect(dialog.get_by_label("Target pace (MM:SS per mi)",exact=True)).to_have_value("10:00")
            dialog.get_by_role("button",name="Save event",exact=True).click()
            page.get_by_role("dialog").wait_for(state="hidden")
            assert intent.list_events(db,s.season_id)[0].draft.target_speed_mps=="2.68224"
            browser.close()
    finally:
        logs=_stop_server(server)
        (browser_artifacts/"browser.log").write_text(logs,encoding="utf8")
    assert not errors
    assert "Traceback" not in application_logs(logs)


@pytest.mark.browser
def test_dashboard_year_scope_coach_context_and_help(tmp_path,browser_artifacts):
    db = _test_database(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute("ALTER TABLE activity ADD COLUMN avg_power REAL")
        conn.execute("ALTER TABLE activity ADD COLUMN norm_power REAL")
    years = []
    for year,lthr in ((2027,170),(2028,175)):
        s = intent.create_season(db,intent.SeasonDraft(f"Year {year}",f"{year}-01-01",f"{year}-01-14","America/New_York",
            intent.SeasonInputs(starting_duration_seconds=10800,lthr=lthr)))
        preview = generation.preview_season(db,s.season_id,GenerationSettings(lthr_confirmed=True))
        generation.apply_season_preview(db,preview,approved_by="TEST",acknowledge_warnings=True)
        years.append(s)
    server = _start_server(db,port:=_free_loopback_port())
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport=dict(width=1440,height=1000))
            page.on("pageerror",lambda e:errors.append(str(e)))
            base = f"http://127.0.0.1:{port}"
            page.goto(base+"/",wait_until="networkidle")
            expect(page.get_by_text("This week · Year 2027",exact=True)).to_be_visible()
            assert f"season_id={years[0].season_id}" in page.url
            page.get_by_text("History and athlete metrics",exact=True).click()
            expect(page.get_by_text("Yearly LTHR",exact=True)).to_be_visible()
            expect(page.get_by_text("170",exact=True).first).to_be_visible()
            expect(page.get_by_text("Scheduled entries · selected plan",exact=True)).to_be_visible()
            page.get_by_label("Selected yearly plan",exact=True).click()
            page.get_by_role("option",name="Year 2028",exact=False).click()
            expect(page.get_by_text("This week · Year 2028",exact=True)).to_be_visible()
            assert f"season_id={years[1].season_id}" in page.url
            page.set_viewport_size(dict(width=390,height=844))
            capture(page,browser_artifacts/"dashboard_year_mobile.png")
            page.goto(base+f"/plan?season_id={years[1].season_id}",wait_until="networkidle")
            expect(page.get_by_label("Event date",exact=True)).not_to_be_visible()
            page.goto(base+"/coach",wait_until="networkidle")
            expect(page.get_by_text("This coach uses single-event settings.",exact=False)).to_be_visible()
            expect(page.get_by_role("link",name="Edit single-event settings",exact=True)).to_have_attribute("href","/plan?workflow=single")
            capture(page,browser_artifacts/"coach_context_mobile.png")
            page.goto(base+"/guide",wait_until="networkidle")
            expect(page.get_by_text("Create a yearly plan",exact=True)).to_be_visible()
            expect(page.get_by_text("Review and apply yearly changes",exact=True)).to_be_visible()
            expect(page.get_by_role("link",name="Open yearly events",exact=True)).to_have_attribute("href","/seasons?section=events")
            browser.close()
    finally:
        logs = _stop_server(server)
        (browser_artifacts/"browser.log").write_text(logs,encoding="utf8")
    assert not errors
    assert "Traceback" not in application_logs(logs)
