# Midar 0.11.0 — Content Operations

## Product work
- Added a dedicated content operations workspace with monthly calendar and list views.
- Added a role-protected, organization-scoped calendar feed using organization-local date boundaries and bounded result sizes.
- Added content status summaries and an unscheduled-draft backlog sourced from the database.
- Added filters by query, status, and platform; filters are applied by the server, with stale asynchronous search responses prevented from replacing newer results.
- Added month navigation and a return-to-today control.
- Made scheduling status explicit: storing a date does not enable background auto-publishing.

## Correctness and engineering
- Normalized rendering and editing of API timestamps that SQLite may serialize without a timezone; the validated workspace time zone is used for display, date input conversion, and server date boundaries. Invalid timezone configuration falls back safely to Asia/Hebron.
- Added calendar boundary, backlog, filter, invalid-timezone fallback, range validation, permission, and static-asset checks.
- Added keyboard focus styling, labels, reduced-motion handling, responsive calendar layout, and light-theme styles.
- Kept database schema unchanged. The calendar endpoint reads existing records only.

## Deliberate limitations
- The list view loads the 250 most recently updated posts through the existing list API; the calendar fetches all events in the selected visible date grid (bounded to 500, with a truncation notice).
- Background scheduling and cross-platform publishing are not enabled by this update. External publishing remains subject to the provider capability and server configuration.
- This is not a claim of WCAG certification or a completed independent security audit. The release uses WCAG 2.2 accessibility targets and OWASP ASVS 5.0.0 as review references.
