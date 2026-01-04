# AgomSAAF 开发环境 Docker 一键部署脚本
# 功能：自动检测代理速度，配置 Docker Compose，启动 PostgreSQL 和 Redis

param(
    [switch]$SkipProxyCheck,
    [switch]$SkipEnvCheck,
    [string]$ProxyAddress = "127.0.0.1:10808"
)

# 颜色输出函数
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

# 获取脚本所在目录
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

Write-Info "`n=========================================="
Write-Info " AgomSAAF 开发环境 Docker 部署脚本"
Write-Info "==========================================`n"

# ============================================
# Step 1: 检查 Docker 是否运行
# ============================================
Write-Info "[1/6] 检查 Docker 环境..."

try {
    $dockerVersion = docker --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Docker 未安装"
    }
    Write-Success "  Docker 已安装: $dockerVersion"

    # 测试 Docker 是否运行
    $null = docker ps 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error "  Docker 未运行，请启动 Docker Desktop"
        exit 1
    }
    Write-Success "  Docker 运行正常"
}
catch {
    Write-Error "  错误: $_"
    Write-Warning "  请安装 Docker Desktop for Windows"
    exit 1
}

# ============================================
# Step 2: 检查 .env 文件
# ============================================
Write-Info "`n[2/6] 检查环境配置..."

if (-not $SkipEnvCheck) {
    $envFile = Join-Path $ProjectRoot ".env"
    $envExample = Join-Path $ProjectRoot ".env.example"

    if (-not (Test-Path $envFile)) {
        Write-Warning "  .env 文件不存在"

        if (Test-Path $envExample) {
            Write-Info "  从 .env.example 创建 .env 文件..."
            Copy-Item $envExample $envFile
            Write-Success "  已创建 .env 文件，请检查配置是否正确"
        }
        else {
            # 创建基本的 .env 文件
            $envContent = @"
# 数据库配置
POSTGRES_PASSWORD=changeme
DATABASE_URL=postgresql://agomsaaf:changeme@localhost:5432/agomsaaf

# Redis 配置
REDIS_URL=redis://localhost:6379/0

# Django 配置
SECRET_KEY=django-insecure-change-this-in-production
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
"@
            Set-Content -Path $envFile -Value $envContent
            Write-Success "  已创建默认 .env 文件"
        }

        Write-Warning "  请修改 .env 中的 POSTGRES_PASSWORD 等敏感配置"
    }
    else {
        Write-Success "  .env 文件已存在"
    }
}
else {
    Write-Info "  跳过环境配置检查"
}

# ============================================
# Step 3: 代理检测（可选）
# ============================================
Write-Info "`n[3/6] 检测最佳 Docker Hub 连接方式..."

if ($SkipProxyCheck) {
    Write-Info "  跳过代理检测，使用默认配置"
}
else {
    # 检测是否使用代理
    $useProxy = $false

    try {
        # 测试直连 Docker Hub（拉取一个小镜像）
        Write-Info "  测试直连 Docker Hub 速度..."
        $directDuration = Measure-Command {
            $null = docker pull --quiet hello-world:latest 2>&1
            docker rmi hello-world:latest 2>&1 | Out-Null
        }

        if ($LASTEXITCODE -eq 0) {
            $directSpeed = [math]::Round(1000 / $directDuration.TotalSeconds, 2)
            Write-Success "  直连速度: ~$directSpeed 秒"
        }
        else {
            Write-Warning "  直连失败"
            $directSpeed = 9999
        }
    }
    catch {
        Write-Warning "  直连测试失败: $_"
        $directSpeed = 9999
    }

    # 测试代理连接
    try {
        Write-Info "  测试代理连接 ($ProxyAddress)..."

        # 检查代理是否可用
        $proxyTest = Test-NetConnection -ComputerName ($ProxyAddress -split ':')[0] -Port ($ProxyAddress -split ':')[1] -InformationLevel Quiet -WarningAction SilentlyContinue

        if ($proxyTest) {
            Write-Success "  代理服务器可用"
            $useProxy = $true
        }
        else {
            Write-Warning "  代理服务器不可用"
        }
    }
    catch {
        Write-Warning "  代理检测失败: $_"
    }

    # 根据检测结果配置 Docker
    if ($useProxy) {
        Write-Info "`n  建议配置 Docker Desktop 代理:"
        Write-Info "  1. 打开 Docker Desktop"
        Write-Info "  2. 进入 Settings -> Resources -> Proxies"
        Write-Info "  3. 启用 Manual proxy configuration"
        Write-Info "  4. 设置: $ProxyAddress"
        Write-Warning "`n  请配置代理后重新运行此脚本"
        exit 0
    }
    else {
        Write-Success "  使用直连方式"
    }
}

