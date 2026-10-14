"""Presentation helpers for yearly planning; never changes stored prescriptions."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

PACE_METRES = {"Metric": Decimal(1000), "Imperial": Decimal("1609.344")}
REASONS = {
    "outside_range": "Outside the affected dates", "outside_manual_edit": "Outside this workout edit",
    "history": "Past workout", "completed": "Completed workout", "locked": "Locked workout",
    "manually_edited": "Manually edited workout", "manually_created": "Manually created workout",
    "unresolved_match": "Activity match needs review", "unchanged": "Workout is unchanged",
}


def friendly_reason(value):
    return REASONS.get(value, value.replace("_", " ").capitalize())


def friendly_phase(value):
    return {"EVENT_SPECIFIC": "Event preparation", "MAINTENANCE": "General fitness", "EVENT": "Event day",
            "PHASE_UNAVAILABLE": "Phase unavailable"}.get(value, (value or "Phase unavailable").replace("_", " ").title())


def friendly_intensity(value):
    if not value:
        return "Target unavailable"
    parts = []
    for part in str(value).split(" · "):
        if part.startswith("F80.ZONE_"):
            part = "80/20 zone " + part.removeprefix("F80.ZONE_")
        elif part.startswith("MAF."):
            part = {"MAF.MAF_AEROBIC_RANGE":"MAF aerobic range", "MAF.MAF_CEILING":"MAF heart-rate ceiling",
                    "MAF.SUB_MAF":"Below the MAF range"}.get(part, part.removeprefix("MAF.").replace("_", " ").capitalize())
        parts.append(part)
    return " · ".join(parts)


def calendar_dates(year, *, today, mode="Calendar year"):
    start = today if mode == "Start today" and year == today.year else date(year, 1, 1)
    return start.isoformat(), date(year, 12, 31).isoformat()


def pace_text(speed_mps, unit_system):
    if speed_mps is None:
        return ""
    seconds = round(PACE_METRES[unit_system] / Decimal(str(speed_mps)))
    return f"{seconds // 60:02}:{seconds % 60:02}"


def pace_speed(seconds, unit_system):
    return format(PACE_METRES[unit_system] / Decimal(seconds), "f")


def describe_workout(workout):
    if workout is None:
        return "Workout unavailable"
    minutes = sum(s.duration_seconds for s in workout.segments) / 60 if all(s.duration_seconds is not None for s in workout.segments) else None
    targets = " · ".join(sorted({friendly_intensity(s.prescription.native_target.value) for s in workout.segments if s.prescription}))
    return " · ".join(filter(None, (workout.title, f"{minutes:g} min" if minutes is not None else "Duration unknown", targets)))


def change_rows(diff, workouts, parent_workouts=()):
    """One row per replacement, plus disjoint additions/removals/preserved rows."""
    proposed = {w.workout_id: w for w in workouts}
    previous = {w.workout_id: w for w in parent_workouts}
    removed = {w["workout_id"]: w for w in diff.get("removed", ())}
    paired_new, paired_old = set(), set()
    rows = []
    for pair in diff.get("changed", ()):
        old_id, new_id = pair["old_workout_id"], pair["new_workout_id"]
        paired_new.add(new_id)
        paired_old.add(old_id)
        old, new = removed.get(old_id, {}), proposed.get(new_id)
        rows.append(dict(id="change:" + old_id, date=pair["date"], action="Changed",
                         before=describe_workout(previous[old_id]) if old_id in previous else old.get("title", "Previous workout"), after=describe_workout(new),
                         reason="Event or training settings changed"))
    for wid in diff.get("added_workout_ids", ()):
        if wid not in paired_new and wid in proposed:
            w = proposed[wid]
            rows.append(dict(id="add:" + wid, date=w.scheduled_date.isoformat(), action="Added",
                             before="—", after=describe_workout(w), reason="New workout"))
    for wid in diff.get("removed_workout_ids", ()):
        if wid not in paired_old:
            w = removed.get(wid, {})
            rows.append(dict(id="remove:" + wid, date=w.get("date", ""), action="Removed",
                             before=w.get("title", "Previous workout"), after="—", reason="No longer scheduled"))
    unchanged = [dict(id="keep:" + w["workout_id"], date=w["date"], action="Unchanged",
                      before=w["title"], after=w["title"], reason=", ".join(friendly_reason(r) for r in w["reasons"]))
                 for w in diff.get("preserved", ())]
    return sorted(rows, key=lambda r: (r["date"], r["id"])), sorted(unchanged, key=lambda r: (r["date"], r["id"]))


def change_counts(diff):
    pairs = diff.get("changed", ())
    new_ids = {p["new_workout_id"] for p in pairs}
    old_ids = {p["old_workout_id"] for p in pairs}
    return dict(changed=len(pairs), added=len(set(diff.get("added_workout_ids", ())) - new_ids),
                removed=len(set(diff.get("removed_workout_ids", ())) - old_ids),
                unchanged=len(diff.get("preserved_workout_ids", ())))


def workout_counts(rows):
    def kind(row):
        sport = str(row.get("sport") or "").upper()
        if sport == "REST" or str(row.get("workout") or "").strip().lower() in {"rest", "rest day"}:
            return "rest"
        if sport == "STRENGTH":
            return "strength"
        if sport in {"RUNNING", "RUN"}:
            return "running"
        return "other"
    return {k: sum(kind(r) == k for r in rows) for k in ("running", "strength", "rest", "other")}


def week_start(today, rows):
    if rows and not any(r["date"] >= today.isoformat() for r in rows):
        day = date.fromisoformat(rows[-1]["date"])
    elif rows and rows[0]["date"] > today.isoformat():
        day = date.fromisoformat(rows[0]["date"])
    else:
        day = today
    return day - timedelta(days=day.weekday())


def default_yearly_plan(seasons, *, today):
    active = [s for s in seasons if s.status != "archived"]
    candidates = active or list(seasons)
    if not candidates:
        return None
    current = [s for s in candidates if s.start_date <= today.isoformat() <= s.end_date]
    if current:
        return max(current,key=lambda s:s.start_date)
    future = [s for s in candidates if s.start_date > today.isoformat()]
    return min(future,key=lambda s:s.start_date) if future else max(candidates,key=lambda s:s.end_date)


def planning_tabs(season_id, current):
    from nicegui import ui
    from garmin_data_hub.ui_nicegui.yearly_workflow import yearly_url
    with ui.row().classes("w-full gap-2 flex-wrap").props('aria-label="Yearly plan views"'):
        for label, route, parameters in (
            ("Overview", "/plan", {"view": "overview"}),
            ("Events", "/seasons", {"section": "events"}),
            ("Settings", "/seasons", {"section": "settings"}),
            ("Workouts", "/plan", {"view": "workouts"}),
        ):
            with ui.link(target=yearly_url(route, season_id, **parameters)).classes("no-underline"):
                ui.button(label).props("unelevated" if current == label.lower() else "outline")


def render_week(rows, unit_system, *, today, on_week_change=None, week_state=None, markers=(), calendar_view=False):
    from nicegui import ui
    from garmin_data_hub.ui_nicegui.data import distance_from_km, distance_unit
    selected = week_state if week_state is not None else {}
    selected.setdefault("monday",week_start(today,rows))
    if calendar_view:
        ui.add_css(".plan-week-grid{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:8px;min-width:1120px}"
            "@media(max-width:700px){.plan-week-grid{grid-template-columns:1fr;min-width:0}}")

    @ui.refreshable
    def week():
        monday = selected["monday"]
        sunday = monday + timedelta(days=6)
        if on_week_change:
            on_week_change([r for r in rows if monday.isoformat() <= r["date"] <= sunday.isoformat()])
        with ui.row().classes("w-full items-center justify-between gap-2 flex-wrap"):
            ui.label(f"{monday:%b %d} – {sunday:%b %d, %Y}").classes("font-semibold").props('data-testid="workout-week"')
            def move(days):
                selected["monday"] += timedelta(days=days)
                week.refresh()
            def jump():
                selected["monday"] = today - timedelta(days=today.weekday())
                week.refresh()
            with ui.row().classes("gap-1"):
                ui.button(icon="chevron_left", on_click=lambda: move(-7)).props('flat round aria-label="Previous week"')
                ui.button("Today", on_click=jump).props('outline aria-label="Jump to today"')
                ui.button(icon="chevron_right", on_click=lambda: move(7)).props('flat round aria-label="Next week"')
        if calendar_view:
            from garmin_data_hub.analytics.plan_calendar import calendar_week
            summary = calendar_week(rows,monday)
            with ui.row().classes("w-full gap-2 items-end flex-wrap"):
                chosen = ui.input("Week containing",value=monday.isoformat()).props("type=date").classes("w-48")
                error = ui.label("").classes("text-sm text-red-800 break-words").props('role="alert"')
                def go():
                    try:
                        day = date.fromisoformat(chosen.value)
                    except (TypeError,ValueError):
                        error.text = "Choose a valid calendar date."
                        return
                    selected["monday"] = day-timedelta(days=day.weekday())
                    week.refresh()
                ui.button("Go to week",on_click=go).props("outline")
            ui.label(f'{summary["training_days"]} training days · {summary["sessions"]} sessions · {summary["rest_days"]} saved rest days · {summary["unclassified"]} unclassified sessions').classes("text-sm break-words").props('data-testid="calendar-week-summary"')
            time,dist = summary["amounts"]["duration_min"],summary["amounts"]["distance_km"]
            amount_parts = []
            for measure,label,formatted in ((time,"Known time",f'{time["value"]:g} min' if time["value"] is not None else "unavailable"),
                    (dist,"Known running distance",f'{distance_from_km(dist["value"],unit_system):g} {distance_unit(unit_system)}' if dist["value"] is not None else "unavailable")):
                amount_parts.append(label+": "+formatted+(f' · partial ({measure["missing"]} missing)' if measure["missing"] else ""))
            ui.label(" · ".join(amount_parts)).classes("text-sm break-words")
            def day_labels(values):
                return ", ".join(f"{date.fromisoformat(d):%a %b %d}" for d in values) or "none labeled"
            ui.label("Hard sessions: "+day_labels(summary["hard"])+" · Long runs: "+day_labels(summary["long"])+" · Strength: "+day_labels(summary["strength"])).classes("text-sm break-words")
            if summary["adjacent"]:
                ui.label("Consecutive hard-session dates: "+", ".join(f"{date.fromisoformat(a):%a %b %d} → {date.fromisoformat(b):%a %b %d}" for a,b in summary["adjacent"])).classes("text-sm text-amber-900 break-words").props('data-testid="calendar-spacing"')
            if summary["multiple"]:
                ui.label("Multiple training sessions: "+day_labels(summary["multiple"])).classes("text-sm break-words")
            ui.label("Labels reflect saved workout flags, not an effort assessment. Missing sport/intensity remains unclassified; no saved workout does not imply rest. Event markers are saved intent and may await plan review.").classes("text-xs text-slate-600 break-words")
        outer = ui.element("div").classes("w-full min-w-0 overflow-x-auto") if calendar_view else ui.column().classes("w-full min-w-0")
        if calendar_view:
            outer.props('tabindex="0" role="region" aria-label="Seven-day calendar" data-testid="plan-calendar"')
        with outer:
            grid = ui.element("div").classes("plan-week-grid") if calendar_view else ui.column().classes("w-full min-w-0")
        with grid:
            for offset in range(7):
                render_day(monday+timedelta(days=offset))

    def render_day(day):
        workouts = [r for r in rows if r["date"] == day.isoformat()]
        with ui.card().classes("w-full p-3 gap-1 shadow-none border min-w-0").props(f'data-testid="calendar-day-{day.isoformat()}"'):
            ui.label(f"{day:%a, %b %d}" + (" · Today" if day == today else "")).classes("font-semibold")
            for marker in markers:
                if marker["date"] == day.isoformat():
                    priority = marker.get("priority","C")
                    ui.label(f'{priority} · {marker["name"]} · '+("Calendar marker" if priority=="C" else "Saved event")).classes("text-sm font-medium break-words")
                    if priority == "C":
                        ui.label("Follow the planned workout; fit this event into that session.").classes("text-xs text-slate-500 break-words")
            if not workouts:
                ui.label("No workout scheduled").classes("text-sm text-slate-500")
            for row in workouts:
                if calendar_view:
                    meta = row.get("calendar",{})
                    tags = [(meta.get("hard") is True,"Hard","orange-9"),(meta.get("long") is True,"Long run","blue-9"),
                            (meta.get("event") is True,"Race / event","red-9"),
                            (row.get("sport")=="STRENGTH","Strength","purple-9"),(row.get("sport")=="MOBILITY","Mobility","teal-9"),
                            (row.get("sport")=="REST","Rest","grey-8"),(meta.get("kind_known") is False,"Unclassified","grey-8")]
                    if meta.get("hard") is None and row.get("sport") == "RUNNING":
                        tags.append((True,"Intensity unlabeled","grey-8"))
                    with ui.row().classes("gap-1 flex-wrap"):
                        for show,label,color in tags:
                            if show:
                                ui.badge(label,color=color)
                ui.label(row["workout"]).classes("font-medium break-words")
                details = []
                if row.get("duration_min") is not None:
                    details.append(f'{row["duration_min"]:g} min')
                if row.get("distance_km") is not None:
                    details.append(f'{distance_from_km(row["distance_km"], unit_system):g} {distance_unit(unit_system)}')
                details.append(friendly_phase(row.get("phase")))
                if row.get("intensity"):
                    details.append(friendly_intensity(row["intensity"]))
                ui.label(" · ".join(details)).classes("text-sm break-words")
                if calendar_view and row.get("calendar",{}).get("estimated"):
                    ui.label("Includes estimated targets").classes("text-xs text-slate-500")
                if row.get("protection"):
                    ui.label(row["protection"]).classes("text-xs text-slate-500")
                if row.get("notes"):
                    with ui.expansion("Workout details").classes("w-full min-w-0"):
                        ui.label(row["notes"]).classes("whitespace-pre-wrap break-words text-sm")
    week()
