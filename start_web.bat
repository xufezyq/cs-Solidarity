@echo off
chcp 65001 >nul
title cs-Solidarity Web Server - Port 11029
set "ROOT=%~dp0"
set "PYTHON=%ROOT%venv\Scripts\python.exe"
set "WEB_DEPS_MARKER=%ROOT%venv\.web-deps-installed"

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
)

if not exist "%WEB_DEPS_MARKER%" (
    echo Installing Python dependencies...
    "%PYTHON%" -m pip install -r "%ROOT%web\requirements.txt"
    if errorlevel 1 (
        echo ERROR: Failed to install Python dependencies.
        pause
        exit /b 1
    )
    type nul > "%WEB_DEPS_MARKER%"
)

cd /d "%ROOT%web"
"%PYTHON%" -m uvicorn server:app --host 0.0.0.0 --port 11029
pause
