"""Recovery estimates, drivers and dated Garmin comparison, all kept local."""
from __future__ import annotations

from datetime import date
import logging
import sqlite3

from garmin_data_hub.services.recovery_readiness import recovery_assessment, save_sleep_target

logger = logging.getLogger(__name__)
SCORE_LABELS = {"recovery": "Recovery", "readiness": "Readiness", "energy": "Energy estimate"}


def _value(value, suffix=""):
    return "Unavailable" if value is None else f"{value:g}{suffix}"


def render_assessment(result, *, compact=False):
    from nicegui import ui
    current = result["assessment"]
    ui.label(f'Assessment: {current["date"]}').classes("text-sm font-medium")
    ui.label("Experimental estimates · Input coverage describes available data, not score accuracy.").classes("text-xs text-slate-600 break-words")
    if result["assessment_age_days"]:
        ui.label(f'Historical assessment · {result["assessment_age_days"]} days old. This is not today\'s readiness.').classes("text-sm text-amber-900 break-words")
    if result["latest_signal_date"] != current["date"]:
        ui.label("No current sleep/HRV/resting-HR record for this date. Latest usable signal: " + (result["latest_signal_date"] or "none")).classes("text-sm text-amber-900 break-words")
    with ui.row().classes("w-full gap-3 flex-wrap"):
        for key, label in SCORE_LABELS.items():
            score = current["scores"][key]
            with ui.card().classes("gdh-card flex-1 min-w-0 p-3").style("flex-basis:200px"):
                ui.label(label).classes("font-semibold").props(f'data-testid="score-label-{key}"')
                ui.label(_value(score["score"], " / 100")).classes("text-3xl font-bold").props(f'data-testid="score-{key}"')
                ui.label(score["label"]).classes("font-medium")
                ui.label(f'{score["confidence"]} · {score["coverage_pct"]:g}% input coverage').classes("text-sm break-words")
                if score["missing"]:
                    ui.label("Missing: " + ", ".join(score["missing"])).classes("text-xs break-words")
    ui.label(current["guidance"]).classes("font-medium break-words").props('data-testid="recovery-guidance"')
    ui.label(result["limitations"]).classes("text-xs text-slate-600 break-words")
    if compact:
        ui.link("Open Recovery & Readiness", "/recovery")
        if result["latest_signal_date"] and result["latest_signal_date"] != current["date"]:
            ui.link("View latest available data · " + result["latest_signal_date"],
                "/recovery?assessment_date=" + result["latest_signal_date"])
        return
    ui.label("Energy is a sleep/stress estimate, not a measurement of physical energy. These scores do not modify your planned workouts.").classes("text-sm break-words")
    with ui.expansion("What drives these scores", value=True).classes("w-full"):
        for key, label in SCORE_LABELS.items():
            ui.label(label).classes("font-semibold mt-2")
            for driver in current["scores"][key]["drivers"]:
                with ui.column().classes("w-full gap-1 border-b py-2 min-w-0"):
                    ui.label(f'{driver["label"]} · {_value(driver["score"], "/100")} · intended weight {driver["weight_pct"]}%').classes("text-sm font-medium break-words")
                    ui.label(driver["detail"]).classes("text-sm break-words")
                    if driver["observations"] is not None:
                        observed = driver["observations"]
                        evidence = (f'Daily summaries: {observed["daily_days"]}/42 days; recent {observed["recent_daily_days"]}/7; recorded activity days: {observed["activity_days"]}; undated activities: {observed["undated_activities"]}'
                            if isinstance(observed, dict) else f'{observed} observed nights')
                        ui.label(evidence).classes("text-xs break-words")
                    source = {"hrv":"Garmin nightly HRV", "rhr":"Garmin sleep/daily resting HR", "sleep":"Garmin sleep duration",
                        "stress":"Garmin prior-day stress", "shortfall":"Recorded sleep and your saved target",
                        "load":"Recorded activity TSS or duration", "recovery":"App Recovery estimate"}[driver["key"]]
                    ui.label(f'Used weight: {driver["used_weight_pct"]:g}% · Source: {source}').classes("text-xs text-slate-600 break-words")
        ui.label("Available weights are renormalized only when minimum evidence is met. Input coverage also reflects baseline nights, observed sleep nights and recorded-load coverage; it does not establish score accuracy.").classes("text-xs break-words")
    with ui.expansion("Garmin comparison · same assessment date", value=True).classes("w-full"):
        ui.label("Comparison only; these Garmin scores are not used in the app's scores.").classes("text-sm break-words")
        with ui.row().classes("w-full gap-3 flex-wrap"):
            for key, label in (("sleep_score", "Garmin sleep score"), ("readiness", "Garmin Training Readiness"), ("body_battery", "Garmin Body Battery at wake")):
                with ui.column().classes("gap-1 min-w-0"):
                    ui.label(label).classes("text-sm")
                    ui.label(_value(current["garmin"][key], " / 100")).classes("font-semibold")
        ui.label("Garmin HRV status: " + str(current["garmin"]["hrv_status"] or "Unavailable")).classes("text-sm break-words")
        ui.label("Garmin sleep need: " + _value(current["garmin"]["sleep_need_minutes"], " min") + " · comparison only").classes("text-sm break-words")
    history = result["history"]
    from plotly import graph_objects as go
    chart = go.Figure()
    for key, label in SCORE_LABELS.items():
        chart.add_trace(go.Scatter(x=[r["date"] for r in history], y=[r["scores"][key]["score"] for r in history],
            name=label, mode="lines+markers", connectgaps=False))
    chart.update_layout(title="Daily app estimates", yaxis=dict(range=[0,100]),
        legend=dict(orientation="h", y=-.25), margin=dict(l=35,r=15,t=55,b=90), height=330)
    ui.plotly(chart).classes("w-full min-w-0")
    with ui.expansion("Daily score history").classes("w-full min-w-0"):
        rows = [dict(date=r["date"], **{k: _value(r["scores"][k]["score"]) for k in SCORE_LABELS},
            coverage=r["scores"]["readiness"]["confidence"]) for r in reversed(history)]
        ui.table(columns=[dict(name=k,field=k,label=k.title(),align="left") for k in rows[0]],
            rows=rows,row_key="date",pagination=10).classes("w-full min-w-0 overflow-auto")
    with ui.expansion("Data sources and calculation policy").classes("w-full"):
        ui.label(f'Policy: {result["policy_version"]} · Sleep target: {result["sleep_target_hours"]:g} h').classes("text-sm break-words")
        ui.label("Personal baselines: prior 28 days; need 14 valid days, including 3 in the last 7. Sleep shortfall needs 5 of 7 nights. Recorded load uses the previous 42 days and existing CTL/ATL calculations.").classes("text-sm break-words")
        for table, source in result["sources"].items():
            detail = (f'{source["sessions"]} recorded sessions; {source["undated"]} undated records' if table == "activity" else f'{source["days"]} recorded dates in the input history window') if source["available"] else "not available"
            ui.label(f'{table.replace("_", " ").title()}: {detail}').classes("text-xs break-words")
        ui.label(result["rr_note"]).classes("text-sm break-words")
        ui.label("Input identity: " + result["input_sha256"]).classes("text-xs break-all")
        ui.link("Garmin HRV context", "https://www.garmin.com/en-IE/garmin-technology/health-science/hrv-status/", new_tab=True)
        ui.link("Adult sleep consensus", "https://www.aasm.org/resources/pdf/adultsleepdurationconsensus.pdf", new_tab=True)
    ui.link("Open existing sleep and recovery trend analysis", "/query")


