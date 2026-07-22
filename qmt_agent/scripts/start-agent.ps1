param(
    [Parameter(Mandatory = $true)][string]$PythonExe,
    [string]$InstallRoot = "$env:LOCALAPPDATA\AgomQmtAgent",
    [switch]$Preflight,
    [switch]$ReadProbe,
    [string]$EvidenceFile = "",
    [switch]$Once
)

$ErrorActionPreference = "Stop"
$JsonConfigPath = Join-Path $InstallRoot "config.json"
$YamlConfigPath = Join-Path $InstallRoot "config.yaml"
if (Test-Path -LiteralPath $JsonConfigPath) {
    $ConfigPath = $JsonConfigPath
}
elseif (Test-Path -LiteralPath $YamlConfigPath) {
    $ConfigPath = $YamlConfigPath
}
else {
    throw "Agent configuration does not exist below: $InstallRoot"
}

if (-not $Preflight -and -not $ReadProbe -and -not $env:AGOM_QMT_AGENT_TOKEN) {
    $SecretPath = Join-Path $InstallRoot "secrets\agent-token.dpapi"
    if (-not (Test-Path -LiteralPath $SecretPath)) {
        throw "Agent token is unavailable. Run Set-AgentToken.ps1 as the scheduled-task user."
    }
    $SecureToken = Get-Content -LiteralPath $SecretPath -Raw | ConvertTo-SecureString
    $TokenPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureToken)
    try {
        $env:AGOM_QMT_AGENT_TOKEN = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($TokenPointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($TokenPointer)
    }
}

$Arguments = @("-m", "qmt_agent.main", "--config", $ConfigPath)
if ($Preflight) {
    $Arguments += "--preflight"
}
if ($ReadProbe) {
    $Arguments += "--qmt-read-probe"
}
if ($EvidenceFile) {
    $Arguments += @("--evidence-file", $EvidenceFile)
}
if ($Once) {
    $Arguments += "--once"
}

Push-Location $InstallRoot
try {
    & $PythonExe @Arguments
    exit $LASTEXITCODE
}
finally {
    $env:AGOM_QMT_AGENT_TOKEN = $null
    Pop-Location
}
