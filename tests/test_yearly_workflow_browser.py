from planning_browser_support import more_options
"""Y5a user lifecycle and responsive evidence; all servers use synthetic databases."""
from dataclasses import replace
from datetime import date
import sqlite3

import pytest
from playwright.sync_api import expect, sync_playwright

from browser_test_support import wait_for_layout
from season_browser_logs import application_logs
from test_activity_grid_browser import _test_database, _start_server, _stop_server, _free_loopback_port
from test_yearly_plan_browser import close_drawer
from garmin_data_hub.services import season_plans as intent, season_generation as generation
from garmin_data_hub.services.plan_persistence import get_active_plan_sha256
from garmin_data_hub.services.season_schedule import GenerationSettings
from test_plan_revision_persistence import _fitzgerald_candidate, _approve


def capture(page, path):
    wait_for_layout(page)
    page.wait_for_function("""() => [...document.querySelectorAll('.q-dialog__inner')]
        .filter(el => el.getBoundingClientRect().width > 0).every(el =>
            getComputedStyle(el).opacity === '1' &&
            (!el.firstElementChild || getComputedStyle(el.firstElementChild).opacity === '1') &&
            !el.getAnimations({subtree:true}).some(a => a.playState === 'running'))""")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.screenshot(path=str(path))


def accept(page):
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("I reviewed the schedule and acknowledge all warnings.", exact=True).click()
    dialog.get_by_role("button", name="Apply changes", exact=True).click()
    page.get_by_text("Yearly plan applied.", exact=True).wait_for()


