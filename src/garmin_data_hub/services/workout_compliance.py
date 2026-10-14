"""Coherent read-only suggestions and atomic, explicitly reviewed match decisions."""
from __future__ import annotations

from contextlib import closing
from datetime import date, timedelta
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from uuid import uuid4

from garmin_data_hub.analytics.workout_compliance import (
    ALL, LEGACY, DAY, POLICY_VERSION, amount, calendar_day, sport, pair_evidence, prepare_compliance,
)
from garmin_data_hub.db.activity_dates import activity_calendar_day_sql
from garmin_data_hub.db.sqlite import connect_sqlite
from garmin_data_hub.plan_methodology.activity_workout_match import create_match, review_match, MatchPersistenceError
from garmin_data_hub.plan_methodology.workout_origin import origin_identity
from garmin_data_hub.services.chart_plan_data import active_chart_plan_data


class MatchReviewError(ValueError):
    """Invalid or unavailable match review."""


class StaleMatchReviewError(MatchReviewError):
    """Reviewed identity/evidence changed; reread before deciding."""


def _today():
    return date.today()


def _json(value):
    def safe(item):
        if isinstance(item,float) and not math.isfinite(item):
            return {"invalid_float":repr(item)}
        if isinstance(item,bytes):
            return {"blob_hex":item.hex()}
        if isinstance(item,dict):
            return {str(k):safe(v) for k,v in item.items()}
        if isinstance(item,(tuple,list)):
            return [safe(v) for v in item]
        return item
    return json.dumps(safe(value),sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False)


