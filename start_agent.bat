@echo off
chcp 65001 >nul
title cs-Solidarity Agent - WebSocket Client

cd /d "%~dp0"
set "ROOT=%~dp0"
set "PYTHON=%ROOT%venv-agent\Scripts\python.exe"
set "AGENT_DEPS_MARKER=%ROOT%venv-agent\.agent-deps-installed"

REM The CS2 PWA signer bundled with the Agent requires CPython 3.12.
REM Keep its environment separate from the lightweight Web environment.
if not exist "%PYTHON%" (
    echo Creating Agent Python 3.12 virtual environment...
    py -3.12 -m venv "%ROOT%venv-agent"
    if errorlevel 1 (
        echo ERROR: Python 3.12 is required for the Agent CS2 video signer.
        echo Install Python 3.12 and run this script again.
        pause
        exit /b 1
    )
)

if not exist "%PYTHON%" (
    echo ERROR: Failed to create Agent virtual environment.
    pause
    exit /b 1
)

if not exist "%AGENT_DEPS_MARKER%" (
    echo Installing Agent Python dependencies...
    "%PYTHON%" -m pip install -r "%ROOT%requirements.txt"
    if errorlevel 1 (
        echo ERROR: Failed to install Agent Python dependencies.
        pause
        exit /b 1
    )
    type nul > "%AGENT_DEPS_MARKER%"
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

"%PYTHON%" -m agent.client --server "%SERVER%" --token "%TOKEN%" --root "%ROOT%."
pause
