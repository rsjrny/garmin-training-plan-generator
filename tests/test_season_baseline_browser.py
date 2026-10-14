"""Reviewed Y5b goal/cycle workflow, with desktop/phone evidence on synthetic data."""
from dataclasses import replace
import re

import pytest
from playwright.sync_api import expect, sync_playwright
from test_activity_grid_browser import _test_database, _start_server, _stop_server, _free_loopback_port
from test_usability_browser import select, capture, apply
from season_browser_logs import application_logs
from garmin_data_hub.services import season_plans as intent, season_generation as generation
from garmin_data_hub.services.season_schedule import GenerationSettings
from garmin_data_hub.services.plan_persistence import get_active_plan_sha256
from garmin_data_hub.plan_methodology.revision_repository import load_revision


@pytest.mark.browser
def test_goal_setup_change_clear_and_applied_phase_details(tmp_path,browser_artifacts):
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
            dialog.get_by_label("Planning year",exact=True).fill("2027")
            dialog.get_by_label("Starting weekly minutes (required for preview)",exact=True).fill("180")
            dialog.get_by_label("Measured running LTHR (required for 80/20)",exact=True).fill("170")
            select(page,dialog,"Always ready for","10 miler")
            dialog.get_by_label("I confirm this LTHR is a measured running threshold.",exact=True).click()
            capture(page,browser_artifacts/"goal_setup_desktop.png")
            page.set_viewport_size(dict(width=390,height=844))
            dialog.get_by_label("Always ready for",exact=True).scroll_into_view_if_needed()
            capture(page,browser_artifacts/"goal_setup_mobile.png")
            before=get_active_plan_sha256(db)
            dialog.get_by_role("button",name="Save and review plan",exact=True).click()
            dialog=page.get_by_role("dialog")
            expect(dialog.get_by_text("Baseline goal: 10 miler",exact=True)).to_be_visible(timeout=20000)
            assert get_active_plan_sha256(db)==before
            capture(page,browser_artifacts/"baseline_review_mobile.png")
            apply(page)
            s=intent.list_seasons(db)[0]
            candidate=load_revision(db,s.current_revision_id).candidate
            assert {w.phase for w in candidate.workouts}=={"BASE","BUILD","RECOVERY"}
            for goal,option in (("HM","Half marathon"),(None,"None / general fitness")):
                before=get_active_plan_sha256(db)
                page.goto(f"http://127.0.0.1:{port}/seasons?season_id={s.season_id}&section=settings&setup=1",wait_until="networkidle")
                dialog=page.get_by_role("dialog")
                expect(dialog.get_by_label("Always ready for",exact=True)).to_have_value("10 miler" if goal=="HM" else "Half marathon")
                select(page,dialog,"Always ready for",option)
                dialog.get_by_role("button",name="Save draft",exact=True).click()
                page.get_by_role("dialog").wait_for(state="hidden")
                page.get_by_role("button",name="Review changes",exact=True).wait_for(timeout=20000)
                assert get_active_plan_sha256(db)==before
                page.goto(f"http://127.0.0.1:{port}/seasons?season_id={s.season_id}&section=settings",wait_until="networkidle")
                page.reload(wait_until="networkidle")
                page.get_by_role("button",name="Review changes",exact=True).wait_for(timeout=20000)
                capture(page,browser_artifacts/("goal_pending_" + str(goal) + ".png"))
                page.get_by_role("button",name="Review changes",exact=True).click()
                apply(page)
                assert intent.get_season(db,s.season_id).inputs.baseline_distance_code==goal
            s=intent.get_season(db,s.season_id)
            intent.save_event(db,s.season_id,intent.EventDraft("Spring Half","2027-05-16"),expected_version=s.input_version)
            page.goto(f"http://127.0.0.1:{port}/plan?season_id={s.season_id}",wait_until="networkidle")
            page.get_by_role("button",name="Review changes",exact=True).click()
            apply(page)
            page.goto(f"http://127.0.0.1:{port}/?season_id={s.season_id}&year=2027",wait_until="networkidle")
            expect(page.get_by_text("Applied baseline goal: General fitness",exact=True)).to_be_visible()
            capture(page,browser_artifacts/"phases_mobile.png")
            peak=page.get_by_role("button",name=re.compile(r"^Peak ·"))
            expect(peak).to_have_count(1)
            peak.click()
            dialog=page.get_by_role("dialog")
            expect(dialog.get_by_text("Phase source: Event Preparation",exact=True)).to_be_visible()
            capture(page,browser_artifacts/"peak_detail_mobile.png")
            dialog.get_by_role("button",name="Close timeline details",exact=True).click()
            page.set_viewport_size(dict(width=1440,height=1000))
            capture(page,browser_artifacts/"phases_desktop.png")
            page.get_by_role("button",name=re.compile(r"^Transition ·")).click()
            dialog=page.get_by_role("dialog")
            expect(dialog.get_by_text("Phase source: Event Reconnection",exact=True)).to_be_visible()
            capture(page,browser_artifacts/"transition_detail_desktop.png")
            browser.close()
    finally:
        logs=_stop_server(server)
        (browser_artifacts/"browser.log").write_text(logs,encoding="utf8")
    assert not errors
    assert "Traceback" not in application_logs(logs)


