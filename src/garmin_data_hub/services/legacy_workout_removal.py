"""Explicit future legacy-calendar removal with immutable retained originals.

No preview writes. Acceptance records retirement membership rather than deleting
planned rows, canonical revisions, activity evidence or original prescriptions.
"""
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
import hashlib
from pathlib import Path
import sqlite3
from uuid import uuid4
from zoneinfo import ZoneInfo

from garmin_data_hub.services import season_generation as generation, season_plans as plans

POLICY_VERSION = "legacy-workout-removal.v1"


def _json(value):
    # Raw SQLite legacy metrics are REAL values, unlike native domain content.
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


@dataclass(frozen=True)
class RemovalPreview:
    preview_id: str
    workout_ids: tuple[int, ...]
    timezone: str
    season_id: str
    local_today: str
    fingerprint: str
    review_json: str
    blockers: tuple[str, ...]

    @property
    def can_apply(self):
        return bool(self.workout_ids) and not self.blockers


def _read_connection(db_path):
    conn = sqlite3.connect(Path(db_path).resolve().as_uri()+"?mode=ro",uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("BEGIN")
    return conn


def _protected_metadata(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"locked","completed","explicitly_completed","manually_edited","manually_created"} and item not in (False,None,0,"", "false", "False"):
                return True
            if key == "status" and str(item).lower() in {"completed","confirmed","locked"}:
                return True
            if key == "flags":
                flags = item.split(",") if isinstance(item,str) else item if isinstance(item,list) else []
                if any(str(f).strip().upper() in {"LOCKED","COMPLETED","CONFIRMED","MANUAL","MANUALLY_EDITED","MANUALLY_CREATED"} for f in flags):
                    return True
            if _protected_metadata(item):
                return True
    elif isinstance(value,list):
        return any(_protected_metadata(item) for item in value)
    return False


def _activity_dates(conn,tz):
    # Older plans have no canonical match IDs. Retain any occurrence whose local
    # date already has recorded activity, without inventing a specific match.
    columns = {r[1] for r in conn.execute("PRAGMA table_info(activity)")}
    result = set()
    if "start_time_gmt" in columns:
        for (value,) in conn.execute("SELECT start_time_gmt FROM activity WHERE start_time_gmt IS NOT NULL"):
            try:
                timestamp = datetime.fromisoformat(str(value).replace("Z","+00:00"))
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                result.add(timestamp.astimezone(tz).date().isoformat())
            except (ValueError,TypeError,OverflowError):
                continue  # No match is inferred from an unreadable timestamp.
    return result


def _reasons(conn,row,today,activity_dates):
    reasons = []
    try:
        plans._day(row["scheduled_date"],"Workout date")
    except ValueError:
        reasons.append("Workout date is unreadable; repair it before removal.")
    if any(row[k] is not None for k in ("source_plan_id","source_revision_id","source_workout_id")):
        reasons.append("Structured or partially sourced workout: use its reviewed plan workflow.")
    if row["scheduled_date"] <= today:
        reasons.append("History and today's workouts are retained.")
    if row["scheduled_date"] in activity_dates:
        reasons.append("Recorded activity on this local date protects the workout.")
    if conn.execute("SELECT 1 FROM legacy_workout_removal_item WHERE planned_workout_id=?",(row["planned_workout_id"],)).fetchone():
        reasons.append("This workout was already removed from the calendar.")
    if conn.execute("SELECT 1 FROM legacy_plan_conversion_source_workout WHERE planned_workout_id=?",(row["planned_workout_id"],)).fetchone():
        reasons.append("Converted source history is retained.")
    if conn.execute("SELECT 1 FROM season_plan WHERE plan_id IS NOT NULL AND start_date <= ? AND end_date >= ?",
                    (row["scheduled_date"],row["scheduled_date"])).fetchone():
        reasons.append("These dates belong to a structured yearly plan.")
    try:
        structure = json.loads(row["structure_json"]) if row["structure_json"] else {}
        if not isinstance(structure,(dict,list)):
            raise ValueError()
        if _protected_metadata(structure):
            reasons.append("Completed, locked or manually protected metadata is retained.")
    except (ValueError,TypeError,RecursionError):
        reasons.append("Workout protection metadata is unreadable; repair it before removal.")
    return tuple(reasons)


def list_workouts(db_path,start,end,tz_name):
    start, end = plans._day(start,"Removal start"), plans._day(end,"Removal end")
    if start > end:
        raise plans.SeasonError("Removal dates must be ordered.")
    tz = ZoneInfo(tz_name)
    today = generation._local_today(tz_name).isoformat()
    with closing(_read_connection(db_path)) as conn:
        activities = _activity_dates(conn,tz)
        return tuple(dict(r, blockers=_reasons(conn,r,today,activities)) for r in conn.execute(
            "SELECT * FROM active_planned_workout WHERE source_plan_id IS NULL AND scheduled_date BETWEEN ? AND ? ORDER BY scheduled_date,planned_workout_id",
            (start.isoformat(),end.isoformat())))


def default_dates(db_path,tz_name):
    start = (generation._local_today(tz_name)+timedelta(days=1)).isoformat()
    with closing(_read_connection(db_path)) as conn:
        last = conn.execute("SELECT MAX(scheduled_date) FROM active_planned_workout WHERE source_plan_id IS NULL").fetchone()[0]
        return start,max(start,last or start)


def _document(conn,ids,tz_name,season_id):
    tz = ZoneInfo(tz_name)
    today = generation._local_today(tz_name).isoformat()
    season = plans._get(conn,season_id) if season_id else None
    if season and tz_name != season.timezone:
        raise plans.SeasonError("Removal timezone must match the selected year.")
    activities = _activity_dates(conn,tz)
    rows, blockers = [],[]
    for wid in ids:
        row = conn.execute("SELECT * FROM planned_workout WHERE planned_workout_id=?",(wid,)).fetchone()
        if not row:
            blockers.append(f"Workout {wid} no longer exists.")
            continue
        reasons = _reasons(conn,row,today,activities)
        if season and not season.start_date <= row["scheduled_date"] <= season.end_date:
            reasons += ("Workout is outside the selected yearly dates.",)
        rows.append(dict(row))
        blockers.extend(f'{row["scheduled_date"]} · {row["workout_name"]}: {reason}' for reason in reasons)
    cache = conn.execute("SELECT value FROM app_settings WHERE key='last_generated_plan'").fetchone()
    if cache:
        try:
            _decode_cache(cache[0])
        except (ValueError,TypeError):
            blockers.append("The saved nutrition cache is unreadable. Repair it before removing workouts.")
    document = {"policy":POLICY_VERSION,"workout_ids":ids,"workouts":rows,"timezone":tz_name,"local_today":today,
                "season_id":season_id,"season_version":season.input_version if season else None,
                "season":asdict(season) if season else None,
                "events":[dict(r) for r in conn.execute("SELECT * FROM season_event WHERE season_id=? ORDER BY event_date,event_id",(season_id,))],
                "state":generation._state(conn),"previous_generated_plan_cache":cache[0] if cache else None,
                "blockers":blockers}
    return document


def preview_removal(db_path,workout_ids,*,timezone="America/New_York",season_id=""):
    requested = tuple(workout_ids)
    if not requested or any(type(wid) is not int or wid <= 0 for wid in requested):
        raise plans.SeasonError("Select at least one older workout to review removal.")
    ids = tuple(sorted(set(requested)))
    with closing(_read_connection(db_path)) as conn:
        document = _document(conn,ids,timezone,season_id)
        review = _json(document)
        return RemovalPreview(uuid4().hex,ids,timezone,season_id,document["local_today"],
                              _hash(document),review,tuple(document["blockers"]))


def _decode_cache(raw):
    if raw is None:
        return None,False
    cache = json.loads(raw)
    double = isinstance(cache,str)
    if double:
        cache = json.loads(cache)
    if cache in (None,""):
        return None,double
    if not isinstance(cache,dict) or not isinstance(cache.get("day_plans",[]),list):
        raise ValueError()
    return cache,double


def _prune_cache(conn,document):
    try:
        cache,double = _decode_cache(document["previous_generated_plan_cache"])
        if cache is None:
            return
        dates = {w["scheduled_date"] for w in document["workouts"]}
        cache["day_plans"] = [day for day in cache.get("day_plans",[]) if not isinstance(day,dict) or str(day.get("iso_date","")) not in dates]
        value = json.dumps(cache,ensure_ascii=False,sort_keys=True)
        conn.execute("UPDATE app_settings SET value=? WHERE key='last_generated_plan'",(json.dumps(value) if double else value,))
    except (ValueError,TypeError):
        raise plans.SeasonError("The saved nutrition cache is unreadable. Repair it before removing workouts.")


def apply_removal(db_path,preview,*,approved_by,acknowledged=False,failure_hook=None):
    if not isinstance(preview,RemovalPreview) or not isinstance(approved_by,str) or not approved_by.strip() or acknowledged is not True:
        raise plans.SeasonError("Removal requires a reviewed selection and explicit acknowledgement.")
    with plans._connection(db_path,write=True) as conn:
        previous = conn.execute("SELECT * FROM legacy_workout_removal WHERE preview_id=?",(preview.preview_id,)).fetchone()
        if previous:
            if previous["review_sha256"] != preview.fingerprint or previous["review_json"] != preview.review_json:
                raise generation.StalePreviewError("The removal preview identity changed.")
            return "duplicate"
        document = _document(conn,preview.workout_ids,preview.timezone,preview.season_id)
        if (_json(document) != preview.review_json or _hash(document) != preview.fingerprint
                or document["local_today"] != preview.local_today):
            raise generation.StalePreviewError("The schedule, protection, activity evidence or yearly settings changed. Review removal again.")
        if document["blockers"] or not preview.can_apply:
            raise plans.SeasonError("Protected or historical workouts cannot be removed by this review.")
        _prune_cache(conn,document)
        rid = uuid4().hex
        conn.execute("INSERT INTO legacy_workout_removal VALUES (?,?,?,?,?,?,?,?)",
            (rid,preview.preview_id,preview.fingerprint,preview.review_json,preview.timezone,preview.local_today,
             approved_by.strip(),datetime.now(timezone.utc).isoformat()))
        generation._call_hook(failure_hook,"after_removal_header",conn)
        conn.executemany("INSERT INTO legacy_workout_removal_item VALUES (?,?)",((wid,rid) for wid in preview.workout_ids))
        generation._call_hook(failure_hook,"after_removal_items",conn)
        return "applied"


def list_removals(db_path):
    with closing(_read_connection(db_path)) as conn:
        return tuple(dict(r) for r in conn.execute("SELECT * FROM legacy_workout_removal ORDER BY approved_at_utc,removal_id"))
