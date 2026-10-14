"""Versioned, explainable recovery estimates; no DB writes or plan changes."""
from __future__ import annotations

from datetime import date, timedelta
import math
from statistics import median

import pandas as pd

from garmin_data_hub.analytics.training_load import calculate_ctl_atl_tsb

POLICY_VERSION = "recovery-readiness.v1"
DAY = timedelta(days=1)
WEIGHTS = {
    "recovery": {"hrv": 35, "rhr": 25, "sleep": 25, "stress": 15},
    "readiness": {"recovery": 55, "load": 25, "shortfall": 20},
    "energy": {"sleep": 50, "shortfall": 30, "stress": 20},
}
LABELS = {"hrv": "Nightly HRV", "rhr": "Resting heart rate", "sleep": "Last-night sleep",
    "stress": "Prior-day stress", "shortfall": "Seven-night sleep shortfall",
    "load": "Recent recorded training load", "recovery": "Recovery estimate"}


def number(value, low, high):
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return result if math.isfinite(result) and low <= result <= high else None


def _first(values, low, high):
    return next((n for value in values if (n := number(value, low, high)) is not None), None)


def _dates(start, end):
    while start <= end:
        yield start
        start += DAY


def normalize_health(inputs):
    """Keep only supported daily measures and exact canonical dates."""
    tables = inputs["tables"]
    days = set().union(*(set(t) for t in tables.values()))
    normalized = {}
    for day in days:
        try:
            if date.fromisoformat(day).isoformat() != day:
                continue
        except (ValueError, TypeError):
            continue
        sleep = tables.get("sleep", {}).get(day, {})
        hrv = tables.get("hrv", {}).get(day, {})
        daily = tables.get("daily_summary", {}).get(day, {})
        readiness = tables.get("training_readiness", {}).get(day, {})
        battery = tables.get("body_battery", {}).get(day, {})
        seconds = number(sleep.get("sleep_time_seconds"), 0, 86400)
        normalized[day] = dict(date=day, sleep=seconds / 3600 if seconds is not None else None,
            hrv=_first((hrv.get("last_night_avg"), hrv.get("last_night")), 1, 500),
            rhr=_first((sleep.get("resting_heart_rate"), daily.get("resting_heart_rate")), 25, 150),
            stress=number(daily.get("average_stress_level"), 0, 100),
            garmin_sleep=number(sleep.get("sleep_score_overall"), 0, 100),
            garmin_readiness=number(readiness.get("score"), 0, 100),
            garmin_battery=_first((daily.get("body_battery_at_wake"), battery.get("at_wake")), 0, 100),
            garmin_hrv_status=hrv.get("status"),
            garmin_sleep_need=number(sleep.get("sleep_need_minutes"), 0, 1440),
            daily_record=day in tables.get("daily_summary", {}))
    return normalized


def _factor(key, score=None, *, value=None, detail="", baseline=None, observations=None, source=None, coverage_pct=100):
    return dict(key=key, label=LABELS[key], score=None if score is None else round(max(0, min(100, score)), 2),
        value=value, detail=detail, baseline=baseline, observations=observations, source=source, coverage_pct=coverage_pct)


def _baseline(rows, day, key):
    values = [(d, rows.get(d.isoformat(), {}).get(key)) for d in _dates(day-28*DAY, day-DAY)]
    available = [(d, v) for d, v in values if v is not None]
    recent = sum(d >= day-7*DAY for d, _ in available)
    if len(available) < 14 or recent < 3:
        return None, None, len(available)
    transformed = [math.log(v) if key == "hrv" else v for _, v in available]
    center = median(transformed)
    floor = math.log(1.1) if key == "hrv" else 3.0
    spread = max(floor, 1.4826 * median(abs(v-center) for v in transformed))
    return center, spread, len(available)


def _personal_factor(rows, day, key):
    value = rows.get(day.isoformat(), {}).get(key)
    center, spread, count = _baseline(rows, day, key)
    source = "hrv.last_night_avg / last_night" if key == "hrv" else "sleep / daily_summary.resting_heart_rate"
    if value is None or center is None:
        reason = "No valid measurement for this date." if value is None else "Building your baseline: need 14 of the prior 28 days, including 3 of the prior 7."
        return _factor(key, value=value, observations=count, detail=reason, source=source)
    z = ((math.log(value) if key == "hrv" else value)-center) / spread
    baseline = math.exp(center) if key == "hrv" else center
    score = 90-20*max(abs(z)-1, 0) if key == "hrv" else 90-15*max(z, 0)
    unit = "ms" if key == "hrv" else "bpm"
    if key == "hrv":
        direction = "below" if z < -1 else "above" if z > 1 else "within"
        detail = f"{value:g} {unit}; {direction} your usual range around {baseline:.1f} {unit}. Unusually high HRV is not automatically better."
    else:
        detail = f"{value:g} {unit} versus your {baseline:.1f} {unit} personal median ({value-baseline:+.1f} bpm)."
    return _factor(key, score, value=value, baseline=round(baseline, 2), observations=count, detail=detail, source=source,
        coverage_pct=round(count*100/28, 1))


