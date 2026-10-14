"""Versioned baseline calendar and completion-goal policy; no persistence or HR inference."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from garmin_data_hub.services import season_plans as intent

CYCLE_DAYS = 56
LONG_RUN_MINUTES = {"5K": 30, "10K": 60, "10M": 90, "HM": 105, "20M": 120,
                    "MAR": 150, "50K": 150, "50M": 180, "100K": 180, "100M": 180}
GOAL_LABELS = {"5K": "5 km", "10K": "10 km", "10M": "10 miler", "HM": "Half marathon",
               "20M": "20 miles", "MAR": "Marathon", "50K": "50 km", "50M": "50 miles",
               "100K": "100 km", "100M": "100 miles"}
GOAL_OPTIONS = {"": "None / general fitness", **GOAL_LABELS}


def goal_label(code):
    if code is None:
        return "General fitness"
    return GOAL_LABELS.get(code, "Unavailable") if isinstance(code, str) else "Unavailable"


def goal_snapshot(code):
    return {"schema_version": "baseline-distance-goal.v1", "distance_code": code,
            "distance_metres": intent.DISTANCES[code] if code else None,
            "intent": "COMPLETION" if code else "GENERAL_FITNESS"}


def cycle_evidence(season, day):
    start = date.fromisoformat(season.start_date)
    anchor = start - timedelta(days=start.weekday())
    elapsed = (day - anchor).days
    cycle, within = divmod(elapsed, CYCLE_DAYS)
    week = within // 7
    return {"schema_version": "baseline-cycle.v1", "anchor": anchor.isoformat(),
            "index": cycle, "week": week + 1,
            "start": (anchor + timedelta(days=cycle * CYCLE_DAYS)).isoformat(),
            "end": (anchor + timedelta(days=(cycle + 1) * CYCLE_DAYS - 1)).isoformat()}


def baseline_control(season, day):
    week = cycle_evidence(season, day)["week"]
    return ("BASE", Decimal(1)) if week <= 3 else (("BUILD", Decimal(1)) if week <= 7
                                                    else ("RECOVERY", Decimal("0.6")))
