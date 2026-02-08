param(
    [string]$Tag,
    [string]$OutputDir = "dist",
    [string]$WebImageName = "agomsaaf-web",
    [string]$RedisImage = "redis:7-alpine",
    [string]$CaddyImage = "caddy:2-alpine",
    [string]$RsshubImage = "diygod/rsshub:latest",
    [string]$SqliteFile = "db.sqlite3",
    [string]$RedisContainer,
    [switch]$SkipData,
    [switch]$SkipRedisData
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. "$PSScriptRoot/shared/common.ps1"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

Require-Command docker

if ([string]::IsNullOrWhiteSpace($Tag)) {
    $Tag = Get-Date -Format "yyyyMMddHHmmss"
}

$bundleName = "agomsaaf-vps-bundle-$Tag"
$bundleRoot = Join-Path $ProjectRoot (Join-Path $OutputDir $bundleName)
$imagesDir = Join-Path $bundleRoot "images"
$backupsDir = Join-Path $bundleRoot "backups"
$deployDir = Join-Path $bundleRoot "deploy"
$dockerDir = Join-Path $bundleRoot "docker"
$scriptsDir = Join-Path $bundleRoot "scripts"

Write-Info "Preparing bundle workspace: $bundleRoot"
New-Item -ItemType Directory -Force $imagesDir, $backupsDir, $deployDir, $dockerDir, $scriptsDir | Out-Null

$webImage = "$WebImageName`:$Tag"
Write-Info "Building web image: $webImage"
docker build -f docker/Dockerfile.prod -t $webImage .

Write-Info "Pulling dependency images"
docker pull $RedisImage | Out-Null
docker pull $CaddyImage | Out-Null
docker pull $RsshubImage | Out-Null

Write-Info "Saving images to tar"
docker save -o (Join-Path $imagesDir "web.tar") $webImage
docker save -o (Join-Path $imagesDir "redis.tar") $RedisImage
docker save -o (Join-Path $imagesDir "caddy.tar") $CaddyImage
docker save -o (Join-Path $imagesDir "rsshub.tar") $RsshubImage

if (-not $SkipData) {
    if (-not (Test-Path $SqliteFile)) {
        Throw-Err "SQLite file not found: $SqliteFile"
    }
    $sqliteBackup = Join-Path $backupsDir "db.sqlite3"
    Write-Info "Backing up SQLite file: $SqliteFile"
    Copy-Item $SqliteFile $sqliteBackup -Force
}

if ((-not $SkipData) -and (-not $SkipRedisData)) {
    if ([string]::IsNullOrWhiteSpace($RedisContainer)) {
        $candidate = docker ps --format "{{.Names}}" | Where-Object { $_ -match "redis" } | Select-Object -First 1
        if (-not [string]::IsNullOrWhiteSpace($candidate)) {
            $RedisContainer = $candidate
        }
    }

    if ([string]::IsNullOrWhiteSpace($RedisContainer)) {
        $RedisContainer = Read-Default -Prompt "Redis container name" -Default "agomsaaf_redis"
    }

    Write-Info "Creating Redis snapshot from container: $RedisContainer"
    docker exec $RedisContainer redis-cli BGSAVE | Out-Null
    Start-Sleep -Seconds 2
    docker cp "$RedisContainer`:/data/dump.rdb" (Join-Path $backupsDir "dump.rdb")
}

Write-Info "Copying deployment assets"
Copy-Item docker/Dockerfile.prod (Join-Path $dockerDir "Dockerfile.prod") -Force
Copy-Item docker/docker-compose.vps.yml (Join-Path $dockerDir "docker-compose.vps.yml") -Force
Copy-Item docker/Caddyfile.template (Join-Path $dockerDir "Caddyfile.template") -Force
Copy-Item docker/entrypoint.prod.sh (Join-Path $dockerDir "entrypoint.prod.sh") -Force
Copy-Item deploy/.env.vps.example (Join-Path $deployDir ".env.vps.example") -Force
Copy-Item deploy/README_DEPLOY.md (Join-Path $deployDir "README_DEPLOY.md") -Force
Copy-Item scripts/deploy-on-vps.sh (Join-Path $scriptsDir "deploy-on-vps.sh") -Force
Copy-Item scripts/deploy-on-vps.ps1 (Join-Path $scriptsDir "deploy-on-vps.ps1") -Force
Copy-Item scripts/shared/common.sh (Join-Path $scriptsDir "common.sh") -Force
Copy-Item scripts/shared/common.ps1 (Join-Path $scriptsDir "common.ps1") -Force

$manifest = [ordered]@{
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    tag = $Tag
    images = [ordered]@{
        web = $webImage
        redis = $RedisImage
        caddy = $CaddyImage
        rsshub = $RsshubImage
    }
    checksums = @()
}

Get-ChildItem -Recurse -File $bundleRoot | ForEach-Object {
    $hash = Get-FileHash -Path $_.FullName -Algorithm SHA256
    $relative = $_.FullName.Substring($bundleRoot.Length + 1).Replace('\\', '/')
    $manifest.checksums += [ordered]@{
        path = $relative
        sha256 = $hash.Hash.ToLowerInvariant()
    }
}

$manifestPath = Join-Path $deployDir "manifest.json"
$manifest | ConvertTo-Json -Depth 8 | Set-Content -Path $manifestPath

$finalTar = Join-Path $ProjectRoot (Join-Path $OutputDir "$bundleName.tar.gz")
if (Test-Path $finalTar) {
    Remove-Item $finalTar -Force
}

Write-Info "Packing bundle: $finalTar"
Push-Location (Join-Path $ProjectRoot $OutputDir)
tar -czf "$finalTar" "$bundleName"
Pop-Location

Write-Info "Bundle completed"
Write-Host "Output: $finalTar"
