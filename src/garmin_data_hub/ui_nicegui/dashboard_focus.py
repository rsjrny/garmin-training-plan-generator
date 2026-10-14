"""Compact dashboard focus with read-only refresh and drill-down links."""
from __future__ import annotations

import logging
import sqlite3

from garmin_data_hub.services.dashboard_focus import dashboard_focus
from garmin_data_hub.services.season_plans import SeasonError
from garmin_data_hub.services.workout_compliance import MatchReviewError
from garmin_data_hub.plan_methodology.revision_repository import CorruptRevisionError
from garmin_data_hub.ui_nicegui.data import distance_from_km, distance_unit
from garmin_data_hub.ui_nicegui.yearly_workflow import yearly_url

logger = logging.getLogger(__name__)


def _amounts(row, units, *, recorded=False):
    duration = row["actual_duration_s"] if recorded else row["duration_s"]
    distance = row["actual_distance_m"] if recorded else row["distance_m"]
    parts = []
    if duration is not None:
        parts.append(f"{duration/60:g} min")
    if distance is not None:
        parts.append(f"{distance_from_km(distance/1000,units):g} {distance_unit(units)}")
    return " · ".join(parts) or "Amounts unavailable"


def _session(row, units):
    from nicegui import ui
    ui.label(row["title"]).classes("font-medium break-words")
    state = row["status"] + (" · "+row["completion"].lower() if row["moved"] else "")
    ui.label(state+" · "+_amounts(row,units)).classes("text-sm break-words")
    if row["duration_estimated"] or row["distance_estimated"]:
        ui.label("Estimated target").classes("text-xs text-slate-600")
    if row["activity_id"] is not None:
        ui.link("Recorded "+str(row["actual_date"] or "date unavailable")+" · "+_amounts(row,units,recorded=True),
                "/activities?activity_id="+str(row["activity_id"])).classes("text-sm break-words")


def _day(day, units):
    from nicegui import ui
    if not day["sessions"]:
        ui.label("No saved session").classes("text-sm text-slate-600")
    for row in day["sessions"]:
        with ui.column().classes("w-full min-w-0 gap-0"):
            _session(row,units)
    for event in day["events"]:
        marker = "C · marker only" if event["priority"] == "C" else event["priority"]+" · saved event"
        ui.label(f'{marker}: {event["name"]} ({event["distance_code"]})').classes("text-sm text-blue-800 break-words")
    if day["events"]:
        ui.label("Saved events may include changes awaiting plan review.").classes("text-xs text-slate-600 break-words")


def _recovery(result, error):
    from nicegui import ui
    ui.label("Recovery & Readiness").classes("font-semibold")
    if result is None:
        ui.label(error or "Recovery estimates unavailable.").classes("text-sm text-amber-900 break-words")
    else:
        current = result["assessment"]
        ui.label("Assessment: "+current["date"]).classes("text-sm")
        if result["latest_signal_date"] != current["date"]:
            ui.label("No current sleep/HRV/resting-HR record. Latest usable signal: "+(result["latest_signal_date"] or "none")).classes("text-sm text-amber-900 break-words")
        with ui.row().classes("w-full gap-3 flex-wrap"):
            for key,label in (("recovery","Recovery"),("readiness","Readiness"),("energy","Energy estimate")):
                score = current["scores"][key]
                with ui.column().classes("min-w-0 gap-0 flex-1").style("flex-basis:95px"):
                    ui.label(label).classes("text-sm")
                    ui.label("Unavailable" if score["score"] is None else f'{score["score"]:g} / 100').classes("text-xl font-semibold").props(f'data-testid="score-{key}"')
                    ui.label(f'{score["confidence"]} · {score["coverage_pct"]:g}% coverage').classes("text-xs break-words")
        ui.label(current["guidance"]).classes("text-sm break-words").props('data-testid="recovery-guidance"')
        ui.label("Experimental estimates · current evidence only; no recovery forecast or automatic workout changes.").classes("text-xs text-slate-600 break-words")
        if result["latest_signal_date"] and result["latest_signal_date"] != current["date"]:
            ui.link("View latest available data · "+result["latest_signal_date"],
                    "/recovery?assessment_date="+result["latest_signal_date"]).classes("text-sm")
    ui.link("Open Recovery & Readiness", "/recovery").classes("text-sm")


