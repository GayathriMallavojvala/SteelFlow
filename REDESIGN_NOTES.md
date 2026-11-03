# SteelFlow Operations Console — interface redesign (v2)

This package upgrades the actual functional web client of SteelFlow v1. The backend, role restrictions, material accounting, genealogy and APIs remain unchanged.

## Design strategy

- Remove the bright teal/navy hero gradients, floating decorative circles and pill-shaped card aesthetic.
- Use a charcoal/forest palette, more restrained surface hierarchy, fine borders and compact operational tables.
- Expose operations and exceptions before decorative marketing copy.
- Add a connected, horizontally scrollable six-stage route with separate indicators for normal and open balances. Select a processing stage to inspect actual recorded runs.
- Add working **All runs / Needs review** filtering to the production list in Factory Flow.
- Preserve receipt, inspection, inventory, transfer, production, discrepancy, audit and export workflows.
- Retain readable units (kg and tonnes), role-specific menus, validation messages, and training-environment warnings.
- Responsive layout: on mobile the process route scrolls horizontally instead of being squeezed to illegible cards.

## How to run

On Windows, extract the ZIP and double-click `START_LOCAL_WINDOWS.bat`, then visit http://127.0.0.1:8000. Use demo account `controller`, password `SteelFlowDemo!2026`. Other demo role accounts are in the README. Keep the app local; these credentials are not suitable for public deployment.

## Verification

- `pytest -q` — 18 backend tests.
- `tests/browser_smoke.py` — end-to-end receiving, approval, dispatch, receipt, controller investigation, mobile.
- `tests/browser_manufacturing.py` — manufacturing chain views, operator production entry and responsive layout.
- SQLite-backed simulation; PostgreSQL and live factory integration remain unverified.

UI code is `web/console-v2.css`, `web/styles.css`, and `web/app.js`.
