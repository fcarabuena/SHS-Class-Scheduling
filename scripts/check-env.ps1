<#
.SYNOPSIS
    Verifies that the whole toolchain, its caches and its data live on drive D.

.DESCRIPTION
    Prints the resolved path and version of every tool the project needs and
    exits with code 1 if anything is missing, is the wrong major version, or
    resolves to a drive other than D.

    Docker is optional: it is reported, and only fails the check if it is
    installed somewhere other than drive D.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\check-env.ps1
#>

$RequiredDrive = 'D:'
$script:Failures = 0

function Write-Row {
    param([string]$Status, [string]$Name, [string]$Value, [string]$Note)
    $color = switch ($Status) {
        'OK'   { 'Green' }
        'WARN' { 'Yellow' }
        default { 'Red' }
    }
    $line = '[{0,-4}] {1,-22} {2}' -f $Status, $Name, $Value
    if ($Note) { $line = "$line  <- $Note" }
    Write-Host $line -ForegroundColor $color
    if ($Status -eq 'FAIL') { $script:Failures++ }
}

function Test-OnRequiredDrive {
    param([string]$Path)
    if (-not $Path) { return $false }
    return $Path.Trim().ToUpper().StartsWith($RequiredDrive)
}

function Get-ToolVersion {
    param([string]$Exe, [string[]]$VersionArgs)
    try {
        $out = & $Exe @VersionArgs 2>$null | Select-Object -First 1
        if ($out) { return "$out".Trim() }
    } catch { }
    return ''
}

function Test-Tool {
    param(
        [string]$Name,
        [string[]]$VersionArgs = @('--version'),
        [string]$VersionPattern = '',
        [string]$Expected = '',
        [switch]$Optional
    )
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $cmd) {
        if ($Optional) {
            Write-Row 'WARN' $Name 'not installed' 'optional, skipped'
        } else {
            Write-Row 'FAIL' $Name 'NOT FOUND' "install to $Expected and add to PATH"
        }
        return
    }
    $path = $cmd.Source
    if (-not (Test-OnRequiredDrive $path)) {
        Write-Row 'FAIL' $Name $path "must be on $RequiredDrive (expected $Expected)"
        return
    }
    $version = Get-ToolVersion $path $VersionArgs
    if ($VersionPattern -and ($version -notmatch $VersionPattern)) {
        Write-Row 'FAIL' $Name "$path ($version)" "version must match $VersionPattern"
        return
    }
    Write-Row 'OK' $Name "$path ($version)"
}

function Test-PathSetting {
    param([string]$Name, [string]$Value, [string]$Expected, [switch]$MustExist)
    if (-not $Value) {
        Write-Row 'FAIL' $Name 'NOT SET' "expected $Expected"
        return
    }
    if (-not (Test-OnRequiredDrive $Value)) {
        Write-Row 'FAIL' $Name $Value "must be on $RequiredDrive (expected $Expected)"
        return
    }
    if ($MustExist -and -not (Test-Path $Value)) {
        Write-Row 'FAIL' $Name $Value 'directory does not exist'
        return
    }
    Write-Row 'OK' $Name $Value
}

Write-Host ''
Write-Host "Environment check - everything must live on drive $RequiredDrive" -ForegroundColor Cyan
Write-Host ''
Write-Host 'Tools' -ForegroundColor Cyan

Test-Tool -Name 'python' -VersionPattern 'Python 3\.12\.' -Expected 'D:\Tools\Python312'
Test-Tool -Name 'pip'    -Expected 'D:\Tools\Python312\Scripts'
Test-Tool -Name 'node'   -Expected 'D:\Tools\nodejs'
Test-Tool -Name 'npm'    -Expected 'D:\Tools\nodejs'
Test-Tool -Name 'psql'   -VersionPattern '\b16\.' -Expected 'D:\Tools\PostgreSQL\bin'
Test-Tool -Name 'git'    -Expected 'D:\Tools\Git'
Test-Tool -Name 'docker' -Expected 'D:\Tools\Docker' -Optional

Write-Host ''
Write-Host 'Caches, temp and data' -ForegroundColor Cyan

# Read the persisted user variable, falling back to the current process
# (a freshly set user variable is not visible in already-open terminals).
$pipCache = [Environment]::GetEnvironmentVariable('PIP_CACHE_DIR', 'User')
if (-not $pipCache) { $pipCache = $env:PIP_CACHE_DIR }
Test-PathSetting -Name 'PIP_CACHE_DIR' -Value $pipCache -Expected 'D:\Cache\pip'

$npm = Get-Command npm -ErrorAction SilentlyContinue | Select-Object -First 1
if ($npm) {
    $npmCache  = Get-ToolVersion $npm.Source @('config', 'get', 'cache')
    $npmPrefix = Get-ToolVersion $npm.Source @('config', 'get', 'prefix')
    Test-PathSetting -Name 'npm cache'  -Value $npmCache  -Expected 'D:\Cache\npm'
    Test-PathSetting -Name 'npm prefix' -Value $npmPrefix -Expected 'D:\Tools\npm-global'
} else {
    Write-Row 'FAIL' 'npm cache'  'UNKNOWN' 'npm is not installed'
    Write-Row 'FAIL' 'npm prefix' 'UNKNOWN' 'npm is not installed'
}

Test-PathSetting -Name 'project TEMP dir' -Value 'D:\Temp' -Expected 'D:\Temp' -MustExist

$pgData = 'D:\Data\pgdata'
if (Test-Path (Join-Path $pgData 'PG_VERSION')) {
    $pgVersion = (Get-Content (Join-Path $pgData 'PG_VERSION') -TotalCount 1).Trim()
    if ($pgVersion -eq '16') {
        Write-Row 'OK' 'PostgreSQL data dir' "$pgData (cluster v$pgVersion)"
    } else {
        Write-Row 'FAIL' 'PostgreSQL data dir' "$pgData (cluster v$pgVersion)" 'expected a v16 cluster'
    }
} else {
    Write-Row 'FAIL' 'PostgreSQL data dir' $pgData 'no initialized cluster found here'
}

$projectRoot = Split-Path -Parent $PSScriptRoot
Test-PathSetting -Name 'project root' -Value $projectRoot -Expected 'D:\Projects\shs-scheduler' -MustExist

Write-Host ''
if ($script:Failures -gt 0) {
    Write-Host "FAILED: $($script:Failures) problem(s). Fix them, open a NEW terminal, and run this again." -ForegroundColor Red
    exit 1
}
Write-Host "PASSED: the toolchain is entirely on drive $RequiredDrive." -ForegroundColor Green
exit 0
