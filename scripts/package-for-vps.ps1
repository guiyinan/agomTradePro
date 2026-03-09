param(
    [string]$Tag,
    [string]$OutputDir = "dist",
    [string]$WebImageName = "agomsaaf-web",
    [string]$RedisImage = "redis:7-alpine",
    [string]$CaddyImage = "caddy:2-alpine",
    [string]$RsshubImage = "diygod/rsshub:latest",
    [string]$SqliteFile = "db.sqlite3",
    [string]$RedisContainer,
    [switch]$IncludeSqliteData,
    [switch]$SkipData,
    [switch]$SkipRedisData,
    [switch]$SkipWebBuild,
    [switch]$SkipWheelCache,
    [switch]$RefreshWheelCache,
    [switch]$AllowOnlinePipFallback,
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
  -IncludeSqliteData          Include SQLite backup in bundle (default: ask, and default answer is No)
  -SkipData                   Skip backing up SQLite data
  -SkipRedisData              Skip backing up Redis RDB data
  -SkipWebBuild               Do not rebuild the web image; require that the image tag already exists locally
  -SkipWheelCache             Skip preparing local Linux wheel cache
  -RefreshWheelCache          Force refresh local Linux wheel cache
  -AllowOnlinePipFallback     Allow online pip fallback during docker build (default: off, fail fast if wheel cache incomplete)
  -DisableBuildKit            Disable BuildKit and use legacy docker build mode
  -UseWslContext              Build Docker image using temporary WSL context
  -NoStageContext             Disable local staged build context (uses project root directly)
  -Help, -h, --help           Show this help and exit

Examples:
  ./scripts/package-for-vps.ps1
  ./scripts/package-for-vps.ps1               # interactive quick mode
  ./scripts/package-for-vps.ps1 -Tag 20260210
  ./scripts/package-for-vps.ps1 -UseWslContext
  ./scripts/package-for-vps.ps1 -NoStageContext
  ./scripts/package-for-vps.ps1 -DisableBuildKit
  ./scripts/package-for-vps.ps1 -RefreshWheelCache
  ./scripts/package-for-vps.ps1 -AllowOnlinePipFallback
  ./scripts/package-for-vps.ps1 -IncludeSqliteData
  ./scripts/package-for-vps.ps1 -RedisContainer agomsaaf_redis
  ./scripts/package-for-vps.ps1 -SkipData -SkipRedisData
  ./scripts/package-for-vps.ps1 -Tag 20260214 -SkipWebBuild -IncludeSqliteData
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

# Some Docker daemons inject proxy settings into builds (seen in `docker info` as HTTPProxy/HTTPSProxy).
# For reproducible builds, explicitly clear proxy build-args/env when running docker commands.
$ProxyBuildArgs = @(
    "--build-arg", "HTTP_PROXY=",
    "--build-arg", "http_proxy=",
    "--build-arg", "HTTPS_PROXY=",
    "--build-arg", "https_proxy=",
    "--build-arg", "NO_PROXY=",
    "--build-arg", "no_proxy="
)
$ProxyEnvClear = @(
    "-e", "HTTP_PROXY=",
    "-e", "http_proxy=",
    "-e", "HTTPS_PROXY=",
    "-e", "https_proxy=",
    "-e", "NO_PROXY=",
    "-e", "no_proxy="
)

function Convert-ToLf {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return }
    # Normalize CRLF -> LF to avoid /bin/sh parse errors on Linux (CR can break closing '}' tokens).
    $raw = Get-Content -Path $Path -Raw
    $lf = $raw -replace "`r`n", "`n"
    $lf = $lf -replace "`r", ""
    if ($lf -ne $raw) {
        Set-Content -Path $Path -Value $lf -Encoding utf8
    }
}

function Read-YesNoDefault {
    param(
        [string]$Prompt,
        [bool]$Default
    )

    $defaultText = if ($Default) { "Y/n" } else { "y/N" }
    $raw = Read-Default -Prompt "$Prompt ($defaultText)" -Default ($(if ($Default) { "Y" } else { "N" }))
    return ($raw -match '^(?i:y|yes|1|true)$')
}

if ([string]::IsNullOrWhiteSpace($Tag)) {
    $Tag = Get-Date -Format "yyyyMMddHHmmss"
}

$sqliteChoiceMade = $PSBoundParameters.ContainsKey("IncludeSqliteData") -or $PSBoundParameters.ContainsKey("SkipData")
# Quick mode is for humans running the script with no args.
# If the caller provided any parameters, do not prompt (important for automation/CI).
$interactiveQuickMode = ($PSBoundParameters.Count -eq 0)

