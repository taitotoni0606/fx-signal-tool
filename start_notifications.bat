@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_notifications.ps1"
if errorlevel 1 (
  echo Failed to start notifications.
  pause
  exit /b 1
)
exit /b 0
