"""Independent score properties, temporal coverage and read-only integration."""
from copy import deepcopy
from datetime import date, timedelta
import sqlite3

import pytest

from garmin_data_hub.analytics.recovery_readiness import (
    analyze_recovery_inputs, POLICY_VERSION,
)
from garmin_data_hub.services.recovery_readiness import recovery_assessment, save_sleep_target, SETTING_KEY
from garmin_data_hub.db.sqlite import connect_sqlite
from garmin_data_hub.db.migrate import apply_schema
from garmin_data_hub.paths import schema_sql_path

AS_OF = date(2026,10,14)


def inputs(end=AS_OF, days=85):
    tables = {t:{} for t in ("sleep","hrv","daily_summary","training_readiness","body_battery")}
    activities = []
    for i in range(days):
        day = (end-timedelta(days=days-1-i)).isoformat()
        tables["sleep"][day] = dict(sleep_time_seconds=28800, resting_heart_rate=50, sleep_score_overall=92, sleep_need_minutes=480)
        tables["hrv"][day] = dict(last_night_avg=50, status="BALANCED")
        tables["daily_summary"][day] = dict(resting_heart_rate=50, average_stress_level=10, body_battery_at_wake=90)
        tables["training_readiness"][day] = dict(score=95)
        if date.fromisoformat(day).weekday() in (0,2,4):
            activities.append(dict(date=day, activity_id=i+1, training_stress_score=60, duration_seconds=3600))
    return dict(tables=tables, activities=activities, undated_activities=0,
        sources={t:dict(available=True,days=len(rows)) for t,rows in tables.items()},
        rr_supported=False, rr_note="No supported beat-to-beat RR input.")


def result(data=None, day=AS_OF, days=1, target=8):
    return analyze_recovery_inputs(data or inputs(), assessment_date=day, history_days=days,
        sleep_target_hours=target, today=AS_OF)


def scores(data):
    return {key:item["score"] for key,item in result(data)["assessment"]["scores"].items()}


def test_fully_covered_reference_has_three_distinct_explained_scores():
    current = result()["assessment"]
    assert current["scores"]["recovery"]["score"] == 92
    assert current["scores"]["energy"]["score"] == 98
    assert current["scores"]["readiness"]["score"] >= 90
    assert all(s["confidence"] == "Well covered" for s in current["scores"].values())
    assert "not a reason to add intensity" in current["guidance"]
    for score in current["scores"].values():
        assert sum(d["weight_pct"] for d in score["drivers"]) == 100
        assert sum(d["used_weight_pct"] for d in score["drivers"]) == pytest.approx(100, abs=.2)


@pytest.mark.parametrize("field,table,value", [("last_night_avg","hrv",20), ("resting_heart_rate","sleep",65), ("sleep_time_seconds","sleep",14400)])
def test_unfavorable_current_measure_reduces_recovery(field, table, value):
    data = inputs()
    before = scores(data)
    data["tables"][table][AS_OF.isoformat()][field] = value
    after = scores(data)
    assert after["recovery"] < before["recovery"]
    assert after["readiness"] < before["readiness"]


def test_seven_bad_nights_and_multiple_unfavorable_signals_suggest_review():
    data = inputs()
    for i in range(7):
        day = (AS_OF-timedelta(days=i)).isoformat()
        data["tables"]["sleep"][day]["sleep_time_seconds"] = 10800
    data["tables"]["sleep"][AS_OF.isoformat()]["resting_heart_rate"] = 65
    data["tables"]["hrv"][AS_OF.isoformat()]["last_night_avg"] = 20
    current = result(data)["assessment"]
    assert current["scores"]["recovery"]["score"] < 50
    assert current["scores"]["readiness"]["score"] < 50
    assert "Consider rest or gentle movement" in current["guidance"]
    assert current["factors"]["shortfall"]["value"] == 35
    assert "below" in current["factors"]["hrv"]["detail"]
    assert current["factors"]["rhr"]["baseline"] == 50


def test_excess_sleep_does_not_cancel_observed_shortfall():
    data = inputs()
    data["tables"]["sleep"][AS_OF.isoformat()]["sleep_time_seconds"] = 36000
    data["tables"]["sleep"][(AS_OF-timedelta(days=1)).isoformat()]["sleep_time_seconds"] = 14400
    assert result(data)["assessment"]["factors"]["shortfall"]["value"] == 4


