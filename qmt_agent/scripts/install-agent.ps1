param(
    [Parameter(Mandatory = $true)][string]$PythonExe,
    [Parameter(Mandatory = $true)][string]$ServerUrl,
    [Parameter(Mandatory = $true)][int]$SystemAccountId,
    [string]$AgentId = "qmt-home-01",
    [string]$QmtRoot = "D:\qmt",
    [string]$BrokerAccountId = "",
    [string]$InstallRoot = "$env:LOCALAPPDATA\AgomQmtAgent",
    [string]$XtQuantWheelPath = "",
    [string]$XtQuantWheelSha256 = "",
    [switch]$RegisterTask,
    [switch]$RunReadProbe
)

$ErrorActionPreference = "Stop"
$SourceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$PackageSource = Join-Path $SourceRoot "qmt_agent"
$LockPath = Join-Path $PackageSource "xtquant-lock.json"
$ResolvedPython = (Resolve-Path -LiteralPath $PythonExe).Path
$ResolvedQmtRoot = (Resolve-Path -LiteralPath $QmtRoot).Path
$ResolvedInstallRoot = [System.IO.Path]::GetFullPath($InstallRoot)
$DriveRoot = [System.IO.Path]::GetPathRoot($ResolvedInstallRoot)

if ($env:OS -ne "Windows_NT") {
    throw "The QMT Agent can only be installed on Windows."
}
if ($ResolvedInstallRoot -eq $DriveRoot -or $ResolvedInstallRoot.Length -lt 8) {
    throw "Refusing to install into an unsafe target path: $ResolvedInstallRoot"
}
if (-not $ServerUrl.StartsWith("https://") -and -not $ServerUrl.StartsWith("http://127.0.0.1")) {
    throw "ServerUrl must use HTTPS outside loopback tests."
}
if ($SystemAccountId -le 0) {
    throw "SystemAccountId must be a positive AgomTradePro account ID."
}

& $ResolvedPython -c "import sys; raise SystemExit(0 if (3, 10) <= sys.version_info[:2] <= (3, 13) else 1)"
if ($LASTEXITCODE -ne 0) {
    throw "The selected Python must be a 64-bit CPython version from 3.10 through 3.13."
}
& $ResolvedPython -c "import struct; raise SystemExit(0 if struct.calcsize('P') == 8 else 1)"
if ($LASTEXITCODE -ne 0) {
    throw "The selected Python must be 64-bit."
}

$MiniUserdata = Join-Path $ResolvedQmtRoot "userdata_mini"
$StandardUserdata = Join-Path $ResolvedQmtRoot "userdata"
if (Test-Path -LiteralPath $MiniUserdata) {
    $QmtUserdataPath = $MiniUserdata
}
elseif (Test-Path -LiteralPath $StandardUserdata) {
    $QmtUserdataPath = $StandardUserdata
}
else {
    throw "Neither userdata_mini nor userdata exists below QmtRoot: $ResolvedQmtRoot"
}

if (-not $BrokerAccountId) {
    $UsersPath = Join-Path $StandardUserdata "users"
    $UserDirectories = @(Get-ChildItem -LiteralPath $UsersPath -Directory -ErrorAction SilentlyContinue)
    if ($UserDirectories.Count -eq 1) {
        $BrokerAccountId = $UserDirectories[0].Name
    }
    else {
        throw "BrokerAccountId is required when the QMT account cannot be identified uniquely."
    }
}

New-Item -ItemType Directory -Force -Path $ResolvedInstallRoot | Out-Null
$RuntimeRoot = Join-Path $ResolvedInstallRoot "runtime"
$RuntimePython = Join-Path $RuntimeRoot "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $RuntimePython)) {
    & $ResolvedPython -m venv $RuntimeRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create the private Agent Python environment."
    }
}

$CacheRoot = Join-Path $ResolvedInstallRoot "cache"
New-Item -ItemType Directory -Force -Path $CacheRoot | Out-Null
if ($XtQuantWheelPath) {
    $WheelPath = (Resolve-Path -LiteralPath $XtQuantWheelPath).Path
    if (-not $XtQuantWheelSha256) {
        throw "XtQuantWheelSha256 is required for a broker-supplied wheel."
    }
    $ExpectedHash = $XtQuantWheelSha256.ToLowerInvariant()
}
else {
    $Lock = Get-Content -LiteralPath $LockPath -Raw | ConvertFrom-Json
    $WheelPath = Join-Path $CacheRoot $Lock.filename
    $ExpectedHash = [string]$Lock.sha256
    if (-not (Test-Path -LiteralPath $WheelPath)) {
        Write-Host "Downloading the locked XtQuant wheel from the recorded official package URL."
        Invoke-WebRequest -Uri $Lock.url -OutFile $WheelPath -UseBasicParsing
    }
}

