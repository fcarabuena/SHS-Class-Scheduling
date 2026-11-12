<#
.SYNOPSIS
    Starts the local PostgreSQL 16 cluster in D:\Databases\pgdata (no Windows service).
#>
. "$PSScriptRoot\env.ps1"

& pg_ctl status -D $env:PGDATA *> $null
if ($LASTEXITCODE -eq 0) {
    Write-Host "PostgreSQL is already running on port $env:PGPORT."
    exit 0
}

New-Item -ItemType Directory -Force 'D:\Databases\pglog' | Out-Null
& pg_ctl start -D $env:PGDATA -l 'D:\Databases\pglog\postgres.log' -o "-p $env:PGPORT" -w
exit $LASTEXITCODE
