[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [ValidateRange(1024, 65535)]
    [int]$Port = 8000
)

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$pidFile = Join-Path (Join-Path $root "tmp") ("local-preview-" + $Port + ".pid")
$stopped = $false

if (Test-Path $pidFile) {
    $pidValue = Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pidValue) {
        Stop-Process -Id ([int]$pidValue) -Force -ErrorAction SilentlyContinue
        $stopped = $true
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

$listenLine = netstat -ano | Select-String -Pattern (":$Port\s+.*LISTENING\s+")
if ($listenLine) {
    $line = ($listenLine | Select-Object -First 1).Line.Trim()
    $parts = $line -split "\s+"
    $portPid = $parts[-1]
    if ($portPid) {
        Stop-Process -Id ([int]$portPid) -Force -ErrorAction SilentlyContinue
        $stopped = $true
    }
}

if ($stopped) {
    Write-Host "[OK] Local preview stopped." -ForegroundColor Green
} else {
    Write-Host "[INFO] No local preview process found." -ForegroundColor Yellow
}
