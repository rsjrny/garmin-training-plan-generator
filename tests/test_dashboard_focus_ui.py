"""A failed asynchronous overview is visible and can be refreshed successfully."""
from garmin_data_hub.ui_nicegui import dashboard_focus as panel
from garmin_data_hub.services.dashboard_focus import dashboard_focus
from garmin_data_hub.services.workout_compliance import MatchReviewError
from ui_test_support import run_ui


def test_failed_overview_refresh_retries_without_stale_content(monkeypatch,ui_database):
    failing = {"value":True}
    def read(*args,**kwargs):
        if failing["value"]:
            raise MatchReviewError("Refresh needed: match evidence changed.")
        return dashboard_focus(*args,**kwargs)
    monkeypatch.setattr(panel,"dashboard_focus",read)
    async def scenario(user):
        await user.open("/")
        await user.should_see("Refresh needed: match evidence changed.",retries=100)
        failing["value"] = False
        user.find("Refresh training overview").click()
        await user.should_see("Coming days · planned sessions",retries=100)
        await user.should_not_see("Refresh needed: match evidence changed.")
        await user.should_see("No saved session")
    run_ui(ui_database,scenario)
