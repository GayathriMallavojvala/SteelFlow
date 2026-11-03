@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
 echo Run START_LOCAL_WINDOWS.bat first to install dependencies.
 pause
 exit /b 1
)
set STEELFLOW_DEMO_MODE=1
.venv\Scripts\python.exe -m app.seed_showcase
if errorlevel 1 (echo Sample data setup failed.) else (echo Sample data is ready. Refresh the browser.)
pause
