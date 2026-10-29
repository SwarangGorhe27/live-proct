@echo off
REM Start Live Proctoring Backend on Windows
REM This script activates the virtual environment and starts the FastAPI server

cd /d "%~dp0"
cd backend

echo ========================================
echo Live Proctoring - Backend Startup
echo ========================================
echo.

REM Check if virtual environment exists
if not exist "backend_env" (
    echo Creating virtual environment...
    python -m venv backend_env
)

REM Activate virtual environment
call backend_env\Scripts\activate.bat

REM Check if requirements are installed
pip show uvicorn > nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo Installing dependencies...
    pip install -r requirements.txt
)

REM Start the server
echo.
echo Starting FastAPI server on http://127.0.0.1:8000
echo Press Ctrl+C to stop
echo.

python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

pause
