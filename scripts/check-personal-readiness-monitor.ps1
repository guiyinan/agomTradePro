[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$SettingsModule = "core.settings.development",

    [Parameter(Mandatory = $false)]
    [double]$LocalRuntimePingTimeout = 12,

    [Parameter(Mandatory = $false)]
    [switch]$StrictAcceptance,

    [Parameter(Mandatory = $false)]
    [switch]$SummaryOnly,

    [Parameter(Mandatory = $false)]
    [switch]$LogToFile,

    [Parameter(Mandatory = $false)]
    [string]$ReferenceTime
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Resolve-PythonExe {
    $venvPython = Join-Path $root "agomtradepro\Scripts\python.exe"
    if ($env:CONDA_DEFAULT_ENV -eq "agomtradepro") {
        $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
        if ($pythonCmd) {
            return $pythonCmd.Source
        }
    }
    if (Test-Path $venvPython) {
        return $venvPython
    }
    throw "Python runtime not found. Activate conda env 'agomtradepro' or create venv at agomtradepro\Scripts\python.exe."
}

function Convert-MonitorPayload {
    param([object[]]$OutputLines)

    $lines = @($OutputLines | ForEach-Object { [string]$_ })
    $start = -1
    $end = -1

    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i].Trim() -eq "{") {
            $start = $i
            break
        }
    }

    for ($i = $lines.Count - 1; $i -ge 0; $i--) {
        if ($lines[$i].Trim() -eq "}") {
            $end = $i
            break
        }
    }

    if ($start -lt 0 -or $end -lt $start) {
        return $null
    }

    $jsonText = ($lines[$start..$end] -join [Environment]::NewLine)
    try {
        return $jsonText | ConvertFrom-Json
    } catch {
        return $null
    }
}

function Format-DurationMinutes {
    param([Nullable[int]]$Minutes)

    if ($null -eq $Minutes) {
        return $null
    }
    if ($Minutes -lt 60) {
        return ([string]$Minutes + "m")
    }

    $days = [math]::Floor($Minutes / 1440)
    $remaining = $Minutes % 1440
    $hours = [math]::Floor($remaining / 60)
    $mins = $remaining % 60
    $parts = @()
    if ($days -gt 0) {
        $parts += ([string]$days + "d")
    }
    if ($hours -gt 0) {
        $parts += ([string]$hours + "h")
    }
    if ($mins -gt 0 -or $parts.Count -eq 0) {
        $parts += ([string]$mins + "m")
    }
    return ($parts -join " ")
}

