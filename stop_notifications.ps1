$ErrorActionPreference = "Stop"

$targets = @(Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*notification_monitor.py*"
})

$targets |
    Select-Object -ExpandProperty ProcessId -Unique |
    ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
