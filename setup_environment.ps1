$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

$python = Join-Path $env:LocalAppData "Programs\Python\Python312\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    Write-Host "Python 3.12 was not found."
    Write-Host "Install it with this free command:"
    Write-Host "winget install --id Python.Python.3.12 -e --source winget --scope user"
    exit 1
}

& $python -m venv ".venv"
& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -r "requirements.txt"
