"""Season calendar and planning-intent editor."""
from __future__ import annotations

from datetime import datetime, timedelta
from dataclasses import replace
from uuid import uuid4
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from garmin_data_hub.services.yearly_workflow import proposals
from garmin_data_hub.ui_nicegui.yearly_workflow import render_workflow, yearly_url
from zoneinfo import ZoneInfo

from garmin_data_hub.services import season_plans as plans
from garmin_data_hub.services import season_generation as generation
from garmin_data_hub.services.season_schedule import GenerationSettings, event_windows, event_resolution_notes
from garmin_data_hub.services.season_regeneration import RegenerationRequest
from garmin_data_hub.services import season_workouts
from garmin_data_hub.services.baseline_plan_builder import BASELINE_DISTANCE_OPTIONS
from garmin_data_hub.ui_nicegui.layout import page_heading, render_shell


def _integer(value, label: str, *, optional: bool = False) -> int | None:
    if optional and value in (None, ""):
        return None
    try:
        integer = int(value)
        if isinstance(value, bool) or Decimal(str(value)) != integer:
            raise ValueError()
        return integer
    except (ValueError, TypeError, ArithmeticError) as exc:
        raise plans.SeasonError(f"{label} must be a whole number.") from exc


def _seconds(value: str, *, pace: bool = False) -> int | None:
    if not value.strip():
        return None
    parts = value.strip().split(":")
    expected = 2 if pace else 3
    if len(parts) != expected or any(not p.isdigit() for p in parts):
        raise plans.SeasonError("Use MM:SS for pace or HH:MM:SS for finish time.")
    numbers = [int(p) for p in parts]
    if any(n >= 60 for n in numbers[1:]):
        raise plans.SeasonError("Minutes and seconds after ':' must be below 60.")
    result = sum(n * 60**i for i, n in enumerate(reversed(numbers)))
    if result <= 0:
        raise plans.SeasonError("Target time or pace must be positive.")
    return result


