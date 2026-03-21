# AgomTradePro Docker Management Menu
# Interactive menu for common Docker operations

$ProjectRoot = "D:\githv\agomTradePro"
$ComposeFile = "$ProjectRoot\docker-compose-dev.yml"

# Color functions
function Write-Header { Write-Host $args -ForegroundColor Cyan }
function Write-Success { Write-Host $args -ForegroundColor Green }
function Write-Warning { Write-Host $args -ForegroundColor Yellow }
function Write-Error { Write-Host $args -ForegroundColor Red }
function Write-Info { Write-Host $args -ForegroundColor White }
function Write-MenuItem { Write-Host $args -ForegroundColor Gray }

# Check if Docker is running
function Test-Docker {
    $null = docker ps 2>&1
    return $LASTEXITCODE -eq 0
}

# Show service status
function Show-Status {
    Write-Header "`n=== Docker Service Status ===`n"
    docker-compose -f $ComposeFile ps
    Write-Host ""
}

# Start services
function Start-Services {
    Write-Header "`n=== Starting Docker Services ===`n"
    docker-compose -f $ComposeFile up -d

    Write-Info "`nWaiting for services to be ready..."
    Start-Sleep -Seconds 3

    $attempt = 0
    while ($attempt -lt 30) {
        $null = docker exec agomtradepro_postgres_dev pg_isready -U agomtradepro -d agomtradepro 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Success "`nPostgreSQL is ready!"
            break
        }
        $attempt++
        Start-Sleep -Seconds 1
        Write-Host "." -NoNewline
    }

    Show-Status
}

# Stop services
function Stop-Services {
    Write-Header "`n=== Stopping Docker Services ===`n"
    docker-compose -f $ComposeFile down
    Write-Success "`nServices stopped!"
}

# Restart services
function Restart-Services {
    Write-Header "`n=== Restarting Docker Services ===`n"
    docker-compose -f $ComposeFile restart
    Start-Sleep -Seconds 2
    Show-Status
}

# View logs
function Show-Logs {
    Write-Header "`n=== View Logs ===`n"
    Write-Info "Select service to view logs:"
    Write-Info "1. All services"
    Write-Info "2. PostgreSQL"
    Write-Info "3. Redis"
    Write-Info "0. Back to menu"

    $choice = Read-Host "`nEnter choice"

    switch ($choice) {
        "1" { docker-compose -f $ComposeFile logs -f }
        "2" { docker-compose -f $ComposeFile logs -f postgres }
        "3" { docker-compose -f $ComposeFile logs -f redis }
        "0" { return }
        default { Write-Error "Invalid choice" }
    }
}

# Execute database migrations
function Run-Migrations {
    Write-Header "`n=== Running Database Migrations ===`n"

    $pythonCmd = "$ProjectRoot\agomtradepro\Scripts\python.exe"
    if (-not (Test-Path $pythonCmd)) {
        $pythonCmd = "python"
    }

    & $pythonCmd manage.py migrate
    Write-Success "`nMigrations completed!"
}

# Create superuser
function Create-Superuser {
    Write-Header "`n=== Create Django Superuser ===`n"

    $pythonCmd = "$ProjectRoot\agomtradepro\Scripts\python.exe"
    if (-not (Test-Path $pythonCmd)) {
        $pythonCmd = "python"
    }

    & $pythonCmd manage.py createsuperuser
}

# Connect to PostgreSQL
function Connect-PostgreSQL {
    Write-Header "`n=== Connecting to PostgreSQL ===`n"
    Write-Info "Type '\q' to exit"
    Write-Host ""

    docker exec -it agomtradepro_postgres_dev psql -U agomtradepro -d agomtradepro
}

# Connect to Redis
function Connect-Redis {
    Write-Header "`n=== Connecting to Redis ===`n"
    Write-Info "Type 'exit' to quit"
    Write-Host ""

    docker exec -it agomtradepro_redis_dev redis-cli
}

