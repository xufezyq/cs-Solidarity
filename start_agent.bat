@echo off
chcp 65001 >nul
title cs-Solidarity Agent

cd /d "%~dp0"

REM Check if virtualenv exists
if exist "venv\Scripts\activate.bat" (
    echo Activating virtualenv...
    call venv\Scripts\activate.bat
) else (
    echo Virtualenv not found, using system Python
)

REM Load environment variables from .env file
if exist ".env" (
    echo Loading environment variables from .env...
    for /f "delims== tokens=1,2" %%a in (.env) do set "%%a=%%b"
) else (
    echo ERROR: .env file not found!
    echo Please create a .env file with the following content:
    echo SERVER=ws://YOUR_SERVER:PORT/ws/agent
    echo TOKEN=YOUR_TOKEN
    pause
    exit /b 1
)

REM Check if required variables are set
if not defined SERVER (
    echo ERROR: SERVER is not set in .env file
    pause
    exit /b 1
)

if not defined TOKEN (
    echo ERROR: TOKEN is not set in .env file
    pause
    exit /b 1
)

python -m agent.client --server "%SERVER%" --token "%TOKEN%" --root "%~dp0."
pause
