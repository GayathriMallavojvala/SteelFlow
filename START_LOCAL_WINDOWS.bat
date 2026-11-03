@echo off
setlocal
cd /d "%~dp0"
echo =========================================================
echo   SteelFlow - Local Training Application (SQLite)
echo   Six-stage manufacturing demo, NOT a real plant deployment
 echo =========================================================
where py >nul 2>&1
if errorlevel 1 (
  echo Python launcher not found. Install Python 3.11+ from python.org.
  echo Remember to enable Python launcher during setup.
  pause
  exit /b 1
)
if not exist .venv\Scripts\python.exe (
  echo Creating local Python environment...
  py -m venv .venv
  if errorlevel 1 goto :failed
)
call .venv\Scripts\activate.bat
echo Installing required packages (Internet required on first use)...
python -m pip install -r requirements.txt
if errorlevel 1 goto :failed
set STEELFLOW_DEMO_MODE=1
python -m app.seed_demo
if errorlevel 1 goto :failed
echo Preparing the sample factory data...
python -m app.seed_showcase
if errorlevel 1 goto :failed
echo.
echo Open http://127.0.0.1:8000 in your browser.
echo Accounts: yard, supervisor, melting, refining, casting, rolling, finishing, controller.
echo Default local training password: SteelFlowDemo!2026
echo Optional sample data: run LOAD_SAMPLE_DATA_WINDOWS.bat in a second window.
echo Keep this demo LOCAL. Do not expose the default password publicly.
echo Press Ctrl+C to stop.
echo.
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
exit /b 0
:failed
echo SteelFlow could not start. See the error above.
pause
exit /b 1
