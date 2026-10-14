"""Deterministic session suggestions and amount-based completion summaries."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
import math

POLICY_VERSION = "workout-compliance.v1"
ALL = "__all__"
LEGACY = "__legacy__"
DAY = timedelta(days=1)


def amount(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) and result >= 0 else None


def calendar_day(value):
    try:
        parsed = date.fromisoformat(str(value))
        return parsed if parsed.isoformat() == value else None
    except (TypeError, ValueError):
        return None


def sport(value):
    value = str(value or "").lower()
    if value in {"run", "running", "trail_running", "indoor_running", "treadmill_running"}:
        return "RUNNING"
    if value in {"strength", "strength_training"}:
        return "STRENGTH"
    if value in {"mobility", "yoga", "pilates", "stretching"}:
        return "MOBILITY"
    if value == "rest":
        return "REST"
    return "UNKNOWN"


def compatible(workout, activity):
    return workout["sport"] != "REST" and workout["sport"] == sport(activity["sport"]) != "UNKNOWN"


def pair_evidence(workout, activity, window, *, manual=False):
    planned, actual = calendar_day(workout["date"]), calendar_day(activity["date"])
    if planned is None or actual is None or workout["rest"] or abs((actual-planned).days) > window:
        return None
    if not compatible(workout, activity) and not (manual and workout["legacy"] and workout["sport"] == "UNKNOWN" and sport(activity["sport"]) in {"RUNNING","STRENGTH","MOBILITY"}):
        return None
    ratios, missing = {}, []
    for field in ("duration_s", "distance_m"):
        expected, recorded = workout[field], activity[field]
        if expected is not None and expected > 0:
            if recorded is None:
                missing.append(field)
            else:
                ratios[field] = recorded / expected
    if not manual and (not ratios or any(not .2 <= v <= 3 for v in ratios.values())):
        return None
    proximity = 1-abs((actual-planned).days)/(window+1)
    similarity = sum(min(v, 1/v) if v > 0 else 0 for v in ratios.values())/len(ratios) if ratios else 0
    score = round(40*proximity+60*similarity, 2)
    return dict(workout_key=workout["key"], activity_id=activity["id"], planned_date=workout["date"], actual_date=activity["date"],
        day_delta=(actual-planned).days, score=score, ratios=ratios, missing_measures=missing,
        reviewed_sport=workout["sport"] if workout["sport"] != "UNKNOWN" else sport(activity["sport"]),
        note="Sport supplied by your explicit association." if workout["sport"] == "UNKNOWN" else "Compatible recorded sport.")


def suggestions(snapshot, window):
    claimed = {m["activity_id"] for m in snapshot["matches"] if m["status"] == "CONFIRMED"}
    rejected = {(m["workout_key"],m["activity_id"]) for m in snapshot["matches"] if m["status"] == "REJECTED" and m.get("current_source",True)}
    pending = {(m["workout_key"],m["activity_id"]) for m in snapshot["matches"] if m["status"] == "CANDIDATE"}
    edges = []
    for w in snapshot["workouts"]:
        if w["activity_id"] is not None or w["explicitly_completed"]:
            continue
        for a in snapshot["activities"]:
            if a["id"] in claimed or (w["key"],a["id"]) in rejected or calendar_day(a["date"]) is None:
                continue
            edge = pair_evidence(w,a,window)
            if edge is not None:
                edge["stored_candidate"] = (w["key"],a["id"]) in pending
                edges.append(edge)
    by_workout, by_activity = defaultdict(list), defaultdict(list)
    for e in edges:
        by_workout[e["workout_key"]].append(e)
        by_activity[e["activity_id"]].append(e)
    def ranked(values):
        return sorted(values,key=lambda e:(-e["score"],abs(e["day_delta"]),e["workout_key"],e["activity_id"]))
    for e in edges:
        w = ranked(by_workout[e["workout_key"]])
        a = ranked(by_activity[e["activity_id"]])
        margins = [e["score"]-max((o["score"] for o in side if o is not e),default=-100) for side in (w,a)]
        e["ambiguous"] = min(margins) < 8
        e["recommended"] = w[0] is e and a[0] is e
        e["confidence"] = "HIGH" if e["score"] >= 85 and abs(e["day_delta"]) <= 1 and not e["missing_measures"] and not e["ambiguous"] else "MEDIUM" if e["score"] >= 65 else "LOW"
        e["alternatives"] = len(w)-1 + len(a)-1
    return sorted(edges,key=lambda e:(e["planned_date"],e["workout_key"],-e["score"],e["activity_id"]))


def classify(workout, activity, *, today, window, candidate_count, activity_available):
    row = dict(workout, actual_date=activity["date"] if activity else None,
        actual_duration_s=activity["duration_s"] if activity else None,
        actual_distance_m=activity["distance_m"] if activity else None, moved=False,
        ratios={}, completion=None, explanation="")
    day = calendar_day(workout["date"])
    if workout["rest"]:
        return dict(row,status="Rest",explanation="Rest has no activity-completion requirement.")
    if workout["activity_id"] is not None:
        if activity is None or calendar_day(activity["date"]) is None or calendar_day(activity["date"]) > today:
            return dict(row,status="Evidence unavailable",explanation="Confirmed identity is retained; its activity/date is unavailable or in the future.")
        if not compatible(workout,activity):
            return dict(row,status="Sport substitution",explanation="Existing confirmed association has a different/unknown sport; it does not establish prescribed-sport completion.")
        expected, missing = 0, []
        for field in ("duration_s","distance_m"):
            if workout[field] is not None and workout[field] > 0:
                expected += 1
                if activity[field] is None:
                    missing.append(field)
                else:
                    row["ratios"][field] = activity[field]/workout[field]
        if any(v < .8 for v in row["ratios"].values()):
            completion = "Partial"
        elif expected and not missing:
            completion = "Completed"
        elif workout["explicitly_completed"]:
            completion = "Completed"
        else:
            completion = "Unverified amounts"
        moved = day != calendar_day(activity["date"])
        explanation = "Confirmed association; completion compares recorded amounts with known planned amounts (80% tolerance)."
        if missing or not expected:
            explanation += " Some required amounts are unavailable; no actual values are invented."
        if workout["explicitly_completed"]:
            explanation += " Also explicitly marked done; known partial measurements remain partial."
        return dict(row,status="Moved" if moved else completion,completion=completion,moved=moved,explanation=explanation)
    if workout["explicitly_completed"]:
        return dict(row,status="Completed",completion="Completed",explanation="Explicitly marked done; no linked activity or actual measures are inferred.")
    if workout["sport"] == "UNKNOWN" and not any(workout[k] is not None and workout[k] > 0 for k in ("duration_s","distance_m")):
        return dict(row,status="Evidence unavailable",explanation="The older saved row lacks sport and positive prescribed amounts; it cannot establish a training/rest requirement.")
    if candidate_count:
        return dict(row,status="Needs review",explanation="Suggested or stored candidate identities are unconfirmed and do not count as completed.")
    if day is None:
        return dict(row,status="Evidence unavailable",explanation="The saved workout date is invalid.")
    if day > today:
        return dict(row,status="Upcoming",explanation="Future prescribed session.")
    if day == today:
        return dict(row,status="Today",explanation="Today's unstarted sessions are not missed.")
    if not activity_available:
        return dict(row,status="Evidence unavailable",explanation="No imported activity source is available. Sync data before evaluating completion.")
    if day+window*DAY >= today:
        return dict(row,status="Awaiting activity",explanation="The matching window is still open; a later/moved activity can be reviewed.")
    return dict(row,status="Missed",explanation="No confirmed or marked completion after the matching window closed; recorded data may still need sync/review.")


def _weekly(workouts, activities, start, end, today, activity_available):
    end = min(end,today-DAY)
    if end < start:
        return []
    week, rows = start-timedelta(days=start.weekday()), []
    while week <= end:
        low, high = max(start,week), min(end,week+6*DAY)
        all_plans = [w for w in workouts if low.isoformat() <= w["date"] <= high.isoformat()]
        planned = [w for w in all_plans if not w["rest"]]
        actual = [a for a in activities if a["date"] and low.isoformat() <= a["date"] <= high.isoformat()]
        complete_plan = len({w["date"] for w in all_plans}) == (high-low).days+1
        row = dict(week=week.isoformat(),start=low.isoformat(),end=high.isoformat(),partial=low != week or high != week+6*DAY,
            plan_days=len({w["date"] for w in all_plans}),calendar_days=(high-low).days+1,
            sessions=len(planned),activities=len(actual))
        for field in ("duration_s","distance_m"):
            ps = planned if field == "duration_s" else [w for w in planned if w["sport"] == "RUNNING"]
            ac = actual if field == "duration_s" else [a for a in actual if sport(a["sport"]) == "RUNNING"]
            known_p, known_a = [w[field] for w in ps if w[field] is not None], [a[field] for a in ac if a[field] is not None]
            p, a = sum(known_p) if known_p or not ps else None, sum(known_a) if activity_available and (known_a or not ac) else None
            known_sports = field != "distance_m" or not any(w["sport"] == "UNKNOWN" for w in planned) and not any(not a["sport"] for a in actual)
            comparable = complete_plan and activity_available and known_sports and len(known_p) == len(ps) and len(known_a) == len(ac)
            row.update({"planned_"+field:p,"recorded_"+field:a,field+"_variance":a-p if comparable and a is not None and p is not None else None,
                field+"_planned_known":len(known_p),field+"_planned_total":len(ps),field+"_recorded_known":len(known_a),field+"_recorded_total":len(ac)})
        rows.append(row)
        week += 7*DAY
    return rows


def prepare_compliance(snapshot, *, start, end, today, window, plan_id=ALL):
    edges = suggestions(snapshot,window)
    selected = sorted(
        (w for w in snapshot["workouts"] if start.isoformat() <= w["date"] <= end.isoformat() and (plan_id == ALL or w["plan_id"] == plan_id)),
        key=lambda w: (w["date"], w["key"]),
    )
    by_activity = {a["id"]:a for a in snapshot["activities"]}
    pending = defaultdict(set)
    for edge in edges:
        pending[edge["workout_key"]].add(edge["activity_id"])
    for m in snapshot["matches"]:
        if m["status"] == "CANDIDATE":
            pending[m["workout_key"]].add(m["activity_id"])
    rows = [classify(w,by_activity.get(w["activity_id"]),today=today,window=window,candidate_count=len(pending[w["key"]]),activity_available=snapshot["activity_available"]) for w in selected]
    selected_keys = {w["key"] for w in selected}
    confirmed = {m["activity_id"]:m for m in snapshot["matches"] if m["status"] == "CONFIRMED"}
    proposed_ids = {e["activity_id"] for e in edges} | {m["activity_id"] for m in snapshot["matches"] if m["status"] == "CANDIDATE"}
    actual = []
    for a in snapshot["activities"]:
        if not a["date"] or not start.isoformat() <= a["date"] <= min(end,today).isoformat():
            continue
        match = confirmed.get(a["id"])
        relation = "Matched" if match and match["workout_key"] in selected_keys else "Matched elsewhere/outside view" if match else "Needs review" if a["id"] in proposed_ids else "Extra"
        actual.append(dict(a,status=relation))
    due = [r for r in rows if r["date"] < today.isoformat() and not r["rest"]]
    by_day = defaultdict(list)
    for r in due:
        by_day[r["date"]].append(r)
    streak, longest, unsettled = 0,0,False
    for day, values in sorted(by_day.items()):
        complete = all(v["completion"] == "Completed" for v in values)
        pending_day = any(v["status"] in {"Needs review","Awaiting activity","Evidence unavailable","Unverified amounts","Sport substitution"} or v["completion"] == "Unverified amounts" for v in values)
        streak = streak+1 if complete else 0
        longest = max(longest,streak)
        unsettled = pending_day
    totals = dict(completed=sum(r["completion"] == "Completed" for r in rows),partial=sum(r["completion"] == "Partial" for r in rows),
        moved=sum(r["moved"] for r in rows),missed=sum(r["status"] == "Missed" for r in rows),needs_review=sum(r["status"] == "Needs review" for r in rows),
        extra=sum(a["status"] == "Extra" for a in actual),due=len(due),completed_due=sum(r["completion"] == "Completed" for r in due),
        current_streak=None if unsettled else streak,longest_streak=longest)
    return dict(workouts=rows,activities=actual,suggestions=[e for e in edges if e["workout_key"] in selected_keys],totals=totals,
        weekly=_weekly(selected,actual,start,end,today,snapshot["activity_available"]))
