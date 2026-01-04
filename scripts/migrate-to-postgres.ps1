# AgomSAAF 数据迁移脚本
# 功能：将 SQLite 数据迁移到 PostgreSQL

param(
    [switch]$SkipBackup,
    [string]$BackupFile = "sqlite-backup.json"
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
Write-Info " AgomSAAF SQLite -> PostgreSQL 迁移工具"
Write-Info "==========================================`n"

$composeFile = Join-Path $ProjectRoot "docker-compose-dev.yml"
$pythonCmd = "agomsaaf/Scripts/python.exe"
$pythonCmdAlt = "D:/githv/agomSAAF/agomsaaf/Scripts/python.exe"

# 检测 Python 命令
if (Test-Path $pythonCmd) {
    # 使用相对路径
}
elseif (Test-Path $pythonCmdAlt) {
    $pythonCmd = $pythonCmdAlt
}
else {
    # 尝试使用虚拟环境中的 python
    $pythonCmd = "agomsaaf/Scripts/python.exe"
}

# ============================================
# Step 1: 检查 SQLite 数据库
# ============================================
Write-Info "[1/5] 检查 SQLite 数据库..."

$sqliteDb = Join-Path $ProjectRoot "db.sqlite3"

if (-not (Test-Path $sqliteDb)) {
    Write-Warning "  未找到 SQLite 数据库 (db.sqlite3)"
    Write-Info "  如果这是全新安装，可以直接运行迁移创建空数据库"
    $response = Read-Host "  是否继续？(y/N)"

    if ($response -ne "y" -and $response -ne "Y") {
        Write-Info "  已取消"
        exit 0
    }
}
else {
    $dbSize = (Get-Item $sqliteDb).Length / 1KB
    Write-Success "  找到 SQLite 数据库 (大小: $([math]::Round($dbSize, 2)) KB)"
}

# ============================================
# Step 2: 备份 SQLite 数据
# ============================================
if (-not $SkipBackup) {
    Write-Info "`n[2/5] 备份 SQLite 数据..."

    if (Test-Path $sqliteDb) {
        $backupPath = Join-Path $ProjectRoot $BackupFile

        # 创建备份目录
        $backupDir = Split-Path -Parent $backupPath
        if (-not (Test-Path $backupDir)) {
            New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
        }

        Write-Info "  导出数据到 $BackupFile ..."
        $dumpCmd = "& `"$pythonCmd`" manage.py dumpdata --exclude contenttypes --exclude auth.Permission --indent 2 > `"$backupPath`""

        try {
            Invoke-Expression $dumpCmd

            if (Test-Path $backupPath) {
                $backupSize = (Get-Item $backupPath).Length / 1KB
                Write-Success "  备份完成 (大小: $([math]::Round($backupSize, 2)) KB)"
                Write-Info "  备份文件: $backupPath"
            }
            else {
                Write-Error "  备份失败"
                exit 1
            }
        }
        catch {
            Write-Error "  备份失败: $_"
            exit 1
        }
    }
    else {
        Write-Info "  跳过备份（未找到 SQLite 数据库）"
    }
}
else {
    Write-Info "`n[2/5] 跳过备份"
}

# ============================================
# Step 3: 检查 Docker 服务
# ============================================
Write-Info "`n[3/5] 检查 Docker 服务..."

try {
    $null = docker ps 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error "  Docker 未运行"
        exit 1
    }

    # 检查 PostgreSQL 容器是否运行
    $pgRunning = docker ps --filter "name=agomsaaf_postgres_dev" --format "{{.Names}}" 2>&1

    if ($pgRunning -eq "agomsaaf_postgres_dev") {
        Write-Success "  PostgreSQL 容器正在运行"
    }
    else {
        Write-Warning "  PostgreSQL 容器未运行"
        Write-Info "  启动 Docker 服务..."

        docker-compose -f $composeFile up -d 2>&1 | Out-Null

        if ($LASTEXITCODE -ne 0) {
            Write-Error "  启动失败"
            exit 1
        }

        Write-Info "  等待服务就绪..."
        Start-Sleep -Seconds 5

        # 检查服务是否就绪
        $maxAttempts = 30
        $attempt = 0

        while ($attempt -lt $maxAttempts) {
            $null = docker exec agomsaaf_postgres_dev pg_isready -U agomsaaf -d agomsaaf 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Success "  服务已就绪"
                break
            }
            $attempt++
            Start-Sleep -Seconds 1
            Write-Host "." -NoNewline
        }
    }
}
catch {
    Write-Error "  错误: $_"
    exit 1
}

