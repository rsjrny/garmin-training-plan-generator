"""Desktop/phone explicit batch and manual matching, stale guards and reload."""
from dataclasses import replace
from datetime import date, timedelta
import json
import sqlite3

import pytest
from playwright.sync_api import expect, sync_playwright

from test_activity_grid_browser import _test_database, _start_server, _stop_server, _free_loopback_port
from test_usability_browser import capture
from season_browser_logs import application_logs
from revision_fixtures import _approve, _fitzgerald_candidate
from garmin_data_hub.services.plan_persistence import get_active_plan_sha256
from garmin_data_hub.services.workout_compliance import compliance_view


def browser_database(tmp_path):
    db = _test_database(tmp_path)
    today = date.today()
    base = _fitzgerald_candidate()
    canonical = replace(base,workouts=(replace(base.workouts[0],scheduled_date=today-timedelta(days=10),title="Prescribed easy run"),))
    _approve(db,canonical)
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM activity")
        for aid,day,kind,seconds,metres in [(1,today-timedelta(days=10),"running",3000,8000),(2,today-timedelta(days=6),"running",1800,5000),(3,today-timedelta(days=4),"cycling",7200,20000)]:
            conn.execute("INSERT INTO activity(activity_id,activity_type,start_time_gmt,elapsed_duration_seconds,distance_meters) VALUES(?,?,?,?,?)",
                (aid,kind,day.isoformat()+'T10:00:00Z',seconds,metres))
        for day,title,kind,seconds,metres in [(today-timedelta(days=7),"Long run moved next day","run",3600,10000),
            (today-timedelta(days=20),"Unrecorded easy run","run",1800,4000),
            (today-timedelta(days=12),"Rest day","rest",0,0),
            (today,"Today pending run","run",2400,6000)]:
            conn.execute("INSERT INTO planned_workout(scheduled_date,workout_name,planned_duration_s,planned_distance_m,structure_json) VALUES(?,?,?,?,?)",
                (day.isoformat(),title,seconds,metres,json.dumps(dict(workout=dict(sport=kind)))))
    return db


def acknowledge_and_save(page):
    dialog = page.get_by_role("dialog")
    ack = dialog.get_by_label("I reviewed the selected pairs and the confirm/reject decision.",exact=True)
    ack.click()
    expect(ack).to_be_checked()
    dialog.get_by_role("button",name="Save match decisions",exact=True).click()
    page.get_by_text("Match review saved.",exact=True).wait_for()


@pytest.mark.browser
@pytest.mark.parametrize("width,height",[(1440,1000),(390,844)])
def test_batch_then_moved_partial_match_reloads_without_schedule_changes(tmp_path,browser_artifacts,width,height):
    db = browser_database(tmp_path)
    before = get_active_plan_sha256(db)
    server = _start_server(db,port:=_free_loopback_port())
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport=dict(width=width,height=height))
            page.on("pageerror",lambda e:errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/compliance",wait_until="networkidle")
            expect(page.get_by_role("button",name="Review clear suggestions (1)",exact=True)).to_be_visible()
            expect(page.get_by_test_id("compliance-count-completed").get_by_text("0",exact=True)).to_be_visible()
            capture(page,browser_artifacts/"unreviewed.png")
            page.get_by_role("button",name="Review clear suggestions (1)",exact=True).click()
            expect(page.get_by_role("dialog").get_by_text("Review activity matches",exact=True)).to_be_visible()
            capture(page,browser_artifacts/"batch_review.png")
            acknowledge_and_save(page)
            expect(page.get_by_test_id("compliance-count-completed").get_by_text("1",exact=True)).to_be_visible()
            assert get_active_plan_sha256(db) == before
            day = (date.today()-timedelta(days=7)).isoformat()
            if width < 600:
                page.get_by_role("button",name=f"Inspect session {day} Long run moved next day",exact=True).click()
            else:
                page.get_by_role("button",name="Long run moved next day",exact=True).click()
            dialog = page.get_by_role("dialog")
            expect(dialog.get_by_label("Activity to associate",exact=True)).to_be_visible()
            dialog.get_by_role("button",name="Review this match",exact=True).click()
            dialog = page.get_by_role("dialog")
            expect(dialog.get_by_text("Time: 50.0% of planned amount",exact=True)).to_be_visible()
            expect(dialog.get_by_text("Distance: 50.0% of planned amount",exact=True)).to_be_visible()
            capture(page,browser_artifacts/"moved_partial_review.png")
            acknowledge_and_save(page)
            expect(page.get_by_test_id("compliance-count-partial").get_by_text("1",exact=True)).to_be_visible()
            expect(page.get_by_test_id("compliance-count-moved").get_by_text("1",exact=True)).to_be_visible()
            expect(page.get_by_test_id("compliance-count-missed").get_by_text("1",exact=True)).to_be_visible()
            expect(page.get_by_test_id("compliance-count-extra").get_by_text("1",exact=True)).to_be_visible()
            capture(page,browser_artifacts/"reviewed_summary.png")
            assert get_active_plan_sha256(db) == before
            page.reload(wait_until="networkidle")
            expect(page.get_by_test_id("compliance-count-moved").get_by_text("1",exact=True)).to_be_visible()
            view = compliance_view(db)
            assert view["data"]["totals"]["completed"] == view["data"]["totals"]["partial"] == 1
            assert len([m for m in view["snapshot"]["matches"] if m["status"] == "CONFIRMED"]) == 2
            page.get_by_text("Weekly recorded volume and variance",exact=True).scroll_into_view_if_needed()
            capture(page,browser_artifacts/"weekly.png")
            browser.close()
    finally:
        logs = _stop_server(server)
        (browser_artifacts/"browser.log").write_text(logs,encoding="utf8")
    assert not errors
    assert "Traceback" not in application_logs(logs)


@pytest.mark.browser
def test_stale_open_review_cannot_confirm_changed_activity(tmp_path,browser_artifacts):
    db = browser_database(tmp_path)
    before = get_active_plan_sha256(db)
    server = _start_server(db,port:=_free_loopback_port())
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport=dict(width=390,height=844))
            page.on("pageerror",lambda e:errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/compliance",wait_until="networkidle")
            page.get_by_role("button",name="Review clear suggestions (1)",exact=True).click()
            with sqlite3.connect(db) as conn:
                conn.execute("UPDATE activity SET elapsed_duration_seconds=1200 WHERE activity_id=1")
            dialog = page.get_by_role("dialog")
            ack = dialog.get_by_label("I reviewed the selected pairs and the confirm/reject decision.",exact=True)
            ack.click()
            expect(ack).to_be_checked()
            dialog.get_by_role("button",name="Save match decisions",exact=True).click()
            expect(dialog.get_by_text("Workouts, activities or match evidence changed.",exact=False)).to_be_visible()
            capture(page,browser_artifacts/"stale_review.png")
            with sqlite3.connect(db) as conn:
                assert conn.execute("SELECT COUNT(*) FROM workout_compliance_review").fetchone()[0] == 0
                assert conn.execute("SELECT COUNT(*) FROM activity_workout_match").fetchone()[0] == 0
            assert get_active_plan_sha256(db) == before
            browser.close()
    finally:
        logs = _stop_server(server)
        (browser_artifacts/"browser.log").write_text(logs,encoding="utf8")
    assert not errors
    assert "Traceback" not in application_logs(logs)