@pytest.mark.browser
def test_blocked_legacy_preview_has_reachable_actions_grouped_warnings_and_honest_resolution(tmp_path, browser_artifacts):
    db = _test_database(tmp_path)
    season = intent.create_season(db,intent.SeasonDraft("2027 MAF year","2027-01-01","2027-12-31","America/New_York",
        intent.SeasonInputs(training_method="maffetone",starting_duration_seconds=16200)))
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO planned_workout(scheduled_date,workout_name,planned_duration_s,structure_json) VALUES ('2027-01-05','Original single-event workout',1800,'{}')")
    before = get_active_plan_sha256(db)
    process = _start_server(db,port := _free_loopback_port())
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport=dict(width=1440,height=1000))
            page.on("pageerror",lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/seasons?season_id={season.season_id}",wait_until="networkidle")
            page.get_by_role("button",name="Edit yearly settings",exact=True).click()
            dialog = page.get_by_role("dialog")
            capture(page,browser_artifacts / "entered_weekly_time_desktop.png")
            page.set_viewport_size(dict(width=390,height=844))
            dialog.get_by_label("Starting weekly minutes (required for preview)",exact=True).scroll_into_view_if_needed()
            capture(page,browser_artifacts / "entered_weekly_time_390.png")
            dialog.get_by_text("MAF uses your age",exact=False).scroll_into_view_if_needed()
            capture(page,browser_artifacts / "entered_weekly_time_guidance_390.png")
            dialog.get_by_role("button",name="Close yearly settings",exact=True).click()
            page.set_viewport_size(dict(width=1440,height=1000))
            page.get_by_role("button",name="Finish setup",exact=True).click()
            page.get_by_label("MAF adjustment",exact=True).click()
            page.get_by_role("option",name="0 bpm",exact=True).click()
            page.get_by_label("I confirm the selected MAF adjustment.",exact=True).click()
            page.get_by_role("button",name="Save and review plan",exact=True).click()
            dialog = page.get_by_role("dialog")
            dialog.get_by_text("Review yearly plan",exact=True).wait_for()
            expect(dialog.get_by_role("button",name="Apply changes",exact=True)).to_be_disabled()
            dialog.get_by_text("Apply unavailable:",exact=False).wait_for()
            dialog.get_by_text("occurrences · Maffetone sessions",exact=False).wait_for()
            assert dialog.get_by_text("Maffetone sessions normally",exact=False).count() == 1
            capture(page,browser_artifacts / "overlap_warnings_desktop.png")
            page.set_viewport_size(dict(width=390,height=844))
            capture(page,browser_artifacts / "overlap_warnings_390.png")
            dialog.locator(".q-card").first.evaluate("el => el.scrollTop = el.scrollHeight")
            expect(dialog.get_by_role("button",name="Apply changes",exact=True)).to_be_visible()
            capture(page,browser_artifacts / "reachable_blocked_actions_390.png")
            dialog.get_by_role("button",name="Review overlapping workouts",exact=True).click()
            dialog = page.get_by_role("dialog")
            dialog.get_by_text("Original single-event workout",exact=True).wait_for()
            dialog.get_by_text("This app cannot yet safely adopt or replace",exact=False).wait_for()
            expect(dialog.get_by_role("button",name="Link reviewed existing plan",exact=True)).to_have_count(0)
            capture(page,browser_artifacts / "legacy_overlap_390.png")
            page.set_viewport_size(dict(width=1440,height=1000))
            capture(page,browser_artifacts / "legacy_overlap_desktop.png")
            assert get_active_plan_sha256(db) == before
            assert intent.get_season(db,season.season_id) == season
            with sqlite3.connect(db) as conn:
                original = conn.execute("SELECT * FROM planned_workout WHERE workout_name='Original single-event workout'").fetchone()
            dialog.get_by_role("button",name="Save start 2027-01-06 and prepare proposal",exact=True).scroll_into_view_if_needed()
            capture(page,browser_artifacts / "separate_dates_choice_desktop.png")
            page.set_viewport_size(dict(width=390,height=844))
            button = dialog.get_by_role("button",name="Save start 2027-01-06 and prepare proposal",exact=True)
            button.scroll_into_view_if_needed()
            capture(page,browser_artifacts / "separate_dates_choice_390.png")
            # Another tab changing intent cannot be overwritten by this choice.
            intent.save_event(db,season.season_id,intent.EventDraft("Spring event","2027-05-16","5K","C"),expected_version=season.input_version)
            button.click()
            dialog.get_by_text("Existing workouts or yearly settings changed. Reopen overlap review for the latest dates.",exact=True).wait_for()
            assert intent.get_season(db,season.season_id).start_date == "2027-01-01"
            dialog.get_by_role("button",name="Close overlap review",exact=True).click()
            page.locator('[data-testid="review-yearly-proposal"]').wait_for(timeout=15000)
            page.locator('[data-testid="review-yearly-proposal"]').click()
            page.get_by_role("button",name="Review overlapping workouts",exact=True).click()
            page.get_by_role("button",name="Save start 2027-01-06 and prepare proposal",exact=True).click()
            page.get_by_text("Yearly start saved. Existing workouts retained; review the new proposal before applying.",exact=True).wait_for()
            assert intent.get_season(db,season.season_id).start_date == "2027-01-06"
            assert get_active_plan_sha256(db) == before
            page.locator('[data-testid="review-yearly-proposal"]').wait_for(timeout=15000)
            page.locator('[data-testid="review-yearly-proposal"]').click()
            expect(page.get_by_role("dialog").get_by_role("button",name="Apply changes",exact=True)).to_be_enabled()
            capture(page,browser_artifacts / "separate_dates_applicable_390.png")
            accept(page)
            with sqlite3.connect(db) as conn:
                assert conn.execute("SELECT * FROM planned_workout WHERE planned_workout_id=?",(original[0],)).fetchone() == original
            assert get_active_plan_sha256(db) != before
            browser.close()
    finally:
        logs = _stop_server(process)
        (browser_artifacts / "browser.log").write_text(logs,encoding="utf-8")
    assert not errors
    assert "Traceback" not in application_logs(logs)


@pytest.mark.browser
def test_overlap_can_explicitly_link_canonical_plan_then_review_separate_replacement(tmp_path, browser_artifacts):
    db = _test_database(tmp_path)
    candidate = _fitzgerald_candidate()
    candidate = replace(candidate,workouts=tuple(replace(w,scheduled_date=date(2027,4,1)) for w in candidate.workouts))
    _approve(db,candidate)
    season = intent.create_season(db,intent.SeasonDraft("2027 existing plan","2027-01-01","2027-12-31","America/New_York",
        intent.SeasonInputs(starting_duration_seconds=10800,lthr=170)))
    before = get_active_plan_sha256(db)
    process = _start_server(db,port := _free_loopback_port())
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport=dict(width=390,height=844))
            page.on("pageerror",lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/seasons?season_id={season.season_id}",wait_until="networkidle")
            page.get_by_role("button",name="Finish setup",exact=True).click()
            page.get_by_label("I confirm this LTHR is a measured running threshold.",exact=True).click()
            page.get_by_role("button",name="Save and review plan",exact=True).click()
            page.get_by_role("button",name="Review overlapping workouts",exact=True).click()
            dialog = page.get_by_role("dialog")
            capture(page,browser_artifacts / "canonical_overlap_390.png")
            dialog.get_by_role("button",name="Link reviewed existing plan",exact=True).click()
            dialog.get_by_text("Review and acknowledge the existing workouts before linking.",exact=True).wait_for()
            assert intent.get_season(db,season.season_id).plan_id is None
            dialog.get_by_text("I reviewed these workouts and want this year to own the existing plan.",exact=True).click()
            dialog.get_by_role("button",name="Link reviewed existing plan",exact=True).click()
            page.get_by_text("Existing plan linked. Workouts retained; review a fresh yearly replacement before applying changes.",exact=True).wait_for()
            assert intent.get_season(db,season.season_id).plan_id == candidate.plan_id
            assert get_active_plan_sha256(db) == before
            page.get_by_role("button",name="Finish setup",exact=True).click()
            page.get_by_label("I confirm this LTHR is a measured running threshold.",exact=True).click()
            page.get_by_role("button",name="Save and review plan",exact=True).click()
            dialog = page.get_by_role("dialog")
            dialog.get_by_text("Affected dates:",exact=False).wait_for()
            expect(dialog.get_by_role("button",name="Apply changes",exact=True)).to_be_enabled()
            capture(page,browser_artifacts / "linked_replacement_390.png")
            assert get_active_plan_sha256(db) == before
            accept(page)
            assert get_active_plan_sha256(db) != before
            browser.close()
    finally:
        logs = _stop_server(process)
        (browser_artifacts / "browser.log").write_text(logs,encoding="utf-8")
    assert not errors
    assert "Traceback" not in application_logs(logs)


@pytest.mark.browser
def test_create_race_free_year_event_crud_auto_review_and_shared_context(tmp_path, browser_artifacts):
    db = _test_database(tmp_path)
    before = get_active_plan_sha256(db)
    process = _start_server(db, port := _free_loopback_port())
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport=dict(width=1440, height=1000))
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/plan", wait_until="networkidle")
            page.get_by_text("Training Plan", exact=True).wait_for()
            page.get_by_role("link", name="New yearly plan", exact=True).click()
            dialog = page.get_by_role("dialog")
            dialog.get_by_label("Yearly plan name", exact=True).fill("2027 Yearly plan")
            dialog.get_by_label("Plan dates", exact=True).click()
            page.get_by_role("option", name="Custom dates", exact=True).click()
            dialog.get_by_label("Plan start", exact=True).fill("2027-01-01")
            dialog.get_by_label("Plan end", exact=True).fill("2027-12-31")
            dialog.get_by_label("Starting weekly minutes (required for preview)", exact=True).fill("180")
            dialog.get_by_label("Measured running LTHR (required for 80/20)", exact=True).fill("170")
            dialog.get_by_text("Events are optional.", exact=False).wait_for()
            expect(dialog.get_by_label("Always ready for", exact=True)).to_be_enabled()
            capture(page, browser_artifacts / "setup_desktop.png")
            page.set_viewport_size(dict(width=390, height=844))
            capture(page, browser_artifacts / "setup_390.png")
            dialog.get_by_label("Starting weekly minutes (required for preview)", exact=True).scroll_into_view_if_needed()
            capture(page, browser_artifacts / "setup_load_390.png")
            dialog.get_by_role("button", name="Save draft", exact=True).click()
            page.get_by_text("No events yet.", exact=True).wait_for()
            s = intent.list_seasons(db)[0]
            assert f"season_id={s.season_id}" in page.url
            page.locator('[data-testid="yearly-workflow-status"]').get_by_text("Settings required", exact=False).wait_for()
            capture(page, browser_artifacts / "initial_settings_390.png")
            assert get_active_plan_sha256(db) == before
            page.get_by_role("button", name="Finish setup", exact=True).click()
            page.get_by_role("dialog").get_by_label("I confirm this LTHR is a measured running threshold.", exact=True).click()
            page.get_by_role("dialog").get_by_role("button", name="Save and review plan", exact=True).click()
            page.get_by_text("Review yearly plan", exact=True).wait_for()
            capture(page, browser_artifacts / "initial_proposal_390.png")
            accept(page)
            page.locator('[data-testid="yearly-workflow-status"]').get_by_text("Up to date", exact=False).wait_for()
            initial = get_active_plan_sha256(db)
            # Adding a race prepares an update without another generation/confirmation step.
            page.get_by_role("button", name="Add event", exact=True).click()
            dialog = page.get_by_role("dialog")
            dialog.get_by_label("Event name", exact=True).fill("Spring half")
            dialog.get_by_label("Event date", exact=True).fill("2027-05-16")
            capture(page, browser_artifacts / "event_390.png")
            page.set_viewport_size(dict(width=1440, height=1000))
            capture(page, browser_artifacts / "event_desktop.png")
            dialog.get_by_role("button", name="Save event", exact=True).click()
            page.locator('[data-testid="review-yearly-proposal"]').wait_for(timeout=15000)
            assert get_active_plan_sha256(db) == initial
            page.locator('[data-testid="review-yearly-proposal"]').click()
            page.get_by_role("dialog").get_by_role("button", name="Review later", exact=True).click()
            page.reload(wait_until="networkidle")
            page.locator('[data-testid="review-yearly-proposal"]').wait_for(timeout=15000)
            assert get_active_plan_sha256(db) == initial
            # Plan reviews the same frozen proposal, not a separate single-event calendar.
            page.get_by_role("link", name="View yearly workouts", exact=True).click()
            assert f"season_id={s.season_id}" in page.url
            page.locator('[data-testid="review-yearly-proposal"]').click()
            page.get_by_text("Review yearly plan", exact=True).wait_for()
            capture(page, browser_artifacts / "proposal_desktop.png")
            page.set_viewport_size(dict(width=390, height=844))
            capture(page, browser_artifacts / "proposal_390.png")
            page.get_by_role("dialog").get_by_label("I reviewed the schedule and acknowledge all warnings.", exact=True).scroll_into_view_if_needed()
            capture(page, browser_artifacts / "acceptance_390.png")
            accept(page)
            page.locator('[data-testid="yearly-workflow-status"]').get_by_text("Up to date", exact=False).wait_for()
            more_options(page)
            page.get_by_role("link", name="View timeline on Dashboard", exact=True).click()
            assert f"season_id={s.season_id}" in page.url
            close_drawer(page)
            expect(page.get_by_role("button", name="A · Spring half · 2027-05-16 · Applied schedule", exact=True)).to_be_visible()
            page.locator('[data-testid="yearly-workflow-status"]').get_by_text("Up to date", exact=False).wait_for()
            capture(page, browser_artifacts / "dashboard_390.png")
            page.get_by_role("link", name="Yearly settings", exact=True).click()
            page.get_by_role("button", name="Events", exact=True).click()
            assert f"season_id={s.season_id}" in page.url
            close_drawer(page)
            e = intent.list_events(db, s.season_id)[0]
            page.get_by_role("button", name=f"Edit event {e.event_id}", exact=True).click()
            dialog = page.get_by_role("dialog")
            dialog.get_by_label("Event date", exact=True).fill("2027-06-06")
            dialog.get_by_role("button", name="Save event", exact=True).click()
            page.locator('[data-testid="review-yearly-proposal"]').wait_for(timeout=15000)
            page.locator('[data-testid="review-yearly-proposal"]').click()
            accept(page)
            moved = get_active_plan_sha256(db)
            page.get_by_role("button", name=f"Remove event {e.event_id}", exact=True).click()
            dialog = page.get_by_role("dialog")
            dialog.get_by_text("Completed and protected workouts remain.", exact=False).wait_for()
            dialog.get_by_role("button", name="Confirm removal", exact=True).click()
            page.locator('[data-testid="review-yearly-proposal"]').wait_for(timeout=15000)
            assert get_active_plan_sha256(db) == moved
            page.locator('[data-testid="review-yearly-proposal"]').click()
            accept(page)
            assert intent.list_events(db, s.season_id)[0].draft.status == "cancelled"
            assert len(generation.list_applications(db, s.season_id)) == 4
            page.get_by_role("link", name="View yearly workouts", exact=True).click()
            close_drawer(page)
            page.locator('[data-testid="yearly-workflow-status"]').get_by_text("Up to date", exact=False).wait_for()
            capture(page, browser_artifacts / "plan_390.png")
            page.set_viewport_size(dict(width=1440, height=1000))
            capture(page, browser_artifacts / "plan_desktop.png")
            page.evaluate("window.socket?.disconnect()")
            browser.close()
    finally:
        server = _stop_server(process)
        (browser_artifacts / "browser-server.txt").write_text(server, encoding="utf-8")
    assert not errors, errors
    assert "Traceback" not in application_logs(server) and "ERROR:" not in application_logs(server), server


