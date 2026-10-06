"""Pure annual phase timeline preparation; never reconstruct phases from intent."""
from __future__ import annotations

import calendar
from datetime import date, timedelta

DAY = timedelta(days=1)
PHASE_COLORS = {
    "BASE": "#dbeafe", "BUILD": "#bfdbfe", "EVENT_SPECIFIC": "#ddd6fe",
    "PEAK": "#fbcfe8", "TAPER": "#fde68a", "EVENT": "#fecaca",
    "RACE": "#fecaca",
    "RECOVERY": "#a7f3d0", "MAINTENANCE": "#cbd5e1", "TRANSITION": "#cffafe",
    "UNPLANNED": "#f1f5f9", "PHASE_UNAVAILABLE": "#e5e7eb", "MIXED_PHASES": "#fed7aa",
}


def phase_label(phase):
    return phase.replace("_", " ").title()


def _totals(workouts):
    result = {"sessions": sum(not w["rest"] for w in workouts)}
    for field in ("duration_s", "distance_m"):
        values = [w[field] for w in workouts]
        result[field] = float(sum(values)) if values and all(v is not None for v in values) else None
        flag = "duration_estimated" if field == "duration_s" else "distance_estimated"
        result[flag] = any(w[flag] for w in workouts)
    return result


def timeline_years(snapshot, today):
    years = {today.year}
    for selection in snapshot["selections"]:
        days = [selection["start"], selection["end"]]
        days += [w["date"] for w in selection["workouts"]]
        days += [e["date"] for e in selection["intent_events"] + selection["applied_events"]]
        years.update(date.fromisoformat(d).year for d in days)
    return sorted(years)


def prepare_yearly_timeline(snapshot, year, selection_id=None, *, today=None):
    today = today or date.today()
    if type(year) is not int or not 1 <= year <= 9998:
        raise ValueError("Choose a supported year.")
    first, finish = date(year, 1, 1), date(year + 1, 1, 1)
    days_in_year = (finish - first).days
    selections = snapshot["selections"]
    selected = next((s for s in selections if s["id"] == selection_id), None)
    if selected is None and selections:
        selected = next((s for s in selections if not s["archived"] and s["workouts"] and s["start"] <= today.isoformat() <= s["end"]),
                        next((s for s in selections if not s["archived"] and s["workouts"]),
                             next((s for s in selections if not s["archived"]), selections[0])))
    data = dict(year=year, selection=selected, blocks=[], events=[], unmanaged=snapshot["unmanaged"],
        days=days_in_year, today=today.isoformat(),
        today_offset=((today - first).days + .5) / days_in_year if first <= today < finish else None,
        months=[dict(name=calendar.month_abbr[m], width=calendar.monthrange(year, m)[1] / days_in_year)
                for m in range(1, 13)])
    if selected is None:
        return data
    by_date = {}
    for w in selected["workouts"]:
        by_date.setdefault(date.fromisoformat(w["date"]), []).append(w)
    # Build full blocks before clipping so details retain actual date ranges.
    full = []
    for day in sorted(by_date):
        rows = by_date[day]
        phases = {w["phase"] or "PHASE_UNAVAILABLE" for w in rows}
        phase = next(iter(phases)) if len(phases) == 1 else "MIXED_PHASES"
        associations = {(w["event"]["id"], w["event"]["name"], w["event"]["date"], w["event"]["priority"])
                        for w in rows if w["event"]}
        context = tuple(sorted(associations))
        preserved = any(w["preserved"] for w in rows)
        key = phase, context, preserved
        if full and full[-1]["key"] == key and full[-1]["end"] + DAY == day:
            full[-1]["end"] = day
            full[-1]["workouts"].extend(rows)
        else:
            full.append(dict(key=key, start=day, end=day, phase=phase, context=context,
                             preserved=preserved, workouts=list(rows)))
    visible = []
    cursor = first
    for block in full:
        if block["end"] < first or block["start"] >= finish:
            continue
        low, high = max(first, block["start"]), min(finish - DAY, block["end"])
        if cursor < low:
            visible.append(dict(start=cursor, end=low - DAY, phase="UNPLANNED", context=(), preserved=False, workouts=[]))
        visible.append(dict(block, visible_start=low, visible_end=high))
        cursor = high + DAY
    if cursor < finish:
        visible.append(dict(start=cursor, end=finish - DAY, phase="UNPLANNED", context=(), preserved=False, workouts=[]))
    for block in visible:
        start, end = block["start"], block["end"]
        low, high = block.get("visible_start", start), block.get("visible_end", end)
        weekly = {}
        for w in block["workouts"]:
            day = date.fromisoformat(w["date"])
            monday = day - timedelta(days=day.weekday())
            weekly.setdefault(monday, []).append(w)
        details = [dict(week=m.isoformat(), start=max(m, start).isoformat(),
                        end=min(m + 6 * DAY, end).isoformat(), partial=start > m or end < m + 6 * DAY,
                        cutback=any(w.get("cutback", False) for w in rows),
                        **_totals(rows)) for m, rows in sorted(weekly.items())]
        identity = f'{selected["id"]}:{selected["revision_id"]}:{start}:{end}:{block["phase"]}'
        data["blocks"].append(dict(id=identity, start=start.isoformat(), end=end.isoformat(),
            visible_start=low.isoformat(), visible_end=high.isoformat(), phase=block["phase"],
            label=phase_label(block["phase"]), color=PHASE_COLORS.get(block["phase"], "#e2e8f0"),
            offset=(low - first).days / days_in_year, width=((high - low).days + 1) / days_in_year,
            events=[dict(id=i, name=n, date=d, priority=p) for i, n, d, p in block["context"]],
            preserved=block["preserved"], weekly=details, **_totals(block["workouts"])))
    applied = selected["applied_events"]
    events = [dict(e, intent_status=next((i["status"] for i in selected["intent_events"] if i["id"] == e["id"]), None)) for e in applied]
    for e in selected["intent_events"]:
        same = any(all(e[k] == a.get(k) for k in ("id", "name", "date", "priority")) for a in applied)
        if e["status"] in {"planned", "completed"} and not same:
            events.append(dict(e, source="Event intent · not applied", preserved=False))
    for e in sorted(events, key=lambda e: (e["date"], e["source"], e["id"])):
        d = date.fromisoformat(e["date"])
        if first <= d < finish:
            data["events"].append(dict(e, key=f'{selected["id"]}:event:{e["source"]}:{e.get("workout_id", e["id"])}:{e["date"]}',
                offset=((d - first).days + .5) / days_in_year))
    return data
