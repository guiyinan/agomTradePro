<#
.SYNOPSIS
    General project backup script
.DESCRIPTION
    Backup current directory to bak folder in parent directory
.PARAMETER ExcludeFiles
    File patterns to exclude (space separated)
.PARAMETER ExcludeDirs
    Directory names to exclude (space separated)
.PARAMETER Compression
    Compression level: NoCompression, Fast, Optimal
.EXAMPLE
    .\backup-script.ps1
    Backup with default exclusion rules
#>

param(
    [string]$ExcludeFiles = "*.xml *.log *.log.*",
    [string]$ExcludeDirs = "__pycache__ .venv venv node_modules .git *.egg-info .vscode .idea",
    [ValidateSet("NoCompression", "Fastest", "Optimal")]
    [string]$Compression = "Fastest"
)

# Get current folder name
$currentFolder = Split-Path -Path (Get-Location) -Leaf
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupName = "${currentFolder}_${timestamp}.zip"

# Script parent directory's bak folder
$scriptDir = Split-Path -Parent $PSScriptRoot
if (-not $scriptDir) {
    $scriptDir = ".."
}
$backupDir = Join-Path $scriptDir "bak"
$destinationPath = Join-Path $backupDir $backupName

# Ensure backup directory exists
if (-not (Test-Path $backupDir)) {
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
}

# Create temp directory
$tempDir = New-Item -ItemType Directory -Path "$env:TEMP\$backupName" -Force

try {
    Write-Host "Backing up: $currentFolder" -ForegroundColor Cyan
    Write-Host "Script location: $PSScriptRoot" -ForegroundColor Gray
    Write-Host "Backup target: $destinationPath" -ForegroundColor Gray
    Write-Host ""

    # Copy files using robocopy
    Write-Host "Copying files..." -ForegroundColor Cyan
    $robocopyCmd = "robocopy . `"$tempDir`" /E /XF $ExcludeFiles /XD $ExcludeDirs /NDL /NFL /NP /NJH /NJS /R:0 /W:0"
    $robocopyExitCode = cmd /c $robocopyCmd

    if ($robocopyExitCode -gt 7) {
        throw "robocopy failed with exit code: $robocopyExitCode"
    }

    # Compress
    Write-Host "Compressing..." -ForegroundColor Cyan
    Compress-Archive -Path "$tempDir\*" -DestinationPath $destinationPath -CompressionLevel $Compression -Force

    $backupSize = (Get-Item $destinationPath).Length / 1MB
    $backupSizeStr = "{0:N2}" -f $backupSize

    Write-Host ""
    Write-Host "[OK] Backup completed!" -ForegroundColor Green
    Write-Host "  Location: $destinationPath" -ForegroundColor Gray
    Write-Host "  Size: $backupSizeStr MB" -ForegroundColor Gray
}
catch {
    Write-Host ""
    $errorMsg = "Backup failed: " + $_.Exception.Message
    Write-Host $errorMsg -ForegroundColor Red
    exit 1
}
finally {
    if (Test-Path $tempDir) {
        Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
