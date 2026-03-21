param(
    [Alias("Host")]
    [string]$VpsHost,
    [int]$Port,
    [string]$User,
    [string]$PasswordFile,
    [string]$RemoteDir,
    [string]$TargetDir,
    [int]$HttpPort,
    [string]$Domain,
    [string]$AllowedHosts,
    [ValidateSet("fresh", "upgrade")]
    [string]$Action,
    [switch]$IncludeSqlite,
    [switch]$WipeDocker,
    [switch]$KeepRemoteTemp,
    [switch]$DownloadReport,
    [switch]$DownloadBuiltImage,
    [switch]$NoDownloadBuiltImage,
    [string]$ReportDir,
    [string]$BuiltImageDir,
    [int]$Timeout,
    [switch]$EnableRsshub,
    [switch]$DisableRsshub,
    [switch]$EnableCelery,
    [string]$EncryptionKey,
    [switch]$PromptBeforeDeploy,
    [switch]$NoPromptBeforeDeploy,
    [switch]$SkipDeployAfterBuild,
    [switch]$Help,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArgs
)

# Notes:
# - Interactive mode now asks whether to deploy after remote build.
# - For build-only usage, answer "No" to that prompt or pass -SkipDeployAfterBuild.
# - In build-only mode, after a successful download the script cleans remote image tar, build image, dangling images, and temp reports by default.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. "$PSScriptRoot/shared/common.ps1"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$ProjectPython = Join-Path $ProjectRoot "agomtradepro\Scripts\python.exe"
$PythonExe = $null

if (Test-Path $ProjectPython) {
    $PythonExe = $ProjectPython
}
else {
    Require-Command python
    $PythonExe = (Get-Command python).Source
    Write-Warn "Project virtualenv python not found, falling back to: $PythonExe"
}

$pythonScript = Join-Path $PSScriptRoot "remote_build_deploy_vps.py"
if (-not (Test-Path $pythonScript)) {
    Throw-Err "Python script not found: $pythonScript"
}

function Add-Arg {
    param(
        [System.Collections.Generic.List[string]]$ArgsList,
        [string]$Name,
        [object]$Value
    )

    if ($null -eq $Value) { return }
    if ($Value -is [string] -and [string]::IsNullOrWhiteSpace($Value)) { return }

    $ArgsList.Add($Name)
    $ArgsList.Add([string]$Value)
}

$pyArgs = [System.Collections.Generic.List[string]]::new()
$pyArgs.Add($pythonScript)

if ($Help) {
    $pyArgs.Add("--help")
}
else {
    Add-Arg -ArgsList $pyArgs -Name "--host" -Value $VpsHost
    if ($PSBoundParameters.ContainsKey("Port")) { Add-Arg -ArgsList $pyArgs -Name "--port" -Value $Port }
    Add-Arg -ArgsList $pyArgs -Name "--user" -Value $User
    Add-Arg -ArgsList $pyArgs -Name "--password-file" -Value $PasswordFile
    Add-Arg -ArgsList $pyArgs -Name "--remote-dir" -Value $RemoteDir
    Add-Arg -ArgsList $pyArgs -Name "--target-dir" -Value $TargetDir
    if ($PSBoundParameters.ContainsKey("HttpPort")) { Add-Arg -ArgsList $pyArgs -Name "--http-port" -Value $HttpPort }
    Add-Arg -ArgsList $pyArgs -Name "--domain" -Value $Domain
    Add-Arg -ArgsList $pyArgs -Name "--allowed-hosts" -Value $AllowedHosts
    Add-Arg -ArgsList $pyArgs -Name "--action" -Value $Action
    if ($IncludeSqlite) { $pyArgs.Add("--include-sqlite") }
    if ($WipeDocker) { $pyArgs.Add("--wipe-docker") }
    if ($KeepRemoteTemp) { $pyArgs.Add("--keep-remote-temp") }
    if ($DownloadReport) { $pyArgs.Add("--download-report") }
    Add-Arg -ArgsList $pyArgs -Name "--report-dir" -Value $ReportDir
    $shouldDownloadBuiltImage = $true
    if ($NoDownloadBuiltImage) { $shouldDownloadBuiltImage = $false }
    if ($DownloadBuiltImage) { $shouldDownloadBuiltImage = $true }
    if ($shouldDownloadBuiltImage) { $pyArgs.Add("--download-built-image") }
    Add-Arg -ArgsList $pyArgs -Name "--built-image-dir" -Value $BuiltImageDir
    if ($PSBoundParameters.ContainsKey("Timeout")) { Add-Arg -ArgsList $pyArgs -Name "--timeout" -Value $Timeout }
    if ($EnableRsshub) { $pyArgs.Add("--enable-rsshub") }
    if ($DisableRsshub) { $pyArgs.Add("--disable-rsshub") }
    if ($EnableCelery) { $pyArgs.Add("--enable-celery") }
    Add-Arg -ArgsList $pyArgs -Name "--encryption-key" -Value $EncryptionKey
    $shouldPromptBeforeDeploy = $false
    if ($NoPromptBeforeDeploy) { $shouldPromptBeforeDeploy = $false }
    if ($PromptBeforeDeploy) { $shouldPromptBeforeDeploy = $true }
    if ($shouldPromptBeforeDeploy) { $pyArgs.Add("--prompt-before-deploy") }
    if ($SkipDeployAfterBuild) { $pyArgs.Add("--skip-deploy-after-build") }

    foreach ($arg in $RemainingArgs) {
        if (-not [string]::IsNullOrWhiteSpace($arg)) {
            $pyArgs.Add($arg)
        }
    }
}

Write-Info ("Running remote build helper: " + $PythonExe + " " + ($pyArgs -join " "))
& $PythonExe @pyArgs
exit $LASTEXITCODE
