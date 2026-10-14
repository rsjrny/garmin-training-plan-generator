from dataclasses import replace
from datetime import date, timedelta
import sqlite3
import json
import time

import pytest

from garmin_data_hub.analytics.yearly_plan import prepare_yearly_timeline, timeline_years
from garmin_data_hub.services.yearly_plan_data import yearly_plan_snapshot, yearly_plan_signature
from garmin_data_hub.plan_methodology.revision_repository import CorruptRevisionError
from garmin_data_hub.services import season_plans as intent, season_generation as generation
from test_season_generation import setup_season, SETTINGS, TODAY
from test_season_plans import snapshot as database_snapshot
from revision_fixtures import _database, _approve, _fitzgerald_candidate


def row(day, phase="BUILD", **changes):
    result = dict(id=day, date=day, phase=phase, event=None, preserved=False,
                  duration_s=3600, distance_m=None, duration_estimated=False,
                  distance_estimated=False, rest=False)
    result.update(changes)
    return result


def facts(workouts=(), **changes):
    selection = dict(id="season:s", name="Season", start="2027-01-01", end="2027-12-31",
        timezone="America/New_York", season_id="s", archived=False, plan_id="p", revision_id="r",
        workouts=list(workouts), intent_events=[], applied_events=[])
    selection.update(changes)
    return dict(selections=[selection], unmanaged=0)


def active(tmp_path, monkeypatch, events=None, **changes):
    monkeypatch.setattr(generation, "_local_today", lambda _: TODAY)
    db, season = setup_season(tmp_path, events if events is not None else [intent.EventDraft("Spring half", "2027-05-16")], **changes)
    preview = generation.preview_season(db, season.season_id, SETTINGS)
    assert preview.can_apply, preview.schedule.errors
    generation.apply_season_preview(db, preview, approved_by="test", acknowledge_warnings=True)
    return db, intent.get_season(db, season.season_id)


def test_leap_year_cross_year_clipping_and_full_block_details():
    data = facts([row((date(2027, 12, 25) + timedelta(days=i)).isoformat()) for i in range(75)])
    graph = prepare_yearly_timeline(data, 2028, today=date(2028, 2, 29))
    block = graph["blocks"][0]
    assert graph["days"] == 366 and len(graph["months"]) == 12
    assert sum(m["width"] for m in graph["months"]) == pytest.approx(1)
    assert block["start"] == "2027-12-25" and block["visible_start"] == "2028-01-01"
    assert block["end"] == "2028-03-08" and block["duration_s"] == 75 * 3600
    assert graph["today_offset"] == pytest.approx(59.5 / 366)
    assert sum(b["width"] for b in graph["blocks"]) == pytest.approx(1)
    assert graph["blocks"][-1]["label"] == "Unplanned"
    assert graph["blocks"][0]["weekly"][0]["partial"]
    assert timeline_years(data, date(2026, 10, 5)) == [2026, 2027, 2028]


@pytest.mark.parametrize("phase", ["BASE", "BUILD", "EVENT_SPECIFIC", "PEAK", "TAPER", "EVENT", "RECOVERY", "MAINTENANCE", "TRANSITION", "CUSTOM_PHASE", None])
def test_all_stored_phases_are_preserved_including_unknown_and_single_days(phase):
    graph = prepare_yearly_timeline(facts([row("2027-02-01", phase)]), 2027)
    block = graph["blocks"][1]
    assert block["phase"] == (phase or "PHASE_UNAVAILABLE")
    assert block["width"] == pytest.approx(1 / 365)


def test_mixed_phases_and_unplanned_gap_not_inferred():
    graph = prepare_yearly_timeline(facts([row("2027-01-01"), row("2027-01-01", "RECOVERY"), row("2027-01-03", None)]), 2027)
    assert [b["phase"] for b in graph["blocks"]] == ["MIXED_PHASES", "UNPLANNED", "PHASE_UNAVAILABLE", "UNPLANNED"]
    assert graph["blocks"][1]["duration_s"] is None


