"""URL handling and local bookmark changes without plan or network side effects."""
import sqlite3

import pytest

from garmin_data_hub.services import race_browse as browse
from garmin_data_hub.services.plan_persistence import get_active_plan_sha256
from revision_fixtures import _database


@pytest.mark.parametrize("url",[
    "javascript:alert(1)","data:text/html,test","file:///C:/private",
    "http://example.com","https://localhost","https://test.local",
    "https://127.0.0.1","https://[::1]","https://0x7f.0x0.0x0.0x1",
    "https://0177.0.0.1","https://2130706433","https://example.com:8091",
    "https://user:secret@example.com","https://example.com\\@localhost",
    "https://exa mple.com","https://example.com/a\nb",None,
])
def test_unsafe_or_local_address_rejected_before_any_open(url,monkeypatch):
    called = []
    monkeypatch.setattr(browse.webbrowser,"open",lambda *args,**kwargs:called.append(args))
    with pytest.raises(browse.BrowseError):
        browse.open_race_browser(url)
    assert not called


def test_public_address_normalizes_host_and_keeps_race_filter_query(monkeypatch):
    url = browse.website_address("WWW.RunningInTheUSA.com/race/list?state=NY#events")
    assert url == "https://www.runningintheusa.com/race/list?state=NY#events"
    opened = []
    monkeypatch.setattr(browse.webbrowser,"open",lambda url,**kwargs:opened.append((url,kwargs)) or True)
    assert browse.open_race_browser(url)
    assert opened == [(url,{"new":2})]


def test_opening_defaults_is_read_only_and_bookmark_changes_only_touch_settings(tmp_path):
    db = _database(tmp_path)
    before = get_active_plan_sha256(db)
    with sqlite3.connect(db) as conn:
        dump = tuple(conn.iterdump())
    assert len(browse.race_bookmarks(db)) == 2
    with sqlite3.connect(db) as conn:
        assert tuple(conn.iterdump()) == dump
    rows = browse.save_race_bookmark(db,"My race","races.example.com/fun")
    assert len(rows)==3
    assert browse.save_race_bookmark(db,"Renamed race","races.example.com/fun")[-1]["name"]=="Renamed race"
    assert len(browse.race_bookmarks(db))==3
    browse.remove_race_bookmark(db,"races.example.com/fun")
    assert len(browse.race_bookmarks(db))==2
    assert get_active_plan_sha256(db)==before


def test_malformed_saved_bookmarks_require_explicit_restore(tmp_path):
    db = _database(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO app_settings(key,value) VALUES(?,'bad json')",(browse.SETTING_KEY,))
    with pytest.raises(browse.BrowseError,match="unreadable"):
        browse.race_bookmarks(db)
    with pytest.raises(browse.BrowseError):
        browse.save_race_bookmark(db,"A race","https://example.com/")
    assert len(browse.restore_race_bookmarks(db))==2
    assert len(browse.race_bookmarks(db))==2


def test_known_blocked_site_classification_is_exact_and_all_paths_use_browser():
    assert browse.browser_only_site("https://www.runningintheusa.com/race/list")
    assert browse.browser_only_site("runningintheusa.com/race/find-by-state/")
    assert not browse.browser_only_site("https://runningintheusa.com.example.org/race/list")
    assert not browse.browser_only_site("https://race.example.org/")


@pytest.mark.parametrize("name,url",[
    ("RunSignup","https://runsignup.com/races"),("UltraSignup","https://ultrasignup.com/events/search.aspx"),
    ("ACTIVE","https://www.active.com/running/"),
])
def test_verified_common_site_framing_policy_uses_exact_host(name,url):
    assert browse.browser_only_site_name(url)==name
    assert not browse.browser_only_site(url.replace(".com/",".com.example.org/"))
