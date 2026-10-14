"""One reviewed, atomic restart of the eligible future year; originals remain immutable."""
from __future__ import annotations

from contextlib import closing
from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta
import hashlib
import json
from uuid import uuid4
from zoneinfo import ZoneInfo

from garmin_data_hub.services import season_plans as plans, season_generation as generation
from garmin_data_hub.services import legacy_workout_removal as legacy
from garmin_data_hub.services.season_schedule import generate_season_schedule, ScheduleIssue, monday, event_windows
from garmin_data_hub.services.season_regeneration import protection
from garmin_data_hub.plan_methodology.canonical import canonical_value, canonical_json, content_sha256
from garmin_data_hub.plan_methodology.domain import RevisionReason
from garmin_data_hub.plan_methodology.revision_repository import load_revision, _approve_revision_on_connection
from garmin_data_hub.plan_methodology.workout_origin import origin_identity, prescribed_content, prescribed_sha256, insert_origins

POLICY = "yearly-reset.v1"


@dataclass(frozen=True)
class ResetPreview:
    preview_id: str
    season_id: str
    restart_date: str
    replace_protected: bool
    clear_events: bool
    settings: object
    document_json: str
    fingerprint: str
    schedule: object
    foreign: tuple
    blockers: tuple[str, ...]

    @property
    def can_apply(self):
        return not self.blockers and not self.schedule.errors


def _state_document(conn, season, start, replace_protected, clear_events):
    today = generation._local_today(season.timezone)
    if season.status == "archived":
        raise plans.SeasonError("Restore the yearly plan before restarting it.")
    if not max(date.fromisoformat(season.start_date), today+timedelta(days=1)) <= start <= date.fromisoformat(season.end_date):
        raise plans.SeasonError("Choose a restart date after today and within the selected year. Today's workouts and history are retained.")
    if type(replace_protected) is not bool or type(clear_events) is not bool:
        raise plans.SeasonError("Choose explicit restart options.")
    events = generation._events(conn, season)
    rows = [dict(r) for r in conn.execute("SELECT * FROM active_planned_workout WHERE scheduled_date BETWEEN ? AND ? ORDER BY planned_workout_id",
        (season.start_date, season.end_date))]
    cache = conn.execute("SELECT value FROM app_settings WHERE key='last_generated_plan'").fetchone()
    # Only date evidence is used; metric refreshes are not a reason to rewrite history.
    activities = sorted(legacy._activity_dates(conn, ZoneInfo(season.timezone)))
    document = {"policy":POLICY, "generator":generation.GENERATOR_VERSION, "generation_policy":generation.POLICY_VERSION,
        "season":asdict(season), "events":[asdict(e) for e in events], "restart_date":start.isoformat(),
        "local_today":today.isoformat(), "replace_protected":replace_protected, "clear_events":clear_events,
        "rows":rows, "state":generation._state(conn), "activity_dates":activities,
        "previous_generated_plan_cache":cache[0] if cache else None,
        "season_owners":[dict(r) for r in conn.execute("SELECT season_id,plan_id,start_date,end_date,status,input_version FROM season_plan ORDER BY season_id")]}
    return document, events, today


def _completed_metadata(value):
    if isinstance(value, dict):
        for key,item in value.items():
            if key in {"completed","explicitly_completed"} and item not in (False,None,0,"","false","False"):
                return True
            if key == "status" and str(item).lower() in {"completed","confirmed"}:
                return True
            if key == "flags":
                flags = item.split(",") if isinstance(item,str) else item if isinstance(item,list) else []
                if any(str(f).strip().upper() in {"COMPLETED","CONFIRMED"} for f in flags):
                    return True
            if _completed_metadata(item):
                return True
    elif isinstance(value,list):
        return any(_completed_metadata(item) for item in value)
    return False


