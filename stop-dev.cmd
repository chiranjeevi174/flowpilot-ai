@echo off
setlocal enabledelayedexpansion

title FlowPilot AI - Shutdown System
set "PROJECT_ROOT=%~dp0"
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"

echo ========================================================
echo   FlowPilot AI - Development Environment Shutdown
echo ========================================================
echo.

:: 1. Terminate tracked development processes by PID
if not exist "%PROJECT_ROOT%\.run" goto STOP_BY_TITLE

echo [INFO] Stopping tracked development processes...

if exist "%PROJECT_ROOT%\.run\fastapi.pid" (
    set /p F_PID=<"%PROJECT_ROOT%\.run\fastapi.pid"
    if defined F_PID (
        echo   - Stopping FastAPI backend [PID !F_PID!]...
        taskkill /F /T /PID !F_PID! >nul 2>&1
    )
    del /f /q "%PROJECT_ROOT%\.run\fastapi.pid" >nul 2>&1
)

if exist "%PROJECT_ROOT%\.run\celery_worker.pid" (
    set /p CW_PID=<"%PROJECT_ROOT%\.run\celery_worker.pid"
    if defined CW_PID (
        echo   - Stopping Celery Worker [PID !CW_PID!]...
        taskkill /F /T /PID !CW_PID! >nul 2>&1
    )
    del /f /q "%PROJECT_ROOT%\.run\celery_worker.pid" >nul 2>&1
)

if exist "%PROJECT_ROOT%\.run\celery_beat.pid" (
    set /p CB_PID=<"%PROJECT_ROOT%\.run\celery_beat.pid"
    if defined CB_PID (
        echo   - Stopping Celery Beat [PID !CB_PID!]...
        taskkill /F /T /PID !CB_PID! >nul 2>&1
    )
    del /f /q "%PROJECT_ROOT%\.run\celery_beat.pid" >nul 2>&1
)

if exist "%PROJECT_ROOT%\.run\frontend.pid" (
    set /p FE_PID=<"%PROJECT_ROOT%\.run\frontend.pid"
    if defined FE_PID (
        echo   - Stopping Next.js Frontend [PID !FE_PID!]...
        taskkill /F /T /PID !FE_PID! >nul 2>&1
    )
    del /f /q "%PROJECT_ROOT%\.run\frontend.pid" >nul 2>&1
)

:STOP_BY_TITLE
:: 2. Target window titles specific to FlowPilot as a failsafe
echo [INFO] Verifying FlowPilot process windows are closed...
taskkill /FI "WINDOWTITLE eq FlowPilot - FastAPI*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq FlowPilot - Celery Worker*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq FlowPilot - Celery Beat*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq FlowPilot - Frontend*" /T /F >nul 2>&1

:: 3. Safely stop Docker infrastructure containers (preserving volumes and data)
echo.
echo [INFO] Stopping Docker infrastructure containers [PostgreSQL and Redis]...
docker compose -f "%PROJECT_ROOT%\infrastructure\compose.yaml" stop
if !ERRORLEVEL! equ 0 (
    echo [OK] Containers stopped safely. PostgreSQL and Redis volumes preserved.
) else (
    echo [WARNING] Docker compose stop returned a non-zero code or containers were already stopped.
)

:: Clean up .run PID tracking files (preserving logs for debugging)
if exist "%PROJECT_ROOT%\.run\*.pid" (
    del /f /q "%PROJECT_ROOT%\.run\*.pid" >nul 2>&1
)

echo.
echo ========================================================
echo   FlowPilot AI Development Environment Stopped.
echo   All development servers terminated cleanly.
echo   Database and persistence data safely preserved.
echo ========================================================
echo.

endlocal
exit /b 0
