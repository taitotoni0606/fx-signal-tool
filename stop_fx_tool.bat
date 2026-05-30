@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop_fx_tool.ps1"
if errorlevel 1 (
  echo Failed to stop FX tool.
  pause
  exit /b 1
)
echo FX tool stopped.
pause
