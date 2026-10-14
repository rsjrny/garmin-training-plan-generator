from planning_browser_support import more_options
import sqlite3

import pytest
from playwright.sync_api import expect, sync_playwright

from garmin_data_hub.services import season_generation as generation, season_plans as plans
from garmin_data_hub.services.plan_persistence import get_active_plan_sha256
from garmin_data_hub.services.season_schedule import GenerationSettings
from test_activity_grid_browser import _test_database, _start_server, _stop_server, _free_loopback_port
from test_yearly_workflow_browser import capture, accept
from browser_test_support import wait_for_layout
from season_browser_logs import application_logs


@pytest.mark.browser
def test_reviewed_older_removals_unblock_full_year_without_losing_originals(tmp_path,browser_artifacts):
    db = _test_database(tmp_path)
    season = plans.create_season(db,plans.SeasonDraft("2027 removal review","2027-01-01","2027-12-31","America/New_York",
        plans.SeasonInputs(age=70,training_method="maffetone",starting_duration_seconds=16200)))
    with sqlite3.connect(db) as conn:
        conn.executemany("INSERT INTO planned_workout(scheduled_date,workout_name,description,planned_duration_s,structure_json) VALUES (?,?,'Original description',1800,'{}')",
            [(f"2027-01-0{n}",f"Older workout {n}") for n in (1,2,3)])
    old_preview = generation.preview_season(db,season.season_id,GenerationSettings(maf_adjustment=0,maf_confirmed=True))
    assert not old_preview.can_apply
    before = get_active_plan_sha256(db)
    process = _start_server(db,port := _free_loopback_port())
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport=dict(width=1440,height=1000))
            page.on("pageerror",lambda e:errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/seasons?season_id={season.season_id}",wait_until="networkidle")
            page.get_by_role("button",name="Finish setup",exact=True).click()
            page.get_by_label("MAF adjustment",exact=True).click()
            page.get_by_role("option",name="0 bpm",exact=True).click()
            page.get_by_label("I confirm the selected MAF adjustment.",exact=True).click()
            page.get_by_role("button",name="Save and review plan",exact=True).click()
            page.get_by_role("button",name="Review overlapping workouts",exact=True).click()
            page.get_by_role("button",name="Remove older workouts",exact=True).click()
            dialog = page.get_by_role("dialog")
            dialog.get_by_label("Older workouts to remove",exact=True).click()
            page.get_by_role("option",name="2027-01-01 · Older workout 1",exact=True).click()
            page.keyboard.press("Escape")
            dialog.get_by_role("button",name="Preview selected removals",exact=True).click()
            dialog = page.get_by_role("dialog").filter(has=page.get_by_text("Review workout removals",exact=True))
            dialog.get_by_text("Review workout removals",exact=True).wait_for()
            dialog.get_by_text("Older workout 1",exact=True).wait_for()
            expect(dialog.get_by_text("Older workout 2",exact=True)).to_have_count(0)
            capture(page,browser_artifacts/"selected_removal_desktop.png")
            page.set_viewport_size(dict(width=390,height=844))
            capture(page,browser_artifacts/"selected_removal_390.png")
            dialog.get_by_role("button",name="Keep these workouts",exact=True).click()
            assert get_active_plan_sha256(db)==before
            with sqlite3.connect(db) as conn:
                assert conn.execute("SELECT COUNT(*) FROM legacy_workout_removal_item").fetchone()[0]==0

            # Plan exposes the same explicit selection workflow, independent of
            # whether a yearly proposal's generation settings are complete.
            page.goto(f"http://127.0.0.1:{port}/plan?season_id={season.season_id}",wait_until="networkidle")
            more_options(page)
            page.get_by_role("button",name="Remove older workouts",exact=True).click()
            dialog = page.get_by_role("dialog")
            dialog.get_by_role("button",name="Select all eligible shown workouts",exact=True).click()
            dialog.get_by_role("button",name="Preview selected removals",exact=True).click()
            dialog = page.get_by_role("dialog").filter(has=page.get_by_text("Review workout removals",exact=True))
            dialog.get_by_text("Review workout removals",exact=True).wait_for()
            dialog.get_by_text("I reviewed these selected workouts and accept their removal from the calendar.",exact=True).click()
            with sqlite3.connect(db) as conn:
                conn.execute("UPDATE planned_workout SET description='Changed by another client' WHERE workout_name='Older workout 2'")
            changed = get_active_plan_sha256(db)
            dialog.get_by_role("button",name="Accept selected workout removals",exact=True).click()
            dialog.get_by_text("The schedule, protection, activity evidence or yearly settings changed. Review removal again.",exact=True).wait_for()
            capture(page,browser_artifacts/"stale_removal_390.png")
            assert get_active_plan_sha256(db)==changed
            dialog.get_by_role("button",name="Keep these workouts",exact=True).click()

            more_options(page)
            page.get_by_role("button",name="Remove older workouts",exact=True).click()
            dialog = page.get_by_role("dialog")
            dialog.get_by_role("button",name="Select all eligible shown workouts",exact=True).click()
            capture(page,browser_artifacts/"selection_390.png")
            page.set_viewport_size(dict(width=1440,height=1000))
            capture(page,browser_artifacts/"selection_desktop.png")
            dialog.get_by_role("button",name="Preview selected removals",exact=True).click()
            dialog = page.get_by_role("dialog").filter(has=page.get_by_text("Review workout removals",exact=True))
            dialog.get_by_text("Review workout removals",exact=True).wait_for()
            dialog.get_by_role("button",name="Accept selected workout removals",exact=True).click()
            dialog.get_by_text("Removal requires a reviewed selection and explicit acknowledgement.",exact=True).wait_for()
            with sqlite3.connect(db) as conn:
                originals = conn.execute("SELECT * FROM planned_workout ORDER BY planned_workout_id").fetchall()
            dialog.get_by_text("I reviewed these selected workouts and accept their removal from the calendar.",exact=True).click()
            dialog.get_by_role("button",name="Accept selected workout removals",exact=True).click()
            page.get_by_text("Selected older workouts removed from the calendar. Originals retained.",exact=True).wait_for()
            with sqlite3.connect(db) as conn:
                assert conn.execute("SELECT * FROM planned_workout ORDER BY planned_workout_id").fetchall()==originals
                assert conn.execute("SELECT COUNT(*) FROM legacy_workout_removal_item").fetchone()[0]==3
                assert conn.execute("SELECT COUNT(*) FROM active_planned_workout WHERE scheduled_date BETWEEN '2027-01-01' AND '2027-12-31'").fetchone()[0]==0
            assert plans.get_season(db,season.season_id)==season
            with pytest.raises(generation.StalePreviewError):
                generation.apply_season_preview(db,old_preview,approved_by="TEST",acknowledge_warnings=True)

            page.locator('[data-testid="yearly-workflow-status"]').get_by_text("latest proposal ready",exact=False).wait_for(timeout=15000)
            page.locator('[data-testid="review-yearly-proposal"]').wait_for(timeout=15000)
            page.locator('[data-testid="review-yearly-proposal"]').click()
            dialog = page.get_by_role("dialog")
            expect(dialog.get_by_role("button",name="Apply changes",exact=True)).to_be_enabled()
            page.set_viewport_size(dict(width=390,height=844))
            capture(page,browser_artifacts/"full_year_unblocked_390.png")
            accept(page)
            assert plans.get_season(db,season.season_id).start_date=="2027-01-01"
            page.reload(wait_until="networkidle")
            page.get_by_text("Removed older workouts — saved originals",exact=True).click()
            page.get_by_text("Older workout 1",exact=True).wait_for()
            wait_for_layout(page)
            page.get_by_text("Older workout 1",exact=True).scroll_into_view_if_needed()
            capture(page,browser_artifacts/"saved_originals_390.png")
            with sqlite3.connect(db) as conn:
                for original in originals:
                    assert conn.execute("SELECT * FROM planned_workout WHERE planned_workout_id=?",(original[0],)).fetchone()==original
            browser.close()
    finally:
        logs = _stop_server(process)
        (browser_artifacts/"browser.log").write_text(logs,encoding="utf-8")
    assert not errors
    assert "Traceback" not in application_logs(logs)
