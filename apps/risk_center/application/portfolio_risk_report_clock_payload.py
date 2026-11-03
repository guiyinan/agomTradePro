"""Serialize typed policy-bound clock proofs for portfolio risk reports."""

from __future__ import annotations

from apps.risk_center.application.portfolio_risk_contracts import (
    PortfolioRiskCloseSnapshotStateClockProofPayload,
    PortfolioRiskDateSnapshotClockProofPayload,
    PortfolioRiskTimestampSnapshotClockProofPayload,
)
from apps.risk_center.application.portfolio_risk_disclosed_etf_report_codec import (
    PortfolioRiskDisclosedETFReportClockProofPayload,
    disclosed_etf_report_clock_payload,
)
from apps.risk_center.domain.portfolio_risk_clock_evidence import (
    PortfolioRiskCloseSnapshotStateProof,
    PortfolioRiskDateSnapshotProof,
    PortfolioRiskTimestampSnapshotProof,
)
from apps.risk_center.domain.portfolio_risk_disclosed_etf_report_clock import (
    PortfolioRiskDisclosedETFReportProof,
)


def clock_evidence_proof_payload(
    proof: (
        PortfolioRiskDateSnapshotProof
        | PortfolioRiskTimestampSnapshotProof
        | PortfolioRiskCloseSnapshotStateProof
        | PortfolioRiskDisclosedETFReportProof
    ),
) -> (
    PortfolioRiskDateSnapshotClockProofPayload
    | PortfolioRiskTimestampSnapshotClockProofPayload
    | PortfolioRiskCloseSnapshotStateClockProofPayload
    | PortfolioRiskDisclosedETFReportClockProofPayload
):
    """Render a derived proof while preserving unknown source-origin clocks."""

    if type(proof) is PortfolioRiskDisclosedETFReportProof:
        return disclosed_etf_report_clock_payload(proof)
    if type(proof) is PortfolioRiskDateSnapshotProof:
        return _date_clock_evidence_proof_payload(proof)
    if type(proof) is PortfolioRiskTimestampSnapshotProof:
        return _timestamp_clock_evidence_proof_payload(proof)
    if type(proof) is PortfolioRiskCloseSnapshotStateProof:
        return _close_snapshot_state_clock_evidence_proof_payload(proof)
    raise TypeError("unsupported portfolio risk clock proof type")


def _date_clock_evidence_proof_payload(
    proof: PortfolioRiskDateSnapshotProof,
) -> PortfolioRiskDateSnapshotClockProofPayload:
    """Render an industry DATE proof without synthesizing a source time."""

    return {
        "scope": proof.scope,
        "source_kind": proof.source_kind,
        "clock_evidence_mode": proof.clock_evidence_mode,
        "profile_key": proof.profile_key,
        "profile_version": proof.profile_version,
        "profile_content_hash": proof.profile_content_hash,
        "policy_snapshot_id": proof.policy_snapshot_id,
        "policy_snapshot_hash": proof.policy_snapshot_hash,
        "policy_content_sha256": proof.policy_content_sha256,
        "policy_known_at": proof.policy_known_at.isoformat(),
        "policy_effective_at": proof.policy_effective_at.isoformat(),
        "source_reference_hash": proof.source_reference_hash,
        "account_id": proof.account_id,
        "asset_code": proof.asset_code,
        "security_id": proof.security_id,
        "source_id": proof.source_id,
        "source_record_id": proof.source_record_id,
        "capture_id": proof.capture_id,
        "original_body_sha256": proof.original_body_sha256,
        "as_of": proof.as_of.isoformat(),
        "business_date": proof.business_date.isoformat(),
        "known_at": proof.known_at.isoformat(),
        "proven_available_at": proof.proven_available_at.isoformat(),
        "http_status": proof.http_status,
        "body_size_bytes": proof.body_size_bytes,
        "body_complete": True,
        "observed_on": proof.observed_on.isoformat(),
        "effective_from": proof.effective_from.isoformat(),
        "effective_until": proof.effective_until.isoformat(),
        "business_timezone_name": proof.business_timezone_name,
        "coverage_status": proof.coverage_status,
        "coverage_precision_basis": proof.coverage_precision_basis,
        "source_max_date_age_days": proof.source_max_date_age_days,
        "date_age_deadline": proof.date_age_deadline.isoformat(),
        "membership_deadline": proof.membership_deadline.isoformat(),
        "policy_deadlines": [item.isoformat() for item in proof.policy_deadlines],
        "policy_acceptance_deadline": proof.policy_acceptance_deadline.isoformat(),
        "source_available_at": None,
        "source_valid_until": None,
    }