function Write-MonitorSummary {
    param(
        $Payload,
        [string]$ReferenceTime
    )

    if ($null -eq $Payload) {
        Write-Host "[WARN] Could not parse monitor JSON for summary." -ForegroundColor Yellow
        return
    }

    $gate = $Payload.monitor_gate
    $acceptance = $Payload.acceptance_gate
    $runtime = $Payload.scheduler_runtime
    $schedule = $Payload.schedule_expectation
    $nextAction = $Payload.next_action
    $latestFormal = $Payload.latest_formal_evidence
    $decisionData = $Payload.current_decision_data
    $decisionDataSource = "live"
    if (-not $decisionData) {
        $decisionData = $latestFormal.summary.decision_data
        $decisionDataSource = "evidence"
    }
    $marketThermometer = $decisionData.market_thermometer
    $skippedLatestThermometer = $decisionData.skipped_latest_market_thermometer
    $macroContext = $Payload.current_macro_context
    $macroContextSource = "live"
    if (-not $macroContext) {
        $macroContext = $latestFormal.summary.macro_context
        $macroContextSource = "evidence"
    }
    $regimeContext = $macroContext.regime
    $pulseContext = $macroContext.pulse
    $scheduler = $Payload.scheduler
    $runMetadata = $scheduler.run_metadata
    $quotePre = $Payload.quote_pre_readiness_scheduler
    $quotePreSchedule = $quotePre.schedule
    $quotePreSafety = $quotePre.safety
    $quotePreRunMetadata = $quotePre.run_metadata
    $quotePreExpectation = $quotePre.schedule_expectation
    $quotePreActivity = $acceptance.requirements.quote_pre_readiness_activity
    $qlibProof = $acceptance.requirements.qlib_formal_evidence
    $workspaceProof = $acceptance.requirements.workspace_core_formal_evidence
    $alphaProof = $acceptance.requirements.alpha_workspace_formal_evidence
    $decisionDataProof = $acceptance.requirements.decision_data_formal_evidence
    $quoteFreshnessProof = $acceptance.requirements.decision_quote_freshness_formal_evidence
    $riskProof = $acceptance.requirements.risk_center_formal_evidence
    $weeklyProof = $acceptance.requirements.auto_advisor_weekly_persistence
    $schedulerActivity = $acceptance.requirements.scheduler_activity
    $postPersistence = $Payload.post_evidence_persistence
    $postRisk = $postPersistence.risk_center_daily_report
    $postWeekly = $postPersistence.auto_advisor_weekly_report
    $operatorCheckAfter = $gate.next_check_after
    $operatorCheckReason = "daily_readiness"
    if ($ReferenceTime) {
        try {
            $operatorCheckNow = [datetimeoffset]::Parse($ReferenceTime)
        } catch {
            throw "ReferenceTime must be parseable as a datetime with timezone offset, for example 2026-07-03T16:20:00+08:00."
        }
    } else {
        $operatorCheckNow = [datetimeoffset]::Now
    }
    function Resolve-EarlierOperatorCheck {
        param(
            [string]$CurrentTime,
            [string]$CurrentReason,
            [string]$CandidateTime,
            [string]$CandidateReason,
            [datetimeoffset]$ReferenceTime
        )

        if (-not $CandidateTime) {
            return @{
                Time = $CurrentTime
                Reason = $CurrentReason
            }
        }
        $effectiveCurrentTime = $CurrentTime
        $effectiveCurrentReason = $CurrentReason
        if ($effectiveCurrentTime) {
            try {
                $currentAt = [datetimeoffset]::Parse($effectiveCurrentTime)
                if ($currentAt -lt $ReferenceTime) {
                    $effectiveCurrentTime = $null
                    $effectiveCurrentReason = $null
                }
            } catch {
                $effectiveCurrentTime = $null
                $effectiveCurrentReason = $null
            }
        }
        try {
            $candidateAt = [datetimeoffset]::Parse($CandidateTime)
            if ($candidateAt -lt $ReferenceTime) {
                return @{
                    Time = $effectiveCurrentTime
                    Reason = $effectiveCurrentReason
                }
            }
            if (-not $effectiveCurrentTime) {
                return @{
                    Time = $CandidateTime
                    Reason = $CandidateReason
                }
            }
            $currentAt = [datetimeoffset]::Parse($effectiveCurrentTime)
            if ($candidateAt -lt $currentAt) {
                return @{
                    Time = $CandidateTime
                    Reason = $CandidateReason
                }
            }
        } catch {
            if (-not $effectiveCurrentTime) {
                return @{
                    Time = $CandidateTime
                    Reason = $CandidateReason
                }
            }
        }
        return @{
            Time = $effectiveCurrentTime
            Reason = $effectiveCurrentReason
        }
    }
    if ($quotePreExpectation) {
        $quoteCheckAfter = $quotePreExpectation.grace_deadline
        if (-not $quoteCheckAfter) {
            $quoteCheckAfter = $quotePreExpectation.scheduled_for
        }
        $operatorCheck = Resolve-EarlierOperatorCheck -CurrentTime $operatorCheckAfter -CurrentReason $operatorCheckReason -CandidateTime $quoteCheckAfter -CandidateReason "quote_pre_refresh" -ReferenceTime $operatorCheckNow
        $operatorCheckAfter = $operatorCheck.Time
        $operatorCheckReason = $operatorCheck.Reason
    }
    if ($postWeekly) {
        $weeklyCheckAfter = $postWeekly.scheduled_for
        if (-not $weeklyCheckAfter) {
            $weeklyCheckAfter = $postWeekly.next_scheduled_for
        }
        $operatorCheck = Resolve-EarlierOperatorCheck -CurrentTime $operatorCheckAfter -CurrentReason $operatorCheckReason -CandidateTime $weeklyCheckAfter -CandidateReason "weekly_auto_advisor" -ReferenceTime $operatorCheckNow
        $operatorCheckAfter = $operatorCheck.Time
        $operatorCheckReason = $operatorCheck.Reason
    }
    if (-not $operatorCheckAfter) {
        $operatorCheckReason = "review_current_status"
    }
    $operatorCheckEtaMinutes = $null
    if ($operatorCheckAfter) {
        try {
            $operatorCheckEtaMinutes = [math]::Ceiling(
                ([datetimeoffset]::Parse([string]$operatorCheckAfter) - $operatorCheckNow).TotalMinutes
            )
        } catch {
            $operatorCheckEtaMinutes = $null
        }
    }

    Write-Host ""
    Write-Host "=======================================" -ForegroundColor Cyan
    Write-Host " Personal Readiness Monitor Summary" -ForegroundColor Cyan
    Write-Host "=======================================" -ForegroundColor Cyan
    Write-Host ("Status:                 " + $Payload.status)
    Write-Host ("Status date:            " + $Payload.status_date + " latest_closed=" + $Payload.latest_closed_date + " expected_latest=" + $Payload.expected_latest_date)
    Write-Host ("Monitor gate:           ok=" + $gate.ok + " state=" + $gate.state)
    Write-Host ("Accepted window:        " + $acceptance.accepted_days + "/" + $acceptance.required_days + " remaining=" + $acceptance.remaining_days)
    Write-Host ("Scheduler-clean window: " + $acceptance.scheduler_clean_suffix_days + "/" + $acceptance.required_days + " remaining=" + $acceptance.scheduler_clean_remaining_days)
    Write-Host ("Failed final gates:     " + ((@($acceptance.failed_requirements) | ForEach-Object { [string]$_.name }) -join ","))
    Write-Host ("Latest formal evidence: " + $latestFormal.target_date + " source=" + $latestFormal.trigger_source + " task=" + $latestFormal.trigger_task_name)
    Write-Host ("Scheduler runs:         count=" + $runMetadata.total_run_count + " last_run_at=" + $runMetadata.last_run_at)
    if ($schedulerActivity) {
        Write-Host ("Evidence provenance:    scheduler=" + $schedulerActivity.scheduler_trigger_record_count + " manual=" + $schedulerActivity.manual_trigger_record_count + " legacy=" + $schedulerActivity.legacy_record_count + " task_proof=" + $schedulerActivity.scheduler_task_provenance_record_count + " unique_task_ids=" + $schedulerActivity.unique_scheduler_task_id_count)
    }
    if ($quotePre) {
        Write-Host ("Quote pre-refresh:      " + $quotePre.status + " enabled=" + $quotePre.enabled + " @ " + $quotePreSchedule.hour + ":" + $quotePreSchedule.minute + " max_age_h=" + $quotePreSafety.quote_max_age_hours + " runs=" + $quotePreRunMetadata.total_run_count + " due=" + $quotePreExpectation.due_status + " scheduled_for=" + $quotePreExpectation.scheduled_for)
    } else {
        Write-Host "Quote pre-refresh:      unavailable"
    }
    if ($quotePreActivity) {
        Write-Host ("Quote pre-proof:        status=" + $quotePreActivity.status + " ok_records=" + $quotePreActivity.formal_quote_pre_readiness_scheduler_ok_record_count + " missing=" + $quotePreActivity.formal_quote_pre_readiness_scheduler_missing_record_count + " blocked=" + $quotePreActivity.formal_quote_pre_readiness_scheduler_blocked_record_count)
    }
    if ($qlibProof) {
        Write-Host ("Qlib proof:             status=" + $qlibProof.status + " records=" + $qlibProof.qlib_record_count + " ok=" + $qlibProof.ok_record_count + " missing=" + $qlibProof.missing_record_count + " blocked=" + $qlibProof.blocked_record_count)
    }
    if ($workspaceProof) {
        Write-Host ("Workspace proof:        status=" + $workspaceProof.status + " records=" + $workspaceProof.workspace_core_record_count + " ok=" + $workspaceProof.ok_record_count + " missing=" + $workspaceProof.missing_record_count)
    }
    if ($alphaProof) {
        Write-Host ("Alpha workspace proof:  status=" + $alphaProof.status + " records=" + $alphaProof.alpha_workspace_record_count + " ok=" + $alphaProof.ok_record_count + " missing=" + $alphaProof.missing_record_count)
    }
    if ($decisionDataProof) {
        Write-Host ("Decision data proof:    status=" + $decisionDataProof.status + " records=" + $decisionDataProof.decision_data_record_count + " ok=" + $decisionDataProof.ok_record_count + " missing=" + $decisionDataProof.missing_record_count + " blocked=" + $decisionDataProof.blocked_record_count)
    }
    if ($quoteFreshnessProof) {
        Write-Host ("Quote freshness proof:  status=" + $quoteFreshnessProof.status + " records=" + $quoteFreshnessProof.quote_freshness_record_count + " ok=" + $quoteFreshnessProof.ok_record_count + " missing=" + $quoteFreshnessProof.missing_record_count + " stale=" + $quoteFreshnessProof.stale_record_count + " blocked=" + $quoteFreshnessProof.blocked_record_count)
    }
    if ($decisionData) {
        $staleDetails = @($marketThermometer.stale_component_details) | ForEach-Object {
            if ($null -ne $_.age_days) {
                [string]$_.component_key + "(" + [string]$_.age_days + "d)"
            } else {
                [string]$_.component_key
            }
        }
        $missingDetails = @($marketThermometer.missing_component_details) | ForEach-Object {
            if ($null -ne $_.age_days) {
                [string]$_.component_key + "(" + [string]$_.age_days + "d)"
            } else {
                [string]$_.component_key
            }
        }
        $staleComponents = $staleDetails -join ","
        $missingComponents = $missingDetails -join ","
        if (-not $staleComponents) {
            $staleComponents = @($marketThermometer.stale_components) -join ","
        }
        if (-not $missingComponents) {
            $missingComponents = @($marketThermometer.missing_components) -join ","
        }
        $proxyDetails = @($marketThermometer.proxy_components) | Where-Object {
            $_.component_key -and $_.proxy
        } | ForEach-Object {
            [string]$_.component_key + ":" + [string]$_.proxy
        }
        $proxyComponents = $proxyDetails -join ","
        $proxyAudit = @($marketThermometer.proxy_components) | Where-Object {
            $_.component_key -and $_.proxy
        } | ForEach-Object {
            $verification = [string]$_.verification_status
            if (-not $verification) {
                $verification = "unmarked_proxy"
            }
            [pscustomobject]@{
                Component = [string]$_.component_key
                Proxy = [string]$_.proxy
                Source = [string]$_.source
                Verification = $verification
            }
        }
        $proxyAuditCount = @($proxyAudit).Count
        $fallbackProxyCount = @($proxyAudit | Where-Object { $_.Verification -eq "fallback_proxy" }).Count
        $unmarkedProxyCount = @($proxyAudit | Where-Object { $_.Verification -eq "unmarked_proxy" }).Count
        $proxyAuditSummary = @($proxyAudit | ForEach-Object {
            $_.Component + ":" + $_.Proxy + "@" + $_.Source + "/" + $_.Verification
        }) -join ","
        Write-Host ("Decision data:          source=" + $decisionDataSource + " status=" + $decisionData.status + " readiness=" + $decisionData.readiness_status + " mt=" + $marketThermometer.status + " mt_date=" + $marketThermometer.observed_at + " mt_source=" + $marketThermometer.data_source + " stale=" + $staleComponents + " missing=" + $missingComponents + " proxy=" + $proxyComponents + " must_not_use=" + $decisionData.must_not_use_for_decision)
        if ($proxyAuditCount -gt 0) {
            Write-Host ("MT proxy audit:         count=" + $proxyAuditCount + " fallback=" + $fallbackProxyCount + " unmarked=" + $unmarkedProxyCount + " components=" + $proxyAuditSummary)
        }
        $staleKeys = @($marketThermometer.stale_components)
        $missingKeys = @($marketThermometer.missing_components)
        if (($staleKeys -contains "new_investor_accounts") -or ($missingKeys -contains "new_investor_accounts")) {
            Write-Host "MT stale action:        python manage.py import_investor_accounts --print-template; then --file <csv_path> --dry-run --json --fail-on-warning; see quick-reference for 10k-account unit import" -ForegroundColor Yellow
        }
        if ($skippedLatestThermometer) {
            Write-Host ("MT skipped latest:      observed_at=" + $skippedLatestThermometer.observed_at + " status=" + $skippedLatestThermometer.status + " reason=" + $skippedLatestThermometer.skip_reason)
        }
    }
    if ($macroContext) {
        Write-Host ("Macro context:          source=" + $macroContextSource + " regime=" + $regimeContext.dominant_regime + " confidence=" + $regimeContext.confidence + " regime_date=" + $regimeContext.observed_at + " pulse=" + $pulseContext.composite_score + " pulse_date=" + $pulseContext.observed_at + " pulse_stale=" + $pulseContext.stale_indicator_count)
    }
    if ($riskProof) {
        Write-Host ("Risk proof:             status=" + $riskProof.status + " accounts=" + $riskProof.account_count + " risk_ok=" + $riskProof.risk_ok_account_count + " persisted=" + $riskProof.persisted_report_account_count + " pre_trade_ok=" + $riskProof.pre_trade_ok_account_count + " post_ok=" + $riskProof.post_investment_ok_account_count)
    }
    if ($weeklyProof) {
        Write-Host ("Weekly advisor proof:   status=" + $weeklyProof.status + " source=" + $weeklyProof.source + " expected=" + $weeklyProof.expected_record_count + " ok_records=" + $weeklyProof.ok_record_count + " missing=" + $weeklyProof.missing_record_count + " warnings=" + $weeklyProof.warning_record_count)
    }
    if ($postPersistence) {
        $postWeeklyDue = $postWeekly.scheduled_for
        if (-not $postWeeklyDue) {
            $postWeeklyDue = $postWeekly.next_scheduled_for
        }
        if (-not $postWeeklyDue) {
            $postWeeklyDue = "not_pending"
        }
        Write-Host ("Post-evidence DB:       status=" + $postPersistence.status + " risk=" + $postRisk.status + " risk_reports=" + @($postRisk.records).Count + " weekly=" + $postWeekly.status + " weekly_reports=" + @($postWeekly.records).Count + " weekly_due=" + $postWeeklyDue + " impact=" + $postPersistence.acceptance_gate_impact)
    }
    Write-Host ("Next required date:     " + $acceptance.next_required_date)
    Write-Host ("Next action:            " + $nextAction.action + " reason=" + $nextAction.reason)
    Write-Host ("Next check after:       " + $gate.next_check_after)
    if ($ReferenceTime) {
        Write-Host ("Summary reference time: " + $operatorCheckNow.ToString("o"))
    }
    $operatorCheckDisplay = $operatorCheckAfter
    if (-not $operatorCheckDisplay -and $operatorCheckReason -eq "review_current_status") {
        $operatorCheckDisplay = "now"
    }
    Write-Host ("Next operator check:    " + $operatorCheckDisplay + " reason=" + $operatorCheckReason)
    if ($null -ne $operatorCheckEtaMinutes) {
        Write-Host ("Operator check in:      " + $operatorCheckEtaMinutes + " min (" + (Format-DurationMinutes -Minutes $operatorCheckEtaMinutes) + ")")
    }
    Write-Host ("Scheduled for:          " + $schedule.scheduled_for + " due_status=" + $schedule.due_status)
    Write-Host ("Runtime:                " + $runtime.status + " beat=" + $runtime.beat_process_count + " workers=" + $runtime.worker_process_count + " queues=" + (($runtime.covered_queues | Sort-Object) -join ","))
    Write-Host ("Task registry:          " + $runtime.registered_tasks_status + " missing=" + (($runtime.missing_registered_tasks | Sort-Object) -join ","))
    Write-Host ("Projected evidence completion:  " + $acceptance.projected_completion_date)
    Write-Host ("Projected scheduler completion: " + $acceptance.projected_scheduler_completion_date)

    if ($gate.command) {
        Write-Host ("Action command:         " + $gate.command) -ForegroundColor Yellow
    } elseif ($operatorCheckAfter) {
        Write-Host ("Operator action:        wait until " + $operatorCheckAfter) -ForegroundColor Green
    } elseif ($operatorCheckReason -eq "review_current_status") {
        Write-Host "Operator action:        rerun monitor now and inspect current status" -ForegroundColor Yellow
    }
    Write-Host ""
}

