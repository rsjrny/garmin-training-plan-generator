"""Desktop/phone score explanations, missing dates and process-restart preferences."""
from datetime import date, timedelta
import sqlite3

import pytest
from playwright.sync_api import expect, sync_playwright

from test_activity_grid_browser import _test_database, _start_server, _stop_server, _free_loopback_port
from test_usability_browser import capture
from test_recovery_readiness import health_database
from season_browser_logs import application_logs
from garmin_data_hub.services.plan_persistence import get_active_plan_sha256
from garmin_data_hub.services.recovery_readiness import recovery_assessment


def recovery_database(tmp_path):
    db = _test_database(tmp_path)
    seed_dir = tmp_path / "seed"
    seed_dir.mkdir()
    source = health_database(seed_dir,end=date.today())
    with sqlite3.connect(source) as origin, sqlite3.connect(db) as conn:
        for table in ("sleep","hrv","daily_summary","training_readiness"):
            conn.execute(origin.execute("SELECT sql FROM sqlite_master WHERE name=?",(table,)).fetchone()[0])
            rows = origin.execute(f"SELECT * FROM {table}").fetchall()
            conn.executemany(f"INSERT INTO {table} VALUES({','.join('?' for _ in rows[0])})",rows)
        for aid, local, duration, tss in origin.execute("SELECT activity_id,start_time_local,duration_seconds,training_stress_score FROM activity"):
            conn.execute("INSERT INTO activity(activity_id,activity_type,start_time_gmt,elapsed_duration_seconds,training_stress_score) VALUES(?,'running',?,?,?)",
                (aid+10000,local,duration,tss))
        conn.execute("INSERT INTO planned_workout(scheduled_date,workout_name,planned_duration_s) VALUES(?,'Long training run',6000)",(date.today().isoformat(),))
    return db