def _legacy_reason(conn, row, document):
    if legacy._confirmed_legacy_match(conn,row["planned_workout_id"]):
        return "Confirmed activity/workout completion"
    if row["scheduled_date"] in document["activity_dates"]:
        return "Recorded activity on this date"
    if conn.execute("SELECT 1 FROM legacy_plan_conversion_source_workout WHERE planned_workout_id=?",(row["planned_workout_id"],)).fetchone():
        return "Converted source history"
    try:
        metadata=json.loads(row["structure_json"]) if row["structure_json"] else {}
        if not isinstance(metadata,(dict,list)):
            raise ValueError()
        if _completed_metadata(metadata):
            return "Completed workout"
        if legacy._protected_metadata(metadata) and not document["replace_protected"]:
            return "Locked/manual workout (include it using the restart option)"
    except (ValueError,TypeError,RecursionError):
        return "Unreadable protection metadata; retained"
    return None


def _protected(conn, season, parent, start, replace_protected):
    span=(start,date.fromisoformat(season.end_date))
    fixed, decisions=protection(conn,season,parent,start,span,set())
    overrides={d["workout_id"] for d in decisions if replace_protected and span[0].isoformat() <= d["date"] <= span[1].isoformat()
        and any(x in d["reasons"] for x in ("locked","manually_edited","manually_created"))
        and not any(x in d["reasons"] for x in ("history","completed","unresolved_match"))}
    return protection(conn,season,parent,start,span,overrides)


def _origins(conn, parent, rows):
    return [{"workout_id":w.workout_id,"origin_revision_id":origin_identity(conn,parent.revision_id,w.workout_id)[0],
        "origin_workout_id":origin_identity(conn,parent.revision_id,w.workout_id)[1],"prescribed_sha256":prescribed_sha256(w)} for w in rows]


def _boundary_blockers(conn,season,events,start):
    blockers=[]
    for window in event_windows(season,events):
        if window.recovery_end.isoformat()>season.end_date and conn.execute(
            "SELECT 1 FROM active_planned_workout WHERE scheduled_date>? AND scheduled_date<=?",
            (season.end_date,window.recovery_end.isoformat())).fetchone():
            blockers.append("Event recovery extends into following-year workouts. Clear upcoming events in the restart or edit the event date.")
        if conn.execute("SELECT 1 FROM season_plan WHERE season_id!=? AND plan_id IS NOT NULL AND start_date>? AND start_date<=?",
            (season.season_id,season.end_date,window.recovery_end.isoformat())).fetchone():
            blockers.append("Event recovery extends into another yearly plan. Clear upcoming events in the restart or edit the event date.")
    for row in conn.execute("SELECT season_id FROM season_plan WHERE season_id!=? AND plan_id IS NOT NULL AND end_date<? AND end_date>=?",
        (season.season_id,season.start_date,(start-timedelta(days=42)).isoformat())):
        prior=plans._get(conn,row[0])
        if any(w.event_date<start<=w.recovery_end for w in event_windows(prior,generation._events(conn,prior))):
            blockers.append("A preceding yearly plan still requires recovery at this restart date. Choose a start after its recovery ends.")
    plans._overlap(conn,plans.SeasonDraft(season.name,season.start_date,season.end_date,season.timezone,season.inputs),season.season_id)
    return blockers