def test_unusually_high_hrv_is_not_rewarded():
    data = inputs()
    before = scores(data)["recovery"]
    data["tables"]["hrv"][AS_OF.isoformat()]["last_night_avg"] = 150
    current = result(data)["assessment"]
    assert current["scores"]["recovery"]["score"] < before
    assert "above" in current["factors"]["hrv"]["detail"]


def test_garmin_comparison_changes_never_change_app_scores():
    data = inputs()
    before = scores(data)
    day = AS_OF.isoformat()
    data["tables"]["sleep"][day].update(sleep_score_overall=0, sleep_need_minutes=720)
    data["tables"]["daily_summary"][day]["body_battery_at_wake"] = 0
    data["tables"]["training_readiness"][day]["score"] = 0
    data["tables"]["hrv"][day].update(status="LOW", weekly_avg=1, baseline_low=1, baseline_upper=2)
    assert scores(data) == before
    assert result(data)["assessment"]["garmin"]["readiness"] == 0


def test_no_future_or_same_day_training_or_stress_leakage():
    data = inputs()
    expected = result(data)["assessment"]
    data["tables"]["daily_summary"][AS_OF.isoformat()]["average_stress_level"] = 100
    data["activities"].append(dict(date=AS_OF.isoformat(),training_stress_score=10000,duration_seconds=72000))
    future = (AS_OF+timedelta(days=1)).isoformat()
    data["tables"]["sleep"][future] = dict(sleep_time_seconds=0,resting_heart_rate=150)
    data["tables"]["hrv"][future] = dict(last_night_avg=1)
    data["activities"].append(dict(date=future,training_stress_score=10000,duration_seconds=72000))
    assert result(data)["assessment"] == expected


def test_prior_day_stress_changes_scores_and_is_dated():
    data = inputs()
    before = scores(data)
    day = (AS_OF-timedelta(days=1)).isoformat()
    data["tables"]["daily_summary"][day]["average_stress_level"] = 90
    current = result(data)["assessment"]
    assert current["scores"]["energy"]["score"] < before["energy"]
    assert current["scores"]["recovery"]["score"] < before["recovery"]
    assert day in current["factors"]["stress"]["detail"]


def test_load_spike_reduces_readiness_and_reports_accumulation():
    data = inputs()
    before = scores(data)
    for a in data["activities"]:
        if (AS_OF-timedelta(days=7)).isoformat() <= a["date"] < AS_OF.isoformat():
            a["training_stress_score"] = 400
    current = result(data)["assessment"]
    assert current["scores"]["readiness"]["score"] < before["readiness"]
    assert current["scores"]["recovery"]["score"] == before["recovery"]
    load = current["factors"]["load"]["value"]
    assert load["acute"] > load["chronic"] and load["balance"] < 0 and load["mode"] == "TSS"


@pytest.mark.parametrize("missing", [("hrv",), ("hrv","sleep"), ("hrv","sleep","daily_summary")])
def test_missing_today_is_not_replaced_by_yesterdays_good_measure(missing):
    data = inputs()
    for table in missing:
        data["tables"][table].pop(AS_OF.isoformat())
    current = result(data)["assessment"]
    assert current["factors"]["hrv"]["score"] is None
    assert "No valid measurement" in current["factors"]["hrv"]["detail"]
    if "sleep" in missing:
        assert current["scores"]["recovery"]["score"] is None
        assert current["scores"]["readiness"]["score"] is None
        assert current["scores"]["energy"]["score"] is None
        assert "Insufficient" in current["guidance"]


def test_partial_coverage_is_explicit_and_sleep_missing_nights_not_scaled():
    data = inputs()
    for i in (1,2):
        data["tables"]["sleep"].pop((AS_OF-timedelta(days=i)).isoformat())
    current = result(data)["assessment"]
    assert current["factors"]["shortfall"]["observations"] == 5
    assert current["factors"]["shortfall"]["value"] == 0
    assert current["scores"]["energy"]["confidence"] == "Limited"
    for i in (3,4):
        data["tables"]["sleep"].pop((AS_OF-timedelta(days=i)).isoformat())
    assert result(data)["assessment"]["factors"]["shortfall"]["score"] is None


@pytest.mark.parametrize("days,allowed", [(14,False),(15,True),(29,True)])
def test_today_excluded_from_personal_baseline(days, allowed):
    current = result(inputs(days=days))["assessment"]
    assert current["factors"]["hrv"]["observations"] == min(days-1,28)
    assert (current["factors"]["hrv"]["score"] is not None) is allowed
    if days == 15:
        assert current["scores"]["recovery"]["confidence"] == "Limited"


