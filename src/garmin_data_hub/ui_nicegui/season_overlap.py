"""Explicit, non-destructive resolution of initial schedule ownership conflicts."""
import sqlite3

from garmin_data_hub.services import season_overlap, season_plans as plans
from garmin_data_hub.services.yearly_workflow import proposals
from garmin_data_hub.ui_nicegui.yearly_workflow import yearly_url


def review_overlap(db_path, season_id, *, container, on_linked=lambda: None):
    from nicegui import ui

    try:
        review = season_overlap.review_overlap(db_path, season_id)
    except (ValueError, sqlite3.Error, OSError) as exc:
        ui.notify(str(exc) if isinstance(exc, ValueError) else "Unable to read overlapping workouts. Refresh and try again.", type="negative")
        return
    with container, ui.dialog() as dialog, ui.card().classes("w-full max-w-3xl max-h-[90vh] overflow-y-auto min-w-0"):
        ui.label("Review overlapping workouts").classes("text-xl font-semibold break-words")
        ui.label(f"{len(review.workouts)} existing workouts overlap {review.season.name}.").classes("break-words")
        ui.label("The initial proposal adds a new schedule; it cannot replace these workouts. Linking an existing structured plan retains its workouts and lets you review a protected replacement proposal next.").classes("text-sm break-words")
        if not review.workouts:
            ui.label("The overlap has changed. Close this review and prepare a fresh yearly proposal.").classes("break-words")
        ui.table(columns=[{"name":k,"label":v,"field":k} for k,v in
            (("scheduled_date","Date"),("workout_name","Existing workout"),("owner","Schedule"))],
            rows=[dict(w, owner=w["source_plan_id"] or "Older single-event schedule") for w in review.workouts],
            row_key="planned_workout_id", pagination=8).classes("w-full")
        if review.legacy_count:
            noun = "workout belongs" if review.legacy_count == 1 else "workouts belong"
            ui.label(f"{review.legacy_count} {noun} to an older single-event schedule.").classes("font-semibold break-words")
            ui.label("This app cannot yet safely adopt or replace just this year's older single-event workouts. Older schedules require a separate reviewed migration of the entire schedule; year-only replacement is not available yet.").classes("text-sm break-words")
            ui.label("You can explicitly review removal of eligible future older workouts first. Their original prescriptions stay saved; yearly apply remains a separate acceptance.").classes("text-sm break-words")

            def remove_older():
                from garmin_data_hub.ui_nicegui.legacy_workout_removal import remove_older_workouts
                dialog.close()
                remove_older_workouts(db_path,container=container,season=review.season,on_removed=on_linked)

            ui.button("Remove older workouts",on_click=remove_older).props("outline")
        if not review.candidates:
            ui.label("No overlapping structured plan is available to link.").classes("break-words")
        if review.separate_start:
            with ui.card().classes("w-full min-w-0"):
                ui.label("Keep existing workouts and use separate dates").classes("font-semibold break-words")
                ui.label(f"Start this yearly plan on {review.separate_start}; keep its end on {review.season.end_date}. All existing workouts remain in place. This saves yearly settings and prepares a new proposal; it does not apply workouts.").classes("text-sm break-words")
                ui.label("Review the retained workouts and any recovery needs before accepting the new proposal.").classes("text-sm break-words")
                separate_error = ui.label("").classes("text-red-800 break-words")

                async def separate_dates():
                    try:
                        # Recheck ownership from a coherent snapshot before the
                        # optimistic update; generation/apply recheck it again.
                        current = season_overlap.review_overlap(db_path,season_id)
                        if current != review:
                            raise plans.StaleSeasonError("Existing workouts or yearly settings changed. Reopen overlap review for the latest dates.")
                        plans.update_season(db_path,season_id,plans.SeasonDraft(review.season.name,
                            review.separate_start,review.season.end_date,review.season.timezone,review.season.inputs),
                            expected_version=review.season.input_version)
                    except (ValueError, sqlite3.Error, OSError) as exc:
                        separate_error.text = str(exc) if isinstance(exc, ValueError) else "Unable to save separate dates. Refresh and try again."
                        return
                    dialog.close()
                    on_linked()
                    ui.notify("Yearly start saved. Existing workouts retained; review the new proposal before applying.",type="positive")
                    try:
                        await proposals.ensure(db_path,season_id)
                    except (ValueError, sqlite3.Error, OSError):
                        ui.notify("Dates saved. Proposal unavailable; refresh or review yearly settings.",type="warning")

                ui.button(f"Save start {review.separate_start} and prepare proposal",on_click=separate_dates).classes("w-full").props("outline")
        elif review.separate_reason:
            ui.label(review.separate_reason).classes("text-amber-900 break-words")
        for candidate in review.candidates:
            with ui.card().classes("w-full min-w-0"):
                noun = "workout" if candidate["workout_count"] == 1 else "workouts"
                ui.label(f'{candidate["start_date"]} → {candidate["end_date"]} · {candidate["workout_count"]} {noun}').classes("font-semibold break-words")
                ui.label(candidate["plan_id"]).classes("text-xs break-all")
                for reason in candidate["reasons"]:
                    ui.label(reason).classes("text-amber-900 break-words")
                acknowledgement = ui.checkbox("I reviewed these workouts and want this year to own the existing plan.").classes("w-full")
                error = ui.label("").classes("text-red-800 break-words")

                async def link(p=candidate, ack=acknowledgement, label=error):
                    try:
                        if not ack.value:
                            raise plans.SeasonError("Review and acknowledge the existing workouts before linking.")
                        plans.link_plan(db_path, season_id, p["plan_id"], expected_version=review.season.input_version,
                                        expected_revision_id=p["current_revision_id"], expected_content_hash=p["content_sha256"])
                    except (ValueError, sqlite3.Error, OSError) as exc:
                        label.text = str(exc) if isinstance(exc, ValueError) else "Unable to link this plan. Refresh and try again."
                        return
                    dialog.close()
                    on_linked()
                    ui.notify("Existing plan linked. Workouts retained; review a fresh yearly replacement before applying changes.", type="positive")
                    try:
                        await proposals.ensure(db_path, season_id)
                    except (ValueError, sqlite3.Error, OSError):
                        ui.notify("Plan linked. Proposal unavailable; refresh or review yearly settings.", type="warning")

                button = ui.button("Link reviewed existing plan", on_click=link)
                if candidate["reasons"]:
                    button.disable()
        ui.label("You can also keep the existing schedule and choose separate yearly dates in Seasons.").classes("text-sm break-words")
        with ui.row().classes("w-full justify-end"):
            ui.link("Edit yearly dates", yearly_url("/seasons",season_id))
            ui.link("View existing schedule", "/plan?workflow=single")
            ui.button("Close overlap review",on_click=dialog.close).props("flat")
    dialog.open()
