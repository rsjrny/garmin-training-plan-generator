"""Real UI callbacks: recover from invalid preferences and reject a late result."""
from datetime import date, timedelta
import sqlite3
import threading

from nicegui import ui

from test_recovery_readiness_browser import recovery_database
from ui_test_support import run_ui, wait_until
from garmin_data_hub.ui_nicegui import recovery
from garmin_data_hub.services.recovery_readiness import SETTING_KEY, recovery_assessment


def test_recovery_page_repairs_invalid_preference_with_explicit_save(tmp_path):
    db = recovery_database(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO app_settings(key,value) VALUES(?,'invalid')",(SETTING_KEY,))
    async def scenario(user):
        await user.open("/recovery")
        await user.should_see("Saved recovery sleep target is invalid", retries=50)
        user.find("Sleep target preference").click()
        next(iter(user.find("Nightly sleep target (hours)").elements)).value = 9
        user.find("Save sleep target").click()
        await user.should_see("Recovery sleep target saved.",retries=100)
        await user.should_see("82 / 100")
    run_ui(db,scenario)
    assert recovery_assessment(db)["sleep_target_hours"] == 9


def test_late_assessment_does_not_render_after_date_selection_changes(tmp_path,monkeypatch):
    db = recovery_database(tmp_path)
    start, release = threading.Event(), threading.Event()
    blocking = {"value": False}
    real = recovery.recovery_assessment
    def delayed(*args,**kwargs):
        if blocking["value"] and kwargs.get("history_days") != 1:
            start.set()
            assert release.wait(10), "Test worker was not released"
        return real(*args,**kwargs)
    monkeypatch.setattr(recovery,"recovery_assessment",delayed)
    async def scenario(user):
        await user.open("/recovery")
        await user.should_see("92 / 100")
        blocking["value"] = True
        user.find("Refresh recovery").click()
        await wait_until(start.is_set)
        next(iter(user.find("Assessment date").elements)).value = (date.today()-timedelta(days=1)).isoformat()
        release.set()
        await user.should_see("Selections changed while loading",retries=100)
        await user.should_not_see("92 / 100")
        blocking["value"] = False
        user.find("Refresh recovery").click()
        await user.should_see("Historical assessment · 1 days old.",retries=100)
    try:
        run_ui(db,scenario)
    finally:
        release.set()
