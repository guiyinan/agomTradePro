<#
.SYNOPSIS
    通用项目备份脚本
.DESCRIPTION
    备份当前目录到 D:\githv\bak，默认排除临时/缓存目录和日志文件
.PARAMETER ExcludeFiles
    要排除的文件模式（空格分隔）
.PARAMETER ExcludeDirs
    要排除的目录名（空格分隔）
.PARAMETER Compression
    压缩级别: NoCompression, Fast, Optimal
.EXAMPLE
    .\backup-script.ps1
    使用默认排除规则备份整个项目
#>

param(
    [string]$ExcludeFiles = "*.xml *.log *.log.*",
    [string]$ExcludeDirs = "__pycache__ .venv venv node_modules .git *.egg-info .vscode .idea",
    [ValidateSet("NoCompression", "Fastest", "Optimal")]
    [string]$Compression = "Fastest"
)

# 获取当前文件夹名称
$currentFolder = Split-Path -Path (Get-Location) -Leaf
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupName = "${currentFolder}_${timestamp}.zip"
$destinationPath = "D:\githv\bak\$backupName"

# 确保备份目标文件夹存在
if (-not (Test-Path "D:\githv\bak")) {
    New-Item -ItemType Directory -Path "D:\githv\bak" -Force | Out-Null
}

# 创建临时目录
$tempDir = New-Item -ItemType Directory -Path "$env:TEMP\$backupName" -Force

try {
    Write-Host "正在备份: $currentFolder" -ForegroundColor Cyan
    Write-Host ""

    # 使用 robocopy 复制整个目录
    Write-Host "正在复制文件..." -ForegroundColor Cyan
    $robocopyCmd = "robocopy . `"$tempDir`" /E /XF $ExcludeFiles /XD $ExcludeDirs /NDL /NFL /NP /NJH /NJS /R:0 /W:0"
    $robocopyExitCode = cmd /c $robocopyCmd

    if ($robocopyExitCode -gt 7) {
        throw "robocopy 失败，退出码: $robocopyExitCode"
    }

    # 压缩
    Write-Host "正在压缩..." -ForegroundColor Cyan
    Compress-Archive -Path "$tempDir\*" -DestinationPath $destinationPath -CompressionLevel $Compression -Force

    $backupSize = (Get-Item $destinationPath).Length / 1MB
    $backupSizeStr = "{0:N2}" -f $backupSize

    Write-Host ""
    Write-Host "✓ 备份完成！" -ForegroundColor Green
    Write-Host "  位置: $destinationPath" -ForegroundColor Gray
    Write-Host "  大小: $backupSizeStr MB" -ForegroundColor Gray
}
catch {
    Write-Host ""
    Write-Host "✗ 备份失败：$($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    if (Test-Path $tempDir) {
        Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
