"""Embedded and blocked external-site fixtures; no real third-party browsing."""
import sqlite3
import json

import pytest
from playwright.sync_api import expect,sync_playwright

from test_activity_grid_browser import _test_database,_start_server,_stop_server,_free_loopback_port
from test_usability_browser import capture
from season_browser_logs import application_logs
from garmin_data_hub.services.plan_persistence import get_active_plan_sha256
from garmin_data_hub.services.race_browse import race_bookmarks
from garmin_data_hub.services import season_plans as intent
import test_activity_grid_browser as server_harness


@pytest.mark.browser
@pytest.mark.parametrize("width,height",[(1440,1000),(390,844)])
def test_browse_stays_local_until_selected_embeds_and_persists_bookmarks(tmp_path,browser_artifacts,width,height):
    db = _test_database(tmp_path)
    year = intent.create_season(db,intent.SeasonDraft("Research year","2027-01-01","2027-12-31","America/New_York"))
    before = get_active_plan_sha256(db)
    server = _start_server(db,port:=_free_loopback_port())
    errors,requests = [],[]
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport=dict(width=width,height=height))
            page.on("pageerror",lambda e:errors.append(str(e)))
            def directory(route):
                requests.append(route.request.url)
                route.fulfill(status=200,content_type="text/html",body="<h1>Synthetic race directory</h1><p>Upcoming races and state search</p>")
            page.route("https://races.example.org/**",directory)
            page.goto(f"http://127.0.0.1:{port}/browse?season_id={year.season_id}",wait_until="networkidle")
            expect(page.get_by_text("Browse races",exact=True).last).to_be_visible()
            expect(page.locator("iframe")).to_have_count(0)
            expect(page.get_by_role("button",name="Open in browser",exact=True)).to_be_disabled()
            assert requests == []
            expect(page.get_by_role("link",name="Open yearly events to add a race",exact=True)).to_have_attribute("href",f"/seasons?section=events&season_id={year.season_id}")
            capture(page,browser_artifacts/"bookmarks.png")
            page.get_by_label("Open website address",exact=True).fill("https://races.example.org/directory")
            page.get_by_role("button",name="Browse website",exact=True).click()
            expect(page.frame_locator('iframe[title="Race website"]').get_by_role("heading",name="Synthetic race directory",exact=True)).to_be_visible()
            expect(page.locator("iframe")).to_have_attribute("referrerpolicy","no-referrer")
            expect(page.get_by_role("button",name="Open in browser",exact=True)).to_be_enabled()
            page.locator("iframe").scroll_into_view_if_needed()
            capture(page,browser_artifacts/"embedded.png")
            page.get_by_label("Open website address",exact=True).fill("https://races.example.com/new")
            page.get_by_role("button",name="Save bookmark",exact=True).click()
            page.get_by_label("Site name",exact=True).fill('My "race" research')
            page.get_by_role("button",name="Save site tile",exact=True).click()
            page.get_by_text("Site tile saved.",exact=True).wait_for()
            expect(page.get_by_role("button",name='Browse bookmark My "race" research',exact=True)).to_have_count(1)
            assert len(race_bookmarks(db)) == 3
            page.get_by_role("button",name="Close website",exact=True).click()
            expect(page.locator("iframe")).to_have_count(0)
            page.reload(wait_until="networkidle")
            expect(page.get_by_role("button",name='Browse bookmark My "race" research',exact=True)).to_have_count(1)
            assert requests == ["https://races.example.org/directory"]
            assert get_active_plan_sha256(db) == before
            capture(page,browser_artifacts/"saved_bookmark.png")
            browser.close()
    finally:
        logs = _stop_server(server)
        (browser_artifacts/"browser.log").write_text(logs,encoding="utf8")
    assert not errors
    assert "Traceback" not in application_logs(logs)


