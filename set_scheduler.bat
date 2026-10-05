```bat
@echo off
setlocal

title StreamDesk - Configure Windows Auto-Start

echo.
echo ========================================
echo   StreamDesk - Configure Auto-Start
echo ========================================
echo.

:: Get the folder where this BAT file is located
set "SCRIPT_DIR=%~dp0"
set "VBS_FILE=%SCRIPT_DIR%run_hidden.vbs"
set "TASK_NAME=StreamDesk"

echo [1/4] Checking launcher...
if not exist "%VBS_FILE%" (
    echo.
    echo [ERROR] run_hidden.vbs was not found.
    echo Expected:
    echo %VBS_FILE%
    echo.
    pause
    exit /b 1
)

echo [OK] Launcher found.
echo.

:: ------------------------------------------------
:: Delete existing scheduled task
:: ------------------------------------------------
echo [2/4] Removing existing scheduled task...

schtasks /query /tn "%TASK_NAME%" >nul 2>&1

if %errorlevel%==0 (
    echo Existing task found. Deleting...
    schtasks /delete /tn "%TASK_NAME%" /f

    if errorlevel 1 (
        echo.
        echo [ERROR] Could not delete existing task.
        echo Please run this file as Administrator.
        echo.
        pause
        exit /b 1
    )

    echo [OK] Existing task deleted.
) else (
    echo [OK] No existing task found.
)

echo.

:: ------------------------------------------------
:: Create scheduled task
:: ------------------------------------------------
echo [3/4] Creating Windows startup task...

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
"$vbs = Join-Path '%SCRIPT_DIR%' 'run_hidden.vbs'; ^
$action = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument ('\"' + $vbs + '\"'); ^
$trigger = New-ScheduledTaskTrigger -AtLogOn; ^
$trigger.Delay = 'PT30S'; ^
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit 0; ^
Register-ScheduledTask -TaskName '%TASK_NAME%' -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest -Force"

if errorlevel 1 (
    echo.
    echo [ERROR] Failed to create scheduled task.
    echo.
    echo Please run set_scheduler.bat as Administrator.
    echo.
    pause
    exit /b 1
)

echo [OK] Scheduled task created.
echo.

:: ------------------------------------------------
:: Verify task
:: ------------------------------------------------
echo [4/4] Verifying scheduled task...
echo.

schtasks /query /tn "%TASK_NAME%" /v /fo list

if errorlevel 1 (
    echo.
    echo [ERROR] Task was created but could not be verified.
    echo.
    pause
    exit /b 1
)

echo.
echo ========================================
echo   Auto-Start Successfully Configured
echo ========================================
echo.
echo Task Name : %TASK_NAME%
echo Trigger   : Windows Logon
echo Delay     : 30 seconds
echo Launcher  : run_hidden.vbs
echo.
echo StreamDesk will automatically start
echo when you log into Windows.
echo.
echo ========================================
echo.

pause
exit /b 0
```
