"""Dashboard annual phase graphic and equivalent keyboard-accessible details."""
from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from nicegui import run, ui

from garmin_data_hub.analytics.yearly_plan import prepare_yearly_timeline, timeline_years
from garmin_data_hub.services.yearly_plan_data import yearly_plan_snapshot, yearly_plan_signature
from garmin_data_hub.ui_nicegui.yearly_workflow import render_workflow, yearly_url


def _amount(value, estimated, divisor, unit):
    if value is None:
        return "Unknown"
    return f'{value / divisor:,.2f} {unit}' + (" (estimated)" if estimated else "")


def render_yearly_plan(db_path: Path, unit_system: str, *, season_id: str = "", year: int = 0, compact: bool = False):
    imperial = unit_system == "Imperial"
    distance_divisor, unit = (1609.344, "mi") if imperial else (1000, "km")
    state = dict(snapshot=None, error=None, year=year or date.today().year, selected="season:" + season_id if season_id else None)
    ui.add_css("""
        .d1-scroll { width:100%; overflow-x:auto; border:1px solid #cbd5e1; border-radius:10px; }
        .d1-timeline { min-width:1040px; position:relative; padding:12px 0; color:#0f172a; background:white; }
        .d1-months { display:flex; font-size:12px; font-weight:600; margin-bottom:12px; }
        .d1-month { border-left:1px solid #cbd5e1; padding-left:8px; }
        .d1-track { position:relative; height:58px; margin-bottom:10px; }
        .d1-block { position:absolute; height:54px; min-width:0; padding:0 3px !important;
                    border:1px solid #64748b; border-radius:3px !important; font-size:12px; }
        .d1-block .q-btn__content { white-space:nowrap; overflow:hidden; flex-wrap:nowrap; }
        .d1-block:focus-visible, .d1-event:focus-visible { outline:3px solid #1d4ed8; outline-offset:2px; z-index:4; }
        .d1-gap { background-image:repeating-linear-gradient(135deg,transparent,transparent 6px,#cbd5e1 6px,#cbd5e1 7px); }
        .d1-today { position:absolute; top:34px; bottom:10px; border-left:2px dashed #334155; pointer-events:none; z-index:2; }
        .d1-today-label { position:absolute; top:0; font-size:11px; font-weight:700; }
        .d1-events { position:relative; }
        .d1-event { position:absolute; width:180px; min-height:42px; font-size:11px; padding:4px !important;
                    background:#f8fafc; color:#0f172a; border:1px solid #64748b; }
        .d1-event .q-btn__content { white-space:pre-line; line-height:14px; max-height:42px; overflow:hidden; }
        .d1-pin { position:absolute; width:2px; height:12px; background:#475569; pointer-events:none; }
        .d1-table { max-width:100%; overflow-x:auto; }
    """)

    def load():
        try:
            state["snapshot"] = yearly_plan_snapshot(db_path)
            state["error"] = None
        except Exception:
            state["snapshot"] = None
            state["error"] = "Yearly plan unavailable: the active schedule or its phase evidence could not be verified. Review Plan or yearly settings, then refresh."

    load()
    if season_id and not year and state["snapshot"]:
        chosen = next((s for s in state["snapshot"]["selections"] if s["season_id"] == season_id), None)
        if chosen and not chosen["start"] <= date.today().isoformat() <= chosen["end"]:
            state["year"] = int(chosen["start"][:4])

    with ui.card().classes("gdh-card w-full min-w-0"):
        with ui.row().classes("w-full justify-between items-center gap-3 flex-wrap"):
            ui.label("Yearly training plan").classes("text-xl font-semibold")
            async def refresh():
                await run.io_bound(load)
                content.refresh()
            ui.button("Refresh yearly plan", icon="refresh", on_click=refresh).props("outline")

        @ui.refreshable
        def content():
            if state["error"]:
                ui.label(state["error"]).classes("text-warning")
                ui.link("Review Plan", "/plan")
                ui.link("Yearly settings", "/seasons")
                return
            snapshot = state["snapshot"]
            if season_id and not any(s["id"] == state["selected"] for s in snapshot["selections"]):
                ui.label("Selected yearly plan not found. Choose another plan.").classes("text-warning")
                ui.link("Choose yearly plan", "/")
                return
            # Current day uses season-local time where available, matching generation.
            chosen = next((s for s in snapshot["selections"] if s["id"] == state["selected"]), None)
            if chosen is None:
                chosen = prepare_yearly_timeline(snapshot, state["year"])["selection"]
            today = datetime.now(ZoneInfo(chosen["timezone"])).date() if chosen and chosen["timezone"] else date.today()
            data = prepare_yearly_timeline(snapshot, state["year"], state["selected"], today=today)
            selected = data["selection"]
            state["selected"] = selected["id"] if selected else None
            with ui.row().classes("w-full items-center gap-3 flex-wrap"):
                def year_changed(e):
                    state["year"] = e.value
                    content.refresh()
                ui.select({y: str(y) for y in sorted(set(timeline_years(snapshot, today)) | {state["year"]})},
                          value=state["year"], label="Timeline year", on_change=year_changed).classes("w-36")
                if snapshot["selections"] and not compact:
                    options = {s["id"]: s["name"] + (" · archived" if s["archived"] else "") +
                               (" · older saved plan" if s.get("legacy") else " · settings saved; no active workouts" if not s["revision_id"] else "") + f' ({s["start"]} – {s["end"]})'
                               for s in snapshot["selections"]}
                    def season_changed(e):
                        state["selected"] = e.value
                        chosen = next(s for s in snapshot["selections"] if s["id"] == e.value)
                        if chosen["season_id"]:
                            ui.navigate.to(yearly_url("/",chosen["season_id"],year=state["year"]))
                        else:
                            content.refresh()
                    ui.select(options, value=state["selected"], label="Selected yearly plan",
                              on_change=season_changed).classes("flex-1 min-w-0").style("min-width:220px;max-width:100%")
                ui.link("Review Plan", yearly_url("/plan",selected["season_id"] if selected else ""))
                ui.link("Yearly settings", yearly_url("/seasons",selected["season_id"] if selected else "",section="settings"))
            if snapshot["unmanaged"]:
                ui.label(f'{snapshot["unmanaged"]} legacy/unmanaged schedule rows are available under Saved workout schedule. Their saved phases are shown where present; missing phases are labeled unavailable.').classes("text-sm text-warning")
            if selected is None:
                ui.label("No yearly plan is available. Create a yearly plan from Plan.").classes("text-grey-7")
                return
            if selected["season_id"] and not compact:
                render_workflow(db_path,selected["season_id"])
            if selected["archived"]:
                ui.label("Archived yearly plan · its applied schedule remains visible.").classes("text-sm")
            if selected.get("legacy"):
                ui.label("Existing saved workout schedule · older format. Phases come from saved workout metadata; dates with workouts but no phase are Phase unavailable. Race priorities and season associations are unknown; this view does not convert or link the plan.").classes("text-sm")
            elif not selected["revision_id"]:
                ui.label("Settings saved · no active training schedule. Finish setup and apply an initial yearly plan to see its phases.").classes("text-sm")
            else:
                ui.label("Phases follow the applied schedule. Carried workouts retain their original phase and event context. Event intent markers show changes awaiting application.").classes("text-sm text-slate-600")
            goal = selected.get("baseline_goal")
            if isinstance(goal, dict) and goal.get("schema_version") == "baseline-distance-goal.v1":
                from garmin_data_hub.services.season_baseline import goal_label
                ui.label("Applied baseline goal: " + goal_label(goal.get("distance_code"))).classes("text-sm break-words")
            ui.label(f'{data["year"]} overview · scroll horizontally for month and event detail on a small screen.').classes("text-xs text-slate-600")

            with ui.dialog() as dialog, ui.card().classes("w-full max-w-3xl min-w-0"):
                dialog_heading = ui.label().classes("text-xl font-semibold")
                dialog_body = ui.column().classes("w-full min-w-0")
                ui.button("Close timeline details", on_click=dialog.close).props("flat")

            blocks = {b["id"]: b for b in data["blocks"]}
            events = {e["key"]: e for e in data["events"]}
            def open_details(identity):
                dialog_body.clear()
                with dialog_body:
                    if identity in blocks:
                        b = blocks[identity]
                        dialog_heading.text = b["label"]
                        ui.label(f'{b["start"]} to {b["end"]} · inclusive dates')
                        if b["start"] != b["visible_start"] or b["end"] != b["visible_end"]:
                            ui.label(f'Displayed in {data["year"]}: {b["visible_start"]} to {b["visible_end"]}. Details cover the full block.')
                        if b["phase"] == "UNPLANNED":
                            ui.label("No applied workouts on these dates. Event intent does not establish a training phase.")
                        elif b["phase"] in {"PHASE_UNAVAILABLE", "MIXED_PHASES"}:
                            ui.label("Stored workouts do not supply one consistent phase for these dates; no phase was inferred.")
                        if selected.get("legacy"):
                            ui.label("Saved older-format targets · shown conservatively as estimates; no canonical revision or event association is claimed.")
                        for source in b["sources"]:
                            ui.label("Phase source: " + source.replace("_", " ").title()).classes("text-sm break-words")
                        for anchor, index, cycle_start, cycle_end in b["cycles"]:
                            ui.label(f"Baseline cycle {index + 1}: {cycle_start} → {cycle_end} · anchor {anchor}").classes("text-sm break-words")
                        if b["preserved"]:
                            ui.label("Preserved original context · carried workouts retain their prior phase and event association.")
                        for e in b["events"]:
                            ui.label(f'{e["priority"]} · {e["name"]} · {e["date"]} (original applied context)')
                        if b["weekly"]:
                            ui.label(f'{b["sessions"]} planned sessions · full block')
                            ui.label("Time: " + _amount(b["duration_s"], b["duration_estimated"], 3600, "h") +
                                     " · Distance: " + _amount(b["distance_m"], b["distance_estimated"], distance_divisor, unit))
                            ui.label("Weekly rows cover this block only; partial weeks are labeled. Unknown means at least one workout lacks the whole-workout measure. Rest contributes zero.").classes("text-sm")
                            rows = [dict(week=w["week"], dates=f'{w["start"]} to {w["end"]}' + (" · partial" if w["partial"] else ""),
                                cutback="Yes" if w["cutback"] else "No",
                                sessions=w["sessions"], time=_amount(w["duration_s"], w["duration_estimated"], 3600, "h"),
                                distance=_amount(w["distance_m"], w["distance_estimated"], distance_divisor, unit)) for w in b["weekly"]]
                            _table(rows, "week")
                    elif identity in events:
                        e = events[identity]
                        dialog_heading.text = e["name"]
                        ui.label(f'{e["date"]} · {e["priority"]} priority · {e["source"]}')
                        ui.label("Distance: " + _amount(e["distance_m"], e.get("distance_estimated", False), distance_divisor, unit))
                        if e.get("marker_only") or (e["priority"] == "C" and e["source"].startswith("Event intent")):
                            ui.label("Calendar marker only. Follow the planned workout and fit the event into that session. No preparation, taper or recovery is added.").classes("break-words")
                        if e.get("preserved"):
                            ui.label("Preserved event from its original applied schedule.")
                        if e.get("intent_status") == "cancelled":
                            ui.label("Cancelled in current event intent; the accepted calendar marker remains until the update is applied." if e.get("marker_only") else "Cancelled in current event intent; the applied event session is still retained.")
                    else:
                        return
                    ui.link("Open Plan", yearly_url("/plan",selected["season_id"]))
                    ui.link("Edit yearly settings", "/seasons" + ("?" + urlencode({"season_id": selected["season_id"]}) if selected["season_id"] else ""))
                dialog.open()

            with ui.element("div").classes("d1-scroll").props('tabindex="0" role="region" aria-label="Yearly phase timeline, horizontally scrollable"'):
                with ui.element("div").classes("d1-timeline"):
                    with ui.element("div").classes("d1-months"):
                        for m in data["months"]:
                            ui.label(m["name"]).classes("d1-month").style(f'width:{m["width"] * 100}%;flex:none')
                    with ui.element("div").classes("d1-track"):
                        for b in data["blocks"]:
                            label = f'{b["label"]} · {b["start"]} to {b["end"]}'
                            ui.button(b["label"] if b["width"] > .045 else "", color=None, on_click=lambda _, key=b["id"]: open_details(key)).classes(
                                "d1-block" + (" d1-gap" if b["phase"] in {"UNPLANNED", "PHASE_UNAVAILABLE"} else "")).style(
                                f'left:{b["offset"] * 100}%;width:{b["width"] * 100}%;background-color:{b["color"]};color:#0f172a').props(
                                f'no-caps unelevated aria-label={json.dumps(label)}').tooltip(label)
                    # Place labels on independent lanes; anchors retain exact event dates.
                    lanes = []
                    positioned = []
                    for e in data["events"]:
                        left = min(max(e["offset"] - .08, 0), 1 - 180 / 1040)
                        lane = next((i for i, right in enumerate(lanes) if right + .012 < left), len(lanes))
                        if lane == len(lanes):
                            lanes.append(0)
                        lanes[lane] = left + 180 / 1040
                        positioned.append((e, left, lane))
                    with ui.element("div").classes("d1-events").style(f'height:{max(1, len(lanes)) * 64}px'):
                        for e, left, lane in positioned:
                            ui.element("div").classes("d1-pin").style(f'left:{e["offset"] * 100}%;top:{lane * 64}px')
                            label = f'{e["priority"]} · {e["name"]} · {e["date"]} · {e["source"]}'
                            ui.button(f'{e["priority"]} · {e["name"]}\n{e["date"]}', color=None, on_click=lambda _, key=e["key"]: open_details(key)).classes("d1-event").style(
                                f'left:{left * 100}%;top:{lane * 64 + 12}px' + (";border-style:dashed" if e["source"] == "Event intent · not applied" else "")).props(
                                f'no-caps unelevated aria-label={json.dumps(label)}').tooltip(label)
                    if data["today_offset"] is not None:
                        ui.element("div").classes("d1-today").style(f'left:{data["today_offset"] * 100}%')
                        ui.label("Today").classes("d1-today-label").style(f'left:{min(data["today_offset"] * 100, 95)}%')
            with ui.row().classes("gap-2 flex-wrap items-center"):
                for phase, color in dict((b["label"], b["color"]) for b in data["blocks"]).items():
                    ui.label(phase).classes("text-xs px-2 py-1 rounded").style(f'background:{color};color:#0f172a;border:1px solid #94a3b8')
                ui.label("Solid events: saved schedule · dashed events: intent · ?: priority unknown").classes("text-xs")
            # Selects/buttons supply large keyboard/pointer targets for one-day blocks.
            choices = {b["id"]: f'{b["label"]} · {b["start"]} to {b["end"]}' for b in data["blocks"]}
            choices.update({e["key"]: f'{e["priority"]} · {e["name"]} · {e["date"]} · {e["source"]}' for e in data["events"]})
            with ui.row().classes("w-full gap-3 flex-wrap items-center"):
                pick = ui.select(choices, value=next(iter(choices), None), label="Inspect timeline block or event").classes("flex-1 min-w-0").style("min-width:220px;max-width:100%")
                ui.button("Show timeline details", on_click=lambda: open_details(pick.value)).props("outline")
            with ui.expansion("Phase and event table", icon="table_view").classes("w-full min-w-0"):
                rows = [dict(id=b["id"], phase=b["label"], start=b["start"], end=b["end"],
                             event="; ".join(e["name"] for e in b["events"]) or "—",
                             source="Unplanned" if b["phase"] == "UNPLANNED" else "Saved legacy schedule" if selected.get("legacy") else "Preserved original context" if b["preserved"] else "Applied schedule") for b in data["blocks"]]
                rows += [dict(id=e["key"], phase="Event " + e["priority"], start=e["date"], end=e["date"], event=e["name"], source=e["source"]) for e in data["events"]]
                table = _table(rows, "id")
                table.add_slot("body-cell-phase", """<q-td :props="props"><q-btn flat dense no-caps :label="props.row.phase" @click="$parent.$emit('inspect', props.row.id)" /></q-td>""")
                table.on("inspect", lambda e: open_details(e.args))
        content()

        async def check_revision():
            try:
                signature = await run.io_bound(yearly_plan_signature, db_path)
                if state["snapshot"] is None or signature != state["snapshot"]["signature"]:
                    await refresh()
            except Exception:
                if state["error"] is None:
                    state["error"] = "Yearly plan unavailable: refresh when the database is accessible."
                    content.refresh()
        ui.timer(5, check_revision)


def _table(rows, key):
    fields = [k for k in rows[0] if k != "id"] if rows else []
    return ui.table(columns=[dict(name=k, field=k, label=k.replace("_", " ").title(), align="left") for k in fields],
                    rows=rows, row_key=key, pagination=10).classes("w-full d1-table")