def test_old_baseline_without_recent_observations_is_unavailable():
    data = inputs()
    for i in range(1,8):
        data["tables"]["hrv"].pop((AS_OF-timedelta(days=i)).isoformat())
    current = result(data)["assessment"]
    assert current["factors"]["hrv"]["observations"] == 21
    assert current["factors"]["hrv"]["score"] is None


@pytest.mark.parametrize("value", [None,True,False,-1,101,float('nan'),float('inf'),"invalid"])
def test_invalid_stress_or_vendor_score_is_missing(value):
    data = inputs()
    data["tables"]["daily_summary"][(AS_OF-timedelta(days=1)).isoformat()]["average_stress_level"] = value
    data["tables"]["training_readiness"][AS_OF.isoformat()]["score"] = value
    current = result(data)["assessment"]
    assert current["factors"]["stress"]["score"] is None
    assert current["garmin"]["readiness"] is None


def test_valid_zero_sleep_and_stress_are_not_missing():
    data = inputs()
    data["tables"]["sleep"][AS_OF.isoformat()]["sleep_time_seconds"] = 0
    data["tables"]["daily_summary"][(AS_OF-timedelta(days=1)).isoformat()]["average_stress_level"] = 0
    current = result(data)["assessment"]
    assert current["factors"]["sleep"]["score"] == 0
    assert current["factors"]["stress"]["score"] == 100


@pytest.mark.parametrize("problem", ["missing_tss","missing_duration","undated","daily_gap","zero"])
def test_load_missing_coverage_and_fallback_never_mix_units(problem):
    data = inputs()
    if problem == "undated":
        data["undated_activities"] = 1
    elif problem == "daily_gap":
        data["tables"]["daily_summary"].pop((AS_OF-timedelta(days=2)).isoformat())
    else:
        for a in data["activities"]:
            a["training_stress_score"] = 0 if problem == "zero" else None
            a["training_load"] = 100000  # never mix Garmin exercise load with TSS
            if problem == "missing_duration":
                a["duration_seconds"] = None
    factor = result(data)["assessment"]["factors"]["load"]
    if problem == "missing_tss":
        assert factor["score"] is not None and factor["value"]["mode"] == "Recorded hours"
        assert "without intensity" in factor["detail"]
        assert result(data)["assessment"]["scores"]["readiness"]["confidence"] == "Limited"
    else:
        assert factor["score"] is None


@pytest.mark.parametrize("days", [0,True,91,-1,1.5])
def test_history_limit_validation(days):
    with pytest.raises(ValueError,match="history"):
        result(days=days)


@pytest.mark.parametrize("target", [5,13,None,True,float('nan'),float('inf')])
def test_sleep_target_validation(target):
    with pytest.raises(ValueError,match="Sleep target"):
        result(target=target)


def test_missing_days_retained_as_gaps_not_favorable_scores():
    data = inputs(days=1)
    data["tables"] = {t:{} for t in data["tables"]}
    data["activities"] = []
    analysis = result(data,days=30)
    assert len(analysis["history"]) == 30
    assert all(s["score"] is None for r in analysis["history"] for s in r["scores"].values())
    assert analysis["latest_signal_date"] is None
    assert analysis["policy_version"] == POLICY_VERSION
    with pytest.raises(ValueError,match="future"):
        result(day=AS_OF+timedelta(days=1))


