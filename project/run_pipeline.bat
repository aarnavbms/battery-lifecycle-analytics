@echo off
REM Run the full pipeline (about 5 minutes). Add --fast to reuse saved model results.
cd /d "%~dp0"
python -m batterylife run %*
python -m batterylife verify
pause
