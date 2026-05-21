@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
set "ROOT=%cd%"
set NODE_EXTRA_CA_CERTS=

where npm >nul 2>nul
if errorlevel 1 (
  echo [setup-web] ERROR: npm not found. Install Node.js LTS from https://nodejs.org/
  echo            Then re-run:  scripts\setup-web.bat
  exit /b 1
)

set "CA_BUNDLE=%ROOT%\ca-bundle.crt"

echo [setup-web] Repository root: %ROOT%
echo [setup-web] Optional corp CA ^(retry only if default npm TLS fails^):
echo           %CA_BUNDLE%
cd /d "%ROOT%\web"
echo [setup-web] npm install + npm run build ...

REM Default trust store first. CORP/MITM: second attempt uses ca-bundle.crt if present.

call npm install --no-fund --no-audit
if errorlevel 1 (
  if exist "%CA_BUNDLE%" (
    echo.
    echo [setup-web] Default npm TLS failed - retrying with repo-root ca-bundle.crt ...
    set "NODE_EXTRA_CA_CERTS=%CA_BUNDLE%"
    call npm install --no-fund --no-audit --cafile="%CA_BUNDLE%"
  )
)
if errorlevel 1 (
  echo.
  echo [setup-web] npm install failed.
  echo            Behind a corp proxy ^(SELF_SIGNED_CERT_IN_CHAIN^): place PEM as  %CA_BUNDLE%
  echo            Docs: docs\multimode.md ^(npm TLS^).
  exit /b 1
)

call npm run build
if errorlevel 1 exit /b 1

echo.
echo [setup-web] OK - web\dist is ready. Start the API: scripts\run-api.bat  then open http://127.0.0.1:8080/
exit /b 0
