"""Read-only explanation of schedule ownership blocking an initial season."""
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
import sqlite3

from garmin_data_hub.services import season_plans as plans


@dataclass(frozen=True)
class OverlapReview:
    season: plans.Season
    workouts: tuple[dict, ...]
    candidates: tuple[dict, ...]
    legacy_count: int
    separate_start: str | None
    separate_reason: str


def review_overlap(db_path, season_id) -> OverlapReview:
    # This diagnostic must never migrate, convert, link or rewrite schedules.
    conn = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        season = plans._get(conn, season_id)
        rows = tuple(dict(r) for r in conn.execute("""SELECT planned_workout_id,
            scheduled_date,workout_name,source_plan_id,source_revision_id,source_workout_id
            FROM active_planned_workout WHERE scheduled_date BETWEEN ? AND ?
            AND (source_plan_id IS NULL OR source_plan_id != ?)
            ORDER BY scheduled_date,planned_workout_id""",
            (season.start_date, season.end_date, season.plan_id or "")))
        candidates = []
        for row in conn.execute("""SELECT p.plan_id,p.current_revision_id,r.content_sha256,
            r.methodology_id,MIN(w.scheduled_date) AS start_date,
            MAX(w.scheduled_date) AS end_date,COUNT(w.workout_id) AS workout_count
            FROM training_plan p JOIN plan_revision r ON r.revision_id=p.current_revision_id
            JOIN plan_revision_workout w ON w.revision_id=r.revision_id
            WHERE NOT EXISTS (SELECT 1 FROM season_plan s WHERE s.plan_id=p.plan_id)
            AND EXISTS (SELECT 1 FROM active_planned_workout a WHERE a.source_plan_id=p.plan_id
                AND a.scheduled_date BETWEEN ? AND ?)
            GROUP BY p.plan_id ORDER BY start_date,p.plan_id""", (season.start_date, season.end_date)):
            candidate = dict(row)
            reasons = []
            if season.status == "archived":
                reasons.append("Restore this archived year before linking an existing plan.")
            if season.plan_id:
                reasons.append("This year already owns another plan.")
            if candidate["methodology_id"] != plans.METHODS[season.inputs.training_method]:
                reasons.append("The existing plan uses a different training method.")
            if conn.execute("""SELECT 1 FROM plan_revision_workout w JOIN plan_revision r USING(revision_id)
                WHERE r.plan_id=? AND (w.scheduled_date < ? OR w.scheduled_date > ? OR w.sport != 'RUNNING')""",
                (candidate["plan_id"], season.start_date, season.end_date)).fetchone():
                reasons.append("Yearly dates must contain every workout and all prior running-plan history.")
            if any(w["source_plan_id"] != candidate["plan_id"] for w in rows):
                reasons.append("Other overlapping workouts would still block this year.")
            candidate["reasons"] = tuple(reasons)
            candidates.append(candidate)
        separate_start, separate_reason = None, ""
        if rows and not season.plan_id and season.status != "archived":
            from garmin_data_hub.services.season_generation import _local_today
            start = max(date.fromisoformat(rows[-1]["scheduled_date"]) + timedelta(days=1),
                        _local_today(season.timezone))
            if start.isoformat() > season.end_date:
                separate_reason = "Existing workouts reach the end of this year; no separate dates remain within it."
            elif conn.execute("SELECT 1 FROM season_event WHERE season_id=? AND event_date < ?",
                              (season_id,start.isoformat())).fetchone():
                separate_reason = "Starting after the overlap would exclude a saved event. Review event dates or choose a different yearly range."
            else:
                separate_start = start.isoformat()
        return OverlapReview(season, rows, tuple(candidates),
                             sum(w["source_plan_id"] is None for w in rows),
                             separate_start, separate_reason)
    finally:
        conn.close()
