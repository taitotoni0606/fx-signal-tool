$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$script = Join-Path $PSScriptRoot "notification_monitor.py"
$out = Join-Path $PSScriptRoot "notification_monitor.out.log"
$err = Join-Path $PSScriptRoot "notification_monitor.err.log"

if (-not (Test-Path -LiteralPath $python)) {
    & (Join-Path $PSScriptRoot "setup_environment.ps1")
}

$running = @(Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*notification_monitor.py*"
})

if ($running.Count -eq 0) {
    Start-Process -FilePath $python -ArgumentList @($script) -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err
}

& (Join-Path $PSScriptRoot "open_fx_tool.ps1")
