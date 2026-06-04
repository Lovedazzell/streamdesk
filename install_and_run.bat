@echo off
setlocal enabledelayedexpansion
title StreamDesk Installer & Launcher

echo.
echo  ========================================
echo   StreamDesk - Installing Dependencies
echo  ========================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.9+ from https://python.org
    pause & exit /b 1
)

:: Install packages
echo [*] Installing Python packages...
python -m pip install --upgrade pip --quiet
python -m pip install --quiet pywin32 pystray Pillow keyboard psutil requests
echo [*] Done installing packages.
echo.

:: Download nircmd if missing
if not exist "%~dp0nircmd.exe" (
    echo [*] Attempting to download nircmd.exe...
    python -c "import urllib.request,zipfile,io,os; r=urllib.request.urlopen('https://www.nirsoft.net/utils/nircmd-x64.zip',timeout=10); z=zipfile.ZipFile(io.BytesIO(r.read())); [z.extract(n,'%~dp0') for n in z.namelist() if n.lower()=='nircmd.exe']" 2>nul
    if exist "%~dp0nircmd.exe" (
        echo [*] nircmd.exe downloaded.
    ) else (
        echo [WARN] Could not download nircmd.exe - volume control unavailable.
    )
)

echo [*] Launching StreamDesk as Administrator...
echo [*] Logs are visible inside the app (Log tab) and in streamdesk.log
echo.

:: Launch with admin rights via PowerShell, then immediately close this terminal
powershell -Command "Start-Process python -ArgumentList '\"%~dp0streamdesk.py\"' -Verb RunAs -WindowStyle Hidden"

:: Give PowerShell a moment to hand off, then exit — no pause, window closes cleanly
timeout /t 2 /nobreak >nul
exit