def register_seasons_page(db_path: Path, *, sandboxed: bool) -> None:
    from nicegui import ui, run

    @ui.page("/seasons")
    def seasons_page(season_id: str = "") -> None:
        if not season_id:
            try:
                existing = plans.list_seasons(db_path)
                if existing:
                    ui.navigate.to(yearly_url("/seasons",existing[0].season_id))
                    return
            except (plans.SeasonError,sqlite3.Error,OSError):
                pass  # The regular error presentation below remains available.
        render_shell("Seasons", db_path, sandboxed=sandboxed)
        ui.add_css(".season-form { grid-template-columns: repeat(2,minmax(0,1fr)); }"
                   "@media(max-width:600px) { .season-form { grid-template-columns:minmax(0,1fr); } }")
        selected = {"id": season_id}
        # Editors outlive refreshed intent cards, so another tab cannot close a
        # user's open editor or discard its optimistic version.
        dialogs = ui.element("div")

        def show_error(error: Exception, label=None) -> None:
            message = str(error) if isinstance(error, (plans.SeasonError, ValueError)) else "Database unavailable. Refresh and try again."
            if label is not None:
                label.text = message
            ui.notify(message, type="negative")

        async def prepare_update(season_id):
            try:
                await proposals.ensure(db_path,season_id)
            except Exception:
                ui.notify("Intent saved. Proposal unavailable; refresh or review yearly settings.",type="warning")

        def season_editor(season: plans.Season | None = None) -> None:
            today = datetime.now(ZoneInfo("America/New_York")).date()
            original = plans.SeasonDraft(season.name, season.start_date, season.end_date, season.timezone, season.inputs) if season else plans.SeasonDraft(
                "", today.isoformat(), (today + timedelta(days=365)).isoformat(), "America/New_York")
            with dialogs, ui.dialog() as dialog, ui.card().classes("w-full max-w-2xl max-h-[90vh] overflow-y-auto"):
                ui.label("Edit season" if season else "New season").classes("text-xl font-semibold")
                with ui.grid().classes("season-form w-full gap-3"):
                    name = ui.input("Season name", value=original.name).classes("w-full")
                    tz = ui.input("Timezone", value=original.timezone).classes("w-full").props('hint="IANA name, e.g. America/New_York"')
                    start = ui.input("Season start", value=original.start_date).props("type=date").classes("w-full")
                    end = ui.input("Season end", value=original.end_date).props("type=date").classes("w-full")
                    age = ui.number("Age", value=original.inputs.age, min=10, max=100, step=1).classes("w-full")
                    method = ui.select({"eighty_twenty": "80/20 running", "maffetone": "Maffetone running"}, value=original.inputs.training_method, label="Training method").classes("w-full")
                    days = ui.number("Run days per week", value=original.inputs.run_days_per_week, min=1, max=7, step=1).classes("w-full")
                    long_day = ui.select(list(plans.WEEKDAYS), value=original.inputs.long_run_day, label="Long-run day").classes("w-full")
                    available = ui.select(dict(enumerate(plans.WEEKDAYS)), multiple=True, value=list(original.inputs.available_weekdays), label="Available days").props("use-chips").classes("w-full")
                    duration = ui.number("Starting weekly minutes (required for preview)", value=None if original.inputs.starting_duration_seconds is None else original.inputs.starting_duration_seconds / 60, min=1, max=2400).classes("w-full")
                    hrmax = ui.number("HRmax (optional)", value=original.inputs.hrmax, min=80, max=250, step=1).classes("w-full")
                    lthr = ui.number("LTHR (optional)", value=original.inputs.lthr, min=80, max=220, step=1).classes("w-full")
                ui.label().bind_text_from(duration,"value",lambda value:
                    (f"Starting weekly load entered: {value:g} running minutes." if value is not None else
                     "Starting weekly running minutes are not set; enter them before previewing.") +
                    " Covered Garmin history is not imported here. Save season to retain changes.").classes("text-sm break-words")
                ui.select({"none": "None / general fitness"}, value="none", label="Always ready for (coming with baseline cycles)").classes("w-full").disable()
                ui.label("Distance goals such as a 10 miler or half marathon will arrive with baseline training cycles. No distance goal is saved or inferred yet.").classes("text-sm break-words")
                ui.label().bind_text_from(method,"value",lambda value:
                    "Maffetone preview also needs a selected and confirmed MAF adjustment in preview settings. HRmax and LTHR are optional for this method."
                    if value == "maffetone" else
                    "80/20 preview also needs a measured running LTHR and confirmation in preview settings.").classes("text-sm break-words")
                if season and season.plan_id:
                    tz.disable()
                    method.disable()
                error = ui.label("").classes("text-red-800 whitespace-normal break-words")

                async def save() -> None:
                    try:
                        seconds = None if duration.value in (None, "") else _integer(Decimal(str(duration.value)) * 60, "Weekly duration")
                        inputs = plans.SeasonInputs(_integer(age.value, "Age"), method.value,
                                                    _integer(days.value, "Run days"), long_day.value,
                                                    tuple(available.value or ()), seconds,
                                                    _integer(hrmax.value, "HRmax", optional=True),
                                                    _integer(lthr.value, "LTHR", optional=True))
                        draft = plans.SeasonDraft(name.value, start.value, end.value, tz.value, inputs)
                        result = plans.update_season(db_path, season.season_id, draft, expected_version=season.input_version) if season else plans.create_season(db_path, draft)
                    except (plans.SeasonError, sqlite3.Error, OSError, ValueError) as exc:
                        show_error(exc, error)
                        return
                    selected["id"] = result.season_id
                    await prepare_update(result.season_id)
                    dialog.close()
                    if season:
                        content.refresh()
                    else:
                        ui.navigate.to(f"/seasons?season_id={result.season_id}")
                    ui.notify("Season saved.", type="positive")

                with ui.row().classes("w-full justify-end"):
                    ui.button("Close season editor", on_click=dialog.close).props("flat")
                    ui.button("Save season", on_click=save)
            dialog.open()

        def event_editor(season: plans.Season, event: plans.SeasonEvent | None = None) -> None:
            today = datetime.now(ZoneInfo(season.timezone)).date().isoformat()
            draft = event.draft if event else plans.EventDraft("", min(max(today, season.start_date), season.end_date))
            pace_seconds = None if draft.target_speed_mps is None else round(Decimal(1000) / Decimal(draft.target_speed_mps))
            original_pace = "" if pace_seconds is None else f"{pace_seconds // 60:02}:{pace_seconds % 60:02}"
            target = draft.target_seconds
            original_time = "" if target is None else f"{target // 3600:02}:{target // 60 % 60:02}:{target % 60:02}"
            with dialogs, ui.dialog() as dialog, ui.card().classes("w-full max-w-2xl max-h-[90vh] overflow-y-auto"):
                ui.label("Edit event" if event else "Add event").classes("text-xl font-semibold")
                with ui.grid().classes("season-form w-full gap-3"):
                    name = ui.input("Event name", value=draft.name).classes("w-full")
                    day = ui.input("Event date", value=draft.event_date).props("type=date").classes("w-full")
                    distance = ui.select(BASELINE_DISTANCE_OPTIONS, value=draft.distance_code, label="Event distance").classes("w-full")
                    kind = ui.select({"road": "Road", "trail": "Trail"}, value=draft.event_type, label="Event type").classes("w-full")
                    priority = ui.select({"A": "A · Primary goal", "B": "B · Supporting event", "C": "C · Training event"}, value=draft.priority, label="Event priority").classes("w-full")
                    status = ui.select({v: v.title() for v in ("planned", "completed", "skipped", "cancelled")}, value=draft.status, label="Event status").classes("w-full")
                    goal = ui.select({"COMPLETION": "Completion", "PERFORMANCE": "Performance"}, value=draft.goal_intent, label="Event goal").classes("w-full")
                    finish = ui.input("Target finish time (HH:MM:SS)", value=original_time).classes("w-full")
                    pace = ui.input("Target pace (MM:SS per km)", value=original_pace).classes("w-full")
                    participation = ui.number("Planned completion minutes (optional)", value=None if draft.participation_seconds is None else draft.participation_seconds / 60, min=1/60, max=10080).classes("w-full")
                    terrain = ui.input("Terrain", value=draft.terrain).classes("w-full")
                    taper = ui.number("Taper days (optional)", value=draft.taper_days, min=0, max=28, step=1).classes("w-full")
                    recovery = ui.number("Recovery days (optional)", value=draft.recovery_days, min=plans.RECOVERY_DAYS[draft.distance_code], max=42, step=1).classes("w-full")
                notes = ui.textarea("Course notes", value=draft.course_notes).classes("w-full")
                ui.label("Use one target: finish time or pace. Recovery cannot be shorter than the distance default.").classes("text-sm text-slate-600")
                ui.label("Planned completion minutes are an estimate for easy participation, not a finish-time goal. Unknown duration stays unknown.").classes("text-sm text-slate-600 break-words")
                @ui.refreshable
                def effective_window():
                    try:
                        window_draft = plans.EventDraft(name.value.strip() or "Event", day.value, distance.value, priority.value,
                            taper_days=_integer(taper.value, "Taper days", optional=True),
                            recovery_days=_integer(recovery.value, "Recovery days", optional=True))
                        event_value = plans.SeasonEvent(event.event_id if event else "draft", season.season_id, window_draft, plans.DISTANCES[distance.value])
                        w = event_windows(season, (event_value,))[0]
                        ui.label(f"Effective window: preparation {w.preparation_start} → {w.taper_start}; taper {w.taper_days} days; recovery through {w.recovery_end} ({w.recovery_days} days).").classes("text-sm break-words")
                        if priority.value == "C":
                            ui.label("C events replace training; separate preparation and taper are disabled, including taper overrides.").classes("text-sm break-words")
                        elif priority.value == "B":
                            ui.label("Supporting taper yields on dates controlled by an A build. Full distance recovery remains reserved.").classes("text-sm break-words")
                    except (plans.SeasonError, KeyError, TypeError, ValueError) as exc:
                        ui.label(str(exc)).classes("text-sm text-amber-900 break-words")
                effective_window()
                def update_window():
                    recovery.props(f"min={plans.RECOVERY_DAYS[distance.value]}")
                    effective_window.refresh()
                for control in (day, distance, priority, taper, recovery):
                    control.on_value_change(lambda _: update_window())
                error = ui.label("").classes("text-red-800 whitespace-normal break-words")

                async def save() -> None:
                    try:
                        speed = draft.target_speed_mps if pace.value == original_pace else None
                        if pace.value and pace.value != original_pace:
                            speed = format(Decimal(1000) / _seconds(pace.value, pace=True), "f")
                        updated = plans.EventDraft(name.value, day.value, distance.value, priority.value,
                                                   kind.value, status.value, goal.value, _seconds(finish.value),
                                                   speed, terrain.value, notes.value,
                                                   _integer(taper.value, "Taper days", optional=True),
                                                   _integer(recovery.value, "Recovery days", optional=True),
                                                   None if participation.value in (None, "") else _integer(Decimal(str(participation.value)) * 60, "Planned participation seconds"))
                        plans.save_event(db_path, season.season_id, updated, expected_version=season.input_version,
                                         event_id=None if event is None else event.event_id)
                    except (plans.SeasonError, sqlite3.Error, OSError, ValueError) as exc:
                        show_error(exc, error)
                        return
                    await prepare_update(season.season_id)
                    dialog.close()
                    content.refresh()
                    ui.notify("Event saved.", type="positive")

                with ui.row().classes("w-full justify-end"):
                    ui.button("Close event editor", on_click=dialog.close).props("flat")
                    ui.button("Save event", on_click=save)
            dialog.open()

        def remove_event(season: plans.Season, event: plans.SeasonEvent) -> None:
            with dialogs, ui.dialog() as dialog, ui.card().classes("w-full max-w-lg"):
                ui.label(f"Remove {event.draft.name}?").classes("text-xl font-semibold break-words")
                ui.label("This event will be cancelled; its history and applied schedule are retained until you accept an updated proposal." if season.plan_id else "This draft event will be deleted.").classes("break-words")
                ui.label("The proposal recalculates future preparation, taper, event and recovery influence and reconnects neighboring phases. Completed and protected workouts remain.").classes("text-sm break-words")
                error = ui.label("").classes("text-red-800 break-words")

                async def remove() -> None:
                    try:
                        plans.remove_event(db_path, season.season_id, event.event_id, expected_version=season.input_version)
                    except (plans.SeasonError, sqlite3.Error, OSError) as exc:
                        show_error(exc, error)
                        return
                    await prepare_update(season.season_id)
                    dialog.close()
                    content.refresh()
                with ui.row():
                    ui.button("Keep event", on_click=dialog.close).props("flat")
                    ui.button("Confirm removal", on_click=remove, color="negative")
            dialog.open()

        def archive(season: plans.Season) -> None:
            try:
                plans.set_archived(db_path, season.season_id, expected_version=season.input_version, archived=season.status != "archived")
            except (plans.SeasonError, sqlite3.Error, OSError) as exc:
                show_error(exc)
                return
            content.refresh()

        def generation_editor(season: plans.Season) -> None:
            with dialogs, ui.dialog() as dialog, ui.card().classes("w-full max-w-xl max-h-[90vh] overflow-y-auto"):
                ui.label("Generate season preview").classes("text-xl font-semibold")
                ui.label("Review one continuous schedule using every saved event. Generation does not change your calendar.").classes("break-words")
                if season.current_revision_id:
                    ui.label("Preserved sessions keep their original intensity parameters. Review the replacement range and exact changes before applying.").classes("break-words")
                    refresh_parameters = ui.checkbox("Use current athlete intensity settings for new prescriptions")
                    if season.inputs.training_method=="eighty_twenty":
                        confirmation = ui.checkbox("I confirm this LTHR is a measured running threshold.").props('aria-label="I confirm this LTHR is a measured running threshold."')
                        adjustment = None
                    else:
                        adjustment = ui.select({-10:"-10 bpm",-5:"-5 bpm",0:"0 bpm",5:"+5 bpm"},label="MAF adjustment").classes("w-full")
                        confirmation = ui.checkbox("I confirm the selected MAF adjustment.")
                elif season.inputs.training_method == "eighty_twenty":
                    ui.label(f"Saved running LTHR: {season.inputs.lthr or 'not set'} bpm. Set it in Edit season if needed.")
                    confirmation = ui.checkbox("I confirm this LTHR is a measured running threshold.").props('aria-label="I confirm this LTHR is a measured running threshold."')
                    adjustment = None
                else:
                    adjustment = ui.select({-10:"-10 bpm",-5:"-5 bpm",0:"0 bpm",5:"+5 bpm"}, label="MAF adjustment").classes("w-full")
                    confirmation = ui.checkbox("I confirm the selected MAF adjustment.").props('aria-label="I confirm the selected MAF adjustment."')
                mode = None
                range_start = range_end = overrides = None
                if season.current_revision_id:
                    mode = ui.select({"AFFECTED":"Calculated affected range","FROM_TODAY":"Full schedule from today","CUSTOM":"Custom replacement range"},value="AFFECTED",label="Regeneration mode").classes("w-full")
                    with ui.grid().classes("season-form w-full gap-3"):
                        range_start = ui.input("Replacement start",value=max(season.start_date,datetime.now(ZoneInfo(season.timezone)).date().isoformat())).props("type=date").classes("w-full")
                        range_end = ui.input("Replacement end",value=season.end_date).props("type=date").classes("w-full")
                    eligible = [w for w in season_workouts.list_workouts(db_path,season.season_id) if any(r in w["reasons"] for r in ("locked","manually_edited","manually_created")) and not any(r in w["reasons"] for r in ("history","completed","unresolved_match"))]
                    overrides = ui.select({w["workout_id"]:f'{w["date"]} · {w["title"]} · {", ".join(w["reasons"])}' for w in eligible},multiple=True,value=[],label="Explicitly replace protected future sessions").props("use-chips").classes("w-full")
                    ui.label("Completion, history and unresolved activity matches cannot be overridden. Custom dates apply only in custom mode.").classes("text-sm break-words")
                ui.label("Starting duration: " + (f"{season.inputs.starting_duration_seconds / 60:g} minutes/week" if season.inputs.starting_duration_seconds else "not set; add an explicit value in Edit season.")).classes("break-words")
                error = ui.label("").classes("text-red-800 break-words")

                async def generate() -> None:
                    try:
                        settings = GenerationSettings(lthr_confirmed=confirmation.value if confirmation is not None and adjustment is None else False,
                            maf_adjustment=adjustment.value if adjustment is not None else None,
                            maf_confirmed=confirmation.value if confirmation is not None and adjustment is not None else False)
                        request = RegenerationRequest(mode.value,range_start.value if mode.value=="CUSTOM" else None,
                            range_end.value if mode.value=="CUSTOM" else None,tuple(overrides.value or ()),refresh_parameters.value) if mode else None
                        if season.inputs.starting_duration_seconds is None:
                            raise plans.SeasonError("Set starting weekly minutes in Edit season before previewing; Garmin history is not imported here.")
                        generate_button.disable()
                        preview = await run.io_bound(generation.preview_season,db_path,season.season_id,settings,request)
                        if preview.season != season:
                            raise plans.StaleSeasonError("Yearly settings or events changed while preparing. Reopen preview settings for the latest version.")
                        proposals.reviewed(db_path,preview)
                    except (plans.SeasonError,sqlite3.Error,OSError,ValueError) as exc:
                        show_error(exc,error)
                        return
                    finally:
                        generate_button.enable()
                    dialog.close()
                    review_preview(preview)
                with ui.row().classes("w-full justify-end"):
                    ui.button("Close generation settings",on_click=dialog.close).props("flat")
                    generate_button = ui.button("Generate preview",on_click=generate)
            dialog.open()

        def review_preview(preview):
            from garmin_data_hub.ui_nicegui.season_review import review_preview as review
            review(db_path, preview, container=dialogs, on_applied=content.refresh, tune_event=event_editor)

        def workout_controls(season: plans.Season) -> None:
            with dialogs, ui.dialog() as dialog, ui.card().classes("w-full max-w-3xl max-h-[90vh] overflow-y-auto"):
                ui.label("Workout protection").classes("text-xl font-semibold")
                ui.label("Lock future sessions or record explicit completion. Completed sessions and history are always retained.").classes("break-words")
                items = season_workouts.list_workouts(db_path,season.season_id)
                options = {w["workout_id"]:f'{w["date"]} · {w["title"]}' for w in items}
                selected_workout = ui.select(options,label="Season workout",with_input=True).classes("w-full")
                locked = ui.checkbox("Keep this workout locked")
                completed = ui.checkbox("Record this workout as completed")
                reason = ui.input("Protection reason").classes("w-full")
                title = ui.input("Edited session title").classes("w-full")
                minutes = ui.number("Edited session minutes",min=1,max=1440).classes("w-full")
                override = ui.checkbox("I authorize editing this locked or manual future session")
                ui.label("Prescription edits create a new reviewed revision. This editor supports timed sessions; event and rest prescriptions use season regeneration.").classes("text-sm break-words")
                status = ui.label("").classes("break-words")
                error = ui.label("").classes("text-red-800 break-words")
                def choose(e):
                    row = next((w for w in items if w["workout_id"]==e.value),None)
                    if row:
                        title.value = row["title"]
                        w = row["workout"]
                        minutes.value = sum(s.duration_seconds for s in w.segments)/60 if all(s.duration_seconds is not None for s in w.segments) else None
                        locked.value = bool(row["state"].get("locked"))
                        completed.value = "completed" in row["reasons"]
                        status.text = "Preservation: " + (", ".join(row["reasons"]) or "Eligible future session")
                        if completed.value:
                            completed.disable()
                        else:
                            completed.enable()
                selected_workout.on_value_change(choose)
                def save():
                    try:
                        row = next((w for w in items if w["workout_id"]==selected_workout.value),None)
                        if row is None:
                            raise plans.SeasonError("Choose a workout.")
                        season_workouts.set_workout_protection(db_path,season.season_id,row["workout_id"],
                            expected_version=row["state"].get("version",0),editor="LOCAL_USER",reason=reason.value,
                            locked=locked.value,explicitly_completed=True if completed.value else None)
                    except (plans.SeasonError,sqlite3.Error,OSError,ValueError) as exc:
                        show_error(exc,error)
                        return
                    dialog.close()
                    content.refresh()
                    ui.notify("Workout protection saved.",type="positive")
                def preview_edit():
                    try:
                        row = next((w for w in items if w["workout_id"]==selected_workout.value),None)
                        if row is None:
                            raise plans.SeasonError("Choose a workout.")
                        w = row["workout"]
                        if w.event_flag or any(s.duration_seconds is None for s in w.segments):
                            raise plans.SeasonError("Choose a timed training session for prescription editing.")
                        total = _integer(Decimal(str(minutes.value))*60,"Edited duration")
                        previous = sum(s.duration_seconds for s in w.segments)
                        durations = [max(1,s.duration_seconds*total//previous) for s in w.segments]
                        durations[-1] += total-sum(durations)
                        if durations[-1]<1:
                            raise plans.SeasonError("Duration is too short for this session’s segments.")
                        edited = replace(w,workout_id=uuid4().hex,title=plans._text(title.value,"Session title"),
                            segments=tuple(replace(s,duration_seconds=n) for s,n in zip(w.segments,durations)))
                        request = RegenerationRequest("MANUAL_EDIT",override_workout_ids=(w.workout_id,) if override.value else (),
                            manual_workout=edited,replaces_workout_id=w.workout_id)
                        preview = generation.preview_season(db_path,season.season_id,GenerationSettings(),request)
                    except (plans.SeasonError,sqlite3.Error,OSError,ValueError) as exc:
                        show_error(exc,error)
                        return
                    dialog.close()
                    review_preview(preview)
                with ui.row().classes("w-full justify-end"):
                    ui.button("Preview prescription edit",on_click=preview_edit).props("outline")
                    ui.button("Close workout protection",on_click=dialog.close).props("flat")
                    ui.button("Save workout protection",on_click=save)
            dialog.open()

        @ui.refreshable
        def content() -> None:
            try:
                seasons = plans.list_seasons(db_path)
                season = next((s for s in seasons if s.season_id == selected["id"]), None)
                if not selected["id"] and seasons:
                    season = seasons[0]
                    selected["id"] = season.season_id
                events = plans.list_events(db_path, season.season_id) if season else ()
            except (plans.SeasonError, sqlite3.Error, OSError) as exc:
                show_error(exc)
                ui.label("Season data could not be loaded.")
                ui.button("Refresh seasons", on_click=content.refresh)
                return
            with ui.row().classes("w-full items-center gap-3"):
                ui.button("New season", icon="add", on_click=lambda: season_editor())
                ui.button("Refresh seasons", icon="refresh", on_click=content.refresh).props("outline")
                if seasons:
                    ui.select({s.season_id: f"{s.name} · {s.status}" for s in seasons}, value=None if season is None else season.season_id,
                              label="Season", on_change=lambda e: ui.navigate.to(f"/seasons?season_id={e.value}")).classes("w-full max-w-lg")
            if season is None:
                ui.label("Season not found. Choose one from the list." if selected["id"] else "Create a season to organize your events and training availability.")
                return
            with ui.card().classes("gdh-card w-full min-w-0"):
                ui.label(season.name).classes("text-2xl font-semibold break-words")
                ui.label(f"{season.start_date} → {season.end_date} · {season.timezone}").classes("text-slate-600 break-words")
                ui.label(f"{season.inputs.run_days_per_week} run days/week · Long run {season.inputs.long_run_day} · {'80/20' if season.inputs.training_method == 'eighty_twenty' else 'Maffetone'}").classes("break-words")
                ui.label("Available: " + ", ".join(plans.WEEKDAYS[d] for d in season.inputs.available_weekdays)).classes("break-words")
                ui.label("Baseline goal: general fitness · Distance goals are coming with baseline cycles.").classes("text-sm break-words")
                ui.label(f"Planning version {season.input_version}" + (f" · Linked revision {season.current_revision_id}" if season.plan_id else " · No linked schedule")).classes("text-sm text-slate-500 break-all")
                if season.plan_id:
                    ui.label("Event changes automatically prepare a proposal. Accept it to update eligible future workouts.").classes("text-amber-900 break-words")
                render_workflow(db_path,season.season_id,on_review=review_preview,on_settings=generation_editor,prepare=True,
                    on_change=lambda value: content.refresh() if value.season != season else None)
                with ui.row().classes("gap-3 flex-wrap"):
                    ui.link("Review yearly workouts on Plan", yearly_url("/plan",season.season_id))
                    ui.link("View applied phases on Dashboard", yearly_url("/",season.season_id,year=int(season.start_date[:4])))
                with ui.row().classes("gap-2"):
                    if season.status != "archived":
                        ui.button("Edit season", on_click=lambda: season_editor(season)).props("outline")
                    if season.status != "archived":
                        ui.button("Preview yearly schedule", icon="preview", on_click=lambda: generation_editor(season))
                        if season.current_revision_id:
                            ui.button("Workout protection",icon="lock",on_click=lambda: workout_controls(season)).props("outline")
                    ui.button("Restore season" if season.status == "archived" else "Archive season", on_click=lambda: archive(season)).props("flat")
            with ui.row().classes("w-full items-center justify-between"):
                ui.label("Event calendar").classes("text-xl font-semibold")
                if season.status != "archived":
                    ui.button("Add event", icon="add", on_click=lambda: event_editor(season))
            ui.label("A: primary peak goal · B: supporting preparation · C: training event").classes("text-sm text-slate-600")
            if not events:
                ui.label("No events yet.")
            for event in events:
                draft = event.draft
                with ui.card().classes("gdh-card w-full min-w-0"):
                    with ui.row().classes("w-full items-start justify-between gap-3 flex-col sm:flex-row"):
                        with ui.column().classes("gap-1 min-w-0 w-full sm:flex-1"):
                            with ui.row().classes("items-center"):
                                ui.badge(draft.priority, color={"A": "blue", "B": "teal", "C": "grey"}[draft.priority])
                                ui.label(draft.name).classes("font-semibold break-words min-w-0 flex-1")
                            ui.label(f"{draft.event_date} · {BASELINE_DISTANCE_OPTIONS[draft.distance_code]} · {draft.event_type.title()} · {draft.status.title()}").classes("break-words")
                            ui.label(draft.goal_intent.title()).classes("text-sm text-slate-600")
                            if draft.target_seconds is not None:
                                t = draft.target_seconds
                                ui.label(f"Target finish: {t // 3600:02}:{t // 60 % 60:02}:{t % 60:02}")
                            if draft.target_speed_mps is not None:
                                p = round(Decimal(1000) / Decimal(draft.target_speed_mps))
                                ui.label(f"Target pace: {p // 60:02}:{p % 60:02} /km")
                            if draft.participation_seconds is not None:
                                ui.label(f"Planned completion: {draft.participation_seconds / 60:g} minutes (estimated)").classes("text-sm break-words")
                            if draft.terrain or draft.course_notes:
                                ui.label(" · ".join(filter(None, (draft.terrain, draft.course_notes)))).classes("text-sm whitespace-pre-wrap break-words")
                            if draft.taper_days is not None or draft.recovery_days is not None:
                                ui.label(f"Taper: {draft.taper_days if draft.taper_days is not None else 'default'} days · Recovery: {draft.recovery_days if draft.recovery_days is not None else 'default'} days").classes("text-sm")
                        if season.status != "archived" and draft.status != "completed":
                            with ui.row().classes("gap-1 shrink-0"):
                                ui.button("Edit", on_click=lambda e=event: event_editor(season, e)).props(f'outline aria-label="Edit event {event.event_id}"').tooltip(f"Edit {draft.name}")
                                ui.button("Remove", on_click=lambda e=event: remove_event(season, e)).props(f'flat aria-label="Remove event {event.event_id}"').tooltip(f"Remove {draft.name}")
            applications = generation.list_applications(db_path,season.season_id)
            if applications:
                with ui.expansion("Applied season revisions", icon="history").classes("gdh-card w-full"):
                    for application in applications:
                        ui.label(f'{application["applied_at_utc"]} · {application["range_start"]} → {application["range_end"]} · {application["mode"]}').classes("break-words")
                        ui.label(f'Revision {application["resulting_revision_id"]} · Reviewed by {application["approved_by"]}').classes("text-sm break-all")
                        review = json.loads(application["review_json"])
                        ui.label(review["rationale"]).classes("text-sm break-words")
                        diff = review["diff"]
                        ui.label(f'{len(diff.get("added_workout_ids",()))} additions · {len(diff.get("removed_workout_ids",()))} removals · {len(diff.get("preserved_workout_ids",()))} preserved').classes("text-sm break-words")
                        with ui.expansion("Recorded preservation and overrides").classes("w-full"):
                            for decision in review.get("preserved",()):
                                ui.label(f'{decision["date"]} · {decision["title"]} · {", ".join(decision["reasons"])}').classes("text-sm break-words")
                            ui.label("Replacement overrides: " + (", ".join(review.get("overrides",())) or "None")).classes("text-sm break-all")
                        if review.get("event_assessments"):
                            with ui.expansion("Recorded event preparation").classes("w-full"):
                                for report in review["event_assessments"]:
                                    ui.label(f'{report["name"]} · {report["controlled_preparation_days"]} controlled preparation days · taper {report["taper_start"]} · recovery through {report["recovery_end"]}').classes("text-sm break-words")
                        with ui.expansion("Acknowledged warnings").classes("w-full"):
                            for warning in review["warnings"]:
                                ui.label(warning["message"]).classes("text-sm text-amber-900 break-words")
            if season.status != "archived" and not season.plan_id:
                with ui.expansion("Link an existing plan", icon="link").classes("gdh-card w-full"):
                    ui.label("Link a reviewed structured plan without changing its workouts. Older single-event schedules stay available on Plan; they must be explicitly converted before linking.").classes("break-words")
                    candidates = plans.linkable_plans(db_path)
                    if not candidates:
                        ui.label("No unlinked structured plans are available.")
                    else:
                        options = {p["plan_id"]: f'{p["plan_id"]} · {p["start_date"]}–{p["end_date"]} · {p["workout_count"]} session' + ('s' if p["workout_count"] != 1 else '') for p in candidates}
                        picker = ui.select(options, label="Existing plan").classes("w-full")
                        acknowledgement = ui.checkbox("I reviewed this plan and want the season to own its date range.").props(
                            'aria-label="I reviewed this plan and want the season to own its date range."')

                        def link() -> None:
                            try:
                                p = next((p for p in candidates if p["plan_id"] == picker.value), None)
                                if not acknowledgement.value or p is None:
                                    raise plans.SeasonError("Choose a plan and acknowledge linking its schedule.")
                                plans.link_plan(db_path, season.season_id, p["plan_id"], expected_version=season.input_version,
                                                expected_revision_id=p["current_revision_id"], expected_content_hash=p["content_sha256"])
                            except (plans.SeasonError, sqlite3.Error, OSError, ValueError) as exc:
                                show_error(exc)
                                return
                            content.refresh()
                            ui.notify("Plan linked. Workouts retained.", type="positive")
                        ui.button("Link reviewed plan", on_click=link)

        with ui.column().classes("gdh-page min-w-0"):
            page_heading("Seasons", "Organize a year of running events, priorities and availability.")
            ui.label("Preview yearly training and safely revise eligible future workouts.").classes("text-slate-600")
            ui.label("A yearly plan does not require a race. Seasons edits settings/events; Plan reviews workouts; Dashboard shows accepted phases.").classes("text-sm break-words")
            ui.link("Manage single-event plan", "/plan?workflow=single")
            content()
