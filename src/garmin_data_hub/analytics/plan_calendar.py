"""Describe saved weekly density and spacing without changing a prescription."""
from datetime import date, timedelta
import math


def _number(value):
    if isinstance(value,bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) and value >= 0 else None
    except (TypeError,ValueError,OverflowError):
        return None


def calendar_week(rows, monday):
    sunday = monday+timedelta(days=6)
    selected = [r for r in rows if monday.isoformat() <= r["date"] <= sunday.isoformat()]
    training = [r for r in selected if r.get("sport") in {"RUNNING","STRENGTH","MOBILITY"}]
    rest = {r["date"] for r in selected if r.get("sport") == "REST"}
    def days(flag):
        return sorted({r["date"] for r in selected if r.get("calendar",{}).get(flag) is True})
    hard = days("hard")
    # Include neighbors so Sunday/Monday spacing is visible across week boundaries.
    all_hard = {r["date"] for r in rows if r.get("calendar",{}).get("hard") is True}
    adjacent = [(day,(date.fromisoformat(day)+timedelta(days=1)).isoformat()) for day in sorted(all_hard)
                if (date.fromisoformat(day)+timedelta(days=1)).isoformat() in all_hard
                and (monday.isoformat() <= day <= sunday.isoformat() or
                     monday.isoformat() <= (date.fromisoformat(day)+timedelta(days=1)).isoformat() <= sunday.isoformat())]
    amounts = {}
    for field,pool in (("duration_min",[r for r in selected if r.get("sport") != "REST"]),("distance_km",[r for r in training if r["sport"] == "RUNNING"])):
        values = [_number(r.get(field)) for r in pool]
        known = [v for v in values if v is not None]
        amounts[field] = dict(value=sum(known) if known or not pool else None,missing=len(values)-len(known),count=len(values))
    return dict(rows=selected,training_days=len({r["date"] for r in training}),sessions=len(training),
        rest_days=len(rest),unclassified=sum(r.get("sport") not in {"RUNNING","STRENGTH","MOBILITY","REST"} for r in selected),
        multiple=[day for day in sorted({r["date"] for r in training}) if sum(r["date"] == day for r in training)>1],
        hard=hard,long=days("long"),strength=sorted({r["date"] for r in training if r["sport"] == "STRENGTH"}),
        adjacent=adjacent,amounts=amounts)
