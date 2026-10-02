# Recreates the project environment from scratch, using the correct interpreter.
# Safe to run any time - it never installs into the global Python.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$VENV = Join-Path $PSScriptRoot ".venv"
$PY   = Join-Path $VENV "Scripts\python.exe"

if (-not (Test-Path $PY)) {
    Write-Host "Creating virtual environment in .venv ..." -ForegroundColor Cyan
    python -m venv .venv
    if (-not (Test-Path $PY)) { throw "Failed to create venv at $VENV" }
}

Write-Host "Installing dependencies from requirements.txt ..." -ForegroundColor Cyan
& $PY -m pip install --upgrade pip --quiet
& $PY -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

Write-Host "Applying migrations ..." -ForegroundColor Cyan
& $PY manage.py migrate

Write-Host "Verifying Django configuration ..." -ForegroundColor Cyan
& $PY manage.py check
if ($LASTEXITCODE -ne 0) { throw "manage.py check failed" }

Write-Host ""
& $PY -c "import sys, django; print('Interpreter :', sys.executable); print('Django      :', django.get_version())"
Write-Host ""
Write-Host "Setup complete. Start the server with:" -ForegroundColor Green
Write-Host "  .\start_server.bat" -ForegroundColor Green
Write-Host "  (or) .\.venv\Scripts\python.exe manage.py runserver" -ForegroundColor Green
Write-Host ""
Write-Host "Need an admin login? Run:" -ForegroundColor Green
Write-Host "  .\.venv\Scripts\python.exe manage.py createsuperuser" -ForegroundColor Green