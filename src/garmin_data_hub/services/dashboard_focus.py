"""Read-only seven-day schedule, reviewed completion and current recovery."""
from __future__ import annotations

from contextlib import closing
from datetime import date, datetime
from pathlib import Path
import sqlite3
import logging
from zoneinfo import ZoneInfo

from garmin_data_hub.analytics.workout_compliance import ALL, DAY
from garmin_data_hub.services.workout_compliance import _options, _view
from garmin_data_hub.services.recovery_readiness import recovery_assessment
from garmin_data_hub.services.season_plans import _get, SeasonError

logger = logging.getLogger(__name__)


def _local_today(timezone):
    return datetime.now(ZoneInfo(timezone)).date() if timezone else date.today()


def dashboard_focus(db_path, *, season_id="", today=None):
    """One coherent snapshot; suggestions never become completion or writes."""
    with closing(sqlite3.connect(Path(db_path).resolve().as_uri()+"?mode=ro", uri=True, timeout=10)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN")
        season = _get(conn, season_id) if season_id else None
        if season and season.status == "archived":
            raise SeasonError("This yearly plan is archived. Select an active yearly plan.")
        today = today or _local_today(season.timezone if season else None)
        first, last = today-7*DAY, today+6*DAY
        options = _options(first.isoformat(), last.isoformat(), 3, season.plan_id if season and season.plan_id else ALL, today)
        view = _view(conn, options, "dashboard-read-only")
        data = view["data"]
        # A selected draft has no applied workouts. Never substitute other plans.
        rows = [] if season and not season.plan_id else data["workouts"]
        events = [dict(row) for row in conn.execute(
            """SELECT e.event_id,e.season_id,e.name,e.event_date,e.priority,e.distance_code
               FROM season_event e JOIN season_plan s ON s.season_id=e.season_id
               WHERE e.status IN ('planned','completed') AND s.status!='archived'
                 AND e.event_date BETWEEN ? AND ? AND (?='' OR e.season_id=?)
               ORDER BY e.event_date,e.event_id""",
            (today.isoformat(), last.isoformat(), season_id, season_id))]
        days = [dict(date=(today+i*DAY).isoformat(),
                     sessions=[r for r in rows if r["date"] == (today+i*DAY).isoformat()],
                     events=[e for e in events if e["event_date"] == (today+i*DAY).isoformat()])
                for i in range(7)]
        past = [r for r in rows if first.isoformat() <= r["date"] < today.isoformat() and not r["rest"]]
        # Recorded activities are athlete-wide; match/session counts follow scope.
        activities = [a for a in data["activities"] if a["date"] < today.isoformat()]
        recent = dict(start=first.isoformat(),end=(today-DAY).isoformat(),
            sessions=past, completed=sum(r["completion"] == "Completed" for r in past),
            partial=sum(r["completion"] == "Partial" for r in past),
            moved=sum(r["moved"] for r in past),missed=sum(r["status"] == "Missed" for r in past),
            needs_review=sum(r["status"] == "Needs review" for r in past),
            pending=sum(r["status"] in {"Awaiting activity","Evidence unavailable","Unverified amounts","Sport substitution"} or r["completion"] == "Unverified amounts" for r in past),
            activity_count=len(activities), extra=sum(a["status"] == "Extra" for a in activities))
        try:
            recovery = recovery_assessment(None, history_days=1, today=today, _connection=conn)
            recovery_error = None
        except ValueError as exc:
            recovery, recovery_error = None, str(exc)
        except sqlite3.Error as exc:
            logger.warning("Dashboard recovery evidence unavailable: %s",type(exc).__name__)
            recovery, recovery_error = None, "Recovery data could not be read. Open Recovery to inspect the source."
        return dict(today=today.isoformat(),end=last.isoformat(),days=days,recent=recent,
            scope=season.name if season else "All active schedules",
            season_id=season_id,timezone=season.timezone if season else "Computer local time",
            no_applied_plan=bool(season and not season.plan_id),
            recovery=recovery,recovery_error=recovery_error,warnings=view["snapshot"]["warnings"])
