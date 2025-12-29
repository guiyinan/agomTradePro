# 获取当前文件夹名称
$currentFolder = Split-Path -Path (Get-Location) -Leaf

# 获取当前时间戳 格式为 yyyyMMdd_HHmmss
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"

# 组合目标备份文件名称
$backupName = "${currentFolder}_${timestamp}.zip"
$destinationPath = "D:\githv\bak\$backupName"

# 确保备份目标文件夹存在
if (-not (Test-Path "D:\githv\bak")) {
    New-Item -ItemType Directory -Path "D:\githv\bak" -Force
}

# 创建临时目录用于存放筛选后的文件
$tempDir = New-Item -ItemType Directory -Path "$env:TEMP\$backupName" -Force

try {
    # 复制所有文件，排除xml、log和log.*文件
    Get-ChildItem -Path . -Recurse -File | 
    Where-Object { 
        $_.Extension -notin @('.xml','.log') -and 
        -not ($_.Name -like "*.log.*")
    } |
    ForEach-Object {
        # 计算相对路径
        $relativePath = $_.FullName.Substring((Get-Location).Path.Length + 1)
        $destination = Join-Path $tempDir $relativePath
        
        # 确保目标目录存在
        $destinationFolder = Split-Path $destination -Parent
        if (-not (Test-Path $destinationFolder)) {
            New-Item -ItemType Directory -Path $destinationFolder -Force | Out-Null
        }
        
        # 复制文件
        Copy-Item $_.FullName -Destination $destination -Force
    }

    # 使用Compress-Archive创建ZIP文件
    Compress-Archive -Path "$tempDir\*" -DestinationPath $destinationPath -CompressionLevel NoCompression -Force

    Write-Host "备份完成！" -ForegroundColor Green
    Write-Host "备份文件位置: $destinationPath" -ForegroundColor Green
}
catch {
    Write-Host "备份过程中发生错误：" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
}
finally {
    # 清理临时目录
    if (Test-Path $tempDir) {
        Remove-Item -Path $tempDir -Recurse -Force
    }
}