# ============================================
# Step 4: 检查端口占用
# ============================================
Write-Info "`n[4/6] 检查端口占用..."

$ports = @(5432, 6379)
$portNames = @("PostgreSQL", "Redis")
$occupiedPorts = @()

for ($i = 0; $i -lt $ports.Count; $i++) {
    $port = $ports[$i]
    $name = $portNames[$i]

    $connection = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue |
                 Where-Object { $_.State -eq 'Listen' }

    if ($connection) {
        Write-Warning "  端口 $port ($name) 已被占用"
        $occupiedPorts += $port
    }
    else {
        Write-Success "  端口 $port ($name) 可用"
    }
}

if ($occupiedPorts.Count -gt 0) {
    Write-Error "`n  以下端口被占用，请先关闭相关服务:"
    $occupiedPorts | ForEach-Object { Write-Error "    - 端口 $_" }
    exit 1
}

# ============================================
# Step 5: 启动 Docker Compose
# ============================================
Write-Info "`n[5/6] 启动 Docker 服务..."

$composeFile = Join-Path $ProjectRoot "docker-compose-dev.yml"

if (-not (Test-Path $composeFile)) {
    Write-Error "  找不到 docker-compose-dev.yml 文件"
    exit 1
}

# 停止现有容器
Write-Info "  停止现有容器..."
docker-compose -f $composeFile down 2>&1 | Out-Null

# 拉取最新镜像
Write-Info "  拉取最新镜像..."
docker-compose -f $composeFile pull 2>&1 | Out-Null

# 启动服务
Write-Info "  启动服务..."
docker-compose -f $composeFile up -d 2>&1 | Out-Null

if ($LASTEXITCODE -ne 0) {
    Write-Error "  启动失败"
    exit 1
}

Write-Success "  服务启动成功"

# ============================================
# Step 6: 等待服务就绪
# ============================================
Write-Info "`n[6/6] 等待服务就绪..."

# 等待 PostgreSQL
Write-Info "  等待 PostgreSQL 启动..."
$maxAttempts = 30
$attempt = 0

while ($attempt -lt $maxAttempts) {
    try {
        $null = docker exec agomsaaf_postgres_dev pg_isready -U agomsaaf -d agomsaaf 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Success "  PostgreSQL 已就绪"
            break
        }
    }
    catch {}

    $attempt++
    Start-Sleep -Seconds 1
    Write-Host "." -NoNewline
}

if ($attempt -eq $maxAttempts) {
    Write-Warning "  PostgreSQL 启动超时，请手动检查"
}

# 等待 Redis
Write-Info "`n  等待 Redis 启动..."
$attempt = 0

while ($attempt -lt $maxAttempts) {
    try {
        $null = docker exec agomsaaf_redis_dev redis-cli ping 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Success "  Redis 已就绪"
            break
        }
    }
    catch {}

    $attempt++
    Start-Sleep -Seconds 1
    Write-Host "." -NoNewline
}

if ($attempt -eq $maxAttempts) {
    Write-Warning "  Redis 启动超时，请手动检查"
}

# ============================================
# 完成
# ============================================
Write-Success "`n=========================================="
Write-Success " 部署完成！"
Write-Success "==========================================`n"

Write-Info "服务状态:"
docker-compose -f $composeFile ps

Write-Info "`n数据库连接信息:"
Write-Info "  PostgreSQL:"
Write-Info "    主机: localhost:5432"
Write-Info "    数据库: agomsaaf"
Write-Info "    用户: agomsaaf"
Write-Info "    密码: (见 .env 文件)"
Write-Info "`n  Redis:"
Write-Info "    主机: localhost:6379"

Write-Info "`n下一步操作:"
Write-Info "  1. 运行数据库迁移:"
Write-Info "     python manage.py migrate"
Write-Info "`n  2. 创建超级用户（可选）:"
Write-Info "     python manage.py createsuperuser"
Write-Info "`n  3. 启动 Django 开发服务器:"
Write-Info "     python manage.py runserver"
Write-Info "`n  4. 查看日志:"
Write-Info "     docker-compose -f docker-compose-dev.yml logs -f"

Write-Info "`n常用命令:"
Write-Info "  停止服务: docker-compose -f docker-compose-dev.yml down"
Write-Info "  重启服务: docker-compose -f docker-compose-dev.yml restart"
Write-Info "  查看日志: docker-compose -f docker-compose-dev.yml logs -f postgres"
Write-Info "  备份数据库: docker exec agomsaaf_postgres_dev pg_dump -U agomsaaf agomsaaf > backup.sql"
