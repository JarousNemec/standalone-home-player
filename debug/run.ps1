# Spustí aplikaci v debug režimu na Windows.
# Spusť z rootu projektu:   .\debug\run.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$py = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $py)) {
    Write-Host "Nejdřív spusť .\debug\setup.ps1" -ForegroundColor Red
    exit 1
}

& $py (Join-Path $root "debug\run.py")
