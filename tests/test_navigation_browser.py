"""Responsive default menu and user-controlled hide/show across shared pages."""
import pytest
from playwright.sync_api import expect, sync_playwright

from test_activity_grid_browser import _test_database, _start_server, _stop_server, _free_loopback_port
from test_usability_browser import capture
from season_browser_logs import application_logs


@pytest.mark.browser
@pytest.mark.parametrize("width,height",[(1440,1000),(390,844)])
def test_navigation_defaults_toggle_close_and_routes(tmp_path,browser_artifacts,width,height):
    db = _test_database(tmp_path)
    server = _start_server(db,port:=_free_loopback_port())
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport=dict(width=width,height=height))
            page.on("pageerror",lambda e:errors.append(str(e)))
            base = f"http://127.0.0.1:{port}"
            page.goto(base+"/browse",wait_until="networkidle")
            menu = page.get_by_role("button",name="Navigation menu",exact=True)
            nav = page.get_by_role("navigation",name="Primary navigation",exact=True,include_hidden=True)
            expect(menu).to_have_attribute("aria-controls",nav.get_attribute("id"))
            if width >= 1024:
                expect(nav).to_be_visible()
                expect(menu).to_have_attribute("aria-expanded","true")
                capture(page,browser_artifacts/"desktop_open.png")
                menu.click()
            else:
                expect(nav).not_to_be_visible()
                expect(menu).to_have_attribute("aria-expanded","false")
            expect(nav).not_to_be_visible()
            expect(menu).to_have_attribute("aria-expanded","false")
            capture(page,browser_artifacts/"closed.png")
            menu.click()
            expect(nav).to_be_visible()
            expect(menu).to_have_attribute("aria-expanded","true")
            expect(nav.get_by_role("link",name="Browse races",exact=True)).to_be_visible()
            capture(page,browser_artifacts/"opened.png")
            nav.get_by_role("button",name="Hide navigation",exact=True).click()
            expect(nav).not_to_be_visible()
            expect(menu).to_have_attribute("aria-expanded","false")
            # Keyboard activation works and navigation uses the same shell on another page.
            menu.focus()
            menu.press("Enter")
            expect(nav).to_be_visible()
            nav.get_by_role("link",name="Help & About",exact=True).click()
            page.wait_for_url(base+"/guide")
            expect(page.get_by_role("button",name="Navigation menu",exact=True)).to_be_visible()
            expect(page.get_by_text("Local by design",exact=True)).to_be_visible()
            if width >= 1024:
                expect(nav).to_be_visible()
            else:
                expect(nav).not_to_be_visible()
            capture(page,browser_artifacts/"help_page.png")
            browser.close()
    finally:
        logs = _stop_server(server)
        (browser_artifacts/"browser.log").write_text(logs,encoding="utf8")
    assert not errors
    assert "Traceback" not in application_logs(logs)
