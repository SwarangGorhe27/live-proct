@echo off
REM Start Live Proctoring Frontend on Windows
REM This script installs dependencies (if needed) and starts the React dev server

cd /d "%~dp0"
cd frontend

echo ========================================
echo Live Proctoring - Frontend Startup
echo ========================================
echo.

REM Check if node_modules exists
if not exist "node_modules" (
    echo Installing dependencies...
    call npm install
)

REM Start the frontend
echo.
echo Starting React server on http://localhost:3000
echo Browser will open automatically
echo Press Ctrl+C to stop
echo.

call npm start

pause
