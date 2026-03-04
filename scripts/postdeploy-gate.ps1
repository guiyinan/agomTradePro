#!/usr/bin/env pwsh
# AgomSAAF Post-Deploy Gate Script
# Default mode is strict: health + business read/write/readback + celery + alert chain.

param(
    [int]$Port = 8000,
    [string]$BaseUrl = "http://127.0.0.1:$Port",
    [int]$TimeoutSec = 60,
    [switch]$Verbose,

    [switch]$SkipBusinessChecks,
    [string]$BusinessReadUrl = "",
    [string]$BusinessWriteUrl = "",
    [string]$BusinessWriteMethod = "POST",
    [string]$BusinessWriteBody = "{}",
    [string]$BusinessWriteHeadersJson = "{}",
    [string]$BusinessReadbackUrlTemplate = "",

    [switch]$SkipCeleryChecks,
    [string]$CeleryTriggerUrl = "",
    [string]$CeleryTriggerMethod = "POST",
    [string]$CeleryTriggerBody = "{}",
    [string]$CeleryTriggerHeadersJson = "{}",
    [string]$CeleryStatusUrlTemplate = "",
    [int]$CeleryPollSeconds = 30,
    [string]$CelerySuccessStates = "SUCCESS,COMPLETED,DONE",

    [switch]$SkipAlertChecks,
    [string]$AlertTriggerUrl = "",
    [string]$AlertTriggerMethod = "POST",
    [string]$AlertTriggerBody = "{}",
    [string]$AlertTriggerHeadersJson = "{}",
    [string]$AlertVerifyUrl = "",
    [string]$AlertVerifyContains = ""
)

$ErrorActionPreference = "Stop"

function Write-Status {
    param([string]$Message, [string]$Level = "INFO")
    $color = switch ($Level) {
        "INFO" { "Cyan" }
        "OK" { "Green" }
        "WARN" { "Yellow" }
        "ERROR" { "Red" }
        default { "White" }
    }
    Write-Host "[$Level] $Message" -ForegroundColor $color
}

function Parse-HeadersJson {
    param([string]$JsonText)
    if (-not $JsonText) { return @{} }
    try {
        $obj = $JsonText | ConvertFrom-Json -AsHashtable
        if ($null -eq $obj) { return @{} }
        return $obj
    } catch {
        throw "Invalid headers JSON: $JsonText"
    }
}

function Invoke-HttpCall {
    param(
        [string]$Url,
        [string]$Method = "GET",
        [string]$Body = "",
        [hashtable]$Headers = @{},
        [int]$ReqTimeoutSec = 10
    )

    try {
        $invokeParams = @{
            Uri = $Url
            Method = $Method
            UseBasicParsing = $true
            TimeoutSec = $ReqTimeoutSec
            Headers = $Headers
        }
        if ($Method -ne "GET" -and $Body -ne "") {
            $invokeParams["Body"] = $Body
            if (-not $Headers.ContainsKey("Content-Type")) {
                $invokeParams["ContentType"] = "application/json"
            }
        }

        $resp = Invoke-WebRequest @invokeParams
        $json = $null
        if ($resp.Content) {
            try { $json = $resp.Content | ConvertFrom-Json } catch {}
        }

        return @{
            Ok = $true
            StatusCode = [int]$resp.StatusCode
            Content = $resp.Content
            Json = $json
            Error = ""
        }
    } catch {
        $statusCode = 0
        $content = ""
        if ($_.Exception.Response) {
            try { $statusCode = [int]$_.Exception.Response.StatusCode.value__ } catch {}
            try {
                $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
                $content = $reader.ReadToEnd()
                $reader.Close()
            } catch {}
        }
        return @{
            Ok = $false
            StatusCode = $statusCode
            Content = $content
            Json = $null
            Error = $_.Exception.Message
        }
    }
}

function Is-AcceptableStatus {
    param([int]$StatusCode)
    return ($StatusCode -ge 200 -and $StatusCode -lt 400) -or $StatusCode -eq 401 -or $StatusCode -eq 403
}

function Get-IdFromJson {
    param($JsonObj)
    if ($null -eq $JsonObj) { return "" }
    foreach ($k in @("id", "task_id", "request_id", "pk", "uuid")) {
        if ($JsonObj.PSObject.Properties.Name -contains $k) {
            $v = [string]$JsonObj.$k
            if ($v) { return $v }
        }
    }
    return ""
}

function Test-HealthEndpoint {
    param([string]$Url)
    $resp = Invoke-HttpCall -Url $Url -Method "GET" -ReqTimeoutSec 5
    if (Is-AcceptableStatus -StatusCode $resp.StatusCode) {
        Write-Status "Health check passed: $Url [$($resp.StatusCode)]" "OK"
        return $true
    }
    Write-Status "Health check failed: $Url [$($resp.StatusCode)] $($resp.Error)" "ERROR"
    return $false
}

