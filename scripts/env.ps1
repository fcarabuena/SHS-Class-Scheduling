<#
.SYNOPSIS
    Puts the drive-D toolchain first on PATH for the current terminal only.

.DESCRIPTION
    Dot-source this at the start of every project terminal session:

        . .\scripts\env.ps1

    It changes nothing outside the current PowerShell process, so other
    projects on this machine keep using whatever tools they already use.
#>

$ToolDirs = @(
    'D:\Tools\Python312',
    'D:\Tools\Python312\Scripts',
    'D:\Tools\nodejs',
    'D:\Tools\npm-global',
    'D:\Tools\PostgreSQL\bin',
    'D:\Tools\Git\cmd'
)

# Prepend, skipping anything already present so re-sourcing is harmless.
$current = $env:Path -split ';' | Where-Object { $_ -and ($ToolDirs -notcontains $_.TrimEnd('\')) }
$env:Path = (@($ToolDirs) + @($current)) -join ';'

# Caches and temp files on drive D
$env:PIP_CACHE_DIR     = 'D:\Cache\pip'
$env:NPM_CONFIG_CACHE  = 'D:\Cache\npm'
$env:NPM_CONFIG_PREFIX = 'D:\Tools\npm-global'
$env:TEMP              = 'D:\Temp'
$env:TMP               = 'D:\Temp'
$env:PYTHONPYCACHEPREFIX = 'D:\Cache\pycache'
$env:NEXT_TELEMETRY_DISABLED = '1'

# Local PostgreSQL cluster (started with scripts\pg-start.ps1)
$env:PGDATA = 'D:\Databases\pgdata'
$env:PGPORT = '5432'
$env:PGHOST = 'localhost'

# Playwright browsers (end-to-end tests) are also kept on drive D
$env:PLAYWRIGHT_BROWSERS_PATH = 'D:\Cache\ms-playwright'
