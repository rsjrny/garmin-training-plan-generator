"""Reviewed session matching, moved/partial outcomes and recorded weekly volume."""
from __future__ import annotations

from datetime import date, timedelta
import logging
import json
import sqlite3

from garmin_data_hub.analytics.workout_compliance import ALL, pair_evidence
from garmin_data_hub.services.workout_compliance import compliance_view, review_pairs, MatchReviewError
from garmin_data_hub.plan_methodology.revision_repository import CorruptRevisionError
from garmin_data_hub.ui_nicegui.data import distance_from_km, distance_unit, interface_settings

logger = logging.getLogger(__name__)


def _time(value):
    return "Unavailable" if value is None else f"{value/60:g} min"


def _distance(value, units):
    return "Unavailable" if value is None else f'{distance_from_km(value/1000,units):g} {distance_unit(units)}'


def _known_total(text, known, total):
    return text + (" · partial" if 0 < known < total else "")


def _row(row, units):
    return dict(id=row["key"],date=row["date"],workout=row["title"],sport=row["sport"].title(),
        status=row["status"] + (" · " + row["completion"].lower() if row["moved"] else ""),
        planned_time=_time(row["duration_s"]),recorded_time=_time(row["actual_duration_s"]),
        planned_distance=_distance(row["distance_m"],units),recorded_distance=_distance(row["actual_distance_m"],units),
        activity_date=row["actual_date"] or "—",estimates="Estimated target" if row["duration_estimated"] or row["distance_estimated"] else "")


