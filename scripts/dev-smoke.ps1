param(
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$pythonExe = ""
$venvPython = Join-Path $root "agomtradepro\\Scripts\\python.exe"
if ($env:CONDA_DEFAULT_ENV -eq "agomtradepro") {
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        $pythonExe = $pythonCmd.Source
    }
}
if ([string]::IsNullOrWhiteSpace($pythonExe) -and (Test-Path $venvPython)) {
    $pythonExe = $venvPython
}
if ([string]::IsNullOrWhiteSpace($pythonExe)) {
    Write-Host "[ERROR] Python runtime not found." -ForegroundColor Red
    Write-Host "Use conda env 'agomtradepro' or create venv at agomtradepro\\Scripts\\python.exe" -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "===================================="
Write-Host " AgomTradePro Dev + URL/API Scan"
Write-Host "===================================="
Write-Host ""

Write-Host "[1/4] Running migrations..."
& $pythonExe manage.py migrate --skip-checks | Out-Host

Write-Host ""
Write-Host "[1.5/4] Checking required Django modules..."
& $pythonExe -c "import corsheaders; print('corsheaders: OK')" | Out-Host
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Missing dependency: django-cors-headers" -ForegroundColor Red
    Write-Host "Run: agomtradepro\\Scripts\\python.exe -m pip install django-cors-headers" -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "[2/4] Starting local server on 127.0.0.1:$Port ..."
$cmdLine = "manage.py runserver 127.0.0.1:$Port --noreload"
$logDir = Join-Path $root "reports\\url_scan"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

# 清理残留的 runserver 进程，避免端口和日志占用
Get-CimInstance Win32_Process |
    Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match "manage.py runserver 127.0.0.1:$Port --noreload" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$stdoutLog = Join-Path $logDir ("runserver." + $stamp + ".stdout.log")
$stderrLog = Join-Path $logDir ("runserver." + $stamp + ".stderr.log")

$proc = Start-Process -FilePath $pythonExe `
    -ArgumentList $cmdLine `
    -WorkingDirectory $root `
    -PassThru `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog

$ready = $false
for ($i = 0; $i -lt 40; $i++) {
    if ($proc.HasExited) { break }
    Start-Sleep -Milliseconds 500
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/health/" -UseBasicParsing -TimeoutSec 2
        if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500) {
            $ready = $true
            break
        }
    } catch {
        try {
            $resp2 = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 2
            if ($resp2.StatusCode -ge 200 -and $resp2.StatusCode -lt 500) {
                $ready = $true
                break
            }
        } catch {
            # keep waiting
        }
    }
}

if (-not $ready) {
    Write-Host "[ERROR] Server failed to start in time." -ForegroundColor Red
    if (Test-Path $stdoutLog) {
        Write-Host "--- runserver stdout (tail) ---" -ForegroundColor Yellow
        Get-Content $stdoutLog -Tail 80 | Out-Host
    }
    if (Test-Path $stderrLog) {
        Write-Host "--- runserver stderr (tail) ---" -ForegroundColor Yellow
        Get-Content $stderrLog -Tail 80 | Out-Host
    }
    if ($proc.HasExited) {
        Write-Host ("[ERROR] runserver exited early with code: " + $proc.ExitCode) -ForegroundColor Red
    } else {
        Stop-Process -Id $proc.Id -Force
    }
    exit 1
}

Write-Host "[OK] Server is up."
Write-Host ""
Write-Host "[3/4] Scanning all resolved URLs and APIs..."
$scanExit = 0
try {
    & $pythonExe scripts/scan_urls_api.py --base-url "http://127.0.0.1:$Port" --settings "core.settings.development"
    if ($LASTEXITCODE -ne 0) { $scanExit = $LASTEXITCODE }
} catch {
    Write-Host "[ERROR] Scan failed: $($_.Exception.Message)" -ForegroundColor Red
    $scanExit = 1
}

Write-Host ""
Write-Host "[4/4] Done."
if ($scanExit -eq 0) {
    Write-Host "[OK] Scan completed without critical errors." -ForegroundColor Green
} else {
    Write-Host "[WARN] Scan found server/error-level issues. Check report under reports/url_scan." -ForegroundColor Yellow
}

$keep = Read-Host "Keep dev server running? (Y/N, default Y)"
if ([string]::IsNullOrWhiteSpace($keep) -or $keep.Trim().ToUpper() -eq "Y") {
    Write-Host "Server PID=$($proc.Id). Use scripts\\stop-dev.bat to stop services." -ForegroundColor Cyan
    exit $scanExit
}

if (-not $proc.HasExited) {
    Stop-Process -Id $proc.Id -Force
}
Write-Host "Server stopped."
exit $scanExit
