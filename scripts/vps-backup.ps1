param(
    [string]$TargetDir = "/opt/agomtradepro/current",
    [string]$BackupDir = "/opt/agomtradepro/backups",
    [int]$KeepDays = 14,
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
New-Item -ItemType Directory -Force "$BackupDir/sqlite", "$BackupDir/redis", "$BackupDir/meta" | Out-Null
$ts = Get-Date -Format "yyyyMMdd-HHmmss"

if (-not $NoSqlite) {
    Write-Info "Backing up SQLite"
    $webCid = (Invoke-Compose -Args @('-f','docker/docker-compose.vps.yml','--env-file','deploy/.env','ps','-q','web') | Out-String).Trim()
    if ([string]::IsNullOrWhiteSpace($webCid)) { Throw-Err "web container not found" }
    $sqliteFile = "$BackupDir/sqlite/db-$ts.sqlite3"
    docker cp "$webCid`:/app/data/db.sqlite3" $sqliteFile
    gzip -f $sqliteFile
}

if (-not $NoRedis) {
    Write-Info "Backing up Redis"
    $redisCid = (Invoke-Compose -Args @('-f','docker/docker-compose.vps.yml','--env-file','deploy/.env','ps','-q','redis') | Out-String).Trim()
    if ([string]::IsNullOrWhiteSpace($redisCid)) { Throw-Err "redis container not found" }
    docker exec $redisCid redis-cli BGSAVE | Out-Null
    Start-Sleep -Seconds 3
    $redisFile = "$BackupDir/redis/dump-$ts.rdb"
    docker cp "$redisCid`:/data/dump.rdb" $redisFile
    gzip -f $redisFile
}

Copy-Item deploy/.env "$BackupDir/meta/env-$ts" -Force
Copy-Item docker/docker-compose.vps.yml "$BackupDir/meta/compose-$ts.yml" -Force
if (Test-Path docker/Caddyfile) {
    Copy-Item docker/Caddyfile "$BackupDir/meta/Caddyfile-$ts" -Force
}

$manifest = "$BackupDir/meta/manifest-$ts.txt"
New-Item -ItemType File -Path $manifest -Force | Out-Null
Get-ChildItem -Recurse -File $BackupDir | Where-Object { $_.Name -match $ts } | ForEach-Object {
    $hash = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  $($_.FullName)" | Add-Content $manifest
}

if ($KeepDays -gt 0) {
    $cutoff = (Get-Date).AddDays(-$KeepDays)
    Get-ChildItem -Recurse -File $BackupDir | Where-Object { $_.LastWriteTime -lt $cutoff } | Remove-Item -Force
}

Write-Info "Backup completed"
Write-Host "Manifest: $manifest"