@pytest.mark.browser
@pytest.mark.parametrize("width,height",[(1440,1000),(390,844)])
def test_common_sites_and_custom_url_create_reload_browse_remove_tile(tmp_path,browser_artifacts,width,height):
    db = _test_database(tmp_path)
    before = get_active_plan_sha256(db)
    server = _start_server(db,port:=_free_loopback_port())
    errors,requests = [],[]
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport=dict(width=width,height=height))
            page.on("pageerror",lambda e:errors.append(str(e)))
            def club(route):
                requests.append(route.request.url)
                route.fulfill(status=200,content_type="text/html",body="<h1>Synthetic local club races</h1>")
            page.route("https://club.example.com/**",club)
            page.goto(f"http://127.0.0.1:{port}/browse",wait_until="networkidle")
            expect(page.get_by_test_id("common-race-site")).to_have_count(4)
            for name in ("RunSignup","UltraSignup","FindMyMarathon","ACTIVE"):
                expect(page.get_by_role("button",name="Open race finder "+name,exact=True)).to_be_visible()
            assert requests == []
            capture(page,browser_artifacts/"common_sites.png")
            page.get_by_role("button",name="Add your own site",exact=True).click()
            dialog = page.get_by_role("dialog")
            expect(dialog.get_by_label("Website URL",exact=True)).to_have_value("")
            custom_name = "My race club" if width>=600 else "club.example.com"
            dialog.get_by_label("Site name",exact=True).fill("My race club" if width>=600 else "")
            dialog.get_by_label("Website URL",exact=True).fill("http://localhost:8091/")
            dialog.get_by_role("button",name="Save site tile",exact=True).click()
            expect(dialog.get_by_text("Use a public HTTPS website name",exact=False)).to_be_visible()
            assert len(race_bookmarks(db)) == 2
            dialog.get_by_label("Website URL",exact=True).fill("club.example.com/races")
            expect(dialog.get_by_text("Use a public HTTPS website name",exact=False)).to_have_count(0)
            capture(page,browser_artifacts/"add_site_dialog.png")
            dialog.get_by_role("button",name="Save site tile",exact=True).click()
            page.get_by_text("Site tile saved.",exact=True).wait_for()
            own = page.get_by_role("button",name="Browse bookmark "+custom_name,exact=True)
            expect(own).to_have_count(1)
            assert requests == []  # saving does not launch or fetch the site
            page.reload(wait_until="networkidle")
            expect(own).to_be_visible()
            expect(page.get_by_test_id("common-race-site")).to_have_count(4)
            own.scroll_into_view_if_needed()
            capture(page,browser_artifacts/"saved_tile.png")
            own.click()
            expect(page.frame_locator("iframe").get_by_role("heading",name="Synthetic local club races",exact=True)).to_be_visible()
            page.get_by_role("button",name="Remove site "+custom_name,exact=True).click()
            expect(own).to_have_count(0)
            assert len(race_bookmarks(db))==2
            assert get_active_plan_sha256(db)==before
            browser.close()
    finally:
        logs = _stop_server(server)
        (browser_artifacts/"browser.log").write_text(logs,encoding="utf8")
    assert not errors
    assert "Traceback" not in application_logs(logs)