# Backup database
function Backup-Database {
    Write-Header "`n=== Backup PostgreSQL Database ===`n"

    Write-Info "Backup options:"
    Write-Info "1. Full backup (all data)"
    Write-Info "2. Schema only (no data)"
    Write-Info "3. Data only (no schema)"
    Write-Info "4. Specific tables"
    Write-Info "5. List existing backups"
    Write-Info "6. Delete old backups"
    Write-Info "0. Back to menu"

    $choice = Read-Host "`nSelect option"

    switch ($choice) {
        "1" {
            $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
            $backupFile = "$ProjectRoot\backup-postgres-$timestamp.sql"
            Write-Info "Creating full backup..."
            docker exec agomtradepro_postgres_dev pg_dump -U agomtradepro -d agomtradepro > $backupFile

            if (Test-Path $backupFile) {
                $size = [math]::Round((Get-Item $backupFile).Length / 1KB, 2)
                Write-Success "`nBackup completed! Size: $size KB"
                Write-Info "File: $backupFile"
            }
            else {
                Write-Error "Backup failed!"
            }
        }
        "2" {
            $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
            $backupFile = "$ProjectRoot\backup-schema-$timestamp.sql"
            Write-Info "Creating schema backup..."
            docker exec agomtradepro_postgres_dev pg_dump -U agomtradepro -d agomtradepro --schema-only > $backupFile

            if (Test-Path $backupFile) {
                $size = [math]::Round((Get-Item $backupFile).Length / 1KB, 2)
                Write-Success "`nSchema backup completed! Size: $size KB"
                Write-Info "File: $backupFile"
            }
            else {
                Write-Error "Backup failed!"
            }
        }
        "3" {
            $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
            $backupFile = "$ProjectRoot\backup-data-$timestamp.sql"
            Write-Info "Creating data backup..."
            docker exec agomtradepro_postgres_dev pg_dump -U agomtradepro -d agomtradepro --data-only > $backupFile

            if (Test-Path $backupFile) {
                $size = [math]::Round((Get-Item $backupFile).Length / 1KB, 2)
                Write-Success "`nData backup completed! Size: $size KB"
                Write-Info "File: $backupFile"
            }
            else {
                Write-Error "Backup failed!"
            }
        }
        "4" {
            Write-Info "Available tables:"
            docker exec agomtradepro_postgres_dev psql -U agomtradepro -d agomtradepro -c "\dt" | Write-Host

            $tables = Read-Host "`nEnter table names (comma separated)"
            $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
            $backupFile = "$ProjectRoot\backup-tables-$timestamp.sql"

            Write-Info "Creating table backup..."
            docker exec agomtradepro_postgres_dev pg_dump -U agomtradepro -d agomtradepro -t $tables > $backupFile

            if (Test-Path $backupFile) {
                $size = [math]::Round((Get-Item $backupFile).Length / 1KB, 2)
                Write-Success "`nTable backup completed! Size: $size KB"
                Write-Info "File: $backupFile"
            }
            else {
                Write-Error "Backup failed!"
            }
        }
        "5" {
            Write-Header "`n=== Existing Backups ===`n"
            $backupDir = "$ProjectRoot\backups"
            if (Test-Path $backupDir) {
                $files = Get-ChildItem $backupDir -Filter "*.sql" | Sort-Object LastWriteTime -Descending
            }
            else {
                $files = Get-ChildItem $ProjectRoot -Filter "backup-*.sql" | Sort-Object LastWriteTime -Descending
            }

            if ($files.Count -eq 0) {
                Write-Info "No backup files found in project directory"
            }
            else {
                Write-Info "Found $($files.Count) backup file(s):`n"
                foreach ($file in $files) {
                    $size = [math]::Round($file.Length / 1KB, 2)
                    Write-Info "  - $($file.Name)"
                    Write-Info "    Size: $size KB | Date: $($file.LastWriteTime)"
                }
            }
        }
        "6" {
            Write-Header "`n=== Delete Old Backups ===`n"
            $backupDir = "$ProjectRoot\backups"
            if (-not (Test-Path $backupDir)) {
                $backupDir = $ProjectRoot
            }

            $files = Get-ChildItem $backupDir -Filter "backup-*.sql" | Sort-Object LastWriteTime -Descending

            if ($files.Count -eq 0) {
                Write-Info "No backup files found"
                return
            }

            Write-Info "Found $($files.Count) backup file(s):`n"
            for ($i = 0; $i -lt $files.Count; $i++) {
                $file = $files[$i]
                $size = [math]::Round($file.Length / 1KB, 2)
                Write-Info "  [$($i + 1)] $($file.Name) - $size KB - $($file.LastWriteTime)"
            }

            Write-Warning "`nDelete backups older than days:"
            Write-Info "1. 7 days"
            Write-Info "2. 30 days"
            Write-Info "3. 90 days"
            Write-Info "4. All backups"
            Write-Info "0. Cancel"

            $deleteChoice = Read-Host "`nSelect option"

            $days = switch ($deleteChoice) {
                "1" { 7 }
                "2" { 30 }
                "3" { 90 }
                "4" { 0 }
                "0" { return }
                default { return }
            }

            $cutoffDate = (Get-Date).AddDays(-$days)
            $toDelete = @()

            if ($days -eq 0) {
                $toDelete = $files
            }
            else {
                foreach ($file in $files) {
                    if ($file.LastWriteTime -lt $cutoffDate) {
                        $toDelete += $file
                    }
                }
            }

            if ($toDelete.Count -eq 0) {
                Write-Info "No backups to delete"
                return
            }

            Write-Warning "`nWill delete $($toDelete.Count) file(s):"
            foreach ($file in $toDelete) {
                Write-Error "  - $($file.Name)"
            }

            $confirm = Read-Host "`nConfirm deletion? (y/N)"
            if ($confirm -eq "y" -or $confirm -eq "Y") {
                foreach ($file in $toDelete) {
                    Remove-Item $file.FullName
                    Write-Info "Deleted: $($file.Name)"
                }
                Write-Success "`nDeleted $($toDelete.Count) file(s)"
            }
            else {
                Write-Info "Cancelled"
            }
        }
        "0" { return }
        default { Write-Error "Invalid option" }
    }
}

