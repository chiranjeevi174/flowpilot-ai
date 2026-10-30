@echo off
setlocal enabledelayedexpansion

title FlowPilot AI - Startup System
set "PROJECT_ROOT=%~dp0"
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"

:: Check for window mode flag: default is hidden (clean), optional --show-windows or /w
set "WINDOW_MODE=hidden"
if /i "%~1"=="--show-windows" set "WINDOW_MODE=normal"
if /i "%~1"=="/w" set "WINDOW_MODE=normal"
if /i "%~1"=="-w" set "WINDOW_MODE=normal"

echo ========================================================
echo   FlowPilot AI - Development Environment Startup
echo ========================================================
if "%WINDOW_MODE%"=="normal" (
    echo [INFO] Window Mode: Visible external console windows.
) else (
    echo [INFO] Window Mode: Clean background mode [logs saved to .run\logs\].
)
echo.

:: 1. Check required CLI tools in PATH
echo [INFO] Checking required CLI tools in PATH...
where docker >nul 2>&1
if !ERRORLEVEL! neq 0 (
    echo [ERROR] 'docker' command was not found in PATH.
    echo Please install or start Docker Desktop and ensure it is in your PATH.
    exit /b 1
)

where uv >nul 2>&1
if !ERRORLEVEL! neq 0 (
    echo [ERROR] 'uv' command was not found in PATH.
    echo Please install Astral 'uv' - Python package manager - to run backend services.
    exit /b 1
)

where npm >nul 2>&1
if !ERRORLEVEL! neq 0 (
    echo [ERROR] 'npm' command was not found in PATH.
    echo Please install Node.js and npm to run the frontend application.
    exit /b 1
)

:: 2. Check Docker daemon responsiveness
echo [INFO] Verifying Docker Desktop daemon availability...
docker info >nul 2>&1
if !ERRORLEVEL! neq 0 (
    echo [ERROR] Docker daemon is not responding.
    echo Please launch Docker Desktop and wait until the engine is fully running.
    exit /b 1
)
echo [OK] Docker Desktop is available.

:: Create runtime directory for process tracking and logs
if not exist "%PROJECT_ROOT%\.run" mkdir "%PROJECT_ROOT%\.run"
if not exist "%PROJECT_ROOT%\.run\logs" mkdir "%PROJECT_ROOT%\.run\logs"

:: 3. Start PostgreSQL and Redis via infrastructure\compose.yaml
echo.
echo [1/5] Starting infrastructure containers [PostgreSQL and Redis]...
docker compose -f "%PROJECT_ROOT%\infrastructure\compose.yaml" up -d
if !ERRORLEVEL! neq 0 (
    echo [ERROR] Docker compose failed to start infrastructure containers.
    exit /b 1
)

:: Verify infrastructure readiness
echo [INFO] Verifying PostgreSQL [port 5433] and Redis [port 6379]...
set /a DB_ATTEMPTS=0
:CHECK_INFRA
set /a DB_ATTEMPTS+=1
netstat -ano | findstr :5433 | findstr LISTENING >nul 2>&1
set "PG_READY=!ERRORLEVEL!"
if !PG_READY! neq 0 (
    powershell -NoProfile -Command "$c = New-Object System.Net.Sockets.TcpClient; try { $c.Connect('127.0.0.1', 5433); $c.Close(); exit 0 } catch { exit 1 }" >nul 2>&1
    set "PG_READY=!ERRORLEVEL!"
)
netstat -ano | findstr :6379 | findstr LISTENING >nul 2>&1
set "REDIS_READY=!ERRORLEVEL!"
if !REDIS_READY! neq 0 (
    powershell -NoProfile -Command "$c = New-Object System.Net.Sockets.TcpClient; try { $c.Connect('127.0.0.1', 6379); $c.Close(); exit 0 } catch { exit 1 }" >nul 2>&1
    set "REDIS_READY=!ERRORLEVEL!"
)

if !PG_READY! neq 0 goto WAIT_INFRA
if !REDIS_READY! neq 0 goto WAIT_INFRA
echo [OK] PostgreSQL and Redis are listening and ready.
goto CHECK_FASTAPI

:WAIT_INFRA
if !DB_ATTEMPTS! gtr 30 (
    echo [ERROR] Infrastructure services did not become ready within 30 seconds.
    echo Please inspect container logs using: docker compose -f infrastructure\compose.yaml logs
    exit /b 1
)
ping -n 2 127.0.0.1 >nul
goto CHECK_INFRA

:CHECK_FASTAPI
:: 4. Start FastAPI from backend/
echo.
echo [2/5] Checking FastAPI backend service [port 8000]...
netstat -ano | findstr :8000 | findstr LISTENING >nul 2>&1
if !ERRORLEVEL! equ 0 goto FASTAPI_ALREADY_RUNNING
curl.exe -s -o nul http://127.0.0.1:8000/api/v1/health >nul 2>&1
if !ERRORLEVEL! equ 0 goto FASTAPI_ALREADY_RUNNING
goto LAUNCH_FASTAPI

:FASTAPI_ALREADY_RUNNING
echo [INFO] FastAPI is already running on http://127.0.0.1:8000. Skipping duplicate launch.
goto CHECK_WORKER

