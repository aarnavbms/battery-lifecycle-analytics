@echo off
REM Battery Lifecycle Analytics: start the dashboard (run from Anaconda Prompt or any prompt with Python)
cd /d "%~dp0"
if not exist results\summary.json (
  echo Building results first...
  python -m batterylife run --fast
)
echo Opening http://127.0.0.1:8050  (press Ctrl+C here to stop)
start "" http://127.0.0.1:8050
python dashboard\app.py
pause