# Restore database
function Restore-Database {
    Write-Header "`n=== Restore PostgreSQL Database ===`n"

    $backupFiles = Get-ChildItem $ProjectRoot -Filter "backup-postgres-*.sql" | Sort-Object LastWriteTime -Descending

    if ($backupFiles.Count -eq 0) {
        Write-Warning "No backup files found in $ProjectRoot"
        return
    }

    Write-Info "Available backup files:"
    for ($i = 0; $i -lt $backupFiles.Count; $i++) {
        $file = $backupFiles[$i]
        $size = [math]::Round($file.Length / 1KB, 2)
        Write-Info "  $($i + 1). $($file.Name) ($size KB) - $($file.LastWriteTime)"
    }

    $choice = Read-Host "`nSelect backup to restore (1-$($backupFiles.Count))"
    $selectedIndex = [int]$choice - 1

    if ($selectedIndex -lt 0 -or $selectedIndex -ge $backupFiles.Count) {
        Write-Error "Invalid selection"
        return
    }

    $selectedFile = $backupFiles[$selectedIndex].FullName

    Write-Warning "`nWARNING: This will replace all data in the database!"
    $confirm = Read-Host "Continue? (y/N)"

    if ($confirm -ne "y" -and $confirm -ne "Y") {
        Write-Info "Cancelled"
        return
    }

    Write-Info "Restoring from: $selectedFile"
    Get-Content $selectedFile | docker exec -i agomtradepro_postgres_dev psql -U agomtradepro -d agomtradepro

    Write-Success "`nRestore completed!"
}

# Reset database
function Reset-Database {
    Write-Header "`n=== Reset Database ===`n"

    Write-Error "WARNING: This will delete ALL data!"
    Write-Error "This action cannot be undone!"
    $confirm = Read-Host "`nType 'RESET' to confirm"

    if ($confirm -ne "RESET") {
        Write-Info "Cancelled"
        return
    }

    Write-Info "Stopping services..."
    docker-compose -f $ComposeFile down -v

    Write-Info "Starting services..."
    docker-compose -f $ComposeFile up -d

    Write-Info "Waiting for services..."
    Start-Sleep -Seconds 5

    Write-Info "Running migrations..."
    $pythonCmd = "$ProjectRoot\agomtradepro\Scripts\python.exe"
    if (-not (Test-Path $pythonCmd)) {
        $pythonCmd = "python"
    }
    & $pythonCmd manage.py migrate

    Write-Success "`nDatabase reset completed!"
}

