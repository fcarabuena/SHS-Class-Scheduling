<#
.SYNOPSIS
    Stops the local PostgreSQL 16 cluster in D:\Databases\pgdata.
#>
. "$PSScriptRoot\env.ps1"

& pg_ctl stop -D $env:PGDATA -m fast -w
exit $LASTEXITCODE
