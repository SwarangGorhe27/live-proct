@echo off
REM Live Proctoring Backend - Production Startup Script (Windows)

setlocal enabledelayedexpansion

REM Get the directory where this batch file is located
set PROJECT_ROOT=%~dp0
set PROJECT_ROOT=%PROJECT_ROOT:~0,-1%

REM Set Python path
set PYTHON_BIN=%PROJECT_ROOT%\backend_env\Scripts\python.exe

REM Set log file path
set LOG_FILE=%TEMP%\proctoring_server.log

echo.
echo 🚀 Starting Live Proctoring Backend...
echo Project: %PROJECT_ROOT%
echo Log: %LOG_FILE%
echo.

REM Kill any existing process
taskkill /F /IM python.exe /FI "WINDOWTITLE eq*uvicorn*" 2>nul || true

REM Start new server
cd /d "%PROJECT_ROOT%"
%PYTHON_BIN% -m uvicorn app.main:app ^
  --host 0.0.0.0 ^
  --port 8000 ^
  --reload >> %LOG_FILE% 2>&1

if %ERRORLEVEL% neq 0 (
    echo.
    echo ❌ Error starting server. Check log: %LOG_FILE%
    pause
    exit /b 1
)

echo.
echo ✅ Server started successfully!
echo Server running on http://0.0.0.0:8000
echo Press Ctrl+C to stop
pause