def test_unknown_measures_estimates_and_rest_are_honest():
    graph = prepare_yearly_timeline(facts([row("2027-01-01", distance_m=1609.344, distance_estimated=True),
        row("2027-01-02", duration_s=0, distance_m=0, rest=True),
        row("2027-01-03", duration_s=None, distance_m=1609.344)]), 2027)
    b = graph["blocks"][0]
    assert b["duration_s"] is None and b["distance_m"] == pytest.approx(3218.688)
    assert b["distance_estimated"] and b["sessions"] == 2


def test_events_applied_and_changed_intent_have_separate_identities():
    event = dict(id="e", name="Race", date="2027-05-16", priority="A", status="planned", distance_m=21097)
    graph = prepare_yearly_timeline(facts([row("2027-05-16", "EVENT", event=event)],
        applied_events=[dict(event, source="Applied schedule")],
        intent_events=[dict(event, date="2027-06-01")]), 2027)
    assert [e["source"] for e in graph["events"]] == ["Applied schedule", "Event intent · not applied"]
    assert len({e["key"] for e in graph["events"]}) == 2
    assert graph["blocks"][1]["events"][0]["date"] == "2027-05-16"
    same = prepare_yearly_timeline(facts([], applied_events=[dict(event, source="Applied schedule")], intent_events=[event]), 2027)
    assert len(same["events"]) == 1


def test_no_plan_intent_archived_and_selection_are_explicit():
    assert prepare_yearly_timeline(dict(selections=[], unmanaged=2), 2027)["selection"] is None
    data = facts([], revision_id=None, archived=True)
    data["selections"].append(dict(data["selections"][0], id="season:other", archived=False))
    assert prepare_yearly_timeline(data, 2027)["selection"]["id"] == "season:other"
    graph = prepare_yearly_timeline(data, 2027, "season:s")
    assert graph["selection"]["archived"] and graph["blocks"][0]["phase"] == "UNPLANNED"


def test_read_only_verified_full_year_and_priority_windows(tmp_path, monkeypatch):
    db, s = active(tmp_path, monkeypatch, [intent.EventDraft("Spring A", "2027-05-16"),
        intent.EventDraft("Fall B", "2027-10-17", "HM", "B"), intent.EventDraft("Practice C", "2027-09-05", "5K", "C")])
    before = database_snapshot(db)
    start = time.monotonic()
    data = yearly_plan_snapshot(db)
    graph = prepare_yearly_timeline(data, 2027)
    assert time.monotonic() - start < 5
    assert database_snapshot(db) == before
    assert data["signature"] == yearly_plan_signature(db)
    assert len(data["selections"][0]["workouts"]) == 365
    assert {e["priority"] for e in graph["events"]} == {"A", "B", "C"}
    assert all(e["source"] == ("Applied calendar marker" if e["priority"] == "C" else "Applied schedule") for e in graph["events"])
    assert any(b["phase"] == "TAPER" and b["start"] == "2027-05-06" for b in graph["blocks"])
    assert any(b["phase"] == "RECOVERY" and b["start"] == "2027-05-17" for b in graph["blocks"])
    old = data["signature"]
    event = intent.list_events(db, s.season_id)[0]
    intent.save_event(db, s.season_id, replace(event.draft, event_date="2027-06-06"), event_id=event.event_id, expected_version=s.input_version)
    assert yearly_plan_signature(db) != old
    changed = prepare_yearly_timeline(yearly_plan_snapshot(db), 2027)
    assert len(changed["events"]) == 4


