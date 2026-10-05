@REM  run_as_admin.bat

@echo off
:: Launches StreamDesk with Administrator privileges (no install step)
:: Terminal closes automatically once the app starts

echo Requesting administrator privileges...
powershell -Command "Start-Process python -ArgumentList '\"%~dp0streamdesk.py\"' -Verb RunAs -WindowStyle Hidden"

timeout /t 2 /nobreak >nul
exit