:LAUNCH_FASTAPI
echo [INFO] Launching FastAPI backend server...
if "%WINDOW_MODE%"=="normal" (
    powershell -NoProfile -Command "$proc = Start-Process -FilePath 'cmd.exe' -ArgumentList @('/k', 'title FlowPilot - FastAPI && cd /d \""%PROJECT_ROOT%\backend\"" && uv run python -m flowpilot.main') -WindowStyle Normal -PassThru; Set-Content -Path '%PROJECT_ROOT%\.run\fastapi.pid' -Value $proc.Id"
) else (
    powershell -NoProfile -Command "$proc = Start-Process -FilePath 'cmd.exe' -ArgumentList @('/c', 'title FlowPilot - FastAPI && cd /d \""%PROJECT_ROOT%\backend\"" && uv run python -m flowpilot.main') -RedirectStandardOutput '%PROJECT_ROOT%\.run\logs\fastapi.log' -RedirectStandardError '%PROJECT_ROOT%\.run\logs\fastapi.err.log' -WindowStyle Hidden -PassThru; Set-Content -Path '%PROJECT_ROOT%\.run\fastapi.pid' -Value $proc.Id"
)

echo [INFO] Waiting for FastAPI to become responsive...
set /a API_ATTEMPTS=0
:WAIT_API
set /a API_ATTEMPTS+=1
curl.exe -s -o nul http://127.0.0.1:8000/api/v1/health >nul 2>&1
if !ERRORLEVEL! equ 0 (
    echo [OK] FastAPI is responsive on http://127.0.0.1:8000.
    goto CHECK_WORKER
)
if !API_ATTEMPTS! gtr 20 (
    echo [WARNING] FastAPI took longer than expected to report healthy. Proceeding...
    goto CHECK_WORKER
)
ping -n 2 127.0.0.1 >nul
goto WAIT_API

:CHECK_WORKER
:: 5. Start Celery Worker (-P solo for Windows compatibility)
echo.
echo [3/5] Checking Celery Worker...
set "WORKER_ALREADY_RUNNING=0"
if exist "%PROJECT_ROOT%\.run\celery_worker.pid" (
    set /p CW_PID=<"%PROJECT_ROOT%\.run\celery_worker.pid"
    if defined CW_PID (
        tasklist /FI "PID eq !CW_PID!" 2>nul | findstr /i "!CW_PID!" >nul && set "WORKER_ALREADY_RUNNING=1"
    )
)
if "!WORKER_ALREADY_RUNNING!"=="0" (
    tasklist /FI "WINDOWTITLE eq FlowPilot - Celery Worker*" 2>nul | findstr /i "cmd.exe" >nul && set "WORKER_ALREADY_RUNNING=1"
)
if "!WORKER_ALREADY_RUNNING!"=="1" (
    echo [INFO] Celery Worker is already running. Skipping duplicate launch.
    goto CHECK_BEAT
)

echo [INFO] Launching Celery Worker with Windows solo pool [-P solo]...
if "%WINDOW_MODE%"=="normal" (
    powershell -NoProfile -Command "$proc = Start-Process -FilePath 'cmd.exe' -ArgumentList @('/k', 'title FlowPilot - Celery Worker && cd /d \""%PROJECT_ROOT%\backend\"" && uv run celery -A flowpilot.workers.celery_app worker --loglevel=info -P solo') -WindowStyle Normal -PassThru; Set-Content -Path '%PROJECT_ROOT%\.run\celery_worker.pid' -Value $proc.Id"
) else (
    powershell -NoProfile -Command "$proc = Start-Process -FilePath 'cmd.exe' -ArgumentList @('/c', 'title FlowPilot - Celery Worker && cd /d \""%PROJECT_ROOT%\backend\"" && uv run celery -A flowpilot.workers.celery_app worker --loglevel=info -P solo') -RedirectStandardOutput '%PROJECT_ROOT%\.run\logs\celery_worker.log' -RedirectStandardError '%PROJECT_ROOT%\.run\logs\celery_worker.err.log' -WindowStyle Hidden -PassThru; Set-Content -Path '%PROJECT_ROOT%\.run\celery_worker.pid' -Value $proc.Id"
)
echo [OK] Celery Worker launched.

:CHECK_BEAT
:: 6. Start Celery Beat
echo.
echo [4/5] Checking Celery Beat scheduler...
set "BEAT_ALREADY_RUNNING=0"
if exist "%PROJECT_ROOT%\.run\celery_beat.pid" (
    set /p CB_PID=<"%PROJECT_ROOT%\.run\celery_beat.pid"
    if defined CB_PID (
        tasklist /FI "PID eq !CB_PID!" 2>nul | findstr /i "!CB_PID!" >nul && set "BEAT_ALREADY_RUNNING=1"
    )
)
if "!BEAT_ALREADY_RUNNING!"=="0" (
    tasklist /FI "WINDOWTITLE eq FlowPilot - Celery Beat*" 2>nul | findstr /i "cmd.exe" >nul && set "BEAT_ALREADY_RUNNING=1"
)
if "!BEAT_ALREADY_RUNNING!"=="1" (
    echo [INFO] Celery Beat is already running. Skipping duplicate launch.
    goto CHECK_FRONTEND
)