def test_regeneration_keeps_original_phases_and_associations(tmp_path, monkeypatch):
    db, s = active(tmp_path, monkeypatch)
    before = yearly_plan_snapshot(db)["selections"][0]["workouts"]
    e = intent.list_events(db, s.season_id)[0]
    intent.save_event(db, s.season_id, replace(e.draft, event_date="2027-06-06"), event_id=e.event_id, expected_version=s.input_version)
    preview = generation.preview_season(db, s.season_id, SETTINGS)
    generation.apply_season_preview(db, preview, approved_by="test", acknowledge_warnings=True)
    after = yearly_plan_snapshot(db)["selections"][0]["workouts"]
    originals = {w["id"]: w for w in before}
    carried = [w for w in after if w["preserved"] and w["event"]]
    assert carried
    assert all(w["phase"] == originals[w["id"]]["phase"] and w["event"] == originals[w["id"]]["event"] for w in carried)
    assert any(e["date"] == "2027-06-06" for e in prepare_yearly_timeline(yearly_plan_snapshot(db), 2027)["events"])


@pytest.mark.parametrize("mutation", ["delete", "date", "duplicate"])
def test_corrupt_projection_is_rejected(tmp_path, monkeypatch, mutation):
    db, _ = active(tmp_path, monkeypatch)
    with sqlite3.connect(db) as conn:
        if mutation == "delete":
            conn.execute("DELETE FROM planned_workout WHERE planned_workout_id=(SELECT MIN(planned_workout_id) FROM planned_workout)")
        elif mutation == "date":
            conn.execute("UPDATE planned_workout SET scheduled_date='2026-01-01' WHERE planned_workout_id=(SELECT MIN(planned_workout_id) FROM planned_workout)")
        else:
            index = conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND sql LIKE '%source_plan_id%' AND sql LIKE '%UNIQUE%'").fetchone()[0]
            conn.execute('DROP INDEX "' + index + '"')
            conn.execute("INSERT INTO planned_workout(scheduled_date,workout_name,source_plan_id,source_revision_id,source_workout_id) SELECT scheduled_date,workout_name,source_plan_id,source_revision_id,source_workout_id FROM planned_workout LIMIT 1")
    with pytest.raises(CorruptRevisionError):
        yearly_plan_snapshot(db)


def test_standalone_plan_and_unmanaged_rows_remain_distinct(tmp_path):
    db = _database(tmp_path)
    candidate = _fitzgerald_candidate()
    _approve(db, replace(candidate, workouts=tuple(replace(w, phase=None) for w in candidate.workouts)))
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO planned_workout(scheduled_date,workout_name) VALUES('2030-01-01','Legacy')")
    data = yearly_plan_snapshot(db)
    assert data["unmanaged"] == 1
    assert data["selections"][0]["id"].startswith("plan:")
    assert all(w["phase"] is None for w in data["selections"][0]["workouts"])


def test_old_database_without_season_schema_is_read_without_migration(tmp_path):
    db = tmp_path / "old.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE planned_workout(scheduled_date TEXT)")
        conn.execute("INSERT INTO planned_workout VALUES('2026-01-01')")
    assert yearly_plan_snapshot(db)["unmanaged"] == 1
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0] == 1


def test_reader_cannot_write_or_read_activity_tracks(tmp_path, monkeypatch):
    db, _ = active(tmp_path, monkeypatch)
    original_connect = sqlite3.connect
    def protected_connect(*args, **kwargs):
        conn = original_connect(*args, **kwargs)
        def authorize(action, table, *unused):
            if action in {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE,
                          sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_ALTER_TABLE}:
                return sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_READ and table in {"activity", "activity_metrics", "activity_trackpoints"}:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        conn.set_authorizer(authorize)
        return conn
    monkeypatch.setattr(sqlite3, "connect", protected_connect)
    assert yearly_plan_snapshot(db)["selections"][0]["workouts"]
    assert yearly_plan_signature(db)


def test_hashed_phase_corruption_is_rejected(tmp_path, monkeypatch):
    db, _ = active(tmp_path, monkeypatch)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE plan_revision_workout SET phase='TAPER' WHERE scheduled_date='2027-01-01'")
    with pytest.raises(CorruptRevisionError):
        yearly_plan_snapshot(db)


