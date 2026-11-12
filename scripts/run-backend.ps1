<#
.SYNOPSIS
    Starts PostgreSQL (if needed), applies migrations and runs the API on http://localhost:8000
#>
. "$PSScriptRoot\env.ps1"
& "$PSScriptRoot\pg-start.ps1"
if ($LASTEXITCODE -ne 0) { exit 1 }

Set-Location (Join-Path (Split-Path -Parent $PSScriptRoot) 'backend')
& .\.venv\Scripts\alembic.exe upgrade head
if ($LASTEXITCODE -ne 0) { exit 1 }
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
