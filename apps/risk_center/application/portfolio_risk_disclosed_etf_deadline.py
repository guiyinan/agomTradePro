"""Rebind a disclosed ETF clock proof to the current simulation policy."""

from __future__ import annotations

from datetime import datetime, tzinfo

from apps.risk_center.application.portfolio_risk_policy import PortfolioRiskPolicyBundle
from apps.risk_center.domain.portfolio_risk_disclosed_etf_report_clock import (
    PortfolioRiskDisclosedETFReportProof,
)
from apps.risk_center.domain.portfolio_risk_sources import (
    PortfolioRiskSourceEvidence,
    SourceObservationPrecision,
    qualify_portfolio_risk_source,
)


def disclosed_etf_report_proof_matches_policy(
    *,
    proof: PortfolioRiskDisclosedETFReportProof,
    evidence: PortfolioRiskSourceEvidence,
    policy: PortfolioRiskPolicyBundle,
    account_id: int,
    business_timezone: tzinfo,
    requested_purpose: str | None,
) -> bool:
    """Preserve both original receipt identities and independently bounded ages."""

    if (
        type(proof) is not PortfolioRiskDisclosedETFReportProof
        or type(evidence) is not PortfolioRiskSourceEvidence
        or type(policy) is not PortfolioRiskPolicyBundle
        or type(account_id) is not int
        or account_id not in policy.account_ids
        or not isinstance(business_timezone, tzinfo)
    ):
        return False
    disclosure = policy.etf_report_policy
    timezone_name = getattr(business_timezone, "key", None)
    if disclosure is None or type(timezone_name) is not str:
        return False
    references = tuple(
        item
        for item in policy.source_references
        if item.kind == "etf_report"
        and item.asset_code == proof.asset_code
        and item.security_id == proof.security_id
        and item.source_record_id == proof.source_record_id
        and item.raw_payload_hash == proof.source_reference_hash
        and item.clock_evidence_mode == "policy_bounded_disclosed_report"
    )
    if len(references) != 1:
        return False
    if (
        policy.scope != "simulation_only"
        or proof.scope != "simulation_only"
        or proof.account_id != account_id
        or proof.as_of != policy.as_of
        or evidence.decision_cutoff != policy.as_of
        or proof.business_date != policy.business_date
        or evidence.decision_date_cutoff != policy.business_date
        or proof.business_timezone_name != timezone_name
        or proof.profile_key != policy.profile_key
        or proof.profile_version != policy.profile_version
        or proof.profile_content_hash != policy.profile_content_hash
        or proof.policy_snapshot_id != policy.snapshot_id
        or proof.policy_snapshot_hash != policy.snapshot_hash
        or proof.policy_content_sha256 != policy.normalized_config_sha256
        or proof.policy_known_at != policy.known_at
        or proof.policy_effective_at != policy.effective_at
        or proof.age_basis != disclosure.age_basis
        or proof.max_report_age_days != disclosure.max_report_age_days
        or proof.source_max_date_age_days != policy.source_max_date_age_days
        or requested_purpose != policy.industry_policy.requested_purpose
        or proof.source_id != evidence.source_id
        or proof.source_record_id != evidence.source_record_id
        or proof.original_body_sha256 != evidence.original_payload_sha256
        or proof.report_period_end != evidence.effective_on
        or proof.publication_on != evidence.observed_on
        or proof.known_at != evidence.known_at
        or evidence.available_at is not None
        or evidence.valid_until is not None
        or evidence.observation_precision is not SourceObservationPrecision.DATE
        or evidence.observed_at is not None
        or proof.coverage_status != evidence.coverage.status.value
        or proof.coverage_precision_basis != evidence.coverage.precision_basis
    ):
        return False
    try:
        proof.__post_init__()
        base_deadlines: tuple[datetime | None, ...] = (
            policy.industry_policy.effective_until,
            policy.capacity_policy.effective_until,
        )
        if any(
            deadline is not None and deadline not in proof.policy_deadlines
            for deadline in base_deadlines
        ):
            return False
        qualification = qualify_portfolio_risk_source(
            evidence=evidence,
            requested_purpose=policy.industry_policy.requested_purpose,
            allowed_observation_precisions=policy.industry_policy.allowed_observation_precisions,
            as_of=policy.as_of,
            allowed_restrictions=policy.industry_policy.allowed_source_restrictions,
            expected_source_kind="etf_report",
        )
    except (ArithmeticError, TypeError, ValueError):
        return False
    return qualification.eligible and proof.policy_acceptance_deadline > policy.as_of


__all__ = ("disclosed_etf_report_proof_matches_policy",)