def _prepare(conn, season_id, start, settings, replace_protected, clear_events, identities=None):
    season=plans._get(conn,season_id)
    document,events,today=_state_document(conn,season,start,replace_protected,clear_events)
    identities=identities or {"preview":uuid4().hex,"plan":season.plan_id or uuid4().hex,"revision":uuid4().hex,"foreign":{}}
    upcoming=tuple(replace(e,draft=replace(e.draft,status="cancelled")) if clear_events and e.draft.status=="planned" and e.draft.event_date>=start.isoformat() else e for e in events)
    # Past intent remains in the audit. Only upcoming planned events and actual
    # completed-event recovery control the fresh future calendar.
    generating=tuple(e for e in upcoming if e.draft.status=="completed" or (e.draft.status=="planned" and e.draft.event_date>=start.isoformat()))
    parent_revision=load_revision(None,season.current_revision_id,_connection=conn) if season.current_revision_id else None
    if season.current_revision_id and parent_revision is None:
        raise plans.SeasonError("The yearly plan revision is missing. Repair its saved source before restarting.")
    parent=parent_revision.candidate if parent_revision else None
    fixed,decisions=_protected(conn,season,parent,start,replace_protected) if parent else ((),[])
    legacy_removed=[]; retained=[]; reserved=set(); blockers=_boundary_blockers(conn,season,generating,start); foreign=[]
    try:
        legacy._decode_cache(document["previous_generated_plan_cache"])
    except (ValueError,TypeError):
        blockers.append("The saved nutrition cache is unreadable; repair it before restarting so other years are retained.")
    def reserve(day):
        first=monday(date.fromisoformat(day))
        reserved.update(first+timedelta(days=i) for i in range(7))
    for row in document["rows"]:
        if row["scheduled_date"] < start.isoformat():
            continue
        if all(row[k] is None for k in ("source_plan_id","source_revision_id","source_workout_id")):
            reason=_legacy_reason(conn,row,document)
            if reason:
                retained.append({"date":row["scheduled_date"],"title":row["workout_name"],"reason":reason})
                reserve(row["scheduled_date"])
            else:
                legacy_removed.append(row["planned_workout_id"])
        elif any(row[k] is None for k in ("source_plan_id","source_revision_id","source_workout_id")):
            blockers.append("A future workout has incomplete source identity. Its data needs repair before a restart can safely replace it.")
    foreign_ids=sorted({r["source_plan_id"] for r in document["rows"] if r["source_plan_id"] and r["source_plan_id"] != season.plan_id
        and r["scheduled_date"]>=start.isoformat()})
    for pid in foreign_ids:
        owner=conn.execute("SELECT season_id FROM season_plan WHERE plan_id=?",(pid,)).fetchone()
        if owner:
            blockers.append("Another yearly plan owns future workouts in this range. Restart only that plan's own dates.")
            continue
        pointer=conn.execute("SELECT current_revision_id FROM training_plan WHERE plan_id=?",(pid,)).fetchone()
        previous=load_revision(None,pointer[0],_connection=conn) if pointer else None
        if previous is None:
            raise plans.SeasonError("An older structured workout has no verified current revision. Repair its source before restarting.")
        old=previous.candidate
        kept,other_decisions=_protected(conn,season,old,start,replace_protected)
        for w in kept:
            if start<=w.scheduled_date<=date.fromisoformat(season.end_date):
                retained.append({"date":w.scheduled_date.isoformat(),"title":w.title,"reason":"Completed/matched or locked/manual structured workout"})
                reserve(w.scheduled_date.isoformat())
        ids={w.workout_id for w in kept}
        removed=[w.workout_id for w in old.workouts if w.workout_id not in ids]
        if not removed:
            continue
        rid=identities["foreign"].setdefault(pid,uuid4().hex)
        candidate=replace(old,revision_id=rid,parent_revision_id=old.revision_id,reason=RevisionReason.REGENERATION,
            workouts=tuple(replace(w,ordinal=i) for i,w in enumerate(kept)),
            change_summary={"schema_version":"yearly-reset-retained.v1","season_id":season_id,"restart_date":start.isoformat(),
                "removed_workout_ids":removed,"origins":_origins(conn,old,kept),"replace_protected":replace_protected},
            validation_summary={"accepted":True,"rationale":"Exact original retained subset after reviewed year restart."}) if kept else None
        foreign.append((old,candidate,removed))
    schedule=generate_season_schedule(season,generating,settings,today=today,plan_id=identities["plan"],revision_id=identities["revision"],
        parent=parent,fixed_workouts=fixed,replacement_range=(start,date.fromisoformat(season.end_date)),
        refresh_parameters=True,preservation_cutover=start,reserved_dates=frozenset(reserved))
    own_removed=[w.workout_id for w in parent.workouts if w.workout_id not in {f.workout_id for f in fixed}] if parent else []
    document.update(workout_ids=legacy_removed,workouts=[r for r in document["rows"] if r["planned_workout_id"] in set(legacy_removed)],
        season_id=season_id,timezone=season.timezone)
    doc_json=legacy._json(document)
    details={"schema_version":POLICY,"restart_date":start.isoformat(),"replace_protected":replace_protected,"clear_events":clear_events,
        "legacy_removed":legacy_removed,"retained":retained,"reserved_dates":sorted(d.isoformat() for d in reserved),
        "foreign_removed":[{"plan_id":p.plan_id,"parent_revision_id":p.revision_id,"removed_workout_ids":removed,
            "resulting_revision_id":c.revision_id if c else None} for p,c,removed in foreign],"document_json":doc_json}
    origins=_origins(conn,parent,fixed) if parent else []
    summary={"schema_version":"season-regeneration-diff.v1","mode":"FROM_TODAY","range_start":start.isoformat(),"range_end":season.end_date,
        "preserved_workout_ids":[w.workout_id for w in fixed],"preserved":[d for d in decisions if d["workout_id"] in {w.workout_id for w in fixed}],"removed_workout_ids":own_removed,
        "added_workout_ids":[w.workout_id for w in schedule.candidate.workouts if w.workout_id not in {f.workout_id for f in fixed}],
        "changed":[],"origins":origins,"yearly_reset":details}
    goal=canonical_value(schedule.candidate.goal_snapshot)
    goal["events"]=[asdict(e) for e in upcoming]
    issues=schedule.issues
    if reserved:
        issues+=(ScheduleIssue("RESET_RETAINED_WEEKS","warning","Weeks containing retained workouts from other/older schedules receive no new workouts; their load is unverified. Completed history remains intact."),)
    # Do not pretend an entirely protected calendar has been rebuilt.
    if not summary["added_workout_ids"]:
        blockers.append("No eligible dates remain for fresh workouts. Include unfinished locked/manual workouts or choose a different future start.")
    candidate=replace(schedule.candidate,goal_snapshot=goal,change_summary=summary,
        validation_summary={**canonical_value(schedule.candidate.validation_summary),"issues":[asdict(i) for i in issues]})
    schedule=replace(schedule,candidate=candidate,issues=issues)
    fingerprint=content_sha256({"document":doc_json,"settings":asdict(settings),"candidate":candidate.content_hash,
        "foreign":[c.content_hash if c else p.content_hash for p,c,_ in foreign]})
    return ResetPreview(identities["preview"],season_id,start.isoformat(),replace_protected,clear_events,settings,doc_json,fingerprint,schedule,tuple(foreign),tuple(sorted(set(blockers))))


