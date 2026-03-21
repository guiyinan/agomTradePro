# AgomTradePro Docker Deployment Script for Development
# Auto-detect proxy speed, configure Docker Compose, start PostgreSQL and Redis

param(
    [switch]$SkipProxyCheck,
    [switch]$SkipEnvCheck,
    [string]$ProxyAddress = "127.0.0.1:10808"
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
Write-Info " AgomTradePro Docker Deployment Script"
Write-Info "==========================================`n"

# ============================================
# Step 1: Check if Docker is running
# ============================================
Write-Info "[1/6] Checking Docker environment..."

try {
    $dockerVersion = docker --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Docker not installed"
    }
    Write-Success "  Docker installed: $dockerVersion"

    # Test if Docker is running
    $null = docker ps 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error "  Docker not running, please start Docker Desktop"
        exit 1
    }
    Write-Success "  Docker is running"
}
catch {
    Write-Error "  Error: $_"
    Write-Warning "  Please install Docker Desktop for Windows"
    exit 1
}

# ============================================
# Step 2: Check .env file
# ============================================
Write-Info "`n[2/6] Checking environment configuration..."

if (-not $SkipEnvCheck) {
    $envFile = Join-Path $ProjectRoot ".env"
    $envExample = Join-Path $ProjectRoot ".env.example"

    if (-not (Test-Path $envFile)) {
        Write-Warning "  .env file does not exist"

        if (Test-Path $envExample) {
            Write-Info "  Creating .env from .env.example..."
            Copy-Item $envExample $envFile
            Write-Success "  .env file created, please check configuration"
        }
        else {
            # Create basic .env file
            $envContent = @"
# Database configuration
POSTGRES_PASSWORD=changeme
DATABASE_URL=postgresql://agomtradepro:changeme@localhost:5432/agomtradepro

# Redis configuration
REDIS_URL=redis://localhost:6379/0

# Django configuration
SECRET_KEY=django-insecure-change-this-in-production
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
"@
            Set-Content -Path $envFile -Value $envContent
            Write-Success "  Default .env file created"
        }

        Write-Warning "  Please modify POSTGRES_PASSWORD in .env"
    }
    else {
        Write-Success "  .env file exists"
    }
}
else {
    Write-Info "  Skipping environment check"
}

# ============================================
# Step 3: Proxy detection (optional)
# ============================================
Write-Info "`n[3/6] Detecting best Docker Hub connection..."

if ($SkipProxyCheck) {
    Write-Info "  Skipping proxy detection, using default configuration"
}
else {
    # Detect whether to use proxy
    $useProxy = $false

    try {
        # Test direct connection to Docker Hub
        Write-Info "  Testing direct connection to Docker Hub..."
        $directDuration = Measure-Command {
            $null = docker pull --quiet hello-world:latest 2>&1
            docker rmi hello-world:latest 2>&1 | Out-Null
        }

        if ($LASTEXITCODE -eq 0) {
            $directSpeed = [math]::Round(1000 / $directDuration.TotalSeconds, 2)
            Write-Success "  Direct connection speed: ~$directSpeed seconds"
        }
        else {
            Write-Warning "  Direct connection failed"
            $directSpeed = 9999
        }
    }
    catch {
        Write-Warning "  Direct connection test failed: $_"
        $directSpeed = 9999
    }

    # Test proxy connection
    try {
        Write-Info "  Testing proxy connection ($ProxyAddress)..."

        # Check if proxy is available
        $proxyTest = Test-NetConnection -ComputerName ($ProxyAddress -split ':')[0] -Port ($ProxyAddress -split ':')[1] -InformationLevel Quiet -WarningAction SilentlyContinue

        if ($proxyTest) {
            Write-Success "  Proxy server available"
            $useProxy = $true
        }
        else {
            Write-Warning "  Proxy server unavailable"
        }
    }
    catch {
        Write-Warning "  Proxy detection failed: $_"
    }

    # Configure Docker based on detection result
    if ($useProxy) {
        Write-Info "`n  Recommend configuring Docker Desktop proxy:"
        Write-Info "  1. Open Docker Desktop"
        Write-Info "  2. Go to Settings -> Resources -> Proxies"
        Write-Info "  3. Enable Manual proxy configuration"
        Write-Info "  4. Set: $ProxyAddress"
        Write-Warning "`n  Please configure proxy and run this script again"
        exit 0
    }
    else {
        Write-Success "  Using direct connection"
    }
}

