<#
.SYNOPSIS
    Runs the backend and frontend tests. Add -E2E to also run the browser tests.
#>
param([switch]$E2E)

. "$PSScriptRoot\env.ps1"
$root = Split-Path -Parent $PSScriptRoot
$failed = $false

& "$PSScriptRoot\pg-start.ps1"

Write-Host "`nBackend tests (pytest)" -ForegroundColor Cyan
Set-Location "$root\backend"
& .\.venv\Scripts\python.exe -m pytest -q
if ($LASTEXITCODE -ne 0) { $failed = $true }

Write-Host "`nFrontend checks (typecheck, lint, vitest)" -ForegroundColor Cyan
Set-Location "$root\frontend"
npm run typecheck; if ($LASTEXITCODE -ne 0) { $failed = $true }
npm run lint;      if ($LASTEXITCODE -ne 0) { $failed = $true }
npm test;          if ($LASTEXITCODE -ne 0) { $failed = $true }

if ($E2E) {
    Write-Host "`nBrowser tests (Playwright)" -ForegroundColor Cyan
    npm run test:e2e; if ($LASTEXITCODE -ne 0) { $failed = $true }
}

if ($failed) { Write-Host "`nSome checks FAILED." -ForegroundColor Red; exit 1 }
Write-Host "`nAll checks passed." -ForegroundColor Green