def preview_reset(db_path,season_id,settings,*,restart_date,replace_protected=False,clear_events=False):
    with closing(legacy._read_connection(db_path)) as conn:
        return _prepare(conn,season_id,plans._day(restart_date,"Restart date"),settings,replace_protected,clear_events)


def validate_initial_restart(conn,candidate,owner,start):
    reset=(candidate.change_summary or {}).get("yearly_reset",{})
    season=plans._get(conn,owner["season_id"])
    if (not conn.in_transaction or reset.get("schema_version")!=POLICY or reset.get("restart_date")!=start
        or not season.start_date<=start<=season.end_date or start<=generation._local_today(season.timezone).isoformat()):
        raise plans.SeasonError("Initial restart requires its reviewed future owner transaction.")


def validate_retained_revision(conn,candidate,season_id,start):
    season=plans._get(conn,season_id)
    if not conn.in_transaction or conn.execute("SELECT 1 FROM season_plan WHERE plan_id=?",(candidate.plan_id,)).fetchone():
        raise plans.SeasonError("Only unowned older structured plans can be superseded by this restart.")
    revision=load_revision(None,candidate.parent_revision_id,_connection=conn) if candidate.parent_revision_id else None
    if revision is None:
        raise plans.SeasonError("Retained restart revision requires a verified original parent.")
    old=revision.candidate
    if old.plan_id!=candidate.plan_id or candidate.change_summary.get("schema_version")!="yearly-reset-retained.v1":
        raise plans.SeasonError("Retained restart revision does not match its original plan.")
    kept,_=_protected(conn,season,old,date.fromisoformat(start),candidate.change_summary.get("replace_protected") is True)
    if [prescribed_content(w) for w in kept] != [prescribed_content(w) for w in candidate.workouts]:
        raise plans.SeasonError("Restart retirement must preserve the exact reviewed history/protected subset.")