# ============================================
# Step 4: Check port availability
# ============================================
Write-Info "`n[4/6] Checking port availability..."

$ports = @(5432, 6379)
$portNames = @("PostgreSQL", "Redis")
$occupiedPorts = @()

for ($i = 0; $i -lt $ports.Count; $i++) {
    $port = $ports[$i]
    $name = $portNames[$i]

    $connection = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue |
                 Where-Object { $_.State -eq 'Listen' }

    if ($connection) {
        Write-Warning "  Port $port ($name) is occupied"
        $occupiedPorts += $port
    }
    else {
        Write-Success "  Port $port ($name) is available"
    }
}

if ($occupiedPorts.Count -gt 0) {
    Write-Error "`n  The following ports are occupied, please stop related services:"
    $occupiedPorts | ForEach-Object { Write-Error "    - Port $_" }
    exit 1
}

# ============================================
# Step 5: Start Docker Compose
# ============================================
Write-Info "`n[5/6] Starting Docker services..."

$composeFile = Join-Path $ProjectRoot "docker-compose-dev.yml"

if (-not (Test-Path $composeFile)) {
    Write-Error "  docker-compose-dev.yml not found"
    exit 1
}

# Stop existing containers
Write-Info "  Stopping existing containers..."
docker-compose -f $composeFile down 2>&1 | Out-Null

# Pull latest images
Write-Info "  Pulling latest images..."
docker-compose -f $composeFile pull 2>&1 | Out-Null

# Start services
Write-Info "  Starting services..."
docker-compose -f $composeFile up -d 2>&1 | Out-Null

if ($LASTEXITCODE -ne 0) {
    Write-Error "  Failed to start"
    exit 1
}

Write-Success "  Services started successfully"

# ============================================
# Step 6: Wait for services to be ready
# ============================================
Write-Info "`n[6/6] Waiting for services to be ready..."

# Wait for PostgreSQL
Write-Info "  Waiting for PostgreSQL..."
$maxAttempts = 30
$attempt = 0

while ($attempt -lt $maxAttempts) {
    try {
        $null = docker exec agomtradepro_postgres_dev pg_isready -U agomtradepro -d agomtradepro 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Success "  PostgreSQL is ready"
            break
        }
    }
    catch {}

    $attempt++
    Start-Sleep -Seconds 1
    Write-Host "." -NoNewline
}

if ($attempt -eq $maxAttempts) {
    Write-Warning "  PostgreSQL startup timeout, please check manually"
}

# Wait for Redis
Write-Info "`n  Waiting for Redis..."
$attempt = 0

while ($attempt -lt $maxAttempts) {
    try {
        $null = docker exec agomtradepro_redis_dev redis-cli ping 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Success "  Redis is ready"
            break
        }
    }
    catch {}

    $attempt++
    Start-Sleep -Seconds 1
    Write-Host "." -NoNewline
}

if ($attempt -eq $maxAttempts) {
    Write-Warning "  Redis startup timeout, please check manually"
}

# ============================================
# Complete
# ============================================
Write-Success "`n=========================================="
Write-Success " Deployment Complete!"
Write-Success "==========================================`n"

Write-Info "Service Status:"
docker-compose -f $composeFile ps

Write-Info "`nDatabase Connection Info:"
Write-Info "  PostgreSQL:"
Write-Info "    Host: localhost:5432"
Write-Info "    Database: agomtradepro"
Write-Info "    User: agomtradepro"
Write-Info "    Password: (see .env file)"
Write-Info "`n  Redis:"
Write-Info "    Host: localhost:6379"

Write-Info "`nNext Steps:"
Write-Info "  1. Run database migrations:"
Write-Info "     python manage.py migrate"
Write-Info "`n  2. Create superuser (optional):"
Write-Info "     python manage.py createsuperuser"
Write-Info "`n  3. Start Django development server:"
Write-Info "     python manage.py runserver"
Write-Info "`n  4. View logs:"
Write-Info "     docker-compose -f docker-compose-dev.yml logs -f"

Write-Info "`nCommon Commands:"
Write-Info "  Stop services: docker-compose -f docker-compose-dev.yml down"
Write-Info "  Restart services: docker-compose -f docker-compose-dev.yml restart"
Write-Info "  View logs: docker-compose -f docker-compose-dev.yml logs -f postgres"
Write-Info "  Backup database: docker exec agomtradepro_postgres_dev pg_dump -U agomtradepro agomtradepro > backup.sql"
