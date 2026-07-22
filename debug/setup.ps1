# Nainstaluje závislosti do .venv a zkontroluje prostředí.
# Spusť z rootu projektu:   .\debug\setup.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$py = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $py)) {
    Write-Host "Nenalezen .venv — vytvářím…" -ForegroundColor Yellow
    python -m venv (Join-Path $root ".venv")
}

Write-Host "Instaluji závislosti…" -ForegroundColor Cyan
& $py -m pip install --upgrade pip
& $py -m pip install -r (Join-Path $root "requirements.txt")

Write-Host "`nKontrola prostředí:" -ForegroundColor Cyan
& $py (Join-Path $root "debug\check_env.py")
