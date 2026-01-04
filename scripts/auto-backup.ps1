# AgomSAAF Auto Backup Script
# Run this script manually or schedule it with Windows Task Scheduler

param(
    [int]$KeepDays = 7,  # Keep backups for 7 days by default
    [string]$BackupDir = "D:\githv\agomSAAF\backups"
)

# Color output
function Write-Success { Write-Host $args -ForegroundColor Green }
function Write-Info { Write-Host $args -ForegroundColor Cyan }
function Write-Warning { Write-Host $args -ForegroundColor Yellow }
function Write-Error { Write-Host $args -ForegroundColor Red }

$ProjectRoot = "D:\githv\agomSAAF"
$ComposeFile = "$ProjectRoot\docker-compose-dev.yml"

# Create backup directory if not exists
if (-not (Test-Path $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
}

# Generate timestamp
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupFile = "$BackupDir\backup-postgres-$timestamp.sql"

Write-Info "=========================================="
Write-Info " AgomSAAF Auto Backup"
Write-Info "==========================================`n"

# Check if Docker is running
$null = docker ps 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker is not running!"
    exit 1
}

# Check if PostgreSQL container is running
$pgRunning = docker ps --filter "name=agomsaaf_postgres_dev" --format "{{.Names}}" 2>&1
if ($pgRunning -ne "agomsaaf_postgres_dev") {
    Write-Error "PostgreSQL container is not running!"
    exit 1
}

Write-Info "Creating backup: $backupFile"

# Create backup
docker exec agomsaaf_postgres_dev pg_dump -U agomsaaf -d agomsaaf > $backupFile

if (-not (Test-Path $backupFile)) {
    Write-Error "Backup failed!"
    exit 1
}

$size = [math]::Round((Get-Item $backupFile).Length / 1KB, 2)
Write-Success "Backup completed! Size: $size KB"

# Clean old backups
Write-Info "`nCleaning old backups (older than $KeepDays days)..."

$cutoffDate = (Get-Date).AddDays(-$KeepDays)
$files = Get-ChildItem $BackupDir -Filter "backup-*.sql" | Where-Object { $_.LastWriteTime -lt $cutoffDate }

if ($files.Count -gt 0) {
    foreach ($file in $files) {
        Remove-Item $file.FullName
        Write-Info "Deleted: $($file.Name)"
    }
    Write-Success "Cleaned $($files.Count) old backup(s)"
}
else {
    Write-Info "No old backups to clean"
}

# Show backup summary
Write-Info "`n=========================================="
Write-Info " Current Backups"
Write-Info "==========================================`n"

$allBackups = Get-ChildItem $BackupDir -Filter "backup-*.sql" | Sort-Object LastWriteTime -Descending
Write-Info "Total backups: $($allBackups.Count)"
$totalSize = [math]::Round(($allBackups | Measure-Object -Property Length -Sum).Sum / 1MB, 2)
Write-Info "Total size: $totalSize MB"

Write-Success "`nBackup task completed!"
