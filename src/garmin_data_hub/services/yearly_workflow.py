"""Read-only yearly workflow state and coalesced proposals; acceptance uses Y3 apply.

Proposals are disposable process-local work. Persisted intent and reviewed application
snapshots, never a cache entry, decide whether a schedule is current after a restart.
"""
from __future__ import annotations

import asyncio
from contextlib import closing
from dataclasses import asdict, dataclass, replace
import json
import hashlib
import sqlite3
from decimal import Decimal
from pathlib import Path

from garmin_data_hub.plan_methodology.canonical import canonical_value, content_sha256
from garmin_data_hub.plan_methodology.revision_repository import load_revision
from garmin_data_hub.services import season_generation as generation, season_plans as intent
from garmin_data_hub.services.season_regeneration import RegenerationRequest
from garmin_data_hub.services.season_schedule import GENERATOR_VERSION, POLICY_VERSION, GenerationSettings


def parameter_key(season):
    i = season.inputs
    return (i.training_method, i.lthr) if i.training_method == "eighty_twenty" else (i.training_method, i.age)


def _intent_value(season, events):
    # Pointer/version changes are not training inputs. Reverting intent can be current.
    value = asdict(season)
    for field in ("plan_id", "current_revision_id", "input_version", "status"):
        value.pop(field)
    return {"season": value, "events": [asdict(e) for e in events]}


@dataclass(frozen=True)
class ParameterConfirmation:
    parameters: tuple
    settings: GenerationSettings
    parent_revision_id: str | None


@dataclass(frozen=True)
class WorkflowState:
    season: intent.Season
    fingerprint: str
    status: str
    message: str
    settings: GenerationSettings | None
    refresh_parameters: bool = False
    preview: generation.SeasonPreview | None = None