if ($interactiveQuickMode) {
    Write-Host ""
    Write-Host "== Package Quick Mode ==" -ForegroundColor Green
    $tagInput = Read-Default -Prompt "Bundle tag" -Default $Tag
    if (-not [string]::IsNullOrWhiteSpace($tagInput)) {
        $Tag = $tagInput.Trim()
    }

    if (-not $DisableBuildKit -and -not $PSBoundParameters.ContainsKey("DisableBuildKit")) {
        $DisableBuildKit = Read-YesNoDefault -Prompt "Disable BuildKit (more stable, slower build)?" -Default $false
    }
    if (-not $RefreshWheelCache -and -not $SkipWheelCache) {
        $RefreshWheelCache = Read-YesNoDefault -Prompt "Refresh Linux wheel cache now?" -Default $false
    }

    if (-not $SkipData) {
        if (-not $sqliteChoiceMade -and -not $PSBoundParameters.ContainsKey("IncludeSqliteData")) {
            $IncludeSqliteData = Read-YesNoDefault -Prompt "Include SQLite database in bundle?" -Default $false
            $sqliteChoiceMade = $true
        }

        if (-not $SkipRedisData -and -not $PSBoundParameters.ContainsKey("SkipRedisData") -and -not $PSBoundParameters.ContainsKey("RedisContainer")) {
            $includeRedisDump = Read-YesNoDefault -Prompt "Include Redis snapshot dump.rdb from a container?" -Default $false
            if (-not $includeRedisDump) {
                $SkipRedisData = $true
            } elseif ([string]::IsNullOrWhiteSpace($RedisContainer)) {
                $RedisContainer = Read-Default -Prompt "Redis container name" -Default "agomsaaf_redis"
            }
        }
    }
    Write-Host ""
}

function Ensure-LinuxWheelCache {
    param(
        [string]$ProjectRootPath,
        [bool]$ForceRefresh
    )

    $reqFile = Join-Path $ProjectRootPath "requirements-prod.lock"
    if (-not (Test-Path $reqFile)) {
        Throw-Err "requirements-prod.lock not found: $reqFile"
    }

    $cacheRoot = Join-Path $ProjectRootPath ".cache\pip-wheels\linux-py311"
    $metaFile = Join-Path $cacheRoot ".requirements.sha256"
    $projectMount = (Resolve-Path $ProjectRootPath).Path
    $cacheMount = (Resolve-Path $cacheRoot).Path
    New-Item -ItemType Directory -Force $cacheRoot | Out-Null

    $reqHash = (Get-FileHash -Path $reqFile -Algorithm SHA256).Hash.ToLowerInvariant()
    $cachedHash = ""
    if (Test-Path $metaFile) {
        $cachedHash = (Get-Content -Path $metaFile -Raw).Trim().ToLowerInvariant()
    }
    $wheelCount = @(Get-ChildItem -Path $cacheRoot -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '\.(whl|tar\.gz|zip)$' }).Count
    $cacheValid = (-not $ForceRefresh) -and ($wheelCount -gt 0) -and ($cachedHash -eq $reqHash)

    if ($cacheValid) {
        Write-Info "Using cached Linux wheelhouse: $cacheRoot ($wheelCount files)"
    } else {
        Write-Info "Preparing Linux wheelhouse cache: $cacheRoot"
        if ($ForceRefresh -and (Test-Path $cacheRoot)) {
            Get-ChildItem -Path $cacheRoot -File -ErrorAction SilentlyContinue | Remove-Item -Force
        }

        Write-Host "Project mount: $projectMount" -ForegroundColor Gray
        Write-Host "Cache mount: $cacheMount" -ForegroundColor Gray
        Write-Host "Using Aliyun PyPI mirror (HTTP) for faster downloads..." -ForegroundColor Cyan

        $downloadCmd = @(
            "run", "--rm",
            "-v", "${projectMount}:/workspace",
            "-v", "${cacheMount}:/wheelhouse"
        ) + $ProxyEnvClear + @(
            "-e", "PIP_INDEX_URL=http://mirrors.aliyun.com/pypi/simple/",
            "-e", "PIP_TRUSTED_HOST=mirrors.aliyun.com",
            "-e", "PIP_DISABLE_PIP_VERSION_CHECK=1",
            "python:3.11-slim",
            "sh", "-lc",
            "pip download --prefer-binary --index-url http://mirrors.aliyun.com/pypi/simple/ -r /workspace/requirements-prod.lock -d /wheelhouse"
        )

        & docker @downloadCmd
        if ($LASTEXITCODE -ne 0) {
            Throw-Err "Linux wheel cache refresh failed"
        }

        Set-Content -Path $metaFile -Value $reqHash
        $newCount = @(Get-ChildItem -Path $cacheRoot -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '\.(whl|tar\.gz|zip)$' }).Count
        Write-Info "Linux wheelhouse ready: $newCount files cached"
    }

    # Strict offline check: fail fast if wheelhouse cannot satisfy requirements-prod.lock.
    $verifyCmd = @(
        "run", "--rm",
        "-v", "${projectMount}:/workspace",
        "-v", "${cacheMount}:/wheelhouse"
    ) + $ProxyEnvClear + @(
        "python:3.11-slim",
        "sh", "-lc",
        "pip install --no-index --find-links=/wheelhouse -r /workspace/requirements-prod.lock --dry-run"
    )

    & docker @verifyCmd
    if ($LASTEXITCODE -ne 0) {
        Throw-Err "Linux wheel cache is incomplete for requirements-prod.lock (offline verification failed). Run with -RefreshWheelCache, or pass -AllowOnlinePipFallback if you accept network install."
    }
    Write-Info "Offline wheelhouse verification passed"
}