@pytest.mark.browser
@pytest.mark.parametrize("width,height", [(1440,1000),(390,844)])
def test_scores_drivers_dates_settings_and_dashboard_survive_process_restart(tmp_path,browser_artifacts,width,height):
    db = recovery_database(tmp_path)
    before = get_active_plan_sha256(db)
    expected = recovery_assessment(db)["assessment"]["scores"]
    server = _start_server(db,port:=_free_loopback_port())
    errors, logs = [], []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport=dict(width=width,height=height))
            page.on("pageerror",lambda e:errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/recovery",wait_until="networkidle")
            for key in ("recovery","readiness","energy"):
                expect(page.get_by_test_id("score-"+key)).to_have_text(f'{expected[key]["score"]} / 100')
            expect(page.get_by_text("What drives these scores",exact=True)).to_be_visible()
            capture(page,browser_artifacts/"scores.png")
            # Score drivers and Garmin comparisons retain their own dated values.
            page.get_by_text("Garmin comparison · same assessment date",exact=True).scroll_into_view_if_needed()
            expect(page.get_by_text("Garmin Training Readiness",exact=True)).to_be_visible()
            expect(page.get_by_text("Comparison only; these Garmin scores are not used in the app's scores.",exact=True)).to_be_visible()
            capture(page,browser_artifacts/"comparison.png")
            page.get_by_label("Assessment date",exact=True).fill((date.today()+timedelta(days=1)).isoformat())
            page.get_by_role("button",name="Refresh recovery",exact=True).click()
            expect(page.get_by_role("alert")).to_have_text("Recovery assessments cannot use a future date.")
            expect(page.get_by_test_id("score-recovery")).to_have_count(0)
            assert get_active_plan_sha256(db) == before
            page.get_by_label("Assessment date",exact=True).fill((date.today()-timedelta(days=1)).isoformat())
            page.get_by_role("button",name="Refresh recovery",exact=True).click()
            expect(page.get_by_text("Historical assessment · 1 days old.",exact=False)).to_be_visible()
            page.get_by_label("Assessment date",exact=True).fill(date.today().isoformat())
            page.get_by_role("button",name="Refresh recovery",exact=True).click()
            expect(page.get_by_test_id("score-recovery")).to_have_text("92 / 100")
            page.get_by_text("Sleep target preference",exact=True).click()
            page.get_by_label("Nightly sleep target (hours)",exact=True).fill("9")
            page.get_by_role("button",name="Save sleep target",exact=True).click()
            page.get_by_text("Recovery sleep target saved.",exact=True).wait_for()
            expect(page.get_by_test_id("score-energy")).to_have_text("82 / 100")
            capture(page,browser_artifacts/"preference.png")
            assert get_active_plan_sha256(db) == before
            page.close()
            logs.append(_stop_server(server))
            server = _start_server(db,port)
            page = browser.new_page(viewport=dict(width=width,height=height))
            page.on("pageerror",lambda e:errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/recovery",wait_until="networkidle")
            expect(page.get_by_test_id("score-energy")).to_have_text("82 / 100")
            page.get_by_text("Sleep target preference",exact=True).click()
            expect(page.get_by_label("Nightly sleep target (hours)",exact=True)).to_have_value("9")
            page.goto(f"http://127.0.0.1:{port}/",wait_until="networkidle")
            expect(page.get_by_test_id("score-energy")).to_have_text("82 / 100")
            page.get_by_role("link",name="Open Recovery & Readiness",exact=True).scroll_into_view_if_needed()
            capture(page,browser_artifacts/"dashboard.png")
            page.get_by_role("link",name="Open Recovery & Readiness",exact=True).click()
            expect(page.get_by_test_id("score-energy")).to_have_text("82 / 100")
            assert get_active_plan_sha256(db) == before
            browser.close()
    finally:
        logs.append(_stop_server(server))
        (browser_artifacts/"browser.log").write_text("\n".join(logs),encoding="utf8")
    assert not errors
    assert "Traceback" not in application_logs("\n".join(logs))


@pytest.mark.browser
def test_missing_and_stale_health_never_show_current_favorable_scores(tmp_path,browser_artifacts):
    db = _test_database(tmp_path)
    before = get_active_plan_sha256(db)
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE sleep(calendar_date TEXT PRIMARY KEY,sleep_time_seconds REAL)")
        conn.execute("INSERT INTO sleep VALUES(?,28800)",((date.today()-timedelta(days=10)).isoformat(),))
    server = _start_server(db,port:=_free_loopback_port())
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport=dict(width=390,height=844))
            page.on("pageerror",lambda e:errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/recovery",wait_until="networkidle")
            for key in ("recovery","readiness","energy"):
                expect(page.get_by_test_id("score-"+key)).to_have_text("Unavailable")
            expect(page.get_by_text("No current sleep/HRV/resting-HR record",exact=False)).to_be_visible()
            expect(page.get_by_test_id("recovery-guidance")).to_contain_text("Insufficient")
            capture(page,browser_artifacts/"missing.png")
            page.get_by_role("button",name="Use latest available day",exact=True).click()
            expect(page.get_by_label("Assessment date",exact=True)).to_have_value((date.today()-timedelta(days=10)).isoformat())
            expect(page.get_by_text("Historical assessment · 10 days old.",exact=False)).to_be_visible()
            expect(page.get_by_test_id("score-recovery")).to_have_text("Unavailable")
            page.get_by_text("Data sources and calculation policy",exact=True).click()
            page.get_by_text("Beat-to-beat RR analysis is not supported",exact=False).scroll_into_view_if_needed()
            capture(page,browser_artifacts/"sources.png")
            page.goto(f"http://127.0.0.1:{port}/",wait_until="networkidle")
            day = (date.today()-timedelta(days=10)).isoformat()
            page.get_by_role("link",name="View latest available data · " + day,exact=True).click()
            expect(page.get_by_label("Assessment date",exact=True)).to_have_value(day)
            expect(page.get_by_text("Historical assessment · 10 days old.",exact=False)).to_be_visible()
            assert get_active_plan_sha256(db) == before
            browser.close()
    finally:
        logs = _stop_server(server)
        (browser_artifacts/"browser.log").write_text(logs,encoding="utf8")
    assert not errors
    assert "Traceback" not in application_logs(logs)
