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
    [switch]$SkipRedisData,
    [switch]$DisableBuildKit,
    [switch]$UseWslContext,
    [switch]$NoStageContext,
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Show-Help {
    @"
Usage:
  ./scripts/package-for-vps.ps1 [options]

Options:
  -Tag <string>               Image/bundle tag. Default: current timestamp (yyyyMMddHHmmss)
  -OutputDir <string>         Bundle output directory. Default: dist
  -WebImageName <string>      Web image repository name. Default: agomsaaf-web
  -RedisImage <string>        Redis image to bundle. Default: redis:7-alpine
  -CaddyImage <string>        Caddy image to bundle. Default: caddy:2-alpine
  -RsshubImage <string>       RSSHub image to bundle. Default: diygod/rsshub:latest
  -SqliteFile <string>        SQLite file path. Default: db.sqlite3
  -RedisContainer <string>    Redis container name used for snapshot export (optional, explicit only)
  -SkipData                   Skip backing up SQLite data
  -SkipRedisData              Skip backing up Redis RDB data
  -DisableBuildKit            Disable BuildKit and use legacy docker build mode
  -UseWslContext              Build Docker image using temporary WSL context
  -NoStageContext             Disable local staged build context (uses project root directly)
  -Help, -h, --help           Show this help and exit

Examples:
  ./scripts/package-for-vps.ps1
  ./scripts/package-for-vps.ps1 -Tag 20260210
  ./scripts/package-for-vps.ps1 -UseWslContext
  ./scripts/package-for-vps.ps1 -NoStageContext
  ./scripts/package-for-vps.ps1 -DisableBuildKit
  ./scripts/package-for-vps.ps1 -RedisContainer agomsaaf_redis
  ./scripts/package-for-vps.ps1 -SkipData -SkipRedisData
"@ | Write-Host
}

if ($Help -or $args -contains "-h" -or $args -contains "--help") {
    Show-Help
    exit 0
}

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

# Detect and activate virtual environment
$pythonCmd = "python"
$venvPath = Join-Path $ProjectRoot "venv"
$condaEnv = $env:CONDA_DEFAULT_ENV

if (-not [string]::IsNullOrWhiteSpace($condaEnv)) {
    Write-Info "Using conda environment: $condaEnv"
} elseif (Test-Path (Join-Path $ProjectRoot ".python-version")) {
    # Check for pyenv
    try {
        $pyenvVersion = Get-Content (Join-Path $ProjectRoot ".python-version") -ErrorAction SilentlyContinue
        if ($pyenvVersion) {
            Write-Info "Detected pyenv version: $pyenvVersion"
        }
    } catch {}
}

$webImage = "$WebImageName`:$Tag"
$buildContext = "."
$wslBuildDir = $null
$stageBuildDir = $null

if ($UseWslContext) {
    try {
        $wslDistros = @(
            (& wsl.exe -l -q 2>$null) |
            ForEach-Object { ($_ -replace "`0", "").Trim() } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) -and $_ -notin @("docker-desktop", "docker-desktop-data") }
        )

        if ($wslDistros.Count -gt 0) {
            $wslDistro = $wslDistros[0]
            $wslBuildDir = "/tmp/agomsaaf-build-$Tag"
            $wslBuildDirEscaped = $wslBuildDir.Replace("'", "'\''")
            $uncBuildContext = "\\wsl$\$wslDistro" + ($wslBuildDir -replace "/", "\")

            Write-Info "Preparing WSL build context: ${wslDistro}:$wslBuildDir"
            wsl.exe -d $wslDistro -- sh -lc "rm -rf '$wslBuildDirEscaped' && mkdir -p '$wslBuildDirEscaped'"
            if ($LASTEXITCODE -ne 0) {
                Throw-Err "failed to prepare WSL build directory: ${wslDistro}:$wslBuildDir"
            }

            $robocopyArgs = @(
                $ProjectRoot,
                $uncBuildContext,
                "/MIR",
                "/FFT",
                "/R:2",
                "/W:1",
                "/NFL",
                "/NDL",
                "/NJH",
                "/NJS",
                "/NP",
                "/XD",
                ".git",
                "node_modules",
                "dist",
                "htmlcov",
                ".pytest_cache",
                ".mypy_cache",
                ".claude",
                "screenshots",
                "docs",
                "doc",
                "venv",
                "env",
                "ENV",
                "agomsaaf",
                "staticfiles",
                "media"
            )

            Write-Info "Syncing project files to WSL temp context"
            & robocopy @robocopyArgs | Out-Null
            if ($LASTEXITCODE -gt 7) {
                Throw-Err "failed to sync files to WSL build context"
            }

            $buildContext = $uncBuildContext
            Write-Info "Using WSL build context: $buildContext"
        } else {
            Write-Info "No usable WSL distro found; using local build context"
        }
    } catch {
        Write-Info "WSL staging unavailable; using local build context"
    }
} else {
    if ($NoStageContext) {
        Write-Info "Using local build context"
    } else {
        $stageBuildDir = Join-Path $env:TEMP "agomsaaf-build-$Tag"
        Write-Info "Preparing local staged build context: $stageBuildDir"
        New-Item -ItemType Directory -Force $stageBuildDir | Out-Null

        $robocopyArgs = @(
            $ProjectRoot,
            $stageBuildDir,
            "/MIR",
            "/FFT",
            "/R:2",
            "/W:1",
            "/NFL",
            "/NDL",
            "/NJH",
            "/NJS",
            "/NP",
            "/XD",
            ".git",
            "node_modules",
            "dist",
            "htmlcov",
            ".pytest_cache",
            ".mypy_cache",
            ".claude",
            "screenshots",
            "docs",
            "doc",
            "venv",
            "env",
            "ENV",
            "agomsaaf",
            "staticfiles",
            "media"
        )

        Write-Info "Syncing project files to local staged context"
        & robocopy @robocopyArgs | Out-Null
        if ($LASTEXITCODE -gt 7) {
            Throw-Err "failed to sync files to local staged build context"
        }

        $buildContext = $stageBuildDir
        Write-Info "Using local staged build context: $buildContext"
    }
}