$pythonExe = Resolve-PythonExe
$env:DJANGO_SETTINGS_MODULE = $SettingsModule

$commandArgs = @(
    "manage.py",
    "show_personal_readiness_status",
    "--json",
    "--require-local-scheduler-runtime",
    "--local-runtime-ping-timeout",
    ([string]$LocalRuntimePingTimeout)
)

if ($StrictAcceptance) {
    $commandArgs += "--strict-acceptance"
} else {
    $commandArgs += "--strict-monitor"
}

Write-Host "[INFO] Running personal readiness monitor..." -ForegroundColor Cyan
Write-Host ("[INFO] Command: " + $pythonExe + " " + ($commandArgs -join " ")) -ForegroundColor DarkCyan

$output = & $pythonExe @commandArgs 2>&1
$exitCode = $LASTEXITCODE
$payload = Convert-MonitorPayload -OutputLines $output

Write-MonitorSummary -Payload $payload -ReferenceTime $ReferenceTime

if ($LogToFile) {
    $logDir = Join-Path $root "var\readiness-monitor"
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $logPath = Join-Path $logDir ("personal-readiness-monitor-" + $stamp + ".log")
    $output | Tee-Object -FilePath $logPath | Out-Host
    Write-Host "[INFO] Monitor output saved to $logPath" -ForegroundColor Cyan
} elseif (-not $SummaryOnly) {
    $output | Out-Host
} else {
    Write-Host "[INFO] Full monitor JSON omitted because -SummaryOnly was set." -ForegroundColor Cyan
}

if ($exitCode -eq 0) {
    Write-Host "[OK] Personal readiness monitor passed." -ForegroundColor Green
} else {
    Write-Host "[ERROR] Personal readiness monitor failed with exit code $exitCode." -ForegroundColor Red
}

exit $exitCode
