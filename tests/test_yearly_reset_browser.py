"""One reviewed restart replaces older rows; desktop and phone workflows."""
from dataclasses import replace
from datetime import date
import json
import sqlite3

import pytest
from playwright.sync_api import sync_playwright, expect
from test_activity_grid_browser import _test_database, _start_server, _stop_server, _free_loopback_port
from test_usability_browser import capture
from garmin_data_hub.services import season_plans as plans, season_generation as generation
from garmin_data_hub.services.plan_persistence import get_active_plan_sha256
from season_browser_logs import application_logs


@pytest.mark.browser
@pytest.mark.parametrize("width",[1440,390])
def test_visible_redo_replaces_legacy_with_one_review_and_acceptance(tmp_path,browser_artifacts,width):
    db=_test_database(tmp_path)
    s=plans.create_season(db,plans.SeasonDraft("Fresh 2027","2027-01-01","2027-12-31","America/New_York",
        plans.SeasonInputs(starting_duration_seconds=10800,lthr=170,baseline_distance_code="HM")))
    with sqlite3.connect(db) as conn:
        wid=conn.execute("INSERT INTO planned_workout(scheduled_date,workout_name,structure_json) VALUES('2027-01-02','Obsolete long run','{}')").lastrowid
        conn.execute("INSERT INTO planned_workout(scheduled_date,workout_name,structure_json) VALUES('2027-01-03','Old locked run',?)",(json.dumps({"locked":True}),))
    before=get_active_plan_sha256(db)
    server=_start_server(db,port:=_free_loopback_port())
    errors=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            page=browser.new_page(viewport=dict(width=width,height=1000 if width==1440 else 844))
            page.on("pageerror",lambda e:errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/plan?season_id={s.season_id}",wait_until="networkidle")
            expect(page.get_by_role("button",name="Redo this year",exact=True)).to_be_visible()
            capture(page,browser_artifacts/"redo_button.png")
            page.get_by_role("button",name="Redo this year",exact=True).click()
            dialog=page.get_by_role("dialog")
            expect(dialog.get_by_label("Restart from",exact=True)).to_have_value("2027-01-01")
            dialog.get_by_label("Replace unfinished locked/manual workouts too",exact=True).click()
            dialog.get_by_label("I confirm this LTHR is a measured running threshold.",exact=True).click()
            capture(page,browser_artifacts/"restart_options.png")
            dialog.get_by_role("button",name="Review fresh year",exact=True).click()
            dialog=page.get_by_role("dialog")
            expect(dialog.get_by_text("Review yearly restart",exact=True)).to_be_visible(timeout=20000)
            expect(dialog.get_by_text("2 older workouts replaced",exact=False)).to_be_visible()
            capture(page,browser_artifacts/"restart_review.png")
            assert get_active_plan_sha256(db)==before
            dialog.get_by_role("button",name="Keep current plan",exact=True).click()
            assert get_active_plan_sha256(db)==before
            page.get_by_role("button",name="Redo this year",exact=True).click()
            dialog=page.get_by_role("dialog")
            dialog.get_by_label("Replace unfinished locked/manual workouts too",exact=True).click()
            dialog.get_by_label("I confirm this LTHR is a measured running threshold.",exact=True).click()
            dialog.get_by_role("button",name="Review fresh year",exact=True).click()
            dialog=page.get_by_role("dialog")
            dialog.get_by_label("I reviewed the replacements and warnings and want to redo this year.",exact=True).click()
            dialog.get_by_role("button",name="Apply yearly restart",exact=True).click()
            page.get_by_text("Yearly plan restarted.",exact=True).wait_for(timeout=20000)
            page.locator('[data-testid="yearly-workflow-status"]').get_by_text("Up to date",exact=False).wait_for(timeout=20000)
            capture(page,browser_artifacts/"fresh_year.png")
            assert get_active_plan_sha256(db)!=before
            with sqlite3.connect(db) as conn:
                assert conn.execute("SELECT COUNT(*) FROM active_planned_workout WHERE planned_workout_id=?",(wid,)).fetchone()[0]==0
                assert conn.execute("SELECT COUNT(*) FROM planned_workout WHERE planned_workout_id=?",(wid,)).fetchone()[0]==1
            page.reload(wait_until="networkidle")
            expect(page.get_by_text("Baseline goal: Half marathon",exact=True)).to_be_visible()
            browser.close()
    finally:
        logs=_stop_server(server)
        (browser_artifacts/"browser.log").write_text(logs,encoding="utf8")
    assert not errors
    assert "Traceback" not in application_logs(logs)


@pytest.mark.browser
def test_current_year_conflict_restart_preserves_past_without_resolution(tmp_path,browser_artifacts):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    today=datetime.now(ZoneInfo("America/New_York")).date()
    db=_test_database(tmp_path)
    s=plans.create_season(db,plans.SeasonDraft("Current year",f"{today.year}-01-01",f"{today.year}-12-31","America/New_York",
        plans.SeasonInputs(starting_duration_seconds=10800,lthr=170)))
    clock=generation._local_today
    try:
        generation._local_today=lambda tz:date(today.year-1,10,1)
        original=generation.preview_season(db,s.season_id,generation.GenerationSettings(lthr_confirmed=True))
        generation.apply_season_preview(db,original,approved_by="TEST",acknowledge_warnings=True)
    finally:
        generation._local_today=clock
    s=plans.get_season(db,s.season_id)
    with sqlite3.connect(db) as conn:
        past=conn.execute("INSERT INTO planned_workout(scheduled_date,workout_name,structure_json) VALUES(?,'Old history','{}')",(f"{today.year}-01-02",)).lastrowid
        future=conn.execute("INSERT INTO planned_workout(scheduled_date,workout_name,structure_json) VALUES(?,'Older future workout','{}')",((today+timedelta(days=2)).isoformat(),)).lastrowid
    plans.update_season(db,s.season_id,plans.SeasonDraft(s.name,s.start_date,s.end_date,s.timezone,replace(s.inputs,baseline_distance_code="HM")),expected_version=s.input_version)
    server=_start_server(db,port:=_free_loopback_port())
    errors=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            page=browser.new_page(viewport=dict(width=1440,height=1000))
            page.on("pageerror",lambda e:errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/plan?season_id={s.season_id}",wait_until="networkidle")
            page.get_by_role("button",name="Resolve conflicts",exact=True).wait_for(timeout=20000)
            capture(page,browser_artifacts/"current_year_conflict_redo_button.png")
            page.get_by_role("button",name="Redo this year",exact=True).click()
            dialog=page.get_by_role("dialog")
            expect(dialog.get_by_label("Restart from",exact=True)).to_have_value((today+timedelta(days=1)).isoformat())
            dialog.get_by_label("I confirm this LTHR is a measured running threshold.",exact=True).check()
            dialog.get_by_role("button",name="Review fresh year",exact=True).click()
            dialog=page.get_by_role("dialog")
            expect(dialog.get_by_role("button",name="Apply yearly restart",exact=True)).to_be_enabled(timeout=20000)
            capture(page,browser_artifacts/"current_year_restart_review.png")
            dialog.get_by_label("I reviewed the replacements and warnings and want to redo this year.",exact=True).click()
            dialog.get_by_role("button",name="Apply yearly restart",exact=True).click()
            page.get_by_text("Yearly plan restarted.",exact=True).wait_for(timeout=20000)
            page.locator('[data-testid="yearly-workflow-status"]').get_by_text("Up to date",exact=False).wait_for(timeout=20000)
            with sqlite3.connect(db) as conn:
                assert conn.execute("SELECT COUNT(*) FROM active_planned_workout WHERE planned_workout_id=?",(past,)).fetchone()[0]==1
                assert conn.execute("SELECT COUNT(*) FROM active_planned_workout WHERE planned_workout_id=?",(future,)).fetchone()[0]==0
            assert generation.list_applications(db,s.season_id)[-1]["mode"]=="FROM_TODAY"
            browser.close()
    finally:
        logs=_stop_server(server)
        (browser_artifacts/"browser.log").write_text(logs,encoding="utf8")
    assert not errors
    assert "Traceback" not in application_logs(logs)


@pytest.mark.browser
def test_maf_restart_reviews_unknown_event_time_and_can_clear_upcoming_events(tmp_path,browser_artifacts):
    from test_usability_browser import select
    db=_test_database(tmp_path)
    s=plans.create_season(db,plans.SeasonDraft("MAF year","2027-01-01","2027-12-31","America/New_York",
        plans.SeasonInputs(training_method="maffetone",starting_duration_seconds=10800)))
    plans.save_event(db,s.season_id,plans.EventDraft("January half","2027-01-02"),expected_version=s.input_version)
    server=_start_server(db,port:=_free_loopback_port())
    errors=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            page=browser.new_page(viewport=dict(width=390,height=844))
            page.on("pageerror",lambda e:errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/plan?season_id={s.season_id}",wait_until="networkidle")
            page.get_by_role("button",name="Redo this year",exact=True).click()
            dialog=page.get_by_role("dialog")
            select(page,dialog,"MAF adjustment","0 bpm")
            dialog.get_by_label("I confirm the selected MAF adjustment.",exact=True).click()
            dialog.get_by_role("button",name="Review fresh year",exact=True).click()
            dialog=page.get_by_role("dialog")
            dialog.get_by_text("Future workouts after restart",exact=True).click()
            expect(dialog.get_by_role("cell",name="Unknown",exact=True)).to_be_visible()
            dialog.get_by_role("cell",name="Unknown",exact=True).scroll_into_view_if_needed()
            capture(page,browser_artifacts/"unknown_event_duration.png")
            dialog.get_by_role("button",name="Back to restart options",exact=True).click()
            dialog=page.get_by_role("dialog")
            dialog.get_by_label("Clear upcoming events and rebuild a race-free year",exact=True).click()
            dialog.get_by_role("button",name="Review fresh year",exact=True).click()
            dialog=page.get_by_role("dialog")
            expect(dialog.get_by_text("Upcoming events will be cancelled",exact=False)).to_be_visible()
            capture(page,browser_artifacts/"clear_upcoming_events_review.png")
            dialog.get_by_label("I reviewed the replacements and warnings and want to redo this year.",exact=True).click()
            dialog.get_by_role("button",name="Apply yearly restart",exact=True).click()
            page.get_by_text("Yearly plan restarted.",exact=True).wait_for(timeout=20000)
            assert plans.list_events(db,s.season_id)[0].draft.status=="cancelled"
            browser.close()
    finally:
        logs=_stop_server(server)
        (browser_artifacts/"browser.log").write_text(logs,encoding="utf8")
    assert not errors
    assert "Traceback" not in application_logs(logs)
