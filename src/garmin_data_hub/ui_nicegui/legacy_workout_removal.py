"""Select, review and accept removal from an older future calendar."""
import json
import sqlite3

from garmin_data_hub.services import legacy_workout_removal as removal, season_plans as plans
from garmin_data_hub.services.yearly_workflow import proposals


def remove_older_workouts(db_path, *, container, season=None, on_removed=lambda: None):
    from nicegui import ui, run

    tz = season.timezone if season else "America/New_York"
    try:
        bounds = (season.start_date,season.end_date) if season else removal.default_dates(db_path,tz)
    except (ValueError,sqlite3.Error,OSError):
        ui.notify("Unable to read older workouts. Refresh and try again.",type="negative")
        return

    with container, ui.dialog() as dialog, ui.card().classes("w-full max-w-3xl max-h-[90vh] overflow-y-auto min-w-0"):
        ui.label("Remove older workouts").classes("text-xl font-semibold break-words")
        ui.label("Select future workouts from the older single-event schedule, then review the exact removals. History, today's workouts, protected metadata and dates with recorded activity are retained. Structured plans use their yearly proposal workflow.").classes("text-sm break-words")
        ui.label(f"Local dates: {tz}").classes("text-sm break-words")
        start = ui.input("Removal start",value=bounds[0]).props("type=date").classes("w-full")
        end = ui.input("Removal end",value=bounds[1]).props("type=date").classes("w-full")
        if season:
            start.disable()
            end.disable()
        state = {"rows":()}
        error = ui.label("").classes("text-red-800 break-words")

        @ui.refreshable
        def choices():
            rows = state["rows"]
            eligible = {r["planned_workout_id"]:f'{r["scheduled_date"]} · {r["workout_name"]}' for r in rows if not r["blockers"]}
            selection = ui.select(eligible,multiple=True,value=[],label="Older workouts to remove").props("use-chips").classes("w-full max-h-48 overflow-y-auto")
            ui.label(f"{len(eligible)} eligible · {len(rows)-len(eligible)} retained in these dates").classes("text-sm break-words")
            ui.button("Select all eligible shown workouts",on_click=lambda:selection.set_value(list(eligible))).props("outline").set_enabled(bool(eligible))
            ui.table(columns=[{"name":k,"label":v,"field":k} for k,v in
                (("scheduled_date","Date"),("workout_name","Workout"),("status","Removal eligibility"))],
                rows=[dict(r,status="; ".join(r["blockers"]) or "Eligible future workout") for r in rows],
                row_key="planned_workout_id",pagination=8).classes("w-full")

            async def preview():
                try:
                    reviewed = await run.io_bound(removal.preview_removal,db_path,tuple(selection.value or ()),
                        timezone=tz,season_id=season.season_id if season else "")
                    if season and json.loads(reviewed.review_json)["season_version"] != season.input_version:
                        raise plans.StaleSeasonError("Yearly settings changed. Reopen older-workout removal for the latest year.")
                except (ValueError,sqlite3.Error,OSError) as exc:
                    error.text = str(exc) if isinstance(exc,ValueError) else "Unable to prepare removal. Refresh and try again."
                    return
                dialog.close()
                review_removal(db_path,reviewed,container=container,on_removed=on_removed)

            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel workout removal",on_click=dialog.close).props("flat")
                ui.button("Preview selected removals",on_click=preview).set_enabled(bool(eligible))

        async def load():
            try:
                state["rows"] = await run.io_bound(removal.list_workouts,db_path,start.value,end.value,tz)
                error.text = ""
                choices.refresh()
            except (ValueError,sqlite3.Error,OSError) as exc:
                error.text = str(exc) if isinstance(exc,ValueError) else "Unable to read workouts. Refresh and try again."

        ui.button("Refresh removal dates",on_click=load).props("outline")
        choices()
        ui.timer(0.1,load,once=True)
    dialog.open()


def review_removal(db_path,preview,*,container,on_removed=lambda:None):
    from nicegui import ui, run

    document = json.loads(preview.review_json)
    with container, ui.dialog() as dialog, ui.card().classes("w-full max-w-3xl max-h-[90vh] overflow-y-auto min-w-0"):
        ui.label("Review workout removals").classes("text-xl font-semibold break-words")
        noun = "workout" if len(preview.workout_ids)==1 else "workouts"
        ui.label(f"{len(preview.workout_ids)} selected older {noun} · local dates in {preview.timezone}").classes("break-words")
        ui.label("Acceptance removes only these workouts from the active calendar. Their original prescriptions remain saved in removal history; recorded activities and other workouts remain intact. Schedule and nutrition suggestions for the selected dates are cleared.").classes("text-sm break-words")
        for blocker in preview.blockers:
            ui.label(blocker).classes("text-amber-900 break-words")
        ui.table(columns=[{"name":k,"label":v,"field":k} for k,v in
            (("scheduled_date","Date"),("workout_name","Workout"),("description","Original description"),("minutes","Planned minutes"))],
            rows=[dict(r,minutes=round(r["planned_duration_s"]/60,1) if r["planned_duration_s"] is not None else None) for r in document["workouts"]],
            row_key="planned_workout_id",pagination=8).classes("w-full")
        acknowledged = ui.checkbox("I reviewed these selected workouts and accept their removal from the calendar.").classes("w-full")
        error = ui.label("").classes("text-red-800 break-words")

        async def apply():
            button.disable()
            try:
                result = await run.io_bound(removal.apply_removal,db_path,preview,approved_by="LOCAL_USER",acknowledged=acknowledged.value)
            except (ValueError,sqlite3.Error,OSError) as exc:
                error.text = str(exc) if isinstance(exc,ValueError) else "Unable to remove workouts. Refresh and review again."
                return
            finally:
                button.set_enabled(preview.can_apply)
            dialog.close()
            on_removed()
            ui.notify("Selected older workouts removed from the calendar. Originals retained." if result=="applied" else "These reviewed removals were already accepted.",type="positive")
            if preview.season_id:
                try:
                    await proposals.ensure(db_path,preview.season_id)
                except (ValueError,sqlite3.Error,OSError):
                    ui.notify("Removal accepted. Refresh to prepare the latest yearly proposal.",type="warning")

        with ui.row().classes("w-full justify-end"):
            ui.button("Keep these workouts",on_click=dialog.close).props("flat")
            button = ui.button("Accept selected workout removals",on_click=apply).set_enabled(preview.can_apply)
    dialog.open()


def render_removal_history(db_path):
    from nicegui import ui

    entries = removal.list_removals(db_path)
    if not entries:
        return
    with ui.expansion("Removed older workouts — saved originals",icon="history").classes("gdh-card w-full"):
        for entry in entries:
            document = json.loads(entry["review_json"])
            ui.label(f'{entry["approved_at_utc"]} · {len(document["workouts"])} removed · {entry["approved_by"]}').classes("text-sm break-words")
            ui.table(columns=[{"name":k,"label":v,"field":k} for k,v in
                (("scheduled_date","Date"),("workout_name","Original workout"),("description","Original description"))],
                rows=document["workouts"],row_key="planned_workout_id",pagination=8).classes("w-full")
