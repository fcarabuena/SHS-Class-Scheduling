<#
.SYNOPSIS
    Runs the web app in development mode on http://localhost:3000
#>
. "$PSScriptRoot\env.ps1"
Set-Location (Join-Path (Split-Path -Parent $PSScriptRoot) 'frontend')
npm run dev
