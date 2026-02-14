param(
    [string]$SourceBundle,
    [string]$OutputTag,
    [string]$SqliteFile = "db.sqlite3",
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Show-Help {
@"
Inject local SQLite DB into an existing VPS bundle without rebuilding Docker images.

Usage:
  pwsh ./scripts/inject-sqlite-into-bundle.ps1 -SourceBundle ./dist/agomsaaf-vps-bundle-<tag>.tar.gz

Options:
  -SourceBundle <path>     Existing bundle tar.gz to modify
  -OutputTag <string>      New bundle directory/file tag (default: current timestamp)
  -SqliteFile <path>       Local SQLite file to inject (default: db.sqlite3)
"@ | Write-Host
}

if ($Help) { Show-Help; exit 0 }

if ([string]::IsNullOrWhiteSpace($SourceBundle)) {
    throw "Missing -SourceBundle"
}
if (-not (Test-Path $SourceBundle)) {
    throw "Source bundle not found: $SourceBundle"
}
if (-not (Test-Path $SqliteFile)) {
    throw "SQLite file not found: $SqliteFile"
}

if ([string]::IsNullOrWhiteSpace($OutputTag)) {
    $OutputTag = Get-Date -Format "yyyyMMddHHmmss"
}

$src = (Resolve-Path $SourceBundle).Path
$tmpRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("agomsaaf-bundle-inject-" + [System.Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $tmpRoot | Out-Null

Write-Host "[INFO] Extracting: $src" -ForegroundColor Cyan
tar -xzf $src -C $tmpRoot
if ($LASTEXITCODE -ne 0) { throw "bundle extraction failed" }

$bundleRoot = Get-ChildItem -Path $tmpRoot -Directory | Where-Object { $_.Name -like 'agomsaaf-vps-bundle-*' } | Select-Object -First 1
if (-not $bundleRoot) { throw "unable to locate extracted bundle root directory" }

$newName = "agomsaaf-vps-bundle-$OutputTag"
$newRoot = Join-Path $tmpRoot $newName
Rename-Item -Path $bundleRoot.FullName -NewName $newName
$bundleRoot = Get-Item $newRoot

$backupsDir = Join-Path $bundleRoot.FullName "backups"
New-Item -ItemType Directory -Force -Path $backupsDir | Out-Null

$destDb = Join-Path $backupsDir "db.sqlite3"
Write-Host "[INFO] Injecting SQLite: $SqliteFile -> $destDb" -ForegroundColor Cyan
Copy-Item -Path $SqliteFile -Destination $destDb -Force

$manifestPath = Join-Path $bundleRoot.FullName "deploy/manifest.json"
if (-not (Test-Path $manifestPath)) { throw "manifest not found: $manifestPath" }

Write-Host "[INFO] Recomputing manifest checksums" -ForegroundColor Cyan
$manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
$manifest.generated_at = (Get-Date).ToUniversalTime().ToString("o")
$manifest.tag = $OutputTag
$manifest.checksums = @()

Get-ChildItem -Recurse -File $bundleRoot.FullName | ForEach-Object {
    $hash = Get-FileHash -Path $_.FullName -Algorithm SHA256
    $relative = $_.FullName.Substring($bundleRoot.FullName.Length + 1).
        Replace([System.IO.Path]::DirectorySeparatorChar, '/').
        Replace([System.IO.Path]::AltDirectorySeparatorChar, '/')
    # Avoid self-referential checksums. The packager writes manifest after enumerating checksums.
    if ($relative -eq "deploy/manifest.json") {
        return
    }
    $manifest.checksums += [pscustomobject]@{
        path = $relative
        sha256 = $hash.Hash.ToLowerInvariant()
    }
}

$manifest | ConvertTo-Json -Depth 10 | Set-Content -Path $manifestPath

$outDir = Join-Path (Split-Path -Parent $src) ""
$outBundle = Join-Path $outDir "$newName.tar.gz"
if (Test-Path $outBundle) { Remove-Item $outBundle -Force }

Write-Host "[INFO] Packing new bundle: $outBundle" -ForegroundColor Cyan
Push-Location $tmpRoot
tar -czf $outBundle $newName
Pop-Location

Write-Host "OUTPUT_BUNDLE=$outBundle"
