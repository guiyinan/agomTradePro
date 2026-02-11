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
    param(
        [string]$Name,
        [string]$HelpMessage
    )

    # First try: check if command already exists
    if (Get-Command $Name -ErrorAction SilentlyContinue) {
        return
    }

    # Special handling for docker
    if ($Name -eq "docker") {
        # Try to find docker.exe in common Docker Desktop locations
        $dockerPaths = @(
            "C:\Program Files\Docker\Docker\resources\bin\docker.exe",
            "C:\Program Files\Docker\Docker\resources\docker.exe",
            "$env:LOCALAPPDATA\Docker\docker.exe"
        )

        foreach ($path in $dockerPaths) {
            if (Test-Path $path) {
                $dockerDir = Split-Path -Parent $path
                $env:Path = "$dockerDir;$env:Path"
                Write-Info "Docker found at: $path"
                return
            }
        }

        # Refresh PATH from environment
        $machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
        $userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
        $env:Path = "$machinePath;$userPath"

        if (Get-Command docker -ErrorAction SilentlyContinue) {
            Write-Info "Docker found after PATH refresh"
            return
        }
    }

    if ($HelpMessage) {
        Throw-Err $HelpMessage
    } else {
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