@pytest.mark.browser
def test_maffetone_goal_short_calendar_constraints(tmp_path,browser_artifacts):
    db=_test_database(tmp_path)
    s=intent.create_season(db,intent.SeasonDraft("MAF baseline","2027-01-01","2027-01-14","America/New_York",
        intent.SeasonInputs(training_method="maffetone",starting_duration_seconds=3600,run_days_per_week=2)))
    server=_start_server(db,port:=_free_loopback_port())
    errors=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            page=browser.new_page(viewport=dict(width=390,height=844))
            page.on("pageerror",lambda e:errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/seasons?season_id={s.season_id}&section=settings&setup=1",wait_until="networkidle")
            dialog=page.get_by_role("dialog")
            select(page,dialog,"Always ready for","Half marathon")
            select(page,dialog,"MAF adjustment","0 bpm")
            dialog.get_by_label("I confirm the selected MAF adjustment.",exact=True).click()
            dialog.get_by_role("button",name="Save and review plan",exact=True).click()
            dialog=page.get_by_role("dialog")
            expect(dialog.get_by_text("Baseline goal: Half marathon",exact=True)).to_be_visible(timeout=20000)
            expect(dialog.get_by_text("Half marathon baseline goal is constrained",exact=False)).to_be_visible()
            capture(page,browser_artifacts/"maf_constraints_mobile.png")
            apply(page)
            s=intent.get_season(db,s.season_id)
            candidate=load_revision(db,s.current_revision_id).candidate
            assert not any(w.quality_flag for w in candidate.workouts)
            assert candidate.goal_snapshot["baseline_goal"]["distance_code"]=="HM"
            browser.close()
    finally:
        logs=_stop_server(server)
        (browser_artifacts/"browser.log").write_text(logs,encoding="utf8")
    assert not errors
    assert "Traceback" not in application_logs(logs)


@pytest.mark.browser
def test_race_free_year_timeline_keyboard_details_desktop_mobile(tmp_path,browser_artifacts):
    db=_test_database(tmp_path)
    s=intent.create_season(db,intent.SeasonDraft("Baseline year","2027-01-01","2027-12-31","America/New_York",
        intent.SeasonInputs(starting_duration_seconds=10800,lthr=170,baseline_distance_code="HM")))
    preview=generation.preview_season(db,s.season_id,GenerationSettings(lthr_confirmed=True))
    generation.apply_season_preview(db,preview,approved_by="TEST",acknowledge_warnings=True)
    before=get_active_plan_sha256(db)
    server=_start_server(db,port:=_free_loopback_port())
    errors=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            page=browser.new_page(viewport=dict(width=1440,height=1000))
            page.on("pageerror",lambda e:errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?season_id={s.season_id}&year=2027",wait_until="networkidle")
            page.locator('[data-testid="yearly-workflow-status"]').get_by_text("Up to date",exact=False).wait_for(timeout=20000)
            expect(page.get_by_text("Applied baseline goal: Half marathon",exact=True)).to_be_visible()
            page.locator('.d1-scroll').scroll_into_view_if_needed()
            capture(page,browser_artifacts/"baseline_year_desktop.png")
            page.set_viewport_size(dict(width=390,height=844))
            page.locator('.d1-scroll').scroll_into_view_if_needed()
            capture(page,browser_artifacts/"baseline_year_mobile.png")
            select(page,page,"Inspect timeline block or event","Recovery · 2027-02-15 to 2027-02-21")
            page.get_by_role("button",name="Show timeline details",exact=True).focus()
            page.keyboard.press("Enter")
            dialog=page.get_by_role("dialog")
            expect(dialog.get_by_text("Phase source: Baseline Cycle",exact=True)).to_be_visible()
            expect(dialog.get_by_text("Baseline cycle 1:",exact=False)).to_be_visible()
            capture(page,browser_artifacts/"baseline_recovery_detail_mobile.png")
            assert get_active_plan_sha256(db)==before
            browser.close()
    finally:
        logs=_stop_server(server)
        (browser_artifacts/"browser.log").write_text(logs,encoding="utf8")
    assert not errors
    assert "Traceback" not in application_logs(logs)
