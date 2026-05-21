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
echo [setup] Installing Python dependencies ^(requirements.txt + requirements-api.txt^) ...

REM pip: default TLS first on all machines; ca-bundle.crt and trusted-host retries only after failure (CORP/MITM).

call :pip_upgrade
if errorlevel 1 exit /b 1
call :pip_install_r requirements.txt
if errorlevel 1 exit /b 1
call :pip_install_r requirements-api.txt
if errorlevel 1 exit /b 1

where npm >nul 2>nul
if errorlevel 1 (
  echo.
  echo [setup] npm not on PATH - skipped web UI build. The API still works ^(e.g. /docs^).
  echo           Full UI in the browser: install Node.js LTS, then run  scripts\setup-web.bat
  echo           Then run  scripts\setup-web.bat  once Node is installed ^(produces  web\dist^).
) else (
  echo.
  echo [setup] Building web UI ^(optional^)...
  call "%~dp0setup-web.bat"
  if errorlevel 1 (
    echo.
    echo [setup] Web UI build failed - Python CLI/API are still OK. Fix Node/npm and run  scripts\setup-web.bat
  )
)

echo.
echo Done. Next steps:
echo   Easiest API:  scripts\run-api.bat   ^(works from any folder; uses project root^)
echo   Or: cd /d "%cd%"  then  python -m uvicorn api.server:app --reload --host 127.0.0.1 --port 8080
echo   "%cd%\.venv\Scripts\activate.bat"
echo   python -m pytest tests -v
echo   python main.py examples\sample_requests.csv -n 2 -e 1 -c 8
echo   Then open  http://127.0.0.1:8080/  for the UI ^(if web\dist exists^) or  /docs  for the API.
exit /b 0


:print_ssl_failure
echo.
echo [setup] ERROR: pip could not use PyPI ^(often: SSL CERTIFICATE_VERIFY_FAILED / self-signed certificate in chain^).
echo [setup] Put your TLS CA bundle here, then run setup again:
echo           %cd%\ca-bundle.crt
echo           More options: docs\multimode.md ^(pip and SSL^)
exit /b 0


:pip_upgrade
echo [setup] pip --upgrade pip
"%PY%" -m pip install --retries 0 --upgrade pip
if not errorlevel 1 exit /b 0
if exist "%cd%\ca-bundle.crt" (
  echo [setup] Retrying pip upgrade with repo-root ca-bundle.crt ...
  "%PY%" -m pip install --retries 0 --upgrade pip --cert "%cd%\ca-bundle.crt" --trusted-host pypi.org --trusted-host files.pythonhosted.org
  if not errorlevel 1 exit /b 0
)
echo [setup] Retrying pip upgrade with trusted-hosts only ...
"%PY%" -m pip install --retries 0 --upgrade pip --trusted-host pypi.org --trusted-host files.pythonhosted.org
if errorlevel 1 (
  call :print_ssl_failure
  exit /b 1
)
exit /b 0


:pip_install_r
set "REQ=%~1"
echo [setup] pip install -r %REQ%
"%PY%" -m pip install --retries 0 -r "%REQ%"
if not errorlevel 1 exit /b 0
if exist "%cd%\ca-bundle.crt" (
  echo [setup] Retrying %REQ% with ca-bundle.crt ...
  "%PY%" -m pip install --retries 0 -r "%REQ%" --cert "%cd%\ca-bundle.crt" --trusted-host pypi.org --trusted-host files.pythonhosted.org
  if not errorlevel 1 exit /b 0
)
echo [setup] Retrying %REQ% with trusted-hosts only ...
"%PY%" -m pip install --retries 0 -r "%REQ%" --trusted-host pypi.org --trusted-host files.pythonhosted.org
if errorlevel 1 (
  call :print_ssl_failure
  exit /b 1
)
exit /b 0
