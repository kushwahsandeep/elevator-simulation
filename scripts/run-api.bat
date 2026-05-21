@echo off
REM Always start the FastAPI app from the repository root so "import api" works.
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
  echo ERROR: No .venv found. Run scripts\setup.bat from the repo root first.
  exit /b 1
)

echo [run-api] Project root: %cd%
echo [run-api] Swagger: http://127.0.0.1:8080/docs
if not exist "web\dist\index.html" (
  echo.
  echo WARNING: web\dist\index.html is missing — the React UI will NOT load at http://127.0.0.1:8080/
  echo          You will only see a placeholder page until you build the bundle.
  echo          Fix: run  scripts\setup-web.bat   (requires Node.js and npm^)
  echo.
) else (
  echo [run-api] SPA UI:   http://127.0.0.1:8080/
)
echo [run-api] Tip: use 127.0.0.1 instead of localhost if the browser cannot connect.
if defined ELEVATOR_API_HOST (
  ".venv\Scripts\python.exe" -m uvicorn api.server:app --reload --host %ELEVATOR_API_HOST% --port 8080
) else (
  ".venv\Scripts\python.exe" -m uvicorn api.server:app --reload --host 127.0.0.1 --port 8080
)
