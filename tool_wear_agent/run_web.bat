@echo off
cd /d %~dp0
if "%TWA_PORT%"=="" set TWA_PORT=8001

where py >nul 2>nul
if %errorlevel%==0 (
    py -m uvicorn api:app --host 0.0.0.0 --port %TWA_PORT%
) else (
    python -m uvicorn api:app --host 0.0.0.0 --port %TWA_PORT%
)