function Test-BusinessReadWriteReadback {
    param([string]$BaseUrlForLog)

    if (-not $BusinessReadUrl -or -not $BusinessWriteUrl -or -not $BusinessReadbackUrlTemplate) {
        Write-Status "Business checks require BusinessReadUrl, BusinessWriteUrl, BusinessReadbackUrlTemplate" "ERROR"
        return $false
    }

    $writeHeaders = Parse-HeadersJson -JsonText $BusinessWriteHeadersJson

    if ($Verbose) { Write-Status "Business read: $BusinessReadUrl" "INFO" }
    $readResp = Invoke-HttpCall -Url $BusinessReadUrl -Method "GET" -ReqTimeoutSec 10
    if (-not (Is-AcceptableStatus -StatusCode $readResp.StatusCode)) {
        Write-Status "Business read failed [$($readResp.StatusCode)]" "ERROR"
        return $false
    }
    Write-Status "Business read passed [$($readResp.StatusCode)]" "OK"

    if ($Verbose) { Write-Status "Business write: $BusinessWriteMethod $BusinessWriteUrl" "INFO" }
    $writeResp = Invoke-HttpCall -Url $BusinessWriteUrl -Method $BusinessWriteMethod -Body $BusinessWriteBody -Headers $writeHeaders -ReqTimeoutSec 15
    if (-not (Is-AcceptableStatus -StatusCode $writeResp.StatusCode)) {
        Write-Status "Business write failed [$($writeResp.StatusCode)]" "ERROR"
        return $false
    }
    Write-Status "Business write passed [$($writeResp.StatusCode)]" "OK"

    $createdId = Get-IdFromJson -JsonObj $writeResp.Json
    $readbackUrl = $BusinessReadbackUrlTemplate
    if ($readbackUrl.Contains("{id}")) {
        if (-not $createdId) {
            Write-Status "Business readback template contains {id} but write response has no id" "ERROR"
            return $false
        }
        $readbackUrl = $readbackUrl.Replace("{id}", $createdId)
    }

    if ($Verbose) { Write-Status "Business readback: $readbackUrl" "INFO" }
    $readbackResp = Invoke-HttpCall -Url $readbackUrl -Method "GET" -ReqTimeoutSec 10
    if (-not (Is-AcceptableStatus -StatusCode $readbackResp.StatusCode)) {
        Write-Status "Business readback failed [$($readbackResp.StatusCode)]" "ERROR"
        return $false
    }
    Write-Status "Business readback passed [$($readbackResp.StatusCode)]" "OK"
    return $true
}

function Test-CeleryFlow {
    if (-not $CeleryTriggerUrl -or -not $CeleryStatusUrlTemplate) {
        Write-Status "Celery checks require CeleryTriggerUrl and CeleryStatusUrlTemplate" "ERROR"
        return $false
    }

    $triggerHeaders = Parse-HeadersJson -JsonText $CeleryTriggerHeadersJson
    $resp = Invoke-HttpCall -Url $CeleryTriggerUrl -Method $CeleryTriggerMethod -Body $CeleryTriggerBody -Headers $triggerHeaders -ReqTimeoutSec 15
    if (-not (Is-AcceptableStatus -StatusCode $resp.StatusCode)) {
        Write-Status "Celery trigger failed [$($resp.StatusCode)]" "ERROR"
        return $false
    }

    $taskId = Get-IdFromJson -JsonObj $resp.Json
    if (-not $taskId) {
        Write-Status "Celery trigger response missing task id" "ERROR"
        return $false
    }

    $successStates = @()
    foreach ($x in $CelerySuccessStates.Split(",")) {
        $s = $x.Trim().ToUpperInvariant()
        if ($s) { $successStates += $s }
    }

    $deadline = (Get-Date).AddSeconds($CeleryPollSeconds)
    while ((Get-Date) -lt $deadline) {
        $statusUrl = $CeleryStatusUrlTemplate.Replace("{task_id}", $taskId)
        $statusResp = Invoke-HttpCall -Url $statusUrl -Method "GET" -ReqTimeoutSec 10
        if ($Verbose) { Write-Status "Celery status [$($statusResp.StatusCode)] from $statusUrl" "INFO" }
        if (Is-AcceptableStatus -StatusCode $statusResp.StatusCode) {
            $state = ""
            if ($statusResp.Json) {
                if ($statusResp.Json.PSObject.Properties.Name -contains "state") { $state = [string]$statusResp.Json.state }
                elseif ($statusResp.Json.PSObject.Properties.Name -contains "status") { $state = [string]$statusResp.Json.status }
            }
            $state = $state.ToUpperInvariant()
            if ($state -and ($successStates -contains $state)) {
                Write-Status "Celery task completed: $taskId ($state)" "OK"
                return $true
            }
        }
        Start-Sleep -Seconds 2
    }

    Write-Status "Celery task did not reach success state within $CeleryPollSeconds seconds" "ERROR"
    return $false
}

