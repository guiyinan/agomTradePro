param(
    [string]$ImageTag = "20260210201040"
)

$ErrorActionPreference = 'Stop'

Write-Host "[INFO] Testing Docker image: agomsaaf-web:$ImageTag" -ForegroundColor Cyan

# 检查镜像是否存在
Write-Host "`n[1/4] Checking if image exists..."
$images = docker images --format "{{.Repository}}:{{.Tag}}" | Select-String "agomsaaf-web:$ImageTag"
if (-not $images) {
    Write-Host "[ERROR] Image not found: agomsaaf-web:$ImageTag" -ForegroundColor Red
    Write-Host "Available images:" -ForegroundColor Yellow
    docker images | Select-String "agomsaaf"
    exit 1
}
Write-Host "[OK] Image found" -ForegroundColor Green

# 检查端口是否占用
Write-Host "`n[2/4] Checking if port 8000 is available..."
$portUsed = netstat -ano | Select-String ":8000.*LISTENING"
if ($portUsed) {
    Write-Host "[WARN] Port 8000 is in use. Trying to free it..." -ForegroundColor Yellow
    Get-Process | Where-Object {
        $portUsed | Select-String $_.Id
    } | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

# 运行容器
Write-Host "`n[3/4] Starting container..."
$containerName = "test-agom-$(Get-Random -Maximum 9999)"
Write-Host "Container name: $containerName"

docker run -d `
    --name $containerName `
    -p 8000:8000 `
    -e DJANGO_SECRET_KEY='test-key-for-local-testing-only' `
    -e DATABASE_URL='sqlite:///db.sqlite3' `
    -e DEBUG='True' `
    agomsaaf-web:$ImageTag

if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Failed to start container" -ForegroundColor Red
    exit 1
}

# 等待容器启动
Write-Host "[OK] Container started, waiting for health check..." -ForegroundColor Green
Start-Sleep -Seconds 5

# 检查容器状态
Write-Host "`n[4/4] Checking container status..."
$status = docker ps --filter "name=$containerName" --format "{{.Status}}"
if (-not $status) {
    Write-Host "[ERROR] Container is not running!" -ForegroundColor Red
    Write-Host "Container logs:" -ForegroundColor Yellow
    docker logs $containerName
    exit 1
}

Write-Host "[OK] Container is running: $status" -ForegroundColor Green

# 显示日志
Write-Host "`n[INFO] Recent logs:" -ForegroundColor Cyan
docker logs --tail 20 $containerName

Write-Host "`n========================================" -ForegroundColor Green
Write-Host "[SUCCESS] Container is running!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "`nAccess the application at:" -ForegroundColor Cyan
Write-Host "  http://localhost:8000" -ForegroundColor White
Write-Host "`nPress Ctrl+C to stop (container will be removed)" -ForegroundColor Yellow
Write-Host "========================================`n" -ForegroundColor Green

# 监控日志
docker logs -f $containerName

# 清理容器（Ctrl+C 后执行）
trap {
    Write-Host "`n[INFO] Stopping and removing container..." -ForegroundColor Cyan
    docker stop $containerName | Out-Null
    docker rm $containerName | Out-Null
    Write-Host "[OK] Container cleaned up" -ForegroundColor Green
    exit 0
}
