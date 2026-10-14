"""Shared reviewed proposal details; application remains explicitly acknowledged."""
import json
import sqlite3
from garmin_data_hub.plan_methodology.canonical import canonical_value
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
    from garmin_data_hub.ui_nicegui.planning_presenter import change_counts, change_rows, friendly_phase, friendly_intensity, workout_counts
    from garmin_data_hub.services.season_baseline import goal_label
    generation_settings_note = ("A/B events shape preparation, peak, taper, recovery and transition. Other dates follow baseline cycles."
        if any(e.draft.priority != "C" and e.draft.status not in {"cancelled", "skipped"} for e in preview.events) else
        "Without A/B events, Base and Build blocks repeat with recovery weeks.")
    schedule = preview.schedule
    with container, ui.dialog() as dialog, ui.card().classes("w-full max-w-5xl max-h-[90vh] overflow-y-auto min-w-0"):
        ui.add_css("@media(min-width:601px){.planning-mobile-changes{display:none!important}} "
                   "@media(max-width:600px){.planning-changes-table{display:none!important}}")
        ui.label("Review yearly plan").classes("text-xl font-semibold")
        ui.label(f"{preview.season.start_date} → {preview.season.end_date} · {len(preview.events)} saved events").classes("break-words")
        totals = workout_counts([dict(sport=w.sport.value, workout=w.title) for w in schedule.candidate.workouts])
        ui.label(" · ".join(f"{totals[k]} {label}" for k,label in (("running","runs"),("strength","strength workouts"),("rest","rest days"),("other","other entries")) if totals[k])).classes("text-sm break-words")
        ui.label(generation_settings_note).classes("text-sm break-words")
        markers = [e for e in preview.events if e.draft.priority == "C" and e.draft.status in {"planned", "completed"}]
        if markers:
            ui.label("C events are calendar markers only. Follow the planned workout; no preparation, taper or recovery is added.").classes("text-sm break-words")
            for marker in markers:
                ui.label(f'C · {marker.draft.name} · {marker.draft.event_date} · Calendar marker').classes("text-sm break-words")
        ui.label("Baseline goal: " + goal_label(preview.season.inputs.baseline_distance_code)).classes("text-sm break-words")
        ui.label("Three Base weeks, four Build weeks, one recovery week. Saved goals describe training intent, not achieved readiness.").classes("text-sm break-words")
        if preview.regeneration:
            diff = schedule.candidate.change_summary
            counts = change_counts(diff)
            ui.label(f'Affected dates: {diff["range_start"]} → {diff["range_end"]}').classes("font-semibold break-words")
            ui.label(f'{counts["changed"]} changed · {counts["added"]} added · {counts["removed"]} removed · {counts["unchanged"]} unchanged workouts').classes("break-words").props('data-testid="change-counts"')
            ui.label("Your saved event or training settings prompted this update. Review the changed workouts before applying.").classes("text-sm break-words")

        else:
            ui.label("Initial plan: these workouts will be added when you apply. Existing workouts outside these dates stay unchanged.").classes("text-slate-600 break-words")
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
                ui.notify("Yearly plan applied." if result.status=="applied" else "This preview was already applied.",type="positive")

            with ui.row().classes("w-full justify-end"):
                ui.button("Review later",on_click=dialog.close).props("flat")
                button = ui.button("Apply changes",on_click=apply)
                if not preview.can_apply:
                    button.disable()
        ui.label("Review later keeps your saved settings and events; the active workouts change only after Apply changes.").classes("text-sm break-words")
        if preview.regeneration:
            from garmin_data_hub.plan_methodology.revision_repository import load_revision
            parent = load_revision(db_path, schedule.candidate.parent_revision_id)
            changed, unchanged = change_rows(diff, schedule.candidate.workouts, parent.candidate.workouts if parent else ())
            mobile_page = {"value": 1}
            @ui.refreshable
            def mobile_changes():
                with ui.column().classes("w-full planning-mobile-changes gap-2"):
                    for row in changed[(mobile_page["value"]-1)*8:mobile_page["value"]*8]:
                        with ui.card().classes("w-full p-3 gap-1 border shadow-none min-w-0"):
                            ui.label(f'{row["date"]} · {row["action"]}').classes("font-semibold")
                            ui.label("Before:").classes("text-xs font-semibold")
                            ui.label(row["before"]).classes("text-sm break-words")
                            ui.label("After:").classes("text-xs font-semibold")
                            ui.label(row["after"]).classes("text-sm break-words")
                            ui.label(row["reason"]).classes("text-xs text-slate-600 break-words")
                    if len(changed) > 8:
                        def change_page(e):
                            mobile_page["value"] = e.value
                            mobile_changes.refresh()
                        ui.pagination(min=1,max=(len(changed)+7)//8,value=mobile_page["value"],on_change=change_page).props("max-pages=3 boundary-numbers=false").classes("w-full")
            with ui.expansion("Changed workouts", value=True).classes("w-full"):
                if not changed:
                    ui.label("No workouts change in this proposal.")
                else:
                    mobile_changes()
                    ui.table(columns=[{"name":k,"label":label,"field":k,"align":"left"} for k,label in
                        (("date","Date"),("action","Change"),("before","Before"),("after","After"),("reason","Why"))],
                        rows=changed,row_key="id",pagination=8).classes("w-full planning-changes-table").props('wrap-cells').props('data-testid="changed-workouts"')
            with ui.expansion(f'Unchanged workouts ({counts["unchanged"]})').classes("w-full"):
                ui.table(columns=[{"name":k,"label":label,"field":k,"align":"left"} for k,label in
                    (("date","Date"),("before","Workout"),("reason","Why it stays"))],rows=unchanged,row_key="id",pagination=8).classes("w-full").props("wrap-cells")
            if parent:
                from collections import defaultdict
                from datetime import timedelta
                def loads(workouts):
                    weeks = defaultdict(list)
                    for w in workouts:
                        weeks[(w.scheduled_date-timedelta(days=w.scheduled_date.weekday())).isoformat()].append(w)
                    return {day: sum(s.duration_seconds for w in ws for s in w.segments)/60
                        if all(s.duration_seconds is not None for w in ws for s in w.segments) else None for day,ws in weeks.items()}
                before, after = loads(parent.candidate.workouts), loads(schedule.candidate.workouts)
                load_changes = [{"week":day,"before":before.get(day,0),"after":after.get(day,0)}
                    for day in sorted(before.keys() | after.keys()) if before.get(day,0) != after.get(day,0)]
                with ui.expansion("Weekly time changes", value=True).classes("w-full"):
                    ui.label("Minutes include timed event and training sessions. Unknown event durations remain unknown.").classes("text-sm break-words")
                    ui.table(columns=[{"name":k,"label":label,"field":k,"align":"left"} for k,label in
                        (("week","Week starting"),("before","Before (min)"),("after","After (min)"))],rows=load_changes,row_key="week",pagination=5).classes("w-full")
            with ui.expansion("Technical change details").classes("w-full"):
                ui.label(f'Replacement: {diff["range_start"]} → {diff["range_end"]} · {diff["mode"]}').classes("break-words")
                ui.label(f'Recommended: {diff["recommended_start"]} → {diff["recommended_end"]}').classes("text-sm break-words")
                for reason in diff["range_reasons"]:
                    ui.label(reason).classes("text-sm break-words")
                ui.code(json.dumps(canonical_value(diff), indent=2), language="json").classes("w-full max-h-72 overflow-auto")
            if diff["overrides"]:
                ui.label("Explicit replacement overrides: " + ", ".join(diff["overrides"])).classes("text-amber-900 break-all")
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
            with ui.expansion("Event preparation and tuning").classes("w-full"):
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
        with ui.expansion("Training phases").classes("w-full"):
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
            rows=[{"id":w.workout_id,"date":w.scheduled_date.isoformat(),"title":w.title,"sport":w.sport.value,"phase":friendly_phase(w.phase),
                   "minutes":round(sum(s.duration_seconds for s in w.segments)/60,1) if all(s.duration_seconds is not None for s in w.segments) else None,
                   "targets":" · ".join(sorted({friendly_intensity(s.prescription.native_target.value) for s in w.segments if s.prescription}))} for w in schedule.candidate.workouts],
            row_key="id",pagination=10).classes("w-full")
    dialog.open()