@pytest.mark.browser
def test_blocked_embed_and_invalid_address_leave_browser_fallback_available(tmp_path,browser_artifacts):
    db = _test_database(tmp_path)
    server = _start_server(db,port:=_free_loopback_port())
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport=dict(width=390,height=844))
            page.on("pageerror",lambda e:errors.append(str(e)))
            page.route("https://blocked.example.com/**",lambda route:route.fulfill(status=200,headers={"Content-Security-Policy":"frame-ancestors 'none'","X-Frame-Options":"DENY"},body="<h1>This site should not embed</h1>"))
            page.goto(f"http://127.0.0.1:{port}/browse",wait_until="networkidle")
            page.get_by_label("Open website address",exact=True).fill("https://blocked.example.com/race")
            page.get_by_role("button",name="Browse website",exact=True).click()
            expect(page.locator("iframe")).to_have_attribute("src","https://blocked.example.com/race")
            expect(page.get_by_role("button",name="Open in browser",exact=True)).to_be_enabled()
            expect(page.get_by_text("use Open in browser if one stays blank.",exact=False)).to_be_visible()
            capture(page,browser_artifacts/"blocked_fallback.png")
            page.get_by_label("Open website address",exact=True).fill("https://127.0.0.1/")
            page.get_by_role("button",name="Browse website",exact=True).click()
            expect(page.get_by_role("alert")).to_contain_text("Use a public HTTPS website name")
            expect(page.locator("iframe")).to_have_attribute("src","https://blocked.example.com/race")
            browser.close()
    finally:
        logs = _stop_server(server)
        (browser_artifacts/"browser.log").write_text(logs,encoding="utf8")
    assert not errors
    assert "Traceback" not in application_logs(logs)


@pytest.mark.browser
@pytest.mark.parametrize("width,height",[(1440,1000),(390,844)])
def test_running_in_usa_bookmarks_request_browser_without_loading_denied_frame(tmp_path,browser_artifacts,monkeypatch,width,height):
    db = _test_database(tmp_path)
    before = get_active_plan_sha256(db)
    stub = r"""
import json
import garmin_data_hub.services.race_browse as race_service
def recorded_open(url):
    receipt = db_path.parent / 'browser-opens.json'
    values = json.loads(receipt.read_text()) if receipt.exists() else []
    values.append(url)
    receipt.write_text(json.dumps(values),encoding='utf8')
    return True
race_service.open_race_browser = recorded_open
create_ui(db_path, sandboxed=True)
"""
    monkeypatch.setattr(server_harness,"SERVER_SCRIPT",server_harness.SERVER_SCRIPT.replace("create_ui(db_path, sandboxed=True)",stub))
    server = _start_server(db,port:=_free_loopback_port())
    requests,errors = [],[]
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport=dict(width=width,height=height))
            page.on("pageerror",lambda e:errors.append(str(e)))
            def denied(route):
                requests.append(route.request.url)
                route.fulfill(status=403,headers={"X-Frame-Options":"SAMEORIGIN"},body="Embedding unavailable")
            page.route("https://www.runningintheusa.com/**",denied)
            page.goto(f"http://127.0.0.1:{port}/browse",wait_until="networkidle")
            assert not (db.parent/"browser-opens.json").exists()
            page.get_by_role("button",name="Open bookmark Running in the USA",exact=True).click()
            fallback = page.get_by_test_id("browse-browser-fallback")
            expect(fallback).to_contain_text("Running in the USA requires your browser")
            expect(fallback).to_contain_text("Browser requested.")
            expect(page.locator("iframe")).to_have_count(0)
            expect(page.get_by_role("button",name="Reload start page",exact=True)).to_be_disabled()
            assert json.loads((db.parent/"browser-opens.json").read_text()) == ["https://www.runningintheusa.com/race/list"]
            fallback.scroll_into_view_if_needed()
            capture(page,browser_artifacts/"running_browser_fallback.png")
            page.get_by_role("button",name="Open bookmark Races by state",exact=True).click()
            expect(fallback).to_contain_text("Browser requested.")
            assert json.loads((db.parent/"browser-opens.json").read_text()) == [
                "https://www.runningintheusa.com/race/list","https://www.runningintheusa.com/race/find-by-state/"]
            assert requests == []
            assert get_active_plan_sha256(db) == before
            page.get_by_role("button",name="Clear selection",exact=True).click()
            expect(fallback).to_have_count(0)
            browser.close()
    finally:
        logs = _stop_server(server)
        (browser_artifacts/"browser.log").write_text(logs,encoding="utf8")
    assert not errors
    assert "Traceback" not in application_logs(logs)
