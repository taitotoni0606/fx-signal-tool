@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_environment.ps1"
if errorlevel 1 (
  echo Setup failed.
  pause
  exit /b 1
)
echo Setup complete.
pause