function Test-AlertChain {
    if (-not $AlertTriggerUrl -or -not $AlertVerifyUrl -or -not $AlertVerifyContains) {
        Write-Status "Alert checks require AlertTriggerUrl, AlertVerifyUrl, AlertVerifyContains" "ERROR"
        return $false
    }

    $triggerHeaders = Parse-HeadersJson -JsonText $AlertTriggerHeadersJson
    $triggerResp = Invoke-HttpCall -Url $AlertTriggerUrl -Method $AlertTriggerMethod -Body $AlertTriggerBody -Headers $triggerHeaders -ReqTimeoutSec 15
    if (-not (Is-AcceptableStatus -StatusCode $triggerResp.StatusCode)) {
        Write-Status "Alert trigger failed [$($triggerResp.StatusCode)]" "ERROR"
        return $false
    }
    Write-Status "Alert trigger passed [$($triggerResp.StatusCode)]" "OK"

    Start-Sleep -Seconds 2

    $verifyResp = Invoke-HttpCall -Url $AlertVerifyUrl -Method "GET" -ReqTimeoutSec 15
    if (-not (Is-AcceptableStatus -StatusCode $verifyResp.StatusCode)) {
        Write-Status "Alert verification request failed [$($verifyResp.StatusCode)]" "ERROR"
        return $false
    }

    if ($verifyResp.Content -and $verifyResp.Content.Contains($AlertVerifyContains)) {
        Write-Status "Alert chain verified by marker: $AlertVerifyContains" "OK"
        return $true
    }

    Write-Status "Alert marker not found in verification response" "ERROR"
    return $false
}

# Main execution
Write-Host ""
Write-Host "=======================================" -ForegroundColor Cyan
Write-Host " AgomSAAF Post-Deploy Gate" -ForegroundColor Cyan
Write-Host "=======================================" -ForegroundColor Cyan
Write-Host ""

$startTime = Get-Date
$allPassed = $true

# Step 1: Test main health endpoint
Write-Status "Step 1: Testing main health endpoint..." "INFO"
$healthUrl = "$BaseUrl/api/health/"
if (-not (Test-HealthEndpoint -Url $healthUrl)) {
    $allPassed = $false
    Write-Status "Main health check failed - aborting" "ERROR"
    exit 1
}
Write-Host ""

# Step 2: Test database health
Write-Status "Step 2: Testing database health endpoint..." "INFO"
$dbResp = Invoke-HttpCall -Url "$BaseUrl/api/health/db/" -Method "GET" -ReqTimeoutSec 5
if ($dbResp.StatusCode -eq 404) {
    Write-Status "Database health endpoint not found (optional)" "WARN"
} elseif (Is-AcceptableStatus -StatusCode $dbResp.StatusCode) {
    Write-Status "Database health endpoint passed [$($dbResp.StatusCode)]" "OK"
} else {
    Write-Status "Database health endpoint failed [$($dbResp.StatusCode)]" "ERROR"
    $allPassed = $false
}
Write-Host ""

# Step 3: Business read/write/readback
if ($SkipBusinessChecks) {
    Write-Status "Step 3: Business read/write/readback skipped by flag" "WARN"
} else {
    Write-Status "Step 3: Testing business read/write/readback..." "INFO"
    if (-not (Test-BusinessReadWriteReadback -BaseUrlForLog $BaseUrl)) {
        $allPassed = $false
    }
}
Write-Host ""

# Step 4: Celery trigger and observable completion
if ($SkipCeleryChecks) {
    Write-Status "Step 4: Celery checks skipped by flag" "WARN"
} else {
    Write-Status "Step 4: Testing Celery trigger and completion..." "INFO"
    if (-not (Test-CeleryFlow)) {
        $allPassed = $false
    }
}
Write-Host ""

# Step 5: Alert chain trigger and verify
if ($SkipAlertChecks) {
    Write-Status "Step 5: Alert checks skipped by flag" "WARN"
} else {
    Write-Status "Step 5: Testing alert chain..." "INFO"
    if (-not (Test-AlertChain)) {
        $allPassed = $false
    }
}
Write-Host ""

# Summary
$duration = (Get-Date) - $startTime
Write-Host "=======================================" -ForegroundColor Cyan
Write-Host " Post-Deploy Gate Summary" -ForegroundColor Cyan
Write-Host "=======================================" -ForegroundColor Cyan
Write-Host "Duration: $($duration.TotalSeconds.ToString('0.00'))s"
Write-Host "Strict checks enabled:"
Write-Host "  Business: $(-not $SkipBusinessChecks)"
Write-Host "  Celery:   $(-not $SkipCeleryChecks)"
Write-Host "  Alert:    $(-not $SkipAlertChecks)"
Write-Host ""

if ($allPassed) {
    Write-Status "POST-DEPLOY GATE: PASSED" "OK"
    exit 0
} else {
    Write-Status "POST-DEPLOY GATE: FAILED" "ERROR"
    exit 1
}