# Clean up Docker resources
function Clean-Docker {
    Write-Header "`n=== Clean Docker Resources ===`n"

    Write-Info "Select cleanup level:"
    Write-Info "1. Remove stopped containers"
    Write-Info "2. Remove unused images"
    Write-Info "3. Remove unused volumes (DANGEROUS!)"
    Write-Info "4. Full cleanup (containers + images)"
    Write-Info "0. Back to menu"

    $choice = Read-Host "`nEnter choice"

    switch ($choice) {
        "1" {
            Write-Info "Removing stopped containers..."
            docker container prune -f
            Write-Success "Done!"
        }
        "2" {
            Write-Info "Removing unused images..."
            docker image prune -a -f
            Write-Success "Done!"
        }
        "3" {
            Write-Warning "This will remove ALL unused volumes!"
            $confirm = Read-Host "Continue? (y/N)"
            if ($confirm -eq "y" -or $confirm -eq "Y") {
                Write-Info "Removing unused volumes..."
                docker volume prune -f
                Write-Success "Done!"
            }
            else {
                Write-Info "Cancelled"
            }
        }
        "4" {
            Write-Info "Removing containers and images..."
            docker container prune -f
            docker image prune -a -f
            Write-Success "Done!"
        }
        "0" { return }
        default { Write-Error "Invalid choice" }
    }
}

# Show service URLs
function Show-Urls {
    Write-Header "`n=== Service URLs ===`n"
    Write-Info "Django Web:     http://localhost:8000"
    Write-Info "Admin Panel:    http://localhost:8000/admin/"
    Write-Info "API Docs:       http://localhost:8000/api/docs/"
    Write-Info "PostgreSQL:     localhost:5432"
    Write-Info "Redis:          localhost:6379"
    Write-Host ""
}

