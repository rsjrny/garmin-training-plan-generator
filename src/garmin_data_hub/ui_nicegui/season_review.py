"""Shared reviewed proposal details; application remains explicitly acknowledged."""
import sqlite3
from collections import OrderedDict
from garmin_data_hub.services import season_generation as generation, season_plans as plans
from garmin_data_hub.services.season_schedule import event_resolution_notes


def warning_groups(warnings):
    """Condense repeated wording while retaining every dated finding for review."""
    groups = OrderedDict()
    for issue in warnings:
        groups.setdefault((issue.code, issue.message, issue.event_ids), []).append(issue)
    return tuple(tuple(issues) for issues in groups.values())

def review_preview(db_path, preview: generation.SeasonPreview, *, container, on_applied=lambda: None, tune_event=None) -> None:
    from nicegui import ui

    def show_error(exc, label):
        label.text = str(exc) if isinstance(exc, ValueError) else "Database unavailable. Refresh and try again."
        ui.notify(label.text, type="negative")
    generation_settings_note = "Baseline goal: general fitness. Always ready for distance goals are coming with baseline cycles."
    schedule = preview.schedule
    with container, ui.dialog() as dialog, ui.card().classes("w-full max-w-5xl max-h-[90vh] overflow-y-auto min-w-0"):
        ui.label("Season schedule preview").classes("text-xl font-semibold")
        ui.label(f"{preview.season.start_date} → {preview.season.end_date} · {len(schedule.candidate.workouts)} sessions · {len(preview.events)} saved events").classes("break-words")
        ui.label(generation_settings_note).classes("text-sm break-words")
        if preview.regeneration:
            diff = schedule.candidate.change_summary
            ui.label(f'Replacement: {diff["range_start"]} → {diff["range_end"]} · {diff["mode"]}').classes("font-semibold break-words")
            ui.label(f'Recommended: {diff["recommended_start"]} → {diff["recommended_end"]}').classes("text-sm break-words")
            for reason in diff["range_reasons"]:
                ui.label(reason).classes("text-sm break-words")
            ui.label(f'{len(diff["added_workout_ids"])} additions · {len(diff["removed_workout_ids"])} removals · {len(diff["changed"])} replacements · {len(diff["preserved_workout_ids"])} preserved').classes("break-words")
            with ui.expansion("Workout changes and preservation",value=True).classes("w-full"):
                changes = [{"id":d["workout_id"],"date":d["date"],"action":"Preserved","reason":", ".join(d["reasons"]),"session":d["title"]} for d in diff["preserved"]]
                for w in schedule.candidate.workouts:
                    if w.workout_id in diff["added_workout_ids"]:
                        changes.append({"id":w.workout_id,"date":w.scheduled_date.isoformat(),"action":"Added","reason":"New prescription","session":w.title})
                changed_ids = {c["old_workout_id"] for c in diff["changed"]}
                for removed in diff.get("removed",()):
                    changes.append({"id":removed["workout_id"],"date":removed["date"],
                        "action":"Removed / replaced" if removed["workout_id"] in changed_ids else "Removed",
                        "reason":"Revised event or training prescription","session":removed["title"]})
                ui.table(columns=[{"name":k,"label":k.title(),"field":k} for k in ("date","action","session","reason")],rows=sorted(changes,key=lambda r:r["date"]),row_key="id",pagination=8).classes("w-full")
            if diff["overrides"]:
                ui.label("Explicit replacement overrides: " + ", ".join(diff["overrides"])).classes("text-amber-900 break-all")
        else:
            ui.label("Initial schedule: all sessions are additions. Existing workouts outside these yearly dates are retained.").classes("text-slate-600 break-words")
        for message in preview.apply_blockers:
            ui.label(message).classes("text-amber-900 break-words")
        if any("Existing workouts overlap" in message for message in preview.apply_blockers):
            from garmin_data_hub.ui_nicegui.season_overlap import review_overlap

            def resolve_overlap():
                dialog.close()
                review_overlap(db_path,preview.season.season_id,container=container,on_linked=on_applied)

            ui.button("Review overlapping workouts",on_click=resolve_overlap).props("outline")
        # Keep approval and its blocker explanation reachable even for full years
        # with hundreds of dated warnings. This does not relax service safeguards.
        with ui.column().classes("sticky top-0 z-10 bg-white w-full py-2 border-b gap-1"):
            if not preview.can_apply:
                ui.label("Apply unavailable: resolve the schedule blockers or conflicts, then review a fresh proposal.").classes("text-sm text-amber-900 break-words")
            acknowledgement = ui.checkbox("I reviewed the schedule and acknowledge all warnings.").props('aria-label="I reviewed the schedule and acknowledge all warnings."').classes("w-full")
            error = ui.label("").classes("text-red-800 break-words")

            def apply() -> None:
                try:
                    if not acknowledgement.value:
                        raise plans.SeasonError("Review and acknowledge the schedule warnings before applying.")
                    result = generation.apply_season_preview(db_path,preview,approved_by="LOCAL_USER",
                                                             acknowledge_warnings=acknowledgement.value)
                except (plans.SeasonError,sqlite3.Error,OSError,ValueError) as exc:
                    show_error(exc,error)
                    return
                dialog.close()
                on_applied()
                ui.notify("Season schedule applied." if result.status=="applied" else "This preview was already applied.",type="positive")

            with ui.row().classes("w-full justify-end"):
                ui.button("Close preview",on_click=dialog.close).props("flat")
                button = ui.button("Apply reviewed season",on_click=apply)
                if not preview.can_apply:
                    button.disable()
        ui.label("Conflicts and warnings").classes("font-semibold")
        with ui.expansion(f"Review {len(schedule.errors)} conflicts and {len(schedule.warnings)} warnings",value=True).classes("w-full"):
            for issue in schedule.errors:
                ui.label((f"{issue.date} · " if issue.date else "") + issue.message).classes("break-words text-red-800")
                for note in event_resolution_notes(issue, schedule.windows):
                    ui.label(note).classes("text-sm break-words text-slate-700")
            groups = warning_groups(schedule.warnings)
            ui.label(f"{len(schedule.warnings)} warnings in {len(groups)} groups. Repeated warnings retain every affected date below.").classes("text-sm break-words")
            for group in groups:
                issue = group[0]
                if len(group)==1:
                    ui.label((f"{issue.date} · " if issue.date else "") + issue.message).classes("break-words text-amber-900")
                    for note in event_resolution_notes(issue, schedule.windows):
                        ui.label(note).classes("text-sm break-words text-slate-700")
                else:
                    ui.label(f"{len(group)} occurrences · {issue.message}").classes("break-words text-amber-900")
                    with ui.expansion(f"Affected dates ({len(group)}): {issue.code}").classes("w-full"):
                        for occurrence in group:
                            ui.label(occurrence.date or "Schedule-wide").classes("text-sm break-words")
                            for note in event_resolution_notes(occurrence, schedule.windows):
                                ui.label(note).classes("text-sm break-words text-slate-700")
        assessments = (schedule.candidate.constraints or {}).get("event_assessments", ())
        if assessments:
            with ui.expansion("Event preparation and tuning", value=True).classes("w-full"):
                ui.label("Calendar opportunity is not a readiness prediction. Shared days can also be constrained; counts describe phase control, not completed training.").classes("text-sm break-words")
                for report in assessments:
                    ui.label(f'{report["priority"]} · {report["name"]} · {report["event_date"]}').classes("font-semibold break-words")
                    ui.label(f'Preparation starts {report["preparation_start"]}; taper starts {report["taper_start"]} ({report["taper_days"]} days); recovery ends {report["recovery_end"]} ({report["recovery_days"]} days).').classes("text-sm break-words")
                    ui.label(f'{report["controlled_preparation_days"]} controlled preparation days · {report["shared_preparation_days"]} shared · {report["constrained_preparation_days"]} constrained · {report["preparation_days_outside_season"]} outside season').classes("text-sm break-words")
                    event = next((e for e in preview.events if e.event_id == report["event_id"]), None)
                    if tune_event and event and event.draft.status != "completed" and preview.season.status != "archived":
                        def tune(e=event):
                            dialog.close()
                            tune_event(preview.season, e)
                        ui.button(f'Tune {event.draft.name}', on_click=tune).props(f'outline aria-label="Tune event {event.event_id}"')
                ui.label("Saving event tuning automatically prepares a fresh proposal. The active calendar changes only after reviewed apply.").classes("text-sm break-words")
        phases = []
        for c in schedule.controls:
            key = (c.phase,c.event_id)
            if phases and phases[-1]["key"]==key:
                phases[-1]["end"] = c.day.isoformat()
            else:
                phases.append({"key":key,"start":c.day.isoformat(),"end":c.day.isoformat(),"phase":c.phase,
                               "event":next((e.draft.name for e in preview.events if e.event_id==c.event_id),"Maintenance")})
        with ui.expansion("Training phases",value=True).classes("w-full"):
            ui.label("Event influence before preservation. Protected and historical sessions keep their original phases; Proposed sessions below shows each session's actual phase.").classes("text-sm break-words")
            for phase in phases:
                ui.label(f'{phase["start"]} → {phase["end"]} · {phase["phase"].replace("_"," ").title()} · {phase["event"]}').classes("break-words text-sm")
        week_rows = [{"week":w.monday,"coverage":"Partial" if w.partial else "Full",
            "minutes":round(w.training_seconds/60,1),"event_minutes":None if w.event_duration_seconds is None else round(w.event_duration_seconds/60,1),
            "event_km":round(w.event_distance_metres/1000,2),"hard":w.hard_days,"cutback":"Yes" if w.cutback else ""} for w in schedule.weeks]
        ui.label("Local Monday–Sunday workload").classes("font-semibold")
        ui.label("Training minutes exclude event load, shown separately. Unknown event minutes and TSS remain unknown.").classes("text-sm break-words")
        ui.table(columns=[{"name":k,"label":v,"field":k} for k,v in [("week","Week starting"),("coverage","Coverage"),("minutes","Training min"),("event_minutes","Event min (estimated)"),("event_km","Event km"),("hard","Hard days"),("cutback","Cutback")]],
                 rows=week_rows,row_key="week",pagination=8).classes("w-full")
        ui.label("Proposed sessions").classes("font-semibold")
        ui.table(columns=[{"name":k,"label":v,"field":k} for k,v in [("date","Date"),("title","Session"),("sport","Sport"),("phase","Phase"),("minutes","Minutes"),("targets","Native targets")]],
            rows=[{"id":w.workout_id,"date":w.scheduled_date.isoformat(),"title":w.title,"sport":w.sport.value,"phase":w.phase,
                   "minutes":round(sum(s.duration_seconds for s in w.segments)/60,1) if all(s.duration_seconds is not None for s in w.segments) else None,
                   "targets":" · ".join(sorted({s.prescription.native_target.value for s in w.segments if s.prescription}))} for w in schedule.candidate.workouts],
            row_key="id",pagination=10).classes("w-full")
    dialog.open()

