# Recovery & Readiness Engine v1

Defined October 14, 2026 before implementation. This is an explainable, experimental
product model, not a reproduction of Welltory/Garmin algorithms or a validated
medical, fatigue, energy or performance measurement. Mathematical, persistence
and UI tests validate implementation; prospective outcome validation remains open.

## Inputs and existing infrastructure

The configured Garmin database has `sleep`, `hrv`, `daily_summary`,
`training_readiness`, `body_battery`, `activity` and app-owned `activity_metrics`.
The installed `garmin-givemydata==0.1.13` runtime imports health summaries; its
`hrv_timeline` holds aggregated readings in JSON, not an app-supported beat-to-beat
RR stream. The old app FIT parser can archive raw messages, but the supported FIT
pipeline is upstream and no RR extraction/quality-control pipeline exists here.
No RMSSD, SDNN, LF/HF or nervous-system diagnosis is inferred from average HRV.

Reuse the existing sleep/recovery table reader, activity calendar-day rules,
current-provenance derived-TSS reader and CTL/ATL/TSB calculation. Do not derive
activity metrics again, change sync, or create a parallel persistent metrics store.
Assessments are recomputed read-only from one coherent transaction and versioned
as `recovery-readiness.v1`; they pick up sync/metric refreshes on refresh/reload.

Garmin sleep score, Training Readiness, HRV status and Body Battery remain dated
comparison values. They never enter the app's composite scores. Measured sleep
duration, nightly HRV, RHR and Garmin's estimated stress can enter the app model.
This independence concerns composite calculations, not independent sensors.

## Time and missing-data rules

An assessment for D uses sleep/HRV/RHR dated D, stress from D-1 and recorded
activities strictly before D. Never substitute an older night as today's signal.
The history chart assesses every calendar date, including empty dates. Baselines
exclude the assessed day and all future data. Retrospective calculations describe
daily summaries, not what was known at a specific clock time.

Non-finite, sentinel, out-of-range or invalid-date inputs are unavailable. Empty
records, missing dates and absent tables are not zero measurements. Sleep accepts
0–24 h, HRV 1–500 ms, RHR 25–150 bpm and stress/comparison scores 0–100. These
are input-quality bounds, not diagnostic thresholds. Valid zero sleep/stress/TSS
is distinct from absence. Require a supported positive training baseline.

HRV and RHR use a trailing 28-day personal median with at least 14 observations,
including at least three in the prior seven days. HRV uses log values; robust
spread is `max(1.4826 × median absolute deviation, log(1.1))`. RHR uses raw bpm
and a spread floor of 3 bpm. Today's value cannot move its own baseline.

The saved sleep target defaults to 8 h and can be set to 6–12 h. It is a planning
preference, not an inferred sleep requirement. Garmin sleep need is comparison
only. Seven-night shortfall sums `max(target - sleep, 0)` on observed nights,
including D; at least five of seven nights are needed to score it. Report the
observed night count and never scale missing nights up or let excess sleep cancel
shortfalls. This is a simple target shortfall estimate, not physiological debt.

## Transparent component rules

Clamp every component to 0–100; higher means more favorable model inputs.

| Component | Rule |
| --- | --- |
| HRV context | `90 - 20 × max(abs(robust log deviation) - 1, 0)`; unusual high HRV is not rewarded |
| RHR context | `90 - 15 × max(positive robust deviation, 0)`; lower RHR never boosts above 90 |
| Last-night sleep | `100 × min(sleep / saved target, 1)` |
| Prior-day stress | `100 - recorded stress` |
| Seven-night shortfall | `100 - 5 × observed shortfall hours` |
| Recent recorded load | `90 - 30 × max(ATL/CTL - 1, 0)` |

Recorded load uses 42 completed calendar days. Choose one consistent series:
device/current derived TSS when every observed activity has TSS; otherwise
recorded duration when every observed activity has duration. Never mix Garmin
exercise load, TRIMP, TSS or time units. Existing CTL/ATL/TSB EWM spans remain
42/7 days; the difference is context, not a validated fatigue measurement.
Require at least four recorded activity days, 28/42 daily-summary dates and all
seven recent daily-summary dates before scoring load. Calendar gaps are zero
**recorded** load only, never verified rest; daily summaries do not prove complete
activity synchronization. Any undated activity makes load unavailable. Duration
fallback is a volume proxy without intensity. Explain both coverage limitations.

## Three distinct composite estimates

Renormalize only available weights and expose coverage against intended weights.
No score is shown until the listed gates hold. Missing components remain visible.

| Score | Intended weights | Minimum evidence |
| --- | --- | --- |
| Recovery | HRV 35%, RHR 25%, sleep 25%, prior stress 15% | At least two components, including HRV or RHR, and ≥60% weight |
| Readiness | Recovery 55%, recorded load 25%, sleep shortfall 20% | Recovery plus another component and ≥70% weight |
| Energy estimate | Sleep 50%, shortfall 30%, prior stress 20% | Today's sleep plus another component and ≥70% weight |

Coverage labels describe available inputs, not clinical confidence. HRV/RHR factors
scale coverage by baseline observations out of 28; shortfall uses observed nights
out of seven. Load uses daily-summary dates out of 42, with an additional 80%
factor for the duration-only proxy. These coverage mappings are product choices.
Full coverage
can be labelled Well covered; partial coverage is Limited; failed gates are
Insufficient. Readiness coverage includes its recovery subscore's missing weights.
No favorable energy estimate substitutes for unavailable recovery/readiness.

## Guidance and user interface

Provide a Recovery page, a compact Dashboard link/summary, dated history, Garmin
comparisons, factor values/baselines/weights, missing inputs and freshness. Persist
only explicitly saved sleep-target preferences in existing `app_settings`.
Do not send new health data to Coach or external services or modify planned work.

Low recovery/readiness suggests reviewing hard/long training and considering an
easy/rest day. Middle estimates suggest keeping training easy until checking how
the athlete feels. Favorable estimates support following the existing plan if
feeling well; they never authorize adding intensity. Insufficient or stale data
produce data-check guidance instead of current training clearance. Use latest
available day can show a historical score with its explicit date and age; it does
not provide today's training guidance. Retrospective TSS follows the existing
current-provenance derived-metric pipeline when device TSS is absent, so historical
results can change after metric refreshes; the input identity records that context.
Multiple unfavorable
HRV/RHR/sleep signals remain explicit drivers, without diagnosing illness or
overtraining. Guidance is advisory and the active schedule remains unchanged.

## Evidence informing scope, not formula validation

Garmin describes comparing HRV to an individual baseline and notes that unusually
high values can also need context. Its [HRV Status explanation](https://www.garmin.com/en-IE/garmin-technology/health-science/hrv-status/)
and [device manual](https://www8.garmin.com/manuals/webhelp/GUID-AC520B63-3C82-4266-90F6-6E9F22D5F76E/EN-US/GUID-9282196F-D969-404D-B678-F48A13D8D0CB.html)
support longitudinal interpretation. The [AASM/SRS adult sleep consensus](https://www.aasm.org/resources/pdf/adultsleepdurationconsensus.pdf)
recommends regular sleep of seven or more hours for adults; it does not validate
this model's adjustable eight-hour target, shortfall mapping or score weights.
All numeric mappings and evidence gates above are documented product choices.
