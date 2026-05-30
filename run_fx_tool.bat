@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0open_fx_tool.ps1"
if errorlevel 1 (
  echo Failed to open FX tool.
  pause
  exit /b 1
)
exit /b 0
