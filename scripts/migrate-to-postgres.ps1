# AgomSAAF Data Migration Script
# Migrate data from SQLite to PostgreSQL

param(
    [switch]$SkipBackup,
    [string]$BackupFile = "sqlite-backup.json"
)

# Color output functions
function Write-ColorOutput($ForegroundColor) {
    $fc = $host.UI.RawUI.ForegroundColor
    $host.UI.RawUI.ForegroundColor = $ForegroundColor
    if ($args) {
        Write-Output $args
    }
    $host.UI.RawUI.ForegroundColor = $fc
}

function Write-Success { Write-ColorOutput Green $args }
function Write-Info { Write-ColorOutput Cyan $args }
function Write-Warning { Write-ColorOutput Yellow $args }
function Write-Error { Write-ColorOutput Red $args }

# Get script directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

Write-Info "`n=========================================="
Write-Info " AgomSAAF SQLite -> PostgreSQL Migration"
Write-Info "==========================================`n"

$composeFile = Join-Path $ProjectRoot "docker-compose-dev.yml"
$pythonCmd = "agomsaaf/Scripts/python.exe"
$pythonCmdAlt = "D:/githv/agomSAAF/agomsaaf/Scripts/python.exe"

# Detect Python command
if (Test-Path $pythonCmd) {
    # Use relative path
}
elseif (Test-Path $pythonCmdAlt) {
    $pythonCmd = $pythonCmdAlt
}
else {
    # Try to use python in virtual environment
    $pythonCmd = "agomsaaf/Scripts/python.exe"
}

# ============================================
# Step 1: Check SQLite database
# ============================================
Write-Info "[1/5] Checking SQLite database..."

$sqliteDb = Join-Path $ProjectRoot "db.sqlite3"

if (-not (Test-Path $sqliteDb)) {
    Write-Warning "  SQLite database not found (db.sqlite3)"
    Write-Info "  If this is a fresh install, you can run migration to create empty database"
    $response = Read-Host "  Continue? (y/N)"

    if ($response -ne "y" -and $response -ne "Y") {
        Write-Info "  Cancelled"
        exit 0
    }
}
else {
    $dbSize = (Get-Item $sqliteDb).Length / 1KB
    Write-Success "  SQLite database found (size: $([math]::Round($dbSize, 2)) KB)"
}

# ============================================
# Step 2: Backup SQLite data
# ============================================
if (-not $SkipBackup) {
    Write-Info "`n[2/5] Backing up SQLite data..."

    if (Test-Path $sqliteDb) {
        $backupPath = Join-Path $ProjectRoot $BackupFile

        # Create backup directory
        $backupDir = Split-Path -Parent $backupPath
        if (-not (Test-Path $backupDir)) {
            New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
        }

        Write-Info "  Exporting data to $BackupFile ..."
        $dumpCmd = "& `"$pythonCmd`" manage.py dumpdata --exclude contenttypes --exclude auth.Permission --indent 2 > `"$backupPath`""

        try {
            Invoke-Expression $dumpCmd

            if (Test-Path $backupPath) {
                $backupSize = (Get-Item $backupPath).Length / 1KB
                Write-Success "  Backup completed (size: $([math]::Round($backupSize, 2)) KB)"
                Write-Info "  Backup file: $backupPath"
            }
            else {
                Write-Error "  Backup failed"
                exit 1
            }
        }
        catch {
            Write-Error "  Backup failed: $_"
            exit 1
        }
    }
    else {
        Write-Info "  Skipping backup (SQLite database not found)"
    }
}
else {
    Write-Info "`n[2/5] Skipping backup"
}

# ============================================
# Step 3: Check Docker services
# ============================================
Write-Info "`n[3/5] Checking Docker services..."

