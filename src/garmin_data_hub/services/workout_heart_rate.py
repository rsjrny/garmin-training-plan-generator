"""Display saved prescriptions without recalculating an accepted workout."""
from decimal import ROUND_CEILING, ROUND_FLOOR

from garmin_data_hub.plan_methodology.domain import Metric, MethodologyId, Sport


def unavailable_heart_rate(sport=None):
    auxiliary = sport in {"REST", "STRENGTH", "MOBILITY"}
    return dict(heart_rate="Not prescribed" if auxiliary else "Unavailable",
                heart_rate_details="" if auxiliary else
                "No saved heart-rate prescription. Check yearly Settings, then review a regenerated plan to create targets.")


def range_text(target, ceiling=None):
    """Whole bpm strictly inside the exact saved bounds, including any ceiling."""
    lower = None if target.lower is None else (
        int(target.lower.to_integral_value(rounding=ROUND_CEILING)) if target.lower_inclusive
        else int(target.lower.to_integral_value(rounding=ROUND_FLOOR)) + 1)
    upper = None if target.upper is None else (
        int(target.upper.to_integral_value(rounding=ROUND_FLOOR)) if target.upper_inclusive
        else int(target.upper.to_integral_value(rounding=ROUND_CEILING)) - 1)
    if ceiling is not None:
        cap = (int(ceiling.value.to_integral_value(rounding=ROUND_FLOOR)) if ceiling.inclusive
               else int(ceiling.value.to_integral_value(rounding=ROUND_CEILING)) - 1)
        upper = cap if upper is None else min(upper, cap)
    if lower is not None and upper is not None:
        if lower > upper:
            return "No whole-bpm target within saved bounds"
        return f"{lower} bpm" if lower == upper else f"{lower}–{upper} bpm"
    return f"≤ {upper} bpm" if lower is None else f"≥ {lower} bpm"


def workout_heart_rate(workout):
    if workout.sport is not Sport.RUNNING:
        return unavailable_heart_rate(workout.sport.value)
    summaries, details = [], []
    for index, segment in enumerate(workout.segments, 1):
        rx = segment.prescription
        target = next((r for r in (rx.primary, rx.secondary)
                       if r is not None and r.metric is Metric.HEART_RATE), None) if rx else None
        if target is None:
            summary = "HR unavailable"
        else:
            method = "80/20" if rx.methodology_id is MethodologyId.FITZGERALD_80_20_RUNNING_V1 else "Maffetone"
            zone = ("zone " + rx.native_target.value.removeprefix("F80.ZONE_")
                    if method == "80/20" else {"MAF.MAF_AEROBIC_RANGE":"aerobic range",
                        "MAF.MAF_CEILING":"ceiling", "MAF.SUB_MAF":"below aerobic range"}[rx.native_target.value])
            summary = f"{method} {zone}: {range_text(target, rx.ceiling)}"
            if target is rx.secondary:
                summary += f" (secondary; {rx.primary.metric.value.lower()} primary)"
        if summary not in summaries:
            summaries.append(summary)
        kind = {"WARMUP": "Warm-up", "COOLDOWN": "Cool-down"}.get(
            segment.kind.value, segment.kind.value.replace("_", " ").title())
        amount = (f"{segment.duration_seconds / 60:g} min" if segment.duration_seconds is not None
                  else f"{segment.distance_metres:g} m" if segment.distance_metres is not None else "")
        repeat = f" · repeat {segment.repeat_iteration}" if segment.repeat_iteration is not None else ""
        details.append(f"{index}. {kind}{repeat}" + (f" · {amount}" if amount else "") + f" · {summary}")
    if not summaries or summaries == ["HR unavailable"]:
        return unavailable_heart_rate(workout.sport.value)
    return dict(heart_rate=" · ".join(summaries), heart_rate_details="\n".join(details))
