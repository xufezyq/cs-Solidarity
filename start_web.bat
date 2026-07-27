@echo off
chcp 65001 >nul
title cs-Solidarity Web Server - Port 11029
set "PYTHON=%~dp0venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo ERROR: Virtual environment not found: %PYTHON%
    echo Create it with: python -m venv venv
    pause
    exit /b 1
)

cd /d "%~dp0web"
"%PYTHON%" -m uvicorn server:app --host 0.0.0.0 --port 11029
pause
