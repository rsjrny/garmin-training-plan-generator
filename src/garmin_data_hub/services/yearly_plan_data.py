"""Read-only Dashboard facts from verified revisions and saved legacy workouts."""
from __future__ import annotations

from datetime import date
from contextlib import closing
from pathlib import Path
import sqlite3
import hashlib
import json
import math
from zoneinfo import ZoneInfo

from garmin_data_hub.plan_methodology.canonical import canonical_value
from garmin_data_hub.plan_methodology.domain import MeasureRole, Sport
from garmin_data_hub.plan_methodology.revision_repository import CorruptRevisionError, load_revision
from garmin_data_hub.plan_methodology.workout_origin import origin_identity


def _measure(workout, field, role):
    if workout.sport is Sport.REST:
        return 0, False
    if not all(getattr(s, field) is not None and getattr(s, role) in
               {MeasureRole.AUTHORITATIVE, MeasureRole.ESTIMATED} for s in workout.segments):
        return None, False
    return sum(getattr(s, field) for s in workout.segments), any(
        getattr(s, role) is MeasureRole.ESTIMATED for s in workout.segments)


def _events(candidate):
    result = {}
    for item in candidate.goal_snapshot.get("events", ()):
        draft = item["draft"]
        result[item["event_id"]] = dict(id=item["event_id"], name=draft["name"],
            date=date.fromisoformat(draft["event_date"]).isoformat(), priority=draft["priority"],
            status=draft["status"], distance_m=item["distance_metres"])
    return result


def _signature(conn, tables):
    plans = tuple(tuple(r) for r in conn.execute("SELECT plan_id,current_revision_id FROM training_plan ORDER BY plan_id")) if "training_plan" in tables else ()
    seasons = tuple(tuple(r) for r in conn.execute("SELECT season_id,input_version,status,plan_id FROM season_plan ORDER BY season_id")) if "season_plan" in tables else ()
    legacy = _legacy_rows(conn, tables)
    digest = hashlib.sha256(repr([tuple(r) for r in legacy]).encode()).hexdigest()
    return plans, seasons, digest


def _legacy_rows(conn, tables):
    if "active_planned_workout" in tables:
        return list(conn.execute("SELECT * FROM active_planned_workout WHERE source_revision_id IS NULL ORDER BY scheduled_date,planned_workout_id"))
    if "planned_workout" in tables:
        return list(conn.execute("SELECT * FROM planned_workout ORDER BY scheduled_date"))
    return []


def _legacy_selection(rows):
    """Use saved row metadata, never stale cache dates or regenerated phases."""
    workouts, events = [], []
    for i, raw in enumerate(rows):
        row = dict(raw)
        day = date.fromisoformat(row["scheduled_date"]).isoformat()
        try:
            structure = json.loads(row.get("structure_json") or "{}")
        except (ValueError, TypeError):
            structure = {}
        w = structure.get("workout") if isinstance(structure, dict) else None
        w = w if isinstance(w, dict) else {}
        # Ignore metadata referring to a different occurrence.
        if w.get("date") not in (None, day):
            w = {}
        phase = w.get("phase")
        phase = "_".join(phase.strip().upper().split()) if isinstance(phase, str) and phase.strip() else None
        rest = w.get("sport") == "rest"
        def amount(field):
            value = row.get(field)
            if rest:
                return 0
            return float(value) if type(value) in (float, int) and math.isfinite(value) and value >= 0 else None
        duration, distance = amount("planned_duration_s"), amount("planned_distance_m")
        identity = "legacy:" + str(row.get("planned_workout_id", i))
        workouts.append(dict(id=identity, date=day, phase=phase, event=None, preserved=False,
            duration_s=duration, distance_m=distance, duration_estimated=duration is not None and not rest,
            distance_estimated=distance is not None and not rest, rest=rest, cutback=False))
        if phase in {"RACE", "EVENT"}:
            events.append(dict(id=identity, workout_id=identity, name=row.get("workout_name") or "Saved race day",
                date=day, priority="?", distance_m=distance, distance_estimated=distance is not None and not rest,
                source="Saved legacy schedule", preserved=False))
    days = [w["date"] for w in workouts]
    return dict(id="legacy:saved", season_id=None, name="Saved workout schedule", start=min(days), end=max(days),
        timezone=None, archived=False, plan_id=None, revision_id=None, legacy=True,
        workouts=workouts, applied_events=events, intent_events=[])