def register_recovery_page(db_path, *, sandboxed):
    from nicegui import ui, run
    from garmin_data_hub.ui_nicegui.layout import render_shell, page_heading

    @ui.page("/recovery")
    async def recovery_page(assessment_date: str | None = None):
        render_shell("Recovery", db_path, sandboxed=sandboxed)
        with ui.column().classes("gdh-page"):
            page_heading("Recovery & Readiness", "Independent daily estimates with personal baselines, score drivers and Garmin comparisons.")
            with ui.row().classes("w-full items-end gap-3 flex-wrap"):
                assessed = ui.input("Assessment date", value=assessment_date or date.today().isoformat()).props("type=date").classes("w-48")
                period = ui.select({7:"7 days",30:"30 days",90:"90 days"}, value=30, label="History").classes("w-40")
                refresh_button = ui.button("Refresh recovery", icon="refresh")
                latest_button = ui.button("Use latest available day").props("outline")
                latest_button.disable()
            with ui.expansion("Sleep target preference").classes("w-full"):
                with ui.row().classes("w-full items-end gap-3 flex-wrap"):
                    target = ui.number("Nightly sleep target (hours)",value=8,min=6,max=12,step=.25).classes("w-64 max-w-full")
                    save_button = ui.button("Save sleep target").props("outline")
                ui.label("Your planning preference; Garmin sleep need remains a separate comparison. Changing this target updates estimates, not workouts.").classes("text-xs break-words")
            error = ui.label("").classes("text-red-800 break-words").props('role="alert"')
            output = ui.column().classes("w-full min-w-0")
            request = {"id": 0, "latest": None}
            async def refresh():
                request["id"] += 1
                token = request["id"]
                selected_date, selected_period = assessed.value, period.value
                refresh_button.disable()
                latest_button.disable()
                error.text = ""
                output.clear()
                with output:
                    ui.label("Loading recovery estimates…").classes("text-sm")
                try:
                    result = await run.io_bound(recovery_assessment, db_path, assessment_date=selected_date, history_days=selected_period)
                    if token != request["id"]:
                        return
                    if (selected_date, selected_period) != (assessed.value, period.value):
                        output.clear()
                        error.text = "Selections changed while loading. Select Refresh recovery to use the new dates."
                        return
                    request["latest"] = result["latest_signal_date"]
                    latest_button.set_enabled(bool(request["latest"] and request["latest"] != result["assessment_date"]))
                    target.value = result["sleep_target_hours"]
                    output.clear()
                    with output:
                        render_assessment(result)
                except (ValueError, sqlite3.Error, OSError) as exc:
                    if token == request["id"]:
                        latest_button.disable()
                        output.clear()
                        error.text = str(exc) if isinstance(exc, ValueError) else "Recovery data could not be read. Check the database and try Refresh recovery."
                        if isinstance(exc, ValueError):
                            logger.info("Recovery input validation: %s", exc)
                        else:
                            logger.warning("Recovery view could not be loaded", exc_info=True)
                finally:
                    if token == request["id"]:
                        refresh_button.enable()
            async def save():
                save_button.disable()
                try:
                    await run.io_bound(save_sleep_target, db_path, target.value)
                    await refresh()
                    ui.notify("Recovery sleep target saved.", type="positive")
                except (ValueError, sqlite3.Error, OSError) as exc:
                    error.text = str(exc) if isinstance(exc, ValueError) else "Recovery preference could not be saved."
                finally:
                    save_button.enable()
            refresh_button.on_click(refresh)
            async def latest():
                if request["latest"]:
                    assessed.value = request["latest"]
                    await refresh()
            latest_button.on_click(latest)
            save_button.on_click(save)
            await refresh()


def render_recovery_summary(db_path):
    """Compact Dashboard summary loaded outside the event loop."""
    from nicegui import ui, run
    with ui.card().classes("gdh-card w-full min-w-0"):
        ui.label("Recovery & Readiness").classes("text-xl font-semibold")
        output = ui.column().classes("w-full min-w-0")
        async def load():
            try:
                result = await run.io_bound(recovery_assessment, db_path, history_days=1)
                output.clear()
                with output:
                    render_assessment(result, compact=True)
            except (ValueError, sqlite3.Error, OSError):
                logger.warning("Dashboard recovery summary unavailable", exc_info=True)
                output.clear()
                with output:
                    ui.label("Recovery estimates unavailable. Open Recovery to inspect missing data or refresh.").classes("text-sm break-words")
                    ui.link("Open Recovery & Readiness", "/recovery")
        ui.timer(.1, load, once=True)