def _hash(value):
    # Runtime observations must be hashed in full, not through prescription
    # hashing, which deliberately excludes activity/compliance content.
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _columns(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _native_key(revision, workout):
    return f"canonical:{revision}:{workout}"


def _legacy_workout(row):
    raw = dict(row)
    try:
        structure = json.loads(raw["structure_json"] or "{}")
        meta = structure.get("workout", {}) if isinstance(structure,dict) else {}
        if not isinstance(meta,dict) or meta.get("date") not in (None,raw["scheduled_date"]):
            meta = {}
            structure = {}
    except (ValueError,TypeError):
        meta = {}
        structure = {}
    kind = sport(meta.get("sport"))
    if meta.get("intensity") == "rest" or meta.get("phase") == "REST":
        kind = "REST"
    return dict(key=f'legacy:{raw["planned_workout_id"]}',plan_id=LEGACY,revision_id=None,workout_id=None,
        legacy_id=raw["planned_workout_id"],legacy=True,source_snapshot=json.loads(_json(raw)),workout_sha256=_hash(raw),
        date=raw["scheduled_date"],title=raw["workout_name"] or "Saved workout",sport=kind,rest=kind == "REST",
        duration_s=0 if kind == "REST" else amount(raw["planned_duration_s"]),distance_m=0 if kind == "REST" else amount(raw["planned_distance_m"]),
        duration_estimated=kind != "REST" and amount(raw["planned_duration_s"]) is not None,
        distance_estimated=kind != "REST" and amount(raw["planned_distance_m"]) is not None,
        activity_id=None,explicitly_completed=_marked_done(structure) if isinstance(structure,dict) else False)


def _marked_done(value, depth=0):
    if depth > 32:
        return False
    if isinstance(value,dict):
        for key,item in value.items():
            if key in {"workouts","day_plans","history","activities"}:
                continue
            if key in {"completed","explicitly_completed"} and (item is True or type(item) is int and item == 1 or isinstance(item,str) and item.lower() in {"true","completed","done"}):
                return True
            if key == "status" and isinstance(item,str) and item.lower() == "completed":
                return True
            if _marked_done(item,depth+1):
                return True
    elif isinstance(value,list):
        return any(_marked_done(item,depth+1) for item in value)
    return False


def _read_snapshot(conn, start, end, window, today):
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    active = active_chart_plan_data(None,_connection=conn)
    warnings, workouts = [], []
    labels = {r["plan_id"]:r["name"] for r in conn.execute("SELECT plan_id,name FROM season_plan WHERE plan_id IS NOT NULL")}
    plans = [dict(p,name=labels.get(p["id"],"Structured plan " + p["id"])) for p in active["plans"]]
    for w in active["workouts"]:
        rid,wid = origin_identity(conn,w["revision_id"],w["workout_id"])
        workouts.append(dict(w,key=_native_key(rid,wid),origin_revision_id=rid,origin_workout_id=wid,legacy=False,
            duration_s=amount(w["duration_s"]),distance_m=amount(w["distance_m"])))
    legacy_raw = {}
    for row in conn.execute("SELECT * FROM active_planned_workout WHERE source_plan_id IS NULL ORDER BY scheduled_date,planned_workout_id"):
        w = _legacy_workout(row)
        legacy_raw[w["legacy_id"]] = w
        if calendar_day(w["date"]) is None:
            warnings.append(f'Saved workout {w["legacy_id"]} has an invalid date and cannot be matched.')
            continue
        workouts.append(w)
    if legacy_raw:
        plans.append(dict(id=LEGACY,name="Saved older workouts",anchor=min(w["date"] for w in legacy_raw.values()),revision=None))
    if len(workouts) > 10000:
        raise MatchReviewError("Compliance is limited to 10,000 active workout occurrences.")
    if len({w["key"] for w in workouts}) != len(workouts):
        raise MatchReviewError("Active workout origins are duplicated. Repair their provenance before matching.")
    matches = []
    for row in conn.execute("SELECT * FROM activity_workout_match ORDER BY activity_workout_match_id"):
        m = dict(row)
        rid,wid = origin_identity(conn,m["revision_id"],m["workout_id"])
        matches.append(dict(m,workout_key=_native_key(rid,wid),legacy=False,current_source=True))
    legacy_supported = "legacy_activity_workout_match" in tables and "workout_compliance_review" in tables
    if legacy_supported:
        for row in conn.execute("SELECT * FROM legacy_activity_workout_match ORDER BY legacy_match_id"):
            m = dict(row)
            original = conn.execute("SELECT * FROM planned_workout WHERE planned_workout_id=?",(m["planned_workout_id"],)).fetchone()
            if m["status"] == "CONFIRMED":
                if not original or _hash(dict(original)) != m["workout_sha256"] or _hash(json.loads(m["workout_snapshot_json"])) != m["workout_sha256"]:
                    raise MatchReviewError("Confirmed older-workout evidence differs from its saved original.")
            current = legacy_raw.get(m["planned_workout_id"])
            matches.append(dict(m,workout_key=f'legacy:{m["planned_workout_id"]}',legacy=True,
                current_source=bool(current and current["workout_sha256"] == m["workout_sha256"])))
            if current and m["status"] == "CONFIRMED" and current["sport"] == "UNKNOWN":
                current["sport"] = m["reviewed_sport"]
                current["sport_from_review"] = True
    confirmed = [m for m in matches if m["status"] == "CONFIRMED"]
    if len({m["activity_id"] for m in confirmed}) != len(confirmed) or len({m["workout_key"] for m in confirmed}) != len(confirmed):
        raise MatchReviewError("Confirmed associations conflict. Repair the evidence before reviewing new matches.")
    by_key = {m["workout_key"]:m for m in confirmed}
    for w in workouts:
        if w["key"] in by_key:
            w["activity_id"] = by_key[w["key"]]["activity_id"]
    columns = _columns(conn,"activity")
    available = "activity_id" in columns
    activities, invalid_dates = [], 0
    if available:
        day_sql = activity_calendar_day_sql(conn)
        fields = ("activity_id","activity_name","activity_type","start_time_local","start_time_gmt","duration_seconds","moving_duration_seconds","elapsed_duration_seconds","distance_meters")
        projections = [f if f in columns else f"NULL AS {f}" for f in fields]
        low,high = (start-window*DAY).isoformat(), min(end+window*DAY,today).isoformat()
        found = {r["activity_id"]:dict(r) for r in conn.execute(f"SELECT {day_sql} AS date, {','.join(projections)} FROM activity WHERE {day_sql} BETWEEN ? AND ? ORDER BY activity_id",(low,high))}
        ids = sorted({w["activity_id"] for w in workouts if w["activity_id"] is not None}-found.keys())
        for i in range(0,len(ids),400):
            chunk = ids[i:i+400]
            for r in conn.execute(f"SELECT {day_sql} AS date, {','.join(projections)} FROM activity WHERE activity_id IN ({','.join('?' for _ in chunk)})",chunk):
                found[r["activity_id"]] = dict(r)
        invalid_dates = conn.execute(f"SELECT COUNT(*) FROM activity WHERE {day_sql} IS NULL").fetchone()[0]
        if len(found) > 25000:
            raise MatchReviewError("Compliance is limited to 25,000 source activities per view.")
        for aid,raw in sorted(found.items()):
            duration = next(((amount(raw[f]),f) for f in ("duration_seconds","moving_duration_seconds","elapsed_duration_seconds") if amount(raw[f]) is not None),(None,None))
            activities.append(dict(id=aid,name=raw["activity_name"] or "Activity " + str(aid),sport=raw["activity_type"],
                date=raw["date"] if calendar_day(raw["date"]) else None,duration_s=duration[0],duration_source=duration[1],
                distance_m=amount(raw["distance_meters"]),source=json.loads(_json(raw))))
    return dict(plans=plans,workouts=workouts,activities=activities,matches=matches,
        activity_available=available,invalid_activity_dates=invalid_dates,legacy_supported=legacy_supported,warnings=warnings,
        revision_pointers=[tuple(r) for r in conn.execute("SELECT plan_id,current_revision_id FROM training_plan ORDER BY plan_id")])


def _options(start, end, window, plan_id, today):
    first,last = calendar_day(start),calendar_day(end)
    if first is None or last is None or first > last or (last-first).days > 365:
        raise MatchReviewError("Choose ordered dates spanning no more than 366 days.")
    if type(window) is not int or not 1 <= window <= 14:
        raise MatchReviewError("Matching date window must be 1–14 days.")
    try:
        first-window*DAY
        last+window*DAY
    except OverflowError as exc:
        raise MatchReviewError("These dates cannot support the requested matching window.") from exc
    return dict(start=start,end=end,window=window,plan_id=plan_id,today=today.isoformat(),policy=POLICY_VERSION)


def _view(conn, options, review_id):
    start,end,today = (calendar_day(options[k]) for k in ("start","end","today"))
    snapshot = _read_snapshot(conn,start,end,options["window"],today)
    if options["plan_id"] not in {ALL,*[p["id"] for p in snapshot["plans"]]}:
        raise MatchReviewError("The selected active schedule is no longer available. Choose a current schedule.")
    data = prepare_compliance(snapshot,start=start,end=end,today=today,window=options["window"],plan_id=options["plan_id"])
    document = dict(options=options,snapshot=snapshot,data=data)
    return dict(review_id=review_id,document_json=_json(document),fingerprint=_hash(document),**document)


def compliance_view(db_path, *, start=None, end=None, window=3, plan_id=ALL):
    today = _today()
    options = _options(start or (today-29*DAY).isoformat(),end or today.isoformat(),window,plan_id,today)
    with closing(sqlite3.connect(Path(db_path).resolve().as_uri()+"?mode=ro",uri=True,timeout=10)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN")
        return _view(conn,options,uuid4().hex)


def review_pairs(db_path, view, decisions, *, reviewer, reason, failure_hook=None):
    """One explicit review, no implicit matching or schedule/activity modification."""
    if not isinstance(reviewer,str) or not reviewer.strip() or not isinstance(reason,str) or not reason.strip():
        raise MatchReviewError("Match reviews require a reviewer and reason.")
    if not decisions or len(decisions) > 200:
        raise MatchReviewError("Select 1–200 activity/workout pairs to review.")
    decisions = [dict(d) for d in decisions]
    if any(set(d) != {"workout_key","activity_id","status"} or type(d["activity_id"]) is not int or d["status"] not in {"CONFIRMED","REJECTED"} for d in decisions):
        raise MatchReviewError("Invalid match review selection.")
    if len({(d["workout_key"],d["activity_id"]) for d in decisions}) != len(decisions):
        raise MatchReviewError("The review contains a duplicate pair.")
    chosen = [d for d in decisions if d["status"] == "CONFIRMED"]
    if len({d["workout_key"] for d in chosen}) != len(chosen) or len({d["activity_id"] for d in chosen}) != len(chosen):
        raise MatchReviewError("One activity and one workout can each have only one confirmed association.")
    frozen = dict(options=view["options"],snapshot=view["snapshot"],data=view["data"])
    if _json(frozen) != view["document_json"] or _hash(frozen) != view["fingerprint"]:
        raise StaleMatchReviewError("The reviewed content was changed. Refresh compliance before reviewing.")
    if not view["snapshot"]["legacy_supported"]:
        raise MatchReviewError("Restart the source app to initialize match-review storage before saving associations.")
    request = dict(review_id=view["review_id"],fingerprint=view["fingerprint"],decisions=decisions,reviewer=reviewer.strip(),reason=reason.strip())
    request_sha = _hash(request)
    path = Path(db_path)
    if not path.is_file():
        raise MatchReviewError("The configured Garmin database does not exist.")
    conn = connect_sqlite(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute("SELECT request_sha256 FROM workout_compliance_review WHERE review_id=?",(view["review_id"],)).fetchone()
        if existing:
            if existing[0] != request_sha:
                raise StaleMatchReviewError("This review identity was already used for different decisions.")
            conn.rollback()
            return dict(status="duplicate",review_id=view["review_id"],decisions=len(decisions))
        if view["options"]["today"] != _today().isoformat() or view["options"]["policy"] != POLICY_VERSION:
            raise StaleMatchReviewError("Local date or matching policy changed. Refresh compliance before reviewing.")
        current = _view(conn,view["options"],view["review_id"])
        if current["document_json"] != view["document_json"]:
            raise StaleMatchReviewError("Workouts, activities or match evidence changed. Refresh compliance before reviewing.")
        work = {w["key"]:w for w in current["data"]["workouts"]}
        acts = {a["id"]:a for a in current["snapshot"]["activities"]}
        global_claims = {m["activity_id"]:m for m in current["snapshot"]["matches"] if m["status"] == "CONFIRMED"}
        evidence = []
        for d in decisions:
            w,a = work.get(d["workout_key"]),acts.get(d["activity_id"])
            pair = pair_evidence(w,a,view["options"]["window"],manual=True) if w and a else None
            if pair is None or calendar_day(a["date"]) > _today():
                raise MatchReviewError("Selected pair must be an active non-rest workout and a dated compatible activity within the displayed matching window.")
            if w["activity_id"] is not None or d["activity_id"] in global_claims:
                raise MatchReviewError("This activity or workout already has an immutable confirmed match.")
            evidence.append(dict(decision=d,pair=pair,workout=w,activity=a))
        receipt = dict(request=request,evidence=evidence,source_document=json.loads(view["document_json"]))
        conn.execute("INSERT INTO workout_compliance_review(review_id,request_sha256,input_sha256,policy_version,reviewer,reason,review_json) VALUES(?,?,?,?,?,?,?)",
            (view["review_id"],request_sha,view["fingerprint"],POLICY_VERSION,reviewer.strip(),reason.strip(),_json(receipt)))
        if failure_hook:
            failure_hook("after_receipt",conn)
        for item in evidence:
            d,w,pair = item["decision"],item["workout"],item["pair"]
            note = reason.strip() + " · " + _json(dict(review_id=view["review_id"],policy=POLICY_VERSION,pair=pair))
            if w["legacy"]:
                prior = conn.execute("SELECT legacy_match_id FROM legacy_activity_workout_match WHERE planned_workout_id=? AND workout_sha256=? AND activity_id=?",
                    (w["legacy_id"],w["workout_sha256"],d["activity_id"])).fetchone()
                if prior:
                    conn.execute("UPDATE legacy_activity_workout_match SET status=?,reviewed_sport=?,review_id=?,reviewer=?,reason=?,updated_at_utc=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE legacy_match_id=?",
                        (d["status"],pair["reviewed_sport"],view["review_id"],reviewer.strip(),note,prior[0]))
                else:
                    conn.execute("INSERT INTO legacy_activity_workout_match(planned_workout_id,workout_sha256,workout_snapshot_json,activity_id,reviewed_sport,status,review_id,reviewer,reason) VALUES(?,?,?,?,?,?,?,?,?)",
                        (w["legacy_id"],w["workout_sha256"],_json(w["source_snapshot"]),d["activity_id"],pair["reviewed_sport"],d["status"],view["review_id"],reviewer.strip(),note))
            else:
                prior = conn.execute("SELECT activity_workout_match_id FROM activity_workout_match WHERE revision_id=? AND workout_id=? AND activity_id=?",
                    (w["origin_revision_id"],w["origin_workout_id"],d["activity_id"])).fetchone()
                if prior:
                    review_match(conn,activity_workout_match_id=prior[0],status=d["status"],reviewer=reviewer.strip(),reason=note)
                else:
                    similarity = next((e for e in current["data"]["suggestions"] if e["workout_key"] == w["key"] and e["activity_id"] == d["activity_id"]),{})
                    create_match(conn,revision_id=w["origin_revision_id"],workout_id=w["origin_workout_id"],activity_id=d["activity_id"],
                        status=d["status"],source="RECONCILIATION" if similarity else "MANUAL",confidence=similarity.get("confidence","UNKNOWN"),
                        reviewer=reviewer.strip(),reason=note)
            if d["status"] == "CONFIRMED":
                for other in conn.execute("SELECT activity_workout_match_id FROM activity_workout_match WHERE status='CANDIDATE' AND (activity_id=? OR (revision_id=? AND workout_id=?))",
                    (d["activity_id"],w.get("origin_revision_id"),w.get("origin_workout_id"))).fetchall():
                    review_match(conn,activity_workout_match_id=other[0],status="REJECTED",reviewer=reviewer.strip(),reason="Alternative rejected by explicit match review " + view["review_id"])
            if failure_hook:
                failure_hook("after_decision",conn)
        conn.commit()
        return dict(status="applied",review_id=view["review_id"],decisions=len(decisions))
    except (sqlite3.Error,MatchPersistenceError) as exc:
        conn.rollback()
        raise MatchReviewError("Match review could not be stored: " + str(exc)) from exc
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
