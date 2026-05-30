$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

$url = "http://localhost:8501"
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$port = 8501

if (-not (Test-Path -LiteralPath $python)) {
    & (Join-Path $PSScriptRoot "setup_environment.ps1")
}

function Get-OwnServerParents {
    @(Get-CimInstance Win32_Process | Where-Object {
        $_.ExecutablePath -eq $python -and
        $_.CommandLine -like "*streamlit run app.py*" -and
        $_.CommandLine -like "*--server.port $port*"
    })
}

function Test-PortOpen {
    try {
        return @(
            Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        ).Count -gt 0
    } catch {
        return $false
    }
}

function Stop-PortOwner {
    try {
        $listeners = @(
            Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        )
        foreach ($listener in $listeners) {
            Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
        }
    } catch {
        return
    }
}

$ownServerParents = Get-OwnServerParents
$portOpen = Test-PortOpen

if ($ownServerParents.Count -eq 0 -or -not $portOpen) {
    Stop-PortOwner
    $args = @(
        "-m",
        "streamlit",
        "run",
        "app.py",
        "--server.headless",
        "true",
        "--server.port",
        "$port",
        "--browser.gatherUsageStats",
        "false"
    )
    Start-Process -FilePath $python -ArgumentList $args -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
    Start-Sleep -Seconds 5
}

Start-Process $url