if ($DisableBuildKit) {
    Write-Info "Building web image: $webImage (legacy builder, BuildKit disabled)"
    $env:DOCKER_BUILDKIT = "0"
    docker build -f docker/Dockerfile.prod -t $webImage $buildContext
    if ($LASTEXITCODE -ne 0) {
        Throw-Err "docker image build failed (legacy builder mode)"
    }
} else {
    Write-Info "Building web image: $webImage (with BuildKit cache)"
    $env:DOCKER_BUILDKIT = "1"
    # --compress is deprecated with BuildKit, use --output instead for faster builds
    docker build --build-arg BUILDKIT_INLINE_CACHE=1 --progress=plain -f docker/Dockerfile.prod -t $webImage $buildContext
    if ($LASTEXITCODE -ne 0) {
        Write-Info "BuildKit build failed, retrying with legacy builder (DOCKER_BUILDKIT=0)"
        $env:DOCKER_BUILDKIT = "0"
        docker build -f docker/Dockerfile.prod -t $webImage $buildContext
        if ($LASTEXITCODE -ne 0) {
            Throw-Err "docker image build failed (BuildKit and legacy builder both failed)"
        }
    }
}

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
        Write-Info "Skipping Redis data backup (no -RedisContainer provided). Redis image is still bundled for VPS."
    } else {
        Write-Info "Creating Redis snapshot from container: $RedisContainer"

        $lastSaveBeforeRaw = (& docker exec $RedisContainer redis-cli LASTSAVE 2>$null | Out-String).Trim()
        [int64]$lastSaveBefore = 0
        if ($lastSaveBeforeRaw -match '^\d+$') {
            $lastSaveBefore = [int64]$lastSaveBeforeRaw
        }

        docker exec $RedisContainer redis-cli BGSAVE | Out-Null

        $deadline = (Get-Date).AddMinutes(2)
        $snapshotReady = $false
        while ((Get-Date) -lt $deadline) {
            Start-Sleep -Milliseconds 1000

            $lastSaveNowRaw = (& docker exec $RedisContainer redis-cli LASTSAVE 2>$null | Out-String).Trim()
            if (-not ($lastSaveNowRaw -match '^\d+$')) {
                continue
            }

            $persistenceInfo = (& docker exec $RedisContainer redis-cli INFO persistence 2>$null | Out-String)
            $isSaving = $true
            foreach ($line in ($persistenceInfo -split "`r?`n")) {
                if ($line -match '^rdb_bgsave_in_progress:(\d+)$') {
                    $isSaving = ($Matches[1] -eq '1')
                    break
                }
            }

            if ((-not $isSaving) -and ([int64]$lastSaveNowRaw -gt $lastSaveBefore)) {
                $snapshotReady = $true
                break
            }
        }

        if (-not $snapshotReady) {
            Throw-Err "timed out waiting for Redis BGSAVE to complete: $RedisContainer"
        }

        docker cp "$RedisContainer`:/data/dump.rdb" (Join-Path $backupsDir "dump.rdb")
    }
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
Copy-Item scripts/vps-backup.sh (Join-Path $scriptsDir "vps-backup.sh") -Force
Copy-Item scripts/vps-backup.ps1 (Join-Path $scriptsDir "vps-backup.ps1") -Force
Copy-Item scripts/vps-restore.sh (Join-Path $scriptsDir "vps-restore.sh") -Force
Copy-Item scripts/vps-restore.ps1 (Join-Path $scriptsDir "vps-restore.ps1") -Force
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

if ($UseWslContext -and -not [string]::IsNullOrWhiteSpace($wslBuildDir)) {
    $cleanupDistros = @(
        (& wsl.exe -l -q 2>$null) |
        ForEach-Object { ($_ -replace "`0", "").Trim() } |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) -and $_ -notin @("docker-desktop", "docker-desktop-data") }
    )
    if ($cleanupDistros.Count -gt 0) {
        $cleanupDistro = $cleanupDistros[0]
        $wslBuildDirEscaped = $wslBuildDir.Replace("'", "'\''")
        wsl.exe -d $cleanupDistro -- sh -lc "rm -rf '$wslBuildDirEscaped'" | Out-Null
    }
}

if (-not [string]::IsNullOrWhiteSpace($stageBuildDir) -and (Test-Path $stageBuildDir)) {
    try {
        Remove-Item -Recurse -Force $stageBuildDir
    } catch {
        Write-Info "Warning: failed to clean local staged context: $stageBuildDir"
    }
}

Write-Info "Bundle completed"
Write-Host "Output: $finalTar"
