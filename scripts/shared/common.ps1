Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Cyan
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Write-Err {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

function Throw-Err {
    param([string]$Message)
    Write-Err $Message
    throw $Message
}

function Require-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        Throw-Err "Missing command: $Name"
    }
}

function Read-Default {
    param(
        [string]$Prompt,
        [string]$Default
    )
    $value = Read-Host "$Prompt [$Default]"
    if ([string]::IsNullOrWhiteSpace($value)) {
        return $Default
    }
    return $value
}
