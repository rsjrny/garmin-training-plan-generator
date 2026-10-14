"""Discoverable Redo this year, with one combined replacement review."""
from datetime import timedelta
import json
import sqlite3

from nicegui import ui, run
from garmin_data_hub.services import yearly_reset as reset, season_plans as plans, season_generation as generation
from garmin_data_hub.services.season_schedule import GenerationSettings
from garmin_data_hub.services.yearly_workflow import read_state, proposals
from garmin_data_hub.services.season_baseline import goal_label
from garmin_data_hub.ui_nicegui.yearly_workflow import yearly_url
from garmin_data_hub.ui_nicegui.planning_presenter import friendly_phase


def redo_year(db_path,season_id,*,container,on_applied):
    try:
        state=read_state(db_path,season_id)
        season=state.season
    except (plans.SeasonError,sqlite3.Error,OSError) as exc:
        ui.notify(str(exc),type="negative")
        return
    start=max(season.start_date,(generation._local_today(season.timezone)+timedelta(days=1)).isoformat())
    if start>season.end_date:
        ui.notify("This year has no future dates to restart. Choose a future yearly plan.",type="info")
        return
    def error_message(error,label):
        label.text=str(error) if isinstance(error,(ValueError,plans.SeasonError)) else "Restart unavailable. Refresh and try again."
    def review(preview):
        details=preview.schedule.candidate.change_summary["yearly_reset"]
        document=json.loads(preview.document_json)
        removed=set(details["legacy_removed"])
        own=set(preview.schedule.candidate.change_summary["removed_workout_ids"])
        foreign={p["plan_id"]:set(p["removed_workout_ids"]) for p in details["foreign_removed"]}
        old_rows=[dict(date=r["scheduled_date"],title=r["workout_name"],source="Older workout" if r["source_plan_id"] is None else "Previous plan")
            for r in document["rows"] if r["planned_workout_id"] in removed or r["source_workout_id"] in own or r["source_workout_id"] in foreign.get(r["source_plan_id"],())]
        future=[w for w in preview.schedule.candidate.workouts if w.scheduled_date.isoformat()>=preview.restart_date]
        with container, ui.dialog() as dialog, ui.card().classes("w-full max-w-4xl max-h-[90vh] overflow-y-auto min-w-0"):
            ui.label("Review yearly restart").classes("text-xl font-semibold")
            ui.label(f"{season.name}: {preview.restart_date} → {season.end_date}").classes("font-semibold break-words")
            ui.label(f"{len(old_rows)} older workouts replaced · {len(future)} future entries in the refreshed plan").classes("break-words")
            ui.label("Completed training, today's workouts, past history and saved originals remain available. Other years are retained.").classes("text-sm break-words")
            if preview.clear_events:
                ui.label("Upcoming events will be cancelled in the same acceptance; their saved history is retained.").classes("text-sm break-words")
            if preview.replace_protected:
                ui.label("The replacement includes unfinished locked/manual workouts. Completed workouts and activity matches remain protected.").classes("text-sm break-words")
            with ui.column().classes("sticky top-0 z-10 bg-white w-full py-2 border-b gap-2"):
                for message in preview.blockers:
                    ui.label(message).classes("text-red-800 break-words")
                for issue in preview.schedule.errors:
                    ui.label(issue.message).classes("text-red-800 break-words")
                if not preview.can_apply:
                    ui.label("This fresh calendar still has a constraint. Go back to change the restart options, clear upcoming events, or edit yearly settings.").classes("text-sm break-words")
                ack=ui.checkbox("I reviewed the replacements and warnings and want to redo this year.").props('aria-label="I reviewed the replacements and warnings and want to redo this year."').classes("w-full")
                error=ui.label("").classes("text-red-800 break-words")
                busy={"value":False}
                async def apply():
                    if busy["value"]:
                        return
                    if not ack.value:
                        error.text="Acknowledge this review before applying the restart."
                        return
                    busy["value"]=True
                    apply_button.disable()
                    try:
                        result=await run.io_bound(reset.apply_reset,db_path,preview,approved_by="LOCAL_USER",acknowledged=True)
                    except (plans.SeasonError,sqlite3.Error,OSError,ValueError) as exc:
                        error_message(exc,error)
                        return
                    finally:
                        busy["value"]=False
                        if preview.can_apply:
                            apply_button.enable()
                    proposals.retry(db_path,season_id)
                    dialog.close()
                    on_applied()
                    ui.notify("Yearly plan restarted." if result.status=="applied" else "This restart was already applied.",type="positive")
                with ui.row().classes("w-full justify-end flex-wrap"):
                    ui.button("Back to restart options",on_click=lambda:(dialog.close(),options.open())).props("flat")
                    ui.button("Keep current plan",on_click=dialog.close).props("outline")
                    apply_button=ui.button("Apply yearly restart",on_click=apply)
                    apply_button.set_enabled(preview.can_apply)
            with ui.expansion("Older workouts to replace",value=True).classes("w-full"):
                if old_rows:
                    ui.table(columns=[{"name":k,"field":k,"label":k.title(),"align":"left"} for k in ("date","title","source")],rows=old_rows,row_key="date",pagination=8).classes("w-full overflow-x-auto").props("wrap-cells")
                else:
                    ui.label("No older future workouts to replace.").classes("text-sm")
            with ui.expansion("Retained workouts and weeks").classes("w-full"):
                for item in details["retained"]:
                    ui.label(f'{item["date"]} · {item["title"]}: {item["reason"]}').classes("text-sm break-words")
                ui.label("Weeks with retained workouts from older/other schedules receive no new workouts because their load is unverified.").classes("text-sm break-words")
            with ui.expansion("Future workouts after restart").classes("w-full"):
                ui.table(columns=[{"name":k,"field":k,"label":k.title(),"align":"left"} for k in ("date","workout","phase","minutes")],
                    rows=[dict(date=w.scheduled_date.isoformat(),workout=w.title,phase=friendly_phase(w.phase),
                        minutes=0 if w.sport.value=="REST" else round(sum(s.duration_seconds for s in w.segments)/60,1)
                        if all(s.duration_seconds is not None for s in w.segments) else "Unknown") for w in future],row_key="date",pagination=8).classes("w-full overflow-x-auto").props("wrap-cells")
            with ui.expansion(f"Warnings ({len(preview.schedule.warnings)})").classes("w-full"):
                for issue in preview.schedule.warnings:
                    ui.label(issue.message).classes("text-sm break-words text-amber-900")
        dialog.open()

    confirmed=state.settings
    with container, ui.dialog() as options, ui.card().classes("w-full max-w-xl max-h-[90vh] overflow-y-auto min-w-0"):
        ui.label("Redo this year").classes("text-xl font-semibold")
        ui.label(f"{season.name} · Baseline goal: {goal_label(season.inputs.baseline_distance_code)}").classes("break-words")
        ui.label("Prepare a fresh remaining schedule and replace older future workouts in one review. You do not need to resolve obsolete schedule overlaps first.").classes("text-sm break-words")
        day=ui.input("Restart from",value=start).props("type=date").classes("w-full")
        include=ui.checkbox("Replace unfinished locked/manual workouts too",value=False).props('aria-label="Replace unfinished locked/manual workouts too"').classes("w-full")
        clear=ui.checkbox("Clear upcoming events and rebuild a race-free year",value=False).props('aria-label="Clear upcoming events and rebuild a race-free year"').classes("w-full")
        ui.label("Completed workouts, recorded activity matches and history stay protected. Saved settings and the baseline distance goal are kept.").classes("text-sm break-words")
        ui.link("Edit yearly settings",yearly_url("/seasons",season_id,section="settings",setup="1"))
        if season.inputs.training_method=="eighty_twenty":
            ui.label(f"Running LTHR: {season.inputs.lthr or 'not set'} · Starting weekly minutes: {(season.inputs.starting_duration_seconds or 0)/60:g}").classes("text-sm break-words")
            threshold=ui.checkbox("I confirm this LTHR is a measured running threshold.",value=bool(confirmed and confirmed.lthr_confirmed)).props('aria-label="I confirm this LTHR is a measured running threshold."').classes("w-full")
        else:
            adjustment=ui.select({-10:"-10 bpm",-5:"-5 bpm",0:"0 bpm",5:"+5 bpm"},label="MAF adjustment",value=confirmed.maf_adjustment if confirmed else None).classes("w-full")
            maf=ui.checkbox("I confirm the selected MAF adjustment.",value=bool(confirmed and confirmed.maf_confirmed)).props('aria-label="I confirm the selected MAF adjustment."').classes("w-full")
        error=ui.label("").classes("text-red-800 break-words")
        pending={"value":False}
        async def prepare():
            if pending["value"]:
                return
            pending["value"]=True
            preview_button.disable()
            error.text=""
            try:
                settings=GenerationSettings(lthr_confirmed=threshold.value) if season.inputs.training_method=="eighty_twenty" else GenerationSettings(maf_adjustment=adjustment.value,maf_confirmed=maf.value)
                preview=await run.io_bound(reset.preview_reset,db_path,season_id,settings,restart_date=day.value,
                    replace_protected=include.value,clear_events=clear.value)
            except (plans.SeasonError,sqlite3.Error,OSError,ValueError) as exc:
                error_message(exc,error)
                return
            finally:
                pending["value"]=False
                preview_button.enable()
            options.close()
            review(preview)
        with ui.row().classes("w-full justify-end sticky bottom-0 bg-white py-2 flex-wrap"):
            ui.button("Cancel restart",on_click=options.close).props("flat")
            preview_button=ui.button("Review fresh year",on_click=prepare)
    options.open()