def yearly_plan_signature(db_path):
    with closing(sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        conn.execute("BEGIN")
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
        return _signature(conn, tables)


def yearly_plan_snapshot(db_path):
    """No activity/track reads, writes, migration, generation or match side effects.

    Verify active projection membership and immutable origins in one SQLite read
    transaction. Carried phase/event context comes from the original revision.
    Event intent is returned separately and never supplies applied phase blocks.
    """
    conn = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN")
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
        revisions, workout_maps, members = {}, {}, {}
        if "training_plan" in tables:
            for (rid,) in conn.execute("SELECT current_revision_id FROM training_plan WHERE current_revision_id IS NOT NULL"):
                revision = load_revision(None, rid, _connection=conn)
                if revision is None:
                    raise CorruptRevisionError("Active revision is missing")
                revisions[rid] = revision.candidate
                workout_maps[rid] = {w.workout_id: w for w in revision.candidate.workouts}
                members[rid] = set()
        unmanaged = 0
        if "active_planned_workout" in tables:
            for row in conn.execute("SELECT source_revision_id,source_plan_id,source_workout_id,scheduled_date FROM active_planned_workout"):
                rid, wid = row["source_revision_id"], row["source_workout_id"]
                if not rid:
                    unmanaged += 1
                    continue
                if rid not in revisions or wid in members[rid]:
                    raise CorruptRevisionError("Active projection has invalid or duplicate membership")
                workout = workout_maps[rid].get(wid)
                if workout is None or row["source_plan_id"] != revisions[rid].plan_id or row["scheduled_date"] != workout.scheduled_date.isoformat():
                    raise CorruptRevisionError("Active projection differs from its canonical schedule")
                members[rid].add(wid)
        elif "planned_workout" in tables:
            unmanaged = conn.execute("SELECT COUNT(*) FROM planned_workout").fetchone()[0]
        for rid in revisions:
            if members[rid] != set(workout_maps[rid]):
                raise CorruptRevisionError("Active schedule membership is incomplete")

        seasons = list(conn.execute("SELECT season_id,name,start_date,end_date,timezone,status,plan_id FROM season_plan ORDER BY start_date,season_id")) if "season_plan" in tables else []
        intent = {}
        if "season_event" in tables:
            for row in conn.execute("SELECT season_id,event_id,name,event_date,priority,status,distance_metres FROM season_event ORDER BY event_date,event_id"):
                date.fromisoformat(row["event_date"])
                intent.setdefault(row["season_id"], []).append(dict(id=row["event_id"],
                    name=row["name"], date=row["event_date"], priority=row["priority"],
                    status=row["status"], distance_m=row["distance_metres"]))
        by_plan = {candidate.plan_id: candidate for candidate in revisions.values()}
        selections, linked = [], set()
        for season in seasons:
            start, end = date.fromisoformat(season["start_date"]), date.fromisoformat(season["end_date"])
            if start > end:
                raise CorruptRevisionError("Season dates are inconsistent")
            ZoneInfo(season["timezone"])
            candidate = by_plan.get(season["plan_id"])
            if season["plan_id"]:
                linked.add(season["plan_id"])
            selections.append(dict(id="season:" + season["season_id"], season_id=season["season_id"],
                name=season["name"], start=season["start_date"], end=season["end_date"],
                timezone=season["timezone"], archived=season["status"] == "archived",
                candidate=candidate, intent_events=intent.get(season["season_id"], [])))
        for candidate in revisions.values():
            if candidate.plan_id in linked or not candidate.workouts:
                continue
            days = [w.scheduled_date for w in candidate.workouts]
            selections.append(dict(id="plan:" + candidate.plan_id, season_id=None,
                name=candidate.goal_snapshot.get("name") or "Plan " + candidate.plan_id,
                start=min(days).isoformat(), end=max(days).isoformat(), timezone=None,
                archived=False, candidate=candidate, intent_events=[]))

        origins = dict(revisions)
        events_by_revision = {rid: _events(c) for rid, c in revisions.items()}
        for selection in selections:
            candidate = selection.pop("candidate")
            selection.update(plan_id=candidate.plan_id if candidate else None,
                revision_id=candidate.revision_id if candidate else None, workouts=[], applied_events=[],
                baseline_goal=canonical_value(candidate.goal_snapshot.get("baseline_goal")) if candidate else None)
            if not candidate:
                continue
            for workout in candidate.workouts:
                origin_rid, _ = origin_identity(conn, candidate.revision_id, workout.workout_id)
                if origin_rid not in origins:
                    source = load_revision(None, origin_rid, _connection=conn)
                    if source is None:
                        raise CorruptRevisionError("Original workout revision is missing")
                    origins[origin_rid] = source.candidate
                    events_by_revision[origin_rid] = _events(source.candidate)
                meta = workout.metadata or {}
                event = events_by_revision[origin_rid].get(meta.get("event_id"))
                duration, de = _measure(workout, "duration_seconds", "duration_role")
                distance, xe = _measure(workout, "distance_metres", "distance_role")
                selection["workouts"].append(dict(id=workout.workout_id,
                    date=workout.scheduled_date.isoformat(), phase=workout.phase,
                    event=event, preserved=origin_rid != candidate.revision_id,
                    duration_s=duration, distance_m=distance, duration_estimated=de,
                    distance_estimated=xe, cutback=meta.get("cutback") is True, rest=workout.sport is Sport.REST,
                    phase_source=meta.get("phase_source"), baseline_cycle=canonical_value(meta.get("baseline_cycle")),
                    baseline_goal=canonical_value(meta.get("baseline_goal"))))
                if workout.event_flag:
                    selection["applied_events"].append(dict(
                        event or dict(id=workout.workout_id, name=workout.title or "Event",
                                      priority=meta.get("event_priority") or "?", distance_m=distance),
                        date=workout.scheduled_date.isoformat(), source="Applied schedule",
                        workout_id=workout.workout_id,
                        preserved=origin_rid != candidate.revision_id))
            # Markers belong to the accepted event snapshot, not to a workout.
            # Older policies used C race prescriptions; retain their exact origin
            # context until a reviewed update replaces eligible future sessions.
            if candidate.goal_snapshot.get("c_event_policy") == "calendar-marker.v1":
                represented = {e["id"] for e in selection["applied_events"]}
                for event in _events(candidate).values():
                    if event["priority"] == "C" and event["status"] in {"planned", "completed"} and event["id"] not in represented:
                        selection["applied_events"].append(dict(event, source="Applied calendar marker",
                            marker_only=True, preserved=False))
        legacy_rows = _legacy_rows(conn, tables)
        if legacy_rows:
            selections.append(_legacy_selection(legacy_rows))
        return dict(selections=selections, unmanaged=unmanaged, signature=_signature(conn, tables))
    finally:
        conn.close()