function Sync-StaticVendor {
    param(
        [string]$ProjectRootPath
    )
    $src = Join-Path $ProjectRootPath "static\vendor"
    $dst = Join-Path $ProjectRootPath "core\static\vendor"
    if (-not (Test-Path $src)) {
        return
    }
    New-Item -ItemType Directory -Force $dst | Out-Null
    Write-Info "Syncing vendor static files: static/vendor -> core/static/vendor"
    & robocopy $src $dst /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -gt 7) {
        Throw-Err "failed to sync vendor static files"
    }
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

# Prefer conda env "agomsaaf" for script-level python operations.
$pythonCmdParts = @("python")
$venvPath = Join-Path $ProjectRoot "venv"
$condaEnv = $env:CONDA_DEFAULT_ENV

if (Get-Command conda -ErrorAction SilentlyContinue) {
    $condaAgom = (& conda env list 2>$null | Select-String -Pattern '^\s*agomsaaf\s')
    if ($condaAgom) {
        $pythonCmdParts = @("conda", "run", "-n", "agomsaaf", "python")
        Write-Info "Using conda environment: agomsaaf"
    } elseif (-not [string]::IsNullOrWhiteSpace($condaEnv)) {
        Write-Info "Using active conda environment: $condaEnv"
    }
} elseif (Test-Path (Join-Path $ProjectRoot ".python-version")) {
    # Check for pyenv
    try {
        $pyenvVersion = Get-Content (Join-Path $ProjectRoot ".python-version") -ErrorAction SilentlyContinue
        if ($pyenvVersion) {
            Write-Info "Detected pyenv version: $pyenvVersion"
        }
    } catch {}
}

$pyExe = $pythonCmdParts[0]
$pyArgs = @()
if ($pythonCmdParts.Count -gt 1) {
    $pyArgs += $pythonCmdParts[1..($pythonCmdParts.Count - 1)]
}
& $pyExe @pyArgs "--version" | Out-Null
if ($LASTEXITCODE -ne 0) {
    Throw-Err "python runtime check failed (expected usable Python / conda agomsaaf environment)"
}

Sync-StaticVendor -ProjectRootPath $ProjectRoot

$webImage = "$WebImageName`:$Tag"
$buildContext = "."
$wslBuildDir = $null
$stageBuildDir = $null
$dockerfilePath = "docker/Dockerfile.prod"
$linuxWheelCacheDir = Join-Path $ProjectRoot ".cache\pip-wheels\linux-py311"
New-Item -ItemType Directory -Force -Path $linuxWheelCacheDir | Out-Null

if (-not $SkipWheelCache) {
    Ensure-LinuxWheelCache -ProjectRootPath $ProjectRoot -ForceRefresh $RefreshWheelCache
}

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
        $dockerfilePath = Join-Path $buildContext "docker/Dockerfile.prod"
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
        $dockerfilePath = Join-Path $buildContext "docker/Dockerfile.prod"
        Write-Info "Using local staged build context: $buildContext"
    }
}

