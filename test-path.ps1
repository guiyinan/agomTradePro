# 测试路径逻辑
Write-Host "===== 路径测试 =====" -ForegroundColor Cyan

$scriptPath = $PSCommandPath
Write-Host "PSCommandPath: $scriptPath"

$scriptRoot = $PSScriptRoot
Write-Host "PSScriptRoot: $scriptRoot"

$currentLocation = Get-Location
Write-Host "当前目录: $currentLocation"

# 测试原来的逻辑
$parentDir = Split-Path -Parent $PSScriptRoot
Write-Host "Split-Path Parent: $parentDir"

# 测试另一种方式
$parentDir2 = $PSScriptRoot | Split-Path -Parent
Write-Host "Pipe 方式 Parent: $parentDir2"

# 最终备份目录
$backupDir = Join-Path $parentDir "bak"
Write-Host "备份目录: $backupDir"

# 测试目录是否存在
Write-Host "备份目录是否存在: $(Test-Path $backupDir)"