def apply_reset(db_path,preview,*,approved_by,acknowledged=False,failure_hook=None):
    if not isinstance(preview,ResetPreview) or acknowledged is not True or not isinstance(approved_by,str) or not approved_by.strip():
        raise plans.SeasonError("Review and acknowledge the restart before applying it.")
    document_identity=json.loads(preview.document_json)
    computed_identity=content_sha256({"document":preview.document_json,"settings":asdict(preview.settings),"candidate":preview.schedule.candidate.content_hash,
        "foreign":[c.content_hash if c else p.content_hash for p,c,_ in preview.foreign]})
    if (computed_identity!=preview.fingerprint or document_identity["season"]["season_id"]!=preview.season_id
        or document_identity["restart_date"]!=preview.restart_date or document_identity["replace_protected"]!=preview.replace_protected
        or document_identity["clear_events"]!=preview.clear_events):
        raise generation.StalePreviewError("The reviewed restart content changed. Prepare a new review.")
    with plans._connection(db_path,write=True) as conn:
        duplicate=conn.execute("SELECT * FROM season_revision_application WHERE season_id=? AND preview_id=?",(preview.season_id,preview.preview_id)).fetchone()
        if duplicate:
            review=json.loads(duplicate["review_json"])
            if review.get("reset_fingerprint")!=preview.fingerprint or duplicate["candidate_sha256"]!=preview.schedule.candidate.content_hash:
                raise generation.StalePreviewError("The applied restart identity does not match this review.")
            return generation.SeasonApplyResult("duplicate",duplicate["application_id"],duplicate["plan_id"],duplicate["resulting_revision_id"],len(preview.schedule.candidate.workouts))
        document_before=json.loads(preview.document_json)
        if generation._local_today(plans._get(conn,preview.season_id).timezone).isoformat()!=document_before["local_today"]:
            raise generation.StalePreviewError("The local date changed. Review Redo this year again.")
        identities={"preview":preview.preview_id,"plan":preview.schedule.candidate.plan_id,"revision":preview.schedule.candidate.revision_id,
            "foreign":{p.plan_id:c.revision_id if c else "archived" for p,c,_ in preview.foreign}}
        fresh=_prepare(conn,preview.season_id,date.fromisoformat(preview.restart_date),preview.settings,preview.replace_protected,preview.clear_events,identities)
        if fresh.fingerprint!=preview.fingerprint or fresh.document_json!=preview.document_json:
            raise generation.StalePreviewError("Settings, events, workouts, activity evidence or the local date changed. Review Redo this year again.")
        if not fresh.can_apply:
            raise plans.SeasonError(" ".join((*fresh.blockers,*(i.message for i in fresh.schedule.errors))))
        generation._call_hook(failure_hook,"after_reset_recheck",conn)
        season=plans._get(conn,preview.season_id)
        candidate=fresh.schedule.candidate
        details=candidate.change_summary["yearly_reset"]
        document=json.loads(fresh.document_json)
        now=plans._stamp()
        removed=details["legacy_removed"]
        if removed:
            removal_id=uuid4().hex
            conn.execute("INSERT INTO legacy_workout_removal VALUES(?,?,?,?,?,?,?,?)",(removal_id,preview.preview_id,legacy._hash(document),fresh.document_json,
                season.timezone,document["local_today"],approved_by,now))
            conn.executemany("INSERT INTO legacy_workout_removal_item VALUES(?,?)",((wid,removal_id) for wid in removed))
        generation._call_hook(failure_hook,"after_reset_legacy",conn)
        for old,kept,_ in fresh.foreign:
            if kept:
                _approve_revision_on_connection(conn,kept,expected_content_hash=kept.content_hash,expected_parent_content_hash=old.content_hash,
                    approved_by=approved_by,_reset_retained_context=(season.season_id,preview.restart_date),failure_hook=failure_hook)
                insert_origins(conn,kept)
            else:
                # Exact eligible membership was rechecked above; originals remain in
                # their immutable revisions. An unowned empty plan is archived.
                conn.execute("DELETE FROM planned_workout WHERE source_plan_id=?",(old.plan_id,))
                conn.execute("UPDATE training_plan SET current_revision_id=NULL WHERE plan_id=?",(old.plan_id,))
        generation._call_hook(failure_hook,"after_reset_foreign",conn)
        if preview.clear_events:
            conn.execute("UPDATE season_event SET status='cancelled',updated_at_utc=? WHERE season_id=? AND status='planned' AND event_date>=?",
                (now,season.season_id,preview.restart_date))
        events=generation._events(conn,season)
        snapshot=generation._snapshot(season,events,preview.settings)
        if not season.plan_id:
            conn.execute("INSERT INTO training_plan VALUES(?,NULL,'NATIVE',?)",(candidate.plan_id,now))
        conn.execute("UPDATE season_plan SET plan_id=?,status='active',input_version=input_version+1,updated_at_utc=? WHERE season_id=?",
            (candidate.plan_id,now,season.season_id))
        result=_approve_revision_on_connection(conn,candidate,expected_content_hash=candidate.content_hash,
            expected_parent_content_hash=load_revision(None,season.current_revision_id,_connection=conn).content_hash if season.current_revision_id else None,
            approved_by=approved_by,_season_initial_owner=season.season_id if not season.current_revision_id else None,
            _season_regeneration_owner=season.season_id if season.current_revision_id else None,
            _season_reset_start=preview.restart_date if not season.current_revision_id else None,failure_hook=failure_hook)
        insert_origins(conn,candidate)
        generation._invalidate_nutrition(conn,preview.restart_date,season.end_date)
        generation._call_hook(failure_hook,"after_reset_schedule",conn)
        application_id=uuid4().hex
        review={"schema_version":"yearly-reset-review.v1","reset_fingerprint":preview.fingerprint,"rationale":"Reviewed Redo this year; exact future replacements and retained history.",
            "diff":canonical_value(candidate.change_summary),"warnings":[asdict(i) for i in fresh.schedule.warnings],"warnings_acknowledged":True,"preserved":canonical_value(candidate.change_summary["preserved"])}
        conn.execute("INSERT INTO season_revision_application VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (application_id,preview.preview_id,season.season_id,candidate.plan_id,result.revision_id,season.current_revision_id,season.input_version,
             hashlib.sha256(snapshot.encode()).hexdigest(),candidate.content_hash,snapshot,canonical_json(review),generation.GENERATOR_VERSION,generation.POLICY_VERSION,
             document["local_today"],season.timezone,preview.restart_date,season.end_date,"FROM_TODAY",approved_by,now))
        generation._call_hook(failure_hook,"before_reset_commit",conn)
        return generation.SeasonApplyResult("applied",application_id,candidate.plan_id,result.revision_id,len(candidate.workouts))