def test_cancelled_intent_retains_applied_event_and_context():
    event = dict(id="e", name="Race", date="2027-05-16", priority="A", status="planned", distance_m=21097)
    graph = prepare_yearly_timeline(facts([row("2027-05-16", "EVENT", event=event)],
        applied_events=[dict(event, source="Applied schedule")],
        intent_events=[dict(event, status="cancelled")]), 2027)
    assert len(graph["events"]) == 1 and graph["events"][0]["intent_status"] == "cancelled"


def test_weekly_cutback_uses_stored_indicator():
    graph = prepare_yearly_timeline(facts([row("2027-01-01", cutback=True)]), 2027)
    assert graph["blocks"][0]["weekly"][0]["cutback"]


def test_saved_legacy_phases_and_missing_metadata_are_visible_without_conversion(tmp_path):
    db = _database(tmp_path)
    with sqlite3.connect(db) as conn:
        rows = [("2026-01-05", "Older", None),
                ("2026-07-06", "Easy run", json.dumps({"source":"rule_based_baseline", "workout":{"phase":"Base"}})),
                ("2026-07-07", "Long run", json.dumps({"workout":{"phase":"Build"}})),
                ("2026-10-10", "Race day", json.dumps({"workout":{"phase":"Race"}}))]
        conn.executemany("INSERT INTO planned_workout(scheduled_date,workout_name,structure_json,planned_duration_s,planned_distance_m) VALUES(?,?,?,1800,5000)", rows)
        # A stale cache must never add phases to missing-metadata workout rows.
        conn.execute("INSERT INTO app_settings(key,value) VALUES('last_generated_plan',?)",
                     (json.dumps({"day_plans":[{"iso_date":"2026-01-05","phase":"Taper"}]}),))
    before = database_snapshot(db)
    facts = yearly_plan_snapshot(db)
    graph = prepare_yearly_timeline(facts, 2026, today=date(2026,7,6))
    assert graph["selection"]["legacy"]
    assert {b["phase"] for b in graph["blocks"]} == {"UNPLANNED", "PHASE_UNAVAILABLE", "BASE", "BUILD", "RACE"}
    assert graph["events"][0]["source"] == "Saved legacy schedule" and graph["events"][0]["priority"] == "?"
    assert graph["events"][0]["distance_estimated"]
    assert next(b for b in graph["blocks"] if b["phase"] == "BASE")["duration_estimated"]
    assert database_snapshot(db) == before
    signature = yearly_plan_signature(db)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE planned_workout SET structure_json=? WHERE scheduled_date='2026-07-06'", (json.dumps({"workout":{"phase":"Peak"}}),))
    assert yearly_plan_signature(db) != signature


def test_saved_schedule_is_preferred_to_unlinked_intent_and_bad_metadata_is_unknown(tmp_path):
    db, season = setup_season(tmp_path, [], start_date="2026-01-01", end_date="2026-12-31")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO planned_workout(scheduled_date,workout_name,structure_json) VALUES('2026-10-05','Existing','invalid json')")
        conn.execute("INSERT INTO planned_workout(scheduled_date,workout_name,structure_json) VALUES('2026-10-06','Existing',?)",
                     (json.dumps({"workout":{"date":"2025-10-06", "phase":"Taper"}}),))
    data = yearly_plan_snapshot(db)
    graph = prepare_yearly_timeline(data, 2026, today=date(2026,10,5))
    assert graph["selection"]["id"] == "legacy:saved"
    assert graph["blocks"][1]["phase"] == "PHASE_UNAVAILABLE"
    assert graph["blocks"][1]["start"] == "2026-10-05" and graph["blocks"][1]["end"] == "2026-10-06"
    assert prepare_yearly_timeline(data, 2026, "season:" + season.season_id)["selection"]["workouts"] == []
