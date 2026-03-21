param(
    [string]$Bundle,
    [switch]$NoDockerLoad,
    [switch]$KeepExtracted
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
    function Require-Command([string]$Name) {
        if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
            throw "Missing command: $Name"
        }
    }
    function Read-Default([string]$Prompt, [string]$Default) {
        $value = Read-Host "$Prompt [$Default]"
        if ([string]::IsNullOrWhiteSpace($value)) { return $Default }
        return $value
    }
}

Require-Command tar

if ([string]::IsNullOrWhiteSpace($Bundle)) {
    $Bundle = Read-Default -Prompt "Bundle tar.gz path" -Default "./dist/agomtradepro-vps-bundle.tar.gz"
}

if (-not (Test-Path $Bundle)) {
    Throw-Err "Bundle not found: $Bundle"
}

$bundlePath = (Resolve-Path $Bundle).Path
Write-Info "Verifying tar.gz integrity: $bundlePath"
tar -tzf $bundlePath > $null
if ($LASTEXITCODE -ne 0) {
    Throw-Err "tar.gz integrity check failed"
}

$tmpRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("agomtradepro-bundle-verify-" + [System.Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $tmpRoot | Out-Null

Write-Info "Extracting bundle to temp dir: $tmpRoot"
tar -xzf $bundlePath -C $tmpRoot
if ($LASTEXITCODE -ne 0) {
    Throw-Err "bundle extraction failed"
}

$bundleRoot = Get-ChildItem -Path $tmpRoot -Directory | Where-Object { $_.Name -like 'agomtradepro-vps-bundle-*' } | Select-Object -First 1
if (-not $bundleRoot) {
    Throw-Err "unable to locate extracted bundle root directory"
}

$requiredFiles = @(
    "deploy/manifest.json",
    "deploy/.env.vps.example",
    "docker/docker-compose.vps.yml",
    "docker/Caddyfile.template",
    "docker/Dockerfile.prod",
    "scripts/deploy-on-vps.sh",
    "scripts/deploy-on-vps.ps1",
    "scripts/vps-backup.sh",
    "scripts/vps-backup.ps1",
    "scripts/vps-restore.sh",
    "scripts/vps-restore.ps1",
    "images/web.tar",
    "images/redis.tar",
    "images/caddy.tar",
    "images/rsshub.tar"
)

$missing = @()
foreach ($rel in $requiredFiles) {
    if (-not (Test-Path (Join-Path $bundleRoot.FullName $rel))) {
        $missing += $rel
    }
}
if ($missing.Count -gt 0) {
    Throw-Err ("missing required files: " + ($missing -join ", "))
}
Write-Info "Required file check passed"

$manifestPath = Join-Path $bundleRoot.FullName "deploy/manifest.json"
$manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
$badChecksums = @()
foreach ($item in $manifest.checksums) {
    $filePath = Join-Path $bundleRoot.FullName $item.path
    if (-not (Test-Path $filePath)) {
        $badChecksums += "missing:$($item.path)"
        continue
    }
    $sha = (Get-FileHash -Path $filePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($sha -ne $item.sha256.ToLowerInvariant()) {
        $badChecksums += "mismatch:$($item.path)"
    }
}
if ($badChecksums.Count -gt 0) {
    $preview = $badChecksums | Select-Object -First 10
    Throw-Err ("manifest checksum verification failed: " + ($preview -join "; "))
}
Write-Info "Manifest checksum verification passed"

if (-not $NoDockerLoad) {
    Require-Command docker
    Write-Info "Running docker load smoke test for bundled images"
    Get-ChildItem -Path (Join-Path $bundleRoot.FullName "images") -Filter "*.tar" | Sort-Object Name | ForEach-Object {
        Write-Info "docker load: $($_.Name)"
        docker load -i $_.FullName | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Throw-Err "docker load failed: $($_.Name)"
        }
    }
    Write-Info "Docker image load smoke test passed"
}

Write-Host "VERIFY_BUNDLE_OK"
Write-Host "Extracted: $($bundleRoot.FullName)"

if (-not $KeepExtracted) {
    Remove-Item -Recurse -Force $tmpRoot
}
