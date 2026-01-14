# AgomSAAF Development Environment Startup Script

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " AgomSAAF Development Environment" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Activate virtual environment
Write-Host "[1/3] Activating agomsaaf virtual environment..." -ForegroundColor Yellow
& "agomsaaf\Scripts\Activate.ps1"

# Check if activation was successful
if ($env:VIRTUAL_ENV -like "*agomsaaf*") {
    Write-Host "[OK] Virtual environment activated: $env:VIRTUAL_ENV" -ForegroundColor Green
} else {
    Write-Host "[ERROR] Failed to activate virtual environment" -ForegroundColor Red
    exit 1
}

# Run migrations
Write-Host ""
Write-Host "[2/3] Running database migrations..." -ForegroundColor Yellow
python manage.py migrate --noinput

# Start Django development server
Write-Host ""
Write-Host "[3/3] Starting Django development server..." -ForegroundColor Yellow
Write-Host "Server will be available at: http://127.0.0.1:8000" -ForegroundColor Cyan
Write-Host ""
Write-Host "Press Ctrl+C to stop the server" -ForegroundColor Gray
Write-Host ""

python manage.py runserver
