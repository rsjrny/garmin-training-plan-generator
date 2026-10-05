# UI Preferences Plan

Created: 2026-10-05
Status: Planned; U1 and U2 implementation has not started.
Roadmap: [Implementation roadmap](IMPLEMENTATION_ROADMAP.md).

## Objective

Reopen the application with the UI sizing the user last chose, and provide a
persistent theme selector that applies consistently throughout the application.

## U1 - Persist UI sizing and restore on reopen

Inventory every user-adjustable sizing control and native-window setting before
implementation. Record the supported controls and persistence location in this
plan. Include native window width/height, position and maximized state; adjustable
sidebar widths, split-pane ratios, table column widths and user-controlled chart/
panel dimensions where these controls exist. Restore collapsed/expanded layout
state when it determines visible sizing. Do not introduce resizing controls for
every fixed component solely to persist them.

Persist preferences across full application restarts, not just page navigation
or the current browser tab. Use stable namespaced keys and versioned validated
values; choose a local user-preference store after inspecting existing settings.
Define whether each value belongs to the installation/user, page or individual
table. Apply shared layout preferences consistently on all pages.

Save changes with bounded/debounced writes during use, plus a best-effort final
flush on close. Do not rely exclusively on a close event. Restore preferences
early enough to avoid an obvious default-size flash where the framework permits.
Remember normal window bounds separately from maximized state. A minimized close
must not cause the next launch to open invisibly.

Validate restored geometry against current monitors/work areas and enforce usable
minimum sizes. Clamp or reposition off-screen windows after monitor removal or
resolution changes. Use responsive defaults when saved pane/column dimensions no
longer fit. Invalid, obsolete or corrupt settings fall back safely.

Native mode owns its window geometry. Browser mode can restore in-page sizing but
must not attempt to control the user's browser window. Establish how concurrent
windows/tabs resolve preference writes. Add a Reset layout action with a clear
scope that leaves unrelated application settings intact.

Completion gate: verify native close/relaunch and maximize/restore; changed monitor
layout, corrupt/missing preferences, per-page/table identity, resize write bounds,
browser refresh/restart, concurrent sessions and reset. Inspect desktop and 390px
layouts. Required native-window checks must not be replaced solely by browser tests.

## U2 - Persistent theme selector

Add Light, Dark and System options in a discoverable shared shell or Appearance
settings location. Persist the selected mode across application restarts and apply
it on startup and navigation. System follows OS/browser appearance changes while
the application runs where supported. Distinguish the chosen System mode from its
currently resolved light/dark appearance.

Use shared theme tokens/framework configuration for page backgrounds, navigation,
cards, tables, forms, dialogs, tooltips, validation and focus states. Update Plotly
charts and custom HTML/CSS surfaces when the resolved theme changes, preserving
filters, zoom where practical, selections and unsaved form values. Review map
controls/legends and external map-tile appearance separately; do not assume that
inverting map imagery creates a usable dark map.

Maintain readable contrast and visible keyboard focus. Phase colors, chart series
and quality indicators retain their meaning and accompanying labels across themes.
Use a safe default if preferences are invalid or system appearance cannot be read.
Theme changes must not trigger schedule/database mutations or expensive analytics
recomputation unnecessarily.

Completion gate: verify persistence/relaunch, all three modes, live System changes,
navigation/dialogs, charts and custom surfaces, keyboard selection and invalid
preferences. Inspect representative Dashboard, Activities, Charts, Plan, Seasons
and Settings views in light/dark at desktop and 390px. Record any external surface
limitations explicitly rather than marking them verified.

## Implementation sequence and evidence

1. Discover window APIs, preference storage, adjustable layout controls and theme
   surfaces; document authoritative settings and platform limitations.
2. Implement U1 storage/restore/reset and verify native/browser behavior.
3. Implement U2 selector, shared tokens and chart/custom-surface updates.
4. Record proportionate tests and visual evidence under `reports/ui_preferences/`.
5. Update this plan and roadmap with separate U1/U2 statuses and handoffs.

U1 and U2 may ship independently. Coordinate appearance verification with D1's
timeline and R1's event editors as those features become available. Deployment,
packaging and new custom theme palettes are separately scoped.
