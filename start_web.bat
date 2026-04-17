@echo off
chcp 65001 >nul
title cs-Solidarity Web Server
cd /d "%~dp0web"
python -m uvicorn server:app --host 0.0.0.0 --port 11029
pause