@pytest.mark.browser
def test_concurrent_edit_stale_review_and_conflict_settings_states(tmp_path, browser_artifacts):
    db = _test_database(tmp_path)
    s = intent.create_season(db, intent.SeasonDraft("Concurrent year", "2027-01-01", "2027-12-31", "America/New_York",
        intent.SeasonInputs(starting_duration_seconds=10800, lthr=170)))
    initial = generation.preview_season(db, s.season_id, GenerationSettings(lthr_confirmed=True))
    generation.apply_season_preview(db, initial, approved_by="TEST", acknowledge_warnings=True)
    process = _start_server(db, port := _free_loopback_port())
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport=dict(width=390, height=844))
            other = browser.new_page(viewport=dict(width=1440, height=1000))
            for tab in (page, other):
                tab.on("pageerror", lambda e: errors.append(str(e)))
                tab.goto(f"http://127.0.0.1:{port}/seasons?season_id={s.season_id}", wait_until="networkidle")
                close_drawer(tab)
                tab.get_by_role("button", name="Add event", exact=True).click()
            for tab, name in ((page,"First save"), (other,"Stale save")):
                tab.get_by_role("dialog").get_by_label("Event name", exact=True).fill(name)
                tab.get_by_role("dialog").get_by_label("Event date", exact=True).fill("2027-05-16")
            page.get_by_role("dialog").get_by_role("button", name="Save event", exact=True).click()
            other.get_by_role("dialog").get_by_role("button", name="Save event", exact=True).click()
            other.get_by_role("dialog").get_by_text("Season changed", exact=False).wait_for()
            other.get_by_role("dialog").get_by_role("button", name="Close event editor", exact=True).click()
            page.locator('[data-testid="review-yearly-proposal"]').wait_for(timeout=15000)
            page.locator('[data-testid="review-yearly-proposal"]').click()
            page.get_by_role("dialog").get_by_text("Review yearly plan", exact=True).wait_for()
            active = get_active_plan_sha256(db)
            for n in range(5):
                fresh = intent.get_season(db, s.season_id)
                e = intent.list_events(db, s.season_id)[0]
                intent.save_event(db, s.season_id, replace(e.draft, name=f"Rapid edit {n}"), event_id=e.event_id, expected_version=fresh.input_version)
            dialog = page.get_by_role("dialog")
            dialog.get_by_label("I reviewed the schedule and acknowledge all warnings.", exact=True).click()
            dialog.get_by_role("button", name="Apply changes", exact=True).click()
            dialog.get_by_text("Season inputs, schedule, completion evidence, policy or local date changed.", exact=False).wait_for()
            assert get_active_plan_sha256(db) == active
            dialog.get_by_role("button", name="Review later", exact=True).click()
            page.reload(wait_until="networkidle")
            close_drawer(page)
            page.get_by_text("Rapid edit 4", exact=True).wait_for(timeout=15000)
            page.locator('[data-testid="review-yearly-proposal"]').wait_for()
            fresh = intent.get_season(db, s.season_id)
            intent.save_event(db, s.season_id, intent.EventDraft("Conflict", "2027-05-17"), expected_version=fresh.input_version)
            page.locator('[data-testid="yearly-workflow-status"]').get_by_text("Update blocked by conflicts", exact=False).wait_for(timeout=15000)
            page.locator('[data-testid="review-yearly-proposal"]').click()
            expect(page.get_by_role("dialog").get_by_role("button", name="Apply changes", exact=True)).to_be_disabled()
            capture(page, browser_artifacts / "conflict_390.png")
            page.get_by_role("button", name="Review later", exact=True).click()
            fresh = intent.get_season(db, s.season_id)
            intent.update_season(db, s.season_id, intent.SeasonDraft(fresh.name,fresh.start_date,fresh.end_date,fresh.timezone,
                replace(fresh.inputs,starting_duration_seconds=None)), expected_version=fresh.input_version)
            page.locator('[data-testid="yearly-workflow-status"]').get_by_text("Settings required", exact=False).wait_for(timeout=15000)
            expect(page.locator('[data-testid="review-yearly-proposal"]')).to_have_count(0)
            capture(page, browser_artifacts / "settings_required_390.png")
            assert get_active_plan_sha256(db) == active
            for tab in (page, other):
                tab.evaluate("window.socket?.disconnect()")
            browser.close()
    finally:
        server = _stop_server(process)
        (browser_artifacts / "browser-server.txt").write_text(server, encoding="utf-8")
    assert not errors, errors
    assert "Traceback" not in application_logs(server) and "ERROR:" not in application_logs(server), server