def read_state(db_path, season_id, confirmation=None):
    """Coherent, read-only input/settings/policy comparison, including runtime state."""
    with closing(sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        season = intent._get(conn, season_id)
        events = generation._events(conn, season)
        # Manual edits accept one prescription, not pending yearly intent.
        revision_id = season.current_revision_id
        applied = None
        seen = set()
        while revision_id:
            if revision_id in seen:
                raise intent.SeasonError("Yearly revision lineage contains a cycle.")
            seen.add(revision_id)
            revision = load_revision(None, revision_id, _connection=conn)
            if revision is None:
                raise intent.SeasonError("Applied yearly revision is unavailable.")
            application = conn.execute("SELECT * FROM season_revision_application WHERE season_id=? AND resulting_revision_id=?",
                (season_id, revision_id)).fetchone()
            if application and application["mode"] != "MANUAL_EDIT":
                if application["candidate_sha256"] != revision.candidate.content_hash:
                    raise intent.SeasonError("Applied yearly snapshot does not match its revision.")
                applied = application
                break
            if not application:  # Explicit adoption is not yearly input acceptance.
                break
            revision_id = revision.candidate.parent_revision_id
        if applied and hashlib.sha256(applied["snapshot_json"].encode()).hexdigest() != applied["input_sha256"]:
            raise intent.SeasonError("Accepted yearly input snapshot could not be verified.")
        snapshot = json.loads(applied["snapshot_json"]) if applied else None
        settings = None
        refresh = False
        applied_settings = None
        if snapshot:
            parameters = canonical_value(revision.candidate.parameter_snapshot)
            # Regeneration can use default confirmation flags while reusing native
            # parameters. Those flags do not revoke the original confirmation.
            if season.inputs.training_method == "eighty_twenty":
                threshold = parameters.get("lthr", {})
                if (threshold.get("evidence_class") == "MEASURED" and
                        threshold.get("source_record") == "USER_CONFIRMED_RUNNING_LTHR"):
                    applied_settings = GenerationSettings(lthr_confirmed=True)
                    if season.inputs.lthr is not None and Decimal(threshold["value"]) == season.inputs.lthr:
                        settings = applied_settings
            elif parameters.get("confirmed") is True:
                applied_settings = GenerationSettings(maf_adjustment=parameters.get("selected_adjustment"), maf_confirmed=True)
                if parameters.get("completed_age") == season.inputs.age:
                    settings = applied_settings
        if (confirmation and confirmation.parameters == parameter_key(season) and
                confirmation.parent_revision_id == season.current_revision_id):
            refresh = bool(snapshot and (settings is None or
                (applied_settings and confirmation.settings.maf_adjustment != applied_settings.maf_adjustment)))
            settings = confirmation.settings
        missing = []
        if season.inputs.starting_duration_seconds is None:
            missing.append("Set starting weekly minutes; yearly setup does not import covered Garmin history.")
        if settings is None or (season.inputs.training_method == "eighty_twenty" and
                (season.inputs.lthr is None or not settings.lthr_confirmed)):
            missing.append("Select and confirm a MAF adjustment in preview settings." if season.inputs.training_method == "maffetone" else
                           "Confirm measured running LTHR in preview settings.")
        elif season.inputs.training_method == "maffetone" and (settings.maf_adjustment is None or not settings.maf_confirmed):
            missing.append("Select and confirm a MAF adjustment in preview settings.")
        current = False
        if snapshot:
            old_intent = dict(snapshot["season"])
            for field in ("plan_id", "current_revision_id", "input_version", "status"):
                old_intent.pop(field)
            current = (canonical_value({"season": old_intent, "events": snapshot["events"]}) ==
                canonical_value(_intent_value(season, events)) and
                applied["generator_version"] == GENERATOR_VERSION and applied["policy_version"] == POLICY_VERSION and
                settings is not None and not refresh)
        fingerprint = content_sha256({"season": asdict(season), "events": [asdict(e) for e in events],
            "settings": asdict(settings) if settings else None, "state": generation._state(conn),
            "today": generation._local_today(season.timezone).isoformat(),
            "generator": GENERATOR_VERSION, "policy": POLICY_VERSION, "refresh": refresh})
        if season.status == "archived":
            status, message = "archived", "Archived yearly plan; applied workouts remain available."
        elif current:
            status, message = "current", "Up to date · event and yearly settings match the accepted schedule."
        elif missing:
            status, message = "settings_required", "Settings required · " + " ".join(missing)
        else:
            status = "pending" if season.current_revision_id else "no_schedule"
            message = "Changes awaiting review · applied workouts stay unchanged." if season.current_revision_id else "No applied schedule · prepare and accept an initial proposal; a race is optional."
        return WorkflowState(season, fingerprint, status, message, settings, refresh)


@dataclass
class _Entry:
    fingerprint: str
    task: asyncio.Task | None = None
    preview: generation.SeasonPreview | None = None
    error: str | None = None


class ProposalCoordinator:
    """One latest task per database/season, shared by tabs; late results are discarded."""
    def __init__(self, debounce_seconds=0.3):
        self.debounce_seconds = debounce_seconds
        self.entries = {}
        self.confirmations = {}

    def _key(self, db_path, season_id):
        return (str(Path(db_path).resolve()), season_id)

    def retry(self, db_path, season_id):
        entry = self.entries.pop(self._key(db_path, season_id), None)
        if entry and entry.task and not entry.task.done():
            entry.task.cancel()

    def state(self, db_path, season_id):
        key = self._key(db_path, season_id)
        state = read_state(db_path, season_id, self.confirmations.get(key))
        entry = self.entries.get(key)
        if state.status in {"current", "settings_required", "archived"} or not entry or entry.fingerprint != state.fingerprint:
            return state
        if entry.task and not entry.task.done():
            return replace(state, status="preparing", message="Preparing update · the latest saved inputs are being evaluated.")
        if entry.error:
            return replace(state, status="conflict", message="Update blocked by conflicts · " + entry.error)
        if entry.preview:
            blocked = not entry.preview.can_apply
            return replace(state, status="conflict" if blocked else "pending",
                message="Update blocked by conflicts · review the proposal and tune settings/events." if blocked else
                    "Changes awaiting review · latest proposal ready. Accept it to change the schedule.", preview=entry.preview)
        return state

    async def ensure(self, db_path, season_id):
        key = self._key(db_path, season_id)
        state = await asyncio.to_thread(self.state, db_path, season_id)
        entry = self.entries.get(key)
        if state.status in {"current", "settings_required", "archived"}:
            if entry and entry.task and not entry.task.done():
                entry.task.cancel()
            self.entries.pop(key, None)
            return state
        if entry and entry.fingerprint == state.fingerprint:
            return state
        if entry and entry.task and not entry.task.done():
            entry.task.cancel()  # to_thread may finish; it cannot publish after cancellation.
        entry = _Entry(state.fingerprint)
        self.entries[key] = entry
        entry.task = asyncio.create_task(self._prepare(key, entry, db_path, state))
        return replace(state,status="preparing",message="Preparing update · the latest saved inputs are being evaluated.")

    async def for_review(self, db_path, season_id):
        """Wait for the latest settled proposal, following superseded work safely."""
        while True:
            state = await self.ensure(db_path,season_id)
            if state.status != "preparing":
                return state
            entry = self.entries.get(self._key(db_path,season_id))
            if not entry or not entry.task:
                return state
            try:
                await asyncio.shield(entry.task)
            except asyncio.CancelledError:
                # A newer edit can cancel the worker without cancelling the
                # user's review request. Actual caller cancellation still exits.
                if asyncio.current_task().cancelling():
                    raise

    async def _prepare(self, key, entry, db_path, state):
        try:
            await asyncio.sleep(self.debounce_seconds)
            if (await asyncio.to_thread(self.state, db_path, state.season.season_id)).fingerprint != entry.fingerprint:
                return
            request = RegenerationRequest(refresh_parameters=state.refresh_parameters) if state.season.current_revision_id else None
            preview = await asyncio.to_thread(generation.preview_season, db_path, state.season.season_id, state.settings, request)
            latest = await asyncio.to_thread(read_state, db_path, state.season.season_id, self.confirmations.get(key))
            if self.entries.get(key) is entry and latest.fingerprint == entry.fingerprint:
                entry.preview = preview
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self.entries.get(key) is entry:
                entry.error = str(exc) if isinstance(exc, intent.SeasonError) else "Proposal unavailable. Refresh and try again."

    def reviewed(self, db_path, preview):
        """Remember explicitly confirmed manual settings, without applying the proposal."""
        key = self._key(db_path, preview.season.season_id)
        # Check the frozen intent/runtime data before exposing a manual preview as latest.
        with closing(sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN")
            season = intent._get(conn, preview.season.season_id)
            valid = generation._snapshot(season, generation._events(conn, season), preview.settings) == preview.snapshot_json
            valid = valid and generation._state(conn) == (preview.active_sha256, preview.runtime_sha256, preview.raw_schedule_sha256)
            valid = valid and generation._local_today(season.timezone).isoformat() == preview.local_today
            valid = valid and (preview.generator_version, preview.policy_version) == (GENERATOR_VERSION, POLICY_VERSION)
        if not valid:
            raise generation.StalePreviewError("Yearly inputs or schedule changed during preparation. Prepare a fresh proposal.")
        if valid:
            if not preview.regeneration or preview.regeneration.refresh_parameters:
                self.confirmations[key] = ParameterConfirmation(parameter_key(preview.season),
                    preview.settings,preview.season.current_revision_id)
            state = read_state(db_path, preview.season.season_id, self.confirmations.get(key))
            prior = self.entries.pop(key, None)
            if prior and prior.task and not prior.task.done():
                prior.task.cancel()
            self.entries[key] = _Entry(state.fingerprint, preview=preview)


proposals = ProposalCoordinator()
