@echo off
cd /d "%~dp0ml-service"
if not exist .venv (
  python -m venv .venv
  call .venv\Scripts\activate.bat
  pip install -r requirements.txt
) else (
  call .venv\Scripts\activate.bat
)
echo.
echo PredictOps ML API
echo   Health: http://127.0.0.1:8000/health
echo   Docs:   http://127.0.0.1:8000/docs
echo.
echo Use 127.0.0.1 in n8n HTTP nodes (not localhost).
echo.
uvicorn main:app --host 0.0.0.0 --port 8000
