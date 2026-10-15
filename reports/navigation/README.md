# Navigation hide/show — 2026-10-14

The shared navigation is visible beside desktop pages above the 1024px drawer
breakpoint. Hiding it expands the available page area. The labeled Menu button
toggles navigation; the drawer's close arrow hides it. Smaller screens start
closed and use an overlay. All routes retain the shared shell and selected-year
links. The Menu button exposes the drawer it controls and its expanded state.

15 distinct checks pass: two desktop/390px navigation browser cases, four
existing Plan/Dashboard browser cases and nine Help/Browse/Dashboard UI cases.
Checks exercise initial state, mouse toggle, drawer close, keyboard activation,
route changes, expanded-state accessibility, no horizontal page overflow and
no browser errors/application tracebacks. Screenshots in [evidence](evidence/)
were inspected. The shared screenshot helper now measures available page width
after the docked drawer's padding instead of requiring every page to occupy the
entire viewport. A Browse UI check now selects its button by type to avoid an
ambiguous descriptive label.

No database changes or installer build. Restart the source app to load the
shared-shell change:

    .\.venv\Scripts\python.exe -m garmin_data_hub.ui_nicegui.app --port 8091
