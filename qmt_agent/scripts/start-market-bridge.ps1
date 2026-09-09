param(
    [Parameter(Mandatory = $true)][string]$PythonExe,
    [string]$InstallRoot = "$env:LOCALAPPDATA\AgomQmtAgent",
    [switch]$Pair,
    [string]$ServerUrl = "",
    [string]$AgentId = "",
    [switch]$Once,
    [string]$BackfillStart = "",
    [string]$BackfillEnd = ""
)

$ErrorActionPreference = "Stop"
$BridgeState = Join-Path $InstallRoot "market-state"
$Arguments = @("-m", "qmt_agent.main", "--bridge", "--state-dir", $BridgeState)
if ($Pair) {
    $Arguments += @("--pair", "--server", $ServerUrl, "--agent-id", $AgentId)
}
if ($Once) { $Arguments += "--once" }
if ($BackfillStart) {
    $Arguments += @("--backfill-start", $BackfillStart, "--backfill-end", $BackfillEnd)
}
Push-Location $InstallRoot
try {
    & $PythonExe @Arguments
    exit $LASTEXITCODE
}
finally { Pop-Location }
