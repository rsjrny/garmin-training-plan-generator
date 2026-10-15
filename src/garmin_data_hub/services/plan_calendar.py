"""Read-only calendar labels from verified workouts and explicit saved metadata."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from garmin_data_hub.services.chart_plan_data import active_chart_plan_data
from garmin_data_hub.services.season_plans import _get
from garmin_data_hub.services.workout_compliance import _legacy_workout
from garmin_data_hub.analytics.workout_compliance import calendar_day
from garmin_data_hub.plan_methodology.revision_repository import load_revision


def calendar_schedule(db_path, *, season_id=""):
    with closing(sqlite3.connect(Path(db_path).resolve().as_uri()+"?mode=ro",uri=True,timeout=10)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN")
        season = _get(conn,season_id) if season_id else None
        active = active_chart_plan_data(None,_connection=conn)
        states = {(r["plan_id"],r["workout_id"]):dict(r) for r in conn.execute("SELECT * FROM season_workout_state")}
        revisions = {}
        rows = []
        warnings = []
        for w in active["workouts"]:
            if season and w["plan_id"] != season.plan_id:
                continue
            rid = w["revision_id"]
            if rid not in revisions:
                revisions[rid] = {item.workout_id:item for item in load_revision(None,rid,_connection=conn).candidate.workouts}
            source = revisions[rid][w["workout_id"]]
            flags = states.get((w["plan_id"],w["workout_id"]),{})
            labels = [label for flag,label in (("locked","Locked"),("manually_edited","Manual"),("manually_created","Manual"),("explicitly_completed","Marked done")) if flags.get(flag)]
            if w["activity_id"] is not None:
                labels.append("Match confirmed")
            if conn.execute("""SELECT 1 FROM plan_revision_workout_origin WHERE revision_id=? AND workout_id=?
                AND (origin_revision_id!=revision_id OR origin_workout_id!=workout_id)""",(rid,w["workout_id"])).fetchone():
                labels.append("Preserved")
            rows.append(dict(date=w["date"],workout=w["title"],sport=w["sport"],phase=source.phase,
                notes=source.description,duration_min=w["duration_s"]/60 if w["duration_s"] is not None else None,
                distance_km=w["distance_m"]/1000 if w["distance_m"] is not None else None,
                intensity=" · ".join(sorted({s.prescription.native_target.value for s in source.segments if s.prescription})),
                protection=" · ".join(dict.fromkeys(labels)),
                heart_rate=w["heart_rate"],heart_rate_details=w["heart_rate_details"],
                calendar=dict(hard=source.quality_flag or source.event_flag,long=source.long_run_flag,
                    event=source.event_flag,estimated=w["duration_estimated"] or w["distance_estimated"],kind_known=True)))
        if not season:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            confirmed_legacy = {r[0] for r in conn.execute("SELECT planned_workout_id FROM legacy_activity_workout_match WHERE status='CONFIRMED'")} if "legacy_activity_workout_match" in tables else set()
            for raw in conn.execute("SELECT * FROM active_planned_workout WHERE source_plan_id IS NULL ORDER BY scheduled_date,planned_workout_id"):
                w = _legacy_workout(raw)
                if calendar_day(w["date"]) is None:
                    warnings.append("An older saved workout has an invalid date and cannot appear in the calendar.")
                    continue
                try:
                    payload = json.loads(raw["structure_json"] or "{}")
                    meta = payload.get("workout",{}) if isinstance(payload,dict) else {}
                    if not isinstance(meta,dict) or meta.get("date") not in (None,w["date"]):
                        meta = {}
                except (ValueError,TypeError):
                    meta = {}
                intensity = str(meta.get("intensity") or "").lower()
                protection = ["Older saved workout"]
                if w["explicitly_completed"]:
                    protection.append("Marked done")
                if w["legacy_id"] in confirmed_legacy:
                    protection.append("Match confirmed")
                rows.append(dict(date=w["date"],workout=w["title"],sport=w["sport"],phase=meta.get("phase"),
                    notes=raw["description"],duration_min=w["duration_s"]/60 if w["duration_s"] is not None else None,
                    distance_km=w["distance_m"]/1000 if w["distance_m"] is not None else None,intensity=meta.get("intensity"),protection=" · ".join(protection),
                    heart_rate=w["heart_rate"],heart_rate_details=w["heart_rate_details"],
                    calendar=dict(hard=True if meta.get("quality_flag") is True or intensity in {"hard","race"} else False if intensity in {"easy","recovery","rest"} or w["rest"] else None,
                        long=meta.get("long_run_flag") if type(meta.get("long_run_flag")) is bool else None,
                        event=meta.get("event_flag") is True or intensity == "race",
                        estimated=not w["rest"] and (w["duration_s"] is not None or w["distance_m"] is not None),
                        kind_known=w["sport"] != "UNKNOWN")))
        events = [dict(date=r["event_date"],name=r["name"],priority=r["priority"],distance_code=r["distance_code"]) for r in conn.execute(
            """SELECT e.* FROM season_event e JOIN season_plan s ON s.season_id=e.season_id
               WHERE s.status!='archived' AND e.status IN ('planned','completed')
                 AND (?='' OR e.season_id=?) ORDER BY e.event_date,e.event_id""",(season_id,season_id))]
        return dict(rows=sorted(rows,key=lambda r:(r["date"],r["workout"])),markers=events,warnings=list(dict.fromkeys(warnings)))
