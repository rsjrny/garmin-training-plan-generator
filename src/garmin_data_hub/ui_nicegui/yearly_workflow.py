"""Shared proposal status for Seasons, Plan and the read-only Dashboard."""
from urllib.parse import urlencode

from nicegui import ui

from garmin_data_hub.services.yearly_workflow import proposals


def yearly_url(route, season_id, **parameters):
    if season_id:
        parameters["season_id"] = season_id
    return route + ("?" + urlencode(parameters) if parameters else "")


def render_workflow(db_path, season_id, *, on_review=None, on_settings=None, prepare=False, on_change=None):
    state = {"value": None, "signature": None, "error": None}

    @ui.refreshable
    def content():
        value = state["value"]
        with ui.column().classes("w-full min-w-0 gap-2").props('role="status" aria-live="polite"'):
            if state["error"]:
                ui.label("Yearly update unavailable. Refresh or review Seasons.").classes("text-red-800 break-words")
                return
            if value is None:
                ui.label("Checking yearly plan…").classes("break-words")
                return
            ui.label(value.message).classes("font-medium break-words").props('data-testid="yearly-workflow-status"')
            if value.status == "preparing":
                ui.linear_progress().props("indeterminate")
            if value.status not in {"current", "archived"}:
                ui.label("Event edits prepare a proposal automatically. Closing a proposal keeps changes pending; only acceptance updates workouts.").classes("text-sm text-slate-600 break-words")
            with ui.row().classes("gap-2 flex-wrap"):
                if value.preview and on_review:
                    async def review_latest():
                        import asyncio
                        try:
                            if prepare:
                                await poll()
                            latest = await proposals.for_review(db_path,season_id) if prepare else await asyncio.to_thread(proposals.state,db_path,season_id)
                            if latest.preview:
                                on_review(latest.preview)
                            else:
                                await poll()
                                ui.notify(latest.message,type="info")
                        except Exception:
                            await poll()
                            ui.notify("Yearly proposal unavailable. Refresh and review again.",type="warning")
                    ui.button("Review yearly proposal", on_click=review_latest).props("outline")
                if value.status == "conflict" and not value.preview and prepare:
                    async def retry():
                        proposals.retry(db_path,season_id)
                        await poll()
                    ui.button("Retry yearly update",on_click=retry).props("outline")
                elif value.status not in {"current", "archived"} and not prepare:
                    ui.link("Review yearly update", yearly_url("/plan", season_id))
                if value.status == "settings_required":
                    if on_settings:
                        ui.button("Complete preview settings", on_click=lambda: on_settings(value.season)).props("outline")
                    else:
                        ui.link("Complete yearly settings", yearly_url("/seasons", season_id))

    async def poll():
        try:
            import asyncio
            value = await proposals.ensure(db_path, season_id) if prepare else await asyncio.to_thread(proposals.state, db_path, season_id)
            signature = (value.fingerprint, value.status, value.message, value.preview.preview_id if value.preview else None)
            if signature != state["signature"]:
                state.update(value=value, signature=signature, error=None)
                content.refresh()
                if on_change:
                    on_change(value)
        except Exception:
            if not state["error"]:
                state["error"] = True
                content.refresh()

    content()
    ui.timer(1.0, poll, immediate=True)
    return poll