def _close_snapshot_state_clock_evidence_proof_payload(
    proof: PortfolioRiskCloseSnapshotStateProof,
) -> PortfolioRiskCloseSnapshotStateClockProofPayload:
    """Render close-only vendor status with full-session state left unknown."""

    return {
        "scope": proof.scope,
        "source_kind": proof.source_kind,
        "clock_evidence_mode": proof.clock_evidence_mode,
        "state_basis": proof.state_basis,
        "reported_trading_state": proof.reported_trading_state,
        "full_session_state": proof.full_session_state,
        "purpose": proof.purpose,
        "required_restrictions": list(proof.required_restrictions),
        "profile_key": proof.profile_key,
        "profile_version": proof.profile_version,
        "profile_content_hash": proof.profile_content_hash,
        "policy_snapshot_id": proof.policy_snapshot_id,
        "policy_snapshot_hash": proof.policy_snapshot_hash,
        "policy_content_sha256": proof.policy_content_sha256,
        "policy_known_at": proof.policy_known_at.isoformat(),
        "policy_effective_at": proof.policy_effective_at.isoformat(),
        "source_reference_hash": proof.source_reference_hash,
        "account_id": proof.account_id,
        "asset_code": proof.asset_code,
        "security_id": proof.security_id,
        "source_id": proof.source_id,
        "source_record_id": proof.source_record_id,
        "capture_id": proof.capture_id,
        "original_body_sha256": proof.original_body_sha256,
        "as_of": proof.as_of.isoformat(),
        "business_date": proof.business_date.isoformat(),
        "execution_session": proof.execution_session.isoformat(),
        "known_at": proof.known_at.isoformat(),
        "proven_available_at": proof.proven_available_at.isoformat(),
        "observed_at": proof.observed_at.isoformat(),
        "http_status": proof.http_status,
        "body_size_bytes": proof.body_size_bytes,
        "body_complete": True,
        "status_mapping_sha256": proof.status_mapping_sha256,
        "trusted_vendor_status_codes": list(proof.trusted_vendor_status_codes),
        "reported_status_code": proof.reported_status_code,
        "close_policy_content_hash": proof.close_policy_content_hash,
        "close_calendar_content_hash": proof.close_calendar_content_hash,
        "close_calendar_source_hash": proof.close_calendar_source_hash,
        "close_calendar_session_state": proof.close_calendar_session_state,
        "close_calendar_available_at": proof.close_calendar_available_at.isoformat(),
        "close_execution_rule_content_hash": proof.close_execution_rule_content_hash,
        "close_market_content_hash": proof.close_market_content_hash,
        "close_market_source_hash": proof.close_market_source_hash,
        "close_market_session_state": proof.close_market_session_state,
        "close_market_security_state_basis": proof.close_market_security_state_basis,
        "close_bundle_content_hash": proof.close_bundle_content_hash,
        "close_decision_content_hash": proof.close_decision_content_hash,
        "close_policy_available_from": proof.close_policy_available_from.isoformat(),
        "close_policy_available_until": proof.close_policy_available_until.isoformat(),
        "close_usage_ttl_seconds": proof.close_usage_ttl_seconds,
        "close_usage_deadline": proof.close_usage_deadline.isoformat(),
        "close_calendar_valid_until": proof.close_calendar_valid_until.isoformat(),
        "close_market_valid_until": proof.close_market_valid_until.isoformat(),
        "business_timezone_name": proof.business_timezone_name,
        "business_date_deadline": proof.business_date_deadline.isoformat(),
        "source_max_timestamp_age_seconds": proof.source_max_timestamp_age_seconds,
        "source_age_deadline": proof.source_age_deadline.isoformat(),
        "policy_deadlines": [item.isoformat() for item in proof.policy_deadlines],
        "policy_acceptance_deadline": proof.policy_acceptance_deadline.isoformat(),
        "source_available_at": None,
        "source_valid_until": None,
    }


def _timestamp_clock_evidence_proof_payload(
    proof: PortfolioRiskTimestampSnapshotProof,
) -> PortfolioRiskTimestampSnapshotClockProofPayload:
    """Render source observation and independently derived acceptance bounds."""

    return {
        "scope": proof.scope,
        "source_kind": proof.source_kind,
        "clock_evidence_mode": proof.clock_evidence_mode,
        "profile_key": proof.profile_key,
        "profile_version": proof.profile_version,
        "profile_content_hash": proof.profile_content_hash,
        "policy_snapshot_id": proof.policy_snapshot_id,
        "policy_snapshot_hash": proof.policy_snapshot_hash,
        "policy_content_sha256": proof.policy_content_sha256,
        "policy_known_at": proof.policy_known_at.isoformat(),
        "policy_effective_at": proof.policy_effective_at.isoformat(),
        "source_reference_hash": proof.source_reference_hash,
        "account_id": proof.account_id,
        "asset_code": proof.asset_code,
        "security_id": proof.security_id,
        "source_id": proof.source_id,
        "source_record_id": proof.source_record_id,
        "capture_id": proof.capture_id,
        "original_body_sha256": proof.original_body_sha256,
        "as_of": proof.as_of.isoformat(),
        "business_date": proof.business_date.isoformat(),
        "execution_session": proof.execution_session.isoformat(),
        "known_at": proof.known_at.isoformat(),
        "proven_available_at": proof.proven_available_at.isoformat(),
        "observed_at": proof.observed_at.isoformat(),
        "http_status": proof.http_status,
        "body_size_bytes": proof.body_size_bytes,
        "body_complete": True,
        "business_timezone_name": proof.business_timezone_name,
        "source_max_timestamp_age_seconds": proof.source_max_timestamp_age_seconds,
        "timestamp_age_deadline": proof.timestamp_age_deadline.isoformat(),
        "market_window_deadline": proof.market_window_deadline.isoformat(),
        "policy_deadlines": [item.isoformat() for item in proof.policy_deadlines],
        "policy_acceptance_deadline": proof.policy_acceptance_deadline.isoformat(),
        "valuation_quantity_unit": proof.valuation_quantity_unit,
        "valuation_price_unit": proof.valuation_price_unit,
        "capacity_window_kind": proof.capacity_window_kind,
        "capacity_window_start": (
            proof.capacity_window_start.isoformat()
            if proof.capacity_window_start is not None
            else None
        ),
        "capacity_window_end": (
            proof.capacity_window_end.isoformat() if proof.capacity_window_end is not None else None
        ),
        "capacity_window_sessions": proof.capacity_window_sessions,
        "capacity_volume_unit": proof.capacity_volume_unit,
        "capacity_amount_unit": proof.capacity_amount_unit,
        "capacity_measure": proof.capacity_measure,
        "capacity_policy_unit": proof.capacity_policy_unit,
        "source_available_at": None,
        "source_valid_until": None,
    }


__all__ = ("clock_evidence_proof_payload",)