async def render_compliance(db_path, *, season_id="", start_date="", end_date=""):
    from nicegui import ui, run
    from garmin_data_hub.ui_nicegui.layout import metric_card
    units = interface_settings(db_path)["unit_system"]
    ui.label("Suggestions need review. Completed and partial labels compare recorded amounts with planned amounts; moved sessions keep their original planned date.").classes("text-sm break-words")
    with ui.row().classes("w-full items-end gap-3 flex-wrap"):
        start = ui.input("Compliance start",value=start_date or (date.today()-timedelta(days=29)).isoformat()).props("type=date").classes("w-48")
        end = ui.input("Compliance end",value=end_date or date.today().isoformat()).props("type=date").classes("w-48")
        plan = ui.select({ALL:"All active schedules"},value=ALL,label="Compliance schedule").classes("w-72 max-w-full")
        window = ui.select({1:"±1 day",3:"±3 days",7:"±7 days",14:"±14 days"},value=3,label="Matching date window").classes("w-48")
        refresh_button = ui.button("Refresh compliance",icon="refresh")
    error = ui.label("").classes("text-red-800 break-words").props('role="alert"')
    content = ui.column().classes("w-full min-w-0")
    dialogs = ui.column()
    state = {"view":None,"request":0,"initial":True}
    ui.add_css("@media(max-width:600px){.compliance-desktop{display:none!important}} "
        "@media(min-width:601px){.compliance-mobile{display:none!important}}")

    def review_dialog(frozen, pairs, *, reject=False):
        work = {w["key"]:w for w in frozen["data"]["workouts"]}
        activities = {a["id"]:a for a in frozen["snapshot"]["activities"]}
        with dialogs, ui.dialog() as dialog, ui.card().classes("w-full max-w-3xl max-h-[90vh] overflow-y-auto min-w-0"):
            ui.label("Review activity matches").classes("text-xl font-semibold")
            ui.label(f'Reviewed view: {frozen["options"]["start"]} to {frozen["options"]["end"]} · matching window ±{frozen["options"]["window"]} days').classes("text-sm break-words")
            ui.label("Confirm saves a permanent association. Confirming a pair also rejects competing stored pending matches. A rejected suggestion stays unconfirmed.").classes("text-sm break-words")
            selections = []
            for key,aid in pairs[:200]:
                w,a = work[key],activities[aid]
                with ui.card().classes("w-full shadow-none border p-3 min-w-0"):
                    pick = ui.checkbox(f'{w["date"]} · {w["title"]} ↔ {a["date"]} · {a["name"]}',value=True).classes("w-full break-words").props(f'aria-label="Select match activity {aid}"')
                    ui.label(f'Planned: {w["sport"].title()} · {_time(w["duration_s"])} · {_distance(w["distance_m"],units)}').classes("text-sm break-words")
                    ui.label(f'Recorded: {a["sport"] or "Sport unavailable"} · {_time(a["duration_s"])} · {_distance(a["distance_m"],units)}').classes("text-sm break-words")
                    evidence = pair_evidence(w,a,frozen["options"]["window"],manual=True)
                    if w["sport"] == "UNKNOWN":
                        ui.label("Saved sport is unavailable. Your explicit association supplies the recorded activity's sport without changing the saved workout.").classes("text-sm text-amber-900 break-words")
                    for field,ratio in evidence["ratios"].items():
                        ui.label(f'{"Time" if field == "duration_s" else "Distance"}: {ratio*100:.1f}% of planned amount').classes("text-sm")
                    if evidence["missing_measures"] or not evidence["ratios"]:
                        ui.label("Some amounts are unavailable; confirming identity does not invent missing completion measures.").classes("text-sm text-amber-900 break-words")
                    competing = [m for m in frozen["snapshot"]["matches"] if m["status"] == "CANDIDATE" and
                        (m["activity_id"] == aid or m["workout_key"] == key) and (m["activity_id"],m["workout_key"]) != (aid,key)]
                    ui.label(f'{len(competing)} competing stored pending association(s) will be rejected if confirmed.').classes("text-xs break-words")
                    selections.append((pick,key,aid))
            action = ui.radio({"CONFIRMED":"Confirm selected matches","REJECTED":"Reject selected pairs"},value="REJECTED" if reject else "CONFIRMED").props("inline")
            reason = ui.input("Match review reason",value="Reviewed dates, sport and recorded amounts.").classes("w-full")
            ack = ui.checkbox("I reviewed the selected pairs and the confirm/reject decision.").props('aria-label="I reviewed the selected pairs and the confirm/reject decision."').classes("w-full")
            message = ui.label("").classes("text-red-800 break-words").props('role="alert"')
            async def save():
                if not ack.value:
                    message.text = "Review and acknowledge the selected pairs before saving."
                    return
                decisions = [dict(workout_key=key,activity_id=aid,status=action.value) for checkbox,key,aid in selections if checkbox.value]
                save_button.disable()
                try:
                    result = await run.io_bound(review_pairs,db_path,frozen,decisions,reviewer="LOCAL_USER",reason=reason.value)
                    dialog.close()
                    await refresh()
                    ui.notify("Match review saved." if result["status"] == "applied" else "This match review was already saved.",type="positive")
                except (MatchReviewError,sqlite3.Error,OSError,CorruptRevisionError) as exc:
                    message.text = str(exc) if isinstance(exc,MatchReviewError) else "Match evidence could not be read or saved. Refresh compliance and try again."
                    logger.info("Compliance review was not saved: %s",type(exc).__name__)
                finally:
                    save_button.enable()
            with ui.row().classes("w-full justify-end gap-2 flex-wrap"):
                ui.button("Close match review",on_click=dialog.close).props("flat")
                save_button = ui.button("Save match decisions",on_click=save)
        dialog.open()

    def inspect(key):
        frozen = state["view"]
        w = next((w for w in frozen["data"]["workouts"] if w["key"] == key),None)
        if w is None:
            return
        with dialogs, ui.dialog() as dialog, ui.card().classes("w-full max-w-2xl max-h-[90vh] overflow-y-auto min-w-0"):
            ui.label(w["title"]).classes("text-xl font-semibold break-words")
            ui.label(f'{w["date"]} · {w["status"]}' + (" · " + w["completion"] if w["moved"] else "")).classes("font-medium break-words")
            ui.label(w["explanation"]).classes("text-sm break-words")
            ui.label(f'Planned: {_time(w["duration_s"])} · {_distance(w["distance_m"],units)}').classes("text-sm break-words")
            if w["activity_id"] is not None:
                ui.label(f'Activity {w["activity_id"]} · {w["actual_date"] or "date unavailable"} · {_time(w["actual_duration_s"])} · {_distance(w["actual_distance_m"],units)}').classes("text-sm break-words")
                ui.label("This confirmed association is retained with its original workout identity.").classes("text-sm break-words")
            elif not w["rest"]:
                claimed = {m["activity_id"] for m in frozen["snapshot"]["matches"] if m["status"] == "CONFIRMED"}
                possible = [a for a in frozen["snapshot"]["activities"] if a["id"] not in claimed and
                    pair_evidence(w,a,frozen["options"]["window"],manual=True) is not None and a["date"] <= frozen["options"]["today"]]
                ranked = {e["activity_id"]:e for e in frozen["data"]["suggestions"] if e["workout_key"] == key}
                possible.sort(key=lambda a:(-ranked.get(a["id"],{}).get("score",-1),a["date"],a["id"]))
                options = {a["id"]:f'{a["date"]} · {a["name"]} · {_time(a["duration_s"])} · {_distance(a["distance_m"],units)}' for a in possible}
                if options:
                    choice = ui.select(options,value=next(iter(options)),label="Activity to associate").classes("w-full")
                    @ui.refreshable
                    def explain_choice():
                        hint = ranked.get(choice.value)
                        if hint:
                            ui.label(f'Similarity: {hint["confidence"].lower()} · {hint["score"]:g}/100 ranking').classes("text-sm")
                            if hint["ambiguous"]:
                                ui.label("Ambiguous: this activity or workout also fits other nearby sessions. Choose the association you intended.").classes("text-sm text-amber-900 break-words")
                        else:
                            ui.label("Manual association; no confident suggestion is made for this pair.").classes("text-sm break-words")
                    explain_choice()
                    choice.on_value_change(lambda _:explain_choice.refresh())
                    def open_review(reject=False):
                        dialog.close()
                        review_dialog(frozen,[(key,choice.value)],reject=reject)
                    with ui.row().classes("w-full gap-2 flex-wrap"):
                        ui.button("Review this match",on_click=lambda:open_review())
                        ui.button("Reject this pair",on_click=lambda:open_review(True)).props("outline")
                else:
                    ui.label("No unclaimed compatible activity in this matching window. Sync Garmin or widen the date window and refresh.").classes("text-sm break-words")
            ui.link("Open activities", "/activities")
            ui.button("Close session details",on_click=dialog.close).props("flat")
        dialog.open()

    def render(view):
        data = view["data"]
        totals = data["totals"]
        ui.label(f'Displayed view: {view["options"]["start"]} to {view["options"]["end"]} · matching window ±{view["options"]["window"]} days').classes("text-sm break-words")
        with ui.row().classes("w-full gap-3 flex-wrap"):
            for key,label in (("completed","Completed sessions"),("partial","Partial sessions"),("moved","Moved · included above"),("missed","Missed sessions"),("needs_review","Sessions needing review"),("extra","Extra activities")):
                with ui.element("div").classes("min-w-0 flex-1").style("flex-basis:160px").props(f'data-testid="compliance-count-{key}"'):
                    metric_card(label,totals[key])
            metric_card("Current training-day streak","Pending" if totals["current_streak"] is None else totals["current_streak"])
            metric_card("Longest streak · this view",totals["longest_streak"])
        ui.label(f'{totals["completed_due"]} / {totals["due"]} past saved sessions completed or marked done, excluding known rest days. Today, future dates and tentative suggestions do not establish missed sessions.').classes("text-sm break-words")
        if view["snapshot"]["invalid_activity_dates"]:
            ui.label(f'{view["snapshot"]["invalid_activity_dates"]} activities have unusable dates and cannot be suggested.').classes("text-sm text-amber-900 break-words")
        for warning in view["snapshot"]["warnings"]:
            ui.label(warning).classes("text-sm text-amber-900 break-words")
        clear = [(e["workout_key"],e["activity_id"]) for e in data["suggestions"] if e["confidence"] == "HIGH" and e["recommended"]]
        if clear:
            ui.button(f"Review clear suggestions ({len(clear)})",on_click=lambda:review_dialog(view,clear)).props("outline")
        ui.label("Planned sessions").classes("text-xl font-semibold")
        if not data["workouts"]:
            ui.label("No active planned sessions in this view. Choose another schedule or date range.").classes("text-sm break-words")
        else:
            display = [_row(r,units) for r in data["workouts"]]
            with ui.element("div").classes("w-full min-w-0 overflow-auto compliance-desktop"):
                table = ui.table(columns=[dict(name=k,field=k,label=k.replace("_"," ").title(),align="left") for k in display[0] if k != "id"],rows=display,row_key="id",pagination=15).classes("w-full")
                table.add_slot("body-cell-workout",'''<q-td :props="props"><q-btn flat dense no-caps :label="props.row.workout" @click="$parent.$emit('inspect', props.row.id)" /></q-td>''')
                table.on("inspect",lambda e:inspect(e.args))
            page = {"value":1}
            @ui.refreshable
            def mobile():
                with ui.column().classes("w-full min-w-0 compliance-mobile"):
                    for row in display[(page["value"]-1)*10:page["value"]*10]:
                        with ui.card().classes("gdh-card w-full min-w-0 p-3"):
                            ui.label(f'{row["date"]} · {row["status"]}').classes("font-semibold break-words")
                            ui.label(row["workout"]).classes("break-words")
                            ui.label(f'Planned: {row["planned_time"]} · {row["planned_distance"]}').classes("text-sm break-words")
                            ui.label(f'Recorded: {row["recorded_time"]} · {row["recorded_distance"]} · {row["activity_date"]}').classes("text-sm break-words")
                            label = f'Inspect session {row["date"]} {row["workout"]}'
                            ui.button("Inspect session",on_click=lambda _,key=row["id"]:inspect(key)).props(f'outline aria-label={json.dumps(label)}')
                    if len(display) > 10:
                        def change(e):
                            page["value"] = e.value
                            mobile.refresh()
                        ui.pagination(min=1,max=(len(display)+9)//10,value=page["value"],on_change=change)
            mobile()
        with ui.expansion("Recorded activities and extras",value=True).classes("w-full min-w-0"):
            acts = [dict(id=a["id"],date=a["date"],activity=a["name"],sport=a["sport"] or "Unknown",status=a["status"],time=_time(a["duration_s"]),distance=_distance(a["distance_m"],units)) for a in data["activities"]]
            ui.table(columns=[dict(name=k,field=k,label=k.title(),align="left") for k in ("date","activity","sport","status","time","distance")],rows=acts,row_key="id",pagination=10).classes("w-full min-w-0 overflow-auto")
        with ui.expansion("Weekly recorded volume and variance",value=True).classes("w-full min-w-0"):
            ui.label("Completed calendar days only. All-sport time and running distance use actual activity dates; completion is credited to planned dates. Known partial totals are labeled; variance requires complete plan-day and measurement coverage.").classes("text-sm break-words")
            weekly = []
            for w in data["weekly"]:
                weekly.append(dict(week=w["week"],dates=f'{w["start"]} to {w["end"]}' + (" · partial week" if w["partial"] else ""),
                    plan_days=f'{w["plan_days"]}/{w["calendar_days"]}',planned_time=_known_total(_time(w["planned_duration_s"]),w["duration_s_planned_known"],w["duration_s_planned_total"]),recorded_time=_known_total(_time(w["recorded_duration_s"]),w["duration_s_recorded_known"],w["duration_s_recorded_total"]),time_variance=_time(w["duration_s_variance"]),
                    planned_run_distance=_known_total(_distance(w["planned_distance_m"],units),w["distance_m_planned_known"],w["distance_m_planned_total"]),recorded_run_distance=_known_total(_distance(w["recorded_distance_m"],units),w["distance_m_recorded_known"],w["distance_m_recorded_total"]),distance_variance=_distance(w["distance_m_variance"],units),
                    time_measures=f'Planned {w["duration_s_planned_known"]}/{w["duration_s_planned_total"]}; recorded {w["duration_s_recorded_known"]}/{w["duration_s_recorded_total"]}',
                    distance_measures=f'Planned {w["distance_m_planned_known"]}/{w["distance_m_planned_total"]}; recorded {w["distance_m_recorded_known"]}/{w["distance_m_recorded_total"]}'))
            ui.table(columns=[dict(name=k,field=k,label=k.replace("_"," ").title(),align="left") for k in weekly[0]] if weekly else [],rows=weekly,row_key="week",pagination=8).classes("w-full min-w-0 overflow-auto")
        with ui.expansion("Reviewed match history").classes("w-full min-w-0"):
            matches = [dict(id=("legacy:" if m["legacy"] else "canonical:")+str(m.get("legacy_match_id",m.get("activity_workout_match_id"))),
                workout=m["workout_key"],activity=m["activity_id"],status=m["status"],reviewer=m.get("reviewer") or "Unreviewed",reason=(m.get("reason") or "").split(" · {")[0],reviewed=m["updated_at_utc"]) for m in view["snapshot"]["matches"]]
            ui.table(columns=[dict(name=k,field=k,label=k.title(),align="left") for k in ("activity","status","reviewer","reason","reviewed")],rows=matches,row_key="id",pagination=10).classes("w-full min-w-0 overflow-auto")
        ui.label("80% is an amount-completion tolerance, not an intensity or fitness assessment. Missing values stay unavailable. Streaks describe this date/schedule view. Recorded data can be incomplete until Garmin sync.").classes("text-xs break-words")

    async def refresh():
        state["request"] += 1
        token = state["request"]
        chosen = (start.value,end.value,window.value,plan.value)
        refresh_button.disable()
        error.text = ""
        content.clear()
        try:
            view = await run.io_bound(compliance_view,db_path,start=chosen[0],end=chosen[1],window=chosen[2],plan_id=chosen[3])
            if token != state["request"]:
                return
            if chosen != (start.value,end.value,window.value,plan.value):
                error.text = "Selections changed while loading. Refresh compliance for the new view."
                return
            plan.options = {ALL:"All active schedules",**{p["id"]:p["name"] for p in view["snapshot"]["plans"]}}
            plan.update()
            if state["initial"] and season_id:
                from garmin_data_hub.services.season_plans import get_season, SeasonError
                try:
                    season = get_season(db_path,season_id)
                    initial = season.plan_id
                except SeasonError:
                    initial = None
                state["initial"] = False
                if initial in plan.options:
                    plan.value = initial
                    await refresh()
                    return
            state["view"] = view
            with content:
                render(view)
        except (MatchReviewError,sqlite3.Error,OSError,CorruptRevisionError) as exc:
            error.text = str(exc) if isinstance(exc,MatchReviewError) else "Compliance evidence could not be read. Check the database and refresh."
            logger.warning("Compliance view unavailable: %s",type(exc).__name__)
        finally:
            if token == state["request"]:
                refresh_button.enable()
    refresh_button.on_click(refresh)
    await refresh()
