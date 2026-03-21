param(
    [string]$TargetDir = "/opt/agomtradepro/current",
    [string]$BackupDir = "/opt/agomtradepro/backups",
    [string]$SqliteFile,
    [string]$RedisFile,
    [switch]$NoSqlite,
    [switch]$NoRedis
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (Test-Path "$PSScriptRoot/shared/common.ps1") {
    . "$PSScriptRoot/shared/common.ps1"
} elseif (Test-Path "$PSScriptRoot/../shared/common.ps1") {
    . "$PSScriptRoot/../shared/common.ps1"
} else {
    function Write-Info([string]$Message) { Write-Host "[INFO] $Message" }
    function Throw-Err([string]$Message) { throw $Message }
    function Require-Command([string]$Name) { if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) { throw "Missing command: $Name" } }
}

Require-Command docker
Require-Command gzip

function Get-ComposeCmd {
    $null = docker compose version 2>$null
    if ($LASTEXITCODE -eq 0) { return @('docker','compose') }
    if (Get-Command docker-compose -ErrorAction SilentlyContinue) { return @('docker-compose') }
    Throw-Err "docker compose is required"
}

$ComposeCmd = Get-ComposeCmd
$env:COMPOSE_PROJECT_NAME = 'agomtradepro'

function Invoke-Compose {
    param([string[]]$Args)
    if ($ComposeCmd.Count -eq 2) {
        & $ComposeCmd[0] $ComposeCmd[1] @Args
    } else {
        & $ComposeCmd[0] @Args
    }
}

Set-Location $TargetDir
Invoke-Compose -Args @('-f','docker/docker-compose.vps.yml','--env-file','deploy/.env','up','-d','redis','web') | Out-Null

if (-not $NoSqlite) {
    if ([string]::IsNullOrWhiteSpace($SqliteFile)) {
        $SqliteFile = Get-ChildItem "$BackupDir/sqlite/db-*.sqlite3.gz" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1 | ForEach-Object { $_.FullName }
    }
    if (-not (Test-Path $SqliteFile)) { Throw-Err "SQLite backup file not found: $SqliteFile" }
    Write-Info "Restoring SQLite from $SqliteFile"

    $tmpSqlite = Join-Path ([System.IO.Path]::GetTempPath()) ("restore-" + [System.IO.Path]::GetRandomFileName() + ".sqlite3")
    gzip -dc $SqliteFile > $tmpSqlite

    $webCid = (Invoke-Compose -Args @('-f','docker/docker-compose.vps.yml','--env-file','deploy/.env','ps','-q','web') | Out-String).Trim()
    if ([string]::IsNullOrWhiteSpace($webCid)) { Throw-Err "web container not found" }

    docker cp $tmpSqlite "$webCid`:/app/data/db.sqlite3"
    Remove-Item $tmpSqlite -Force
    Invoke-Compose -Args @('-f','docker/docker-compose.vps.yml','--env-file','deploy/.env','restart','web') | Out-Null
}

if (-not $NoRedis) {
    if ([string]::IsNullOrWhiteSpace($RedisFile)) {
        $RedisFile = Get-ChildItem "$BackupDir/redis/dump-*.rdb.gz" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1 | ForEach-Object { $_.FullName }
    }
    if (-not (Test-Path $RedisFile)) { Throw-Err "Redis backup file not found: $RedisFile" }
    Write-Info "Restoring Redis from $RedisFile"

    $tmpRedis = Join-Path ([System.IO.Path]::GetTempPath()) ("restore-" + [System.IO.Path]::GetRandomFileName() + ".rdb")
    gzip -dc $RedisFile > $tmpRedis

    $redisCid = (Invoke-Compose -Args @('-f','docker/docker-compose.vps.yml','--env-file','deploy/.env','ps','-q','redis') | Out-String).Trim()
    if ([string]::IsNullOrWhiteSpace($redisCid)) { Throw-Err "redis container not found" }

    Invoke-Compose -Args @('-f','docker/docker-compose.vps.yml','--env-file','deploy/.env','stop','redis') | Out-Null
    docker cp $tmpRedis "$redisCid`:/data/dump.rdb"
    Remove-Item $tmpRedis -Force
    Invoke-Compose -Args @('-f','docker/docker-compose.vps.yml','--env-file','deploy/.env','start','redis') | Out-Null
}

Write-Info "Restore completed"
