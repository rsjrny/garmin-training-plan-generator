"""Real browser fallback callback stays explicit and does not navigate at page load."""
from nicegui import ui
import pytest

from garmin_data_hub.ui_nicegui import race_browse as page
from ui_test_support import run_ui,wait_until
from garmin_data_hub.services.race_browse import race_bookmarks


def test_browser_fallback_only_opens_a_valid_explicitly_selected_address(monkeypatch,ui_database):
    opened = []
    monkeypatch.setattr(page,"open_race_browser",lambda url:opened.append(url) or True)
    async def scenario(user):
        await user.open("/browse")
        assert opened == []
        assert not next(iter(user.find(kind=ui.button,content="Open in browser").elements)).enabled
        next(iter(user.find("Open website address").elements)).value = "https://example.com/race"
        user.find("Browse website").click()
        await wait_until(lambda:any(e.tag=="iframe" for e in user.client.elements.values()))
        frame = next(e for e in user.client.elements.values() if e.tag == "iframe")
        assert frame._props["src"] == "https://example.com/race"
        assert "allow-top-navigation" not in frame._props["sandbox"]
        user.find("Open in browser").click()
        await wait_until(lambda:len(opened)==1)
        assert opened == ["https://example.com/race"]
        next(iter(user.find("Open website address").elements)).value = "javascript:alert(1)"
        user.find("Open in browser").click()
        await user.should_see("Use a public HTTPS website name",retries=100)
        assert len(opened)==1
    run_ui(ui_database,scenario)


@pytest.mark.parametrize("success",[True,False])
def test_known_frame_blocked_site_opens_browser_without_creating_failed_frame(monkeypatch,ui_database,success):
    opened = []
    monkeypatch.setattr(page,"open_race_browser",lambda url:opened.append(url) or success)
    async def scenario(user):
        await user.open("/browse")
        assert opened == []
        next(iter(user.find("Open website address").elements)).value = "https://www.runningintheusa.com/race/list"
        user.find("Browse website").click()
        await wait_until(lambda:len(opened)==1)
        assert opened == ["https://www.runningintheusa.com/race/list"]
        assert not any(e.tag=="iframe" for e in user.client.elements.values())
        await user.should_see("Running in the USA requires your browser")
        if success:
            await user.should_see("Browser requested.",retries=100)
        else:
            await user.should_see("Browser could not be opened.",retries=100)
        assert not next(iter(user.find("Reload start page").elements)).enabled
        user.find("Clear selection").click()
        await user.should_not_see("Running in the USA requires your browser")
    run_ui(ui_database,scenario)


def test_url_only_add_site_creates_tile_without_opening_site(ui_database):
    async def scenario(user):
        await user.open("/browse")
        user.find("Add your own site").click()
        next(iter(user.find("Website URL").elements)).value = "club.example.com/races"
        user.find("Save site tile").click()
        await user.should_see("Site tile saved.",retries=100)
        await user.should_see("club.example.com")
        assert race_bookmarks(ui_database)[-1] == dict(name="club.example.com",url="https://club.example.com/races")
        assert not any(e.tag=="iframe" for e in user.client.elements.values())
    run_ui(ui_database,scenario)
