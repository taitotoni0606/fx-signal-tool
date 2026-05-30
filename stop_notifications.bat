@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop_notifications.ps1"
if errorlevel 1 (
  echo Failed to stop notifications.
  pause
  exit /b 1
)
echo Notifications stopped.
pause