echo [INFO] Launching Celery Beat scheduler...
if "%WINDOW_MODE%"=="normal" (
    powershell -NoProfile -Command "$proc = Start-Process -FilePath 'cmd.exe' -ArgumentList @('/k', 'title FlowPilot - Celery Beat && cd /d \""%PROJECT_ROOT%\backend\"" && uv run celery -A flowpilot.workers.celery_app beat --loglevel=info') -WindowStyle Normal -PassThru; Set-Content -Path '%PROJECT_ROOT%\.run\celery_beat.pid' -Value $proc.Id"
) else (
    powershell -NoProfile -Command "$proc = Start-Process -FilePath 'cmd.exe' -ArgumentList @('/c', 'title FlowPilot - Celery Beat && cd /d \""%PROJECT_ROOT%\backend\"" && uv run celery -A flowpilot.workers.celery_app beat --loglevel=info') -RedirectStandardOutput '%PROJECT_ROOT%\.run\logs\celery_beat.log' -RedirectStandardError '%PROJECT_ROOT%\.run\logs\celery_beat.err.log' -WindowStyle Hidden -PassThru; Set-Content -Path '%PROJECT_ROOT%\.run\celery_beat.pid' -Value $proc.Id"
)
echo [OK] Celery Beat launched.

:CHECK_FRONTEND
:: 7. Start Next.js from frontend/
echo.
echo [5/5] Checking Next.js frontend [port 3000]...
netstat -ano | findstr :3000 | findstr LISTENING >nul 2>&1
if !ERRORLEVEL! equ 0 goto FRONTEND_ALREADY_RUNNING
curl.exe -s -o nul http://localhost:3000 >nul 2>&1
if !ERRORLEVEL! equ 0 goto FRONTEND_ALREADY_RUNNING
goto LAUNCH_FRONTEND

:FRONTEND_ALREADY_RUNNING
echo [INFO] Next.js frontend is already running on http://localhost:3000. Skipping duplicate launch.
goto WAIT_FRONTEND_READY

:LAUNCH_FRONTEND
echo [INFO] Launching Next.js frontend development server...
if "%WINDOW_MODE%"=="normal" (
    powershell -NoProfile -Command "$proc = Start-Process -FilePath 'cmd.exe' -ArgumentList @('/k', 'title FlowPilot - Frontend && cd /d \""%PROJECT_ROOT%\frontend\"" && npm run dev') -WindowStyle Normal -PassThru; Set-Content -Path '%PROJECT_ROOT%\.run\frontend.pid' -Value $proc.Id"
) else (
    powershell -NoProfile -Command "$proc = Start-Process -FilePath 'cmd.exe' -ArgumentList @('/c', 'title FlowPilot - Frontend && cd /d \""%PROJECT_ROOT%\frontend\"" && npm run dev') -RedirectStandardOutput '%PROJECT_ROOT%\.run\logs\frontend.log' -RedirectStandardError '%PROJECT_ROOT%\.run\logs\frontend.err.log' -WindowStyle Hidden -PassThru; Set-Content -Path '%PROJECT_ROOT%\.run\frontend.pid' -Value $proc.Id"
)

:WAIT_FRONTEND_READY
:: 8. Wait for Frontend to become reachable and open browser
echo.
echo [INFO] Waiting for Next.js frontend to become reachable on http://localhost:3000...
set /a FE_ATTEMPTS=0
:CHECK_FE
set /a FE_ATTEMPTS+=1
curl.exe -s -o nul http://localhost:3000 >nul 2>&1
if !ERRORLEVEL! equ 0 (
    echo [OK] Frontend is online and responding!
    goto READY
)
if !FE_ATTEMPTS! gtr 45 (
    echo [WARNING] Frontend did not respond on http://localhost:3000 within 45 seconds.
    echo Please inspect .run\logs\frontend.err.log for compile or runtime errors.
    goto READY
)
ping -n 2 127.0.0.1 >nul
goto CHECK_FE

:READY
echo.
echo ========================================================
echo   FlowPilot AI is running and ready for development!
echo ========================================================
echo   Frontend UI:      http://localhost:3000
echo   FastAPI Swagger:  http://127.0.0.1:8000/docs
echo   API Health:       http://127.0.0.1:8000/api/v1/health
echo   PostgreSQL:       127.0.0.1:5433 [flowpilot]
echo   Redis:            127.0.0.1:6379 [db 0]
echo.
if "%WINDOW_MODE%"=="hidden" (
    echo   Process Logs:
    echo     FastAPI:        .run\logs\fastapi.log
    echo     Celery Worker:  .run\logs\celery_worker.log
    echo     Celery Beat:    .run\logs\celery_beat.log
    echo     Frontend:       .run\logs\frontend.log
)
echo ========================================================
echo   To stop all services and containers safely:
echo     stop-dev.cmd
echo ========================================================
echo.
echo Opening http://localhost:3000 in your default browser...
start http://localhost:3000

endlocal
exit /b 0