# Setup scheduled backup
function Setup-ScheduledBackup {
    Write-Header "`n=== Setup Scheduled Backup ===`n"

    Write-Info "This will create a Windows Task Scheduler job for automatic backups"
    Write-Info "Backups will be stored in: $ProjectRoot\backups"
    Write-Host ""

    Write-Info "Select backup frequency:"
    Write-Info "1. Daily"
    Write-Info "2. Weekly"
    Write-Info "3. Custom"
    Write-Info "0. Cancel"

    $freqChoice = Read-Host "`nEnter choice"

    $trigger = switch ($freqChoice) {
        "1" { "Daily" }
        "2" { "Weekly" }
        "0" { return }
        default { "Custom" }
    }

    $time = Read-Host "Enter time (24h format, e.g., 02:00)"
    $keepDays = Read-Host "Keep backups for how many days? (default: 7)"

    if ([string]::IsNullOrWhiteSpace($keepDays)) {
        $keepDays = 7
    }

    $taskName = "AgomTradePro-AutoBackup"
    $scriptPath = "$ProjectRoot\scripts\auto-backup.ps1"
    $action = New-ScheduledTaskAction -Execute "PowerShell.exe" -Argument "-ExecutionPolicy Bypass -File `"$scriptPath`" -KeepDays $keepDays"

    Write-Info "`nCreating scheduled task..."

    try {
        switch ($trigger) {
            "Daily" {
                $triggerObj = New-ScheduledTaskTrigger -Daily -At $time
            }
            "Weekly" {
                $day = Read-Host "Enter day (0=Sunday, 1=Monday, ..., 6=Saturday)"
                $triggerObj = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $day -At $time
            }
            "Custom" {
                Write-Info "Custom schedule - you'll need to modify in Task Scheduler"
                $triggerObj = New-ScheduledTaskTrigger -Once -At (Get-Date) -RecurInterval 1 -RepetitionDuration ([TimeSpan]::MaxValue)
            }
        }

        Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggerObj -Description "AgomTradePro PostgreSQL automatic backup" -User $env:USERNAME

        Write-Success "`nScheduled task created successfully!"
        Write-Info "Task name: $taskName"
        Write-Info "You can modify it in Task Scheduler (taskschd.msc)"
        Write-Info "`nTo manage scheduled tasks:"
        Write-Info "  - Open Task Scheduler: taskschd.msc"
        Write-Info "  - Find: AgomTradePro-AutoBackup"
        Write-Info "  - Run/Pause/Disable as needed"
    }
    catch {
        Write-Error "Failed to create scheduled task: $_"
        Write-Info "`nYou can create it manually in Task Scheduler:"
        Write-Info "  Script: $scriptPath"
        Write-Info "  Args: -ExecutionPolicy Bypass -File `"$scriptPath`" -KeepDays $keepDays"
    }
}

# System info
function Show-SystemInfo {
    Write-Header "`n=== System Information ===`n"

    Write-Info "Docker version:"
    docker --version
    Write-Host ""

    Write-Info "Docker Compose version:"
    docker-compose --version
    Write-Host ""

    Write-Info "Running containers:"
    docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    Write-Host ""

    Write-Info "Disk usage:"
    docker system df
    Write-Host ""
}

# Shell access to container
function Shell-Access {
    Write-Header "`n=== Container Shell Access ===`n"
    Write-Info "Select container:"
    Write-Info "1. PostgreSQL"
    Write-Info "2. Redis"
    Write-Info "0. Back to menu"

    $choice = Read-Host "`nEnter choice"

    switch ($choice) {
        "1" {
            Write-Info "Opening shell in PostgreSQL container..."
            Write-Info "Type 'exit' to quit"
            docker exec -it agomtradepro_postgres_dev sh
        }
        "2" {
            Write-Info "Opening shell in Redis container..."
            Write-Info "Type 'exit' to quit"
            docker exec -it agomtradepro_redis_dev sh
        }
        "0" { return }
        default { Write-Error "Invalid choice" }
    }
}

# Main menu
function Show-Menu {
    Clear-Host
    Write-Header "========================================"
    Write-Header "  AgomTradePro Docker Management Menu"
    Write-Header "========================================`n"

    # Show service status
    Write-Info "Service Status:"
    docker-compose -f $ComposeFile ps --format "table {{.Service}}\t{{.Status}}\t{{.Ports}}" 2>$null
    Write-Host ""

    Write-Header "--- Service Management ---"
    Write-MenuItem "  1. Start services"
    Write-MenuItem "  2. Stop services"
    Write-MenuItem "  3. Restart services"
    Write-MenuItem "  4. View service status"
    Write-MenuItem "  5. View logs"

    Write-Header "`n--- Database Operations ---"
    Write-MenuItem "  6. Run migrations"
    Write-MenuItem "  7. Create superuser"
    Write-MenuItem "  8. Connect to PostgreSQL"
    Write-MenuItem "  9. Connect to Redis"
    Write-MenuItem " 10. Backup database (enhanced)"
    Write-MenuItem " 11. Restore database"
    Write-MenuItem " 12. Auto backup now"
    Write-MenuItem " 13. Reset database (DANGER!)"

    Write-Header "`n--- Maintenance ---"
    Write-MenuItem " 14. Clean Docker resources"
    Write-MenuItem " 15. Container shell access"
    Write-MenuItem " 16. System information"
    Write-MenuItem " 17. Show service URLs"
    Write-MenuItem " 18. Setup scheduled backup"

    Write-Header "`n--- Other ---"
    Write-MenuItem "  0. Exit"
    Write-Host ""
}

# Main loop
function Main {
    # Check if Docker is running
    if (-not (Test-Docker)) {
        Write-Error "Docker is not running!"
        Write-Info "Please start Docker Desktop and try again."
        Read-Host "`nPress Enter to exit"
        exit 1
    }

    while ($true) {
        Show-Menu
        $choice = Read-Host "Select an option"

        switch ($choice) {
            "1" { Start-Services }
            "2" { Stop-Services }
            "3" { Restart-Services }
            "4" { Show-Status }
            "5" { Show-Logs }
            "6" { Run-Migrations }
            "7" { Create-Superuser }
            "8" { Connect-PostgreSQL }
            "9" { Connect-Redis }
            "10" { Backup-Database }
            "11" { Restore-Database }
            "12" {
                Write-Header "`n=== Auto Backup ===`n"
                & "$ProjectRoot\scripts\auto-backup.ps1" -KeepDays 7
            }
            "13" { Reset-Database }
            "14" { Clean-Docker }
            "15" { Shell-Access }
            "16" { Show-SystemInfo }
            "17" { Show-Urls }
            "18" { Setup-ScheduledBackup }
            "0" {
                Write-Info "Exiting..."
                exit 0
            }
            default {
                Write-Error "Invalid option. Please try again."
            }
        }

        Write-Host ""
        Read-Host "Press Enter to continue"
    }
}

# Run main function
Main