def health_database(tmp_path, end=AS_OF):
    path = tmp_path / "recovery.db"
    conn = connect_sqlite(path)
    apply_schema(conn,schema_sql_path())
    conn.executescript("""
        CREATE TABLE sleep(calendar_date TEXT PRIMARY KEY,sleep_time_seconds REAL,resting_heart_rate REAL,sleep_score_overall REAL);
        CREATE TABLE hrv(calendar_date TEXT PRIMARY KEY,last_night_avg REAL,status TEXT);
        CREATE TABLE daily_summary(calendar_date TEXT PRIMARY KEY,resting_heart_rate REAL,average_stress_level REAL,body_battery_at_wake REAL);
        CREATE TABLE training_readiness(calendar_date TEXT PRIMARY KEY,score REAL);
        CREATE TABLE activity(activity_id INTEGER PRIMARY KEY,start_time_local TEXT,start_time_gmt TEXT,duration_seconds REAL,training_stress_score REAL);
    """)
    data = inputs(end=end)
    for day, row in data["tables"]["sleep"].items():
        conn.execute("INSERT INTO sleep VALUES(?,?,?,?)", (day,row["sleep_time_seconds"],row["resting_heart_rate"],row["sleep_score_overall"]))
        conn.execute("INSERT INTO hrv VALUES(?,50,'BALANCED')", (day,))
        conn.execute("INSERT INTO daily_summary VALUES(?,50,10,90)", (day,))
        conn.execute("INSERT INTO training_readiness VALUES(?,95)", (day,))
    for a in data["activities"]:
        conn.execute("INSERT INTO activity VALUES(?,?,NULL,?,?)",(a["activity_id"],a["date"]+'T23:30:00-04:00',a["duration_seconds"],a["training_stress_score"]))
    conn.execute("INSERT INTO planned_workout(scheduled_date,workout_name,planned_duration_s) VALUES(?, '10 mile run', 6000)",(end.isoformat(),))
    conn.commit()
    conn.close()
    return path


def db_snapshot(path):
    with sqlite3.connect(path) as conn:
        return tuple(conn.iterdump())


def test_reader_and_assessment_are_read_only_reproducible_and_use_local_days(tmp_path):
    path = health_database(tmp_path)
    before = db_snapshot(path)
    a = recovery_assessment(path,assessment_date=AS_OF,today=AS_OF)
    b = recovery_assessment(path,assessment_date=AS_OF,today=AS_OF)
    assert a == b
    assert db_snapshot(path) == before
    assert a["assessment"]["scores"]["recovery"]["score"] == 92
    assert a["assessment"]["factors"]["load"]["score"] is not None
    assert not a["rr_supported"] and "not RR intervals" in a["rr_note"]


def test_preferences_save_only_target_and_recompute_without_workout_changes(tmp_path):
    path = health_database(tmp_path)
    with sqlite3.connect(path) as conn:
        before = tuple(conn.execute("SELECT * FROM planned_workout"))
    assert save_sleep_target(path,9) == 9
    analysis = recovery_assessment(path,assessment_date=AS_OF,today=AS_OF)
    assert analysis["sleep_target_hours"] == 9
    assert analysis["assessment"]["factors"]["shortfall"]["value"] == 7
    with sqlite3.connect(path) as conn:
        assert tuple(conn.execute("SELECT * FROM planned_workout")) == before
        assert conn.execute("SELECT value FROM app_settings WHERE key=?",(SETTING_KEY,)).fetchone()[0] == '9.0'
    before = db_snapshot(path)
    with pytest.raises(ValueError):
        save_sleep_target(path,True)
    assert db_snapshot(path) == before


def test_reader_tolerates_partial_or_absent_upstream_schema(tmp_path):
    path = tmp_path / "partial.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE sleep(calendar_date TEXT PRIMARY KEY, sleep_time_seconds REAL)")
        conn.execute("INSERT INTO sleep VALUES(?,28800)",(AS_OF.isoformat(),))
    result = recovery_assessment(path,assessment_date=AS_OF,today=AS_OF)
    assert result["assessment"]["factors"]["sleep"]["score"] == 100
    assert result["assessment"]["scores"]["recovery"]["score"] is None
    assert not result["sources"]["hrv"]["available"]


def test_corrupt_preference_has_explicit_error_and_can_be_repaired(tmp_path):
    path = health_database(tmp_path)
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO app_settings(key,value) VALUES(?,?)",(SETTING_KEY,'NaN'))
    with pytest.raises(ValueError,match="Saved recovery sleep target"):
        recovery_assessment(path,assessment_date=AS_OF,today=AS_OF)
    save_sleep_target(path,8)
    assert recovery_assessment(path,assessment_date=AS_OF,today=AS_OF)["sleep_target_hours"] == 8


def test_numeric_string_target_is_normalized_and_input_is_not_mutated():
    data = inputs()
    before = deepcopy(data)
    assert scores(data) == {key:item["score"] for key,item in result(data,target="8")["assessment"]["scores"].items()}
    assert data == before


