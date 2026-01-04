# AgomSAAF Docker Management Menu
# Interactive menu for common Docker operations

$ProjectRoot = "D:\githv\agomSAAF"
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
        $null = docker exec agomsaaf_postgres_dev pg_isready -U agomsaaf -d agomsaaf 2>&1
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

    $pythonCmd = "$ProjectRoot\agomsaaf\Scripts\python.exe"
    if (-not (Test-Path $pythonCmd)) {
        $pythonCmd = "python"
    }

    & $pythonCmd manage.py migrate
    Write-Success "`nMigrations completed!"
}

# Create superuser
function Create-Superuser {
    Write-Header "`n=== Create Django Superuser ===`n"

    $pythonCmd = "$ProjectRoot\agomsaaf\Scripts\python.exe"
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

    docker exec -it agomsaaf_postgres_dev psql -U agomsaaf -d agomsaaf
}

# Connect to Redis
function Connect-Redis {
    Write-Header "`n=== Connecting to Redis ===`n"
    Write-Info "Type 'exit' to quit"
    Write-Host ""

    docker exec -it agomsaaf_redis_dev redis-cli
}

# Backup database
function Backup-Database {
    Write-Header "`n=== Backup PostgreSQL Database ===`n"

    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $backupFile = "$ProjectRoot\backup-postgres-$timestamp.sql"

    Write-Info "Backing up to: $backupFile"
    docker exec agomsaaf_postgres_dev pg_dump -U agomsaaf agomsaaf > $backupFile

    if (Test-Path $backupFile) {
        $size = (Get-Item $backupFile).Length / 1KB
        Write-Success "`nBackup completed! Size: $([math]::Round($size, 2)) KB"
        Write-Info "File: $backupFile"
    }
    else {
        Write-Error "Backup failed!"
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
    Get-Content $selectedFile | docker exec -i agomsaaf_postgres_dev psql -U agomsaaf -d agomsaaf

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
    $pythonCmd = "$ProjectRoot\agomsaaf\Scripts\python.exe"
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
            docker exec -it agomsaaf_postgres_dev sh
        }
        "2" {
            Write-Info "Opening shell in Redis container..."
            Write-Info "Type 'exit' to quit"
            docker exec -it agomsaaf_redis_dev sh
        }
        "0" { return }
        default { Write-Error "Invalid choice" }
    }
}

# Main menu
function Show-Menu {
    Clear-Host
    Write-Header "========================================"
    Write-Header "  AgomSAAF Docker Management Menu"
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
    Write-MenuItem " 10. Backup database"
    Write-MenuItem " 11. Restore database"
    Write-MenuItem " 12. Reset database (DANGER!)"

    Write-Header "`n--- Maintenance ---"
    Write-MenuItem " 13. Clean Docker resources"
    Write-MenuItem " 14. Container shell access"
    Write-MenuItem " 15. System information"
    Write-MenuItem " 16. Show service URLs"

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
            "12" { Reset-Database }
            "13" { Clean-Docker }
            "14" { Shell-Access }
            "15" { Show-SystemInfo }
            "16" { Show-Urls }
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