@pytest.mark.browser
def test_year_selection_navigation_reload_and_invalid_context(tmp_path, browser_artifacts):
    db = _test_database(tmp_path)
    seasons = [intent.create_season(db,intent.SeasonDraft(f"Year {y}",f"{y}-01-01",f"{y}-12-31","America/New_York")) for y in (2027,2028)]
    process = _start_server(db,port := _free_loopback_port())
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport=dict(width=390,height=844))
            page.on("pageerror",lambda e: errors.append(str(e)))
            base = f"http://127.0.0.1:{port}"
            page.goto(base+f"/plan?season_id={seasons[0].season_id}",wait_until="networkidle")
            page.get_by_label("Selected yearly plan",exact=True).click()
            page.get_by_role("option",name="Year 2028",exact=True).click()
            page.wait_for_url(f"**/plan?view=overview&season_id={seasons[1].season_id}")
            page.get_by_role("button",name="Navigation menu",exact=True).click()
            expect(page.get_by_role("link",name="Plan",exact=True)).to_have_attribute("href",f"/plan?season_id={seasons[1].season_id}")
            close_drawer(page)
            page.get_by_role("button",name="Events",exact=True).click()
            page.wait_for_url(f"**/seasons?section=events&season_id={seasons[1].season_id}")
            page.get_by_text("Year 2028",exact=True).wait_for()
            page.get_by_role("link",name="View timeline on Dashboard",exact=True).click()
            page.get_by_text("2028 overview",exact=False).wait_for()
            page.reload(wait_until="networkidle")
            page.get_by_text("2028 overview",exact=False).wait_for()
            expect(page.get_by_role("link",name="Review Plan",exact=True)).to_have_attribute("href",f"/plan?season_id={seasons[1].season_id}")
            page.get_by_label("Selected yearly plan",exact=True).scroll_into_view_if_needed()
            capture(page,browser_artifacts/"selection_390.png")
            page.goto(base+"/?season_id=missing",wait_until="networkidle")
            page.get_by_text("Selected yearly plan not found. Choose another plan.",exact=True).wait_for()
            page.goto(base+"/plan?season_id=missing",wait_until="networkidle")
            page.get_by_text("Yearly plan not found. Choose a plan from the list.",exact=True).wait_for()
            capture(page,browser_artifacts/"invalid_context_390.png")
            page.evaluate("window.socket?.disconnect()")
            browser.close()
    finally:
        server = _stop_server(process)
        (browser_artifacts/"browser-server.txt").write_text(server,encoding="utf-8")
    assert not errors,errors
    assert "Traceback" not in application_logs(server) and "ERROR:" not in application_logs(server),server
