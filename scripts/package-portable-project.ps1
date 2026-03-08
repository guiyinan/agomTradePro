[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$OutputDir,

    [Parameter(Mandatory = $false)]
    [ValidateSet('auto', 'zip', '7z')]
    [string]$Format = 'auto',

    [Parameter(Mandatory = $false)]
    [switch]$IncludeEnv,

    [Parameter(Mandatory = $false)]
    [switch]$IncludeDatabase,

    [Parameter(Mandatory = $false)]
    [switch]$IncludeMedia,

    [Parameter(Mandatory = $false)]
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

$script:HasExplicitParams = $PSBoundParameters.Count -gt 0

function Write-Info($msg) {
    Write-Host "[INFO] $msg" -ForegroundColor Cyan
}

function Write-WarnMsg($msg) {
    Write-Host "[WARN] $msg" -ForegroundColor Yellow
}

function Write-Ok($msg) {
    Write-Host "[OK] $msg" -ForegroundColor Green
}

function Read-DefaultValue {
    param(
        [string]$Prompt,
        [string]$Default
    )

    $raw = Read-Host "$Prompt [$Default]"
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return $Default
    }
    return $raw.Trim()
}

function Read-YesNoDefault {
    param(
        [string]$Prompt,
        [bool]$Default = $false
    )

    $defaultLabel = if ($Default) { 'Y/n' } else { 'y/N' }
    while ($true) {
        $raw = Read-Host "$Prompt [$defaultLabel]"
        if ([string]::IsNullOrWhiteSpace($raw)) {
            return $Default
        }

        switch ($raw.Trim().ToLowerInvariant()) {
            'y' { return $true }
            'yes' { return $true }
            'n' { return $false }
            'no' { return $false }
            default { Write-WarnMsg "Please answer y or n." }
        }
    }
}

function Resolve-SevenZip {
    $candidates = @(
        "C:\Program Files\7-Zip\7z.exe",
        "C:\Program Files (x86)\7-Zip\7z.exe"
    )

    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    $cmd = Get-Command 7z -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    return $null
}

