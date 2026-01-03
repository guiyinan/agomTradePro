<#
.SYNOPSIS
    閫氱敤椤圭洰澶囦唤鑴氭湰
.DESCRIPTION
    澶囦唤褰撳墠鐩綍鍒拌剼鏈笂涓€灞傜洰褰曠殑 bak 鏂囦欢澶癸紝榛樿鎺掗櫎涓存椂/缂撳瓨鐩綍鍜屾棩蹇楁枃浠?.PARAMETER ExcludeFiles
    瑕佹帓闄ょ殑鏂囦欢妯″紡锛堢┖鏍煎垎闅旓級
.PARAMETER ExcludeDirs
    瑕佹帓闄ょ殑鐩綍鍚嶏紙绌烘牸鍒嗛殧锛?.PARAMETER Compression
    鍘嬬缉绾у埆: NoCompression, Fast, Optimal
.EXAMPLE
    .\backup-script.ps1
    浣跨敤榛樿鎺掗櫎瑙勫垯澶囦唤鏁翠釜椤圭洰
#>

param(
    [string]$ExcludeFiles = "*.xml *.log *.log.*",
    [string]$ExcludeDirs = "__pycache__ .venv venv node_modules .git *.egg-info .vscode .idea",
    [ValidateSet("NoCompression", "Fastest", "Optimal")]
    [string]$Compression = "Fastest"
)

# 鑾峰彇褰撳墠鏂囦欢澶瑰悕绉?$currentFolder = Split-Path -Path (Get-Location) -Leaf
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupName = "${currentFolder}_${timestamp}.zip"

# 鑴氭湰涓婁竴灞傜洰褰曠殑 bak 鏂囦欢澶?$scriptDir = Split-Path -Parent $PSScriptRoot
if (-not $scriptDir) {
    $scriptDir = ".."
}
$backupDir = Join-Path $scriptDir "bak"
$destinationPath = Join-Path $backupDir $backupName

# 纭繚澶囦唤鐩爣鏂囦欢澶瑰瓨鍦?if (-not (Test-Path $backupDir)) {
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
}

# 鍒涘缓涓存椂鐩綍
$tempDir = New-Item -ItemType Directory -Path "$env:TEMP\$backupName" -Force

try {
    Write-Host "姝ｅ湪澶囦唤: $currentFolder" -ForegroundColor Cyan
    Write-Host "鑴氭湰浣嶇疆: $PSScriptRoot" -ForegroundColor Gray
    Write-Host "澶囦唤鐩爣: $destinationPath" -ForegroundColor Gray
    Write-Host ""

    # 浣跨敤 robocopy 澶嶅埗鏁翠釜鐩綍
    Write-Host "姝ｅ湪澶嶅埗鏂囦欢..." -ForegroundColor Cyan
    $robocopyCmd = "robocopy . `"$tempDir`" /E /XF $ExcludeFiles /XD $ExcludeDirs /NDL /NFL /NP /NJH /NJS /R:0 /W:0"
    $robocopyExitCode = cmd /c $robocopyCmd

    if ($robocopyExitCode -gt 7) {
        throw "robocopy 澶辫触锛岄€€鍑虹爜: $robocopyExitCode"
    }

    # 鍘嬬缉
    Write-Host "姝ｅ湪鍘嬬缉..." -ForegroundColor Cyan
    Compress-Archive -Path "$tempDir\*" -DestinationPath $destinationPath -CompressionLevel $Compression -Force

    $backupSize = (Get-Item $destinationPath).Length / 1MB
    $backupSizeStr = "{0:N2}" -f $backupSize

    Write-Host ""
    Write-Host "鉁?澶囦唤瀹屾垚锛? -ForegroundColor Green
    Write-Host "  浣嶇疆: $destinationPath" -ForegroundColor Gray
    Write-Host "  澶у皬: $backupSizeStr MB" -ForegroundColor Gray
}
catch {
    Write-Host ""
    Write-Host "鉁?澶囦唤澶辫触锛?($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    if (Test-Path $tempDir) {
        Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