def _load_factor(inputs, rows, day):
    first, last = day-42*DAY, day-DAY
    daily_dates = [d for d in _dates(first, last) if rows.get(d.isoformat(), {}).get("daily_record")]
    recent = sum(d >= day-7*DAY for d in daily_dates)
    activities = [a for a in inputs["activities"] if first.isoformat() <= a["date"] <= last.isoformat()]
    activity_days = len({a["date"] for a in activities})
    observations = dict(daily_days=len(daily_dates), recent_daily_days=recent, activity_days=activity_days,
        undated_activities=inputs.get("undated_activities", 0))
    if inputs.get("undated_activities") or recent < 7 or len(daily_dates) < 28 or activity_days < 4:
        return _factor("load", observations=observations, detail=f"Observed {len(daily_dates)}/42 daily-summary dates, {recent}/7 recent dates and {activity_days} activity days; {observations['undated_activities']} undated activities. Need 28/42, all 7 recent dates and 4 activity days; undated activities must be resolved. Missing activity days are not verified rest.")
    tss = [_first((a.get("training_stress_score"), a.get("derived_tss")), 0, 10000) for a in activities]
    duration = [_first((a.get("duration_seconds"), a.get("moving_duration_seconds"), a.get("elapsed_duration_seconds")), 0, 604800) for a in activities]
    if all(v is not None for v in tss):
        values, mode = tss, "TSS"
    elif all(v is not None for v in duration):
        values, mode = [v/3600 for v in duration], "Recorded hours"
    else:
        return _factor("load", observations=observations, detail="Some activities lack both consistent TSS and duration. Unknown load is not zero.")
    totals = {d.isoformat(): 0.0 for d in _dates(first, last)}
    for a, value in zip(activities, values):
        totals[a["date"]] += value
    frame = pd.DataFrame({"tss": list(totals.values())}, index=pd.to_datetime(list(totals)))
    model = calculate_ctl_atl_tsb(frame).iloc[-1]
    ctl, atl, balance = (float(model[key]) for key in ("ctl", "atl", "tsb"))
    if ctl <= 0:
        return _factor("load", observations=observations, detail="No positive recorded training baseline is available.")
    ratio = atl / ctl
    evidence = dict(mode=mode, chronic=round(ctl, 3), acute=round(atl, 3), balance=round(balance, 3),
        ratio=round(ratio, 3), start=first.isoformat(), end=last.isoformat(), **observations)
    detail = f"{mode}: recent average {atl:.1f}, longer average {ctl:.1f}; ratio {ratio:.2f}. Recorded activities only; daily summaries do not prove complete activity sync."
    if mode != "TSS":
        detail += " Duration is a volume proxy without intensity."
    return _factor("load", 90-30*max(ratio-1, 0), value=evidence, observations=observations, detail=detail,
        source="activity.training_stress_score / current activity_metrics.tss" if mode == "TSS" else "activity duration",
        coverage_pct=round(len(daily_dates)*100/42*(1 if mode == "TSS" else .8), 1))


def _composite(key, factors):
    weights = WEIGHTS[key]
    available = {k: factors[k] for k in weights if factors[k]["score"] is not None}
    weight = sum(weights[k] for k in available)
    enough = (len(available) >= 2 and weight >= 60 and bool({"hrv", "rhr"} & available.keys()) if key == "recovery" else
        len(available) >= 2 and weight >= 70 and ("recovery" if key == "readiness" else "sleep") in available)
    coverage = sum(weights[k] * factors[k].get("coverage_pct", 100) / 100 for k in available)
    value = round(sum(weights[k] * available[k]["score"] for k in available)/weight) if enough else None
    drivers = [dict(factors[k], weight_pct=weights[k], used_weight_pct=round(weights[k]*100/weight, 1) if enough and k in available else 0)
        for k in weights]
    return dict(key=key, score=value, coverage_pct=round(coverage, 1), available_weight_pct=weight,
        confidence="Insufficient" if not enough else "Well covered" if coverage == 100 else "Limited",
        label="Unavailable" if value is None else "Low" if value < 50 else "Moderate" if value < 75 else "Favorable",
        drivers=drivers, missing=[LABELS[k] for k in weights if k not in available])