function New-PortableReadme {
    param(
        [string]$TargetFile,
        [string]$ProjectName
    )

    $content = @"
# $ProjectName Portable Package

This package is intended for quickly moving the project to another Windows machine.

Suggested first steps:
1. Extract this archive.
2. Create a virtual environment:
   `python -m venv agomsaaf`
3. Activate it:
   PowerShell: `agomsaaf/Scripts/Activate.ps1`
4. Install dependencies:
   `pip install -r requirements.txt`
5. Copy environment template if needed:
   `Copy-Item .env.example .env`
6. Start the project:
   `start.bat`

Notes:
- This portable package excludes caches, virtual environments, git metadata, local databases, dist artifacts, and VPS/bundle deployment files by default.
- Use `scripts/dev.bat` for quick SQLite startup.
- Use `scripts/docker-dev.bat` if Docker Desktop is installed and you want PostgreSQL + Redis.
"@

    Set-Content -Path $TargetFile -Value $content -Encoding UTF8
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$projectName = Split-Path -Leaf $projectRoot
$timestamp = Get-Date -Format 'yyyyMMddHHmmss'

if (-not $OutputDir) {
    $OutputDir = Split-Path -Parent $projectRoot
}

if (-not $script:HasExplicitParams) {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host " AgomSAAF Portable Project Packager" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""

    $OutputDir = Read-DefaultValue -Prompt 'Output directory' -Default $OutputDir
    $Format = Read-DefaultValue -Prompt 'Archive format (auto/zip/7z)' -Default $Format
    $IncludeEnv = Read-YesNoDefault -Prompt 'Include .env file?' -Default $false
    $IncludeDatabase = Read-YesNoDefault -Prompt 'Include local SQLite/database files?' -Default $false
    $IncludeMedia = Read-YesNoDefault -Prompt 'Include media directory?' -Default $false
    $DryRun = Read-YesNoDefault -Prompt 'Dry run only?' -Default $false
}

$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

$sevenZip = Resolve-SevenZip
$resolvedFormat = $Format
if ($resolvedFormat -eq 'auto') {
    if ($sevenZip) {
        $resolvedFormat = '7z'
    } else {
        $resolvedFormat = 'zip'
    }
}

if ($resolvedFormat -eq '7z' -and -not $sevenZip) {
    throw "7z format requested, but 7-Zip was not found."
}

$extension = if ($resolvedFormat -eq '7z') { '7z' } else { 'zip' }
$archiveName = "$projectName-$timestamp.$extension"
$archivePath = Join-Path $OutputDir $archiveName

$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("agomsaaf-portable-" + [System.Guid]::NewGuid().ToString('N'))
$stageRoot = Join-Path $tempRoot $projectName

$excludeDirNames = @(
    '.git',
    '.github',
    '.idea',
    '.mypy_cache',
    '.pytest_cache',
    '.pyre',
    '.pytype',
    '.tox',
    '.venv',
    '.vscode',
    '__pycache__',
    'agomsaaf',
    'backups',
    'build',
    'dist',
    'downloads',
    'htmlcov',
    'logs',
    'node_modules',
    'output',
    'reports',
    'sdist',
    'var',
    'venv',
    'wheels'
)

$excludeDirPaths = @(
    (Join-Path $projectRoot '.agents'),
    (Join-Path $projectRoot '.claude'),
    (Join-Path $projectRoot '.git'),
    (Join-Path $projectRoot '.hypothesis'),
    (Join-Path $projectRoot '.ruff_cache'),
    (Join-Path $projectRoot '.cache'),
    (Join-Path $projectRoot 'archive'),
    (Join-Path $projectRoot 'docs\archive'),
    (Join-Path $projectRoot 'media')
)

if ($IncludeMedia) {
    $excludeDirPaths = $excludeDirPaths | Where-Object { $_ -ne (Join-Path $projectRoot 'media') }
}

$excludeFilePatterns = @(
    '*.7z',
    '*.egg',
    '*.egg-info',
    '*.log',
    '*.pyc',
    '*.pyd',
    '*.pyo',
    '*.tmp',
    '.coverage',
    '.env',
    'Thumbs.db'
)

if ($IncludeEnv) {
    $excludeFilePatterns = $excludeFilePatterns | Where-Object { $_ -ne '.env' }
}

if (-not $IncludeDatabase) {
    $excludeFilePatterns += @('*.sqlite3', 'celerybeat-schedule*')
}

$excludeFilePaths = @(
    (Join-Path $projectRoot 'scripts\deploy-bundle-to-vps.py'),
    (Join-Path $projectRoot 'scripts\deploy-on-vps.ps1'),
    (Join-Path $projectRoot 'scripts\deploy-on-vps.sh'),
    (Join-Path $projectRoot 'scripts\deploy-one-click.sh'),
    (Join-Path $projectRoot 'scripts\inject-sqlite-into-bundle.ps1'),
    (Join-Path $projectRoot 'scripts\package-for-vps-aggressive.ps1'),
    (Join-Path $projectRoot 'scripts\package-for-vps.ps1'),
    (Join-Path $projectRoot 'scripts\remote_build_deploy_vps.py'),
    (Join-Path $projectRoot 'scripts\verify-vps-bundle.ps1'),
    (Join-Path $projectRoot 'scripts\vps-backup.ps1'),
    (Join-Path $projectRoot 'scripts\vps-backup.sh'),
    (Join-Path $projectRoot 'scripts\vps-restore.ps1'),
    (Join-Path $projectRoot 'scripts\vps-restore.sh')
)

$existingExcludeDirs = @($excludeDirPaths | Where-Object { Test-Path $_ })
$existingExcludeFiles = @($excludeFilePaths | Where-Object { Test-Path $_ })

Write-Info "Project root: $projectRoot"
Write-Info "Output archive: $archivePath"
Write-Info "Archive format: $resolvedFormat"

if ($DryRun) {
    Write-Info "Dry run only. No files will be copied or archived."
    Write-Host ""
    Write-Host "Excluded directory names:" -ForegroundColor White
    $excludeDirNames | Sort-Object | ForEach-Object { Write-Host "  - $_" }
    Write-Host ""
    Write-Host "Excluded directory paths:" -ForegroundColor White
    $existingExcludeDirs | Sort-Object | ForEach-Object { Write-Host "  - $_" }
    Write-Host ""
    Write-Host "Excluded file patterns:" -ForegroundColor White
    $excludeFilePatterns | Sort-Object | ForEach-Object { Write-Host "  - $_" }
    Write-Host ""
    Write-Host "Excluded file paths:" -ForegroundColor White
    $existingExcludeFiles | Sort-Object | ForEach-Object { Write-Host "  - $_" }
    exit 0
}

try {
    New-Item -ItemType Directory -Path $stageRoot -Force | Out-Null

    $robocopyArgs = @(
        $projectRoot,
        $stageRoot,
        '/E',
        '/R:0',
        '/W:0',
        '/NFL',
        '/NDL',
        '/NJH',
        '/NJS',
        '/NP',
        '/XD'
    ) + $excludeDirNames + $existingExcludeDirs + @('/XF') + $excludeFilePatterns + $existingExcludeFiles

    Write-Info "Copying project into staging directory"
    & robocopy @robocopyArgs | Out-Null
    $robocopyCode = $LASTEXITCODE
    if ($robocopyCode -ge 8) {
        throw "robocopy failed with exit code $robocopyCode"
    }

    New-PortableReadme -TargetFile (Join-Path $stageRoot 'PORTABLE_PACKAGE_README.txt') -ProjectName $projectName

    if (Test-Path $archivePath) {
        Remove-Item $archivePath -Force
    }

    if ($resolvedFormat -eq '7z') {
        Write-Info "Creating 7z archive"
        Push-Location $tempRoot
        try {
            & $sevenZip a -t7z -mx=5 $archivePath $projectName | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw "7-Zip failed with exit code $LASTEXITCODE"
            }
        } finally {
            Pop-Location
        }
    } else {
        Write-Info "Creating zip archive"
        Compress-Archive -Path $stageRoot -DestinationPath $archivePath -CompressionLevel Optimal
    }

    $sizeMb = "{0:N2}" -f ((Get-Item $archivePath).Length / 1MB)
    Write-Ok "Portable package created: $archivePath ($sizeMb MB)"
    Write-Host ""
    Write-Host "Default exclusions applied:" -ForegroundColor White
    Write-Host "  - git metadata, local venvs, caches, logs, dist/output/reports"
    Write-Host "  - local SQLite DB and .env unless explicitly included"
    Write-Host "  - VPS/bundle deployment scripts not needed for local bring-up"
} finally {
    if (Test-Path $tempRoot) {
        Remove-Item $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
