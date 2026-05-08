@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0.."

echo [setup] Project root: %cd%

where python >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python not found on PATH. Install Python 3.10+ from python.org and try again.
  exit /b 1
)

if not exist ".venv\" (
  echo [setup] Creating .venv ...
  python -m venv .venv
  if errorlevel 1 exit /b 1
)

set "PY=%cd%\.venv\Scripts\python.exe"
echo [setup] Installing dependencies ...
"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo [setup] Retrying with trusted-hosts ^(corporate proxy^)...
  "%PY%" -m pip install -r requirements.txt --trusted-host pypi.org --trusted-host files.pythonhosted.org
  if errorlevel 1 exit /b 1
)

echo.
echo Done. Next steps:
echo   .venv\Scripts\activate.bat
echo   python -m pytest tests -v
echo   python main.py examples\sample_requests.csv -n 2 -e 1 -c 8
exit /b 0
