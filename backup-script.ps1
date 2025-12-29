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
    # 使用 robocopy 高效复制文件，它比 PowerShell 的 Copy-Item 更快
    # /E :: 复制子目录，包括空的子目录。
    # /XF <FileName>[...] :: 排除与指定名称/路径/通配符匹配的文件。
    # /NDL :: 不记录目录名称。
    # /NFL :: 不记录文件名称。
    # /NP :: 无进度 - 不显示已复制的百分比。
    # /NJH :: 无作业标头。
    # /NJS :: 无作业摘要。
    robocopy . $tempDir /E /XF *.xml *.log *.log.* /NDL /NFL /NP /NJH /NJS


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