def test_derived_tss_reuses_current_provenance_and_rejects_stale_rows(tmp_path):
    from garmin_data_hub.db import queries
    path = health_database(tmp_path)
    with connect_sqlite(path) as conn:
        conn.execute("UPDATE activity SET training_stress_score=NULL")
        lthr, _, rhr = queries.get_current_activity_metric_provenance(conn)
        for row in conn.execute("SELECT activity_id FROM activity").fetchall():
            conn.execute("INSERT INTO activity_metrics(activity_id,tss,refresh_provenance_version,threshold_lthr_bpm,threshold_resting_hr_bpm) VALUES(?,60,?,?,?)",
                (row[0],queries.ACTIVITY_METRICS_PROVENANCE_VERSION,lthr,rhr))
    before = db_snapshot(path)
    current = recovery_assessment(path,assessment_date=AS_OF,today=AS_OF)["assessment"]
    assert current["factors"]["load"]["value"]["mode"] == "TSS"
    assert db_snapshot(path) == before
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE activity_metrics SET threshold_resting_hr_bpm=99")
    current = recovery_assessment(path,assessment_date=AS_OF,today=AS_OF)["assessment"]
    assert current["factors"]["load"]["value"]["mode"] == "Recorded hours"
    assert current["scores"]["readiness"]["confidence"] == "Limited"
    assert "Coverage is limited" in current["guidance"]


def test_undated_activity_does_not_become_zero_load(tmp_path):
    path = health_database(tmp_path)
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO activity(activity_id,start_time_local,duration_seconds,training_stress_score) VALUES(9999,'unknown',3600,100)")
    current = recovery_assessment(path,assessment_date=AS_OF,today=AS_OF)["assessment"]
    assert current["factors"]["load"]["score"] is None
    assert "1 undated activities" in current["factors"]["load"]["detail"]
    assert current["scores"]["readiness"]["confidence"] == "Limited"


def test_inputs_and_preference_share_one_coherent_read_transaction(tmp_path,monkeypatch):
    from garmin_data_hub.services import recovery_readiness as service
    path = health_database(tmp_path)
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
    expected = recovery_assessment(path,assessment_date=AS_OF,today=AS_OF)
    real_read = service.read_recovery_inputs
    def changed_elsewhere(conn,*args):
        with sqlite3.connect(path) as writer:
            writer.execute("UPDATE sleep SET sleep_time_seconds=14400 WHERE calendar_date=?",(AS_OF.isoformat(),))
            writer.execute("INSERT INTO app_settings(key,value) VALUES(?,'9')",(SETTING_KEY,))
        return real_read(conn,*args)
    monkeypatch.setattr(service,"read_recovery_inputs",changed_elsewhere)
    concurrent = recovery_assessment(path,assessment_date=AS_OF,today=AS_OF)
    assert concurrent == expected
    monkeypatch.setattr(service,"read_recovery_inputs",real_read)
    after = recovery_assessment(path,assessment_date=AS_OF,today=AS_OF)
    assert after["sleep_target_hours"] == 9
    assert after["assessment"]["factors"]["sleep"]["value"] == 4
    assert after["input_sha256"] != expected["input_sha256"]


@pytest.mark.parametrize("value", [0,-1,501,True,float('inf'),float('nan')])
def test_invalid_nightly_hrv_can_use_valid_alternate_but_not_weekly_average(value):
    data = inputs()
    day = AS_OF.isoformat()
    data["tables"]["hrv"][day].update(last_night_avg=value,last_night=50,weekly_avg=50)
    assert result(data)["assessment"]["factors"]["hrv"]["value"] == 50
    data["tables"]["hrv"][day]["last_night"] = None
    assert result(data)["assessment"]["factors"]["hrv"]["score"] is None


def test_too_early_dates_are_explicit_errors_not_overflow_or_database_creation(tmp_path):
    with pytest.raises(ValueError,match="too early"):
        result(day=date.min)
    missing = tmp_path / "not-created.db"
    with pytest.raises(ValueError,match="too early"):
        recovery_assessment(missing,assessment_date=date.min,today=AS_OF)
    assert not missing.exists()
    with pytest.raises(FileNotFoundError):
        save_sleep_target(missing, 8)
    assert not missing.exists()


def test_historical_scores_never_give_current_training_clearance():
    prior = result(day=AS_OF-timedelta(days=1))
    assert prior["assessment_age_days"] == 1
    assert prior["assessment"]["scores"]["recovery"]["score"] == 92
    assert "Historical assessment" in prior["assessment"]["guidance"]
    assert "current data" in prior["assessment"]["guidance"]
