# AgomSaaS SDK & MCP Integration Test Orchestrator
# Version: 1.0
# This script runs all SDK and MCP integration tests

[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)]
    [ValidateSet('quick', 'full', 'mcp-only', 'sdk-only')]
    [string]$TestMode = 'full',

    [Parameter(Mandatory=$false)]
    [switch]$SkipServerCheck,

    [Parameter(Mandatory=$false)]
    [switch]$NoCoverage,

    [Parameter(Mandatory=$false)]
    [string]$OutputPath = (Join-Path $PSScriptRoot "test-results")
)

$ErrorActionPreference = 'Stop'
$PythonExe = "agomsaaf\Scripts\python.exe"

# ==============================================================================
# Helper Functions
# ==============================================================================

function Write-Header {
    param([string]$Title)
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host " $Title" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""
}

function Write-Section {
    param([string]$Title)
    Write-Host ""
    Write-Host "--- $Title ---" -ForegroundColor Yellow
}

function Write-Success {
    param([string]$Message)
    Write-Host "[OK] $Message" -ForegroundColor Green
}

function Write-Error {
    param([string]$Message)
    Write-Host "[FAIL] $Message" -ForegroundColor Red
}

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Gray
}

function Test-VirtualEnvironment {
    if (-not (Test-Path $PythonExe)) {
        Write-Error "Virtual environment not found!"
        Write-Info "Please run: python -m venv agomsaaf"
        return $false
    }
    Write-Success "Virtual environment found"
    return $true
}

function Test-ServerRunning {
    if ($SkipServerCheck) {
        Write-Info "Skipping server check"
        return $true
    }

    Write-Info "Checking if server is running..."
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8000/api/" -TimeoutSec 5 -UseBasicParsing
        Write-Success "Server is running"
        return $true
    }
    catch {
        Write-Error "Server is not running!"
        Write-Info "Please start the server first: .\scripts\start-dev.ps1"
        return $false
    }
}

function Initialize-OutputPath {
    if (-not (Test-Path $OutputPath)) {
        New-Item -ItemType Directory -Path $OutputPath -Force | Out-Null
        Write-Info "Created output directory: $OutputPath"
    }
}

# ==============================================================================
# Test Functions
# ==============================================================================

function Test-SDKConnection {
    Write-Section "Running SDK Connection Tests"

    $testFile = Join-Path $PSScriptRoot "tests\acceptance\test_sdk_connection.py"
    $outputFile = Join-Path $OutputPath "sdk_connection.log"

    if (-not (Test-Path $testFile)) {
        Write-Error "Test file not found: $testFile"
        return $false
    }

    & $PythonExe $testFile *>&1 | Tee-Object -FilePath $outputFile
    $result = $LASTEXITCODE

    if ($result -eq 0) {
        Write-Success "SDK connection tests passed"
        return $true
    }
    else {
        Write-Error "SDK connection tests failed"
        return $false
    }
}

function Test-MCPServer {
    Write-Section "Running MCP Server Tests"

    $testFile = Join-Path $PSScriptRoot "tests\acceptance\test_mcp_server.py"
    $outputFile = Join-Path $OutputPath "mcp_server.log"

    if (-not (Test-Path $testFile)) {
        Write-Error "Test file not found: $testFile"
        return $false
    }

    & $PythonExe $testFile *>&1 | Tee-Object -FilePath $outputFile
    $result = $LASTEXITCODE

    if ($result -eq 0) {
        Write-Success "MCP server tests passed"
        return $true
    }
    else {
        Write-Error "MCP server tests failed"
        return $false
    }
}

function Test-Integration {
    Write-Section "Running Integration Tests"

    $integrationDir = Join-Path $PSScriptRoot "tests\integration"

    if (-not (Test-Path $integrationDir)) {
        Write-Error "Integration tests directory not found: $integrationDir"
        return $false
    }

    $testFiles = @(
        "test_complete_investment_flow.py",
        "test_backtesting_flow.py",
        "test_realtime_monitoring_flow.py"
    )

    $allPassed = $true

    foreach ($testFile in $testFiles) {
        $testPath = Join-Path $integrationDir $testFile

        if (Test-Path $testPath) {
            Write-Info "Running $testFile..."

            $logFile = Join-Path $OutputPath "$($testFile -replace '\.py$', '.log')"

            & $PythonExe $testPath *>&1 | Tee-Object -FilePath $logFile
            $result = $LASTEXITCODE

            if ($result -ne 0) {
                Write-Error "$testFile failed"
                $allPassed = $false
            }
        }
        else {
            Write-Info "Skipping $testFile (not found)"
        }
    }

    if ($allPassed) {
        Write-Success "All integration tests passed"
    }
    else {
        Write-Error "Some integration tests failed"
    }

    return $allPassed
}

