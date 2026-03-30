[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [int]$Port = 0
)

$ErrorActionPreference = 'Continue'

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Kill Django Runserver Processes" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

function Test-RunserverCommandLine {
    param(
        [string]$CommandLine,
        [int]$PortFilter
    )

    if ([string]::IsNullOrWhiteSpace($CommandLine)) {
        return $false
    }

    $normalized = $CommandLine.ToLowerInvariant()
    $isRunserver = (
        $normalized -like '*manage.py runserver*' -or
        $normalized -like '*django-admin*runserver*' -or
        $normalized -like '*-m django*runserver*'
    )

    if (-not $isRunserver) {
        return $false
    }

    if ($PortFilter -le 0) {
        return $true
    }

    return (
        $normalized -like "*runserver $PortFilter*" -or
        $normalized -like "*runserver 127.0.0.1:$PortFilter*" -or
        $normalized -like "*runserver 0.0.0.0:$PortFilter*" -or
        $normalized -like "*runserver localhost:$PortFilter*"
    )
}

$pythonProcesses = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -in @('python.exe', 'py.exe', 'pythonw.exe') -and
    (Test-RunserverCommandLine -CommandLine $_.CommandLine -PortFilter $Port)
}

if (-not $pythonProcesses) {
    if ($Port -gt 0) {
        Write-Host "[INFO] No Django runserver process found for port $Port." -ForegroundColor Yellow
    } else {
        Write-Host "[INFO] No Django runserver process found." -ForegroundColor Yellow
    }
    exit 0
}

Write-Host "[INFO] Found $($pythonProcesses.Count) Django process(es)." -ForegroundColor Yellow

foreach ($proc in $pythonProcesses) {
    Write-Host ("[INFO] Stopping PID {0}: {1}" -f $proc.ProcessId, $proc.CommandLine) -ForegroundColor Gray
    try {
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
        Write-Host "[OK] Stopped PID $($proc.ProcessId)" -ForegroundColor Green
    } catch {
        Write-Host "[WARN] Failed to stop PID $($proc.ProcessId): $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

Start-Sleep -Seconds 1

$remaining = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -in @('python.exe', 'py.exe', 'pythonw.exe') -and
    (Test-RunserverCommandLine -CommandLine $_.CommandLine -PortFilter $Port)
}

if ($remaining) {
    Write-Host ""
    Write-Host "[WARN] Some Django processes are still running:" -ForegroundColor Yellow
    $remaining | Select-Object ProcessId, Name, CommandLine | Format-Table -AutoSize
    exit 1
}

Write-Host ""
Write-Host "[OK] All matching Django runserver processes have been stopped." -ForegroundColor Green