def render_dashboard_focus(db_path, units, *, season_id=""):
    from nicegui import ui, run
    with ui.card().classes("gdh-card w-full min-w-0").props('data-testid="dashboard-focus"'):
        with ui.row().classes("w-full items-center justify-between gap-2 flex-wrap"):
            ui.label("Today / next 7 days").classes("text-xl font-semibold")
            button = ui.button("Refresh training overview",icon="refresh").props("flat")
        output = ui.column().classes("w-full min-w-0")
        ui.label("Loading training overview…").classes("text-sm").move(output)
        request = {"id":0}
        async def load():
            request["id"] += 1
            token = request["id"]
            button.disable()
            output.clear()
            try:
                result = await run.io_bound(dashboard_focus,db_path,season_id=season_id)
                if token != request["id"]:
                    return
                with output:
                    ui.label(f'{result["scope"]} · {result["today"]} to {result["end"]} · {result["timezone"]}').classes("text-sm break-words")
                    if result["no_applied_plan"]:
                        ui.label("This yearly plan has no applied schedule. Review and apply its plan to populate these days.").classes("text-sm text-amber-900 break-words")
                    for warning in result["warnings"]:
                        ui.label(warning).classes("text-sm text-amber-900 break-words")
                    with ui.row().classes("w-full gap-4 flex-wrap items-start"):
                        with ui.column().classes("min-w-0 flex-1 gap-2").style("flex-basis:320px").props('data-testid="focus-today"'):
                            ui.label("Today · "+result["today"]).classes("font-semibold")
                            _day(result["days"][0],units)
                            ui.link("Open training plan",yearly_url("/plan",season_id,view="workouts")).classes("text-sm")
                            if any(not row["rest"] for row in result["days"][0]["sessions"]):
                                ui.link("Review today's matches",yearly_url("/compliance",season_id,start=result["today"],end=result["today"])).classes("text-sm")
                        with ui.column().classes("min-w-0 flex-1 gap-2").style("flex-basis:360px"):
                            _recovery(result["recovery"],result["recovery_error"])
                    recent = result["recent"]
                    with ui.column().classes("w-full min-w-0 gap-1 border-t pt-3").props('data-testid="focus-recent"'):
                        ui.label("Recent completion · "+recent["start"]+" to "+recent["end"]).classes("font-semibold break-words")
                        ui.label(f'{recent["completed"]} completed · {recent["partial"]} partial · {recent["moved"]} moved (included above) · {recent["missed"]} missed').classes("text-sm break-words")
                        ui.label(f'{recent["needs_review"]} needing review · {recent["pending"]} awaiting activity or evidence').classes("text-sm break-words")
                        ui.label(f'{recent["activity_count"]} recorded activities · {recent["extra"]} extra activities · all Garmin history in this period').classes("text-sm break-words")
                        ui.link("Review recent matches",yearly_url("/compliance",season_id,start=recent["start"],end=recent["end"])).classes("text-sm")
                        if recent["sessions"]:
                            with ui.expansion("Recent session details").classes("w-full min-w-0"):
                                for row in reversed(recent["sessions"]):
                                    with ui.column().classes("w-full min-w-0 gap-0 border-b py-2"):
                                        ui.label(row["date"]).classes("text-xs")
                                        _session(row,units)
                    ui.label("Coming days · planned sessions").classes("font-semibold mt-2")
                    with ui.element("div").classes("w-full min-w-0 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3"):
                        for day in result["days"][1:]:
                            with ui.column().classes("min-w-0 gap-1 border rounded p-3").props(f'data-testid="focus-day-{day["date"]}"'):
                                ui.label(day["date"]).classes("font-semibold")
                                _day(day,units)
                    ui.label("Seven calendar days including today. Only reviewed matches or explicit done flags count as completion; no saved session does not imply rest. Refresh after syncing or applying a plan.").classes("text-xs text-slate-600 break-words")
            except (MatchReviewError,SeasonError,CorruptRevisionError,sqlite3.Error,OSError) as exc:
                if token == request["id"]:
                    with output:
                        ui.label(str(exc) if isinstance(exc,(MatchReviewError,SeasonError)) else "Training overview unavailable. Check the database and refresh.").classes("text-sm text-amber-900 break-words").props('role="alert"')
                        ui.link("Open training plan",yearly_url("/plan",season_id))
                logger.warning("Dashboard training overview unavailable: %s",type(exc).__name__)
            finally:
                if token == request["id"]:
                    button.enable()
        button.on_click(load)
        ui.timer(.1,load,once=True)