function Test-Pytest {
    Write-Section "Running Pytest Tests"

    $sdkDir = Join-Path $PSScriptRoot "sdk"
    $pytestArgs = @("-v", "--tb=short")

    if ($NoCoverage) {
        $pytestArgs += "--no-cov"
    }
    else {
        $pytestArgs += "--cov=agomsaaf", "--cov-report=term-missing", "--cov-report=html"
    }

    $outputFile = Join-Path $OutputPath "pytest.log"

    Push-Location $sdkDir
    try {
        & $PythonExe -m pytest $pytestArgs *>&1 | Tee-Object -FilePath $outputFile
        $result = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }

    if ($result -eq 0) {
        Write-Success "Pytest tests passed"
        return $true
    }
    else {
        Write-Error "Pytest tests failed"
        return $false
    }
}

function Test-LogicGuardrails {
    Write-Section "Running Logic Guardrail Tests"

    $testTargets = @(
        "tests\guardrails\test_logic_guardrails.py",
        "tests\integration\policy\test_policy_integration.py",
        "tests\unit\policy\test_fetch_rss_use_case.py",
        "tests\unit\regime\test_config_threshold_regression.py"
    )
    $outputFile = Join-Path $OutputPath "logic_guardrails.log"

    Push-Location $PSScriptRoot
    try {
        & $PythonExe -m pytest -q @testTargets *>&1 | Tee-Object -FilePath $outputFile
        $result = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }

    if ($result -eq 0) {
        Write-Success "Logic guardrail tests passed"
        return $true
    }
    else {
        Write-Error "Logic guardrail tests failed"
        return $false
    }
}

# ==============================================================================
# Main Execution
# ==============================================================================

$startTime = Get-Date

Write-Header "AgomSAAF SDK & MCP Integration Tests"

# Check prerequisites
Write-Section "Checking Prerequisites"

$veOk = Test-VirtualEnvironment
if (-not $veOk) {
    exit 1
}

$serverOk = Test-ServerRunning
if (-not $serverOk) {
    exit 1
}

Initialize-OutputPath

# Run tests based on mode
$results = @()

switch ($TestMode) {
    'sdk-only' {
        $results += @(
            @{Name = "SDK Connection"; Result = (Test-SDKConnection)}
        )
    }

    'mcp-only' {
        $results += @(
            @{Name = "MCP Server"; Result = (Test-MCPServer)}
        )
    }

    'quick' {
        $results += @(
            @{Name = "SDK Connection"; Result = (Test-SDKConnection)}
            @{Name = "MCP Server"; Result = (Test-MCPServer)}
            @{Name = "Logic Guardrails"; Result = (Test-LogicGuardrails)}
        )
    }

    'full' {
        $results += @(
            @{Name = "SDK Connection"; Result = (Test-SDKConnection)}
            @{Name = "MCP Server"; Result = (Test-MCPServer)}
            @{Name = "Integration Tests"; Result = (Test-Integration)}
            @{Name = "Pytest Tests"; Result = (Test-Pytest)}
            @{Name = "Logic Guardrails"; Result = (Test-LogicGuardrails)}
        )
    }
}

# ==============================================================================
# Summary
# ==============================================================================

$endTime = Get-Date
$duration = $endTime - $startTime

Write-Header "Test Summary"

foreach ($result in $results) {
    $status = if ($result.Result) { "PASS" } else { "FAIL" }
    $symbol = if ($result.Result) { "[OK]" } else { "[X]" }
    $color = if ($result.Result) { "Green" } else { "Red" }

    Write-Host "$symbol $($result.Name): $status" -ForegroundColor $color
}

Write-Host ""
Write-Host "Duration: $($duration.TotalSeconds.ToString('0.00')) seconds" -ForegroundColor Cyan
Write-Host "Output directory: $OutputPath" -ForegroundColor Cyan

$allPassed = $results | Where-Object { -not $_.Result } | Measure-Object | Select-Object -ExpandProperty Count -eq 0

if ($allPassed) {
    Write-Host ""
    Write-Success "All tests passed!"
    exit 0
}
else {
    $failedCount = ($results | Where-Object { -not $_.Result }).Count
    Write-Host ""
    Write-Error "$failedCount test suite(s) failed"
    Write-Info "Check logs in: $OutputPath"
    exit 1
}
