"""Read-only recovery assessment and explicit sleep-target preferences."""
from __future__ import annotations

from contextlib import closing
from datetime import date, timedelta
import json
from pathlib import Path
import sqlite3

from garmin_data_hub.analytics.sleep_recovery import read_recovery_inputs, _parse_date
from garmin_data_hub.analytics.recovery_readiness import analyze_recovery_inputs, number, POLICY_VERSION

SETTING_KEY = "recovery_sleep_target_hours"
DEFAULT_SLEEP_TARGET = 8.0


def _sleep_target(conn):
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_settings'").fetchone()
    raw = conn.execute("SELECT value FROM app_settings WHERE key=?", (SETTING_KEY,)).fetchone() if exists else None
    if raw is None:
        return DEFAULT_SLEEP_TARGET
    value = number(raw[0], 6, 12)
    if value is None:
        raise ValueError("Saved recovery sleep target is invalid. Save a target between 6 and 12 hours.")
    return value


def save_sleep_target(db_path, hours):
    value = number(hours, 6, 12)
    if value is None:
        raise ValueError("Sleep target must be between 6 and 12 hours.")
    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError("The configured Garmin database does not exist.")
    # Existing app_settings; no migrations, metric or workout writes.
    with closing(sqlite3.connect(path)) as conn, conn:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(app_settings)")}
        timestamp = ",updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')" if "updated_at" in columns else ""
        conn.execute("INSERT INTO app_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value" + timestamp,
            (SETTING_KEY, str(value)))
    return value


def recovery_assessment(db_path, *, assessment_date=None, history_days=30, today=None, _connection=None):
    today = today or date.today()
    assessed = _parse_date(assessment_date or today, "Assessment date")
    if type(history_days) is not int or not 1 <= history_days <= 90:
        raise ValueError("Recovery history must be 1–90 days.")
    if assessed > today:
        raise ValueError("Recovery assessments cannot use a future date.")
    try:
        first = assessed-timedelta(days=history_days+42)
    except OverflowError as exc:
        raise ValueError("Assessment date is too early for the required recovery history.") from exc
    def read(conn):
        conn.row_factory = sqlite3.Row
        target = _sleep_target(conn)
        inputs = read_recovery_inputs(conn, first, assessed)
        return target, inputs
    if _connection is not None:
        target, inputs = read(_connection)
    else:
        with closing(sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True, timeout=10)) as conn:
            conn.execute("BEGIN")
            target, inputs = read(conn)
    result = analyze_recovery_inputs(inputs, assessment_date=assessed, history_days=history_days,
        sleep_target_hours=target, today=today)
    # Deterministic input identity makes the score explainable/reproducible without
    # retaining raw health JSON or creating a second persistent calculation cache.
    import hashlib
    result["input_sha256"] = hashlib.sha256(json.dumps(dict(inputs=inputs, sleep_target=target,
        date=assessed.isoformat(), history_days=history_days, policy=POLICY_VERSION),
        sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
    return result
