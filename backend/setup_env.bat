@echo off
REM Create Python virtual environment and install dependencies

setlocal enabledelayedexpansion

REM Get the directory where this batch file is located
set PROJECT_ROOT=%~dp0
set PROJECT_ROOT=%PROJECT_ROOT:~0,-1%

set PYTHON_BIN=%PROJECT_ROOT%\backend_env\Scripts\python.exe

echo.
echo 🐍 Setting up Python virtual environment...
echo.

REM Check if venv exists
if exist "%PROJECT_ROOT%\backend_env" (
    echo ✅ Virtual environment already exists
) else (
    echo 📦 Creating virtual environment...
    python -m venv "%PROJECT_ROOT%\backend_env"
    if %ERRORLEVEL% neq 0 (
        echo ❌ Failed to create virtual environment
        pause
        exit /b 1
    )
)

REM Activate and upgrade pip
echo 📦 Upgrading pip...
call "%PROJECT_ROOT%\backend_env\Scripts\activate.bat"
%PYTHON_BIN% -m pip install --upgrade pip setuptools wheel

REM Install requirements
echo 📦 Installing dependencies from requirements.txt...
%PYTHON_BIN% -m pip install -r "%PROJECT_ROOT%\requirements.txt"

if %ERRORLEVEL% neq 0 (
    echo ❌ Failed to install dependencies
    pause
    exit /b 1
)

echo.
echo ✅ Setup complete!
echo.
echo Next steps:
echo 1. Run: start_server.bat
echo 2. Access: http://localhost:8000
echo.
pause
