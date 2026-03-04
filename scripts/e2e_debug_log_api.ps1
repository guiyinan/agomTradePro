param(
    [int]$Port = 8000,
    [string]$Token = "agom_local_debug_token_20260217_e2e",
    [switch]$KeepServer = $true
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Get-RunserverProc([int]$port) {
    Get-CimInstance Win32_Process |
        Where-Object { $_.Name -eq "python.exe" -and $_.CommandLine -match "manage.py runserver 127.0.0.1:$port --noreload" } |
        Select-Object -First 1
}

function Wait-ServerReady([int]$port, [int]$timeoutSeconds = 40) {
    $base = "http://127.0.0.1:$port"
    for ($i = 0; $i -lt $timeoutSeconds; $i++) {
        Start-Sleep -Seconds 1
        try {
            $resp = Invoke-WebRequest -Uri "$base/api/health/" -UseBasicParsing -TimeoutSec 2
            if ($resp.StatusCode -eq 200) { return $true }
        } catch {}
    }
    return $false
}

$baseUrl = "http://127.0.0.1:$Port"
$serverStartedByScript = $false
$serverPid = $null

$existing = Get-RunserverProc -port $Port
if ($existing) {
    $serverPid = $existing.ProcessId
} else {
    $out = Join-Path $env:TEMP "agom_e2e_api_$Port.stdout.log"
    $err = Join-Path $env:TEMP "agom_e2e_api_$Port.stderr.log"
    if (Test-Path $out) { Remove-Item $out -Force }
    if (Test-Path $err) { Remove-Item $err -Force }

    $proc = Start-Process -FilePath "python" `
        -ArgumentList "manage.py runserver 127.0.0.1:$Port --noreload" `
        -WorkingDirectory $root `
        -PassThru `
        -WindowStyle Hidden `
        -RedirectStandardOutput $out `
        -RedirectStandardError $err
    $serverStartedByScript = $true
    $serverPid = $proc.Id

    if (-not (Wait-ServerReady -port $Port)) {
        Write-Output "SERVER_READY=False"
        Write-Output "SERVER_PID=$serverPid"
        if (Test-Path $out) {
            Write-Output "STDOUT_TAIL_BEGIN"
            Get-Content $out -Tail 80 | ForEach-Object { Write-Output $_ }
            Write-Output "STDOUT_TAIL_END"
        }
        if (Test-Path $err) {
            Write-Output "STDERR_TAIL_BEGIN"
            Get-Content $err -Tail 80 | ForEach-Object { Write-Output $_ }
            Write-Output "STDERR_TAIL_END"
        }
        if ($proc -and -not $proc.HasExited) { Stop-Process -Id $proc.Id -Force }
        exit 1
    }
}

$results = [ordered]@{}
$results.server_pid = $serverPid
$results.server_started_by_script = $serverStartedByScript

try {
    # 1) health
    $results.health = (Invoke-WebRequest -Uri "$baseUrl/api/health/" -UseBasicParsing -TimeoutSec 10).StatusCode

    # 2) no token -> 401
    try {
        Invoke-WebRequest -Uri "$baseUrl/api/debug/server-logs/stream/?since=0&limit=5" -UseBasicParsing -TimeoutSec 10 | Out-Null
        $results.no_token = 200
    } catch {
        $results.no_token = $_.Exception.Response.StatusCode.value__
    }

    # 3) bad token -> 401
    try {
        Invoke-WebRequest -Uri "$baseUrl/api/debug/server-logs/stream/?since=0&limit=5" -Headers @{ Authorization = "Bearer bad-token" } -UseBasicParsing -TimeoutSec 10 | Out-Null
        $results.bad_token = 200
    } catch {
        $results.bad_token = $_.Exception.Response.StatusCode.value__
    }

    # generate additional logs
    1..3 | ForEach-Object { Invoke-WebRequest -Uri "$baseUrl/api/health/" -UseBasicParsing -TimeoutSec 10 | Out-Null }

    # 4) good token first pull
    $r1 = Invoke-WebRequest -Uri "$baseUrl/api/debug/server-logs/stream/?since=0&limit=2" -Headers @{ Authorization = "Bearer $Token" } -UseBasicParsing -TimeoutSec 10
    $j1 = $r1.Content | ConvertFrom-Json
    $results.good_token_first = $r1.StatusCode
    $results.first_count = [int]$j1.count
    $results.first_last_id = [int]$j1.last_id

    # 5) incremental with cursor
    Invoke-WebRequest -Uri "$baseUrl/api/health/" -UseBasicParsing -TimeoutSec 10 | Out-Null
    $r2 = Invoke-WebRequest -Uri "$baseUrl/api/debug/server-logs/stream/?since=$($j1.last_id)&limit=50" -Headers @{ Authorization = "Bearer $Token" } -UseBasicParsing -TimeoutSec 10
    $j2 = $r2.Content | ConvertFrom-Json
    $results.incremental_status = $r2.StatusCode
    $results.incremental_count = [int]$j2.count
    $results.incremental_last_id = [int]$j2.last_id

    # 6) limit clamp
    $r3 = Invoke-WebRequest -Uri "$baseUrl/api/debug/server-logs/stream/?since=0&limit=9999" -Headers @{ Authorization = "Bearer $Token" } -UseBasicParsing -TimeoutSec 10
    $j3 = $r3.Content | ConvertFrom-Json
    $results.limit_clamp_status = $r3.StatusCode
    $results.limit_clamp_count = [int]$j3.count

    # 7) export
    $exp = Invoke-WebRequest -Uri "$baseUrl/api/debug/server-logs/export/" -Headers @{ Authorization = "Bearer $Token" } -UseBasicParsing -TimeoutSec 10
    $results.export_status = $exp.StatusCode
    $results.export_len = $exp.Content.Length
    $results.export_has_health = [bool]($exp.Content -match "/api/health/")

    # 8) response shape
    $shapeOk = ($j1.PSObject.Properties.Name -contains "entries") -and
        ($j1.PSObject.Properties.Name -contains "last_id") -and
        ($j1.PSObject.Properties.Name -contains "count")
    $results.shape_ok = $shapeOk

    # Print summary
    Write-Output "E2E_RESULT_BEGIN"
    $results.GetEnumerator() | ForEach-Object { Write-Output ("{0}={1}" -f $_.Key, $_.Value) }
    if ($j1.entries.Count -gt 0) {
        Write-Output ("first_entry=" + ($j1.entries[0] | ConvertTo-Json -Compress))
    } else {
        Write-Output "first_entry=NONE"
    }
    Write-Output "E2E_RESULT_END"
}
finally {
    if ($serverStartedByScript -and -not $KeepServer) {
        $p = Get-Process -Id $serverPid -ErrorAction SilentlyContinue
        if ($p) { Stop-Process -Id $serverPid -Force }
        Write-Output "SERVER_STOPPED=True"
    } else {
        Write-Output "SERVER_STOPPED=False"
    }
}