if ($SkipWebBuild) {
    Write-Info "Skipping web image build by request: $webImage"
    docker image inspect $webImage *> $null
    if ($LASTEXITCODE -ne 0) {
        Throw-Err "web image not found locally: $webImage (remove -SkipWebBuild or build/tag the image first)"
    }
} else {
    $pipOfflineOnly = if ($AllowOnlinePipFallback) { "0" } else { "1" }
    if ($DisableBuildKit) {
        Write-Info "Building web image: $webImage (legacy builder, BuildKit disabled)"
        $env:DOCKER_BUILDKIT = "0"
        docker build $ProxyBuildArgs --build-arg PIP_OFFLINE_ONLY=$pipOfflineOnly -f $dockerfilePath -t $webImage $buildContext
        if ($LASTEXITCODE -ne 0) {
            Throw-Err "docker image build failed (legacy builder mode)"
        }
    } else {
        Write-Info "Building web image: $webImage (with BuildKit cache)"
        $env:DOCKER_BUILDKIT = "1"
        # --compress is deprecated with BuildKit, use --output instead for faster builds
        docker build $ProxyBuildArgs --build-arg BUILDKIT_INLINE_CACHE=1 --build-arg PIP_OFFLINE_ONLY=$pipOfflineOnly --progress=plain -f $dockerfilePath -t $webImage $buildContext
        if ($LASTEXITCODE -ne 0) {
            Write-Info "BuildKit build failed, retrying with legacy builder (DOCKER_BUILDKIT=0)"
            $env:DOCKER_BUILDKIT = "0"
            docker build $ProxyBuildArgs --build-arg PIP_OFFLINE_ONLY=$pipOfflineOnly -f $dockerfilePath -t $webImage $buildContext
            if ($LASTEXITCODE -ne 0) {
                Throw-Err "docker image build failed (BuildKit and legacy builder both failed)"
            }
        }
    }
}

Write-Info "Pulling dependency images"
Write-Host "  Pulling $RedisImage..." -ForegroundColor Cyan
docker pull $RedisImage
Write-Host "  Pulling $CaddyImage..." -ForegroundColor Cyan
docker pull $CaddyImage
Write-Host "  Pulling $RsshubImage..." -ForegroundColor Cyan
docker pull $RsshubImage

Write-Info "Saving images to tar"
Write-Host "  Saving web image..." -ForegroundColor Cyan
docker save -o (Join-Path $imagesDir "web.tar") $webImage
Write-Host "  Saving redis image..." -ForegroundColor Cyan
docker save -o (Join-Path $imagesDir "redis.tar") $RedisImage
Write-Host "  Saving caddy image..." -ForegroundColor Cyan
docker save -o (Join-Path $imagesDir "caddy.tar") $CaddyImage
Write-Host "  Saving rsshub image..." -ForegroundColor Cyan
docker save -o (Join-Path $imagesDir "rsshub.tar") $RsshubImage
Write-Host "  All images saved!" -ForegroundColor Green

if (-not $SkipData) {
    $shouldBackupSqlite = $IncludeSqliteData
    if ((-not $IncludeSqliteData) -and (-not $sqliteChoiceMade)) {
        $includeAnswer = Read-Default -Prompt "Include SQLite database in bundle? (y/N)" -Default "N"
        $shouldBackupSqlite = ($includeAnswer -match '^(?i:y|yes|1|true)$')
    }

    if (-not $shouldBackupSqlite) {
        Write-Info "Skipping SQLite backup by choice"
    } else {
    if (-not (Test-Path $SqliteFile)) {
        Throw-Err "SQLite file not found: $SqliteFile"
    }
    $sqliteBackup = Join-Path $backupsDir "db.sqlite3"
    Write-Info "Backing up SQLite file: $SqliteFile"
    Copy-Item $SqliteFile $sqliteBackup -Force
    }
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
Copy-Item scripts/verify-vps-bundle.ps1 (Join-Path $scriptsDir "verify-vps-bundle.ps1") -Force
Copy-Item scripts/deploy-one-click.sh (Join-Path $scriptsDir "deploy-one-click.sh") -Force
Copy-Item scripts/shared/common.sh (Join-Path $scriptsDir "common.sh") -Force
Copy-Item scripts/shared/common.ps1 (Join-Path $scriptsDir "common.ps1") -Force

# Ensure shell scripts have LF line endings for Linux hosts.
Convert-ToLf -Path (Join-Path $dockerDir "entrypoint.prod.sh")
Convert-ToLf -Path (Join-Path $scriptsDir "deploy-on-vps.sh")
Convert-ToLf -Path (Join-Path $scriptsDir "vps-backup.sh")
Convert-ToLf -Path (Join-Path $scriptsDir "vps-restore.sh")
Convert-ToLf -Path (Join-Path $scriptsDir "deploy-one-click.sh")
Convert-ToLf -Path (Join-Path $scriptsDir "common.sh")

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
    $relative = $_.FullName.Substring($bundleRoot.Length + 1).
        Replace([System.IO.Path]::DirectorySeparatorChar, '/').
        Replace([System.IO.Path]::AltDirectorySeparatorChar, '/')
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
