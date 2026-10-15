# Race browsing verification — October 14, 2026

The user requested a race-website browsing page and chose in-app viewing when
possible with a regular-browser fallback. Browse races now appears in navigation.
No installer build, live-user database migration/write, commit, push or deployment
was performed. Bookmark writes and browser scenarios used isolated synthetic data.

## Behavior

Starter bookmarks use Running in the USA's official
[upcoming races](https://www.runningintheusa.com/race/list) and
[state directory](https://www.runningintheusa.com/race/find-by-state/).
Opening the page neither loads an external website nor stores defaults.
Selecting a bookmark or address starts the embedded page. Existing third-party
frame restrictions still apply. Open in browser always remains available after
selection and uses the visible address; cross-origin site navigation is not
misrepresented as a synchronized address bar. Reload start page recreates the
frame at its start address; Close website removes it.

Names and URLs are saved only on an explicit bookmark action in existing
app_settings storage. Removing/updating bookmarks affects this one setting and
uses a write transaction that rereads the latest list. Invalid saved data remains
visible as an error until an explicit starter-list restore. Events navigation
retains the selected yearly plan. No race details are scraped or inserted.

URLs accept HTTPS public hostnames, with optional filters/fragments, and normalize
scheme/host. Credential-bearing URLs, non-HTTPS protocols, literal IPs, common
alternative numeric IP forms, local hostname forms, custom ports, controls and
backslashes are rejected before opening. This is syntactic URL validation, not a
claim about arbitrary DNS resolution. There is no server-side fetch or proxy.
Iframe URL/ARIA attributes are structured properties, names use text rendering,
and no URL/name is interpolated into raw HTML. The frame omits top navigation and
uses no-referrer. Local app host/origin and anti-embedding headers remain intact.

The OS browser fallback runs only after an explicit user action. Known blocked
Running in the USA bookmarks and Browse actions for its addresses request the
browser directly; other sites retain their embedded view and manual fallback.
No page-load browser launch, sign-in, registration, cookie extraction, source health data
transmission or workout/event modification is introduced.

## Verification

37 distinct cases passed, excluding overlapping reruns:

- 20 address/bookmark/source cases, including unsafe protocols and local/numeric
  addresses rejected before any browser call, host normalization/filter retention,
  defaults read without writes, explicit preference-only mutations, malformed
  settings and explicit recovery.
- One real UI callback case verifying no automatic browser call, explicit valid
  fallback, iframe attributes and rejection of a changed invalid visible address.
- 13 existing local-server security, Help/navigation, Dashboard-copy/focus and
  Recovery callback cases.
- Three browser cases: desktop 1440px, phone 390px and a blocked external frame.

Commands:

    .\.venv\Scripts\python.exe -m pytest tests/test_race_browse.py tests/test_race_browse_ui.py tests/test_nicegui_app_security.py tests/test_help_about_ui.py tests/test_dashboard_plan_copy.py tests/test_dashboard_focus_ui.py tests/test_recovery_readiness_ui.py -q -p no:cacheprovider --tb=short
    # 34 passed in 4.12s

    $env:GARMIN_TEST_ARTIFACTS = 'reports/race_browse/evidence'
    .\.venv\Scripts\python.exe -m pytest tests/test_race_browse_browser.py -q -p no:cacheprovider --tb=short
    # 3 passed in 16.56s

Browser network fixtures supply synthetic directory content on allowed HTTPS
origins and an explicitly denying CSP/X-Frame-Options response on another origin.
They verify no external request before selection, embedded content, fallback
availability under denied embedding, exact preserved year link, quoted bookmark
names as safe properties, save/reload persistence without duplicate cards,
frame close, invalid-address rejection and unchanged plan hashes. Page-level
overflow, page-error and unexpected application-traceback checks pass.
Desktop bookmarks, phone embedded content and phone blocked-site fallback in
[evidence](evidence) were visually inspected. Compilation and whitespace checks pass.

The initial directory verification used official search results; direct fetch
returned 403 and the initial header probe was unavailable. The follow-up below
confirmed SAMEORIGIN framing restrictions. No anti-framing or access restriction
is bypassed; top-level website contents and the OS browser launch are not replaced
by a proxy.

No personal source database was read or written for this feature. All screenshots
show synthetic content. No failing checks remained.

## Running in the USA framing follow-up

The user's screenshot showed the native webview's failed embedded page. A
read-only request outside the network-restricted sandbox returned status 403
with X-Frame-Options: SAMEORIGIN on the official race-list URL. This independently
confirms framing restrictions rather than assuming every frame failure has
that cause.

Exact runningintheusa.com and www.runningintheusa.com hosts now use the regular
browser on an explicit bookmark/Browse click. No iframe is created for them.
Bookmarks say Open site in browser; a short explanation replaces the failed
view. Reload is disabled without an embedded page. Clear selection dismisses
the explanation and leaves the user's browser alone. Other hosts continue to
embed when allowed, with the original manual fallback. No runtime header-fetch
or proxy was added. Pending launch feedback cannot repopulate a cleared view.

42 final distinct cases passed: 37 service/callback/security/Help/Dashboard/
Recovery cases (4.40 seconds), and five browser cases (22.24 seconds). The
previous overlapping cases are not added again. Commands use the same regression
selection above, now with the two known-host callback success/failure cases and
one exact-host classification case; the browser module adds desktop/390px
known-host handling cases and moves embeddable test content to a neutral fixture
host.

The known-host browser tests record a stubbed OS browser request on both starter
links, verify zero remote iframe requests and unchanged plan hashes, and exercise
Clear selection. Actual user browser windows are not opened during tests.
Source callback cases cover a successful request and a failed opener with copy/
retry guidance. Existing other-host embedding, denied-host manual fallback,
bookmark persistence and address validation still pass.

Desktop/phone replacement messages in [fallback_evidence](fallback_evidence)
were visually inspected. Compilation and whitespace checks pass. No installer,
live-user write, migration, commit, push or deployment occurred.

## Common finders and custom site tiles

Common race-finder tiles now include official
[RunSignup](https://runsignup.com/races),
[UltraSignup](https://ultrasignup.com/events/search.aspx),
[FindMyMarathon](https://www.findmymarathon.com/calendar.php) and
[ACTIVE](https://www.active.com/running/). The separate catalog is read-only,
appears even when an older saved list exists and does not replace, rename or
re-add removed saved bookmarks. Existing Running in the USA starter/saved tiles
continue using their browser handling.

Read-only public response checks returned RunSignup 200 with SAMEORIGIN,
UltraSignup 200 with frame-ancestors restricted to itself/its domain, and ACTIVE
200 with SAMEORIGIN and restricted frame ancestors. These exact root/www hosts
therefore request the regular browser, with a correctly named explanation.
FindMyMarathon's direct check returned 406 without a framing header; its official
calendar was verified through web browsing, but embed compatibility is not
claimed. Its catalog tile prefers the regular browser without falsely claiming
a framing restriction. No runtime remote header request or proxy was introduced.

Add your own site opens a standalone name/URL dialog without requiring an
address to be entered above first. Name is optional: a valid address alone uses
its hostname, bounded to the existing name limit. Save site tile creates or
updates one persisted bookmark and refreshes its tile immediately, without
opening/fetching the site. Bare domains normalize to HTTPS. Saved tiles can be
removed; common tiles stay available. The original Save bookmark entry point
prefills the same dialog.

48 final distinct checks passed: 41 source/callback/security/navigation/
Dashboard/Recovery cases in 4.80 seconds and seven browser cases in 34.97 seconds.
The final two new desktop/phone browser cases were rechecked after the URL-only
name option, with their screenshots updated; overlapping cases are counted once.
Commands use the same regression selection above and the full browser module,
with GARMIN_TEST_ARTIFACTS set to reports/race_browse/site_tiles_evidence.

New checks cover exact-host policy classification, URL-only real UI creation,
all common tiles, standalone name/URL entry, invalid local HTTP rejection,
immediate saved-tile appearance, persistence after reload, custom-site embedded
browsing, removal, unchanged plan hashes and no site request on saving.
The phone case leaves the name blank; the desktop case uses an explicit name.
Existing embedded/fallback and bookmark flows still pass.

Verification found a dialog lifecycle bug: Add your own site was inside the
refreshed tile section, which deleted its dialog during save. The dialog now
belongs to a stable root layer, so refresh cannot delete the active callback.
Corrected desktop/phone flows pass with no application tracebacks; failed
attempts are excluded from the count.

Desktop common sites and phone add-site/saved-tile views in
[site_tiles_evidence](site_tiles_evidence) were visually inspected.
Compilation and whitespace checks pass. No installer build, live-user database
write, schema migration, commit, push or deployment occurred.
