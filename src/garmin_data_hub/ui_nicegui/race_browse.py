"""User-selected external race sites, embedded when permitted by the site."""
import sqlite3
from urllib.parse import urlsplit

from garmin_data_hub.services.race_browse import (
    BrowseError, race_bookmarks, website_address, save_race_bookmark,
    remove_race_bookmark, restore_race_bookmarks, open_race_browser, browser_only_site,
    browser_only_site_name,COMMON_RACE_SITES,
)
from garmin_data_hub.ui_nicegui.layout import render_shell, page_heading


def register_race_browse_page(db_path, *, sandboxed):
    from nicegui import ui, run

    @ui.page("/browse")
    def browse_page(season_id: str = ""):
        render_shell("Browse races",db_path,sandboxed=sandboxed)
        dialogs = ui.element("div")
        with ui.column().classes("gdh-page"):
            page_heading("Browse races","Explore race websites and save places you want to visit again.")
            state = {"url":None,"request":0}
            error = ui.label("").classes("text-sm text-red-800 break-words").props('role="alert"')
            with ui.row().classes("w-full items-end gap-2 flex-wrap"):
                address = ui.input("Open website address",placeholder="https://www.runningintheusa.com/race/list").classes("min-w-0 flex-1").style("flex-basis:350px")
                ui.button("Browse website",icon="travel_explore",on_click=lambda:show(address.value))
                ui.button("Save bookmark",icon="bookmark_add",on_click=lambda:bookmark_dialog())
            with ui.row().classes("w-full gap-2 flex-wrap"):
                external = ui.button("Open in browser",icon="open_in_new",on_click=lambda:open_external())
                external.disable()
                reload_button = ui.button("Reload start page",icon="refresh",on_click=lambda:show(state["url"])).props("outline")
                reload_button.disable()
                close_button = ui.button("Close website",icon="close",on_click=lambda:close()).props("flat")
                close_button.disable()
            ui.label("Many race directories open in your browser because they restrict embedded viewing. Other sites can be viewed here; use Open in browser if one stays blank.").classes("text-sm break-words")
            bookmarks = ui.column().classes("w-full min-w-0")
            viewer = ui.column().classes("w-full min-w-0")
            with viewer:
                ui.label("Choose a bookmark or enter a website address to start browsing.").classes("text-sm text-slate-600")
            from garmin_data_hub.ui_nicegui.yearly_workflow import yearly_url
            ui.link("Open yearly events to add a race",yearly_url("/seasons",season_id,section="events")).classes("text-sm")

            async def show(url, *, site_name=None, prefer_browser=False):
                try:
                    url = website_address(url)
                except BrowseError as exc:
                    error.text = str(exc)
                    return
                error.text = ""
                address.value = url
                state["request"] += 1
                token = state["request"]
                state["url"] = url
                viewer.clear()
                external.enable()
                reload_button.enable()
                close_button.enable()
                blocked_site = browser_only_site_name(url)
                if blocked_site or prefer_browser:
                    reload_button.disable()
                    close_button.text = "Clear selection"
                    with viewer:
                        with ui.card().classes("gdh-card w-full min-w-0").props('data-testid="browse-browser-fallback"'):
                            ui.label((blocked_site+" requires your browser") if blocked_site else site_name+" opens in your browser").classes("font-semibold break-words")
                            ui.label("This website blocks viewing inside another app. Its directory opens in your regular browser; no embedded page is loaded here." if blocked_site else "Use your regular browser to explore this race directory.").classes("text-sm break-words")
                            status = ui.label("Opening browser…").classes("text-sm break-words")
                            ui.button("Open race site in browser",icon="open_in_new",on_click=lambda:open_external()).props("outline")
                    opened = await open_external()
                    if token == state["request"]:
                        status.text = "Browser requested. You can keep this page open while researching races." if opened else "Browser could not be opened. Copy the website address into your browser."
                    return
                close_button.text = "Close website"
                with viewer:
                    frame = ui.element("iframe").classes("w-full border rounded").style("height:70vh;min-height:420px")
                    frame.props('title="Race website" referrerpolicy="no-referrer" sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox allow-downloads"')
                    frame._props["src"] = url
                    frame._props["allow"] = ""

            def close():
                viewer.clear()
                state["request"] += 1
                state["url"] = None
                external.disable()
                reload_button.disable()
                close_button.disable()

            async def open_external():
                try:
                    # Use the visible address; in-frame navigation is controlled
                    # by the third-party website and cannot expose its current URL.
                    url = website_address(address.value)
                    opened = await run.io_bound(open_race_browser,url)
                    if not opened:
                        error.text = "The browser could not be opened. Copy the website address into your browser."
                    else:
                        error.text = ""
                    return opened
                except (BrowseError,OSError) as exc:
                    error.text = str(exc) if isinstance(exc,BrowseError) else "The browser could not be opened. Copy the website address into your browser."
                    return False

            def bookmark_list():
                bookmarks.clear()
                with bookmarks:
                    with ui.row().classes("w-full justify-between items-center gap-2 flex-wrap"):
                        ui.label("Race-site bookmarks").classes("text-xl font-semibold")
                        ui.button("Add your own site",icon="add",on_click=lambda:bookmark_dialog(prefill=False))
                    ui.label("Common race finders").classes("font-semibold")
                    with ui.row().classes("w-full gap-3 flex-wrap"):
                        for row in COMMON_RACE_SITES:
                            with ui.card().classes("gdh-card min-w-0 flex-1").style("flex-basis:280px").props('data-testid="common-race-site"'):
                                ui.label(row["name"]).classes("font-semibold break-words")
                                ui.label(row["description"]).classes("text-sm break-words")
                                ui.label(row["url"]).classes("text-xs text-slate-600 break-all")
                                browse = ui.button("Open site in browser",on_click=lambda _,site=row:show(site["url"],site_name=site["name"],prefer_browser=site.get("prefer_browser",False)))
                                browse._props["aria-label"] = "Open race finder "+row["name"]
                    ui.label("Your saved site tiles").classes("font-semibold")
                    try:
                        rows = race_bookmarks(db_path)
                    except (BrowseError,sqlite3.Error,OSError):
                        ui.label("Saved bookmarks are unavailable. You can still browse an address or restore the starter bookmarks.").classes("text-sm text-amber-900 break-words")
                        ui.button("Restore default bookmarks",on_click=restore).props("outline")
                        return
                    with ui.row().classes("w-full gap-3 flex-wrap"):
                        for row in rows:
                            with ui.card().classes("gdh-card min-w-0 flex-1").style("flex-basis:280px").props('data-testid="saved-race-site"'):
                                ui.label(row["name"]).classes("font-semibold break-words")
                                ui.label(row["url"]).classes("text-xs text-slate-600 break-all")
                                with ui.row().classes("w-full gap-2 flex-wrap"):
                                    external_site = browser_only_site(row["url"])
                                    browse = ui.button("Open site in browser" if external_site else "Browse here",on_click=lambda _,url=row["url"]:show(url))
                                    browse._props["aria-label"] = ("Open bookmark " if external_site else "Browse bookmark ")+row["name"]
                                    remove_button = ui.button(icon="delete_outline",on_click=lambda _,url=row["url"]:remove(url)).props("flat").tooltip("Remove bookmark")
                                    remove_button._props["aria-label"] = "Remove site "+row["name"]
                    if not rows:
                        ui.label("No saved site tiles. Select Add your own site to create one.").classes("text-sm")

            async def remove(url):
                try:
                    await run.io_bound(remove_race_bookmark,db_path,url)
                    bookmark_list()
                except (BrowseError,sqlite3.Error,OSError) as exc:
                    error.text = str(exc) if isinstance(exc,BrowseError) else "Bookmark could not be removed."

            async def restore():
                try:
                    await run.io_bound(restore_race_bookmarks,db_path)
                    bookmark_list()
                except (BrowseError,sqlite3.Error,OSError):
                    error.text = "Bookmarks could not be restored."

            def bookmark_dialog(*, prefill=True):
                with dialogs,ui.dialog() as dialog,ui.card().classes("w-full max-w-md"):
                    ui.label("Add your own race site").classes("text-xl font-semibold")
                    name = ui.input("Site name").classes("w-full")
                    ui.label("Name is optional; the website address is used when left blank.").classes("text-xs text-slate-600 break-words")
                    url = ui.input("Website URL",value=(address.value or "") if prefill else "",placeholder="https://example.com/races").classes("w-full")
                    message = ui.label("").classes("text-sm text-red-800 break-words")
                    name.on_value_change(lambda _:setattr(message,"text",""))
                    url.on_value_change(lambda _:setattr(message,"text",""))
                    async def save():
                        save_button.disable()
                        try:
                            normalized = website_address(url.value)
                            title = (name.value or "").strip() or urlsplit(normalized).hostname.removeprefix("www.")[:120]
                            await run.io_bound(save_race_bookmark,db_path,title,normalized)
                            bookmark_list()
                            dialog.close()
                            ui.notify("Site tile saved.",type="positive")
                        except (BrowseError,sqlite3.Error,OSError) as exc:
                            message.text = str(exc) if isinstance(exc,BrowseError) else "Bookmark could not be saved."
                        finally:
                            save_button.enable()
                    with ui.row().classes("w-full justify-end gap-2"):
                        ui.button("Cancel",on_click=dialog.close).props("flat")
                        save_button = ui.button("Save site tile",on_click=save)
                dialog.open()

            bookmark_list()
