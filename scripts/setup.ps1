<#
.SYNOPSIS
    One-time project setup: Python venv, Node packages, database and migrations.
    Safe to run again after pulling new code.
#>
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\env.ps1"
$root = Split-Path -Parent $PSScriptRoot

& "$PSScriptRoot\check-env.ps1"
if ($LASTEXITCODE -ne 0) { throw 'Environment check failed. Fix the problems above first.' }

if (-not (Test-Path "$root\.env")) { throw "Missing $root\.env - copy .env.example to .env and fill it in." }

Write-Host "`nBackend packages" -ForegroundColor Cyan
Set-Location "$root\backend"
if (-not (Test-Path '.venv')) { python -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
& .\.venv\Scripts\python.exe -m pip install --quiet -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }

Write-Host "`nDatabase" -ForegroundColor Cyan
& "$PSScriptRoot\pg-start.ps1"
$settings = @{}
Get-Content "$root\.env" | Where-Object { $_ -match '^\s*([A-Z_]+)=(.*)$' } | ForEach-Object { $settings[$Matches[1]] = $Matches[2] }
$env:PGPASSWORD = $settings['POSTGRES_PASSWORD']
$db = $settings['POSTGRES_DB']
$exists = & psql -U $settings['POSTGRES_USER'] -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$db'"
if (-not $exists) { & psql -U $settings['POSTGRES_USER'] -d postgres -c "CREATE DATABASE $db ENCODING 'UTF8' TEMPLATE template0" }
& .\.venv\Scripts\alembic.exe upgrade head
if ($LASTEXITCODE -ne 0) { throw 'Database migration failed' }

Write-Host "`nFrontend packages" -ForegroundColor Cyan
Set-Location "$root\frontend"
npm ci
if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' }

Write-Host "`nSetup finished. Start the app with scripts\run-backend.ps1 and scripts\run-frontend.ps1." -ForegroundColor Green