# ============================================
# Step 4: 执行数据库迁移
# ============================================
Write-Info "`n[4/5] 执行数据库迁移..."

Write-Warning "  警告: 此操作将清空 PostgreSQL 数据库中的现有数据"
$response = Read-Host "  是否继续？(y/N)"

if ($response -ne "y" -and $response -ne "Y") {
    Write-Info "  已取消"
    exit 0
}

# 先确保 .env 使用 PostgreSQL 连接
Write-Info "  检查 .env 配置..."

$envFile = Join-Path $ProjectRoot ".env"
if (Test-Path $envFile) {
    $envContent = Get-Content $envFile -Raw

    # 确保使用 PostgreSQL
    if ($envContent -match 'DATABASE_URL=sqlite:') {
        Write-Warning "  .env 文件中仍使用 SQLite，正在更新..."

        $envContent = $envContent -replace 'DATABASE_URL=sqlite:.*', 'DATABASE_URL=postgresql://agomsaaf:changeme@localhost:5432/agomsaaf'
        Set-Content -Path $envFile -Value $envContent

        Write-Success "  已更新为 PostgreSQL 连接"
    }
    else {
        Write-Success "  .env 配置正确"
    }
}

# 执行迁移
Write-Info "  运行数据库迁移..."

try {
    & "$pythonCmd" manage.py migrate --noinput 2>&1 | ForEach-Object {
        if ($_ -match "Running migrations:") {
            Write-Info "    $_"
        }
        elseif ($_ -match "Applying") {
            Write-Host "      $_" -ForegroundColor Gray
        }
    }

    Write-Success "  迁移完成"
}
catch {
    Write-Error "  迁移失败: $_"
    exit 1
}

# ============================================
# Step 5: 恢复数据
# ============================================
if ((Test-Path $sqliteDb) -and -not $SkipBackup) {
    Write-Info "`n[5/5] 恢复数据到 PostgreSQL..."

    $backupPath = Join-Path $ProjectRoot $BackupFile

    if (Test-Path $backupPath) {
        Write-Info "  从备份文件恢复数据..."

        try {
            & "$pythonCmd" manage.py loaddata "`"$backupPath`"" 2>&1 | ForEach-Object {
                Write-Host "      $_" -ForegroundColor Gray
            }

            Write-Success "  数据恢复完成"
        }
        catch {
            Write-Warning "  恢复失败: $_"
            Write-Info "  请手动运行: python manage.py loaddata $BackupFile"
        }
    }
    else {
        Write-Warning "  未找到备份文件，跳过恢复"
    }
}
else {
    Write-Info "`n[5/5] 跳过数据恢复"
}

# ============================================
# 完成
# ============================================
Write-Success "`n=========================================="
Write-Success " 迁移完成！"
Write-Success "==========================================`n"

Write-Info "下一步操作:"
Write-Info "  1. 测试数据库连接:"
Write-Info "     python manage.py check"
Write-Info "`n  2. 创建超级用户:"
Write-Info "     python manage.py createsuperuser"
Write-Info "`n  3. 启动开发服务器:"
Write-Info "     python manage.py runserver"
Write-Info "`n  4. 访问应用: http://localhost:8000"

Write-Info "`n备份文件位置:"
Write-Info "  $backupPath"

Write-Warning "`n重要提示:"
Write-Warning "  - SQLite 原始文件 (db.sqlite3) 仍然保留"
Write-Warning "  - 建议保留备份一段时间，确认数据无误后再删除"
Write-Warning "  - 如需回滚，修改 .env 中的 DATABASE_URL 为 sqlite:///db.sqlite3"