def assess_day(inputs, rows, day, sleep_target_hours):
    today = rows.get(day.isoformat(), {})
    factors = {key: _personal_factor(rows, day, key) for key in ("hrv", "rhr")}
    sleep = today.get("sleep")
    factors["sleep"] = _factor("sleep", 100*min(sleep/sleep_target_hours, 1) if sleep is not None else None,
        value=sleep, detail=f"Recorded sleep versus your saved {sleep_target_hours:g} h target." if sleep is not None else "No valid sleep duration for this date.", source="sleep.sleep_time_seconds")
    previous = rows.get((day-DAY).isoformat(), {})
    stress = previous.get("stress")
    factors["stress"] = _factor("stress", 100-stress if stress is not None else None, value=stress,
        detail=f"Stress dated {day-DAY}; today's incomplete daily stress is excluded." if stress is not None else "No valid prior-day stress measurement.", source="daily_summary.average_stress_level")
    nights = [rows.get(d.isoformat(), {}).get("sleep") for d in _dates(day-6*DAY, day)]
    nights = [n for n in nights if n is not None]
    shortfall = sum(max(sleep_target_hours-n, 0) for n in nights)
    factors["shortfall"] = _factor("shortfall", 100-5*shortfall if len(nights) >= 5 else None,
        value=round(shortfall, 2) if nights else None, observations=len(nights),
        detail=f"{shortfall:.1f} h below target across {len(nights)}/7 observed nights; missing nights are not extrapolated. Need at least 5 nights.", source="sleep.sleep_time_seconds + saved target",
        coverage_pct=round(len(nights)*100/7, 1))
    factors["load"] = _load_factor(inputs, rows, day)
    recovery = _composite("recovery", factors)
    factors["recovery"] = dict(_factor("recovery", recovery["score"], value=recovery["score"],
        detail="Uses the independent Recovery components shown above.", source=POLICY_VERSION), coverage_pct=recovery["coverage_pct"])
    readiness, energy = _composite("readiness", factors), _composite("energy", factors)
    scores = dict(recovery=recovery, readiness=readiness, energy=energy)
    if recovery["score"] is None or readiness["score"] is None:
        guidance = "Insufficient recovery/readiness evidence. Check missing inputs or sync Garmin; use how you feel and your existing plan rather than an unavailable score."
    elif min(recovery["score"], readiness["score"]) < 50:
        guidance = "Consider rest or gentle movement today and review any hard or long session. Check how you feel; the planned workout has not been changed."
    elif min(recovery["score"], readiness["score"]) < 75:
        guidance = "Consider keeping training easy today. Check how you feel before a hard or long session; the planned workout has not been changed."
    else:
        guidance = "Follow the existing planned session if you feel well. A favorable estimate is not a reason to add intensity or extra volume."
    if readiness["score"] is not None and readiness["confidence"] == "Limited":
        guidance += " Coverage is limited; review missing or partial inputs before a hard or long session."
    return dict(date=day.isoformat(), scores=scores, factors=factors, guidance=guidance,
        garmin=dict(sleep_score=today.get("garmin_sleep"), readiness=today.get("garmin_readiness"),
            body_battery=today.get("garmin_battery"), hrv_status=today.get("garmin_hrv_status"),
            sleep_need_minutes=today.get("garmin_sleep_need")))


def analyze_recovery_inputs(inputs, *, assessment_date: date, history_days: int, sleep_target_hours: float, today: date):
    if type(history_days) is not int or not 1 <= history_days <= 90:
        raise ValueError("Recovery history must be 1–90 days.")
    sleep_target_hours = number(sleep_target_hours, 6, 12)
    if sleep_target_hours is None:
        raise ValueError("Sleep target must be between 6 and 12 hours.")
    if assessment_date > today:
        raise ValueError("Recovery assessments cannot use a future date.")
    if assessment_date < date.min+timedelta(days=history_days+42):
        raise ValueError("Assessment date is too early for the required recovery history.")
    rows = normalize_health(inputs)
    history = [assess_day(inputs, rows, d, sleep_target_hours) for d in _dates(assessment_date-(history_days-1)*DAY, assessment_date)]
    current = dict(history[-1])
    if assessment_date < today:
        current["guidance"] = f"Historical assessment for {assessment_date}. Sync or select current data before using recovery guidance for today's training."
    latest = max((d for d, r in rows.items() if d <= assessment_date.isoformat() and any(r.get(k) is not None for k in ("sleep", "hrv", "rhr"))), default=None)
    return dict(policy_version=POLICY_VERSION, assessment=current, history=history,
        assessment_date=assessment_date.isoformat(), sleep_target_hours=sleep_target_hours,
        latest_signal_date=latest, assessment_age_days=(today-assessment_date).days,
        sources=inputs["sources"], rr_supported=inputs["rr_supported"], rr_note=inputs["rr_note"],
        limitations="Experimental app estimates, not validated measurements of recovery, performance or physical energy. Coverage describes available data, not medical confidence.")