try {
    $null = docker ps 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error "  Docker not running"
        exit 1
    }

    # Check if PostgreSQL container is running
    $pgRunning = docker ps --filter "name=agomsaaf_postgres_dev" --format "{{.Names}}" 2>&1

    if ($pgRunning -eq "agomsaaf_postgres_dev") {
        Write-Success "  PostgreSQL container is running"
    }
    else {
        Write-Warning "  PostgreSQL container not running"
        Write-Info "  Starting Docker services..."

        docker-compose -f $composeFile up -d 2>&1 | Out-Null

        if ($LASTEXITCODE -ne 0) {
            Write-Error "  Failed to start"
            exit 1
        }

        Write-Info "  Waiting for services to be ready..."
        Start-Sleep -Seconds 5

        # Check if service is ready
        $maxAttempts = 30
        $attempt = 0

        while ($attempt -lt $maxAttempts) {
            $null = docker exec agomsaaf_postgres_dev pg_isready -U agomsaaf -d agomsaaf 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Success "  Services are ready"
                break
            }
            $attempt++
            Start-Sleep -Seconds 1
            Write-Host "." -NoNewline
        }
    }
}
catch {
    Write-Error "  Error: $_"
    exit 1
}

# ============================================
# Step 4: Execute database migration
# ============================================
Write-Info "`n[4/5] Executing database migration..."

Write-Warning "  WARNING: This will clear existing data in PostgreSQL database"
$response = Read-Host "  Continue? (y/N)"

if ($response -ne "y" -and $response -ne "Y") {
    Write-Info "  Cancelled"
    exit 0
}

# Ensure .env uses PostgreSQL connection
Write-Info "  Checking .env configuration..."

$envFile = Join-Path $ProjectRoot ".env"
if (Test-Path $envFile) {
    $envContent = Get-Content $envFile -Raw

    # Ensure PostgreSQL is used
    if ($envContent -match 'DATABASE_URL=sqlite:') {
        Write-Warning "  .env still uses SQLite, updating..."

        $envContent = $envContent -replace 'DATABASE_URL=sqlite:.*', 'DATABASE_URL=postgresql://agomsaaf:changeme@localhost:5432/agomsaaf'
        Set-Content -Path $envFile -Value $envContent

        Write-Success "  Updated to PostgreSQL connection"
    }
    else {
        Write-Success "  .env configuration is correct"
    }
}

# Execute migration
Write-Info "  Running database migration..."

try {
    & "$pythonCmd" manage.py migrate --noinput 2>&1 | ForEach-Object {
        if ($_ -match "Running migrations:") {
            Write-Info "    $_"
        }
        elseif ($_ -match "Applying") {
            Write-Host "      $_" -ForegroundColor Gray
        }
    }

    Write-Success "  Migration completed"
}
catch {
    Write-Error "  Migration failed: $_"
    exit 1
}

# ============================================
# Step 5: Restore data
# ============================================
if ((Test-Path $sqliteDb) -and -not $SkipBackup) {
    Write-Info "`n[5/5] Restoring data to PostgreSQL..."

    $backupPath = Join-Path $ProjectRoot $BackupFile

    if (Test-Path $backupPath) {
        Write-Info "  Restoring data from backup file..."

        try {
            & "$pythonCmd" manage.py loaddata "`"$backupPath`"" 2>&1 | ForEach-Object {
                Write-Host "      $_" -ForegroundColor Gray
            }

            Write-Success "  Data restoration completed"
        }
        catch {
            Write-Warning "  Restoration failed: $_"
            Write-Info "  Please run manually: python manage.py loaddata $BackupFile"
        }
    }
    else {
        Write-Warning "  Backup file not found, skipping restoration"
    }
}
else {
    Write-Info "`n[5/5] Skipping data restoration"
}

# ============================================
# Complete
# ============================================
Write-Success "`n=========================================="
Write-Success " Migration Complete!"
Write-Success "==========================================`n"

Write-Info "Next Steps:"
Write-Info "  1. Test database connection:"
Write-Info "     python manage.py check"
Write-Info "`n  2. Create superuser:"
Write-Info "     python manage.py createsuperuser"
Write-Info "`n  3. Start development server:"
Write-Info "     python manage.py runserver"
Write-Info "`n  4. Access application: http://localhost:8000"

Write-Info "`nBackup file location:"
Write-Info "  $backupPath"

Write-Warning "`nImportant notes:"
Write-Warning "  - SQLite original file (db.sqlite3) is still preserved"
Write-Warning "  - Recommended to keep backup for a while until data is verified"
Write-Warning "  - To rollback, change DATABASE_URL in .env to sqlite:///db.sqlite3"
