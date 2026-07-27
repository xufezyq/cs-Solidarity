@echo off
chcp 65001 >nul
title cs-Solidarity Web Server - Port 11029
set "ROOT=%~dp0"
set "PYTHON=%ROOT%venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo Creating local Python virtual environment...
    py -3 -m venv "%ROOT%venv" >nul 2>&1
    if not exist "%PYTHON%" python -m venv "%ROOT%venv" >nul 2>&1
    if not exist "%PYTHON%" (
        echo ERROR: Python 3 was not found.
        echo Install Python 3.12 or later, then run this script again.
        pause
        exit /b 1
    )
    echo Installing Python dependencies...
    "%PYTHON%" -m pip install -r "%ROOT%requirements.txt"
    if errorlevel 1 (
        echo ERROR: Failed to install Python dependencies.
        pause
        exit /b 1
    )
)

cd /d "%ROOT%web"
"%PYTHON%" -m uvicorn server:app --host 0.0.0.0 --port 11029
pause
