# SteelFlow — deployable FastAPI demo

**This is a demo, not production-ready steel-plant software.** It preserves the existing SteelFlow Operations Console interface and uses FastAPI, not Streamlit.

## Preferred host: Render
1. Push the contents of this folder to a private GitHub repository (exclude local SQLite files, credentials, and user data). Do not upload the ZIP itself as the repository root.
2. In Render, create a new **Blueprint** from that repository, or a Python Web Service using the commands below.
3. Set `STEELFLOW_DEMO_PASSWORD` to a strong, unique password in Render's secret environment settings. Do not use the old `SteelFlowDemo!2026` password on a publicly available instance.
4. For a durable demo, provision hosted PostgreSQL and set `DATABASE_URL` to its SQLAlchemy `postgresql+psycopg://...` URL. Without a PostgreSQL database, the default SQLite file is on an ephemeral host filesystem, and demo data may reset on restarts or redeployments.
5. Deploy. Only after hosting confirms a healthy deployment, copy the actual generated HTTPS URL and verify it opens in a separate browser.

Build command: `pip install -r requirements.txt`
Start command: `bash start_public_demo.sh`
Health check: `/api/health`

Demo accounts: `controller`, `yard`, `supervisor`, `melting`, `refining`, `casting`, `rolling`, `finishing`. They all share the strong password you set for this demo. Public shared accounts are suitable **only** for disposable fictional demo data. No real plant data or personal information should be entered.

## Why not Streamlit Community Cloud?
Streamlit Community Cloud expects a Streamlit entrypoint (`streamlit run ...`). SteelFlow currently uses a FastAPI ASGI server serving an interactive HTML/CSS/JS interface. Simply uploading the project to Streamlit Cloud will not host its FastAPI routes. Rewriting it as Streamlit would be a separate project and would alter the current user interface.

## Important limitations
- Web hosting needs a user-controlled hosting account and repository connection; this package itself has not been deployed.
- The database schema's PostgreSQL behavior has not been verified against a live hosted PostgreSQL instance.
- Public demo login is not appropriate for confidential or production data. Implement real user-specific authentication, rate limits, CSRF/cookie hardening where relevant, backups, monitoring and a security review for production.
- This does not validate plant-specific material balances or root-cause diagnosis.