$ActualHash = (Get-FileHash -LiteralPath $WheelPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($ActualHash -ne $ExpectedHash.ToLowerInvariant()) {
    throw "XtQuant wheel SHA-256 verification failed."
}
& $RuntimePython -m pip install --no-deps --force-reinstall $WheelPath
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install the verified XtQuant wheel."
}
& $RuntimePython -c "import xtquant; from xtquant.xttrader import XtQuantTrader; from xtquant.xttype import StockAccount"
if ($LASTEXITCODE -ne 0) {
    throw "XtQuant was installed but its trading modules cannot be imported."
}
$XtQuantVersion = (& $RuntimePython -c "import importlib.metadata as m; print(m.version('xtquant'))").Trim()

$PackageTarget = Join-Path $ResolvedInstallRoot "qmt_agent"
New-Item -ItemType Directory -Force -Path $PackageTarget | Out-Null
Copy-Item -Recurse -Force -Path (Join-Path $PackageSource "*") -Destination $PackageTarget
foreach ($Name in @("logs", "state", "secrets")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $ResolvedInstallRoot $Name) | Out-Null
}

$QmtVersion = "unknown"
$QmtExecutable = Join-Path $ResolvedQmtRoot "bin.x64\XtMiniQmt.exe"
if (Test-Path -LiteralPath $QmtExecutable) {
    $QmtVersion = (Get-Item -LiteralPath $QmtExecutable).VersionInfo.FileVersion
}
$Config = [ordered]@{
    agent_id = $AgentId
    server_url = $ServerUrl.TrimEnd("/")
    qmt_userdata_path = $QmtUserdataPath
    broker_account_id = $BrokerAccountId
    broker_account_type = "STOCK"
    system_account_id = $SystemAccountId
    qmt_client_version = $QmtVersion
    xtquant_version = $XtQuantVersion
    poll_interval_seconds = 2
    lease_seconds = 30
    dry_run = $true
    log_dir = (Join-Path $ResolvedInstallRoot "logs")
    state_dir = (Join-Path $ResolvedInstallRoot "state")
    kill_switch_file = (Join-Path $ResolvedInstallRoot "STOP")
    verify_tls = $true
    enforce_trading_session = $true
    trading_timezone = "Asia/Shanghai"
    allowed_trading_windows = @("09:30-11:30", "13:00-15:00")
    price_deviation_limit_pct = 0.03
    max_position_count = 20
}
$ConfigPath = Join-Path $ResolvedInstallRoot "config.json"
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($ConfigPath, ($Config | ConvertTo-Json -Depth 5), $Utf8NoBom)

$CurrentIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls.exe $ResolvedInstallRoot /inheritance:r /grant:r "${CurrentIdentity}:(OI)(CI)F" "SYSTEM:(OI)(CI)F" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Failed to restrict the Agent installation directory ACL."
}

if ($RegisterTask) {
    $StartScript = Join-Path $PackageTarget "scripts\start-agent.ps1"
    $Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument (
        "-NoProfile -ExecutionPolicy Bypass -File `"$StartScript`" " +
        "-PythonExe `"$RuntimePython`" -InstallRoot `"$ResolvedInstallRoot`""
    )
    $Trigger = New-ScheduledTaskTrigger -AtLogOn
    $Settings = New-ScheduledTaskSettingsSet -RestartCount 10 -RestartInterval (New-TimeSpan -Minutes 1)
    $Principal = New-ScheduledTaskPrincipal -UserId $CurrentIdentity -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName "AgomQmtAgent" -Action $Action -Trigger $Trigger `
        -Settings $Settings -Principal $Principal `
        -Description "AgomTradePro local QMT execution Agent" -Force | Out-Null
}

Push-Location $ResolvedInstallRoot
try {
    & $RuntimePython -m qmt_agent.main --config $ConfigPath --preflight
    if ($LASTEXITCODE -ne 0) {
        throw "Agent preflight failed. Review the printed checks before continuing."
    }
    if ($RunReadProbe) {
        $EvidencePath = Join-Path $ResolvedInstallRoot "logs\qmt-read-probe.json"
        & $RuntimePython -m qmt_agent.main --config $ConfigPath --qmt-read-probe --evidence-file $EvidencePath
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "The read-only QMT probe did not pass. No order or cancellation was sent."
        }
    }
}
finally {
    Pop-Location
}

$MaskedAccount = if ($BrokerAccountId.Length -gt 4) { "****" + $BrokerAccountId.Substring($BrokerAccountId.Length - 4) } else { "****" }
Write-Host "QMT Agent installed at $ResolvedInstallRoot"
Write-Host "QMT userdata: $QmtUserdataPath"
Write-Host "Broker account: $MaskedAccount"
Write-Host "Dry-run remains enabled. Store the Agent token with Set-AgentToken.ps1 before starting the task."
