param(
    [string]$Bundle,
    [string]$TargetDir = "/opt/agomtradepro",
    [ValidateSet('menu','fresh','upgrade','restore-only','status','logs')]
    [string]$Action = 'menu'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (Test-Path "$PSScriptRoot/common.ps1") {
    . "$PSScriptRoot/common.ps1"
} elseif (Test-Path "$PSScriptRoot/shared/common.ps1") {
    . "$PSScriptRoot/shared/common.ps1"
} elseif (Test-Path "$PSScriptRoot/lib/common.ps1") {
    . "$PSScriptRoot/lib/common.ps1"
} else {
    throw "common.ps1 not found"
}

$ProjectName = if ([string]::IsNullOrWhiteSpace($env:COMPOSE_PROJECT_NAME)) { 'agomtradepro' } else { $env:COMPOSE_PROJECT_NAME }
$env:COMPOSE_PROJECT_NAME = $ProjectName

Require-Command docker
Require-Command tar

function Get-ComposeCmd {
    $null = docker compose version 2>$null
    if ($LASTEXITCODE -eq 0) {
        return @('docker','compose')
    }
    if (Get-Command docker-compose -ErrorAction SilentlyContinue) {
        return @('docker-compose')
    }
    Throw-Err "docker compose is required"
}

$ComposeCmd = Get-ComposeCmd

function Invoke-Compose {
    param([string[]]$Args)
    $fullArgs = @('-p', $ProjectName) + $Args
    if ($ComposeCmd.Count -eq 2) {
        & $ComposeCmd[0] $ComposeCmd[1] @fullArgs
    } else {
        & $ComposeCmd[0] @fullArgs
    }
}

function Assert-NoConflictingProject {
    $candidates = @('docker', 'agomtradepro') | Where-Object { $_ -ne $ProjectName }
    $names = docker ps -a --format "{{.Names}}"
    foreach ($candidate in $candidates) {
        if ($names | Select-String -Pattern "^$candidate-(web|redis|caddy)-1$" -Quiet) {
            Throw-Err "Detected compose project '$candidate' alongside '$ProjectName'. Clean old stack first to avoid mixed deployments."
        }
    }
}

function Get-EnvValue {
    param(
        [string]$Name,
        [string]$Text
    )
    $regex = [regex]::Match($Text, "(?m)^$Name=(.*)$")
    if ($regex.Success) {
        return $regex.Groups[1].Value.Trim()
    }
    return ""
}

function Test-Truthy {
    param([string]$Value)
    $v = ($Value ?? "").ToLowerInvariant()
    return @('1','true','yes','on').Contains($v)
}

if ($Action -eq 'menu') {
    Write-Host "Select action:"
    Write-Host "1) fresh"
    Write-Host "2) upgrade"
    Write-Host "3) restore-only"
    Write-Host "4) status"
    Write-Host "5) logs"
    $choice = Read-Host "Enter choice [1]"
    switch ($choice) {
        '2' { $Action = 'upgrade' }
        '3' { $Action = 'restore-only' }
        '4' { $Action = 'status' }
        '5' { $Action = 'logs' }
        default { $Action = 'fresh' }
    }
}

New-Item -ItemType Directory -Force "$TargetDir/releases" | Out-Null

$currentDir = "$TargetDir/current"

if ($Action -eq 'status') {
    Set-Location $currentDir
    Invoke-Compose -Args @('-f','docker/docker-compose.vps.yml','--env-file','deploy/.env','ps')
    exit 0
}

if ($Action -eq 'logs') {
    Set-Location $currentDir
    Invoke-Compose -Args @('-f','docker/docker-compose.vps.yml','--env-file','deploy/.env','logs','-f')
    exit 0
}

if ([string]::IsNullOrWhiteSpace($Bundle)) {
    $Bundle = Read-Default -Prompt "Bundle tar.gz path" -Default "./agomtradepro-vps-bundle.tar.gz"
}

if (-not (Test-Path $Bundle)) {
    Throw-Err "Bundle not found: $Bundle"
}

$releaseName = [System.IO.Path]::GetFileNameWithoutExtension([System.IO.Path]::GetFileNameWithoutExtension($Bundle))
$releaseDir = "$TargetDir/releases/$releaseName"
if (Test-Path $releaseDir) {
    Remove-Item -Recurse -Force $releaseDir
}

New-Item -ItemType Directory -Force $releaseDir | Out-Null
& tar -xzf $Bundle -C "$TargetDir/releases"

if (-not (Test-Path $releaseDir)) {
    $releaseDir = Get-ChildItem "$TargetDir/releases" -Directory | Where-Object { $_.Name -like 'agomtradepro-vps-bundle-*' } | Sort-Object LastWriteTime -Descending | Select-Object -First 1 | ForEach-Object { $_.FullName }
}

if (-not $releaseDir) {
    Throw-Err "Could not locate extracted bundle"
}

Set-Location $releaseDir

if (Test-Path "deploy/manifest.json") {
    Write-Info "Verifying checksums"
    $manifest = Get-Content "deploy/manifest.json" -Raw | ConvertFrom-Json
    foreach ($item in $manifest.checksums) {
        $manifestPath = ($item.path -replace '\\', '/')
        if (-not (Test-Path $manifestPath)) {
            Throw-Err "Missing file from manifest: $manifestPath"
        }
        $hash = (Get-FileHash -Path $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($hash -ne $item.sha256.ToLowerInvariant()) {
            Throw-Err "Checksum mismatch: $manifestPath"
        }
    }
}

Write-Info "Loading Docker images"
Get-ChildItem images/*.tar | ForEach-Object { docker load -i $_.FullName | Out-Null }

if (-not (Test-Path "deploy/.env")) {
    Copy-Item "deploy/.env.vps.example" "deploy/.env"
}

$envText = Get-Content "deploy/.env" -Raw
if ($envText -match "DOMAIN=(.*)") {
    $domain = $Matches[1].Trim()
} else {
    $domain = ""
}

if ([string]::IsNullOrWhiteSpace($domain)) {
    $domain = Read-Host "Domain (blank for HTTP only)"
}

if ($envText -match "SECRET_KEY=(.*)") {
    $secret = $Matches[1].Trim()
} else {
    $secret = ""
}
if ([string]::IsNullOrWhiteSpace($secret) -or $secret -eq 'change-this-to-a-strong-secret') {
    $secret = Read-Default -Prompt "SECRET_KEY" -Default "replace-me"
    $envText = $envText -replace "(?m)^SECRET_KEY=.*$", "SECRET_KEY=$secret"
}

if ([string]::IsNullOrWhiteSpace($domain)) {
    $siteAddress = ':80'
} else {
    $siteAddress = $domain
    if ($envText -match "(?m)^DOMAIN=.*$") {
        $envText = $envText -replace "(?m)^DOMAIN=.*$", "DOMAIN=$domain"
    } else {
        $envText += "`nDOMAIN=$domain`n"
    }
}

$foundWeb = docker images --format "{{.Repository}}:{{.Tag}}" | Where-Object { $_ -like 'agomtradepro-web:*' } | Select-Object -First 1
if ($foundWeb) {
    if ($envText -match "(?m)^WEB_IMAGE=.*$") {
        $envText = $envText -replace "(?m)^WEB_IMAGE=.*$", "WEB_IMAGE=$foundWeb"
    }
}

$envText | Set-Content "deploy/.env"

(Get-Content "docker/Caddyfile.template" -Raw).Replace("__SITE_ADDRESS__", $siteAddress) | Set-Content "docker/Caddyfile"

# Prompt ALLOWED_HOSTS for IP access (template defaults to localhost only)
$allowedHosts = Get-EnvValue -Name 'ALLOWED_HOSTS' -Text $envText
if ([string]::IsNullOrWhiteSpace($allowedHosts) -or $allowedHosts -eq '127.0.0.1,localhost') {
    $defaultHosts = '127.0.0.1,localhost'
    if (-not [string]::IsNullOrWhiteSpace($domain)) {
        $defaultHosts = "$domain,$defaultHosts"
    }
    $allowedHosts = Read-Default -Prompt "ALLOWED_HOSTS (comma-separated)" -Default $defaultHosts
    if ($envText -match "(?m)^ALLOWED_HOSTS=.*$") {
        $envText = $envText -replace "(?m)^ALLOWED_HOSTS=.*$", "ALLOWED_HOSTS=$allowedHosts"
    } else {
        $envText += "`nALLOWED_HOSTS=$allowedHosts`n"
    }
    $envText | Set-Content "deploy/.env"
}

$services = @('redis', 'web', 'caddy')
if (Test-Truthy (Get-EnvValue -Name 'ENABLE_RSSHUB' -Text $envText)) {
    $services += 'rsshub'
}
if (Test-Truthy (Get-EnvValue -Name 'ENABLE_CELERY' -Text $envText)) {
    $services += 'celery_worker'
    $services += 'celery_beat'
}

if ($Action -in @('fresh', 'upgrade')) {
    Assert-NoConflictingProject
    Write-Info "Starting stack"
    $upArgs = @('-f','docker/docker-compose.vps.yml','--env-file','deploy/.env','up','-d') + $services
    Invoke-Compose -Args $upArgs
}

if ($Action -in @('fresh', 'restore-only')) {
    Assert-NoConflictingProject
    if ($Action -eq 'restore-only') {
        Write-Info "Starting data services for restore"
        Invoke-Compose -Args @('-f','docker/docker-compose.vps.yml','--env-file','deploy/.env','up','-d','redis','web')
    }

    if (Test-Path "backups/db.sqlite3") {
        Write-Info "Restoring SQLite database"
        $webCid = Invoke-Compose -Args @('-f','docker/docker-compose.vps.yml','--env-file','deploy/.env','ps','-q','web')
        $webCid = ($webCid | Out-String).Trim()
        if ([string]::IsNullOrWhiteSpace($webCid)) {
            Throw-Err "Web container not found"
        }
        docker cp "backups/db.sqlite3" "$webCid`:/app/data/db.sqlite3"
        Invoke-Compose -Args @('-f','docker/docker-compose.vps.yml','--env-file','deploy/.env','restart','web')
    }

    if (Test-Path "backups/dump.rdb") {
        Write-Info "Restoring Redis snapshot"
        $redisCid = Invoke-Compose -Args @('-f','docker/docker-compose.vps.yml','--env-file','deploy/.env','ps','-q','redis')
        $redisCid = ($redisCid | Out-String).Trim()
        if ([string]::IsNullOrWhiteSpace($redisCid)) {
            Throw-Err "Redis container not found"
        }
        Invoke-Compose -Args @('-f','docker/docker-compose.vps.yml','--env-file','deploy/.env','stop','redis')
        docker cp "backups/dump.rdb" "$redisCid`:/data/dump.rdb"
        Invoke-Compose -Args @('-f','docker/docker-compose.vps.yml','--env-file','deploy/.env','start','redis')
    }
}

if (Test-Path $currentDir) {
    Remove-Item -Recurse -Force $currentDir
}
Copy-Item -Recurse -Force $releaseDir $currentDir

Set-Location $currentDir
Write-Info "Running cold-start bootstrap"
$alphaUniverses = if ($env:AGOMTRADEPRO_BOOTSTRAP_ALPHA_UNIVERSES) { $env:AGOMTRADEPRO_BOOTSTRAP_ALPHA_UNIVERSES } else { 'csi300' }
$alphaTopN = if ($env:AGOMTRADEPRO_BOOTSTRAP_ALPHA_TOP_N) { $env:AGOMTRADEPRO_BOOTSTRAP_ALPHA_TOP_N } else { '30' }
Invoke-Compose -Args @('-f','docker/docker-compose.vps.yml','--env-file','deploy/.env','exec','-T','web','python','manage.py','bootstrap_cold_start','--with-alpha','--alpha-universes',$alphaUniverses,'--alpha-top-n',$alphaTopN)
Invoke-Compose -Args @('-f','docker/docker-compose.vps.yml','--env-file','deploy/.env','ps')
Write-Info "Deployment done"
