$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$port = 8501

$targets = @()
$parents = @(Get-CimInstance Win32_Process | Where-Object {
    $_.ExecutablePath -eq $python -and
    $_.CommandLine -like "*streamlit run app.py*" -and
    $_.CommandLine -like "*--server.port $port*"
})
$targets += $parents

$parentIds = @($parents | ForEach-Object { $_.ProcessId })
if ($parentIds.Count -gt 0) {
    $targets += @(Get-CimInstance Win32_Process | Where-Object {
        $parentIds -contains $_.ParentProcessId
    })
}

try {
    $listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
    foreach ($listener in $listeners) {
        $targets += @(Get-CimInstance Win32_Process | Where-Object {
            $_.ProcessId -eq $listener.OwningProcess
        })
    }
} catch {
}

$targets |
    Where-Object { $_ -ne $null } |
    Select-Object -ExpandProperty ProcessId -Unique |
    ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
