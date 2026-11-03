# SteelFlow v1.0 — End-to-End Manufacturing Tracking Demonstration

**Status:** Complete runnable **training / demonstration application** covering six material-flow stages. **NOT** a commissioned production MES, not calibrated against a steel factory, not suitable for plant-control use.

SteelFlow brings receiving, inventory, handovers, processing, material balances, batch genealogy and controller investigations into one role-based web interface.

## Run with one double-click on Windows

1. Install **Python 3.11 or later** and ensure the `py` command works.
2. Extract this project ZIP to a folder such as `C:\SteelFlow`.
3. Double-click **`START_LOCAL_WINDOWS.bat`**. It creates a virtual environment, installs dependencies (Internet required on first run), prepares demo accounts and sample manufacturing data, then launches the server.
4. Open **http://127.0.0.1:8000** on the same computer.
5. Sign in as `controller` with local **training-only** password `SteelFlowDemo!2026`. To record new operations, switch to the relevant operator account.

**Do not publish this demo online with default accounts.** It is intended for local exploration. If port 8000 is occupied, stop the other server before launching.

On Linux/macOS (developer setup):

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export STEELFLOW_DEMO_MODE=1
python -m app.seed_demo
python -m app.seed_showcase
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The sample dataset is **idempotent**: restarting the Windows script does not insert the example repeatedly. The local SQLite database file is `steelflow-dev.db`. To start from a clean slate, stop the server and rename/move this database file before restarting; your existing demo records will be lost if you delete it.

### Demo accounts

| Login name | What the role does |
|---|---|
| `yard` | Record truck deliveries, reserve material and dispatch measured weights |
| `supervisor` | Approve/hold/reject delivery receipts; inspect inventory balances |
| `melting` | Confirm incoming material and record melting production |
| `refining` | Record refining runs |
| `casting` | Record casting runs |
| `rolling` | Record rolling runs |
| `finishing` | Record finishing runs |
| `controller` | Monitor the full factory, review material discrepancies and record investigations |

All accounts use the local demo password `SteelFlowDemo!2026` unless changed via `STEELFLOW_DEMO_PASSWORD` **before seeding** a new database. These credentials must never be used in a deployed plant system.

## Six-stage system implemented

1. **Raw material receiving**: weighbridge gross/tare/net, approval, lot identity and on-hand inventory.
2. **Steel melting**: separately weighed transfer receipt; consumes real receiving-stock lot; creates liquid steel and documented secondary output batches.
3. **Ladle refining**: consumes actual liquid-steel output batch and records refined steel and secondary material.
4. **Continuous casting**: consumes refined steel, records billets and crop/reject output.
5. **Rolling mill**: consumes billets, records rolled product, scale, crop scrap.
6. **Quality & finishing**: consumes rolled product, records finished steel and rejects.

The six stages are represented as **one simplified reference route**. Physical plant routes vary; realistic steelmaking requires plant-specific chemistry, equipment boundaries, time windows and uncertainty calibration.

## Controller capabilities

- **Factory flow:** interactive stage cards with run counts, throughput totals and unresolved process discrepancies.
- **Production records:** recorded input/output lines, original evidence references, operator, stage, time and unexplained balance.
- **Genealogy:** trace a finished product batch through its recorded parent input batches back to the original material lot. The trace represents *process contribution*, not atom-level identity.
- **Balance checks:** yard/transfer ledger versus inventory; quantities consumed in manufacturing are included correctly in stock reconciliation.
- **Investigations:** record controller review of both transfer discrepancies and unexplained production-stage balances. Review does not overwrite source measurements.
- **Reports:** download production runs and material-transfer summaries as CSV. CSV cells are escaped against spreadsheet-formula injection.

## Useful sample scenario

The sample dataset creates two supplier receipts and transfers, an example all-the-way-through production chain and one deliberately incomplete melting balance:

- 10,000 kg consumed at melting → 9,000 kg main steel output + 900 kg slag + 100 kg dust
- Refining: 9,000 → 8,900 steel + 100 slag
- Casting: 8,900 → 8,800 billets + 100 crop scrap
- Rolling: 8,800 → 8,540 rolled steel + 150 scrap + 100 scale + **10 kg unaccounted difference**
- Finishing: 8,540 → 8,450 finished steel + 90 reject
- Separate melting example: 5,000 → 4,400 liquid steel + 450 slag + **150 kg unexplained difference**

**Note:** The rolling example intentionally includes a 10 kg discrepancy, so the factory map displays **two** process-balance cases. These are examples for practicing investigations, **not verified losses**.

## Test / development commands

```bash
pip install -r requirements-dev.txt
pytest -q
STEELFLOW_CHROMIUM_PATH=/usr/bin/chromium PYTHONPATH=. python tests/browser_smoke.py
STEELFLOW_CHROMIUM_PATH=/usr/bin/chromium PYTHONPATH=. python tests/browser_manufacturing.py
```

Browser tests use actual FastAPI TestClient responses routed into Chromium without exposing a localhost HTTP service (which was restricted in the development environment). All tests work on temporary databases and do not modify your local demo data.

## Technology and architecture

- FastAPI + Python; SQLAlchemy ORM with decimal mass quantities in kilograms.
- PostgreSQL-compatible relational models, with SQLite as tested local demo database.
- Responsive HTML/CSS/vanilla JS with in-app forms, no external CDN.
- API permission checks by role; per-stage operators cannot submit runs for other stages.
- Atomic stock deduction, unique lot/transfer IDs, recorded movement events and audit trail.
- Local Docker/PostgreSQL configuration inherited from Step 6 is supplied but **live PostgreSQL execution has not been verified** in this environment.
- FastAPI API reference at `http://127.0.0.1:8000/docs` when running locally.

## Scope limits — read before evaluating as an industrial product

This is a **complete six-stage interactive demonstration**, not a production-ready factory deployment. Gaps include: real physical material conversion/chemistry validation, moisture/gas flows/energy accounting, uncertainty-based tolerances, realistic grade/heat constraints, dynamic route editing and all 60–70 plant areas, comprehensive WIP/shift accounting, sensor/PLC/OPC UA/ERP integration, machine identity and calibration, dedicated quality-management workflows, operational load/performance testing, verified PostgreSQL migration of a long-lived database, security audit, full operator UX field study, backup/recovery and industrial deployment approval.

**A process residual only means a recorded imbalance.** It does not establish that material was physically lost, or that a particular employee/stage caused it.

## Where to look in the source

- `app/main.py`: receiving, transfers, inventory and controller APIs.
- `app/manufacturing.py`: run ledger, produced batches, genealogy, stage rules, process alerts.
- `app/reconciliation.py`: inventory and accounting balance checks.
- `app/seed_demo.py`: demo accounts and plant departments.
- `app/seed_showcase.py`: six-stage example production chain and anomaly.
- `web/app.js`, `web/styles.css`: operator and controller UI.
- `tests/test_manufacturing.py`: complete production chain and negative tests.
- `tests/browser_manufacturing.py`: connected browser and mobile verification.
- `docs/PROJECT_STATUS.md`: evidence and limitations.

**Do not put this system in a factory before plant engineering, IT/OT and security teams verify its assumptions and controls.**

## Interface refresh — Operations Console v2

The design has been updated with a restrained industrial control-room aesthetic, clearer action hierarchy and a connected process route. The factory screen now supports **All runs / Needs review** filtering. See `REDESIGN_NOTES.md` for details and verification boundaries.
