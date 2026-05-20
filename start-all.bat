@echo off
title PredictOps - Start All
echo.
echo Starting ML API on http://127.0.0.1:8000
echo Starting n8n on http://127.0.0.1:5678
echo.
echo KEEP BOTH WINDOWS OPEN!
echo.
start "PredictOps ML API" cmd /k "cd /d %~dp0ml-service && call .venv\Scripts\activate.bat && uvicorn main:app --host 0.0.0.0 --port 8000"
timeout /t 5 /nobreak >nul
start "PredictOps n8n" cmd /k "set N8N_DIAGNOSTICS_ENABLED=false && n8n start"
echo.
echo Open in browser:
echo   http://127.0.0.1:8000/health
echo   http://127.0.0.1:5678
echo.
pause
