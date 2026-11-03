"""Stable JSON rendering for the read-only simulated portfolio risk result."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Literal
from zoneinfo import ZoneInfo

from apps.risk_center.application.portfolio_risk_assets import PortfolioRiskAssetsReadResult
from apps.risk_center.application.portfolio_risk_contracts import (
    PortfolioRiskCheckPayload,
    PortfolioRiskOutcome,
    PortfolioRiskReportPayload,
    PortfolioRiskSourcePayload,
)
from apps.risk_center.application.portfolio_risk_disclosed_etf_deadline import (
    disclosed_etf_report_proof_matches_policy,
)
from apps.risk_center.application.portfolio_risk_policy import (
    PortfolioRiskPolicyBundle,
    PortfolioRiskSourceReference,
)
from apps.risk_center.application.portfolio_risk_report_clock_payload import (
    clock_evidence_proof_payload,
)
from apps.risk_center.domain.portfolio_capacity import PortfolioCapacityDecision
from apps.risk_center.domain.portfolio_exposure_types import (
    ExposureOutcome,
    PortfolioIndustryExposureAssessment,
)
from apps.risk_center.domain.portfolio_risk_clock_evidence import (
    PortfolioRiskCloseSnapshotStateProof,
    PortfolioRiskDateSnapshotProof,
    PortfolioRiskTimestampSnapshotProof,
)
from apps.risk_center.domain.portfolio_risk_disclosed_etf_report_clock import (
    PortfolioRiskDisclosedETFReportProof,
)
from apps.risk_center.domain.portfolio_risk_snapshot import (
    AccountSnapshot,
    ProposedOrder,
    exact_decimal_sum,
)
from apps.risk_center.domain.portfolio_risk_sources import (
    CoverageStatus,
    PortfolioRiskSourceEvidence,
    SourceObservationPrecision,
    qualify_portfolio_risk_source,
)


@dataclass(frozen=True, slots=True)
class PortfolioRiskReportBuildResult:
    """Rendered simulation-only payload plus its stable aggregated reasons."""

    payload: PortfolioRiskReportPayload
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ReportSourceUseRule:
    """Bind one retained evidence record to the exact report purpose and age policy."""

    evidence: PortfolioRiskSourceEvidence
    purpose: str
    allowed_precisions: tuple[SourceObservationPrecision, ...]
    date_precision_purposes: tuple[str, ...]
    allowed_restrictions: tuple[str, ...]
    coverage_precision_basis: str | None
    source_role: str
    asset_code: str
    security_id: str | None
    expected_observation_date: date | None = None


def build_portfolio_risk_report(
    *,
    snapshot: AccountSnapshot,
    proposals: tuple[ProposedOrder, ...],
    policy: PortfolioRiskPolicyBundle | None,
    asset_inputs: PortfolioRiskAssetsReadResult,
    all_source_evidence: tuple[PortfolioRiskSourceEvidence, ...],
    as_of: datetime,
    business_date: date,
    capacity_requested_purpose: str,
    scope_reasons: tuple[str, ...],
    calculation_reasons: tuple[str, ...],
    pre_trade_nav: Decimal | None,
    actual_holdings_value: Decimal | None,
    industry: PortfolioIndustryExposureAssessment | None,
    capacity_decisions: tuple[PortfolioCapacityDecision, ...],
    capacity_reasons: tuple[str, ...],
    identity_basis: dict[str, str],
) -> PortfolioRiskReportBuildResult:
    """Render all checks and source evidence without granting execution authority."""

    checks = _checks(
        snapshot=snapshot,
        proposals=proposals,
        policy=policy,
        asset_inputs=asset_inputs,
        all_source_evidence=all_source_evidence,
        scope_reasons=scope_reasons,
        calculation_reasons=calculation_reasons,
        pre_trade_nav=pre_trade_nav,
        actual_holdings_value=actual_holdings_value,
        industry=industry,
        capacity_decisions=capacity_decisions,
        capacity_reasons=capacity_reasons,
        identity_basis=identity_basis,
        capacity_requested_purpose=capacity_requested_purpose,
    )
    freshness, reliability, quality_reasons = _report_source_quality(
        policy=policy,
        asset_inputs=asset_inputs,
        all_source_evidence=all_source_evidence,
        as_of=as_of,
        business_date=business_date,
        execution_session=snapshot.execution_session,
        capacity_requested_purpose=capacity_requested_purpose,
        account_id=snapshot.account_id,
    )
    if quality_reasons:
        checks = _replace_source_quality_check(checks, quality_reasons)
    must_not_use_for_decision = (
        freshness != "qualified_snapshot"
        or reliability != "source_bound"
        or bool(scope_reasons)
        or not _checks_support_only_known_vetoes(checks)
    )
    outcome = _combine_statuses(tuple(check["status"] for check in checks))
    reasons = tuple(dict.fromkeys(reason for check in checks for reason in check["reason_codes"]))
    content = repr(
        (
            snapshot,
            proposals,
            policy,
            asset_inputs.policy_snapshot_id,
            asset_inputs.policy_snapshot_hash,
            asset_inputs.source_reference_bindings,
            asset_inputs,
            all_source_evidence,
            as_of,
            business_date,
            capacity_requested_purpose,
        )
    )
    resource_hash = f"sha256:{sha256(content.encode('utf-8')).hexdigest()}"
    payload: PortfolioRiskReportPayload = {
        "account_id": snapshot.account_id,
        "as_of": as_of.isoformat(),
        "outcome": outcome,
        "policy_version": (
            f"{policy.profile_key}@{policy.profile_version}" if policy is not None else None
        ),
        "resource_snapshot_hash": resource_hash,
        "checks": list(checks),
        "sources": [_source_payload(item) for item in all_source_evidence],
        "freshness": freshness,
        "reliability": reliability,
        "must_not_use_for_decision": must_not_use_for_decision,
        "scope": "simulation_only",
        "must_not_execute": True,
    }
    return PortfolioRiskReportBuildResult(payload=payload, reason_codes=reasons)


def _report_source_quality(
    *,
    policy: PortfolioRiskPolicyBundle | None,
    asset_inputs: PortfolioRiskAssetsReadResult,
    all_source_evidence: tuple[PortfolioRiskSourceEvidence, ...],
    as_of: datetime,
    business_date: date,
    execution_session: date,
    capacity_requested_purpose: str,
    account_id: int,
) -> tuple[
    Literal["qualified_snapshot", "expired", "unknown"],
    Literal["source_bound", "partial", "unknown"],
    tuple[str, ...],
]:
    """Classify source freshness and binding without promoting disclosure to realtime."""

    reasons: list[str] = []
    expired = any(
        evidence.valid_until is not None and as_of >= evidence.valid_until
        for evidence in all_source_evidence
    )
    partial_coverage = (
        any(evidence.coverage.status is CoverageStatus.PARTIAL for evidence in all_source_evidence)
        or asset_inputs.status == "partial"
    )
    if policy is None:
        reasons.append("PORTFOLIO_REPORT_POLICY_IDENTITY_UNKNOWN")
    else:
        if (
            asset_inputs.policy_snapshot_id != policy.snapshot_id
            or asset_inputs.policy_snapshot_hash != policy.snapshot_hash
            or policy.as_of != as_of
            or policy.business_date != business_date
        ):
            reasons.append("PORTFOLIO_REPORT_POLICY_READER_IDENTITY_MISMATCH")
    if asset_inputs.status != "complete" or asset_inputs.reason_codes:
        reasons.extend(asset_inputs.reason_codes or ("PORTFOLIO_REPORT_READER_INCOMPLETE",))
    if not all_source_evidence:
        reasons.append("PORTFOLIO_REPORT_SOURCE_EVIDENCE_EMPTY")
    for asset in asset_inputs.assets:
        observation = asset.capacity_observation
        if observation is None:
            continue
        if (
            observation.window_kind == "rolling_sessions"
            and observation.window_end >= execution_session
        ):
            reasons.append("PORTFOLIO_REPORT_CAPACITY_LOOKBACK_NOT_BEFORE_EXECUTION_SESSION")
        elif (
            observation.window_kind == "session_cumulative"
            and observation.window_start != execution_session
        ):
            reasons.append("PORTFOLIO_REPORT_CAPACITY_SESSION_DATE_MISMATCH")
        state_evidence = observation.execution_session_state_evidence
        state_proof = state_evidence.policy_clock_proof if state_evidence is not None else None
        close_snapshot_state = (
            type(state_proof) is PortfolioRiskCloseSnapshotStateProof
            and capacity_requested_purpose == "close_snapshot_simulation"
            and observation.execution_session_suspended is None
            and state_proof.full_session_state == "unknown"
        )
        if (
            state_evidence is None
            or observation.execution_session_state_date is None
            or (observation.execution_session_suspended is None and not close_snapshot_state)
            or (close_snapshot_state and observation.execution_session_suspended is not None)
        ):
            reasons.append("PORTFOLIO_REPORT_EXECUTION_SESSION_STATE_UNKNOWN")
    if policy is not None and all_source_evidence:
        rules = _source_use_rules(
            policy=policy,
            asset_inputs=asset_inputs,
            capacity_requested_purpose=capacity_requested_purpose,
        )
        evidence_set = set(all_source_evidence)
        for evidence in all_source_evidence:
            matching_rules = tuple(rule for rule in rules if rule.evidence == evidence)
            if not matching_rules:
                reasons.append("PORTFOLIO_REPORT_SOURCE_USE_UNBOUND")
                continue
            for rule in matching_rules:
                reasons.extend(
                    _source_use_qualification_reasons(
                        rule=rule,
                        policy=policy,
                        as_of=as_of,
                        business_date=business_date,
                        execution_session=execution_session,
                        account_id=account_id,
                        source_reference_bindings=asset_inputs.source_reference_bindings,
                    )
                )
        if any(rule.evidence not in evidence_set for rule in rules):
            reasons.append("PORTFOLIO_REPORT_SOURCE_EVIDENCE_OMITTED")

    unique_reasons = tuple(dict.fromkeys(reasons))
    if expired:
        freshness: Literal["qualified_snapshot", "expired", "unknown"] = "expired"
    elif not unique_reasons:
        freshness = "qualified_snapshot"
    else:
        freshness = "unknown"
    if not unique_reasons and not expired:
        reliability: Literal["source_bound", "partial", "unknown"] = "source_bound"
    elif partial_coverage:
        reliability = "partial"
    else:
        reliability = "unknown"
    return freshness, reliability, unique_reasons


def _source_use_rules(
    *,
    policy: PortfolioRiskPolicyBundle,
    asset_inputs: PortfolioRiskAssetsReadResult,
    capacity_requested_purpose: str,
) -> tuple[_ReportSourceUseRule, ...]:
    """Associate every loaded source with the exact configured reader purpose."""

    rules: list[_ReportSourceUseRule] = []
    industry_policy = policy.industry_policy
    capacity_policy = policy.capacity_policy

    def add_industry_source(
        evidence: PortfolioRiskSourceEvidence | None,
        *,
        role: str,
        asset_code: str,
        security_id: str | None,
        coverage_basis: str | None = None,
    ) -> None:
        """Attach one exact source record to its report asset pair and role."""
        if evidence is None:
            return
        rules.append(
            _ReportSourceUseRule(
                evidence=evidence,
                purpose=industry_policy.requested_purpose,
                allowed_precisions=industry_policy.allowed_observation_precisions,
                date_precision_purposes=industry_policy.date_precision_purposes,
                allowed_restrictions=industry_policy.allowed_source_restrictions,
                coverage_precision_basis=coverage_basis,
                source_role=role,
                asset_code=asset_code,
                security_id=security_id,
            )
        )

    for asset in asset_inputs.assets:
        add_industry_source(
            asset.valuation_evidence,
            role="valuation",
            asset_code=asset.asset_code,
            security_id=asset.security_id,
        )
        if asset.industry_membership is not None:
            add_industry_source(
                asset.industry_membership.source_evidence,
                role="industry_membership",
                asset_code=asset.asset_code,
                security_id=asset.security_id,
                coverage_basis=industry_policy.coverage_precision_basis,
            )
        if asset.etf_report is not None:
            add_industry_source(
                asset.etf_report.source_evidence,
                role="etf_report",
                asset_code=asset.asset_code,
                security_id=asset.security_id,
                coverage_basis=industry_policy.coverage_precision_basis,
            )
            for constituent in asset.etf_report.constituents:
                membership = constituent.industry_membership
                if membership is not None:
                    add_industry_source(
                        membership.source_evidence,
                        role="industry_membership",
                        asset_code=constituent.asset_code,
                        security_id=None,
                        coverage_basis=industry_policy.coverage_precision_basis,
                    )
        observation = asset.capacity_observation
        if observation is None:
            continue
        rules.append(
            _ReportSourceUseRule(
                evidence=observation.source_evidence,
                purpose=capacity_requested_purpose,
                allowed_precisions=capacity_policy.allowed_observation_precisions,
                date_precision_purposes=capacity_policy.date_precision_purposes,
                allowed_restrictions=capacity_policy.allowed_source_restrictions,
                coverage_precision_basis=None,
                source_role="capacity_window",
                asset_code=observation.asset_code,
                security_id=observation.security_id,
                expected_observation_date=observation.window_end,
            )
        )
        state_evidence = observation.execution_session_state_evidence
        if state_evidence is not None:
            rules.append(
                _ReportSourceUseRule(
                    evidence=state_evidence,
                    purpose=capacity_requested_purpose,
                    allowed_precisions=capacity_policy.allowed_observation_precisions,
                    date_precision_purposes=capacity_policy.date_precision_purposes,
                    allowed_restrictions=capacity_policy.allowed_source_restrictions,
                    coverage_precision_basis=None,
                    source_role="execution_session_state",
                    asset_code=observation.asset_code,
                    security_id=observation.security_id,
                    expected_observation_date=observation.execution_session_state_date,
                )
            )
    return tuple(rules)


def _source_use_qualification_reasons(
    *,
    rule: _ReportSourceUseRule,
    policy: PortfolioRiskPolicyBundle,
    as_of: datetime,
    business_date: date,
    execution_session: date,
    account_id: int,
    source_reference_bindings: tuple[PortfolioRiskSourceReference, ...],
) -> tuple[str, ...]:
    """Recheck source clocks, use prohibition, age limits, and coverage policy."""

    evidence = rule.evidence
    qualification = qualify_portfolio_risk_source(
        evidence=evidence,
        requested_purpose=rule.purpose,
        allowed_observation_precisions=rule.allowed_precisions,
        as_of=as_of,
        allowed_restrictions=rule.allowed_restrictions,
        expected_source_kind=(
            rule.source_role
            if rule.source_role
            in (
                "industry_membership",
                "valuation",
                "etf_report",
                "capacity_window",
                "execution_session_state",
            )
            else None
        ),
    )
    reasons = list(qualification.reason_codes)
    policy_references = tuple(
        reference
        for reference in policy.source_references
        if reference.kind == rule.source_role
        and reference.asset_code == rule.asset_code
        and (rule.security_id is None or reference.security_id == rule.security_id)
        and reference.source_record_id == evidence.source_record_id
    )
    read_references = tuple(
        reference
        for reference in source_reference_bindings
        if reference.kind == rule.source_role
        and reference.asset_code == rule.asset_code
        and (rule.security_id is None or reference.security_id == rule.security_id)
        and reference.source_record_id == evidence.source_record_id
    )
    if len(policy_references) != 1 or policy_references != read_references:
        reasons.append("PORTFOLIO_REPORT_SOURCE_REFERENCE_BINDING_MISMATCH")
    else:
        reference = policy_references[0]
        proof = evidence.policy_clock_proof
        if proof is not None and not _clock_proof_matches_current_report(
            proof=proof,
            reference=reference,
            policy=policy,
            evidence=evidence,
            account_id=account_id,
            as_of=as_of,
            business_date=business_date,
            execution_session=execution_session,
        ):
            reasons.append("PORTFOLIO_REPORT_SOURCE_PROOF_POLICY_BINDING_MISMATCH")
    if evidence.coverage.status is CoverageStatus.PARTIAL:
        reasons.append("PORTFOLIO_REPORT_SOURCE_COVERAGE_PARTIAL")
    elif evidence.coverage.status is CoverageStatus.UNKNOWN:
        reasons.append("PORTFOLIO_REPORT_SOURCE_COVERAGE_UNKNOWN")
    if (
        rule.coverage_precision_basis is not None
        and evidence.coverage.precision_basis != rule.coverage_precision_basis
    ):
        reasons.append("PORTFOLIO_REPORT_SOURCE_COVERAGE_BASIS_MISMATCH")
    if evidence.observation_precision is SourceObservationPrecision.TIMESTAMP:
        observed_at = evidence.observed_at
        if observed_at is None or as_of - observed_at > timedelta(
            seconds=policy.source_max_timestamp_age_seconds
        ):
            reasons.append("PORTFOLIO_REPORT_SOURCE_TIMESTAMP_AGE_EXCEEDED")
    elif evidence.observation_precision is SourceObservationPrecision.DATE:
        observed_on = evidence.observed_on
        if rule.purpose not in rule.date_precision_purposes:
            reasons.append("PORTFOLIO_REPORT_SOURCE_DATE_PURPOSE_NOT_ALLOWED")
        if evidence.decision_date_cutoff != business_date:
            reasons.append("PORTFOLIO_REPORT_SOURCE_DATE_CUTOFF_MISMATCH")
        if observed_on is None or observed_on > business_date:
            reasons.append("PORTFOLIO_REPORT_SOURCE_OBSERVATION_DATE_INVALID")
        elif (business_date - observed_on).days > policy.source_max_date_age_days:
            reasons.append("PORTFOLIO_REPORT_SOURCE_DATE_AGE_EXCEEDED")
        if (
            rule.expected_observation_date is not None
            and observed_on != rule.expected_observation_date
        ):
            reasons.append("PORTFOLIO_REPORT_SOURCE_OBSERVATION_DATE_SCOPE_MISMATCH")
    if rule.source_role == "execution_session_state":
        state_date = rule.expected_observation_date
        if state_date is None or state_date != execution_session or state_date > business_date:
            reasons.append("PORTFOLIO_REPORT_EXECUTION_SESSION_STATE_DATE_UNKNOWN")
        if evidence.effective_on != state_date:
            reasons.append("PORTFOLIO_REPORT_EXECUTION_SESSION_STATE_EFFECTIVE_DATE_MISMATCH")
    return tuple(dict.fromkeys(reasons))


def _clock_proof_matches_current_report(
    *,
    proof: (
        PortfolioRiskDateSnapshotProof
        | PortfolioRiskTimestampSnapshotProof
        | PortfolioRiskCloseSnapshotStateProof
        | PortfolioRiskDisclosedETFReportProof
    ),
    reference: PortfolioRiskSourceReference,
    policy: PortfolioRiskPolicyBundle,
    evidence: PortfolioRiskSourceEvidence,
    account_id: int,
    as_of: datetime,
    business_date: date,
    execution_session: date,
) -> bool:
    """Rebind each special proof to the exact current profile, source and owner."""

    mismatch = (
        proof.scope != "simulation_only"
        or proof.source_kind != reference.kind
        or proof.clock_evidence_mode != reference.clock_evidence_mode
        or proof.profile_key != policy.profile_key
        or proof.profile_version != policy.profile_version
        or proof.profile_content_hash != policy.profile_content_hash
        or proof.policy_snapshot_id != policy.snapshot_id
        or proof.policy_snapshot_hash != policy.snapshot_hash
        or proof.policy_content_sha256 != policy.normalized_config_sha256
        or proof.policy_known_at != policy.known_at
        or proof.policy_effective_at != policy.effective_at
        or proof.source_reference_hash != reference.raw_payload_hash
        or proof.account_id != account_id
        or proof.asset_code != reference.asset_code
        or proof.security_id != reference.security_id
        or proof.source_id != evidence.source_id
        or proof.source_record_id != reference.source_record_id
        or proof.original_body_sha256 != evidence.original_payload_sha256
        or proof.as_of != as_of
        or evidence.decision_cutoff != as_of
    )
    if mismatch:
        return False
    if type(proof) is PortfolioRiskDisclosedETFReportProof:
        return disclosed_etf_report_proof_matches_policy(
            proof=proof,
            evidence=evidence,
            policy=policy,
            account_id=account_id,
            business_timezone=ZoneInfo(proof.business_timezone_name),
            requested_purpose=policy.industry_policy.requested_purpose,
        )
    if type(proof) is PortfolioRiskCloseSnapshotStateProof:
        return (
            proof.business_date == business_date
            and proof.execution_session == execution_session
            and proof.purpose == "close_snapshot_simulation"
            and evidence.source_purpose == proof.purpose
            and proof.observed_at == evidence.observed_at
            and proof.known_at == evidence.known_at
            and evidence.available_at is None
            and evidence.valid_until is None
            and proof.policy_acceptance_deadline > as_of
        )
    if type(proof) is PortfolioRiskTimestampSnapshotProof:
        return (
            proof.business_date == business_date
            and proof.execution_session == execution_session
            and proof.policy_known_at == policy.known_at
            and proof.policy_effective_at == policy.effective_at
            and proof.policy_acceptance_deadline > as_of
        )
    return (
        type(proof) is PortfolioRiskDateSnapshotProof
        and proof.business_date == business_date
        and proof.policy_known_at == policy.known_at
        and proof.policy_effective_at == policy.effective_at
        and proof.policy_acceptance_deadline > as_of
    )


def _replace_source_quality_check(
    checks: tuple[PortfolioRiskCheckPayload, ...],
    reasons: tuple[str, ...],
) -> tuple[PortfolioRiskCheckPayload, ...]:
    """Publish report-level source qualification blockers in the source check."""

    source_status: PortfolioRiskOutcome = (
        "partial" if any("PARTIAL" in reason for reason in reasons) else "unknown"
    )
    replaced: list[PortfolioRiskCheckPayload] = []
    for check in checks:
        if check["dimension"] != "source_inputs":
            replaced.append(check)
            continue
        details = dict(check["details"])
        details["report_source_quality_reasons"] = list(reasons)
        replaced.append(
            {
                **check,
                "status": source_status,
                "reason_codes": list(dict.fromkeys((*check["reason_codes"], *reasons))),
                "summary": "来源时钟、覆盖或资格未能满足显式策略。",
                "details": details,
            }
        )
    return tuple(replaced)


def _checks_support_only_known_vetoes(
    checks: tuple[PortfolioRiskCheckPayload, ...],
) -> bool:
    """Allow a fully source-bound report to veto known risk without authorizing use."""

    known_capacity_vetoes = frozenset(
        {
            "CAPACITY_TRADING_SUSPENDED",
            "CAPACITY_ZERO_VOLUME",
            "CAPACITY_ZERO_AMOUNT",
            "CAPACITY_PARTICIPATION_BUDGET_ZERO",
            "CAPACITY_PROPOSAL_EXCEEDS_REMAINDER",
            "CAPACITY_REMAINDER_EXHAUSTED",
        }
    )
    for check in checks:
        if check["status"] in ("partial", "unknown"):
            return False
        if check["status"] != "blocked":
            continue
        if check["dimension"] == "industry_and_security_exposure":
            if check["details"].get("assessment_outcome") not in (
                "limit_breached",
                "blocked",
            ):
                return False
            continue
        if check["dimension"] == "liquidity_capacity":
            details = check["details"]
            decisions = details.get("decisions")
            if details.get("reasons") or type(decisions) is not list or not decisions:
                return False
            for decision in decisions:
                if type(decision) is not dict or decision.get("status") != "blocked":
                    return False
                reason_codes = decision.get("reason_codes")
                if (
                    type(reason_codes) is not list
                    or not reason_codes
                    or not set(reason_codes).issubset(known_capacity_vetoes)
                ):
                    return False
            continue
        return False
    return True


def _checks(
    *,
    snapshot: AccountSnapshot,
    proposals: tuple[ProposedOrder, ...],
    policy: PortfolioRiskPolicyBundle | None,
    asset_inputs: PortfolioRiskAssetsReadResult,
    all_source_evidence: tuple[PortfolioRiskSourceEvidence, ...],
    scope_reasons: tuple[str, ...],
    calculation_reasons: tuple[str, ...],
    pre_trade_nav: Decimal | None,
    actual_holdings_value: Decimal | None,
    industry: PortfolioIndustryExposureAssessment | None,
    capacity_decisions: tuple[PortfolioCapacityDecision, ...],
    capacity_reasons: tuple[str, ...],
    identity_basis: dict[str, str],
    capacity_requested_purpose: str,
) -> tuple[PortfolioRiskCheckPayload, ...]:
    source_reasons = asset_inputs.reason_codes
    if not source_reasons and asset_inputs.status == "partial":
        source_reasons = ("RISK_INPUTS_PARTIAL",)
    elif not source_reasons and asset_inputs.status == "blocked":
        source_reasons = ("RISK_INPUTS_BLOCKED",)
    if asset_inputs.status == "complete":
        source_status: PortfolioRiskOutcome = "allowed"
    elif asset_inputs.status == "partial":
        source_status = "partial"
    else:
        source_status = "blocked"
    checks: list[PortfolioRiskCheckPayload] = [
        {
            "dimension": "input_scope",
            "status": "blocked" if scope_reasons else "allowed",
            "reason_codes": list(scope_reasons),
            "summary": (
                "账户、策略及来源范围已核对。"
                if not scope_reasons
                else "账户或来源范围存在阻断项。"
            ),
            "details": {
                "account_id": snapshot.account_id,
                "owner_user_id": snapshot.owner_user_id,
                "snapshot_id": snapshot.snapshot_id,
                "read_at": snapshot.read_at.isoformat(),
                "execution_session": snapshot.execution_session.isoformat(),
                "identity_basis": identity_basis,
                "reader_status": asset_inputs.status,
                "reader_reasons": list(asset_inputs.reason_codes),
                "reader_policy_snapshot_id": asset_inputs.policy_snapshot_id,
                "reader_policy_snapshot_hash": asset_inputs.policy_snapshot_hash,
                "source_reference_bindings": [
                    {
                        "kind": item.kind,
                        "asset_code": item.asset_code,
                        "security_id": item.security_id,
                        "manifest_sha256": item.raw_payload_hash,
                        "source_record_id": item.source_record_id,
                    }
                    for item in asset_inputs.source_reference_bindings
                ],
                "sell_exit_pressure": _sell_pressure(snapshot, proposals),
                "policy_snapshot_id": policy.snapshot_id if policy else None,
                "policy_snapshot_hash": policy.snapshot_hash if policy else None,
                "policy_profile_key": policy.profile_key if policy else None,
                "policy_profile_version": policy.profile_version if policy else None,
                "policy_profile_content_hash": policy.profile_content_hash if policy else None,
                "policy_config_sha256": policy.normalized_config_sha256 if policy else None,
                "policy_known_at": policy.known_at.isoformat() if policy else None,
                "policy_effective_at": policy.effective_at.isoformat() if policy else None,
            },
        },
        {
            "dimension": "source_inputs",
            "status": source_status,
            "reason_codes": list(source_reasons),
            "summary": (
                "资产来源完整。"
                if asset_inputs.status == "complete"
                else "资产来源存在缺失、过期或资格限制。"
            ),
            "details": {
                "reader_status": asset_inputs.status,
                "source_count": len(all_source_evidence),
                "reasons": list(source_reasons),
            },
        },
    ]
    nav_reasons = tuple(
        reason
        for reason in calculation_reasons
        if reason.startswith(
            (
                "PORTFOLIO_CASH_",
                "PORTFOLIO_ACTUAL_HOLDING_",
                "PORTFOLIO_MONEY_UNIT_",
                "PORTFOLIO_NAV_",
            )
        )
    )
    nav_status: PortfolioRiskOutcome = (
        "allowed" if pre_trade_nav is not None and not nav_reasons else "unknown"
    )
    checks.append(
        {
            "dimension": "pre_trade_gross_nav",
            "status": nav_status,
            "reason_codes": list(nav_reasons),
            "summary": (
                "已按实际现金和持仓计算交易前总资产。"
                if nav_status == "allowed"
                else "交易前总资产缺少现金、持仓估值或明确币种。"
            ),
            "details": {
                "basis": "actual_cash_plus_settled_holdings_at_qualified_current_price",
                "cash": _text(snapshot.cash),
                "actual_holdings_value": _text(actual_holdings_value),
                "pre_trade_gross_nav": _text(pre_trade_nav),
                "money_unit": snapshot.money_unit,
                "excluded": ["future_sell_proceeds", "active_buy_notional", "proposed_orders"],
            },
        }
    )
    if industry is None:
        industry_status: PortfolioRiskOutcome = "unknown"
        industry_reasons: tuple[str, ...] = ("PORTFOLIO_INDUSTRY_ASSESSMENT_UNAVAILABLE",)
        industry_details: dict[str, object] = {}
    else:
        industry_status = _industry_status(industry.outcome)
        industry_reasons = industry.reason_codes
        industry_details = _industry_details(industry, pre_trade_nav)
    if not snapshot.active_orders_complete:
        if industry_status == "allowed":
            industry_status = "unknown"
        industry_reasons = tuple(
            dict.fromkeys((*industry_reasons, "PORTFOLIO_ACTIVE_ORDER_SNAPSHOT_INCOMPLETE"))
        )
    checks.append(
        {
            "dimension": "industry_and_security_exposure",
            "status": industry_status,
            "reason_codes": list(industry_reasons),
            "summary": (
                "行业、单证券和ETF穿透风险在配置范围内。"
                if industry_status == "allowed"
                else "行业或证券暴露未能证明处于配置范围内。"
            ),
            "details": industry_details,
        }
    )
    if not capacity_decisions and not capacity_reasons:
        capacity_status: PortfolioRiskOutcome = "allowed"
        capacity_reason_codes: tuple[str, ...] = ()
        capacity_summary = "没有新提议订单，本次无需新增容量申请。"
    else:
        statuses = tuple(item.status for item in capacity_decisions)
        if capacity_reasons:
            statuses = (*statuses, "blocked")
        capacity_status = _combine_statuses(statuses)
        capacity_reason_codes = tuple(
            dict.fromkeys(
                (
                    *capacity_reasons,
                    *(reason for item in capacity_decisions for reason in item.reason_codes),
                )
            )
        )
        if proposals:
            capacity_summary = (
                "提议订单通过容量规则。"
                if capacity_status == "allowed"
                else "提议订单未能全部通过容量规则。"
            )
        else:
            capacity_summary = (
                "当前持仓及在途订单的容量占用与可用额度已评估。"
                if capacity_status == "allowed"
                else "当前持仓或在途订单容量状态未能证明可用额度。"
            )
    checks.append(
        {
            "dimension": "liquidity_capacity",
            "status": capacity_status,
            "reason_codes": list(capacity_reason_codes),
            "summary": capacity_summary,
            "details": {
                "decisions": [_capacity_details(item) for item in capacity_decisions],
                "reasons": list(capacity_reasons),
                "execution_session": snapshot.execution_session.isoformat(),
                "active_orders_are_gross": True,
                "requested_purpose": capacity_requested_purpose,
            },
        }
    )
    return tuple(checks)


def _industry_status(outcome: ExposureOutcome) -> PortfolioRiskOutcome:
    if outcome is ExposureOutcome.WITHIN_LIMIT:
        return "allowed"
    if outcome in (ExposureOutcome.LIMIT_BREACHED, ExposureOutcome.BLOCKED):
        return "blocked"
    return "unknown"


def _sell_pressure(
    snapshot: AccountSnapshot,
    proposals: tuple[ProposedOrder, ...],
) -> list[dict[str, object]]:
    codes = (
        {item.asset_code for item in snapshot.holdings}
        | {item.asset_code for item in snapshot.active_orders}
        | {item.asset_code for item in proposals}
    )
    pressure: list[dict[str, object]] = []
    for asset_code in sorted(codes):
        holdings = tuple(item for item in snapshot.holdings if item.asset_code == asset_code)
        active_sells = tuple(
            item
            for item in snapshot.active_orders
            if item.asset_code == asset_code and item.side == "sell"
        )
        proposed_sells = tuple(
            item for item in proposals if item.asset_code == asset_code and item.side == "sell"
        )
        available_values = tuple(item.available_quantity for item in holdings)
        active_values = tuple(item.remaining_quantity for item in active_sells)
        pressure.append(
            {
                "asset_code": asset_code,
                "held_quantity": str(exact_decimal_sum(tuple(item.quantity for item in holdings))),
                "available_quantity": (
                    str(
                        exact_decimal_sum(
                            tuple(value for value in available_values if value is not None)
                        )
                    )
                    if all(value is not None for value in available_values)
                    else None
                ),
                "active_sell_remaining_quantity": (
                    str(
                        exact_decimal_sum(
                            tuple(value for value in active_values if value is not None)
                        )
                    )
                    if snapshot.active_orders_complete
                    and all(value is not None for value in active_values)
                    else None
                ),
                "proposed_sell_quantity": str(
                    exact_decimal_sum(tuple(item.quantity for item in proposed_sells))
                ),
                "is_gate": False,
            }
        )
    return pressure


def _industry_details(
    result: PortfolioIndustryExposureAssessment,
    portfolio_market_value: Decimal | None,
) -> dict[str, object]:
    return {
        "assessment_outcome": result.outcome.value,
        "portfolio_market_value": _text(portfolio_market_value),
        "industry_bounds": [
            f"{item.industry_code}:{_text(item.lower_weight)}..{_text(item.upper_weight)}"
            f"/{item.outcome.value}"
            for item in result.industry_bounds
        ],
        "security_bounds": [
            f"{item.asset_code}:{_text(item.lower_weight)}..{_text(item.upper_weight)}"
            f"/{item.outcome.value}"
            for item in result.security_bounds
        ],
        "etf_bounds": [
            f"{item.asset_code}:report={item.report_date.isoformat() if item.report_date else None}"
            f":coverage={_text(item.reported_coverage_fraction)}"
            f":unknown={_text(item.unknown_market_value)}"
            f":unknown_security={_text(item.unknown_security_market_value)}"
            for item in result.etf_bounds
        ],
        "repeated_underlyings": [
            f"{item.asset_code}:direct={item.direct_market_value}:etf={item.etf_market_value}"
            f":etfs={','.join(item.etf_asset_codes)}"
            for item in result.repeated_underlyings
        ],
        "unknown_industry_market_value": _text(result.unknown_industry_market_value),
        "unknown_security_market_value": _text(result.unknown_security_market_value),
        "industry_coverage_fraction": _text(result.industry_coverage_fraction),
        "etf_lookthrough_coverage_fraction": _text(result.etf_lookthrough_coverage_fraction),
        "source_ids": list(result.source_ids),
        "reason_codes": list(result.reason_codes),
    }


def _capacity_details(decision: PortfolioCapacityDecision) -> dict[str, object]:
    return {
        "status": decision.status,
        "asset_code": decision.asset_code,
        "security_id": decision.security_id,
        "reason_codes": list(decision.reason_codes),
        "measure": decision.measure,
        "unit": decision.unit,
        "window_capacity": _text(decision.window_capacity),
        "used_capacity": _text(decision.used_capacity),
        "reserved_buy_capacity": _text(decision.reserved_buy_capacity),
        "reserved_sell_capacity": _text(decision.reserved_sell_capacity),
        "proposed_capacity": _text(decision.proposed_capacity),
        "remaining_capacity": _text(decision.remaining_capacity),
        "allowed_new_capacity": _text(decision.allowed_new_capacity),
        "source_record_id": decision.source_record_id,
        "source_payload_sha256": decision.source_payload_sha256,
        "execution_session_state_date": (
            decision.execution_session_state_date.isoformat()
            if decision.execution_session_state_date
            else None
        ),
        "execution_session_suspended": decision.execution_session_suspended,
    }


def _source_payload(evidence: PortfolioRiskSourceEvidence) -> PortfolioRiskSourcePayload:
    cutoff = evidence.decision_cutoff.isoformat()
    if evidence.observation_precision is SourceObservationPrecision.DATE:
        cutoff = (
            evidence.decision_date_cutoff.isoformat()
            if evidence.decision_date_cutoff
            else "unknown"
        )
    payload: PortfolioRiskSourcePayload = {
        "source_id": evidence.source_id,
        "source_record_id": evidence.source_record_id,
        "raw_payload_sha256": evidence.original_payload_sha256,
        "observed_at": evidence.observed_at.isoformat() if evidence.observed_at else None,
        "observed_on": evidence.observed_on.isoformat() if evidence.observed_on else None,
        "observation_precision": evidence.observation_precision.value,
        "available_at": evidence.available_at.isoformat() if evidence.available_at else None,
        "known_at": evidence.known_at.isoformat() if evidence.known_at else None,
        "cutoff": cutoff,
        "valid_until": evidence.valid_until.isoformat() if evidence.valid_until else None,
        "purpose": evidence.source_purpose,
        "restrictions": list(evidence.restrictions),
        "must_not_use_for_decision": evidence.must_not_use_for_decision,
        "coverage_fraction": _text(evidence.coverage.reported_weight_fraction),
        "coverage_basis": evidence.coverage.precision_basis,
    }
    if evidence.policy_clock_proof is not None:
        payload["clock_evidence_proof"] = clock_evidence_proof_payload(evidence.policy_clock_proof)
    return payload


def _combine_statuses(statuses: tuple[str, ...]) -> PortfolioRiskOutcome:
    if "blocked" in statuses:
        return "blocked"
    if "unknown" in statuses:
        return "unknown"
    if "partial" in statuses:
        return "partial"
    return "allowed"


def _text(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None
