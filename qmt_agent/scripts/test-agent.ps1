param(
    [string]$InstallRoot = "$env:LOCALAPPDATA\AgomQmtAgent",
    [switch]$ReadProbe
)

$ErrorActionPreference = "Stop"
$RuntimePython = Join-Path $InstallRoot "runtime\Scripts\python.exe"
$StartScript = Join-Path $InstallRoot "qmt_agent\scripts\start-agent.ps1"
if (-not (Test-Path -LiteralPath $RuntimePython) -or -not (Test-Path -LiteralPath $StartScript)) {
    throw "The QMT Agent installation is incomplete below: $InstallRoot"
}

& $StartScript -PythonExe $RuntimePython -InstallRoot $InstallRoot -Preflight
if ($LASTEXITCODE -ne 0) {
    throw "Agent preflight failed."
}
if ($ReadProbe) {
    $EvidencePath = Join-Path $InstallRoot "logs\qmt-read-probe.json"
    & $StartScript -PythonExe $RuntimePython -InstallRoot $InstallRoot `
        -ReadProbe -EvidenceFile $EvidencePath
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "The read-only QMT probe failed. No order or cancellation was sent."
        exit $LASTEXITCODE
    }
}
